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

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

DEFAULT_DATA = {
    "settings": {},
    "warnings": {},
    "giveaways": {},
    "giveaway_entries": {},
    "giveaway_history": {},
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
    channel = await get_saved_text_channel(
        guild, get_settings(guild.id).get("message_log_channel")
    )
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


# -------- GIVEAWAYS --------

def giveaway_embed(giveaway_id, giveaway):
    entries = data["giveaway_entries"].get(giveaway_id, {})
    end = datetime.fromisoformat(giveaway["end_time"])
    return aura_embed(
        "GIVEAWAY",
        f"🎁 **Prize:** {giveaway['prize']}\n"
        f"🏆 **Winners:** {giveaway['winners']}\n"
        f"🆔 **Giveaway ID:** `{giveaway_id}`\n"
        f"👥 **Participants:** {len(entries)}\n"
        f"🎟️ **Total Entries:** {sum(entries.values())}\n"
        f"👤 **Hosted by:** <@{giveaway['created_by']}>\n"
        f"⏰ **Ends:** <t:{int(end.timestamp())}:R>\n\n"
        f"**Click Participate to enter!**",
        AURA_PURPLE, "🎉"
    )


class GiveawayView(discord.ui.View):
    def __init__(self, giveaway_id):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id

        participate_button = discord.ui.Button(
            label="Participate", emoji="🎉", style=discord.ButtonStyle.success,
            custom_id=f"auraguard_giveaway_enter_{giveaway_id}"
        )
        participate_button.callback = self.enter
        self.add_item(participate_button)

        entries_button = discord.ui.Button(
            label="My Entries", emoji="🎟️", style=discord.ButtonStyle.primary,
            custom_id=f"auraguard_giveaway_entries_{giveaway_id}"
        )
        entries_button.callback = self.my_entries
        self.add_item(entries_button)

    async def enter(self, interaction):
        giveaway = data["giveaways"].get(self.giveaway_id)
        if not giveaway:
            await interaction.response.send_message("❌ This giveaway is no longer active.", ephemeral=True)
            return

        entries = data["giveaway_entries"].setdefault(self.giveaway_id, {})
        user_id = str(interaction.user.id)

        if user_id in entries:
            await interaction.response.send_message(
                f"❌ You're already entered with **{entries[user_id]} entries**.", ephemeral=True
            )
            return

        entries[user_id] = 1
        save_data()
        await interaction.response.send_message("🎉 You're entered with **1 entry!**", ephemeral=True)

    async def my_entries(self, interaction):
        amount = data["giveaway_entries"].get(
            self.giveaway_id, {}
        ).get(str(interaction.user.id), 0)
        await interaction.response.send_message(
            f"🎟️ You have **{amount} {'entry' if amount == 1 else 'entries'}**.",
            ephemeral=True
        )


async def finish_giveaway(guild, channel, giveaway_id):
    giveaway = data["giveaways"].get(giveaway_id)
    if not giveaway:
        return

    entries = data["giveaway_entries"].get(giveaway_id, {})
    winners = weighted_winners(entries, giveaway["winners"])

    history = dict(giveaway)
    history["entries"] = dict(entries)
    history["winners_list"] = winners
    history["ended_at"] = datetime.now(timezone.utc).isoformat()

    data["giveaway_history"][giveaway_id] = history
    data["giveaways"].pop(giveaway_id, None)
    data["giveaway_entries"].pop(giveaway_id, None)
    save_data()

    if not channel:
        return

    if winners:
        winner_text = " ".join(f"<@{winner}>" for winner in winners)
        await channel.send(embed=aura_embed(
            "Giveaway Winner!",
            f"🎁 **Prize:** {history['prize']}\n\n🏆 {winner_text}",
            AURA_GREEN, "🏆"
        ))
    else:
        await channel.send(embed=aura_embed(
            "Giveaway Ended",
            f"🎁 **{history['prize']}**\n\nNobody entered.",
            AURA_YELLOW, "🎉"
        ))


# -------- COMMAND GROUPS --------

welcome_group = app_commands.Group(name="welcome", description="Manage welcome messages.")
leave_group = app_commands.Group(name="leave", description="Manage leave messages.")
tickets_group = app_commands.Group(name="tickets", description="Manage tickets.")
giveaway_group = app_commands.Group(name="giveaway", description="Manage giveaways.")
automod_group = app_commands.Group(name="automod", description="Manage AutoMod.")


# -------- WELCOME COMMANDS --------

class WelcomeChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, message):
        super().__init__(
            placeholder="Select the welcome text channel",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text]
        )
        self.welcome_message = message

    async def callback(self, interaction: discord.Interaction):
        selected_channel = self.values[0]
        channel = await get_saved_text_channel(interaction.guild, selected_channel.id)

        if channel is None:
            await interaction.response.edit_message(
                content="❌ I couldn't access that text channel.",
                view=None
            )
            return

        settings = get_settings(interaction.guild.id)
        settings["welcome_channel"] = int(channel.id)
        settings["welcome_message"] = self.welcome_message
        save_data()

        print(
            f"[WELCOME SETUP] Guild: {interaction.guild.id} | "
            f"Channel: {channel.name} ({channel.id})"
        )

        await interaction.response.edit_message(
            content=(
                f"✅ **Welcome setup complete!**\n\n"
                f"📢 Channel: {channel.mention}\n"
                f"💬 Message: {self.welcome_message}\n\n"
                f"Use `/welcome enable` to turn welcome messages on."
            ),
            view=None
        )


