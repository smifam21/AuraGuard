# AuraGuard V10 — Snipe, Mute, Warn, and Dual Prefix Upgrade

import discord
from discord import app_commands
from discord.ext import commands, tasks

import os
import json
import random
import asyncio
import io
import copy

from datetime import datetime, timedelta, timezone
from PIL import Image, ImageDraw, ImageFont

# Load the token from the host environment first, then token.txt.
# token.txt should contain ONLY the Discord bot token, with no quotes or variable name.
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN and os.path.isfile("token.txt"):
    with open("token.txt", "r", encoding="utf-8") as token_file:
        TOKEN = token_file.read().strip()

DATA_FILE = "auraguard_data.json"

AURA_PURPLE = 0x8A2BE2
AURA_GREEN = 0x2ECC71
AURA_RED = 0xE74C3C
AURA_YELLOW = 0xF1C40F
AURA_BLUE = 0x3498DB
FOOTER = "AuraGuard • Powered by Aura"

if not TOKEN:
    raise RuntimeError(
        "Discord bot token not found. Set DISCORD_TOKEN in your host variables "
        "or place your token in token.txt beside this script."
    )

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
intents.invites = True

async def get_prefix(bot, message):
    # Support both Aura's prefix and the short legacy prefix.
    return commands.when_mentioned_or("A!", "!")(bot, message)


bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None)

DEFAULT_DATA = {
    "settings": {},
    "warnings": {},
    "giveaways": {},
    "giveaway_entries": {},
    "giveaway_history": {},
    "giveaway_blacklist": {},
    "ticket_claims": {},
    "automod": {},
    "invites": {},
    "member_invites": {},
    "levels": {},
    "message_stats": {}
}


def load_data():
    """Load persisted data defensively so a partial/corrupt file won't crash startup."""
    if not os.path.exists(DATA_FILE):
        return copy.deepcopy(DEFAULT_DATA)

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        if not isinstance(loaded, dict):
            raise ValueError("The data file must contain a JSON object.")

        for key, default_value in DEFAULT_DATA.items():
            if not isinstance(loaded.get(key), dict):
                loaded[key] = copy.deepcopy(default_value)

        # Repair known nested collections that are expected to be dictionaries/lists.
        for guild_id, settings in list(loaded["settings"].items()):
            if not isinstance(settings, dict):
                loaded["settings"][guild_id] = {}
        for guild_id, settings in list(loaded["automod"].items()):
            if not isinstance(settings, dict):
                loaded["automod"][guild_id] = {"enabled": False, "blocked_words": []}
            else:
                settings["enabled"] = bool(settings.get("enabled", False))
                words = settings.get("blocked_words", [])
                settings["blocked_words"] = words if isinstance(words, list) else []
        for key in ("giveaway_entries", "giveaway_history", "giveaway_blacklist",
                    "ticket_claims", "invites", "member_invites", "warnings", "levels", "message_stats"):
            if not isinstance(loaded.get(key), dict):
                loaded[key] = {}

        return loaded
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print("Data load error:", repr(error))
        # Preserve the damaged file for recovery rather than overwriting it automatically.
        return copy.deepcopy(DEFAULT_DATA)


data = load_data()


def save_data():
    try:
        with open(DATA_FILE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        os.replace(DATA_FILE + ".tmp", DATA_FILE)
    except Exception as e:
        print("Data save error:", e)


invite_cache = {}

# Keep only the most recent deleted/edited message per channel.
# These caches reset when the bot restarts.
snipe_cache = {}
editsnipe_cache = {}


def get_settings(guild_id):
    guild_id = str(guild_id)
    defaults = {
        "welcome_enabled": False,
        "welcome_channel": None,
        "welcome_message": "Welcome {user} to {server}! 🛡️",
        "welcome_image_enabled": True,
        "leave_enabled": False,
        "leave_channel": None,
        "leave_message": "{user} has left {server}. 👋",
        "ticket_category": None,
        "staff_role": None,
        "log_channel": None,
        "message_log_channel": None,
        "leveling_enabled": True,
        "levelup_channel": None,
        "invite_channel": None,
        "giveaway_bonus_roles": {}
    }
    current = data["settings"].get(guild_id)
    if not isinstance(current, dict):
        current = copy.deepcopy(defaults)
        data["settings"][guild_id] = current
        save_data()
    else:
        for key, value in defaults.items():
            if key not in current or (key == "giveaway_bonus_roles" and not isinstance(current[key], dict)):
                current[key] = copy.deepcopy(value)
    return current


def get_automod(guild_id):
    guild_id = str(guild_id)
    data["automod"].setdefault(guild_id, {"enabled": False, "blocked_words": []})
    return data["automod"][guild_id]


def get_invite_data(guild_id):
    guild_id = str(guild_id)
    data["invites"].setdefault(guild_id, {})
    return data["invites"][guild_id]


def get_member_invites(guild_id):
    guild_id = str(guild_id)
    data["member_invites"].setdefault(guild_id, {})
    return data["member_invites"][guild_id]

def get_giveaway_blacklist(guild_id):
    guild_id = str(guild_id)
    data["giveaway_blacklist"].setdefault(guild_id, [])
    return data["giveaway_blacklist"][guild_id]


def aura_embed(title, description="", color=AURA_PURPLE, emoji="🛡️"):
    embed = discord.Embed(
        title=f"{emoji} {title}",
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text=FOOTER)
    return embed


def is_staff(member):
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    role_id = get_settings(member.guild.id).get("staff_role")
    try:
        role_id = int(role_id) if role_id else None
    except (TypeError, ValueError):
        role_id = None
    role = member.guild.get_role(role_id) if role_id else None
    return bool(role and role in member.roles)


def apply_placeholders(text, member):
    return (
        text.replace("{user}", member.mention)
        .replace("{server}", member.guild.name)
        .replace("{member_count}", str(member.guild.member_count))
    )


def clean_message_content(content):
    return discord.utils.escape_markdown(content or "*No text content*")[:3500]


def make_unique_id(collection):
    while True:
        giveaway_id = str(random.randint(100000, 999999))
        if giveaway_id not in collection:
            return giveaway_id


# -------- CHANNEL HELPERS --------

def normalize_channel_id(channel_id):
    if channel_id is None:
        return None
    try:
        return int(channel_id)
    except (TypeError, ValueError):
        return None


async def get_saved_text_channel(guild, channel_id):
    channel_id = normalize_channel_id(channel_id)
    if channel_id is None:
        return None

    channel = guild.get_channel(channel_id)
    if isinstance(channel, discord.TextChannel):
        return channel

    try:
        channel = await guild.fetch_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            return channel
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass

    return None


async def get_saved_category(guild, channel_id):
    channel_id = normalize_channel_id(channel_id)
    if channel_id is None:
        return None

    channel = guild.get_channel(channel_id)
    if isinstance(channel, discord.CategoryChannel):
        return channel

    try:
        channel = await guild.fetch_channel(channel_id)
        if isinstance(channel, discord.CategoryChannel):
            return channel
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass

    return None


async def resolve_channel(guild, channel):
    if isinstance(channel, discord.TextChannel):
        return channel
    return await get_saved_text_channel(guild, getattr(channel, "id", None))


async def resolve_category(guild, channel):
    if isinstance(channel, discord.CategoryChannel):
        return channel
    return await get_saved_category(guild, getattr(channel, "id", None))


async def require_text_channel(interaction, channel):
    resolved = await resolve_channel(interaction.guild, channel)
    if resolved is None:
        await interaction.response.send_message(
            "❌ Please select a normal text channel.",
            ephemeral=True
        )
        return None
    return resolved


# -------- LOGGING --------

async def send_log(guild, title, description, color=AURA_PURPLE):
    """Send a moderation/member/automod event to the configured log channel."""
    if guild is None:
        return
    settings = get_settings(guild.id)
    channel = await get_saved_text_channel(guild, settings.get("log_channel"))
    if channel is None:
        return
    try:
        await channel.send(embed=aura_embed(title, description, color, "📋"))
    except (discord.Forbidden, discord.HTTPException) as error:
        print("Moderation log send error:", repr(error))


async def send_message_log(guild, title, description, color=AURA_BLUE):
    """Send message edit/delete logs to the separately configured message log channel."""
    if guild is None:
        return
    settings = get_settings(guild.id)
    channel = await get_saved_text_channel(guild, settings.get("message_log_channel"))
    if channel is None:
        return
    try:
        await channel.send(embed=aura_embed(title, description, color, "💬"))
    except (discord.Forbidden, discord.HTTPException) as error:
        print("Message log send error:", repr(error))


def get_level_record(guild_id, user_id):
    guild_levels = data["levels"].setdefault(str(guild_id), {})
    record = guild_levels.setdefault(str(user_id), {"xp": 0, "level": 0, "last_xp_at": 0})
    if not isinstance(record, dict):
        record = {"xp": 0, "level": 0, "last_xp_at": 0}
        guild_levels[str(user_id)] = record
    record.setdefault("xp", 0)
    record.setdefault("level", 0)
    record.setdefault("last_xp_at", 0)
    return record


def xp_needed(level):
    return 100 * (max(0, int(level)) + 1) ** 2


# -------- WELCOME CARD --------

def get_message_record(guild_id, user_id):
    guild = data["message_stats"].setdefault(str(guild_id), {})
    return guild.setdefault(str(user_id), {"total": 0, "today": 0, "today_key": "", "week": 0, "week_key": "", "month": 0, "month_key": ""})


def update_message_record(guild_id, user_id):
    """Count a human member's message in any guild text channel, resetting periods lazily."""
    record = get_message_record(guild_id, user_id)
    now = datetime.now(timezone.utc)
    day_key = now.strftime("%Y-%m-%d")
    week_key = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    month_key = now.strftime("%Y-%m")
    if record.get("today_key") != day_key:
        record["today_key"], record["today"] = day_key, 0
    if record.get("week_key") != week_key:
        record["week_key"], record["week"] = week_key, 0
    if record.get("month_key") != month_key:
        record["month_key"], record["month"] = month_key, 0
    record["today"] = int(record.get("today", 0)) + 1
    record["week"] = int(record.get("week", 0)) + 1
    record["month"] = int(record.get("month", 0)) + 1
    record["total"] = int(record.get("total", 0)) + 1


# One active Guess the Number game per channel.
gtn_games = {}


def get_font(size, bold=False):
    path = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    )
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


