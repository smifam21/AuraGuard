# =========================================================
#                    AURAGUARD V8
# =========================================================
# Features:
# - Multi-server support
# - Welcome & leave messages
# - Welcome cards
# - Tickets + claims + transcripts
# - Giveaways + rerolls
# - Moderation + warnings
# - AutoMod + anti-spam
# - Message logging
# - Invite tracking + announcements + leaderboard
# - Server & user information
# - Improved error handling
# - Safer per-server settings
# =========================================================

import discord
from discord import app_commands
from discord.ext import commands, tasks

import os
import json
import random
import asyncio
import io

from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque

from PIL import Image, ImageDraw, ImageFont


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")
DATA_FILE = "auraguard_data.json"

AURA_PURPLE = 0x8A2BE2
AURA_GREEN = 0x2ECC71
AURA_RED = 0xE74C3C
AURA_YELLOW = 0xF1C40F
AURA_BLUE = 0x3498DB

FOOTER = "AuraGuard • Powered by Aura"

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN is missing from Railway Variables."
    )


# =========================================================
# BOT SETUP
# =========================================================

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
intents.invites = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)


# =========================================================
# DATA
# =========================================================

DEFAULT_DATA = {
    "settings": {},
    "warnings": {},
    "giveaways": {},
    "giveaway_entries": {},
    "giveaway_history": {},
    "ticket_claims": {},
    "automod": {},
    "invites": {}
}


def deep_copy_defaults():
    return json.loads(json.dumps(DEFAULT_DATA))


def load_data():

    if not os.path.exists(DATA_FILE):
        return deep_copy_defaults()

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            loaded = json.load(file)

        for key, value in DEFAULT_DATA.items():

            if key not in loaded:
                loaded[key] = json.loads(
                    json.dumps(value)
                )

        return loaded

    except Exception as error:

        print(
            "Data load error:",
            repr(error)
        )

        return deep_copy_defaults()


data = load_data()


def save_data():

    try:

        temp_file = DATA_FILE + ".tmp"

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                data,
                file,
                indent=4,
                ensure_ascii=False
            )

        os.replace(
            temp_file,
            DATA_FILE
        )

    except Exception as error:

        print(
            "Data save error:",
            repr(error)
        )


# =========================================================
# INVITE CACHE
# =========================================================

invite_cache = {}


# =========================================================
# ANTI-SPAM CACHE
# =========================================================

message_cache = defaultdict(deque)


# =========================================================
# SETTINGS
# =========================================================

def get_settings(guild_id):

    guild_id = str(guild_id)

    defaults = {

        # Welcome
        "welcome_enabled": False,
        "welcome_channel": None,
        "welcome_message":
            "Welcome {user} to {server}! 🛡️",
        "welcome_image_enabled": True,

        # Leave
        "leave_enabled": False,
        "leave_channel": None,
        "leave_message":
            "{user} has left {server}. 👋",

        # Tickets
        "ticket_category": None,
        "staff_role": None,

        # Logging
        "log_channel": None,
        "message_log_channel": None,

        # Invites
        "invite_channel": None,

        # Giveaway
        "giveaway_bonus_roles": {}
    }

    if guild_id not in data["settings"]:

        data["settings"][guild_id] = defaults.copy()
        save_data()

    else:

        for key, value in defaults.items():

            data["settings"][guild_id].setdefault(
                key,
                value
            )

    return data["settings"][guild_id]


def get_automod(guild_id):

    guild_id = str(guild_id)

    defaults = {

        "enabled": False,
        "blocked_words": [],
        "anti_spam": False,
        "spam_limit": 6,
        "spam_seconds": 5
    }

    if guild_id not in data["automod"]:

        data["automod"][guild_id] = defaults.copy()
        save_data()

    else:

        for key, value in defaults.items():

            data["automod"][guild_id].setdefault(
                key,
                value
            )

    return data["automod"][guild_id]


def get_invite_data(guild_id):

    guild_id = str(guild_id)

    data["invites"].setdefault(
        guild_id,
        {}
    )

    return data["invites"][guild_id]


# =========================================================
# HELPERS
# =========================================================

def aura_embed(
    title,
    description="",
    color=AURA_PURPLE,
    emoji="🛡️"
):

    embed = discord.Embed(

        title=f"{emoji} {title}",

        description=description,

        color=color,

        timestamp=datetime.now(
            timezone.utc
        )
    )

    embed.set_footer(
        text=FOOTER
    )

    return embed


def is_message_channel(channel):

    return isinstance(
        channel,
        (
            discord.TextChannel,
            discord.Thread
        )
    )


def get_message_channel(
    guild,
    channel_id
):

    if not channel_id:
        return None

    try:

        channel = guild.get_channel(
            int(channel_id)
        )

        if is_message_channel(channel):
            return channel

    except Exception:
        pass

    return None


def is_staff(member):

    if not isinstance(
        member,
        discord.Member
    ):
        return False

    if member.guild_permissions.administrator:
        return True

    if member.guild_permissions.manage_guild:
        return True

    role_id = get_settings(
        member.guild.id
    ).get(
        "staff_role"
    )

    if not role_id:
        return False

    role = member.guild.get_role(
        int(role_id)
    )

    return bool(
        role
        and role in member.roles
    )


def apply_placeholders(
    text,
    member
):

    return (
        text
        .replace(
            "{user}",
            member.mention
        )
        .replace(
            "{server}",
            member.guild.name
        )
        .replace(
            "{member_count}",
            str(member.guild.member_count)
        )
    )


def clean_message_content(content):

    return discord.utils.escape_markdown(

        content
        or "*No text content*"

    )[:3500]


def make_unique_id(collection):

    while True:

        item_id = str(
            random.randint(
                100000,
                999999
            )
        )

        if item_id not in collection:
            return item_id


def weighted_winners(
    entries,
    amount
):

    pool = {}

    for user_id, weight in entries.items():

        try:

            weight = int(weight)

            if weight > 0:
                pool[user_id] = weight

        except Exception:
            continue

    winners = []

    while pool and len(winners) < amount:

        winner = random.choices(

            list(pool.keys()),

            weights=list(pool.values()),

            k=1

        )[0]

        winners.append(winner)

        pool.pop(
            winner,
            None
        )

    return winners


async def safe_send(
    channel,
    *args,
    **kwargs
):

    try:

        if channel and is_message_channel(channel):
            return await channel.send(
                *args,
                **kwargs
            )

    except Exception as error:

        print(
            "Send error:",
            repr(error)
        )

    return None


# =========================================================
# LOGGING
# =========================================================

async def send_log(
    guild,
    title,
    description,
    color=AURA_PURPLE
):

    if not guild:
        return

    channel_id = get_settings(
        guild.id
    ).get(
        "log_channel"
    )

    channel = get_message_channel(
        guild,
        channel_id
    )

    if channel:

        await safe_send(

            channel,

            embed=aura_embed(

                title,

                description,

                color,

                "📋"
            )
        )


async def send_message_log(
    guild,
    title,
    description,
    color=AURA_BLUE
):

    if not guild:
        return

    channel_id = get_settings(
        guild.id
    ).get(
        "message_log_channel"
    )

    channel = get_message_channel(
        guild,
        channel_id
    )

    if channel:

        await safe_send(

            channel,

            embed=aura_embed(

                title,

                description[:4000],

                color,

                "💬"
            )
        )


