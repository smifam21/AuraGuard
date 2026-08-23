# =========================================================
#                    AURAGUARD V7
# =========================================================
# Features:
# - Welcome & leave messages
# - Custom welcome cards
# - Advanced ticket system + transcripts
# - Giveaways + rerolls
# - Moderation + warnings
# - AutoMod: blocked words, spam, links, caps
# - Message logging
# - Invite tracking + leaderboard
# - Server & user info
# - Channel tools
# =========================================================

import discord
from discord import app_commands
from discord.ext import commands, tasks

import os
import json
import random
import asyncio
import io
import re
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
AURA_DARK = 0x2B124C

FOOTER = "AuraGuard V7 • Powered by Aura"

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
intents.messages = True

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
    "ticket_transcripts": {},
    "automod": {},
    "invites": {}
}


def deep_copy_default():
    return json.loads(json.dumps(DEFAULT_DATA))


def load_data():

    if not os.path.exists(DATA_FILE):
        return deep_copy_default()

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            loaded = json.load(file)

        for key, value in DEFAULT_DATA.items():

            if key not in loaded:
                loaded[key] = value

        return loaded

    except Exception as error:

        print(
            "Data load error:",
            error
        )

        return deep_copy_default()


data = load_data()


def save_data():

    temp_file = DATA_FILE + ".tmp"

    try:

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
            error
        )


# =========================================================
# CACHES
# =========================================================

invite_cache = {}

message_cache = defaultdict(
    lambda: deque(maxlen=10)
)


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
            "Welcome {user} to **{server}**! 🛡️",
        "welcome_image_enabled": True,

        # Leave
        "leave_enabled": False,
        "leave_channel": None,
        "leave_message":
            "{user} has left **{server}**. 👋",

        # Tickets
        "ticket_category": None,
        "ticket_log_channel": None,

        # Staff
        "staff_role": None,

        # Logs
        "log_channel": None,
        "message_log_channel": None,

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

        "anti_spam": True,

        "anti_links": False,

        "anti_caps": False,

        "spam_limit": 6,

        "spam_seconds": 7,

        "caps_percentage": 75
    }

    if guild_id not in data["automod"]:

        data["automod"][guild_id] = defaults.copy()

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


def is_staff(member):

    if member.guild_permissions.administrator:
        return True

    if member.guild_permissions.manage_guild:
        return True

    settings = get_settings(
        member.guild.id
    )

    role_id = settings.get(
        "staff_role"
    )

    if not role_id:
        return False

    role = member.guild.get_role(
        role_id
    )

    return bool(
        role and role in member.roles
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
            str(
                member.guild.member_count
            )
        )
        .replace(
            "{username}",
            member.display_name
        )
    )


