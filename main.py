# AuraGuard V8 — Updated Welcome & Channel Fix Version

import discord
from discord import app_commands
from discord.ext import commands, tasks

import os
import json
import random
import asyncio
import io

from datetime import datetime, timedelta, timezone
from PIL import Image, ImageDraw, ImageFont

TOKEN = os.getenv("DISCORD_TOKEN")
DATA_FILE = "auraguard_data.json"

AURA_PURPLE = 0x8A2BE2
AURA_GREEN = 0x2ECC71
AURA_RED = 0xE74C3C
AURA_YELLOW = 0xF1C40F
AURA_BLUE = 0x3498DB
FOOTER = "AuraGuard • Powered by Aura"

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from Railway Variables.")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
intents.invites = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None, max_messages=5000)

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
    "member_invites": {}
}


def load_data():
    if not os.path.exists(DATA_FILE):
        return json.loads(json.dumps(DEFAULT_DATA))
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        for key, value in DEFAULT_DATA.items():
            loaded.setdefault(key, value)
        return loaded
    except Exception as e:
        print("Data load error:", e)
        return json.loads(json.dumps(DEFAULT_DATA))


data = load_data()


def save_data():
    try:
        with open(DATA_FILE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        os.replace(DATA_FILE + ".tmp", DATA_FILE)
    except Exception as e:
        print("Data save error:", e)


invite_cache = {}

MAX_SNIPE_MESSAGES = 50
deleted_message_cache = {}


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
        "invite_channel": None,
        "giveaway_bonus_roles": {}
    }
    if guild_id not in data["settings"]:
        data["settings"][guild_id] = defaults.copy()
        save_data()
    else:
        for key, value in defaults.items():
            data["settings"][guild_id].setdefault(key, value)
    return data["settings"][guild_id]


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


def weighted_winners(entries, amount):
    pool = {user_id: int(weight) for user_id, weight in entries.items() if int(weight) > 0}
    result = []
    while pool and len(result) < amount:
        winner = random.choices(list(pool.keys()), weights=list(pool.values()), k=1)[0]
        result.append(winner)
        pool.pop(winner)
    return result


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



# -------- SNIPE / EVENT LOG HELPERS --------

def remember_deleted_message(message):
    if not message.guild:
        return

    guild_id = str(message.guild.id)
    deleted_message_cache.setdefault(guild_id, [])

    entry = {
        "message_id": int(message.id),
        "author_id": int(message.author.id),
        "author_name": str(message.author),
        "author_display_name": getattr(message.author, "display_name", str(message.author)),
        "author_avatar": str(getattr(message.author.display_avatar, "url", "")),
        "channel_id": int(message.channel.id),
        "channel_name": getattr(message.channel, "name", "unknown"),
        "content": message.content or "",
        "attachments": [a.url for a in message.attachments],
        "created_at": message.created_at.isoformat() if message.created_at else datetime.now(timezone.utc).isoformat(),
        "deleted_at": datetime.now(timezone.utc).isoformat()
    }

    deleted_message_cache[guild_id].insert(0, entry)
    deleted_message_cache[guild_id] = deleted_message_cache[guild_id][:MAX_SNIPE_MESSAGES]


def get_snipe_messages(guild_id):
    return deleted_message_cache.setdefault(str(guild_id), [])


def snipe_channel_text(channel):
    return channel.mention if hasattr(channel, "mention") else f"# {getattr(channel, 'name', 'unknown')}"


def snipe_content_text(content):
    content = content or "*No text content*"
    return discord.utils.escape_markdown(content)[:900]


def make_event_log_embed(title, member, channel, description, color, emoji):
    channel_text = snipe_channel_text(channel)
    embed = discord.Embed(
        title=f"{title} in {channel_text}",
        description=description[:3900],
        color=color,
        timestamp=datetime.now(timezone.utc)
    )

    try:
        embed.set_author(
            name=getattr(member, "display_name", str(member)),
            icon_url=str(member.display_avatar.url)
        )
    except Exception:
        embed.set_author(name=str(member))

    embed.set_footer(text=FOOTER)
    embed.add_field(
        name="ID",
        value=f"{member.id} | <t:{int(datetime.now(timezone.utc).timestamp())}:f>",
        inline=False
    )
    return embed


class SnipeView(discord.ui.View):
    def __init__(self, ctx, entries, page=0):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.entries = entries
        self.page = page
        self.per_page = 5
        self.total_pages = max(1, (len(entries) + self.per_page - 1) // self.per_page)
        self._update_buttons()

    def _update_buttons(self):
        self.previous.disabled = self.page <= 0
        self.next.disabled = self.page >= self.total_pages - 1

    async def interaction_check(self, interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "❌ Only the person who ran !snipe can use these buttons.",
                ephemeral=True
            )
            return False
        return True

    def build_embed(self):
        start = self.page * self.per_page
        current = self.entries[start:start + self.per_page]

        embed = discord.Embed(
            title="🕵️ Deleted Messages",
            description=f"Recent deleted messages • Page **{self.page + 1}/{self.total_pages}**",
            color=AURA_RED,
            timestamp=datetime.now(timezone.utc)
        )

        if not current:
            embed.description = "There are no deleted messages stored yet."
        else:
            for index, entry in enumerate(current, start=start + 1):
                content = snipe_content_text(entry.get("content"))
                channel = f"<#{entry['channel_id']}>"
                author = f"<@{entry['author_id']}>"
                deleted_at = datetime.fromisoformat(entry["deleted_at"])
                value = (
                    f"**Author:** {author}\n"
                    f"**Channel:** {channel}\n"
                    f"**Message:** {content}\n"
                    f"**Deleted:** <t:{int(deleted_at.timestamp())}:R>\n"
                    f"**Message ID:** {entry['message_id']}"
                )
                if entry.get("attachments"):
                    value += f"\n📎 **Attachments:** {len(entry['attachments'])}"

                embed.add_field(
                    name=f"{index}. {entry.get('author_display_name', entry.get('author_name', 'Unknown'))}",
                    value=value[:1024],
                    inline=False
                )

        embed.set_footer(text=f"AuraGuard • {len(self.entries)} stored deleted messages")
        return embed

    @discord.ui.button(label="Previous", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction, button):
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next", emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction, button):
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Clear", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def clear(self, interaction, button):
        if not is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ Only staff can clear the snipe history.",
                ephemeral=True
            )
            return

        deleted_message_cache[str(interaction.guild.id)] = []
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🗑️ Snipe History Cleared",
                description="The stored deleted-message history has been cleared.",
                color=AURA_GREEN
            ),
            view=None
        )