# =========================================================
# WELCOME CARD
# =========================================================

def get_font(
    size,
    bold=False
):

    paths = [

        (
            "/usr/share/fonts/truetype/dejavu/"
            "DejaVuSans-Bold.ttf"
        )

        if bold

        else

        (
            "/usr/share/fonts/truetype/dejavu/"
            "DejaVuSans.ttf"
        )
    ]

    for path in paths:

        try:

            return ImageFont.truetype(
                path,
                size
            )

        except Exception:
            pass

    return ImageFont.load_default()


async def create_welcome_card(member):

    image = Image.new(

        "RGB",

        (1000, 360),

        (18, 8, 32)
    )

    draw = ImageDraw.Draw(image)

    draw.ellipse(

        (650, -100, 1150, 400),

        fill=(85, 25, 145)
    )

    draw.rounded_rectangle(

        (20, 20, 980, 340),

        radius=30,

        outline=(170, 90, 255),

        width=5
    )

    avatar_bytes = await member.display_avatar.read()

    avatar = Image.open(
        io.BytesIO(avatar_bytes)
    ).convert("RGB")

    avatar = avatar.resize(
        (190, 190)
    )

    mask = Image.new(

        "L",

        (190, 190),

        0
    )

    ImageDraw.Draw(mask).ellipse(

        (0, 0, 189, 189),

        fill=255
    )

    image.paste(

        avatar,

        (70, 85),

        mask
    )

    draw.text(

        (300, 70),

        "WELCOME TO",

        font=get_font(
            38,
            True
        ),

        fill=(190, 145, 255)
    )

    draw.text(

        (300, 125),

        member.display_name[:22],

        font=get_font(
            56,
            True
        ),

        fill="white"
    )

    draw.text(

        (302, 210),

        member.guild.name[:35],

        font=get_font(30),

        fill=(225, 215, 240)
    )

    draw.text(

        (302, 265),

        f"Member #{member.guild.member_count}",

        font=get_font(26),

        fill=(190, 145, 255)
    )

    output = io.BytesIO()

    image.save(
        output,
        "PNG"
    )

    output.seek(0)

    return discord.File(

        output,

        filename="auraguard-welcome.png"
    )


async def send_welcome(
    member,
    channel,
    title="Welcome!"
):

    settings = get_settings(
        member.guild.id
    )

    embed = aura_embed(

        title,

        apply_placeholders(

            settings["welcome_message"],

            member
        ),

        AURA_PURPLE,

        "👋"
    )

    try:

        if settings.get(
            "welcome_image_enabled",
            True
        ):

            file = await create_welcome_card(
                member
            )

            embed.set_image(
                url="attachment://auraguard-welcome.png"
            )

            await safe_send(

                channel,

                embed=embed,

                file=file
            )

        else:

            await safe_send(
                channel,
                embed=embed
            )

    except Exception as error:

        print(
            "Welcome card error:",
            repr(error)
        )

        await safe_send(
            channel,
            embed=embed
        )


# =========================================================
# TICKETS
# =========================================================

class TicketView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

    @discord.ui.button(

        label="Open Ticket",

        style=discord.ButtonStyle.primary,

        emoji="🎫",

        custom_id="auraguard_open_ticket"
    )
    async def open_ticket(
        self,
        interaction,
        button
    ):

        guild = interaction.guild
        user = interaction.user

        if not guild:
            return

        settings = get_settings(
            guild.id
        )

        for channel in guild.text_channels:

            if channel.topic == (
                f"AURAGUARD_TICKET_OWNER={user.id}"
            ):

                await interaction.response.send_message(

                    f"🎫 You already have a ticket: "
                    f"{channel.mention}",

                    ephemeral=True
                )

                return

        overwrites = {

            guild.default_role:

                discord.PermissionOverwrite(
                    view_channel=False
                ),

            user:

                discord.PermissionOverwrite(

                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )
        }

        role_id = settings.get(
            "staff_role"
        )

        role = (

            guild.get_role(
                int(role_id)
            )

            if role_id

            else None
        )

        if role:

            overwrites[role] = (
                discord.PermissionOverwrite(

                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )
            )

        category_id = settings.get(
            "ticket_category"
        )

        category = (

            guild.get_channel(
                int(category_id)
            )

            if category_id

            else None
        )

        channel_name = (
            f"ticket-{user.name}"
            .lower()
            .replace(" ", "-")
        )[:90]

        channel = await guild.create_text_channel(

            channel_name,

            category=(
                category
                if isinstance(
                    category,
                    discord.CategoryChannel
                )
                else None
            ),

            overwrites=overwrites,

            topic=(
                f"AURAGUARD_TICKET_OWNER={user.id}"
            ),

            reason="AuraGuard ticket opened"
        )

        await safe_send(

            channel,

            content=user.mention,

            embed=aura_embed(

                "Ticket Opened",

                "A staff member will help you soon.\n\n"
                "Use the buttons below.",

                AURA_PURPLE,

                "🎫"
            ),

            view=TicketControls()
        )

        await interaction.response.send_message(

            f"🎫 Your ticket: {channel.mention}",

            ephemeral=True
        )

        await send_log(

            guild,

            "Ticket Opened",

            f"User: {user.mention}\n"
            f"Channel: {channel.mention}",

            AURA_BLUE
        )