async def create_welcome_card(member):
    image = Image.new("RGB", (1000, 360), (18, 8, 32))
    draw = ImageDraw.Draw(image)
    draw.ellipse((650, -100, 1150, 400), fill=(85, 25, 145))
    draw.rounded_rectangle((20, 20, 980, 340), radius=30, outline=(170, 90, 255), width=5)

    avatar = Image.open(io.BytesIO(await member.display_avatar.read())).convert("RGB")
    avatar = avatar.resize((190, 190))
    mask = Image.new("L", (190, 190), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 189, 189), fill=255)
    image.paste(avatar, (70, 85), mask)

    draw.text((300, 70), "WELCOME TO", font=get_font(38, True), fill=(190, 145, 255))
    draw.text((300, 125), member.display_name[:22], font=get_font(56, True), fill="white")
    draw.text((302, 210), member.guild.name[:35], font=get_font(30), fill=(225, 215, 240))
    draw.text((302, 265), f"Member #{member.guild.member_count}", font=get_font(26), fill=(190, 145, 255))

    output = io.BytesIO()
    image.save(output, "PNG")
    output.seek(0)
    return discord.File(output, filename="auraguard-welcome.png")


async def send_welcome(member, channel, inviter=None):
    settings = get_settings(member.guild.id)
    description = apply_placeholders(settings["welcome_message"], member)
    if inviter:
        description += f"\n\n📨 **Invited by:** {inviter.mention}"

    embed = aura_embed("Welcome!", description, AURA_PURPLE, "👋")

    try:
        if settings.get("welcome_image_enabled", True):
            welcome_file = await create_welcome_card(member)
            embed.set_image(url="attachment://auraguard-welcome.png")
            await channel.send(embed=embed, file=welcome_file)
        else:
            await channel.send(embed=embed)
    except Exception as e:
        print("Welcome send error:", repr(e))
        try:
            await channel.send(embed=embed)
        except Exception:
            pass


# -------- TICKETS --------

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary,
                       emoji="🎫", custom_id="auraguard_open_ticket")
    async def open_ticket(self, interaction, button):
        guild = interaction.guild
        user = interaction.user
        settings = get_settings(guild.id)

        for channel in guild.text_channels:
            if channel.topic == f"AURAGUARD_TICKET_OWNER={user.id}":
                await interaction.response.send_message(
                    f"🎫 You already have a ticket: {channel.mention}", ephemeral=True
                )
                return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )
        }

        role_id = normalize_channel_id(settings.get("staff_role"))
        role = guild.get_role(role_id) if role_id else None
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )

        category = await get_saved_category(guild, settings.get("ticket_category"))

        safe_name = "".join(c for c in user.name.lower() if c.isalnum() or c == "-")[:80]
        channel = await guild.create_text_channel(
            f"ticket-{safe_name}",
            category=category,
            overwrites=overwrites,
            topic=f"AURAGUARD_TICKET_OWNER={user.id}"
        )

        await channel.send(
            content=user.mention,
            embed=aura_embed(
                "Ticket Opened",
                "A staff member will help you soon.\n\nUse the buttons below.",
                AURA_PURPLE, "🎫"
            ),
            view=TicketControls()
        )
        await interaction.response.send_message(f"🎫 Your ticket: {channel.mention}", ephemeral=True)


class TicketControls(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success,
                       emoji="🙋", custom_id="auraguard_claim_ticket")
    async def claim_ticket(self, interaction, button):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Only staff can claim tickets.", ephemeral=True)
            return

        channel_id = str(interaction.channel.id)
        current = data["ticket_claims"].get(channel_id)

        if current and current != interaction.user.id:
            await interaction.response.send_message(
                f"❌ Already claimed by <@{current}>.", ephemeral=True
            )
            return

        data["ticket_claims"][channel_id] = interaction.user.id
        save_data()
        await interaction.response.send_message(f"🙋 Ticket claimed by {interaction.user.mention}.")

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger,
                       emoji="🔒", custom_id="auraguard_close_ticket")
    async def close_ticket(self, interaction, button):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Only staff can close tickets.", ephemeral=True)
            return
        await interaction.response.send_message("🔒 Closing ticket...")
        await asyncio.sleep(1)
        data["ticket_claims"].pop(str(interaction.channel.id), None)
        save_data()
        await interaction.channel.delete()


# -------- ADVANCED GIVEAWAYS --------

def giveaway_id_exists(giveaway_id):
    return giveaway_id in data["giveaways"] or giveaway_id in data["giveaway_history"]


def make_giveaway_id():
    while True:
        giveaway_id = str(random.randint(100000, 999999))
        if not giveaway_id_exists(giveaway_id):
            return giveaway_id


def get_giveaway_entries(giveaway_id):
    entries = data["giveaway_entries"].get(giveaway_id)
    if not isinstance(entries, dict):
        entries = {}
        data["giveaway_entries"][giveaway_id] = entries
    return entries


def weighted_winners(entries, amount, excluded=None):
    excluded = {str(x) for x in (excluded or [])}
    if not isinstance(entries, dict):
        entries = {}
    amount = max(0, int(amount))
    pool = {}
    for user_id, raw_weight in entries.items():
        try:
            weight = int(raw_weight)
        except (TypeError, ValueError, OverflowError):
            continue
        if weight > 0 and str(user_id) not in excluded:
            pool[str(user_id)] = weight
    result = []
    while pool and len(result) < amount:
        winner = random.choices(
            list(pool.keys()),
            weights=list(pool.values()),
            k=1
        )[0]
        result.append(winner)
        pool.pop(winner, None)
    return result


def get_bonus_entries(member):
    bonus_roles = get_settings(member.guild.id).get("giveaway_bonus_roles", {})
    total = 0
    for role in member.roles:
        try:
            total += max(0, int(bonus_roles.get(str(role.id), 0)))
        except (TypeError, ValueError):
            pass
    return total


def giveaway_required_role_text(giveaway):
    role_id = giveaway.get("required_role")
    return f"<@&{role_id}>" if role_id else "None"


def giveaway_embed(giveaway_id, giveaway):
    entries = get_giveaway_entries(giveaway_id)
    end = datetime.fromisoformat(giveaway["end_time"])
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    return aura_embed(
        "GIVEAWAY",
        f"╭─ <a:GiveawayInvictus:1559042120377962507> **Prize:** {giveaway['prize']}\n"
        f"├─ 🏆 **Winners:** {giveaway['winners']}\n"
        f"├─ 👥 **Participants:** {len(entries)}\n"
        f"├─ 🎟️ **Total Entries:** {sum(int(v) for v in entries.values())}\n"
        f"├─ 🔐 **Required Role:** {giveaway_required_role_text(giveaway)}\n"
        f"├─ 👤 **Hosted by:** <@{giveaway['created_by']}>\n"
        f"├─<:Clock:1559311727504662749> **Ends:** <t:{int(end.timestamp())}:R>\n"
        f"╰─ 🆔 **ID:** `{giveaway_id}`\n\n"
        "🎉 **Click Enter Giveaway to participate!**",
        AURA_PURPLE,
        "🎉"
    )


class GiveawayView(discord.ui.View):
    def __init__(self, giveaway_id):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id

        enter_button = discord.ui.Button(
            label="Enter Giveaway",
            emoji="🎉",
            style=discord.ButtonStyle.success,
            custom_id=f"auraguard_giveaway_enter_{giveaway_id}"
        )
        enter_button.callback = self.enter
        self.add_item(enter_button)

        entries_button = discord.ui.Button(
            label="My Entries",
            emoji="🎟️",
            style=discord.ButtonStyle.primary,
            custom_id=f"auraguard_giveaway_entries_{giveaway_id}"
        )
        entries_button.callback = self.my_entries
        self.add_item(entries_button)

    async def enter(self, interaction):
        giveaway = data["giveaways"].get(self.giveaway_id)
        if (not interaction.guild or not giveaway
                or str(giveaway.get("guild")) != str(interaction.guild.id)):
            await interaction.response.send_message(
                "❌ This giveaway is no longer active in this server.", ephemeral=True
            )
            return

        try:
            end_time = datetime.fromisoformat(giveaway["end_time"])
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)
        except (KeyError, TypeError, ValueError):
            await interaction.response.send_message(
                "❌ This giveaway has invalid saved timing data. Please contact staff.",
                ephemeral=True
            )
            return
        if datetime.now(timezone.utc) >= end_time:
            await interaction.response.send_message(
                "⏰ This giveaway has ended.", ephemeral=True
            )
            return

        if str(interaction.user.id) in get_giveaway_blacklist(interaction.guild.id):
            await interaction.response.send_message(
                "🚫 You are blacklisted from AuraGuard giveaways.", ephemeral=True
            )
            return

        required_role_id = giveaway.get("required_role")
        if required_role_id:
            try:
                role = interaction.guild.get_role(int(required_role_id))
            except (TypeError, ValueError):
                role = None
            if role is None:
                await interaction.response.send_message(
                    "❌ The required giveaway role no longer exists. Please contact staff.",
                    ephemeral=True
                )
                return
            if role not in interaction.user.roles:
                await interaction.response.send_message(
                    f"🔐 You need the {role.mention} role to enter this giveaway.",
                    ephemeral=True
                )
                return

        entries = get_giveaway_entries(self.giveaway_id)
        user_id = str(interaction.user.id)
        if user_id in entries:
            await interaction.response.send_message(
                f"❌ You're already entered with **{entries[user_id]} entries**.",
                ephemeral=True
            )
            return

        amount = 1 + get_bonus_entries(interaction.user)
        entries[user_id] = amount
        save_data()
        await interaction.response.send_message(
            f"🎉 You're entered with **{amount} {'entry' if amount == 1 else 'entries'}**!",
            ephemeral=True
        )

    async def my_entries(self, interaction):
        amount = get_giveaway_entries(self.giveaway_id).get(
            str(interaction.user.id), 0
        )
        await interaction.response.send_message(
            f"🎟️ You have **{amount} {'entry' if amount == 1 else 'entries'}**.",
            ephemeral=True
        )