@bot.command(name="snipe")
async def prefix_snipe(ctx, page: int = 1):
    if not ctx.guild:
        return

    if not is_staff(ctx.author):
        await ctx.send(embed=prefix_moderation_embed(
            "Missing Permissions",
            "❌ You need staff permissions to use !snipe.",
            AURA_RED,
            "🔒"
        ))
        return

    entries = get_snipe_messages(ctx.guild.id)
    if not entries:
        await ctx.send(embed=aura_embed(
            "No Deleted Messages",
            "There are no deleted messages stored yet.",
            AURA_YELLOW,
            "🕵️"
        ))
        return

    view = SnipeView(ctx, entries, max(0, min(page - 1, (len(entries) - 1) // 5)))
    await ctx.send(embed=view.build_embed(), view=view)


@bot.command(name="snipeclear")
async def prefix_snipe_clear(ctx):
    if not ctx.guild or not is_staff(ctx.author):
        await ctx.send(embed=prefix_moderation_embed(
            "Missing Permissions",
            "❌ Only staff can clear the snipe history.",
            AURA_RED,
            "🔒"
        ))
        return

    deleted_message_cache[str(ctx.guild.id)] = []
    await ctx.send(embed=aura_embed(
        "Snipe History Cleared",
        "🗑️ The deleted-message history has been cleared.",
        AURA_GREEN,
        "🗑️"
    ))


# -------- LOGGING --------

async def send_log(guild, title, description, color=AURA_PURPLE):
    channel = await get_saved_text_channel(
        guild, get_settings(guild.id).get("log_channel")
    )
    if channel:
        try:
            await channel.send(embed=aura_embed(title, description, color, "📋"))
        except Exception:
            pass


async def send_message_log(guild, title, description, color=AURA_BLUE):
    settings = get_settings(guild.id)
    channel = await get_saved_text_channel(guild, settings.get("log_channel"))
    if channel is None:
        channel = await get_saved_text_channel(guild, settings.get("message_log_channel"))

    if channel:
        try:
            await channel.send(embed=aura_embed(title, description[:4000], color, "💬"))
        except Exception:
            pass


# -------- WELCOME CARD --------

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
    ImageDraw.Draw(mask).ellipse((0, 0, 189, 189), fill=255)    image.paste(avatar, (70, 85), mask)

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
    return data["giveaway_entries"].setdefault(giveaway_id, {})


def weighted_winners(entries, amount, excluded=None):
    excluded = {str(x) for x in (excluded or [])}
    pool = {
        str(user_id): max(0, int(weight))        for user_id, weight in entries.items()
        if int(weight) > 0 and str(user_id) not in excluded
    }
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

    participant_message = giveaway.get("message") or "🎉 **Click Enter Giveaway to participate!**"
    return aura_embed(
        "GIVEAWAY",
        f"╭─ 🎁 **Prize:** {giveaway['prize']}\n"
        f"├─ 🏆 **Winners:** {giveaway['winners']}\n"
        f"├─ 👥 **Participants:** {len(entries)}\n"
        f"├─ 🎟️ **Total Entries:** {sum(int(v) for v in entries.values())}\n"
        f"├─ 🔐 **Required Role:** {giveaway_required_role_text(giveaway)}\n"
        f"├─ 👤 **Hosted by:** <@{giveaway['created_by']}>\n"
        f"├─ ⏰ **Ends:** <t:{int(end.timestamp())}:R>\n"
        f"╰─ 🆔 **ID:** `{giveaway_id}`\n\n"
        f"{participant_message}",
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
        if not giveaway:
            await interaction.response.send_message(
                "❌ This giveaway is no longer active.", ephemeral=True
            )
            return

        if str(interaction.user.id) in get_giveaway_blacklist(interaction.guild.id):
            await interaction.response.send_message(
                "🚫 You are blacklisted from AuraGuard giveaways.", ephemeral=True
            )
            return

        required_role_id = giveaway.get("required_role")
        if required_role_id:
            role = interaction.guild.get_role(int(required_role_id))
            if role and role not in interaction.user.roles:
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

        amount = 1 + get_bonus_entries(interaction.user) + int(giveaway.get("extra_entries", 0))
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
    winners = weighted_winners(entries, int(giveaway["winners"]))

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


def _parse_role_id(value):
    value = (value or "").strip()
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    return int(digits) if digits else None


def giveaway_draft_embed(draft):
    required = f"<@&{draft['required_role']}>" if draft.get("required_role") else "None"
    extra = draft.get("extra_entries", 0)
    message = draft.get("message") or "Click **Enter Giveaway** below to participate!"
    return aura_embed(
        "GIVEAWAY SETUP",
        "╭─ 🎁 **Giveaway Configuration**\n"
        f"├─ 🎁 **Prize:** {draft.get('prize') or 'Not set'}\n"
        f"├─ 🏆 **Winners:** {draft.get('winners', 1)}\n"
        f"├─ ⏱️ **Duration:** {draft.get('minutes', 10)} minutes\n"
        f"├─ 🎟️ **Extra Entries:** {extra}\n"
        f"├─ 🔐 **Required Role:** {required}\n"
        f"├─ 🚫 **Blacklist:** Enabled\n"
        f"╰─ 💬 **Message:** {message}\n\n"
        "Use **Edit** to change the giveaway settings, **Start** to publish it,\n"
        "**Premium Customize Message** to change the participant message, or **Cancel** to discard it.",
        AURA_PURPLE,
        "🎉"
    )


class GiveawayEditModal(discord.ui.Modal, title="Edit Giveaway"):
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.prize = discord.ui.TextInput(
            label="Prize",
            placeholder="What are you giving away?",
            default=str(view.draft.get("prize", "")),
            max_length=200,
            required=True,
        )
        self.minutes = discord.ui.TextInput(
            label="Duration (minutes)",
            placeholder="10",
            default=str(view.draft.get("minutes", 10)),
            max_length=6,
            required=True,
        )
        self.winners = discord.ui.TextInput(
            label="Number of winners",
            placeholder="1",
            default=str(view.draft.get("winners", 1)),
            max_length=3,
            required=True,
        )
        self.required_role = discord.ui.TextInput(
            label="Required role (mention or ID, optional)",
            placeholder="@Verified or 1234567890",
            default=(f"<@&{view.draft['required_role']}>" if view.draft.get("required_role") else ""),
            max_length=100,
            required=False,
        )
        self.extra_entries = discord.ui.TextInput(
            label="Extra entries for every participant",
            placeholder="0",
            default=str(view.draft.get("extra_entries", 0)),
            max_length=5,
            required=True,
        )
        for item in (self.prize, self.minutes, self.winners, self.required_role, self.extra_entries):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            minutes = int(self.minutes.value)
            winners = int(self.winners.value)
            extra_entries = int(self.extra_entries.value)
        except ValueError:
            await interaction.response.send_message("❌ Use numbers for duration, winners, and extra entries.", ephemeral=True)
            return

        if minutes < 1 or winners < 1 or extra_entries < 0:
            await interaction.response.send_message("❌ Duration/winners must be at least 1 and extra entries cannot be negative.", ephemeral=True)
            return

        role_id = _parse_role_id(self.required_role.value)
        if role_id and not interaction.guild.get_role(role_id):
            await interaction.response.send_message("❌ I couldn't find that required role in this server.", ephemeral=True)
            return

        self.view.draft.update({
            "prize": self.prize.value.strip(),
            "minutes": minutes,
            "winners": winners,
            "required_role": role_id,
            "extra_entries": extra_entries,
        })
        await interaction.response.edit_message(
            embed=giveaway_draft_embed(self.view.draft),
            view=self.view
        )


class GiveawayCustomizeModal(discord.ui.Modal, title="Customize Giveaway Message"):
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.message = discord.ui.TextInput(
            label="Participant message",
            style=discord.TextStyle.paragraph,
            placeholder="Write the message shown to participants...",
            default=str(view.draft.get("message", "")),
            max_length=1000,
            required=False,
        )
        self.add_item(self.message)

    async def on_submit(self, interaction: discord.Interaction):
        self.view.draft["message"] = self.message.value.strip()
        await interaction.response.edit_message(
            embed=giveaway_draft_embed(self.view.draft),            view=self.view
        )


class GiveawaySetupView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction):
        super().__init__(timeout=600)
        self.guild_id = interaction.guild.id
        self.channel_id = interaction.channel.id
        self.host_id = interaction.user.id
        self.draft = {
            "prize": "",
            "minutes": 10,
            "winners": 1,
            "required_role": None,
            "extra_entries": 0,
            "message": "",
        }

    @discord.ui.button(label="Edit", emoji="✏️", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host_id:
            await interaction.response.send_message("❌ Only the giveaway host can edit this setup.", ephemeral=True)
            return
        await interaction.response.send_modal(GiveawayEditModal(self))

    @discord.ui.button(label="Start", emoji="▶️", style=discord.ButtonStyle.success)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host_id:
            await interaction.response.send_message("❌ Only the giveaway host can start this setup.", ephemeral=True)
            return
        if not self.draft["prize"].strip():
            await interaction.response.send_message("❌ Click **Edit** and enter a prize first.", ephemeral=True)
            return

        giveaway_id = make_giveaway_id()
        end = datetime.now(timezone.utc) + timedelta(minutes=int(self.draft["minutes"]))
        giveaway = {
            "guild": self.guild_id,
            "channel": self.channel_id,
            "prize": self.draft["prize"].strip(),
            "winners": int(self.draft["winners"]),
            "end_time": end.isoformat(),
            "created_by": self.host_id,
            "required_role": self.draft.get("required_role"),
            "extra_entries": int(self.draft.get("extra_entries", 0)),
            "message": self.draft.get("message", ""),
        }
        data["giveaways"][giveaway_id] = giveaway
        data["giveaway_entries"][giveaway_id] = {}
        save_data()

        await interaction.response.edit_message(
            embed=giveaway_embed(giveaway_id, giveaway),
            view=GiveawayView(giveaway_id)
        )

    @discord.ui.button(label="Premium Customize Message", emoji="✨", style=discord.ButtonStyle.secondary)
    async def premium_customize(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host_id:
            await interaction.response.send_message("❌ Only the giveaway host can customize this setup.", ephemeral=True)
            return
        await interaction.response.send_modal(GiveawayCustomizeModal(self))

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host_id:
            await interaction.response.send_message("❌ Only the giveaway host can cancel this setup.", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            embed=aura_embed("Giveaway Cancelled", "The giveaway setup was discarded.", AURA_RED, "✖️"),
            view=self
        )
        self.stop()


@giveaway_group.command(name="start", description="Open the advanced giveaway setup panel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_start(interaction: discord.Interaction):
    view = GiveawaySetupView(interaction)
    await interaction.response.send_message(
        embed=giveaway_draft_embed(view.draft),
        view=view
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
    interaction: discord.Interaction,    role: discord.Role,
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
    winners: int = 1):
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

    async def callback(self, interaction: discord.Interaction):        selected_channel = self.values[0]
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
    await member.kick(reason=reason)
    await interaction.response.send_message(f"👢 Kicked {member.mention}.")
    await send_log(
        interaction.guild, "Member Kicked",
        f"Member: {member.mention}\nModerator: {interaction.user.mention}\nReason: {reason}",
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


@bot.tree.command(name="untimeout", description="Remove a timeout.")
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout(interaction, member: discord.Member):
    if not await hierarchy_check(interaction, member):
        return
    await member.timeout(None)
    await interaction.response.send_message(f"🔓 Removed {member.mention}'s timeout.")




# -------- WARNING SYSTEM --------

def get_warning_list(guild_id, user_id):
    guild_id = str(guild_id)
    user_id = str(user_id)
    guild_warnings = data["warnings"].setdefault(guild_id, {})
    return guild_warnings.setdefault(user_id, [])


def next_warning_id(warnings):
    used = {int(item.get("id", 0)) for item in warnings if str(item.get("id", "")).isdigit()}
    warning_id = 1
    while warning_id in used:
        warning_id += 1
    return warning_id


def add_warning_record(guild_id, member_id, moderator_id, reason):
    warnings = get_warning_list(guild_id, member_id)
    record = {
        "id": next_warning_id(warnings),
        "moderator_id": int(moderator_id),
        "reason": reason.strip() or "No reason provided",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    warnings.append(record)
    save_data()
    return record, warnings


def remove_warning_record(guild_id, member_id, warning_id):
    warnings = get_warning_list(guild_id, member_id)
    for index, warning in enumerate(warnings):
        if int(warning.get("id", 0)) == int(warning_id):
            removed = warnings.pop(index)
            if not warnings:
                data["warnings"].setdefault(str(guild_id), {}).pop(str(member_id), None)
            save_data()
            return removed
    return None


def clear_warning_records(guild_id, member_id):
    guild_warnings = data["warnings"].setdefault(str(guild_id), {})
    removed = list(guild_warnings.get(str(member_id), []))
    guild_warnings.pop(str(member_id), None)
    save_data()
    return removed


def warning_history_embed(guild, member, warnings, checked_by):
    if not warnings:
        description = (
            f"{member.mention} has **0 warnings**.\n\n"
            "This user has no warnings."
        )
    else:
        lines = []
        for warning in warnings[-10:]:
            try:
                stamp = datetime.fromisoformat(warning["timestamp"])
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                time_text = f"<t:{int(stamp.timestamp())}:R>"
            except Exception:
                time_text = "Unknown time"

            moderator = f"<@{warning.get('moderator_id')}>"
            lines.append(
                f"**#{warning.get('id', '?')}** • {time_text}\n"
                f"👤 **Moderator:** {moderator}\n"
                f"📝 **Reason:** {discord.utils.escape_markdown(str(warning.get('reason', 'No reason provided')))[:500]}"
            )
        description = "\n\n".join(lines)
        if len(warnings) > 10:
            description += f"\n\n*Showing the 10 most recent of {len(warnings)} warnings.*"

    embed = discord.Embed(
        title="📋 Warning History",
        description=description,
        color=AURA_YELLOW if warnings else AURA_GREEN,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text=f"Checked by {checked_by} • AuraGuard")
    try:
        embed.set_thumbnail(url=str(member.display_avatar.url))
    except Exception:
        pass
    return embed


async def send_warning_dm(member, guild, record):
    try:
        await member.send(
            embed=prefix_moderation_embed(
                "Warning Issued",
                f"You received a warning in **{guild.name}**.\n\n"
                f"📝 **Reason:** {discord.utils.escape_markdown(record['reason'])[:1500]}\n"
                f"🔢 **Warning:** #{record['id']}",
                AURA_YELLOW,
                "⚠️"
            )
        )
    except (discord.Forbidden, discord.HTTPException):
        pass


@bot.tree.command(name="warn", description="Issue a warning to a member.")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn_slash(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await hierarchy_check(interaction, member):
        return

    record, warnings = add_warning_record(
        interaction.guild.id,
        member.id,
        interaction.user.id,
        reason
    )

    await send_warning_dm(member, interaction.guild, record)

    await interaction.response.send_message(embed=aura_embed(
        "Warning Successfully Issued",
        f"⚠️ **Member:** {member.mention}\n"
        f"🔢 **Warning:** **#{record['id']}**\n"
        f"📝 **Reason:** {discord.utils.escape_markdown(record['reason'])[:1500]}\n"
        f"📋 **Total Warnings:** **{len(warnings)}**\n\n"
        f"The warning for {member.mention} was recorded by {interaction.user.mention}.",
        AURA_YELLOW,
        "⚠️"
    ))

    await send_log(
        interaction.guild,
        "Warning Issued",
        f"Member: {member.mention}\nModerator: {interaction.user.mention}\n"
        f"Warning: #{record['id']}\nReason: {record['reason']}",
        AURA_YELLOW
    )


@bot.tree.command(name="warnings", description="View a member's warning history.")
@app_commands.checks.has_permissions(moderate_members=True)
async def warnings_slash(interaction: discord.Interaction, member: discord.Member):
    warnings = get_warning_list(interaction.guild.id, member.id)
    await interaction.response.send_message(
        embed=warning_history_embed(interaction.guild, member, warnings, interaction.user.mention),
        ephemeral=True
    )


@bot.tree.command(name="removewarning", description="Remove one warning from a member.")
@app_commands.checks.has_permissions(moderate_members=True)
async def removewarning_slash(interaction: discord.Interaction, member: discord.Member, warning_id: int):
    if warning_id < 1:
        await interaction.response.send_message("❌ Warning number must be at least 1.", ephemeral=True)
        return

    removed = remove_warning_record(interaction.guild.id, member.id, warning_id)
    if removed is None:
        await interaction.response.send_message(
            f"❌ Warning **#{warning_id}** was not found for {member.mention}.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(embed=aura_embed(
        "Warning Removed",
        f"🗑️ Removed warning **#{warning_id}** from {member.mention}.\n"
        f"🛡️ Removed by: {interaction.user.mention}",
        AURA_GREEN,
        "🗑️"
    ))

    await send_log(
        interaction.guild,
        "Warning Removed",
        f"Member: {member.mention}\nModerator: {interaction.user.mention}\n"
        f"Warning: #{warning_id}\nReason: {removed.get('reason', 'No reason provided')}",
        AURA_GREEN
    )


@bot.tree.command(name="clearwarnings", description="Clear every warning from a member.")
@app_commands.checks.has_permissions(moderate_members=True)
async def clearwarnings_slash(interaction: discord.Interaction, member: discord.Member):
    removed = clear_warning_records(interaction.guild.id, member.id)
    if not removed:
        await interaction.response.send_message(
            f"❌ {member.mention} has no warnings to clear.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(embed=aura_embed(
        "Warnings Cleared",
        f"🗑️ Cleared **{len(removed)} warnings** from {member.mention}.\n"
        f"🛡️ Cleared by: {interaction.user.mention}",
        AURA_GREEN,
        "🗑️"
    ))

    await send_log(
        interaction.guild,
        "Warnings Cleared",
        f"Member: {member.mention}\nModerator: {interaction.user.mention}\n"
        f"Warnings removed: **{len(removed)}**",
        AURA_GREEN
    )


@bot.command(name="warn")
@commands.has_permissions(moderate_members=True)
async def prefix_warn(ctx, member: discord.Member, *, reason="No reason provided"):
    if not await prefix_hierarchy_check(ctx, member):
        return

    record, warnings = add_warning_record(
        ctx.guild.id,
        member.id,
        ctx.author.id,
        reason
    )

    await send_warning_dm(member, ctx.guild, record)

    await ctx.send(embed=prefix_moderation_embed(
        "Warning Successfully Issued",
        f"⚠️ **Member:** {member.mention}\n"
        f"🔢 **Warning:** **#{record['id']}**\n"
        f"📝 **Reason:** {discord.utils.escape_markdown(record['reason'])[:1500]}\n"
        f"📋 **Total Warnings:** **{len(warnings)}**\n\n"
        f"The warning for {member.mention} was recorded by {ctx.author.mention}.",
        AURA_YELLOW,
        "⚠️"
    ))

    await send_log(
        ctx.guild,
        "Warning Issued",
        f"Member: {member.mention}\nModerator: {ctx.author.mention}\n"
        f"Warning: #{record['id']}\nReason: {record['reason']}",
        AURA_YELLOW
    )


@bot.command(name="warnings")
@commands.has_permissions(moderate_members=True)
async def prefix_warnings(ctx, member: discord.Member):
    warnings = get_warning_list(ctx.guild.id, member.id)
    await ctx.send(
        embed=warning_history_embed(ctx.guild, member, warnings, ctx.author.mention)
    )


@bot.command(name="removewarning", aliases=["delwarning", "removewarn"])
@commands.has_permissions(moderate_members=True)
async def prefix_removewarning(ctx, member: discord.Member, warning_id: int):
    if warning_id < 1:
        await ctx.send(embed=prefix_moderation_embed(
            "Invalid Warning",
            "❌ Warning number must be at least 1.",
            AURA_YELLOW,
            "⚠️"
        ))
        return

    removed = remove_warning_record(ctx.guild.id, member.id, warning_id)
    if removed is None:
        await ctx.send(embed=prefix_moderation_embed(
            "Warning Not Found",
            f"❌ Warning **#{warning_id}** was not found for {member.mention}.",
            AURA_YELLOW,
            "⚠️"
        ))
        return

    await ctx.send(embed=prefix_moderation_embed(
        "Warning Removed",
        f"🗑️ Removed warning **#{warning_id}** from {member.mention}.\n"
        f"🛡️ Removed by: {ctx.author.mention}",
        AURA_GREEN,
        "🗑️"
    ))

    await send_log(
        ctx.guild,
        "Warning Removed",
        f"Member: {member.mention}\nModerator: {ctx.author.mention}\n"
        f"Warning: #{warning_id}\nReason: {removed.get('reason', 'No reason provided')}",
        AURA_GREEN
    )


@bot.command(name="clearwarnings", aliases=["clearwarns"])
@commands.has_permissions(moderate_members=True)
async def prefix_clearwarnings(ctx, member: discord.Member):
    removed = clear_warning_records(ctx.guild.id, member.id)
    if not removed:
        await ctx.send(embed=prefix_moderation_embed(
            "No Warnings",
            f"❌ {member.mention} has no warnings to clear.",
            AURA_YELLOW,
            "⚠️"
        ))
        return

    await ctx.send(embed=prefix_moderation_embed(
        "Warnings Cleared",
        f"🗑️ Cleared **{len(removed)} warnings** from {member.mention}.\n"
        f"🛡️ Cleared by: {ctx.author.mention}",
        AURA_GREEN,
        "🗑️"
    ))

    await send_log(
        ctx.guild,
        "Warnings Cleared",
        f"Member: {member.mention}\nModerator: {ctx.author.mention}\n"
        f"Warnings removed: **{len(removed)}**",
        AURA_GREEN
    )


# -------- PREFIX MODERATION --------

def prefix_moderation_embed(title, description="", color=AURA_PURPLE, emoji="🛡️"):
    embed = discord.Embed(
        title=f"{emoji} {title}",
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="AuraGuard • Moderation")
    return embed


def parse_prefix_duration(value):
    """Parse 10m, 30s, 2h, 1d, or a plain number of minutes."""
    value = str(value).strip().lower()
    if not value:
        return None

    units = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }

    try:
        if value[-1] in units:
            amount = float(value[:-1])
            seconds = int(amount * units[value[-1]])
        else:
            seconds = int(float(value) * 60)
    except (ValueError, TypeError):
        return None

    if seconds < 1 or seconds > 28 * 86400:
        return None
    return seconds


def format_prefix_duration(seconds):
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


async def prefix_hierarchy_check(ctx, member):
    if member == ctx.author:
        await ctx.send(embed=prefix_moderation_embed(
            "Cannot Moderate User",
            "❌ You can't moderate yourself.",
            AURA_RED,
            "🚫"
        ))
        return False

    if member == ctx.guild.owner:
        await ctx.send(embed=prefix_moderation_embed(
            "Cannot Moderate User",
            "❌ The server owner can't be moderated by this command.",
            AURA_RED,
            "🚫"
        ))
        return False

    if ctx.author != ctx.guild.owner and member.top_role >= ctx.author.top_role:
        await ctx.send(embed=prefix_moderation_embed(
            "Cannot Moderate User",
            "❌ That member has an equal or higher role than you.",
            AURA_RED,
            "🚫"
        ))
        return False

    if ctx.guild.me and member.top_role >= ctx.guild.me.top_role:
        await ctx.send(embed=prefix_moderation_embed(
            "Cannot Moderate User",
            "❌ My role is not high enough to moderate that member.",
            AURA_RED,
            "🚫"
        ))
        return False

    return True


@bot.command(name="mute", aliases=["timeout"])
@commands.has_permissions(moderate_members=True)
async def prefix_mute(ctx, member: discord.Member, *args):
    """
    Prefix usage:
    !mute @user <reason> <duration>
    Examples:
    !mute @user mogged 10m
    !mute @user spamming 30m
    """
    if not args:
        await ctx.send(embed=prefix_moderation_embed(
            "Missing Duration",
            "Usage: `!mute @user <reason> <duration>`\n\n"
            "Example: `!mute @user mogged 10m`",
            AURA_YELLOW,
            "⚠️"
        ))
        return

    duration = parse_prefix_duration(args[-1])
    if duration is None:
        await ctx.send(embed=prefix_moderation_embed(
            "Invalid Duration",
            "Use a duration such as **30s**, **10m**, **2h**, or **1d**.\n\n"
            "Usage: `!mute @user <reason> <duration>`",
            AURA_YELLOW,
            "⚠️"
        ))
        return

    if not await prefix_hierarchy_check(ctx, member):
        return

    reason = " ".join(args[:-1]).strip() or "No reason provided"

    try:
        await member.timeout(
            discord.utils.utcnow() + timedelta(seconds=duration),
            reason=f"{reason} | Moderator: {ctx.author}"
        )
    except discord.Forbidden:
        await ctx.send(embed=prefix_moderation_embed(            "Moderation Failed",
            "❌ I don't have permission to timeout that member. "
            "Make sure my role is above theirs.",
            AURA_RED,
            "🚫"
        ))
        return
    except discord.HTTPException:
        await ctx.send(embed=prefix_moderation_embed(
            "Moderation Failed",
            "❌ Discord rejected the timeout request. Please try again.",
            AURA_RED,
            "🚫"
        ))
        return

    duration_text = format_prefix_duration(duration)

    embed = prefix_moderation_embed(
        "User Muted",
        "",
        AURA_RED,
        "🔇"
    )
    embed.add_field(name="User", value=member.mention, inline=False)
    embed.add_field(name="Duration", value=duration_text, inline=True)
    embed.add_field(name="Reason", value=reason[:1024], inline=False)
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=False)

    await ctx.send(embed=embed)

    await send_log(
        ctx.guild,
        "User Muted",
        f"User: {member.mention}\n"
        f"Moderator: {ctx.author.mention}\n"
        f"Duration: **{duration_text}**\n"
        f"Reason: {reason}",
        AURA_RED
    )


@bot.command(name="unmute", aliases=["untimeout"])
@commands.has_permissions(moderate_members=True)
async def prefix_unmute(ctx, member: discord.Member):
    if not await prefix_hierarchy_check(ctx, member):
        return

    try:
        await member.timeout(None, reason=f"Unmuted by {ctx.author}")
    except discord.Forbidden:
        await ctx.send(embed=prefix_moderation_embed(
            "Moderation Failed",
            "❌ I don't have permission to remove that timeout.",
            AURA_RED,
            "🚫"
        ))
        return

    embed = prefix_moderation_embed("User Unmuted", "", AURA_GREEN, "🔊")
    embed.add_field(name="User", value=member.mention, inline=False)
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=False)
    await ctx.send(embed=embed)

    await send_log(
        ctx.guild,
        "User Unmuted",
        f"User: {member.mention}\nModerator: {ctx.author.mention}",
        AURA_GREEN
    )


@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def prefix_kick(ctx, member: discord.Member, *, reason="No reason provided"):
    if not await prefix_hierarchy_check(ctx, member):
        return

    try:
        await member.kick(reason=f"{reason} | Moderator: {ctx.author}")
    except discord.Forbidden:
        await ctx.send(embed=prefix_moderation_embed(
            "Moderation Failed",
            "❌ I don't have permission to kick that member.",
            AURA_RED,
            "🚫"
        ))
        return

    embed = prefix_moderation_embed("User Kicked", "", AURA_RED, "👢")
    embed.add_field(name="User", value=member.mention, inline=False)
    embed.add_field(name="Reason", value=reason[:1024], inline=False)
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=False)
    await ctx.send(embed=embed)

    await send_log(
        ctx.guild,
        "User Kicked",
        f"User: {member.mention}\nModerator: {ctx.author.mention}\nReason: {reason}",
        AURA_RED
    )


@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def prefix_ban(ctx, member: discord.Member, *, reason="No reason provided"):
    if not await prefix_hierarchy_check(ctx, member):
        return

    try:
        await member.ban(reason=f"{reason} | Moderator: {ctx.author}")
    except discord.Forbidden:
        await ctx.send(embed=prefix_moderation_embed(
            "Moderation Failed",
            "❌ I don't have permission to ban that member.",
            AURA_RED,
            "🚫"
        ))
        return

    embed = prefix_moderation_embed("User Banned", "", AURA_RED, "🔨")
    embed.add_field(name="User", value=member.mention, inline=False)
    embed.add_field(name="Reason", value=reason[:1024], inline=False)
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=False)
    await ctx.send(embed=embed)

    await send_log(
        ctx.guild,
        "User Banned",
        f"User: {member.mention}\nModerator: {ctx.author.mention}\nReason: {reason}",
        AURA_RED
    )


@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
async def prefix_unban(ctx, user_id: int):
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user, reason=f"Unbanned by {ctx.author}")
    except (discord.NotFound, discord.HTTPException):
        await ctx.send(embed=prefix_moderation_embed(
            "User Not Found",
            "❌ That user is not banned or the ID is invalid.",
            AURA_YELLOW,
            "⚠️"
        ))
        return
    except discord.Forbidden:
        await ctx.send(embed=prefix_moderation_embed(
            "Moderation Failed",
            "❌ I don't have permission to unban that user.",
            AURA_RED,
            "🚫"
        ))
        return

    embed = prefix_moderation_embed("User Unbanned", "", AURA_GREEN, "🔓")
    embed.add_field(name="User", value=f"<@{user.id}> ({user})", inline=False)
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=False)
    await ctx.send(embed=embed)

    await send_log(
        ctx.guild,
        "User Unbanned",
        f"User: <@{user.id}>\nModerator: {ctx.author.mention}",
        AURA_GREEN
    )


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    command_name = ctx.command.qualified_name if ctx.command else "command"

    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=prefix_moderation_embed(
            "Missing Permissions",
            "❌ You don't have the required permissions to use this command.",
            AURA_RED,
            "🔒"
        ))
        return

    if isinstance(error, (commands.MissingRequiredArgument, commands.MemberNotFound)):
        usage = {
            "mute": "!mute @user <reason> <duration>",
            "timeout": "!timeout @user <reason> <duration>",
            "unmute": "!unmute @user",
            "untimeout": "!untimeout @user",
            "kick": "!kick @user <reason>",
            "ban": "!ban @user <reason>",
            "unban": "!unban <user_id>",
            "warn": "!warn @user <reason>",
            "warnings": "!warnings @user",
            "removewarning": "!removewarning @user <warning_id>",
            "delwarning": "!delwarning @user <warning_id>",
            "removewarn": "!removewarn @user <warning_id>",
            "clearwarnings": "!clearwarnings @user",
            "clearwarns": "!clearwarns @user"
        }.get(command_name, f"!{command_name} <arguments>")

        if command_name == "warn":
            message = (
                "You need to mention a member you want to warn.\n\n"
                "**Usage:** `!warn @user <reason>`"
            )
        elif command_name == "warnings":
            message = (
                "You need to mention a member whose warning history you want to view.\n\n"
                "**Usage:** `!warnings @user`"
            )
        elif command_name in {"removewarning", "delwarning", "removewarn"}:
            message = (
                "You need to mention a member and provide the warning ID.\n\n"
                f"**Usage:** `{usage}`"
            )
        elif command_name in {"clearwarnings", "clearwarns"}:
            message = (
                "You need to mention a member whose warnings you want to clear.\n\n"
                f"**Usage:** `{usage}`"
            )
        else:
            message = f"Usage: `{usage}`"

        await ctx.send(embed=prefix_moderation_embed(
            "Missing User",
            message,
            AURA_YELLOW,
            "⚠️"
        ))
        return

    if isinstance(error, commands.BadArgument):
        await ctx.send(embed=prefix_moderation_embed(
            "Invalid User",
            "❌ I couldn't find that member. Mention them or use a valid user ID.",
            AURA_YELLOW,
            "⚠️"
        ))
        return

    if isinstance(error, commands.BotMissingPermissions):
        await ctx.send(embed=prefix_moderation_embed(
            "Bot Missing Permissions",
            "❌ I don't have the Discord permissions needed for that action.",
            AURA_RED,
            "🚫"
        ))
        return

    print("Prefix command error:", repr(error))
    await ctx.send(embed=prefix_moderation_embed(
        "Command Error",
        "❌ Something went wrong while running that command.",
        AURA_RED,
        "⚠️"
    ))