class TicketControls(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

    @discord.ui.button(

        label="Claim",

        style=discord.ButtonStyle.success,

        emoji="🙋",

        custom_id="auraguard_claim_ticket"
    )
    async def claim_ticket(

        self,
        interaction,
        button
    ):

        if not is_staff(
            interaction.user
        ):

            await interaction.response.send_message(

                "❌ Only staff can claim tickets.",

                ephemeral=True
            )

            return

        channel_id = str(
            interaction.channel.id
        )

        current = data[
            "ticket_claims"
        ].get(
            channel_id
        )

        if (
            current
            and current != interaction.user.id
        ):

            await interaction.response.send_message(

                f"❌ Already claimed by <@{current}>.",

                ephemeral=True
            )

            return

        data[
            "ticket_claims"
        ][channel_id] = interaction.user.id

        save_data()

        await interaction.response.send_message(

            f"🙋 Ticket claimed by "
            f"{interaction.user.mention}."
        )

    @discord.ui.button(

        label="Transcript",

        style=discord.ButtonStyle.secondary,

        emoji="📄",

        custom_id="auraguard_transcript"
    )
    async def transcript(

        self,
        interaction,
        button
    ):

        if not is_staff(
            interaction.user
        ):

            await interaction.response.send_message(

                "❌ Only staff can create transcripts.",

                ephemeral=True
            )

            return

        await interaction.response.defer(
            ephemeral=True
        )

        lines = []

        async for message in (
            interaction.channel.history(
                oldest_first=True,
                limit=None
            )
        ):

            timestamp = message.created_at.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            content = (
                message.content
                or "[No text content]"
            )

            lines.append(

                f"[{timestamp}] "
                f"{message.author}: "
                f"{content}"
            )

        transcript = "\n".join(lines)

        file = discord.File(

            io.BytesIO(
                transcript.encode("utf-8")
            ),

            filename=(
                f"{interaction.channel.name}"
                "-transcript.txt"
            )
        )

        await interaction.followup.send(

            "📄 Transcript created.",

            file=file,

            ephemeral=True
        )

    @discord.ui.button(

        label="Close",

        style=discord.ButtonStyle.danger,

        emoji="🔒",

        custom_id="auraguard_close_ticket"
    )
    async def close_ticket(

        self,
        interaction,
        button
    ):

        if not is_staff(
            interaction.user
        ):

            await interaction.response.send_message(

                "❌ Only staff can close tickets.",

                ephemeral=True
            )

            return

        await interaction.response.send_message(

            "🔒 Closing ticket in **3 seconds**..."
        )

        await asyncio.sleep(3)

        data[
            "ticket_claims"
        ].pop(
            str(interaction.channel.id),
            None
        )

        save_data()

        await interaction.channel.delete(

            reason="AuraGuard ticket closed"
        )


# =========================================================
# GIVEAWAYS
# =========================================================

def giveaway_embed(
    giveaway_id,
    giveaway
):

    entries = data[
        "giveaway_entries"
    ].get(
        giveaway_id,
        {}
    )

    end = datetime.fromisoformat(
        giveaway["end_time"]
    )

    return aura_embed(

        "GIVEAWAY",

        f"🎁 **Prize:** {giveaway['prize']}\n"
        f"🏆 **Winners:** {giveaway['winners']}\n"
        f"🆔 **Giveaway ID:** `{giveaway_id}`\n"
        f"👥 **Participants:** {len(entries)}\n"
        f"🎟️ **Total Entries:** "
        f"{sum(entries.values())}\n"
        f"👤 **Hosted by:** "
        f"<@{giveaway['created_by']}>\n"
        f"⏰ **Ends:** "
        f"<t:{int(end.timestamp())}:R>\n\n"
        f"**Click Participate to enter!**",

        AURA_PURPLE,

        "🎉"
    )


class GiveawayView(
    discord.ui.View
):

    def __init__(
        self,
        giveaway_id
    ):

        super().__init__(
            timeout=None
        )

        self.giveaway_id = giveaway_id

        participate = discord.ui.Button(

            label="Participate",

            emoji="🎉",

            style=discord.ButtonStyle.success,

            custom_id=(
                "auraguard_giveaway_enter_"
                f"{giveaway_id}"
            )
        )

        participate.callback = self.enter

        self.add_item(participate)

        info = discord.ui.Button(

            label="Info",

            emoji="ℹ️",

            style=discord.ButtonStyle.secondary,

            custom_id=(
                "auraguard_giveaway_info_"
                f"{giveaway_id}"
            )
        )

        info.callback = self.info

        self.add_item(info)

    async def enter(
        self,
        interaction
    ):

        giveaway = data[
            "giveaways"
        ].get(
            self.giveaway_id
        )

        if not giveaway:

            await interaction.response.send_message(

                "❌ This giveaway is no longer active.",

                ephemeral=True
            )

            return

        if giveaway["guild"] != interaction.guild.id:

            await interaction.response.send_message(

                "❌ This giveaway belongs to another server.",

                ephemeral=True
            )

            return

        entries = data[
            "giveaway_entries"
        ].setdefault(

            self.giveaway_id,

            {}
        )

        user_id = str(
            interaction.user.id
        )

        if user_id in entries:

            await interaction.response.send_message(

                f"❌ You're already entered with "
                f"**{entries[user_id]} entries**.",

                ephemeral=True
            )

            return

        amount = 1

        settings = get_settings(
            interaction.guild.id
        )

        for role_id, bonus in settings.get(
            "giveaway_bonus_roles",
            {}
        ).items():

            try:

                role = interaction.guild.get_role(
                    int(role_id)
                )

                if (
                    role
                    and role
                    in interaction.user.roles
                ):

                    amount += int(bonus)

            except Exception:
                continue

        entries[user_id] = amount

        save_data()

        await interaction.response.send_message(

            f"🎉 You're entered with "
            f"**{amount} entries**!",

            ephemeral=True
        )

    async def info(
        self,
        interaction
    ):

        giveaway = data[
            "giveaways"
        ].get(
            self.giveaway_id
        )

        if not giveaway:

            await interaction.response.send_message(

                "❌ Giveaway no longer active.",

                ephemeral=True
            )

            return

        await interaction.response.send_message(

            embed=giveaway_embed(
                self.giveaway_id,
                giveaway
            ),

            ephemeral=True
        )


async def finish_giveaway(
    guild,
    channel,
    giveaway_id
):

    giveaway = data[
        "giveaways"
    ].get(
        giveaway_id
    )

    if not giveaway:
        return []

    entries = data[
        "giveaway_entries"
    ].get(
        giveaway_id,
        {}
    )

    winners = weighted_winners(

        entries,

        giveaway["winners"]
    )

    history = dict(giveaway)

    history["entries"] = dict(entries)

    history["winners_list"] = winners

    history["ended_at"] = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    data[
        "giveaway_history"
    ][giveaway_id] = history

    data[
        "giveaways"
    ].pop(
        giveaway_id,
        None
    )

    data[
        "giveaway_entries"
    ].pop(
        giveaway_id,
        None
    )

    save_data()

    if channel:

        if winners:

            mentions = " ".join(

                f"<@{winner}>"

                for winner in winners
            )

            await safe_send(

                channel,

                embed=aura_embed(

                    "Giveaway Winner!",

                    f"🎁 **Prize:** "
                    f"{history['prize']}\n\n"
                    f"🏆 {mentions}",

                    AURA_GREEN,

                    "🏆"
                )
            )

        else:

            await safe_send(

                channel,

                embed=aura_embed(

                    "Giveaway Ended",

                    f"🎁 **{history['prize']}**"
                    "\n\nNobody entered.",

                    AURA_YELLOW,

                    "🎉"
                )
            )

    return winners


# =========================================================
# COMMAND GROUPS
# =========================================================

welcome_group = app_commands.Group(
    name="welcome",
    description="Manage welcome messages."
)

leave_group = app_commands.Group(
    name="leave",
    description="Manage leave messages."
)

tickets_group = app_commands.Group(
    name="tickets",
    description="Manage AuraGuard tickets."
)

giveaway_group = app_commands.Group(
    name="giveaway",
    description="Manage giveaways."
)

automod_group = app_commands.Group(
    name="automod",
    description="Manage AuraGuard AutoMod."
)


# =========================================================
# WELCOME COMMANDS
# =========================================================

@welcome_group.command(
    name="setup",
    description="Set welcome channel and message."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def welcome_setup(
    interaction,
    channel: discord.abc.GuildChannel,
    message: str = (
        "Welcome {user} to {server}! 🛡️"
    )
):

    if not is_message_channel(channel):

        await interaction.response.send_message(

            "❌ Please select a normal text channel.",

            ephemeral=True
        )

        return

    settings = get_settings(
        interaction.guild.id
    )

    settings["welcome_channel"] = channel.id
    settings["welcome_message"] = message

    save_data()

    await interaction.response.send_message(

        f"✅ Welcome channel set to "
        f"{channel.mention}.",

        ephemeral=True
    )


@welcome_group.command(
    name="enable",
    description="Enable welcome messages."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def welcome_enable(interaction):

    settings = get_settings(
        interaction.guild.id
    )

    if not settings.get("welcome_channel"):

        await interaction.response.send_message(

            "❌ Run `/welcome setup` first.",

            ephemeral=True
        )

        return

    settings["welcome_enabled"] = True

    save_data()

    await interaction.response.send_message(

        "🟢 Welcome messages enabled.",

        ephemeral=True
    )


@welcome_group.command(
    name="disable",
    description="Disable welcome messages."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def welcome_disable(interaction):

    get_settings(
        interaction.guild.id
    )["welcome_enabled"] = False

    save_data()

    await interaction.response.send_message(

        "🔴 Welcome messages disabled.",

        ephemeral=True
    )


@welcome_group.command(
    name="image",
    description="Enable or disable welcome cards."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def welcome_image(
    interaction,
    enabled: bool
):

    get_settings(
        interaction.guild.id
    )["welcome_image_enabled"] = enabled

    save_data()

    await interaction.response.send_message(

        f"🖼️ Welcome cards "
        f"{'enabled' if enabled else 'disabled'}.",

        ephemeral=True
    )


@welcome_group.command(
    name="test",
    description="Test welcome message."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def welcome_test(interaction):

    channel_id = get_settings(
        interaction.guild.id
    ).get(
        "welcome_channel"
    )

    channel = get_message_channel(
        interaction.guild,
        channel_id
    )

    if not channel:

        await interaction.response.send_message(

            "❌ Run `/welcome setup` first.",

            ephemeral=True
        )

        return

    await interaction.response.defer(
        ephemeral=True
    )

    await send_welcome(

        interaction.user,
        channel,
        "Welcome Test"
    )

    await interaction.followup.send(

        "✅ Welcome test sent.",

        ephemeral=True
    )


# =========================================================
# LEAVE COMMANDS
# =========================================================

@leave_group.command(
    name="setup",
    description="Set leave channel and message."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def leave_setup(
    interaction,
    channel: discord.abc.GuildChannel,
    message: str = (
        "{user} has left {server}. 👋"
    )
):

    if not is_message_channel(channel):

        await interaction.response.send_message(

            "❌ Please select a normal text channel.",

            ephemeral=True
        )

        return

    settings = get_settings(
        interaction.guild.id
    )

    settings["leave_channel"] = channel.id
    settings["leave_message"] = message

    save_data()

    await interaction.response.send_message(

        f"✅ Leave channel set to "
        f"{channel.mention}.",

        ephemeral=True
    )


@leave_group.command(
    name="enable",
    description="Enable leave messages."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def leave_enable(interaction):

    settings = get_settings(
        interaction.guild.id
    )

    if not settings.get("leave_channel"):

        await interaction.response.send_message(

            "❌ Run `/leave setup` first.",

            ephemeral=True
        )

        return

    settings["leave_enabled"] = True

    save_data()

    await interaction.response.send_message(

        "🟢 Leave messages enabled.",

        ephemeral=True
    )


@leave_group.command(
    name="disable",
    description="Disable leave messages."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def leave_disable(interaction):

    get_settings(
        interaction.guild.id
    )["leave_enabled"] = False

    save_data()

    await interaction.response.send_message(

        "🔴 Leave messages disabled.",

        ephemeral=True
    )


# =========================================================
# TICKET COMMANDS
# =========================================================

@tickets_group.command(
    name="setup",
    description="Set ticket category."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def tickets_setup(
    interaction,
    category: discord.CategoryChannel
):

    get_settings(
        interaction.guild.id
    )["ticket_category"] = category.id

    save_data()

    await interaction.response.send_message(

        f"🎫 Ticket category set to "
        f"**{category.name}**.",

        ephemeral=True
    )


@tickets_group.command(
    name="panel",
    description="Send ticket panel."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def tickets_panel(interaction):

    await interaction.response.send_message(

        embed=aura_embed(

            "AuraGuard Support",

            "Need help?\n\n"
            "Click the button below "
            "to open a ticket.",

            AURA_PURPLE,

            "🎫"
        ),

        view=TicketView()
    )


# =========================================================
# INVITE CHANNEL
# =========================================================

@bot.tree.command(
    name="setinvitechannel",
    description="Set the channel for invite announcements."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def set_invite_channel(
    interaction,
    channel: discord.abc.GuildChannel
):

    if not is_message_channel(channel):

        await interaction.response.send_message(

            "❌ Please select a normal text channel "
            "for invite announcements.",

            ephemeral=True
        )

        return

    settings = get_settings(
        interaction.guild.id
    )

    settings["invite_channel"] = channel.id

    save_data()

    await interaction.response.send_message(

        f"📮 Invite announcements will now "
        f"be sent to {channel.mention}.",

        ephemeral=True
    )


# =========================================================
# INVITE COMMANDS
# =========================================================

@bot.tree.command(
    name="invites",
    description="Check invite count."
)
async def invites(
    interaction,
    member: discord.Member = None
):

    member = member or interaction.user

    invite_data = get_invite_data(
        interaction.guild.id
    )

    user_data = invite_data.get(

        str(member.id),

        {}
    )

    total = user_data.get(
        "total",
        0
    )

    regular = user_data.get(
        "regular",
        0
    )

    await interaction.response.send_message(

        embed=aura_embed(

            "Invite Information",

            f"👤 **Member:** {member.mention}\n"
            f"📨 **Total Invites:** "
            f"**{total}**\n"
            f"✅ **Regular Invites:** "
            f"**{regular}**",

            AURA_PURPLE,

            "📨"
        )
    )


@bot.tree.command(
    name="inviteleaderboard",
    description="Show invite leaderboard."
)
async def invite_leaderboard(interaction):

    invite_data = get_invite_data(
        interaction.guild.id
    )

    sorted_invites = sorted(

        invite_data.items(),

        key=lambda item:
            item[1].get(
                "total",
                0
            ),

        reverse=True
    )

    if not sorted_invites:

        await interaction.response.send_message(

            embed=aura_embed(

                "Invite Leaderboard",

                "No invite data has been recorded yet.",

                AURA_PURPLE,

                "🏆"
            )
        )

        return

    lines = []

    for position, (
        user_id,
        user_data
    ) in enumerate(
        sorted_invites[:10],
        1
    ):

        lines.append(

            f"**{position}.** "
            f"<@{user_id}> — "
            f"**{user_data.get('total', 0)} "
            f"invites**"
        )

    await interaction.response.send_message(

        embed=aura_embed(

            "Invite Leaderboard",

            "\n".join(lines),

            AURA_PURPLE,

            "🏆"
        )
    )


# =========================================================
# SETTINGS COMMANDS
# =========================================================

@bot.tree.command(
    name="ping",
    description="Check AuraGuard latency."
)
async def ping(interaction):

    await interaction.response.send_message(

        embed=aura_embed(

            "AuraGuard Online",

            f"⚡ Pong!\n"
            f"Latency: "
            f"**{round(bot.latency * 1000)}ms**",

            AURA_PURPLE,

            "⚡"
        ),

        ephemeral=True
    )


@bot.tree.command(
    name="setstaffrole",
    description="Set staff role."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def set_staff_role(
    interaction,
    role: discord.Role
):

    get_settings(
        interaction.guild.id
    )["staff_role"] = role.id

    save_data()

    await interaction.response.send_message(

        f"🛡️ Staff role set to "
        f"{role.mention}.",

        ephemeral=True
    )


@bot.tree.command(
    name="setlogchannel",
    description="Set moderation log channel."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def set_log_channel(
    interaction,
    channel: discord.abc.GuildChannel
):

    if not is_message_channel(channel):

        await interaction.response.send_message(

            "❌ Please select a normal text channel.",

            ephemeral=True
        )

        return

    get_settings(
        interaction.guild.id
    )["log_channel"] = channel.id

    save_data()

    await interaction.response.send_message(

        f"📋 Log channel set to "
        f"{channel.mention}.",

        ephemeral=True
    )


@bot.tree.command(
    name="setmessagelog",
    description="Set message log channel."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def set_message_log(
    interaction,
    channel: discord.abc.GuildChannel
):

    if not is_message_channel(channel):

        await interaction.response.send_message(

            "❌ Please select a normal text channel.",

            ephemeral=True
        )

        return

    get_settings(
        interaction.guild.id
    )["message_log_channel"] = channel.id

    save_data()

    await interaction.response.send_message(

        f"💬 Message log set to "
        f"{channel.mention}.",

        ephemeral=True
    )


# =========================================================
# AUTOMOD COMMANDS
# =========================================================

@automod_group.command(
    name="enable",
    description="Enable blocked-word AutoMod."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def automod_enable(interaction):

    get_automod(
        interaction.guild.id
    )["enabled"] = True

    save_data()

    await interaction.response.send_message(

        "🛡️ AutoMod enabled.",

        ephemeral=True
    )


@automod_group.command(
    name="disable",
    description="Disable blocked-word AutoMod."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def automod_disable(interaction):

    get_automod(
        interaction.guild.id
    )["enabled"] = False

    save_data()

    await interaction.response.send_message(

        "🔴 AutoMod disabled.",

        ephemeral=True
    )


@automod_group.command(
    name="addword",
    description="Add blocked word."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def automod_add_word(
    interaction,
    word: str
):

    automod = get_automod(
        interaction.guild.id
    )

    word = word.strip()

    if not word:

        await interaction.response.send_message(

            "❌ Invalid word.",

            ephemeral=True
        )

        return

    if word.lower() in [

        item.lower()

        for item in automod[
            "blocked_words"
        ]
    ]:

        await interaction.response.send_message(

            "❌ That word is already blocked.",

            ephemeral=True
        )

        return

    automod[
        "blocked_words"
    ].append(word)

    save_data()

    await interaction.response.send_message(

        f"🛡️ Added `{word}`.",

        ephemeral=True
    )


@automod_group.command(
    name="removeword",
    description="Remove blocked word."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def automod_remove_word(
    interaction,
    word: str
):

    automod = get_automod(
        interaction.guild.id
    )

    match = next(

        (

            item

            for item in automod[
                "blocked_words"
            ]

            if item.lower() == word.lower()

        ),

        None
    )

    if not match:

        await interaction.response.send_message(

            "❌ That word is not blocked.",

            ephemeral=True
        )

        return

    automod[
        "blocked_words"
    ].remove(match)

    save_data()

    await interaction.response.send_message(

        f"✅ Removed `{match}`.",

        ephemeral=True
    )


@automod_group.command(
    name="antispam",
    description="Enable or disable anti-spam."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def automod_antispam(
    interaction,
    enabled: bool
):

    get_automod(
        interaction.guild.id
    )["anti_spam"] = enabled

    save_data()

    await interaction.response.send_message(

        f"🚨 Anti-spam "
        f"{'enabled' if enabled else 'disabled'}.",

        ephemeral=True
    )


# =========================================================
# MODERATION HELPERS
# =========================================================

async def hierarchy_check(
    interaction,
    member
):

    if member == interaction.user:

        await interaction.response.send_message(

            "❌ You can't moderate yourself.",

            ephemeral=True
        )

        return False

    if member == interaction.guild.owner:

        await interaction.response.send_message(

            "❌ You can't moderate the server owner.",

            ephemeral=True
        )

        return False

    if (

        interaction.user != interaction.guild.owner

        and member.top_role
        >= interaction.user.top_role

    ):

        await interaction.response.send_message(

            "❌ That member has an equal "
            "or higher role.",

            ephemeral=True
        )

        return False

    if (
        member.top_role
        >= interaction.guild.me.top_role
    ):

        await interaction.response.send_message(

            "❌ My role is not high enough.",

            ephemeral=True
        )

        return False

    return True


# =========================================================
# MODERATION COMMANDS
# =========================================================

@bot.tree.command(
    name="kick",
    description="Kick a member."
)
@app_commands.checks.has_permissions(
    kick_members=True
)
async def kick(
    interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):

    if not await hierarchy_check(
        interaction,
        member
    ):
        return

    await member.kick(
        reason=reason
    )

    await interaction.response.send_message(

        f"👢 Kicked {member.mention}."
    )

    await send_log(

        interaction.guild,

        "Member Kicked",

        f"Member: {member}\n"
        f"Moderator: {interaction.user}\n"
        f"Reason: {reason}",

        AURA_RED
    )


@bot.tree.command(
    name="ban",
    description="Ban a member."
)
@app_commands.checks.has_permissions(
    ban_members=True
)
async def ban(
    interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):

    if not await hierarchy_check(
        interaction,
        member
    ):
        return

    await member.ban(
        reason=reason
    )

    await interaction.response.send_message(

        f"🔨 Banned {member.mention}."
    )

    await send_log(

        interaction.guild,

        "Member Banned",

        f"Member: {member}\n"
        f"Moderator: {interaction.user}\n"
        f"Reason: {reason}",

        AURA_RED
    )


@bot.tree.command(
    name="unban",
    description="Unban a user using their ID."
)
@app_commands.checks.has_permissions(
    ban_members=True
)
async def unban(
    interaction,
    user_id: str
):

    try:

        user = await bot.fetch_user(
            int(user_id)
        )

        await interaction.guild.unban(
            user
        )

        await interaction.response.send_message(

            f"🔓 **{user}** has been unbanned."
        )

    except Exception:

        await interaction.response.send_message(

            "❌ User not found or not banned.",

            ephemeral=True
        )


@bot.tree.command(
    name="timeout",
    description="Timeout a member."
)
@app_commands.checks.has_permissions(
    moderate_members=True
)
async def timeout(
    interaction,
    member: discord.Member,
    minutes: int,
    reason: str = "No reason provided"
):

    if minutes < 1 or minutes > 40320:

        await interaction.response.send_message(

            "❌ Choose between 1 minute "
            "and 28 days.",

            ephemeral=True
        )

        return

    if not await hierarchy_check(
        interaction,
        member
    ):
        return

    await member.timeout(

        discord.utils.utcnow()
        + timedelta(minutes=minutes),

        reason=reason
    )

    await interaction.response.send_message(

        f"⏳ {member.mention} timed out "
        f"for **{minutes} minutes**."
    )


@bot.tree.command(
    name="untimeout",
    description="Remove a timeout."
)
@app_commands.checks.has_permissions(
    moderate_members=True
)
async def untimeout(
    interaction,
    member: discord.Member
):

    if not await hierarchy_check(
        interaction,
        member
    ):
        return

    await member.timeout(
        None
    )

    await interaction.response.send_message(

        f"🔓 Removed {member.mention}'s timeout."
    )


# =========================================================
# WARNINGS
# =========================================================

@bot.tree.command(
    name="warn",
    description="Warn a member."
)
@app_commands.checks.has_permissions(
    moderate_members=True
)
async def warn(
    interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):

    warnings_list = data[
        "warnings"
    ].setdefault(

        str(interaction.guild.id),

        {}

    ).setdefault(

        str(member.id),

        []
    )

    warnings_list.append({

        "reason": reason,

        "moderator":
            interaction.user.id,

        "time":
            datetime.now(
                timezone.utc
            ).isoformat()
    })

    save_data()

    await interaction.response.send_message(

        f"⚠️ Warned {member.mention}.\n"
        f"Total warnings: "
        f"**{len(warnings_list)}**"
    )

    await send_log(

        interaction.guild,

        "Member Warned",

        f"Member: {member.mention}\n"
        f"Moderator: "
        f"{interaction.user.mention}\n"
        f"Reason: {reason}",

        AURA_YELLOW
    )


@bot.tree.command(
    name="warnings",
    description="View member warnings."
)
@app_commands.checks.has_permissions(
    moderate_members=True
)
async def warnings(
    interaction,
    member: discord.Member
):

    member_warnings = data[
        "warnings"
    ].get(

        str(interaction.guild.id),

        {}

    ).get(

        str(member.id),

        []
    )

    if not member_warnings:

        await interaction.response.send_message(

            f"✅ {member.mention} has no warnings.",

            ephemeral=True
        )

        return

    lines = []

    for index, warning in enumerate(
        member_warnings,
        1
    ):

        lines.append(

            f"**{index}.** "
            f"{warning['reason']} — "
            f"<@{warning['moderator']}>"
        )

    await interaction.response.send_message(

        embed=aura_embed(

            f"Warnings • {member}",

            "\n".join(lines)[:4000],

            AURA_YELLOW,

            "⚠️"
        ),

        ephemeral=True
    )


@bot.tree.command(
    name="clearwarnings",
    description="Clear all warnings."
)
@app_commands.checks.has_permissions(
    moderate_members=True
)
async def clear_warnings(
    interaction,
    member: discord.Member
):

    guild_warnings = data[
        "warnings"
    ].setdefault(

        str(interaction.guild.id),

        {}
    )

    old_count = len(

        guild_warnings.get(
            str(member.id),
            []
        )
    )

    guild_warnings[
        str(member.id)
    ] = []

    save_data()

    await interaction.response.send_message(

        f"🗑️ Cleared **{old_count}** "
        f"warnings from {member.mention}."
    )


# =========================================================
# MESSAGE MANAGEMENT
# =========================================================

@bot.tree.command(
    name="clear",
    description="Delete messages."
)
@app_commands.checks.has_permissions(
    manage_messages=True
)
async def clear(
    interaction,
    amount: int
):

    if amount < 1 or amount > 100:

        await interaction.response.send_message(

            "❌ Choose between 1 and 100.",

            ephemeral=True
        )

        return

    if not isinstance(
        interaction.channel,
        discord.TextChannel
    ):

        await interaction.response.send_message(

            "❌ This command must be used "
            "in a text channel.",

            ephemeral=True
        )

        return

    await interaction.response.defer(
        ephemeral=True
    )

    deleted = await interaction.channel.purge(
        limit=amount
    )

    await interaction.followup.send(

        f"🧹 Deleted "
        f"**{len(deleted)} messages**.",

        ephemeral=True
    )


@bot.tree.command(
    name="lock",
    description="Lock a text channel."
)
@app_commands.checks.has_permissions(
    manage_channels=True
)
async def lock(
    interaction,
    channel: discord.TextChannel = None
):

    target = (
        channel
        or interaction.channel
    )

    if not isinstance(
        target,
        discord.TextChannel
    ):

        await interaction.response.send_message(

            "❌ Text channels only.",

            ephemeral=True
        )

        return

    await target.set_permissions(

        interaction.guild.default_role,

        send_messages=False
    )

    await interaction.response.send_message(

        f"🔒 {target.mention} locked."
    )


@bot.tree.command(
    name="unlock",
    description="Unlock a text channel."
)
@app_commands.checks.has_permissions(
    manage_channels=True
)
async def unlock(
    interaction,
    channel: discord.TextChannel = None
):

    target = (
        channel
        or interaction.channel
    )

    if not isinstance(
        target,
        discord.TextChannel
    ):

        await interaction.response.send_message(

            "❌ Text channels only.",

            ephemeral=True
        )

        return

    await target.set_permissions(

        interaction.guild.default_role,

        send_messages=None
    )

    await interaction.response.send_message(

        f"🔓 {target.mention} unlocked."
    )


# =========================================================
# SERVER INFO
# =========================================================

@bot.tree.command(
    name="serverinfo",
    description="Show server information."
)
async def server_info(interaction):

    guild = interaction.guild

    owner = guild.owner

    owner_text = (
        owner.mention
        if owner
        else "Unknown"
    )

    embed = aura_embed(

        guild.name,

        f"👑 **Owner:** {owner_text}\n"
        f"👥 **Members:** {guild.member_count}\n"
        f"💬 **Channels:** {len(guild.channels)}\n"
        f"🎭 **Roles:** {len(guild.roles)}\n"
        f"🆔 **Server ID:** `{guild.id}`",

        AURA_PURPLE,

        "🏠"
    )

    if guild.icon:

        embed.set_thumbnail(
            url=guild.icon.url
        )

    await interaction.response.send_message(
        embed=embed
    )


@bot.tree.command(
    name="userinfo",
    description="Show member information."
)
async def user_info(
    interaction,
    member: discord.Member = None
):

    member = member or interaction.user

    joined_server = (

        f"<t:{int(member.joined_at.timestamp())}:R>"

        if member.joined_at

        else "Unknown"
    )

    embed = aura_embed(

        "User Information",

        f"👤 **User:** {member.mention}\n"
        f"🆔 **ID:** `{member.id}`\n"
        f"📅 **Joined Discord:** "
        f"<t:{int(member.created_at.timestamp())}:R>\n"
        f"📥 **Joined Server:** "
        f"{joined_server}",

        AURA_PURPLE,

        "👤"
    )

    embed.set_thumbnail(
        url=member.display_avatar.url
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# GIVEAWAY COMMANDS
# =========================================================

@giveaway_group.command(
    name="start",
    description="Start a giveaway."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def giveaway_start(
    interaction,
    prize: str,
    minutes: int,
    winners: int = 1
):

    if minutes < 1 or winners < 1:

        await interaction.response.send_message(

            "❌ Minutes and winners "
            "must be at least 1.",

            ephemeral=True
        )

        return

    giveaway_id = make_unique_id(
        data["giveaways"]
    )

    end = (

        datetime.now(
            timezone.utc
        )

        + timedelta(minutes=minutes)
    )

    data[
        "giveaways"
    ][giveaway_id] = {

        "guild":
            interaction.guild.id,

        "channel":
            interaction.channel.id,

        "prize":
            prize,

        "winners":
            winners,

        "end_time":
            end.isoformat(),

        "created_by":
            interaction.user.id
    }

    data[
        "giveaway_entries"
    ][giveaway_id] = {}

    save_data()

    await interaction.response.send_message(

        embed=giveaway_embed(

            giveaway_id,

            data[
                "giveaways"
            ][giveaway_id]
        ),

        view=GiveawayView(
            giveaway_id
        )
    )


@giveaway_group.command(
    name="end",
    description="End giveaway early."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def giveaway_end(
    interaction,
    giveaway_id: str
):

    giveaway = data[
        "giveaways"
    ].get(
        giveaway_id
    )

    if (

        not giveaway

        or giveaway["guild"]
        != interaction.guild.id

    ):

        await interaction.response.send_message(

            "❌ Giveaway not found.",

            ephemeral=True
        )

        return

    await interaction.response.defer()

    channel = get_message_channel(

        interaction.guild,

        giveaway["channel"]
    )

    await finish_giveaway(

        interaction.guild,

        channel,

        giveaway_id
    )


@giveaway_group.command(
    name="reroll",
    description="Reroll a finished giveaway."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def giveaway_reroll(
    interaction,
    giveaway_id: str
):

    history = data[
        "giveaway_history"
    ].get(
        giveaway_id
    )

    if not history:

        await interaction.response.send_message(

            "❌ Giveaway history not found.",

            ephemeral=True
        )

        return

    if history.get(
        "guild"
    ) != interaction.guild.id:

        await interaction.response.send_message(

            "❌ That giveaway belongs "
            "to another server.",

            ephemeral=True
        )

        return

    entries = history.get(
        "entries",
        {}
    )

    previous_winners = set(
        history.get(
            "winners_list",
            []
        )
    )

    available = {

        user_id: weight

        for user_id, weight
        in entries.items()

        if user_id
        not in previous_winners
    }

    if not available:

        await interaction.response.send_message(

            "❌ No eligible users remain.",

            ephemeral=True
        )

        return

    winner = weighted_winners(
        available,
        1
    )

    if not winner:

        await interaction.response.send_message(

            "❌ Could not select a winner.",

            ephemeral=True
        )

        return

    history[
        "winners_list"
    ].append(
        winner[0]
    )

    save_data()

    await interaction.response.send_message(

        embed=aura_embed(

            "Giveaway Reroll",

            f"🎁 **Prize:** "
            f"{history['prize']}\n\n"
            f"🏆 New winner: "
            f"<@{winner[0]}>",

            AURA_GREEN,

            "🎉"
        )
    )


# =========================================================
# EVENTS
# =========================================================

@bot.event
async def on_ready():

    print("=" * 45)

    print(
        f"AuraGuard V8 online as "
        f"{bot.user}"
    )

    print(
        f"Bot ID: {bot.user.id}"
    )

    print("=" * 45)

    await bot.change_presence(

        status=discord.Status.online,

        activity=discord.Activity(

            type=
            discord.ActivityType.watching,

            name="over your server 🛡️"
        )
    )

    if not getattr(
        bot,
        "_auraguard_views_loaded",
        False
    ):

        bot.add_view(
            TicketView()
        )

        bot.add_view(
            TicketControls()
        )

        for giveaway_id in list(
            data["giveaways"].keys()
        ):

            bot.add_view(
                GiveawayView(
                    giveaway_id
                )
            )

        bot._auraguard_views_loaded = True

    # Load invite cache for every server
    for guild in bot.guilds:

        try:

            invites_list = await guild.invites()

            invite_cache[guild.id] = {

                invite.code:
                    invite.uses

                for invite
                in invites_list
            }

            print(
                f"Loaded invite cache for "
                f"{guild.name}"
            )

        except Exception as error:

            print(

                f"Could not load invites for "
                f"{guild.name}: {error}"
            )

    if not giveaway_loop.is_running():

        giveaway_loop.start()

    try:

        synced = await bot.tree.sync()

        print(
            f"Synced {len(synced)} "
            f"slash commands."
        )

    except Exception as error:

        print(
            "Slash command sync error:",
            repr(error)
        )


# =========================================================
# MEMBER JOIN + INVITES
# =========================================================

@bot.event
async def on_member_join(member):

    guild = member.guild

    inviter = None

    try:

        old_invites = invite_cache.get(
            guild.id,
            {}
        )

        new_invites = await guild.invites()

        for invite in new_invites:

            old_uses = old_invites.get(
                invite.code,
                0
            )

            if (
                invite.uses
                and invite.uses > old_uses
            ):

                inviter = invite.inviter

                break

        invite_cache[guild.id] = {

            invite.code:
                invite.uses

            for invite
            in new_invites
        }

    except Exception as error:

        print(
            "Invite tracking error:",
            repr(error
        )

    # Invite tracking
    if (
        inviter
        and inviter.id != member.id
    ):

        invite_data = get_invite_data(
            guild.id
        )

        inviter_data = invite_data.setdefault(

            str(inviter.id),

            {

                "total": 0,

                "regular": 0
            }
        )

        inviter_data["total"] += 1
        inviter_data["regular"] += 1

        save_data()

        invite_channel_id = get_settings(
            guild.id
        ).get(
            "invite_channel"
        )

        invite_channel = get_message_channel(
            guild,
            invite_channel_id
        )

        if invite_channel:

            await safe_send(

                invite_channel,

                embed=aura_embed(

                    "Member Invited",

                    f"👤 {member.mention} "
                    f"joined the server!\n\n"
                    f"📨 **Invited by:** "
                    f"{inviter.mention}\n"
                    f"📊 **Total Invites:** "
                    f"**{inviter_data['total']}**",

                    AURA_PURPLE,

                    "📮"
                )
            )

        await send_log(

            guild,

            "Member Joined",

            f"Member: {member.mention}\n"
            f"Invited By: {inviter.mention}\n"
            f"Total Invites: "
            f"**{inviter_data['total']}**",

            AURA_GREEN
        )

    else:

        await send_log(

            guild,

            "Member Joined",

            f"Member: {member.mention}\n"
            f"Inviter: **Unknown**",

            AURA_GREEN
        )

    # Welcome
    settings = get_settings(
        guild.id
    )

    if settings.get(
        "welcome_enabled"
    ):

        channel = get_message_channel(

            guild,

            settings.get(
                "welcome_channel"
            )
        )

        if channel:

            await send_welcome(
                member,
                channel
            )


# =========================================================
# MEMBER LEAVE
# =========================================================

@bot.event
async def on_member_remove(member):

    settings = get_settings(
        member.guild.id
    )

    if settings.get(
        "leave_enabled"
    ):

        channel = get_message_channel(

            member.guild,

            settings.get(
                "leave_channel"
            )
        )

        if channel:

            await safe_send(

                channel,

                embed=aura_embed(

                    "Member Left",

                    apply_placeholders(

                        settings[
                            "leave_message"
                        ],

                        member
                    ),

                    AURA_YELLOW,

                    "🚪"
                )
            )

    await send_log(

        member.guild,

        "Member Left",

        f"Member: {member}\n"
        f"ID: `{member.id}`",

        AURA_YELLOW
    )


# =========================================================
# INVITE EVENTS
# =========================================================

@bot.event
async def on_invite_create(invite):

    try:

        invite_cache.setdefault(

            invite.guild.id,

            {}
        )[invite.code] = invite.uses

    except Exception:
        pass


@bot.event
async def on_invite_delete(invite):

    try:

        invite_cache.setdefault(

            invite.guild.id,

            {}

        ).pop(
            invite.code,
            None
        )

    except Exception:
        pass


# =========================================================
# MESSAGE EVENTS + AUTOMOD
# =========================================================

@bot.event
async def on_message(message):

    if (
        message.author.bot
        or not message.guild
    ):

        return

    automod = get_automod(
        message.guild.id
    )

    # -------------------------------
    # ANTI-SPAM
    # -------------------------------

    if automod.get(
        "anti_spam"
    ):

        key = (
            message.guild.id,
            message.author.id
        )

        now = datetime.now(
            timezone.utc
        ).timestamp()

        cache = message_cache[key]

        cache.append(now)

        spam_seconds = automod.get(
            "spam_seconds",
            5
        )

        while (

            cache

            and now - cache[0]
            > spam_seconds

        ):

            cache.popleft()

        spam_limit = automod.get(
            "spam_limit",
            6
        )

        if len(cache) >= spam_limit:

            try:
                await message.delete()

            except Exception:
                pass

            await safe_send(

                message.channel,

                f"🚨 {message.author.mention}, "
                f"please slow down.",

                delete_after=5
            )

            cache.clear()

            await send_log(

                message.guild,

                "Anti-Spam Action",

                f"Member: "
                f"{message.author.mention}\n"
                f"Channel: "
                f"{message.channel.mention}",

                AURA_RED
            )

            return

    # -------------------------------
    # BLOCKED WORDS
    # -------------------------------

    if automod.get(
        "enabled"
    ):

        lower_content = (
            message.content.lower()
        )

        for word in automod.get(
            "blocked_words",
            []
        ):

            if word.lower() in lower_content:

                try:
                    await message.delete()

                except Exception:
                    pass

                await safe_send(

                    message.channel,

                    f"⚠️ "
                    f"{message.author.mention}, "
                    f"that message contains "
                    f"a blocked word.",

                    delete_after=5
                )

                await send_log(

                    message.guild,

                    "AutoMod Action",

                    f"Member: "
                    f"{message.author.mention}\n"
                    f"Channel: "
                    f"{message.channel.mention}\n"
                    f"Blocked Word: "
                    f"`{word}`",

                    AURA_RED
                )

                return

    # Message logging
    await send_message_log(

        message.guild,

        "Message Sent",

        f"**Author:** "
        f"{message.author.mention}\n"
        f"**Channel:** "
        f"{message.channel.mention}\n\n"
        f"**Message:**\n"
        f"{clean_message_content(message.content)}"
    )

    await bot.process_commands(
        message
    )


@bot.event
async def on_message_delete(message):

    if (
        message.author.bot
        or not message.guild
    ):

        return

    await send_message_log(

        message.guild,

        "Message Deleted",

        f"**Author:** "
        f"{message.author.mention}\n"
        f"**Channel:** "
        f"{message.channel.mention}\n\n"
        f"**Deleted Message:**\n"
        f"{clean_message_content(message.content)}",

        AURA_RED
    )


@bot.event
async def on_message_edit(
    before,
    after
):

    if (

        before.author.bot

        or not before.guild

        or before.content == after.content

    ):

        return

    await send_message_log(

        before.guild,

        "Message Edited",

        f"**Author:** "
        f"{before.author.mention}\n"
        f"**Channel:** "
        f"{before.channel.mention}\n\n"
        f"**Before:**\n"
        f"{clean_message_content(before.content)}"
        "\n\n"
        f"**After:**\n"
        f"{clean_message_content(after.content)}",

        AURA_YELLOW
    )


# =========================================================
# GIVEAWAY LOOP
# =========================================================

@tasks.loop(
    seconds=15
)
async def giveaway_loop():

    now = datetime.now(
        timezone.utc
    )

    for giveaway_id, giveaway in list(
        data[
            "giveaways"
        ].items()
    ):

        try:

            end = datetime.fromisoformat(
                giveaway["end_time"]
            )

        except Exception:

            continue

        if now >= end:

            guild = bot.get_guild(
                giveaway["guild"]
            )

            channel = (

                get_message_channel(

                    guild,

                    giveaway["channel"]
                )

                if guild

                else None
            )

            try:

                await finish_giveaway(

                    guild,

                    channel,

                    giveaway_id
                )

            except Exception as error:

                print(
                    "Giveaway error:",
                    repr(error)
                )


# =========================================================
# HELP COMMAND
# =========================================================

@bot.tree.command(
    name="help",
    description="Show AuraGuard commands."
)
async def help_command(interaction):

    text = """
**👋 Welcome**
`/welcome setup`
`/welcome enable`
`/welcome disable`
`/welcome image`
`/welcome test`

**🚪 Leave**
`/leave setup`
`/leave enable`
`/leave disable`

**🎫 Tickets**
`/tickets setup`
`/tickets panel`

**🎉 Giveaways**
`/giveaway start`
`/giveaway end`
`/giveaway reroll`

**📮 Invites**
`/setinvitechannel`
`/invites`
`/inviteleaderboard`

**🛡️ Moderation**
`/kick`
`/ban`
`/unban`
`/timeout`
`/untimeout`
`/warn`
`/warnings`
`/clearwarnings`
`/clear`
`/lock`
`/unlock`

**🤖 AutoMod**
`/automod enable`
`/automod disable`
`/automod addword`
`/automod removeword`
`/automod antispam`

**⚙️ Settings**
`/setstaffrole`
`/setlogchannel`
`/setmessagelog`

**ℹ️ Information**
`/serverinfo`
`/userinfo`
`/ping`
"""

    await interaction.response.send_message(

        embed=aura_embed(

            "AuraGuard V8 Commands",

            text,

            AURA_PURPLE,

            "🛡️"
        ),

        ephemeral=True
    )


# =========================================================
# REGISTER GROUPS
# =========================================================

for group in [

    welcome_group,

    leave_group,

    tickets_group,

    giveaway_group,

    automod_group
]:

    bot.tree.add_command(
        group
    )


# =========================================================
# ERROR HANDLER
# =========================================================

@bot.tree.error
async def on_app_command_error(
    interaction,
    error
):

    print(
        "Command error:",
        repr(error)
    )

    original = getattr(
        error,
        "original",
        error
    )

    if isinstance(
        error,
        app_commands.MissingPermissions
    ):

        message = (

            "❌ You don't have permission "
            "to use that command."
        )

    elif isinstance(
        error,
        app_commands.BotMissingPermissions
    ):

        message = (

            "❌ I don't have the required "
            "permissions to do that."
        )

    elif isinstance(
        error,
        app_commands.TransformerError
    ):

        message = (

            "❌ I couldn't use that option. "
            "Please select a valid channel, "
            "member, or role."
        )

    elif isinstance(
        original,
        discord.Forbidden
    ):

        message = (

            "❌ I don't have permission "
            "to do that."
        )

    else:

        message = (

            "❌ Something went wrong while "
            "running that command."
        )

    try:

        if interaction.response.is_done():

            await interaction.followup.send(

                message,

                ephemeral=True
            )

        else:

            await interaction.response.send_message(

                message,

                ephemeral=True
            )

    except Exception:
        pass


# =========================================================
# START BOT
# =========================================================

bot.run(TOKEN)