class WelcomeSetupView(discord.ui.View):
    def __init__(self, message):
        super().__init__(timeout=300)
        self.add_item(WelcomeChannelSelect(message))


@welcome_group.command(name="setup", description="Set the welcome channel and message.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_setup(
    interaction: discord.Interaction,
    message: str = "Welcome {user} to {server}! 🛡️"
):
    await interaction.response.send_message(
        "👋 Select the **welcome text channel** below.",
        view=WelcomeSetupView(message),
        ephemeral=True
    )


@welcome_group.command(name="enable", description="Enable welcome messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_enable(interaction: discord.Interaction):
    settings = get_settings(interaction.guild.id)
    channel = await get_saved_text_channel(
        interaction.guild, settings.get("welcome_channel")
    )

    if channel is None:
        await interaction.response.send_message(
            "❌ No valid welcome channel is configured. Run `/welcome setup` first.",
            ephemeral=True
        )
        return

    settings["welcome_enabled"] = True
    settings["welcome_channel"] = int(channel.id)
    save_data()

    await interaction.response.send_message(
        f"🟢 Welcome messages enabled in {channel.mention}.",
        ephemeral=True
    )


@welcome_group.command(name="disable", description="Disable welcome messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_disable(interaction):
    get_settings(interaction.guild.id)["welcome_enabled"] = False
    save_data()
    await interaction.response.send_message("🔴 Welcome messages disabled.", ephemeral=True)


@welcome_group.command(name="image", description="Turn welcome cards on or off.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_image(interaction, enabled: bool):
    get_settings(interaction.guild.id)["welcome_image_enabled"] = enabled
    save_data()
    await interaction.response.send_message(
        f"🖼️ Welcome image {'enabled' if enabled else 'disabled'}.", ephemeral=True
    )


@welcome_group.command(name="test", description="Test the welcome message.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_test(interaction: discord.Interaction):
    settings = get_settings(interaction.guild.id)
    saved_channel_id = settings.get("welcome_channel")

    print(
        f"[WELCOME TEST] Guild: {interaction.guild.id} | "
        f"Saved Channel ID: {saved_channel_id}"
    )

    if saved_channel_id is None:
        await interaction.response.send_message(
            "❌ No welcome channel has been configured yet. Run `/welcome setup` first.",
            ephemeral=True
        )
        return

    channel = await get_saved_text_channel(
        interaction.guild, saved_channel_id
    )

    if channel is None:
        await interaction.response.send_message(
            "❌ The saved welcome channel could not be found. Please run `/welcome setup` again.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        await send_welcome(interaction.user, channel)
        await interaction.followup.send(
            f"✅ Welcome test sent to {channel.mention}.",
            ephemeral=True
        )
    except Exception as e:
        print("[WELCOME TEST ERROR]", repr(e))
        await interaction.followup.send(
            "❌ Something went wrong while sending the welcome test.",
            ephemeral=True
        )


# -------- LEAVE COMMANDS --------

@leave_group.command(name="setup", description="Set leave channel and message.")
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_setup(
    interaction: discord.Interaction,
    leave_channel: discord.TextChannel,
    message: str = "{user} has left {server}. 👋"
):
    channel = await require_text_channel(interaction, leave_channel)
    if channel is None:
        return

    settings = get_settings(interaction.guild.id)
    settings["leave_channel"] = int(channel.id)
    settings["leave_message"] = message
    save_data()

    await interaction.response.send_message(
        f"✅ Leave channel set to {channel.mention}.", ephemeral=True
    )


@leave_group.command(name="enable", description="Enable leave messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_enable(interaction):
    settings = get_settings(interaction.guild.id)
    channel = await get_saved_text_channel(
        interaction.guild, settings.get("leave_channel")
    )
    if channel is None:
        await interaction.response.send_message("❌ Run `/leave setup` first.", ephemeral=True)
        return
    settings["leave_enabled"] = True
    settings["leave_channel"] = int(channel.id)
    save_data()
    await interaction.response.send_message("🟢 Leave messages enabled.", ephemeral=True)


@leave_group.command(name="disable", description="Disable leave messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_disable(interaction):
    get_settings(interaction.guild.id)["leave_enabled"] = False
    save_data()
    await interaction.response.send_message("🔴 Leave messages disabled.", ephemeral=True)


# -------- TICKET COMMANDS --------

@tickets_group.command(name="setup", description="Set ticket category.")
@app_commands.checks.has_permissions(manage_guild=True)
async def tickets_setup(interaction: discord.Interaction, category: discord.CategoryChannel):
    resolved_category = await resolve_category(interaction.guild, category)
    if resolved_category is None:
        await interaction.response.send_message(
            "❌ Please select a category channel.", ephemeral=True
        )
        return

    get_settings(interaction.guild.id)["ticket_category"] = int(resolved_category.id)
    save_data()
    await interaction.response.send_message(
        f"🎫 Ticket category set to **{resolved_category.name}**.", ephemeral=True
    )


@tickets_group.command(name="panel", description="Send the ticket panel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def tickets_panel(interaction):
    await interaction.response.send_message(
        embed=aura_embed(
            "AuraGuard Support",
            "Need help?\n\nClick below to open a ticket.",
            AURA_PURPLE, "🎫"
        ),
        view=TicketView()
    )


# -------- GIVEAWAY COMMANDS --------

@giveaway_group.command(name="start", description="Start a giveaway.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_start(interaction, prize: str, minutes: int, winners: int = 1):
    if minutes < 1 or winners < 1:
        await interaction.response.send_message(
            "❌ Minutes and winners must be at least 1.", ephemeral=True
        )
        return

    giveaway_id = make_unique_id(data["giveaways"])
    end = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    data["giveaways"][giveaway_id] = {
        "guild": interaction.guild.id,
        "channel": interaction.channel.id,
        "prize": prize,
        "winners": winners,
        "end_time": end.isoformat(),
        "created_by": interaction.user.id
    }
    data["giveaway_entries"][giveaway_id] = {}
    save_data()

    await interaction.response.send_message(
        embed=giveaway_embed(giveaway_id, data["giveaways"][giveaway_id]),
        view=GiveawayView(giveaway_id)
    )


@giveaway_group.command(name="entries", description="Check your giveaway entries.")
async def giveaway_entries(interaction, giveaway_id: str):
    amount = data["giveaway_entries"].get(giveaway_id, {}).get(str(interaction.user.id), 0)
    await interaction.response.send_message(
        f"🎟️ You have **{amount} {'entry' if amount == 1 else 'entries'}**.", ephemeral=True
    )


@giveaway_group.command(name="addentries", description="Give a member extra entries.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_addentries(interaction, giveaway_id: str, member: discord.Member, amount: int):
    if amount < 1 or giveaway_id not in data["giveaways"]:
        await interaction.response.send_message("❌ Invalid amount or giveaway.", ephemeral=True)
        return

    entries = data["giveaway_entries"].setdefault(giveaway_id, {})
    user_id = str(member.id)
    entries[user_id] = entries.get(user_id, 0) + amount
    save_data()

    await interaction.response.send_message(
        f"➕ {member.mention} now has **{entries[user_id]} entries**.", ephemeral=True
    )


@giveaway_group.command(name="end", description="End a giveaway early.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_end(interaction, giveaway_id: str):
    giveaway = data["giveaways"].get(giveaway_id)
    if not giveaway or giveaway["guild"] != interaction.guild.id:
        await interaction.response.send_message("❌ Giveaway not found.", ephemeral=True)
        return

    await interaction.response.defer()
    channel = await get_saved_text_channel(interaction.guild, giveaway["channel"])
    await finish_giveaway(interaction.guild, channel, giveaway_id)
    await interaction.followup.send("✅ Giveaway ended.")


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

    await send_message_log(
        message.guild, "Message Sent",
        f"**Author:** {message.author.mention}\n"
        f"**Channel:** {message.channel.mention}\n\n"
        f"**Message:**\n{clean_message_content(message.content)}"
    )

    await bot.process_commands(message)


@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild:
        return

    await send_message_log(
        message.guild, "Message Deleted",
        f"**Author:** {message.author.mention}\n"
        f"**Channel:** {message.channel.mention}\n\n"
        f"**Deleted Message:**\n{clean_message_content(message.content)}",
        AURA_RED
    )


@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild or before.content == after.content:
        return

    await send_message_log(
        before.guild, "Message Edited",
        f"**Author:** {before.author.mention}\n"
        f"**Channel:** {before.channel.mention}\n\n"
        f"**Before:**\n{clean_message_content(before.content)}\n\n"
        f"**After:**\n{clean_message_content(after.content)}",
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

    if isinstance(error, app_commands.MissingPermissions):
        message = "❌ You don't have permission to use that command."
    elif isinstance(error, app_commands.TransformerError):
        message = (
            "❌ That channel selection could not be processed. "
            "Please use the channel picker again."
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