# -------- EVENTS --------

@bot.event
async def on_ready():
    print("=" * 45)
    print(f"AuraGuard V8 online as {bot.user}")
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

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} top-level slash commands.")
    except Exception as e:
        print("Slash command sync error:", e)


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
            await channel.send(embed=aura_embed(
                "Member Left",
                apply_placeholders(settings["leave_message"], member),
                AURA_YELLOW, "🚪"
            ))

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

    automod = get_automod(message.guild.id)

    if automod.get("enabled"):
        lower_content = message.content.lower()
        for word in automod.get("blocked_words", []):
            if word.lower() in lower_content:
                try:
                    await message.delete()
                except Exception:
                    pass

                try:
                    await message.channel.send(
                        f"⚠️ {message.author.mention}, that message contains a blocked word.",
                        delete_after=5
                    )
                except Exception:
                    pass

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

    remember_deleted_message(message)

    embed = make_event_log_embed(
        "Message deleted",
        message.author,
        message.channel,
        f"{clean_message_content(message.content)}\n\n"
        f"**Message ID:** {message.id}",
        AURA_RED,
        "🗑️"
    )

    log_channel = await get_saved_text_channel(
        message.guild, get_settings(message.guild.id).get("log_channel")
    )
    if log_channel:
        try:
            await log_channel.send(embed=embed)
        except Exception:
            pass