def clean_message_content(content):

    if not content:
        return "*No text content*"

    return discord.utils.escape_markdown(
        content
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

    pool = {

        user_id: int(weight)

        for user_id, weight
        in entries.items()

        if int(weight) > 0
    }

    winners = []

    while pool and len(winners) < amount:

        winner = random.choices(

            list(pool.keys()),

            weights=list(
                pool.values()
            ),

            k=1

        )[0]

        winners.append(
            winner
        )

        pool.pop(
            winner
        )

    return winners


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

    settings = get_settings(
        guild.id
    )

    channel_id = settings.get(
        "log_channel"
    )

    channel = (
        guild.get_channel(channel_id)
        if channel_id
        else None
    )

    if isinstance(
        channel,
        discord.TextChannel
    ):

        try:

            await channel.send(

                embed=aura_embed(

                    title,

                    description[:4000],

                    color,

                    "📋"
                )
            )

        except Exception as error:

            print(
                "Log error:",
                error
            )


async def send_message_log(
    guild,
    title,
    description,
    color=AURA_BLUE
):

    if not guild:
        return

    settings = get_settings(
        guild.id
    )

    channel_id = settings.get(
        "message_log_channel"
    )

    channel = (
        guild.get_channel(channel_id)
        if channel_id
        else None
    )

    if isinstance(
        channel,
        discord.TextChannel
    ):

        try:

            await channel.send(

                embed=aura_embed(

                    title,

                    description[:4000],

                    color,

                    "💬"
                )
            )

        except Exception:
            pass


# =========================================================
# WELCOME CARD
# =========================================================

def get_font(
    size,
    bold=False
):

    paths = []

    if bold:

        paths.extend([

            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",

            "DejaVuSans-Bold.ttf"

        ])

    else:

        paths.extend([

            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",

            "DejaVuSans.ttf"

        ])

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

    width = 1000
    height = 360

    image = Image.new(

        "RGB",

        (width, height),

        (18, 8, 32)
    )

    draw = ImageDraw.Draw(
        image
    )

    # Decorative circles

    draw.ellipse(

        (700, -180, 1150, 300),

        fill=(72, 25, 120)
    )

    draw.ellipse(

        (800, 100, 1100, 430),

        fill=(42, 20, 80)
    )

    # Border

    draw.rounded_rectangle(

        (20, 20, 980, 340),

        radius=30,

        outline=(138, 43, 226),

        width=5
    )

    # Avatar

    avatar_bytes = await (
        member.display_avatar
        .replace(size=256)
        .read()
    )

    avatar = Image.open(
        io.BytesIO(
            avatar_bytes
        )
    ).convert(
        "RGB"
    )

    avatar = avatar.resize(
        (190, 190)
    )

    mask = Image.new(
        "L",
        (190, 190),
        0
    )

    ImageDraw.Draw(
        mask
    ).ellipse(
        (0, 0, 189, 189),
        fill=255
    )

    image.paste(

        avatar,

        (70, 85),

        mask
    )

    # Text

    draw.text(

        (300, 60),

        "WELCOME TO",

        font=get_font(
            38,
            True
        ),

        fill=(190, 145, 255)
    )

    draw.text(

        (300, 120),

        member.display_name[:22],

        font=get_font(
            55,
            True
        ),

        fill="white"
    )

    draw.text(

        (302, 210),

        member.guild.name[:35],

        font=get_font(
            30
        ),

        fill=(225, 215, 240)
    )

    draw.text(

        (302, 265),

        f"Member #{member.guild.member_count}",

        font=get_font(
            26
        ),

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

            settings[
                "welcome_message"
            ],

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

            welcome_file = await create_welcome_card(
                member
            )

            embed.set_image(
                url="attachment://auraguard-welcome.png"
            )

            await channel.send(

                embed=embed,

                file=welcome_file
            )

        else:

            await channel.send(
                embed=embed
            )

    except Exception:

        await channel.send(
            embed=embed
        )


# =========================================================
# TICKET TRANSCRIPT
# =========================================================

async def create_transcript(channel):

    lines = [

        f"AuraGuard Ticket Transcript",

        f"Channel: {channel.name}",

        f"Created: {datetime.now(timezone.utc).isoformat()}",

        "=" * 60,

        ""
    ]

    try:

        async for message in channel.history(
            limit=None,
            oldest_first=True
        ):

            timestamp = message.created_at.strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )

            content = (
                message.content
                or "[No text content]"
            )

            lines.append(

                f"[{timestamp}] "
                f"{message.author} "
                f"({message.author.id}):"

            )

            lines.append(
                content
            )

            if message.attachments:

                lines.append(
                    "Attachments:"
                )

                for attachment in message.attachments:

                    lines.append(
                        attachment.url
                    )

            lines.append("")

    except Exception as error:

        lines.append(
            f"Transcript error: {error}"
        )

    transcript = "\n".join(
        lines
    )

    output = io.BytesIO(
        transcript.encode(
            "utf-8"
        )
    )

    output.seek(0)

    return discord.File(

        output,

        filename=f"{channel.name}-transcript.txt"
    )


# =========================================================
# TICKET VIEWS
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
                f"AURAGUARD_TICKET_OWNER="
                f"{user.id}"
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

                    read_message_history=True,

                    attach_files=True,

                    embed_links=True
                )
        }

        staff_role = None

        if settings.get(
            "staff_role"
        ):

            staff_role = guild.get_role(
                settings["staff_role"]
            )

        if staff_role:

            overwrites[staff_role] = (
                discord.PermissionOverwrite(

                    view_channel=True,

                    send_messages=True,

                    read_message_history=True,

                    manage_messages=True
                )
            )

        category = None

        if settings.get(
            "ticket_category"
        ):

            possible_category = guild.get_channel(
                settings["ticket_category"]
            )

            if isinstance(
                possible_category,
                discord.CategoryChannel
            ):

                category = possible_category

        channel_name = (
            f"ticket-"
            f"{user.name}"
        ).lower()

        channel = await guild.create_text_channel(

            channel_name[:90],

            category=category,

            overwrites=overwrites,

            topic=(
                f"AURAGUARD_TICKET_OWNER="
                f"{user.id}"
            ),

            reason=(
                f"AuraGuard ticket opened "
                f"by {user}"
            )
        )

        await channel.send(

            content=user.mention,

            embed=aura_embed(

                "Ticket Opened",

                "Thanks for contacting the staff team!\n\n"
                "🔹 A staff member can claim your ticket.\n"
                "🔹 Please explain what you need help with.\n"
                "🔹 Use the buttons below when finished.",

                AURA_PURPLE,

                "🎫"
            ),

            view=TicketControls()
        )

        await interaction.response.send_message(

            f"🎫 Your ticket has been created: "
            f"{channel.mention}",

            ephemeral=True
        )

        await send_log(

            guild,

            "Ticket Opened",

            f"**User:** {user.mention}\n"
            f"**Channel:** {channel.mention}",

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

        if current:

            if current == interaction.user.id:

                await interaction.response.send_message(

                    "🙋 You already claimed this ticket.",

                    ephemeral=True
                )

            else:

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

        await send_log(

            interaction.guild,

            "Ticket Claimed",

            f"**Staff:** "
            f"{interaction.user.mention}\n"
            f"**Channel:** "
            f"{interaction.channel.mention}",

            AURA_GREEN
        )

    @discord.ui.button(

        label="Unclaim",

        style=discord.ButtonStyle.secondary,

        emoji="↩️",

        custom_id="auraguard_unclaim_ticket"

    )
    async def unclaim_ticket(
        self,
        interaction,
        button
    ):

        if not is_staff(
            interaction.user
        ):

            await interaction.response.send_message(

                "❌ Only staff can unclaim tickets.",

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

        if not current:

            await interaction.response.send_message(

                "❌ This ticket is not claimed.",

                ephemeral=True
            )

            return

        if (
            current != interaction.user.id
            and not interaction.user.guild_permissions.administrator
        ):

            await interaction.response.send_message(

                "❌ Only the staff member who claimed "
                "this ticket can unclaim it.",

                ephemeral=True
            )

            return

        data[
            "ticket_claims"
        ].pop(
            channel_id,
            None
        )

        save_data()

        await interaction.response.send_message(

            "↩️ Ticket is now unclaimed."
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

        channel = interaction.channel

        if not isinstance(
            channel,
            discord.TextChannel
        ):

            return

        owner_id = None

        if (
            channel.topic
            and channel.topic.startswith(
                "AURAGUARD_TICKET_OWNER="
            )
        ):

            try:

                owner_id = int(
                    channel.topic.split("=")[1]
                )

            except Exception:
                pass

        if owner_id:

            owner = interaction.guild.get_member(
                owner_id
            )

            if owner:

                await channel.set_permissions(

                    owner,

                    view_channel=True,

                    send_messages=False,

                    read_message_history=True
                )

        await interaction.response.send_message(

            "🔒 Ticket closed.\n"
            "Staff can reopen or delete it below.",

            view=ClosedTicketControls()
        )

        await send_log(

            interaction.guild,

            "Ticket Closed",

            f"**Staff:** "
            f"{interaction.user.mention}\n"
            f"**Channel:** "
            f"{channel.mention}",

            AURA_RED
        )


class ClosedTicketControls(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

    @discord.ui.button(

        label="Reopen",

        style=discord.ButtonStyle.success,

        emoji="🔓",

        custom_id="auraguard_reopen_ticket"

    )
    async def reopen_ticket(
        self,
        interaction,
        button
    ):

        if not is_staff(
            interaction.user
        ):

            await interaction.response.send_message(

                "❌ Only staff can reopen tickets.",

                ephemeral=True
            )

            return

        channel = interaction.channel

        if not isinstance(
            channel,
            discord.TextChannel
        ):

            return

        owner_id = None

        try:

            owner_id = int(
                channel.topic.split("=")[1]
            )

        except Exception:
            pass

        if owner_id:

            owner = interaction.guild.get_member(
                owner_id
            )

            if owner:

                await channel.set_permissions(

                    owner,

                    view_channel=True,

                    send_messages=True,

                    read_message_history=True
                )

        await interaction.response.send_message(

            "🔓 Ticket reopened."
        )

    @discord.ui.button(

        label="Transcript & Delete",

        style=discord.ButtonStyle.danger,

        emoji="🗑️",

        custom_id="auraguard_delete_ticket"

    )
    async def delete_ticket(
        self,
        interaction,
        button
    ):

        if not is_staff(
            interaction.user
        ):

            await interaction.response.send_message(

                "❌ Only staff can delete tickets.",

                ephemeral=True
            )

            return

        channel = interaction.channel

        if not isinstance(
            channel,
            discord.TextChannel
        ):

            return

        await interaction.response.defer()

        transcript = await create_transcript(
            channel
        )

        settings = get_settings(
            interaction.guild.id
        )

        log_channel = None

        ticket_log_id = settings.get(
            "ticket_log_channel"
        )

        if ticket_log_id:

            possible = interaction.guild.get_channel(
                ticket_log_id
            )

            if isinstance(
                possible,
                discord.TextChannel
            ):

                log_channel = possible

        if not log_channel:

            log_id = settings.get(
                "log_channel"
            )

            if log_id:

                possible = interaction.guild.get_channel(
                    log_id
                )

                if isinstance(
                    possible,
                    discord.TextChannel
                ):

                    log_channel = possible

        if log_channel:

            try:

                await log_channel.send(

                    embed=aura_embed(

                        "Ticket Deleted",

                        f"**Channel:** #{channel.name}\n"
                        f"**Deleted By:** "
                        f"{interaction.user.mention}",

                        AURA_RED,

                        "🗑️"
                    ),

                    file=transcript
                )

            except Exception:
                pass

        data[
            "ticket_claims"
        ].pop(
            str(channel.id),
            None
        )

        save_data()

        await asyncio.sleep(2)

        await channel.delete(
            reason="AuraGuard ticket deleted"
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
        f"🆔 **ID:** `{giveaway_id}`\n"
        f"👥 **Participants:** {len(entries)}\n"
        f"🎟️ **Total Entries:** "
        f"{sum(entries.values())}\n"
        f"👤 **Hosted By:** "
        f"<@{giveaway['created_by']}>\n"
        f"⏰ **Ends:** "
        f"<t:{int(end.timestamp())}:R>\n\n"
        f"Click **Participate** to enter!",

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

        enter_button = discord.ui.Button(

            label="Participate",

            emoji="🎉",

            style=discord.ButtonStyle.success,

            custom_id=(
                f"auraguard_giveaway_enter_"
                f"{giveaway_id}"
            )
        )

        enter_button.callback = self.enter

        self.add_item(
            enter_button
        )

        info_button = discord.ui.Button(

            label="Info",

            emoji="ℹ️",

            style=discord.ButtonStyle.secondary,

            custom_id=(
                f"auraguard_giveaway_info_"
                f"{giveaway_id}"
            )
        )

        info_button.callback = self.info

        self.add_item(
            info_button
        )

        entries_button = discord.ui.Button(

            label="My Entries",

            emoji="🎟️",

            style=discord.ButtonStyle.primary,

            custom_id=(
                f"auraguard_giveaway_entries_"
                f"{giveaway_id}"
            )
        )

        entries_button.callback = self.my_entries

        self.add_item(
            entries_button
        )

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

                f"🎟️ You're already entered with "
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

            role = interaction.guild.get_role(
                int(role_id)
            )

            if (
                role
                and role in interaction.user.roles
            ):

                amount += int(
                    bonus
                )

        entries[user_id] = amount

        save_data()

        await interaction.response.send_message(

            f"🎉 You're entered with "
            f"**{amount} "
            f"{'entry' if amount == 1 else 'entries'}**!",

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

                "❌ This giveaway is no longer active.",

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

    async def my_entries(
        self,
        interaction
    ):

        amount = data[
            "giveaway_entries"
        ].get(
            self.giveaway_id,
            {}
        ).get(
            str(interaction.user.id),
            0
        )

        await interaction.response.send_message(

            f"🎟️ You currently have "
            f"**{amount} "
            f"{'entry' if amount == 1 else 'entries'}**.",

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

    history = dict(
        giveaway
    )

    history["entries"] = dict(
        entries
    )

    history["winners_list"] = winners

    history["ended_at"] = datetime.now(
        timezone.utc
    ).isoformat()

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

            winner_mentions = " ".join(

                f"<@{winner}>"

                for winner in winners
            )

            await channel.send(

                embed=aura_embed(

                    "Giveaway Ended!",

                    f"🎁 **Prize:** "
                    f"{history['prize']}\n\n"
                    f"🏆 **Winner"
                    f"{'s' if len(winners) != 1 else ''}:**\n"
                    f"{winner_mentions}",

                    AURA_GREEN,

                    "🏆"
                )
            )

        else:

            await channel.send(

                embed=aura_embed(

                    "Giveaway Ended",

                    f"🎁 **Prize:** "
                    f"{history['prize']}\n\n"
                    f"Nobody entered this giveaway.",

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
    description="Manage AutoMod."
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
    channel: discord.TextChannel,
    message: str = "Welcome {user} to **{server}**! 🛡️"
):

    settings = get_settings(
        interaction.guild.id
    )

    settings["welcome_channel"] = channel.id

    settings["welcome_message"] = message

    save_data()

    await interaction.response.send_message(

        "✅ Welcome setup saved.\n\n"
        "Placeholders:\n"
        "`{user}` • `{username}` • `{server}` • "
        "`{member_count}`",

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

    if not settings.get(
        "welcome_channel"
    ):

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
    description="Test the welcome system."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def welcome_test(interaction):

    settings = get_settings(
        interaction.guild.id
    )

    channel = interaction.guild.get_channel(
        settings.get(
            "welcome_channel"
        )
    )

    if not isinstance(
        channel,
        discord.TextChannel
    ):

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

        f"✅ Welcome test sent to "
        f"{channel.mention}.",

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
    channel: discord.TextChannel,
    message: str = "{user} has left **{server}**. 👋"
):

    settings = get_settings(
        interaction.guild.id
    )

    settings["leave_channel"] = channel.id

    settings["leave_message"] = message

    save_data()

    await interaction.response.send_message(
        "✅ Leave setup saved.",
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

    if not settings.get(
        "leave_channel"
    ):

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
    description="Set the ticket category."
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
    name="setlog",
    description="Set the ticket transcript channel."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def tickets_setlog(
    interaction,
    channel: discord.TextChannel
):

    get_settings(
        interaction.guild.id
    )["ticket_log_channel"] = channel.id

    save_data()

    await interaction.response.send_message(

        f"📜 Ticket transcripts will be sent to "
        f"{channel.mention}.",

        ephemeral=True
    )


@tickets_group.command(
    name="panel",
    description="Send the ticket panel."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def tickets_panel(interaction):

    await interaction.response.send_message(

        embed=aura_embed(

            "AuraGuard Support",

            "Need help from the staff team?\n\n"
            "Click **Open Ticket** below and a "
            "private support channel will be created.",

            AURA_PURPLE,

            "🎫"
        ),

        view=TicketView()
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

    if minutes < 1 or minutes > 43200:

        await interaction.response.send_message(

            "❌ Choose between 1 minute and 30 days.",

            ephemeral=True
        )

        return

    if winners < 1 or winners > 20:

        await interaction.response.send_message(

            "❌ Choose between 1 and 20 winners.",

            ephemeral=True
        )

        return

    giveaway_id = make_unique_id(
        data["giveaways"]
    )

    end = datetime.now(
        timezone.utc
    ) + timedelta(
        minutes=minutes
    )

    data[
        "giveaways"
    ][giveaway_id] = {

        "guild": interaction.guild.id,

        "channel": interaction.channel.id,

        "prize": prize[:200],

        "winners": winners,

        "end_time": end.isoformat(),

        "created_by": interaction.user.id
    }

    data[
        "giveaway_entries"
    ][giveaway_id] = {}

    save_data()

    await interaction.response.send_message(

        embed=giveaway_embed(

            giveaway_id,

            data["giveaways"][giveaway_id]
        ),

        view=GiveawayView(
            giveaway_id
        )
    )


@giveaway_group.command(
    name="end",
    description="End a giveaway early."
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
        or giveaway["guild"] != interaction.guild.id
    ):

        await interaction.response.send_message(

            "❌ Active giveaway not found.",

            ephemeral=True
        )

        return

    await interaction.response.defer()

    channel = interaction.guild.get_channel(
        giveaway["channel"]
    )

    await finish_giveaway(

        interaction.guild,

        channel
        if isinstance(
            channel,
            discord.TextChannel
        )
        else None,

        giveaway_id
    )

    await interaction.followup.send(
        "✅ Giveaway ended."
    )


@giveaway_group.command(
    name="cancel",
    description="Cancel an active giveaway."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def giveaway_cancel(
    interaction,
    giveaway_id: str
):

    giveaway = data[
        "giveaways"
    ].get(
        giveaway_id
    )

    if not giveaway:

        await interaction.response.send_message(

            "❌ Active giveaway not found.",

            ephemeral=True
        )

        return

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

    await interaction.response.send_message(

        f"🗑️ Giveaway `{giveaway_id}` cancelled.",

        ephemeral=True
    )


@giveaway_group.command(
    name="reroll",
    description="Reroll winners for an ended giveaway."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def giveaway_reroll(
    interaction,
    giveaway_id: str,
    winners: int = 1
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

    entries = history.get(
        "entries",
        {}
    )

    new_winners = weighted_winners(
        entries,
        winners
    )

    if not new_winners:

        await interaction.response.send_message(

            "❌ There are no valid participants.",

            ephemeral=True
        )

        return

    mentions = " ".join(

        f"<@{user_id}>"

        for user_id in new_winners
    )

    await interaction.response.send_message(

        embed=aura_embed(

            "Giveaway Reroll",

            f"🎁 **Prize:** "
            f"{history['prize']}\n\n"
            f"🏆 **New Winner"
            f"{'s' if len(new_winners) != 1 else ''}:**\n"
            f"{mentions}",

            AURA_GREEN,

            "🎉"
        )
    )


# =========================================================
# AUTOMOD COMMANDS
# =========================================================

@automod_group.command(
    name="enable",
    description="Enable AuraGuard AutoMod."
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
        "🟢 AutoMod enabled.",
        ephemeral=True
    )


@automod_group.command(
    name="disable",
    description="Disable AuraGuard AutoMod."
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
    description="Add a blocked word."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def automod_addword(
    interaction,
    word: str
):

    automod = get_automod(
        interaction.guild.id
    )

    word = word.strip()

    if not word:

        await interaction.response.send_message(

            "❌ Enter a valid word.",

            ephemeral=True
        )

        return

    if any(

        item.lower() == word.lower()

        for item in automod[
            "blocked_words"
        ]
    ):

        await interaction.response.send_message(

            "❌ That word is already blocked.",

            ephemeral=True
        )

        return

    automod[
        "blocked_words"
    ].append(
        word
    )

    save_data()

    await interaction.response.send_message(

        f"🛡️ Added `{word}` to the blocked list.",

        ephemeral=True
    )


@automod_group.command(
    name="removeword",
    description="Remove a blocked word."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def automod_removeword(
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
    ].remove(
        match
    )

    save_data()

    await interaction.response.send_message(

        f"✅ Removed `{match}`.",

        ephemeral=True
    )


@automod_group.command(
    name="links",
    description="Enable or disable anti-link protection."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def automod_links(
    interaction,
    enabled: bool
):

    get_automod(
        interaction.guild.id
    )["anti_links"] = enabled

    save_data()

    await interaction.response.send_message(

        f"🔗 Anti-link protection "
        f"{'enabled' if enabled else 'disabled'}.",

        ephemeral=True
    )


@automod_group.command(
    name="caps",
    description="Enable or disable anti-caps protection."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def automod_caps(
    interaction,
    enabled: bool
):

    get_automod(
        interaction.guild.id
    )["anti_caps"] = enabled

    save_data()

    await interaction.response.send_message(

        f"🔠 Anti-caps protection "
        f"{'enabled' if enabled else 'disabled'}.",

        ephemeral=True
    )


@automod_group.command(
    name="spam",
    description="Configure anti-spam."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def automod_spam(
    interaction,
    enabled: bool,
    limit: int = 6,
    seconds: int = 7
):

    if limit < 2 or seconds < 1:

        await interaction.response.send_message(

            "❌ Invalid spam settings.",

            ephemeral=True
        )

        return

    automod = get_automod(
        interaction.guild.id
    )

    automod["anti_spam"] = enabled

    automod["spam_limit"] = limit

    automod["spam_seconds"] = seconds

    save_data()

    await interaction.response.send_message(

        f"📨 Anti-spam "
        f"{'enabled' if enabled else 'disabled'}.\n"
        f"Limit: **{limit} messages / {seconds} seconds**",

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
        and member.top_role >= interaction.user.top_role
    ):

        await interaction.response.send_message(

            "❌ That member has an equal or higher role.",

            ephemeral=True
        )

        return False

    if member.top_role >= interaction.guild.me.top_role:

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

        f"👢 Kicked {member.mention}.\n"
        f"Reason: **{reason}**"
    )

    await send_log(

        interaction.guild,

        "Member Kicked",

        f"**Member:** {member.mention}\n"
        f"**Moderator:** "
        f"{interaction.user.mention}\n"
        f"**Reason:** {reason}",

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

        f"🔨 Banned {member.mention}.\n"
        f"Reason: **{reason}**"
    )

    await send_log(

        interaction.guild,

        "Member Banned",

        f"**Member:** {member}\n"
        f"**Moderator:** "
        f"{interaction.user.mention}\n"
        f"**Reason:** {reason}",

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

        await send_log(

            interaction.guild,

            "Member Unbanned",

            f"**User:** {user}\n"
            f"**Moderator:** "
            f"{interaction.user.mention}",

            AURA_GREEN
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

            "❌ Choose between 1 minute and 28 days.",

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
        + timedelta(
            minutes=minutes
        ),

        reason=reason
    )

    await interaction.response.send_message(

        f"⏳ {member.mention} timed out for "
        f"**{minutes} minutes**."
    )

    await send_log(

        interaction.guild,

        "Member Timed Out",

        f"**Member:** {member.mention}\n"
        f"**Moderator:** "
        f"{interaction.user.mention}\n"
        f"**Duration:** {minutes} minutes\n"
        f"**Reason:** {reason}",

        AURA_YELLOW
    )


@bot.tree.command(
    name="untimeout",
    description="Remove a member's timeout."
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

    warnings = data[
        "warnings"
    ].setdefault(
        str(interaction.guild.id),
        {}
    ).setdefault(
        str(member.id),
        []
    )

    warning_id = make_unique_id(
        {
            warning.get("id"): warning
            for warning in warnings
            if warning.get("id")
        }
    )

    warnings.append({

        "id": warning_id,

        "reason": reason,

        "moderator": interaction.user.id,

        "time": datetime.now(
            timezone.utc
        ).isoformat()
    })

    save_data()

    await interaction.response.send_message(

        f"⚠️ Warned {member.mention}.\n"
        f"Warning ID: `{warning_id}`\n"
        f"Total warnings: **{len(warnings)}**"
    )

    await send_log(

        interaction.guild,

        "Member Warned",

        f"**Member:** {member.mention}\n"
        f"**Moderator:** "
        f"{interaction.user.mention}\n"
        f"**Reason:** {reason}\n"
        f"**Warning ID:** `{warning_id}`",

        AURA_YELLOW
    )


@bot.tree.command(
    name="warnings",
    description="View a member's warnings."
)
@app_commands.checks.has_permissions(
    moderate_members=True
)
async def warnings_command(
    interaction,
    member: discord.Member
):

    warnings = data[
        "warnings"
    ].get(
        str(interaction.guild.id),
        {}
    ).get(
        str(member.id),
        []
    )

    if not warnings:

        await interaction.response.send_message(

            f"✅ {member.mention} has no warnings.",

            ephemeral=True
        )

        return

    lines = []

    for index, warning in enumerate(
        warnings,
        1
    ):

        lines.append(

            f"**{index}.** "
            f"`{warning.get('id', 'N/A')}` — "
            f"{warning['reason']}\n"
            f"Moderator: "
            f"<@{warning['moderator']}>"
        )

    await interaction.response.send_message(

        embed=aura_embed(

            f"Warnings • {member}",

            "\n\n".join(
                lines
            )[:3900],

            AURA_YELLOW,

            "⚠️"
        ),

        ephemeral=True
    )


@bot.tree.command(
    name="clearwarnings",
    description="Clear all warnings for a member."
)
@app_commands.checks.has_permissions(
    moderate_members=True
)
async def clearwarnings(
    interaction,
    member: discord.Member
):

    guild_warnings = data[
        "warnings"
    ].setdefault(
        str(interaction.guild.id),
        {}
    )

    removed = len(
        guild_warnings.get(
            str(member.id),
            []
        )
    )

    guild_warnings.pop(
        str(member.id),
        None
    )

    save_data()

    await interaction.response.send_message(

        f"🧹 Cleared **{removed} warning(s)** "
        f"for {member.mention}."
    )


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

    await interaction.response.defer(
        ephemeral=True
    )

    deleted = await interaction.channel.purge(
        limit=amount
    )

    await interaction.followup.send(

        f"🧹 Deleted **{len(deleted)} messages**.",

        ephemeral=True
    )


# =========================================================
# CHANNEL COMMANDS
# =========================================================

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

    target = channel or interaction.channel

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

    target = channel or interaction.channel

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


@bot.tree.command(
    name="slowmode",
    description="Set channel slowmode."
)
@app_commands.checks.has_permissions(
    manage_channels=True
)
async def slowmode(
    interaction,
    seconds: int,
    channel: discord.TextChannel = None
):

    target = channel or interaction.channel

    if not isinstance(
        target,
        discord.TextChannel
    ):

        await interaction.response.send_message(

            "❌ Text channels only.",

            ephemeral=True
        )

        return

    if seconds < 0 or seconds > 21600:

        await interaction.response.send_message(

            "❌ Choose between 0 and 21600 seconds.",

            ephemeral=True
        )

        return

    await target.edit(
        slowmode_delay=seconds
    )

    await interaction.response.send_message(

        f"🐢 Slowmode set to "
        f"**{seconds} seconds** in "
        f"{target.mention}."
    )


# =========================================================
# INFORMATION COMMANDS
# =========================================================

@bot.tree.command(
    name="serverinfo",
    description="Show information about the server."
)
async def serverinfo(interaction):

    guild = interaction.guild

    embed = aura_embed(

        guild.name,

        f"👑 **Owner:** {guild.owner.mention}\n"
        f"👥 **Members:** {guild.member_count}\n"
        f"💬 **Channels:** {len(guild.channels)}\n"
        f"🎭 **Roles:** {len(guild.roles)}\n"
        f"🆔 **Server ID:** `{guild.id}`\n"
        f"📅 **Created:** "
        f"<t:{int(guild.created_at.timestamp())}:R>",

        AURA_PURPLE,

        "🏰"
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
    description="Show information about a member."
)
async def userinfo(
    interaction,
    member: discord.Member = None
):

    member = member or interaction.user

    roles = [

        role.mention

        for role in member.roles[1:]
    ]

    role_text = (
        " ".join(roles[:10])
        if roles
        else "None"
    )

    embed = aura_embed(

        f"User Information",

        f"👤 **User:** {member.mention}\n"
        f"🆔 **ID:** `{member.id}`\n"
        f"🤖 **Bot:** {'Yes' if member.bot else 'No'}\n"
        f"📅 **Account Created:** "
        f"<t:{int(member.created_at.timestamp())}:R>\n"
        f"📥 **Joined Server:** "
        f"<t:{int(member.joined_at.timestamp())}:R>\n"
        f"🎭 **Roles:** {role_text}",

        AURA_PURPLE,

        "👤"
    )

    embed.set_thumbnail(
        url=member.display_avatar.url
    )

    await interaction.response.send_message(
        embed=embed
    )


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


# =========================================================
# SETTINGS COMMANDS
# =========================================================

@bot.tree.command(
    name="setstaffrole",
    description="Set the AuraGuard staff role."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def setstaffrole(
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
    description="Set the moderation log channel."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def setlogchannel(
    interaction,
    channel: discord.TextChannel
):

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
    description="Set the message log channel."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def setmessagelog(
    interaction,
    channel: discord.TextChannel
):

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
# INVITE COMMANDS
# =========================================================

@bot.tree.command(
    name="invites",
    description="Check invite information."
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

            f"👤 **Member:** "
            f"{member.mention}\n"
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
    description="Show the invite leaderboard."
)
async def inviteleaderboard(interaction):

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

                "No invite data recorded yet.",

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
            f"**{user_data.get('total', 0)} invites**"
        )

    await interaction.response.send_message(

        embed=aura_embed(

            "Invite Leaderboard",

            "\n".join(
                lines
            ),

            AURA_PURPLE,

            "🏆"
        )
    )


# =========================================================
# EVENTS
# =========================================================

@bot.event
async def on_ready():

    print("=" * 50)

    print(
        f"AuraGuard V7 online as {bot.user}"
    )

    print(
        f"Bot ID: {bot.user.id}"
    )

    print("=" * 50)

    await bot.change_presence(

        status=discord.Status.online,

        activity=discord.Activity(

            type=discord.ActivityType.watching,

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

        bot.add_view(
            ClosedTicketControls()
        )

        for giveaway_id in data[
            "giveaways"
        ]:

            bot.add_view(
                GiveawayView(
                    giveaway_id
                )
            )

        bot._auraguard_views_loaded = True

    for guild in bot.guilds:

        try:

            invites_list = await guild.invites()

            invite_cache[guild.id] = {

                invite.code: invite.uses

                for invite in invites_list
            }

        except Exception as error:

            print(
                f"Could not load invites "
                f"for {guild.name}: {error}"
            )

    if not giveaway_loop.is_running():

        giveaway_loop.start()

    try:

        synced = await bot.tree.sync()

        print(
            f"Synced {len(synced)} slash commands."
        )

    except Exception as error:

        print(
            "Slash command sync error:",
            error
        )


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

            if invite.uses > old_uses:

                inviter = invite.inviter

                break

        invite_cache[guild.id] = {

            invite.code: invite.uses

            for invite in new_invites
        }

    except Exception as error:

        print(
            "Invite tracking error:",
            error
        )

    if inviter and inviter.id != member.id:

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

        await send_log(

            guild,

            "Member Joined",

            f"**Member:** "
            f"{member.mention}\n"
            f"**Invited By:** "
            f"{inviter.mention}\n"
            f"**Total Invites:** "
            f"**{inviter_data['total']}**",

            AURA_GREEN
        )

    else:

        await send_log(

            guild,

            "Member Joined",

            f"**Member:** "
            f"{member.mention}\n"
            f"**Inviter:** Unknown",

            AURA_GREEN
        )

    settings = get_settings(
        guild.id
    )

    if settings.get(
        "welcome_enabled"
    ):

        channel = guild.get_channel(
            settings.get(
                "welcome_channel"
            )
        )

        if isinstance(
            channel,
            discord.TextChannel
        ):

            await send_welcome(
                member,
                channel
            )


@bot.event
async def on_member_remove(member):

    settings = get_settings(
        member.guild.id
    )

    if settings.get(
        "leave_enabled"
    ):

        channel = member.guild.get_channel(

            settings.get(
                "leave_channel"
            )
        )

        if isinstance(
            channel,
            discord.TextChannel
        ):

            await channel.send(

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

        f"**Member:** {member}\n"
        f"**ID:** `{member.id}`",

        AURA_YELLOW
    )


@bot.event
async def on_invite_create(invite):

    invite_cache.setdefault(

        invite.guild.id,

        {}

    )[invite.code] = invite.uses


@bot.event
async def on_invite_delete(invite):

    invite_cache.setdefault(

        invite.guild.id,

        {}

    ).pop(
        invite.code,
        None
    )


@bot.event
async def on_message(message):

    if message.author.bot:

        return

    if not message.guild:

        return

    if is_staff(message.author):

        await bot.process_commands(
            message
        )

        return

    automod = get_automod(
        message.guild.id
    )

    if automod.get(
        "enabled"
    ):

        content = message.content

        lower_content = content.lower()

        # Blocked words

        for word in automod.get(
            "blocked_words",
            []
        ):

            if word.lower() in lower_content:

                try:

                    await message.delete()

                except Exception:
                    pass

                await send_log(

                    message.guild,

                    "AutoMod • Blocked Word",

                    f"**Member:** "
                    f"{message.author.mention}\n"
                    f"**Channel:** "
                    f"{message.channel.mention}",

                    AURA_RED
                )

                return

        # Anti-link

        if automod.get(
            "anti_links"
        ):

            link_pattern = (
                r"(https?://|www\.|discord\.gg/)"
            )

            if re.search(
                link_pattern,
                content,
                re.IGNORECASE
            ):

                try:

                    await message.delete()

                except Exception:
                    pass

                await send_log(

                    message.guild,

                    "AutoMod • Link Blocked",

                    f"**Member:** "
                    f"{message.author.mention}\n"
                    f"**Channel:** "
                    f"{message.channel.mention}",

                    AURA_RED
                )

                return

        # Anti-caps

        if automod.get(
            "anti_caps"
        ):

            letters = [
                char
                for char in content
                if char.isalpha()
            ]

            if len(letters) >= 8:

                caps = sum(

                    char.isupper()

                    for char in letters
                )

                percentage = (
                    caps / len(letters)
                ) * 100

                if percentage >= automod.get(
                    "caps_percentage",
                    75
                ):

                    try:

                        await message.delete()

                    except Exception:
                        pass

                    await send_log(

                        message.guild,

                        "AutoMod • Excessive Caps",

                        f"**Member:** "
                        f"{message.author.mention}\n"
                        f"**Channel:** "
                        f"{message.channel.mention}",

                        AURA_YELLOW
                    )

                    return

        # Anti-spam

        if automod.get(
            "anti_spam"
        ):

            key = (
                message.guild.id,
                message.author.id
            )

            now = datetime.now(
                timezone.utc
            )

            cache = message_cache[
                key
            ]

            cache.append(
                now
            )

            seconds = automod.get(
                "spam_seconds",
                7
            )

            while (
                cache
                and (
                    now - cache[0]
                ).total_seconds()
                > seconds
            ):

                cache.popleft()

            if len(cache) >= automod.get(
                "spam_limit",
                6
            ):

                try:

                    await message.delete()

                except Exception:
                    pass

                cache.clear()

                await send_log(

                    message.guild,

                    "AutoMod • Spam",

                    f"**Member:** "
                    f"{message.author.mention}\n"
                    f"**Channel:** "
                    f"{message.channel.mention}",

                    AURA_RED
                )

                return

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

    if message.author.bot:

        return

    if not message.guild:

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

    if before.author.bot:

        return

    if not before.guild:

        return

    if before.content == after.content:

        return

    await send_message_log(

        before.guild,

        "Message Edited",

        f"**Author:** "
        f"{before.author.mention}\n"
        f"**Channel:** "
        f"{before.channel.mention}\n\n"
        f"**Before:**\n"
        f"{clean_message_content(before.content)}\n\n"
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
        data["giveaways"].items()
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

                guild.get_channel(
                    giveaway["channel"]
                )

                if guild

                else None
            )

            try:

                await finish_giveaway(

                    guild,

                    channel
                    if isinstance(
                        channel,
                        discord.TextChannel
                    )
                    else None,

                    giveaway_id
                )

            except Exception as error:

                print(
                    "Giveaway error:",
                    error
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
`/tickets setlog`
`/tickets panel`

**🎉 Giveaways**
`/giveaway start`
`/giveaway end`
`/giveaway cancel`
`/giveaway reroll`

**🛡️ AutoMod**
`/automod enable`
`/automod disable`
`/automod addword`
`/automod removeword`
`/automod links`
`/automod caps`
`/automod spam`

**⚔️ Moderation**
`/kick`
`/ban`
`/unban`
`/timeout`
`/untimeout`
`/warn`
`/warnings`
`/clearwarnings`
`/clear`

**🔒 Channels**
`/lock`
`/unlock`
`/slowmode`

**📨 Invites**
`/invites`
`/inviteleaderboard`

**ℹ️ Information**
`/userinfo`
`/serverinfo`
`/ping`

**⚙️ Settings**
`/setstaffrole`
`/setlogchannel`
`/setmessagelog`
"""

    await interaction.response.send_message(

        embed=aura_embed(

            "AuraGuard V7 Commands",

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
        app_commands.CommandOnCooldown
    ):

        message = (
            "⏳ Please wait before using "
            "that command again."
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
# START AURAGUARD
# =========================================================

bot.run(TOKEN)