async def finish_giveaway(guild, channel, giveaway_id):
    giveaway = data["giveaways"].get(giveaway_id)
    if not giveaway:
        return

    entries = get_giveaway_entries(giveaway_id)
    try:
        winner_count = max(1, int(giveaway.get("winners", 1)))
    except (TypeError, ValueError, OverflowError):
        winner_count = 1
    winners = weighted_winners(entries, winner_count)

    history = dict(giveaway)
    history["entries"] = dict(entries)
    history["winners_list"] = winners
    history["ended_at"] = datetime.now(timezone.utc).isoformat()
    history.setdefault("rerolls", [])

    data["giveaway_history"][giveaway_id] = history
    data["giveaways"].pop(giveaway_id, None)
    data["giveaway_entries"].pop(giveaway_id, None)
    save_data()

    if channel is None:
        return

    if winners:
        winner_text = " ".join(f"<@{winner}>" for winner in winners)
        await channel.send(embed=aura_embed(
            "Giveaway Winner!",
            f"🎁 **Prize:** {history['prize']}\n\n"
            f"🏆 **Congratulations:** {winner_text}",
            AURA_GREEN,
            "🏆"
        ))
    else:
        await channel.send(embed=aura_embed(
            "Giveaway Ended",
            f"🎁 **Prize:** {history['prize']}\n\nNobody entered.",
            AURA_YELLOW,
            "🎉"
        ))


# -------- COMMAND GROUPS --------

welcome_group = app_commands.Group(name="welcome", description="Manage welcome messages.")
leave_group = app_commands.Group(name="leave", description="Manage leave messages.")
tickets_group = app_commands.Group(name="tickets", description="Manage tickets.")
giveaway_group = app_commands.Group(name="giveaway", description="Advanced AuraGuard giveaways.")
automod_group = app_commands.Group(name="automod", description="Manage AutoMod.")


# -------- GIVEAWAY COMMANDS --------

@giveaway_group.command(name="start", description="Start an advanced giveaway.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_start(
    interaction: discord.Interaction,
    prize: str,
    minutes: int,
    winners: int = 1,
    required_role: discord.Role = None
):
    if minutes < 1 or winners < 1:
        await interaction.response.send_message(
            "❌ Minutes and winners must be at least 1.", ephemeral=True
        )
        return
    if minutes > 525600 or winners > 100:
        await interaction.response.send_message(
            "❌ Giveaways can last at most 365 days and have at most 100 winners.",
            ephemeral=True
        )
        return
    prize = prize.strip()
    if not prize or len(prize) > 200:
        await interaction.response.send_message(
            "❌ The prize must be between 1 and 200 characters.", ephemeral=True
        )
        return

    giveaway_id = make_giveaway_id()
    end = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    data["giveaways"][giveaway_id] = {
        "guild": interaction.guild.id,
        "channel": interaction.channel.id,
        "prize": prize,
        "winners": winners,
        "end_time": end.isoformat(),
        "created_by": interaction.user.id,
        "required_role": required_role.id if required_role else None
    }
    data["giveaway_entries"][giveaway_id] = {}
    save_data()

    await interaction.response.send_message(
        embed=giveaway_embed(giveaway_id, data["giveaways"][giveaway_id]),
        view=GiveawayView(giveaway_id)
    )


@giveaway_group.command(name="entries", description="Check your entries in a giveaway.")
async def giveaway_entries(interaction: discord.Interaction, giveaway_id: str):
    amount = get_giveaway_entries(giveaway_id).get(str(interaction.user.id), 0)
    await interaction.response.send_message(
        f"🎟️ You have **{amount} {'entry' if amount == 1 else 'entries'}**.",
        ephemeral=True
    )


@giveaway_group.command(name="addentries", description="Add entries to a member.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_addentries(
    interaction: discord.Interaction,
    giveaway_id: str,
    member: discord.Member,
    amount: int
):
    giveaway = data["giveaways"].get(giveaway_id)
    if not giveaway or giveaway["guild"] != interaction.guild.id or amount < 1:
        await interaction.response.send_message("❌ Invalid giveaway or amount.", ephemeral=True)
        return

    entries = get_giveaway_entries(giveaway_id)
    user_id = str(member.id)
    entries[user_id] = entries.get(user_id, 0) + amount
    save_data()
    await interaction.response.send_message(
        f"➕ {member.mention} now has **{entries[user_id]} entries**.",
        ephemeral=True
    )


@giveaway_group.command(name="removeentries", description="Remove entries from a member.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_removeentries(
    interaction: discord.Interaction,
    giveaway_id: str,
    member: discord.Member,
    amount: int
):
    giveaway = data["giveaways"].get(giveaway_id)
    if not giveaway or giveaway["guild"] != interaction.guild.id or amount < 1:
        await interaction.response.send_message("❌ Invalid giveaway or amount.", ephemeral=True)
        return

    entries = get_giveaway_entries(giveaway_id)
    user_id = str(member.id)
    new_amount = max(0, entries.get(user_id, 0) - amount)
    if new_amount:
        entries[user_id] = new_amount
    else:
        entries.pop(user_id, None)
    save_data()
    await interaction.response.send_message(
        f"➖ Removed **{amount} entries** from {member.mention}.", ephemeral=True
    )


@giveaway_group.command(name="bonusrole", description="Set bonus giveaway entries for a role.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_bonusrole(
    interaction: discord.Interaction,
    role: discord.Role,
    amount: int
):
    if amount < 0:
        await interaction.response.send_message("❌ Amount cannot be negative.", ephemeral=True)
        return
    get_settings(interaction.guild.id)["giveaway_bonus_roles"][str(role.id)] = amount
    save_data()
    await interaction.response.send_message(
        f"🎟️ {role.mention} now gives **+{amount} bonus entries**.", ephemeral=True
    )