@bot.event
async def on_raw_message_delete(payload):
    cached = getattr(payload, "cached_message", None)
    if cached is not None or not payload.guild_id:
        return

    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return

    channel = guild.get_channel(payload.channel_id)
    if channel is None:
        try:
            channel = await guild.fetch_channel(payload.channel_id)
        except Exception:
            channel = None

    log_channel = await get_saved_text_channel(
        guild, get_settings(guild.id).get("log_channel")
    )
    if log_channel:
        try:
            embed = aura_embed(
                "Message Deleted",
                f"**Channel:** {snipe_channel_text(channel) if channel else f'Channel ID: {payload.channel_id}'}\n"
                f"**Message ID:** {payload.message_id}\n\n"
                f"*The original message was not in cache, so its author/content could not be recovered.*",
                AURA_RED,
                "🗑️"
            )
            await log_channel.send(embed=embed)
        except Exception:
            pass


@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild or before.content == after.content:
        return

    embed = make_event_log_embed(
        "Message edited",
        before.author,
        before.channel,
        f"**Before:** {clean_message_content(before.content)}\n\n"
        f"**+After:** {clean_message_content(after.content)}\n\n"
        f"**Message ID:** {before.id}",
        AURA_YELLOW,
        "✏️"
    )

    log_channel = await get_saved_text_channel(
        before.guild, get_settings(before.guild.id).get("log_channel")
    )
    if log_channel:
        try:
            await log_channel.send(embed=embed)
        except Exception:
            pass