@giveaway_group.command(name="removebonusrole", description="Remove a giveaway bonus role.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_removebonusrole(interaction: discord.Interaction, role: discord.Role):
    get_settings(interaction.guild.id)["giveaway_bonus_roles"].pop(str(role.id), None)
    save_data()
    await interaction.response.send_message("✅ Giveaway bonus role removed.", ephemeral=True)


@giveaway_group.command(name="bonusroles", description="Show giveaway bonus roles.")
async def giveaway_bonusroles(interaction: discord.Interaction):
    bonus_roles = get_settings(interaction.guild.id)["giveaway_bonus_roles"]
    description = "\n".join(
        f"<@&{role_id}> — **+{amount} entries**"
        for role_id, amount in bonus_roles.items()
    ) or "No bonus roles configured."
    await interaction.response.send_message(
        embed=aura_embed("Giveaway Bonus Roles", description, AURA_PURPLE, "🎟️"),
        ephemeral=True
    )


@giveaway_group.command(name="blacklist", description="Blacklist a member from giveaways.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_blacklist(interaction: discord.Interaction, member: discord.Member):
    blacklist = get_giveaway_blacklist(interaction.guild.id)
    if str(member.id) not in blacklist:
        blacklist.append(str(member.id))
        save_data()
    await interaction.response.send_message(
        f"🚫 {member.mention} is giveaway blacklisted.", ephemeral=True
    )


@giveaway_group.command(name="unblacklist", description="Remove a member from giveaway blacklist.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_unblacklist(interaction: discord.Interaction, member: discord.Member):
    blacklist = get_giveaway_blacklist(interaction.guild.id)
    if str(member.id) in blacklist:
        blacklist.remove(str(member.id))
        save_data()
    await interaction.response.send_message(
        f"✅ {member.mention} was removed from the giveaway blacklist.", ephemeral=True
    )


@giveaway_group.command(name="list", description="Show active giveaways.")
async def giveaway_list(interaction: discord.Interaction):
    active = [
        (giveaway_id, giveaway)
        for giveaway_id, giveaway in data["giveaways"].items()
        if giveaway["guild"] == interaction.guild.id
    ]

    if not active:
        description = "No active giveaways."
    else:
        lines = []
        for giveaway_id, giveaway in active[:15]:
            end = datetime.fromisoformat(giveaway["end_time"])
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            lines.append(
                f"🎁 `{giveaway_id}` — **{giveaway['prize']}**\n"
                f"└ Ends <t:{int(end.timestamp())}:R>"
            )
        description = "\n\n".join(lines)

    await interaction.response.send_message(
        embed=aura_embed("Active Giveaways", description, AURA_PURPLE, "📋"),
        ephemeral=True
    )


@giveaway_group.command(name="end", description="End a giveaway early.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_end(interaction: discord.Interaction, giveaway_id: str):
    giveaway = data["giveaways"].get(giveaway_id)
    if not giveaway or giveaway["guild"] != interaction.guild.id:
        await interaction.response.send_message("❌ Giveaway not found.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    channel = await get_saved_text_channel(interaction.guild, giveaway["channel"])
    await finish_giveaway(interaction.guild, channel, giveaway_id)
    await interaction.followup.send("✅ Giveaway ended.", ephemeral=True)


@giveaway_group.command(name="reroll", description="Reroll winners for a finished giveaway.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_reroll(
    interaction: discord.Interaction,
    giveaway_id: str,
    winners: int = 1
):
    history = data["giveaway_history"].get(giveaway_id)
    if not history or history["guild"] != interaction.guild.id:
        await interaction.response.send_message("❌ Finished giveaway not found.", ephemeral=True)
        return
    if winners < 1:
        await interaction.response.send_message("❌ Winners must be at least 1.", ephemeral=True)
        return

    new_winners = weighted_winners(
        history.get("entries", {}),
        winners
    )
    reroll = {
        "winners": new_winners,
        "at": datetime.now(timezone.utc).isoformat(),
        "rerolled_by": interaction.user.id
    }
    history.setdefault("rerolls", []).append(reroll)
    history["winners_list"] = new_winners
    save_data()

    winner_text = " ".join(f"<@{user_id}>" for user_id in new_winners) or "Nobody"
    await interaction.response.send_message(embed=aura_embed(
        "Giveaway Rerolled!",
        f"🎁 **Prize:** {history['prize']}\n\n"
        f"🏆 **New Winners:** {winner_text}",
        AURA_GREEN,
        "🔄"
    ))


# -------- INVITE COMMANDS --------

class InviteChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="Select the invite notification text channel",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text]
        )

    async def callback(self, interaction: discord.Interaction):
        selected_channel = self.values[0]
        channel = await get_saved_text_channel(interaction.guild, selected_channel.id)

        if channel is None:
            await interaction.response.edit_message(
                content="❌ I couldn't access that text channel.",
                view=None
            )
            return

        get_settings(interaction.guild.id)["invite_channel"] = int(channel.id)
        save_data()
        await interaction.response.edit_message(
            content=f"📨 Invite channel set to {channel.mention}.",
            view=None
        )


class InviteChannelSetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(InviteChannelSelect())


@bot.tree.command(name="setinvitechannel", description="Set the channel for invite notifications.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setinvitechannel(interaction: discord.Interaction):
    await interaction.response.send_message(
        "📨 Select the **invite notification text channel** below.",
        view=InviteChannelSetupView(),
        ephemeral=True
    )


@bot.tree.command(name="invites", description="Check invite information.")
async def invites(interaction, member: discord.Member = None):
    member = member or interaction.user
    invite_data = get_invite_data(interaction.guild.id)
    user_data = invite_data.get(str(member.id), {
        "total": 0, "regular": 0, "bonus": 0, "fake": 0, "left": 0
    })

    await interaction.response.send_message(embed=aura_embed(
        "Invite Information",
        f"👤 **Member:** {member.mention}\n"
        f"📨 **Total Invites:** **{user_data.get('total', 0)}**\n"
        f"✅ **Regular:** **{user_data.get('regular', 0)}**\n"
        f"➕ **Bonus:** **{user_data.get('bonus', 0)}**\n"
        f"👋 **Left:** **{user_data.get('left', 0)}**",
        AURA_PURPLE, "📨"
    ))


@bot.tree.command(name="inviteleaderboard", description="Show the invite leaderboard.")
async def inviteleaderboard(interaction):
    invite_data = get_invite_data(interaction.guild.id)
    sorted_invites = sorted(
        invite_data.items(),
        key=lambda item: item[1].get("total", 0),
        reverse=True
    )

    if not sorted_invites:
        await interaction.response.send_message(embed=aura_embed(
            "Invite Leaderboard",
            "No invite data has been recorded yet.",
            AURA_PURPLE, "🏆"
        ))
        return

    lines = []
    for position, (user_id, user_data) in enumerate(sorted_invites[:10], 1):
        lines.append(
            f"**{position}.** <@{user_id}> — **{user_data.get('total', 0)} invites**"
        )

    await interaction.response.send_message(embed=aura_embed(
        "Invite Leaderboard", "\n".join(lines), AURA_PURPLE, "🏆"
    ))


def invite_record(invite_data, member_id):
    return invite_data.setdefault(str(member_id), {
        "total": 0, "regular": 0, "bonus": 0, "fake": 0, "left": 0
    })


@bot.tree.command(name="setinvite", description="Set a member's invite amount.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setinvite(interaction, member: discord.Member, amount: int):
    if amount < 0:
        await interaction.response.send_message("❌ Invite amount cannot be negative.", ephemeral=True)
        return

    user_data = invite_record(get_invite_data(interaction.guild.id), member.id)
    old_amount = user_data.get("total", 0)
    difference = amount - old_amount
    user_data["total"] = amount
    if difference > 0:
        user_data["bonus"] = user_data.get("bonus", 0) + difference
    save_data()

    await interaction.response.send_message(embed=aura_embed(
        "Invites Updated",
        f"👤 **Member:** {member.mention}\n"
        f"📨 **Previous:** **{old_amount}**\n"
        f"✨ **New Total:** **{amount} invites**",
        AURA_GREEN, "📨"
    ))


@bot.tree.command(name="addinvites", description="Add invites to a member.")
@app_commands.checks.has_permissions(manage_guild=True)
async def addinvites(interaction, member: discord.Member, amount: int):
    if amount < 1:
        await interaction.response.send_message("❌ Amount must be at least 1.", ephemeral=True)
        return
    user_data = invite_record(get_invite_data(interaction.guild.id), member.id)
    user_data["total"] += amount
    user_data["bonus"] += amount
    save_data()
    await interaction.response.send_message(
        f"➕ Added **{amount} invites** to {member.mention}.\n"
        f"📨 They now have **{user_data['total']} invites**."
    )


@bot.tree.command(name="removeinvites", description="Remove invites from a member.")
@app_commands.checks.has_permissions(manage_guild=True)
async def removeinvites(interaction, member: discord.Member, amount: int):
    if amount < 1:
        await interaction.response.send_message("❌ Amount must be at least 1.", ephemeral=True)
        return
    user_data = invite_record(get_invite_data(interaction.guild.id), member.id)
    user_data["total"] = max(0, user_data.get("total", 0) - amount)
    save_data()
    await interaction.response.send_message(
        f"➖ Removed **{amount} invites** from {member.mention}.\n"
        f"📨 They now have **{user_data['total']} invites**."
    )


@bot.tree.command(name="resetinvites", description="Reset a member's invites.")
@app_commands.checks.has_permissions(manage_guild=True)
async def resetinvites(interaction, member: discord.Member):
    get_invite_data(interaction.guild.id)[str(member.id)] = {
        "total": 0, "regular": 0, "bonus": 0, "fake": 0, "left": 0
    }
    save_data()
    await interaction.response.send_message(f"🔄 Reset all invite data for {member.mention}.")


# -------- SETTINGS --------

@bot.tree.command(name="ping", description="Check AuraGuard latency.")
async def ping(interaction):
    await interaction.response.send_message(embed=aura_embed(
        "AuraGuard Online",
        f"⚡ Pong!\nLatency: **{round(bot.latency * 1000)}ms**",
        AURA_PURPLE, "⚡"
    ), ephemeral=True)


@bot.tree.command(name="setstaffrole", description="Set the staff role.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setstaffrole(interaction, role: discord.Role):
    get_settings(interaction.guild.id)["staff_role"] = int(role.id)
    save_data()
    await interaction.response.send_message(
        f"🛡️ Staff role set to {role.mention}.", ephemeral=True
    )


@bot.tree.command(name="setlogchannel", description="Set the moderation log channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setlogchannel(interaction: discord.Interaction, log_channel: discord.TextChannel):
    channel = await require_text_channel(interaction, log_channel)
    if channel is None:
        return
    get_settings(interaction.guild.id)["log_channel"] = int(channel.id)
    save_data()
    await interaction.response.send_message(
        f"📋 Log channel set to {channel.mention}.", ephemeral=True
    )


@bot.tree.command(name="setmessagelog", description="Set the message log channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setmessagelog(interaction: discord.Interaction, message_log_channel: discord.TextChannel):
    channel = await require_text_channel(interaction, message_log_channel)
    if channel is None:
        return
    get_settings(interaction.guild.id)["message_log_channel"] = int(channel.id)
    save_data()
    await interaction.response.send_message(
        f"💬 Message log set to {channel.mention}.", ephemeral=True
    )


@bot.tree.command(name="leveling", description="Turn the level system on or off.")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.choices(state=[
    app_commands.Choice(name="Enable", value="on"),
    app_commands.Choice(name="Disable", value="off")
])
async def leveling(interaction: discord.Interaction, state: app_commands.Choice[str]):
    get_settings(interaction.guild.id)["leveling_enabled"] = state.value == "on"
    save_data()
    await interaction.response.send_message(
        f"✨ Leveling **{ 'enabled' if state.value == 'on' else 'disabled' }**.", ephemeral=True
    )


@bot.tree.command(name="setlevelchannel", description="Choose where level-up messages appear.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setlevelchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    resolved = await require_text_channel(interaction, channel)
    if resolved is None:
        return
    get_settings(interaction.guild.id)["levelup_channel"] = int(resolved.id)
    save_data()
    await interaction.response.send_message(f"✨ Level-up messages will appear in {resolved.mention}.", ephemeral=True)


@bot.tree.command(name="rank", description="View your or another member's level and XP.")
async def rank(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    record = get_level_record(interaction.guild.id, member.id)
    level = int(record.get("level", 0))
    xp = int(record.get("xp", 0))
    needed = xp_needed(level)
    await interaction.response.send_message(embed=aura_embed(
        f"{member.display_name}'s Rank",
        f"👤 **Member:** {member.mention}\n⭐ **Level:** {level}\n✨ **Total XP:** {xp}\n📈 **Next level:** {max(0, needed - xp)} XP remaining",
        AURA_PURPLE, "🏆"
    ))


@bot.tree.command(name="leaderboard", description="Show the server's top levels.")
async def level_leaderboard(interaction: discord.Interaction):
    records = data["levels"].get(str(interaction.guild.id), {})
    ranked = sorted(records.items(), key=lambda pair: (int(pair[1].get("level", 0)), int(pair[1].get("xp", 0))), reverse=True)
    if not ranked:
        await interaction.response.send_message("No level data yet—chat to earn XP!")
        return
    lines = [f"**{i}.** <@{uid}> — Level **{int(rec.get('level', 0))}** ({int(rec.get('xp', 0))} XP)" for i, (uid, rec) in enumerate(ranked[:10], 1)]
    await interaction.response.send_message(embed=aura_embed("Level Leaderboard", "\n".join(lines), AURA_PURPLE, "🏆"))


# -------- LEVELS, MESSAGE STATS, GAMES, SAY, AND WHEEL --------


def make_rank_embed(member):
    record = get_level_record(member.guild.id, member.id)
    level = int(record.get("level", 0))
    xp = int(record.get("xp", 0))
    needed = xp_needed(level)
    embed = aura_embed(f"{member.display_name}'s Rank", f"👤 **Member:** {member.mention}\n⭐ **Level:** {level}\n✨ **XP:** {xp}\n📈 **Next level:** {max(0, needed - xp)} XP remaining", AURA_PURPLE, "🏆")
    embed.set_thumbnail(url=member.display_avatar.url)
    return embed


@bot.command(name="rank")
async def prefix_rank(ctx, member: discord.Member = None):
    member = member or ctx.author
    await ctx.send(embed=make_rank_embed(member))


@bot.command(name="leaderboard", aliases=["levels", "lb"])
async def prefix_level_leaderboard(ctx):
    records = data["levels"].get(str(ctx.guild.id), {})
    ranked = sorted(records.items(), key=lambda pair: (int(pair[1].get("level", 0)), int(pair[1].get("xp", 0))), reverse=True)
    if not ranked:
        await ctx.send("No level data yet—chat to earn XP!")
        return
    lines = []
    for i, (uid, rec) in enumerate(ranked[:10], 1):
        lines.append(f"**{i}.** <@{uid}> — Level **{int(rec.get('level', 0))}** ({int(rec.get('xp', 0))} XP)")
    await ctx.send(embed=aura_embed("Level Leaderboard", "\n".join(lines), AURA_PURPLE, "🏆"))


@bot.command(name="a.m", aliases=["am", "gm"])
async def prefix_message_stats(ctx, member: discord.Member = None):
    member = member or ctx.author
    record = get_message_record(ctx.guild.id, member.id)
    # Roll periods forward even if the member hasn't spoken since the period changed.
    now = datetime.now(timezone.utc)
    day_key = now.strftime("%Y-%m-%d")
    week_key = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    month_key = now.strftime("%Y-%m")
    today = int(record.get("today", 0)) if record.get("today_key") == day_key else 0
    week = int(record.get("week", 0)) if record.get("week_key") == week_key else 0
    month = int(record.get("month", 0)) if record.get("month_key") == month_key else 0
    embed = discord.Embed(title=f"{member.display_name}'s Messages", description=f"**Messages Sent:**\n\nToday: **{today:,}**\nThis Week: **{week:,}**\nThis Month: **{month:,}**\nTotal: **{int(record.get('total', 0)):,}**", color=AURA_BLUE, timestamp=now)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="AuraGuard • Message statistics")
    await ctx.send(embed=embed)


@bot.tree.command(name="am", description="View today's, weekly, monthly, and total message counts.")
async def slash_message_stats(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    record = get_message_record(interaction.guild.id, member.id)
    now = datetime.now(timezone.utc)
    day_key = now.strftime("%Y-%m-%d")
    week_key = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    month_key = now.strftime("%Y-%m")
    today = int(record.get("today", 0)) if record.get("today_key") == day_key else 0
    week = int(record.get("week", 0)) if record.get("week_key") == week_key else 0
    month = int(record.get("month", 0)) if record.get("month_key") == month_key else 0
    embed = discord.Embed(title=f"{member.display_name}'s Messages", description=f"**Messages Sent:**\n\nToday: **{today:,}**\nThis Week: **{week:,}**\nThis Month: **{month:,}**\nTotal: **{int(record.get('total', 0)):,}**", color=AURA_BLUE, timestamp=now)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="AuraGuard • Message statistics")
    await interaction.response.send_message(embed=embed)


@bot.command(name="say")
async def prefix_say(ctx, *, text: str):
    if not is_staff(ctx.author):
        await ctx.reply("❌ Only server staff can use this command.", mention_author=False)
        return
    if len(text) > 1800:
        await ctx.reply("Please keep the message under 1,800 characters.", mention_author=False)
        return
    await ctx.send(text, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="say", description="Make AuraGuard send a message (staff only).")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(text="The message AuraGuard should send")
async def slash_say(interaction: discord.Interaction, text: str):
    if len(text) > 1800:
        await interaction.response.send_message("Please keep the message under 1,800 characters.", ephemeral=True)
        return
    await interaction.response.send_message("Message sent.", ephemeral=True)
    await interaction.channel.send(text, allowed_mentions=discord.AllowedMentions.none())


@bot.command(name="gtn", aliases=["guessnumber", "guess"])
async def prefix_gtn(ctx, minimum: int = 1, maximum: int = 100):
    """Start Guess the Number; players submit guesses by typing a number in chat."""
    if ctx.channel.id in gtn_games:
        await ctx.send("🎯 A game is already running in this channel. Type a number to guess!")
        return
    if minimum >= maximum:
        await ctx.send("The minimum must be smaller than the maximum. Example: `!gtn 1 100`.")
        return
    if maximum - minimum > 1_000_000:
        await ctx.send("Please choose a range no larger than 1,000,000 numbers.")
        return
    gtn_games[ctx.channel.id] = {
        "number": random.randint(minimum, maximum),
        "minimum": minimum,
        "maximum": maximum,
        "guesses": 0,
        "started_by": ctx.author.id,
        "last_hint": None,
    }
    await ctx.send(
        f"🎯 **Guess The Number is starting!**\n"
        f"I'm thinking of a number from **{minimum:,} to {maximum:,}**.\n"
        "Type your guess as a number directly in this channel. First correct guess wins!"
    )


@bot.command(name="gtnstop", aliases=["stopgame"])
async def prefix_gtn_stop(ctx):
    if not is_staff(ctx.author):
        await ctx.reply("❌ Only server staff can stop a game.", mention_author=False)
        return
    game = gtn_games.pop(ctx.channel.id, None)
    await ctx.send(
        f"🛑 Game ended. The number was **{game['number']:,}**."
        if game else "There isn't a game running here."
    )


@bot.tree.command(name="gtn", description="Start a Guess The Number event in this channel.")
@app_commands.describe(minimum="Lowest possible number", maximum="Highest possible number")
async def slash_gtn(interaction: discord.Interaction, minimum: int = 1, maximum: int = 100):
    if interaction.channel_id in gtn_games:
        await interaction.response.send_message("🎯 A game is already running in this channel. Type a number to guess!", ephemeral=True)
        return
    if minimum >= maximum:
        await interaction.response.send_message("The minimum must be smaller than the maximum.", ephemeral=True)
        return
    if maximum - minimum > 1_000_000:
        await interaction.response.send_message("Please choose a range no larger than 1,000,000 numbers.", ephemeral=True)
        return
    gtn_games[interaction.channel_id] = {
        "number": random.randint(minimum, maximum),
        "minimum": minimum,
        "maximum": maximum,
        "guesses": 0,
        "started_by": interaction.user.id,
        "last_hint": None,
    }
    await interaction.response.send_message(
        f"🎯 **Guess The Number is starting!**\n"
        f"I'm thinking of a number from **{minimum:,} to {maximum:,}**.\n"
        "Type your guess as a number directly in this channel. First correct guess wins!"
    )


@bot.command(name="hint")
async def prefix_gtn_hint(ctx):
    game = gtn_games.get(ctx.channel.id)
    if not game:
        await ctx.send("There isn't a Guess The Number game running in this channel.")
        return
    number = game["number"]
    if game.get("last_hint") == "parity":
        hint = "The number is **even**." if number % 2 == 0 else "The number is **odd**."
        game["last_hint"] = "parity-used"
    else:
        midpoint = (game["minimum"] + game["maximum"]) // 2
        hint = f"The number is **above {midpoint:,}**." if number > midpoint else f"The number is **{midpoint:,} or below**."
        game["last_hint"] = "parity"
    await ctx.send("💡 **Hint:** " + hint)


@bot.tree.command(name="hint", description="Get a hint for the active number game.")
async def slash_gtn_hint(interaction: discord.Interaction):
    game = gtn_games.get(interaction.channel_id)
    if not game:
        await interaction.response.send_message("There isn't a Guess The Number game running in this channel.", ephemeral=True)
        return
    number = game["number"]
    if game.get("last_hint") == "parity":
        hint = "The number is **even**." if number % 2 == 0 else "The number is **odd**."
        game["last_hint"] = "parity-used"
    else:
        midpoint = (game["minimum"] + game["maximum"]) // 2
        hint = f"The number is **above {midpoint:,}**." if number > midpoint else f"The number is **{midpoint:,} or below**."
        game["last_hint"] = "parity"
    await interaction.response.send_message("💡 **Hint:** " + hint)


@bot.command(name="range")
async def prefix_gtn_range(ctx):
    game = gtn_games.get(ctx.channel.id)
    if game:
        await ctx.send(f"🔢 Current range: **{game['minimum']:,}–{game['maximum']:,}**. Type a number here to guess.")
    else:
        await ctx.send("There isn't a Guess The Number game running in this channel.")


@bot.tree.command(name="range", description="Show the active Guess The Number range.")
async def slash_gtn_range(interaction: discord.Interaction):
    game = gtn_games.get(interaction.channel_id)
    if game:
        await interaction.response.send_message(f"🔢 Current range: **{game['minimum']:,}–{game['maximum']:,}**. Type a number here to guess.", ephemeral=True)
    else:
        await interaction.response.send_message("There isn't a Guess The Number game running in this channel.", ephemeral=True)


@bot.tree.command(name="stopgame", description="Stop the active Guess The Number game (staff only).")
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_gtn_stop(interaction: discord.Interaction):
    game = gtn_games.pop(interaction.channel_id, None)
    if game:
        await interaction.response.send_message(f"🛑 Game ended. The number was **{game['number']:,}**.")
    else:
        await interaction.response.send_message("There isn't a game running in this channel.", ephemeral=True)


@bot.command(name="wheel", aliases=["spinwheel", "spin"])
async def prefix_wheel(ctx, *, names: str):
    entries = [item.strip() for item in names.split(",") if item.strip()]
    if not 2 <= len(entries) <= 50:
        await ctx.send("Give me 2–50 names separated by commas. Example: `!wheel Alex, Sam, Taylor`")
        return
    winner = random.choice(entries)
    await ctx.send(embed=aura_embed("The Wheel Has Spoken!", "🎡 Entries: " + ", ".join(entries) + f"\n\n🏆 **Winner: {winner}**", AURA_GREEN, "🎡"))


@bot.tree.command(name="wheel", description="Randomly pick a name from a list of 2–50 entries.")
@app_commands.describe(names="Names separated by commas")
async def slash_wheel(interaction: discord.Interaction, names: str):
    entries = [item.strip() for item in names.split(",") if item.strip()]
    if not 2 <= len(entries) <= 50:
        await interaction.response.send_message("Give me 2–50 names separated by commas.", ephemeral=True)
        return
    winner = random.choice(entries)
    await interaction.response.send_message(embed=aura_embed("The Wheel Has Spoken!", "🎡 Entries: " + ", ".join(entries) + f"\n\n🏆 **Winner: {winner}**", AURA_GREEN, "🎡"))


# -------- AUTOMOD --------

@automod_group.command(name="enable", description="Enable AutoMod.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_enable(interaction):
    get_automod(interaction.guild.id)["enabled"] = True
    save_data()
    await interaction.response.send_message("🛡️ AutoMod enabled.", ephemeral=True)


@automod_group.command(name="disable", description="Disable AutoMod.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_disable(interaction):
    get_automod(interaction.guild.id)["enabled"] = False
    save_data()
    await interaction.response.send_message("🔴 AutoMod disabled.", ephemeral=True)


@automod_group.command(name="addword", description="Add a blocked word.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_addword(interaction, word: str):
    automod = get_automod(interaction.guild.id)
    word = word.strip()
    if not word:
        await interaction.response.send_message("❌ Invalid word.", ephemeral=True)
        return
    if word.lower() in [item.lower() for item in automod["blocked_words"]]:
        await interaction.response.send_message("❌ That word is already blocked.", ephemeral=True)
        return
    automod["blocked_words"].append(word)
    save_data()
    await interaction.response.send_message(f"🛡️ Added `{word}`.", ephemeral=True)


@automod_group.command(name="removeword", description="Remove a blocked word.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_removeword(interaction, word: str):
    automod = get_automod(interaction.guild.id)
    match = next((item for item in automod["blocked_words"] if item.lower() == word.lower()), None)
    if not match:
        await interaction.response.send_message("❌ That word is not blocked.", ephemeral=True)
        return
    automod["blocked_words"].remove(match)
    save_data()
    await interaction.response.send_message(f"✅ Removed `{match}`.", ephemeral=True)


# -------- MODERATION --------

async def hierarchy_check(interaction, member):
    if member == interaction.user or member == interaction.guild.owner:
        await interaction.response.send_message("❌ You can't moderate that member.", ephemeral=True)
        return False
    if interaction.user != interaction.guild.owner and member.top_role >= interaction.user.top_role:
        await interaction.response.send_message("❌ That member has an equal or higher role.", ephemeral=True)
        return False
    if interaction.guild.me and member.top_role >= interaction.guild.me.top_role:
        await interaction.response.send_message("❌ My role is not high enough.", ephemeral=True)
        return False
    return True


@bot.tree.command(name="kick", description="Kick a member.")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await hierarchy_check(interaction, member):
        return
    try:
        await member.kick(reason=f"{reason} (by {interaction.user})")
    except discord.Forbidden:
        await interaction.response.send_message("❌ I can't kick that member. Check my Kick Members permission and role position.", ephemeral=True)
        return
    except discord.HTTPException:
        await interaction.response.send_message("❌ Discord couldn't kick that member. Please try again.", ephemeral=True)
        return
    await interaction.response.send_message(f"👢 Kicked {member.mention}. Reason: **{reason}**")
    await send_log(
        interaction.guild, "Member Kicked",
        f"Member: {member.mention} (`{member.id}`)\nModerator: {interaction.user.mention}\nReason: {reason}",
        AURA_RED
    )


@bot.tree.command(name="ban", description="Ban a member.")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await hierarchy_check(interaction, member):
        return
    await member.ban(reason=reason)
    await interaction.response.send_message(f"🔨 Banned {member.mention}.")
    await send_log(
        interaction.guild, "Member Banned",
        f"Member: {member.mention}\nModerator: {interaction.user.mention}\nReason: {reason}",
        AURA_RED
    )


@bot.tree.command(name="unban", description="Unban a user by ID.")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction, user_id: str):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
        await interaction.response.send_message(f"🔓 **{user}** has been unbanned.")
    except Exception:
        await interaction.response.send_message("❌ User not found or not banned.", ephemeral=True)


@bot.tree.command(name="timeout", description="Timeout a member.")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout(interaction, member: discord.Member, minutes: int, reason: str = "No reason provided"):
    if minutes < 1 or minutes > 40320:
        await interaction.response.send_message(
            "❌ Choose between 1 minute and 28 days.", ephemeral=True
        )
        return
    if not await hierarchy_check(interaction, member):
        return
    await member.timeout(discord.utils.utcnow() + timedelta(minutes=minutes), reason=reason)
    await interaction.response.send_message(
        f"⏳ {member.mention} timed out for **{minutes} minutes**."
    )
    await send_log(interaction.guild, "Member Timed Out", f"Member: {member.mention} (`{member.id}`)\nModerator: {interaction.user.mention}\nDuration: {minutes} minutes\nReason: {reason}", AURA_YELLOW)


@bot.tree.command(name="untimeout", description="Remove a timeout.")
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout(interaction, member: discord.Member):
    if not await hierarchy_check(interaction, member):
        return
    await member.timeout(None)
    await interaction.response.send_message(f"🔓 Removed {member.mention}'s timeout.")
    await send_log(interaction.guild, "Timeout Removed", f"Member: {member.mention} (`{member.id}`)\nModerator: {interaction.user.mention}", AURA_GREEN)


# -------- PREFIX MODERATION COMMANDS --------


def parse_duration(value: str) -> timedelta:
    """Parse compact durations like 1s, 10m, 2h, or 1d; reject word forms such as 1sec."""
    value = value.strip().lower()
    if len(value) < 2 or not value[:-1].isdigit():
        raise ValueError("Use a duration like 1s, 10m, 2h, or 1d (number + s/m/h/d; do not use words like sec).")
    amount = int(value[:-1])
    unit = value[-1]
    units = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
    if amount < 1 or unit not in units:
        raise ValueError("Use a positive duration like 1s, 10m, 2h, or 1d. Use only s/m/h/d, not words like sec.")
    duration = timedelta(**{units[unit]: amount})
    if duration > timedelta(days=28):
        raise ValueError("Discord timeouts cannot be longer than 28 days.")
    return duration


def prefix_can_moderate(ctx, member: discord.Member) -> bool:
    if member == ctx.author or member == ctx.guild.owner:
        return False
    if ctx.author != ctx.guild.owner and member.top_role >= ctx.author.top_role:
        return False
    if ctx.guild.me and member.top_role >= ctx.guild.me.top_role:
        return False
    return True


@bot.command(name="mute", aliases=["timeout"])
@commands.has_permissions(moderate_members=True)
async def prefix_mute(ctx, member: discord.Member, *, reason_and_duration: str = ""):
    """Timeout a member. Format: A!mute @member reason 1s (duration must be last)."""
    if not prefix_can_moderate(ctx, member):
        await ctx.send("❌ You can't mute that member because of role hierarchy or self-moderation rules.")
        return

    # Keep the reason as free-form text and parse only the final token as duration.
    parts = reason_and_duration.strip().rsplit(maxsplit=1)
    if len(parts) != 2:
        await ctx.send("❌ Use: `A!mute @user reason 1s` — put the duration last (e.g. `1s`, `10m`, `2h`, `1d`).")
        return
    reason, duration = parts[0].strip(), parts[1].strip()
    if not reason:
        await ctx.send("❌ Please provide a reason before the duration. Example: `A!mute @user spamming 1s`.")
        return

    try:
        delta = parse_duration(duration)
    except ValueError as exc:
        await ctx.send(f"❌ {exc} Put the duration at the end, like `A!mute @user spamming 1s`.")
        return
    try:
        until = discord.utils.utcnow() + delta
        await member.timeout(until, reason=f"{reason} (by {ctx.author})")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to timeout that member. Check my role and permissions.")
        return
    except discord.HTTPException:
        await ctx.send("❌ Discord couldn't apply the timeout. Please try again.")
        return
    await ctx.send(embed=aura_embed(
        "Member Muted",
        f"**Member:** {member.mention}\n**Duration:** {duration}\n**Reason:** {reason}\n**Moderator:** {ctx.author.mention}",
        AURA_YELLOW,
        "🔇"
    ))
    await send_log(ctx.guild, "Member Muted", f"Member: {member.mention}\nModerator: {ctx.author.mention}\nDuration: {duration}\nReason: {reason}", AURA_YELLOW)


@bot.command(name="unmute", aliases=["untimeout"])
@commands.has_permissions(moderate_members=True)
async def prefix_unmute(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    """Remove a timeout. Example: !unmute @member."""
    if not prefix_can_moderate(ctx, member):
        await ctx.send("❌ You can't unmute that member because of role hierarchy or self-moderation rules.")
        return
    try:
        await member.timeout(None, reason=f"{reason} (by {ctx.author})")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to remove that timeout.")
        return
    except discord.HTTPException:
        await ctx.send("❌ Discord couldn't remove the timeout. Please try again.")
        return
    await ctx.send(embed=aura_embed(
        "Member Unmuted",
        f"**Member:** {member.mention}\n**Moderator:** {ctx.author.mention}\n**Reason:** {reason}",
        AURA_GREEN,
        "🔊"
    ))
    await send_log(ctx.guild, "Member Unmuted", f"Member: {member.mention}\nModerator: {ctx.author.mention}\nReason: {reason}", AURA_GREEN)


@bot.command(name="warn")
@commands.has_permissions(moderate_members=True)
async def prefix_warn(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    """Record a warning. Example: A!warn @member Please follow the rules."""
    if member == ctx.author or member == ctx.guild.owner:
        await ctx.send("❌ You can't warn yourself or the server owner.")
        return
    if ctx.author != ctx.guild.owner and member.top_role >= ctx.author.top_role:
        await ctx.send("❌ You can't warn a member with an equal or higher role.")
        return
    guild_id, user_id = str(ctx.guild.id), str(member.id)
    data["warnings"].setdefault(guild_id, {})
    data["warnings"][guild_id].setdefault(user_id, [])
    data["warnings"][guild_id][user_id].append({
        "reason": reason,
        "moderator_id": ctx.author.id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    save_data()
    count = len(data["warnings"][guild_id][user_id])
    await ctx.send(embed=aura_embed(
        "Warning Added",
        f"**Member:** {member.mention}\n**Reason:** {reason}\n**Moderator:** {ctx.author.mention}\n**Total warnings:** {count}",
        AURA_YELLOW,
        "⚠️"
    ))
    await send_log(ctx.guild, "Member Warned", f"Member: {member.mention}\nModerator: {ctx.author.mention}\nReason: {reason}\nTotal warnings: {count}", AURA_YELLOW)


@bot.command(name="warnings", aliases=["warns"])
@commands.has_permissions(moderate_members=True)
async def prefix_warnings(ctx, member: discord.Member):
    """Show a member's warnings. Example: !warnings @member."""
    records = data["warnings"].get(str(ctx.guild.id), {}).get(str(member.id), [])
    if not records:
        await ctx.send(f"✅ {member.mention} has no warnings recorded.")
        return
    lines = []
    for index, record in enumerate(records[-10:], start=max(1, len(records) - 9)):
        moderator_id = record.get("moderator_id")
        lines.append(f"**{index}.** {record.get('reason', 'No reason provided')} — moderator <@{moderator_id}>" if moderator_id else f"**{index}.** {record.get('reason', 'No reason provided')}")
    await ctx.send(embed=aura_embed(
        f"Warnings for {member.display_name}",
        "\n".join(lines) + f"\n\nTotal: **{len(records)}** warning(s).",
        AURA_YELLOW,
        "⚠️"
    ))


@bot.command(name="clearwarnings", aliases=["clearwarns"])
@commands.has_permissions(moderate_members=True)
async def prefix_clearwarnings(ctx, member: discord.Member):
    """Clear a member's warning history. Example: !clearwarnings @member."""
    guild_warnings = data["warnings"].setdefault(str(ctx.guild.id), {})
    previous = len(guild_warnings.get(str(member.id), []))
    guild_warnings.pop(str(member.id), None)
    save_data()
    await ctx.send(f"🧹 Cleared **{previous}** warning(s) for {member.mention}.")
    await send_log(ctx.guild, "Warnings Cleared", f"Member: {member.mention}\nModerator: {ctx.author.mention}\nRemoved warnings: {previous}", AURA_GREEN)


@bot.command(name="snipe")
async def prefix_snipe(ctx):
    """Show the latest deleted message in this channel, if cached."""
    item = snipe_cache.get(ctx.channel.id)
    if not item:
        await ctx.send("Nothing to snipe in this channel yet.", delete_after=8)
        return
    embed = aura_embed(
        "Deleted Message",
        f"**Author:** {item['author']}\n**When:** <t:{int(item['timestamp'])}:R>\n\n{item['content'] or '*No text content*'}",
        AURA_RED,
        "🗑️"
    )
    await ctx.send(embed=embed)


@bot.command(name="editsnipe", aliases=["esnipe"])
async def prefix_editsnipe(ctx):
    """Show the latest edited message's previous text in this channel."""
    item = editsnipe_cache.get(ctx.channel.id)
    if not item:
        await ctx.send("Nothing to editsnipe in this channel yet.", delete_after=8)
        return
    embed = aura_embed(
        "Edited Message",
        f"**Author:** {item['author']}\n**When:** <t:{int(item['timestamp'])}:R>\n\n**Before:**\n{item['before'] or '*No text content*'}\n\n**After:**\n{item['after'] or '*No text content*'}",
        AURA_YELLOW,
        "✏️"
    )
    await ctx.send(embed=embed)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use that command.")
    elif isinstance(error, (commands.MissingRequiredArgument, commands.MemberNotFound, commands.BadArgument)):
        await ctx.send(f"⚠️ Check the command arguments. Try `{ctx.prefix}help` if a help command is configured.")
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.send("❌ AuraGuard needs additional Discord permissions to do that.")
    else:
        print("Prefix command error:", repr(error))
        await ctx.send("❌ Something went wrong while running that command.")




# -------- HELP COMMANDS --------

HELP_TEXT = (
    "**🛡️ General**\n"
    "`/help` — Show this command guide\n"
    "`/ping` — Check AuraGuard latency\n\n"
    "**📈 Leveling & Stats**\n"
    "`/leveling` — Turn leveling on or off\n"
    "`/setlevelchannel` — Choose where level-up messages appear\n"
    "`/rank` or `A!rank` — View a member's level and XP\n"
    "`/leaderboard` or `A!leaderboard` — Show top levels\n"
    "`/am` or `A!a.m` — View message statistics\n\n"
    "**🎯 Games**\n"
    "`/gtn` — Start Guess The Number; players type guesses in chat\n"
    "`/hint` — Get a hint for the active game\n"
    "`/range` — Show the active game's range\n"
    "`/stopgame` — Stop a game (staff only)\n"
    "`/wheel` — Pick a random name from a list\n\n"
    "**🛡️ Moderation & Server Setup**\n"
    "`/kick`, `/ban`, `/unban` — Moderation\n"
    "`/timeout`, `/untimeout` — Manage timeouts\n"
    "Prefix mute format: `A!mute @member reason 1s` (duration last; use `s`, `m`, `h`, or `d`, not `sec`).\n"
    "`/setstaffrole` — Set the staff role\n"
    "`/setlogchannel` — Set the moderation log channel\n"
    "`/setmessagelog` — Set the message log channel\n\n"
    "**💬 Prefix commands**\n"
    "AuraGuard supports `A!` and `!` prefixes for commands that have prefix versions.\n"
    "Some commands are staff-only. Use slash-command suggestions to see available options."
)


@bot.tree.command(name="help", description="Show AuraGuard's command guide.")
async def slash_help(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=aura_embed("AuraGuard Help", HELP_TEXT, AURA_PURPLE, "📖"),
        ephemeral=True
    )


@bot.command(name="help", aliases=["commands", "cmds"])
async def prefix_help(ctx):
    await ctx.send(embed=aura_embed("AuraGuard Help", HELP_TEXT, AURA_PURPLE, "📖"))


# -------- EVENTS --------

@bot.event
async def on_ready():
    print("=" * 45)
    print(f"AuraGuard V10 online as {bot.user}")
    print(f"Bot ID: {bot.user.id}")
    print("=" * 45)

    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="over your server 🛡️"
        )
    )

    if not getattr(bot, "_auraguard_views_loaded", False):
        bot.add_view(TicketView())
        bot.add_view(TicketControls())
        for giveaway_id in list(data["giveaways"]):
            bot.add_view(GiveawayView(giveaway_id))
        bot._auraguard_views_loaded = True

    for guild in bot.guilds:
        try:
            invites_list = await guild.invites()
            invite_cache[guild.id] = {
                invite.code: invite.uses for invite in invites_list
            }
        except Exception as e:
            print(f"Could not load invites for {guild.name}: {e}")

    if not giveaway_loop.is_running():
        giveaway_loop.start()

    # Sync slash-command definitions once per process startup. This refreshes
    # Discord's registered option signatures when commands have changed.
    if not getattr(bot, "_auraguard_startup_commands_synced", False):
        try:
            synced = await bot.tree.sync()
            bot._auraguard_startup_commands_synced = True
            print(f"Synced {len(synced)} top-level slash commands.")
        except Exception as e:
            print("Slash command sync error:", repr(e))


@bot.event
async def on_member_join(member):
    guild = member.guild
    inviter = None

    try:
        old_invites = invite_cache.get(guild.id, {})
        new_invites = await guild.invites()

        for invite in new_invites:
            old_uses = old_invites.get(invite.code, 0)
            if invite.uses and invite.uses > old_uses:
                inviter = invite.inviter
                break

        invite_cache[guild.id] = {
            invite.code: invite.uses for invite in new_invites
        }
    except Exception as e:
        print("Invite tracking error:", e)

    if inviter and inviter.id != member.id:
        inviter_data = invite_record(get_invite_data(guild.id), inviter.id)
        inviter_data["total"] += 1
        inviter_data["regular"] += 1
        get_member_invites(guild.id)[str(member.id)] = inviter.id
        save_data()

        settings = get_settings(guild.id)
        invite_channel = await get_saved_text_channel(
            guild, settings.get("invite_channel")
        )

        if invite_channel:
            try:
                await invite_channel.send(embed=aura_embed(
                    "New Invite!",
                    f"👋 **Member:** {member.mention}\n\n"
                    f"📨 **Invited By:** {inviter.mention}\n\n"
                    f"📊 **Total Invites:** **{inviter_data['total']}**",
                    AURA_GREEN, "📨"
                ))
            except Exception:
                pass

        await send_log(
            guild, "Member Joined",
            f"👤 **Member:** {member.mention}\n"
            f"📨 **Invited By:** {inviter.mention}\n"
            f"📊 **Their Invites:** **{inviter_data['total']}**",
            AURA_GREEN
        )
    else:
        await send_log(
            guild, "Member Joined",
            f"👤 **Member:** {member.mention}\n📨 **Inviter:** Unknown",
            AURA_GREEN
        )

    settings = get_settings(guild.id)
    if settings.get("welcome_enabled"):
        channel = await get_saved_text_channel(
            guild, settings.get("welcome_channel")
        )

        if channel:
            try:
                await send_welcome(member, channel, inviter)
            except Exception as e:
                print("[WELCOME ERROR]", repr(e))
        else:
            print(
                "[WELCOME ERROR] Could not find saved welcome channel:",
                settings.get("welcome_channel")
            )


@bot.event
async def on_member_remove(member):
    guild = member.guild
    inviter_id = get_member_invites(guild.id).pop(str(member.id), None)

    if inviter_id:
        inviter_data = get_invite_data(guild.id).get(str(inviter_id))
        if inviter_data:
            inviter_data["total"] = max(0, inviter_data.get("total", 0) - 1)
            inviter_data["regular"] = max(0, inviter_data.get("regular", 0) - 1)
            inviter_data["left"] = inviter_data.get("left", 0) + 1
            save_data()

    settings = get_settings(guild.id)
    if settings.get("leave_enabled"):
        channel = await get_saved_text_channel(
            guild, settings.get("leave_channel")
        )
        if channel:
            try:
                await channel.send(embed=aura_embed(
                    "Member Left",
                    apply_placeholders(settings["leave_message"], member),
                    AURA_YELLOW, "🚪"
                ))
            except (discord.Forbidden, discord.HTTPException) as error:
                print("Leave message send error:", repr(error))

    await send_log(
        guild, "Member Left",
        f"Member: {member}\nID: `{member.id}`",
        AURA_YELLOW
    )


@bot.event
async def on_invite_create(invite):
    try:
        invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses
    except Exception:
        pass


@bot.event
async def on_invite_delete(invite):
    try:
        invite_cache.setdefault(invite.guild.id, {}).pop(invite.code, None)
    except Exception:
        pass


@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    # Guess The Number accepts plain numeric messages in the channel, like the dedicated GTN bot.
    active_game = gtn_games.get(message.channel.id)
    if active_game and message.content.strip().isdigit():
        guess = int(message.content.strip())
        minimum, maximum = active_game["minimum"], active_game["maximum"]
        if minimum <= guess <= maximum:
            active_game["guesses"] += 1
            if guess == active_game["number"]:
                gtn_games.pop(message.channel.id, None)
                await message.channel.send(
                    f"🎉 {message.author.mention} guessed **{guess:,}** correctly in **{active_game['guesses']}** guesses!"
                )
            elif guess < active_game["number"]:
                await message.channel.send(f"⬆️ {message.author.mention} guessed **{guess:,}** — too low! Guess higher.")
            else:
                await message.channel.send(f"⬇️ {message.author.mention} guessed **{guess:,}** — too high! Guess lower.")
        else:
            await message.channel.send(f"Choose a number between **{minimum:,} and {maximum:,}**.")

    # Count every human message across all guild channels. Periods reset lazily by UTC date/week/month.
    update_message_record(message.guild.id, message.author.id)
    save_data()

    # Award XP at most once per minute per member to discourage spam farming.
    settings = get_settings(message.guild.id)
    if settings.get("leveling_enabled", True) and message.content.strip():
        record = get_level_record(message.guild.id, message.author.id)
        now_ts = datetime.now(timezone.utc).timestamp()
        if now_ts - float(record.get("last_xp_at", 0)) >= 60:
            old_level = int(record.get("level", 0))
            record["xp"] = int(record.get("xp", 0)) + random.randint(15, 25)
            record["last_xp_at"] = now_ts
            while record["xp"] >= xp_needed(record["level"]):
                record["level"] = int(record["level"]) + 1
            if int(record["level"]) > old_level:
                target = await get_saved_text_channel(message.guild, settings.get("levelup_channel"))
                target = target or message.channel
                try:
                    await target.send(embed=aura_embed(
                        "Level Up!",
                        f"🎉 {message.author.mention} reached **Level {record['level']}**! Keep chatting to earn more XP.",
                        AURA_GREEN, "⭐"
                    ))
                except (discord.Forbidden, discord.HTTPException) as error:
                    print("Level-up message error:", repr(error))
            save_data()

    automod = get_automod(message.guild.id)

    if automod.get("enabled"):
        lower_content = message.content.lower()
        for word in automod.get("blocked_words", []):
            if word.lower() in lower_content:
                try:
                    await message.delete()
                except (discord.Forbidden, discord.HTTPException) as error:
                    print("AutoMod couldn't delete a blocked message:", repr(error))
                    return

                try:
                    await message.channel.send(
                        f"⚠️ {message.author.mention}, that message contains a blocked word.",
                        delete_after=5,
                        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)
                    )
                except (discord.Forbidden, discord.HTTPException) as error:
                    print("AutoMod notice send error:", repr(error))

                await send_log(
                    message.guild, "AutoMod Action",
                    f"Member: {message.author.mention}\nChannel: {message.channel.mention}",
                    AURA_RED
                )
                return

    await bot.process_commands(message)


@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild:
        return
    snipe_cache[message.channel.id] = {
        "author": str(message.author),
        "content": clean_message_content(message.content)[:3500],
        "timestamp": datetime.now(timezone.utc).timestamp(),
    }
    await send_message_log(
        message.guild, "Message Deleted",
        f"**Author:** {message.author.mention} (`{message.author.id}`)\n**Channel:** {message.channel.mention}\n**Content:**\n{clean_message_content(message.content)[:3000]}",
        AURA_RED
    )


@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild or before.content == after.content:
        return
    editsnipe_cache[before.channel.id] = {
        "author": str(before.author),
        "before": clean_message_content(before.content)[:1600],
        "after": clean_message_content(after.content)[:1600],
        "timestamp": datetime.now(timezone.utc).timestamp(),
    }
    await send_message_log(
        before.guild, "Message Edited",
        f"**Author:** {before.author.mention} (`{before.author.id}`)\n**Channel:** {before.channel.mention}\n**Before:**\n{clean_message_content(before.content)[:1500]}\n\n**After:**\n{clean_message_content(after.content)[:1500]}",
        AURA_YELLOW
    )


@tasks.loop(seconds=15)
async def giveaway_loop():
    now = datetime.now(timezone.utc)

    for giveaway_id, giveaway in list(data["giveaways"].items()):
        try:
            end = datetime.fromisoformat(giveaway["end_time"])
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        if now >= end:
            guild = bot.get_guild(giveaway["guild"])
            channel = await get_saved_text_channel(
                guild, giveaway["channel"]
            ) if guild else None

            try:
                await finish_giveaway(guild, channel, giveaway_id)
            except Exception as e:
                print("Giveaway error:", e)


for group in [welcome_group, leave_group, tickets_group, giveaway_group, automod_group]:
    bot.tree.add_command(group)


@bot.tree.error
async def on_app_command_error(interaction, error):
    print("Command error:", repr(error))

    original = getattr(error, "original", error)

    # Recover if Discord invokes an older cached slash-command signature.
    # This can affect any slash command whose options changed, not only welcome.
    if type(original).__name__ == "CommandSignatureMismatch":
        message = (
            "🔄 AuraGuard detected outdated slash-command settings and refreshed "
            "them with Discord. Please run the command again in a few seconds."
        )
        try:
            synced = await bot.tree.sync()
            bot._auraguard_startup_commands_synced = True
            print(
                "Recovered from CommandSignatureMismatch; synced "
                f"{len(synced)} top-level slash commands."
            )
        except Exception as sync_error:
            print("Slash-command recovery sync failed:", repr(sync_error))
            message = (
                "⚠️ AuraGuard's slash commands are out of sync, and I couldn't "
                "refresh them automatically. Check the host logs for the sync "
                "error, then restart the bot."
            )

        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except Exception as response_error:
            print("Could not send slash-command recovery notice:", repr(response_error))
        return

    if isinstance(error, app_commands.MissingPermissions):
        message = "❌ You don't have permission to use that command."
    elif isinstance(error, app_commands.TransformerError):
        message = (
            "❌ That option could not be processed. Please check your selection and try again."
        )
    elif isinstance(error, app_commands.CheckFailure):
        message = "❌ You don't have permission to use that command."
    elif isinstance(original, discord.Forbidden):
        message = "❌ AuraGuard is missing a Discord permission or its role is too low."
    elif isinstance(original, discord.NotFound):
        message = "❌ The requested Discord item could not be found. It may have been deleted."
    elif isinstance(original, discord.HTTPException):
        message = "❌ Discord couldn't complete that action. Please try again in a moment."
    else:
        message = "❌ Something went wrong while running that command. Check the bot host logs for details."

    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except Exception:
        pass


bot.run(TOKEN)