@bot.event
async def on_raw_message_edit(payload):
    cached = getattr(payload, "cached_message", None)
    if cached is not None or not payload.guild_id:
        return

    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return

    log_channel = await get_saved_text_channel(
        guild, get_settings(guild.id).get("log_channel")
    )
    if log_channel:
        try:
            channel = guild.get_channel(payload.channel_id)
            channel_text = snipe_channel_text(channel) if channel else f"Channel ID: {payload.channel_id}"
            embed = aura_embed(
                "Message Edited",
                f"**Channel:** {channel_text}\n"
                f"**Message ID:** {payload.message_id}\n\n"
                f"*The original message was not in cache, so the before/after text could not be recovered.*",
                AURA_YELLOW,
                "✏️"
            )
            await log_channel.send(embed=embed)
        except Exception:
            pass


@bot.event
async def on_bulk_message_delete(messages):
    if not messages:
        return

    guild = messages[0].guild
    if guild is None:
        return

    for message in messages:
        if not message.author.bot:
            remember_deleted_message(message)

    log_channel = await get_saved_text_channel(
        guild, get_settings(guild.id).get("log_channel")
    )
    if log_channel:
        try:
            await log_channel.send(embed=aura_embed(
                "Messages Deleted",
                f"🗑️ **{len(messages)} messages** were deleted in "
                f"{snipe_channel_text(messages[0].channel)}.",
                AURA_RED,
                "🗑️"
            ))
        except Exception:
            pass


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
    if isinstance(error, app_commands.MissingPermissions):
        message = "❌ You don't have permission to use that command."
    elif isinstance(error, app_commands.TransformerError):
        message = (
            "❌ That channel selection could not be processed. "            "Please use the channel picker again."
        )
    elif isinstance(error, app_commands.CheckFailure):
        message = "❌ You don't have permission to use that command."
    else:
        message = "❌ Something went wrong while running that command."

    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except Exception:
        pass


bot.run(TOKEN)