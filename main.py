# =========================================================
#                    AURAGUARD V6
# =========================================================
# Features:
# - Welcome & leave messages
# - Welcome cards
# - Tickets
# - Giveaways
# - Moderation
# - AutoMod
# - Message logging
# - Invite tracking
# - Invite leaderboard
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
from PIL import Image, ImageDraw, ImageFont


# ==================== CONFIG ====================

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


# ==================== BOT SETUP ====================

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)


# ==================== DATA ====================

DEFAULT_DATA = {
    "settings": {},
    "warnings": {},
    "giveaways": {},
    "giveaway_entries": {},
    "giveaway_history": {},
    "backups": {},
    "ticket_claims": {},
    "automod": {},
    "invites": {}
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


# ==================== INVITE CACHE ====================

invite_cache = {}


# ==================== SETTINGS ====================

def get_settings(guild_id):

    gid = str(guild_id)

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

        "giveaway_bonus_roles": {}
    }

    if gid not in data["settings"]:
        data["settings"][gid] = defaults.copy()
        save_data()

    else:
        for key, value in defaults.items():
            data["settings"][gid].setdefault(key, value)

    return data["settings"][gid]


def get_automod(guild_id):

    gid = str(guild_id)

    data["automod"].setdefault(
        gid,
        {
            "enabled": False,
            "blocked_words": []
        }
    )

    return data["automod"][gid]


def get_invite_data(guild_id):

    gid = str(guild_id)

    data["invites"].setdefault(gid, {})

    return data["invites"][gid]


# ==================== HELPERS ====================

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

    if member.guild_permissions.administrator:
        return True

    if member.guild_permissions.manage_guild:
        return True

    role_id = get_settings(member.guild.id).get("staff_role")

    role = member.guild.get_role(role_id) if role_id else None

    return bool(role and role in member.roles)


def apply_placeholders(text, member):

    return (
        text.replace("{user}", member.mention)
        .replace("{server}", member.guild.name)
        .replace("{member_count}", str(member.guild.member_count))
    )


def clean_message_content(content):

    return discord.utils.escape_markdown(
        content or "*No text content*"
    )[:3500]


def make_unique_id(collection):

    while True:

        giveaway_id = str(random.randint(100000, 999999))

        if giveaway_id not in collection:
            return giveaway_id


def weighted_winners(entries, amount):

    pool = {
        user_id: int(weight)
        for user_id, weight in entries.items()
        if int(weight) > 0
    }

    result = []

    while pool and len(result) < amount:

        winner = random.choices(
            list(pool.keys()),
            weights=list(pool.values()),
            k=1
        )[0]

        result.append(winner)

        pool.pop(winner)

    return result


# ==================== LOGGING ====================

async def send_log(guild, title, description, color=AURA_PURPLE):

    channel_id = get_settings(guild.id).get("log_channel")

    channel = guild.get_channel(channel_id) if channel_id else None

    if isinstance(channel, discord.TextChannel):

        try:

            await channel.send(
                embed=aura_embed(
                    title,
                    description,
                    color,
                    "📋"
                )
            )

        except Exception:
            pass


async def send_message_log(guild, title, description, color=AURA_BLUE):

    channel_id = get_settings(guild.id).get("message_log_channel")

    channel = guild.get_channel(channel_id) if channel_id else None

    if isinstance(channel, discord.TextChannel):

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


# ==================== WELCOME IMAGE ====================

def get_font(size, bold=False):

    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ]

    for path in paths:

        try:
            return ImageFont.truetype(path, size)

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

    avatar = Image.open(
        io.BytesIO(
            await member.display_avatar.read()
        )
    ).convert("RGB")

    avatar = avatar.resize((190, 190))

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
        font=get_font(38, True),
        fill=(190, 145, 255)
    )

    draw.text(
        (300, 125),
        member.display_name[:22],
        font=get_font(56, True),
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

    image.save(output, "PNG")

    output.seek(0)

    return discord.File(
        output,
        filename="auraguard-welcome.png"
    )


async def send_welcome(member, channel, title="Welcome!"):

    settings = get_settings(member.guild.id)

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

        if settings.get("welcome_image_enabled", True):

            welcome_file = await create_welcome_card(member)

            embed.set_image(
                url="attachment://auraguard-welcome.png"
            )

            await channel.send(
                embed=embed,
                file=welcome_file
            )

        else:

            await channel.send(embed=embed)

    except Exception:

        await channel.send(embed=embed)


# ==================== TICKETS ====================

class TicketView(discord.ui.View):

    def __init__(self):

        super().__init__(timeout=None)

    @discord.ui.button(
        label="Open Ticket",
        style=discord.ButtonStyle.primary,
        emoji="🎫",
        custom_id="auraguard_open_ticket"
    )
    async def open_ticket(self, interaction, button):

        guild = interaction.guild
        user = interaction.user

        settings = get_settings(guild.id)

        for channel in guild.text_channels:

            if channel.topic == f"AURAGUARD_TICKET_OWNER={user.id}":

                await interaction.response.send_message(
                    f"🎫 You already have a ticket: {channel.mention}",
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

        role = (
            guild.get_role(settings["staff_role"])
            if settings.get("staff_role")
            else None
        )

        if role:

            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )

        category = (
            guild.get_channel(settings["ticket_category"])
            if settings.get("ticket_category")
            else None
        )

        channel = await guild.create_text_channel(

            f"ticket-{user.name}".lower()[:90],

            category=(
                category
                if isinstance(category, discord.CategoryChannel)
                else None
            ),

            overwrites=overwrites,

            topic=f"AURAGUARD_TICKET_OWNER={user.id}",

            reason="AuraGuard ticket opened"
        )

        await channel.send(

            content=user.mention,

            embed=aura_embed(
                "Ticket Opened",
                "A staff member will help you soon.\n\nUse the buttons below.",
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
            f"User: {user.mention}\nChannel: {channel.mention}",
            AURA_BLUE
        )


class TicketControls(discord.ui.View):

    def __init__(self):

        super().__init__(timeout=None)

    @discord.ui.button(
        label="Claim",
        style=discord.ButtonStyle.success,
        emoji="🙋",
        custom_id="auraguard_claim_ticket"
    )
    async def claim_ticket(self, interaction, button):

        if not is_staff(interaction.user):

            await interaction.response.send_message(
                "❌ Only staff can claim tickets.",
                ephemeral=True
            )

            return

        channel_id = str(interaction.channel.id)

        current = data["ticket_claims"].get(channel_id)

        if current and current != interaction.user.id:

            await interaction.response.send_message(
                f"❌ Already claimed by <@{current}>.",
                ephemeral=True
            )

            return

        data["ticket_claims"][channel_id] = interaction.user.id

        save_data()

        await interaction.response.send_message(
            f"🙋 Ticket claimed by {interaction.user.mention}."
        )

        await send_log(
            interaction.guild,
            "Ticket Claimed",
            f"Staff: {interaction.user.mention}\n"
            f"Channel: {interaction.channel.mention}",
            AURA_GREEN
        )

    @discord.ui.button(
        label="Close",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="auraguard_close_ticket"
    )
    async def close_ticket(self, interaction, button):

        if not is_staff(interaction.user):

            await interaction.response.send_message(
                "❌ Only staff can close tickets.",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            "🔒 Closing ticket in **1 second**..."
        )

        await send_log(
            interaction.guild,
            "Ticket Closed",
            f"Staff: {interaction.user.mention}\n"
            f"Channel: {interaction.channel.mention}",
            AURA_RED
        )

        await asyncio.sleep(1)

        data["ticket_claims"].pop(
            str(interaction.channel.id),
            None
        )

        save_data()

        await interaction.channel.delete(
            reason="AuraGuard ticket closed"
        )


# ==================== GIVEAWAYS ====================

def giveaway_embed(giveaway_id, giveaway):

    entries = data["giveaway_entries"].get(
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
        f"🎟️ **Total Entries:** {sum(entries.values())}\n"
        f"👤 **Hosted by:** <@{giveaway['created_by']}>\n"
        f"⏰ **Ends:** <t:{int(end.timestamp())}:R>\n\n"
        f"**Click Participate to enter!**",

        AURA_PURPLE,

        "🎉"
    )


class GiveawayView(discord.ui.View):

    def __init__(self, giveaway_id):

        super().__init__(timeout=None)

        self.giveaway_id = giveaway_id

        participate_button = discord.ui.Button(

            label="Participate",

            emoji="🎉",

            style=discord.ButtonStyle.success,

            custom_id=f"auraguard_giveaway_enter_{giveaway_id}"
        )

        participate_button.callback = self.enter

        self.add_item(participate_button)

        info_button = discord.ui.Button(

            label="Giveaway Info",

            emoji="ℹ️",

            style=discord.ButtonStyle.secondary,

            custom_id=f"auraguard_giveaway_info_{giveaway_id}"
        )

        info_button.callback = self.info

        self.add_item(info_button)

        entries_button = discord.ui.Button(

            label="My Entries",

            emoji="🎟️",

            style=discord.ButtonStyle.primary,

            custom_id=f"auraguard_giveaway_myentries_{giveaway_id}"
        )

        entries_button.callback = self.my_entries

        self.add_item(entries_button)

    async def enter(self, interaction):

        giveaway = data["giveaways"].get(
            self.giveaway_id
        )

        if not giveaway:

            await interaction.response.send_message(
                "❌ This giveaway is no longer active.",
                ephemeral=True
            )

            return

        entries = data["giveaway_entries"].setdefault(
            self.giveaway_id,
            {}
        )

        user_id = str(interaction.user.id)

        if user_id in entries:

            await interaction.response.send_message(
                f"❌ You're already entered with **{entries[user_id]} entries**.",
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

            if role and role in interaction.user.roles:

                amount += int(bonus)

        entries[user_id] = amount

        save_data()

        await interaction.response.send_message(
            f"🎉 You're entered with **{amount} "
            f"{'entry' if amount == 1 else 'entries'}**!",
            ephemeral=True
        )

    async def info(self, interaction):

        giveaway = data["giveaways"].get(
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

    async def my_entries(self, interaction):

        giveaway = data["giveaways"].get(
            self.giveaway_id
        )

        if not giveaway:

            await interaction.response.send_message(
                "❌ This giveaway is no longer active.",
                ephemeral=True
            )

            return

        entries = data["giveaway_entries"].get(
            self.giveaway_id,
            {}
        )

        amount = entries.get(
            str(interaction.user.id),
            0
        )

        end = datetime.fromisoformat(
            giveaway["end_time"]
        )

        await interaction.response.send_message(

            embed=aura_embed(

                "My Giveaway Entries",

                f"🎁 **Prize:** {giveaway['prize']}\n"
                f"🆔 **Giveaway ID:** `{self.giveaway_id}`\n"
                f"🎟️ **Your Entries:** **{amount}**\n"
                f"⏰ **Ends:** <t:{int(end.timestamp())}:R>",

                AURA_PURPLE,

                "🎟️"
            ),

            ephemeral=True
        )


async def finish_giveaway(
    guild,
    channel,
    giveaway_id
):

    giveaway = data["giveaways"].get(
        giveaway_id
    )

    if not giveaway:
        return []

    entries = data["giveaway_entries"].get(
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
    history["ended_at"] = datetime.now(
        timezone.utc
    ).isoformat()

    data["giveaway_history"][giveaway_id] = history

    data["giveaways"].pop(
        giveaway_id,
        None
    )

    data["giveaway_entries"].pop(
        giveaway_id,
        None
    )

    save_data()

    if channel:

        if winners:

            await channel.send(

                embed=aura_embed(

                    "Giveaway Winner!",

                    f"🎁 **Prize:** {history['prize']}\n\n🏆 "
                    + " ".join(
                        f"<@{winner}>"
                        for winner in winners
                    ),

                    AURA_GREEN,

                    "🏆"
                )
            )

        else:

            await channel.send(

                embed=aura_embed(

                    "Giveaway Ended",

                    f"🎁 **{history['prize']}**\n\nNobody entered.",

                    AURA_YELLOW,

                    "🎉"
                )
            )

    return winners


# ==================== COMMAND GROUPS ====================

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


# ==================== WELCOME COMMANDS ====================

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
    message: str = "Welcome {user} to {server}! 🛡️"
):

    settings = get_settings(
        interaction.guild.id
    )

    settings["welcome_channel"] = channel.id
    settings["welcome_message"] = message

    save_data()

    await interaction.response.send_message(
        "✅ Welcome setup saved.",
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

    if not settings["welcome_channel"]:

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
    description="Turn welcome image on or off."
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
        f"🖼️ Welcome image "
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

    channel = interaction.guild.get_channel(
        get_settings(
            interaction.guild.id
        ).get("welcome_channel")
    )

    if not isinstance(channel, discord.TextChannel):

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
        f"✅ Test sent to {channel.mention}.",
        ephemeral=True
    )


# ==================== LEAVE COMMANDS ====================

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
    message: str = "{user} has left {server}. 👋"
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

    if not settings["leave_channel"]:

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


@leave_group.command(
    name="test",
    description="Test leave message."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def leave_test(interaction):

    settings = get_settings(
        interaction.guild.id
    )

    channel = interaction.guild.get_channel(
        settings.get("leave_channel")
    )

    if not isinstance(channel, discord.TextChannel):

        await interaction.response.send_message(
            "❌ Run `/leave setup` first.",
            ephemeral=True
        )

        return

    await channel.send(

        embed=aura_embed(

            "Leave Test",

            apply_placeholders(
                settings["leave_message"],
                interaction.user
            ),

            AURA_YELLOW,

            "🚪"
        )
    )

    await interaction.response.send_message(
        "✅ Leave test sent.",
        ephemeral=True
    )


# ==================== TICKET COMMANDS ====================

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
        f"🎫 Ticket category set to **{category.name}**.",
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

            "Need help?\n\nClick below to open a ticket.",

            AURA_PURPLE,

            "🎫"
        ),

        view=TicketView()
    )


# ==================== GIVEAWAY COMMANDS ====================

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
            "❌ Minutes and winners must be at least 1.",
            ephemeral=True
        )

        return

    giveaway_id = make_unique_id(
        data["giveaways"]
    )

    end = datetime.now(
        timezone.utc
    ) + timedelta(minutes=minutes)

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

        embed=giveaway_embed(
            giveaway_id,
            data["giveaways"][giveaway_id]
        ),

        view=GiveawayView(giveaway_id)
    )


@giveaway_group.command(
    name="participants",
    description="View giveaway participants."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def giveaway_participants(
    interaction,
    giveaway_id: str
):

    giveaway = data["giveaways"].get(
        giveaway_id
    )

    entries = data["giveaway_entries"].get(
        giveaway_id
    )

    if giveaway is None or entries is None:

        await interaction.response.send_message(
            "❌ Active giveaway not found.",
            ephemeral=True
        )

        return

    if not entries:

        text = "Nobody has entered yet."

    else:

        lines = []

        for index, (user_id, count) in enumerate(
            entries.items(),
            1
        ):

            lines.append(
                f"**{index}.** <@{user_id}> — "
                f"**{count} entries**"
            )

        text = "\n".join(lines)

    await interaction.response.send_message(

        embed=aura_embed(

            f"Giveaway Participants • {giveaway_id}",

            f"👥 **Participants:** {len(entries)}\n"
            f"🎟️ **Total Entries:** {sum(entries.values())}\n\n"
            f"{text[:3500]}",

            AURA_PURPLE,

            "👥"
        ),

        ephemeral=True
    )


@giveaway_group.command(
    name="entries",
    description="Check your entries."
)
async def giveaway_entries(interaction, giveaway_id: str):

    amount = data["giveaway_entries"].get(
        giveaway_id,
        {}
    ).get(
        str(interaction.user.id),
        0
    )

    await interaction.response.send_message(
        f"🎟️ You have **{amount} "
        f"{'entry' if amount == 1 else 'entries'}**.",
        ephemeral=True
    )


@giveaway_group.command(
    name="addentries",
    description="Give extra entries."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def giveaway_addentries(
    interaction,
    giveaway_id: str,
    member: discord.Member,
    amount: int
):

    if amount < 1 or giveaway_id not in data["giveaways"]:

        await interaction.response.send_message(
            "❌ Invalid amount or active giveaway.",
            ephemeral=True
        )

        return

    entries = data["giveaway_entries"].setdefault(
        giveaway_id,
        {}
    )

    user_id = str(member.id)

    entries[user_id] = entries.get(
        user_id,
        0
    ) + amount

    save_data()

    await interaction.response.send_message(
        f"➕ {member.mention} now has "
        f"**{entries[user_id]} entries**.",
        ephemeral=True
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

    giveaway = data["giveaways"].get(
        giveaway_id
    )

    if not giveaway or giveaway["guild"] != interaction.guild.id:

        await interaction.response.send_message(
            "❌ Giveaway not found.",
            ephemeral=True
        )

        return

    await interaction.response.defer()

    channel = interaction.guild.get_channel(
        giveaway["channel"]
    )

    await finish_giveaway(
        interaction.guild,
        channel if isinstance(
            channel,
            discord.TextChannel
        ) else None,
        giveaway_id
    )


# ==================== INVITE COMMANDS ====================

@bot.tree.command(
    name="invites",
    description="Check your or another member's invite count."
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
            f"📨 **Total Invites:** **{total}**\n"
            f"✅ **Regular Invites:** **{regular}**",

            AURA_PURPLE,

            "📨"
        )
    )


@bot.tree.command(
    name="inviteleaderboard",
    description="Show the server invite leaderboard."
)
async def invite_leaderboard(interaction):

    invite_data = get_invite_data(
        interaction.guild.id
    )

    sorted_invites = sorted(

        invite_data.items(),

        key=lambda item: item[1].get(
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

    for position, (user_id, user_data) in enumerate(
        sorted_invites[:10],
        1
    ):

        lines.append(
            f"**{position}.** <@{user_id}> — "
            f"**{user_data.get('total', 0)} invites**"
        )

    await interaction.response.send_message(

        embed=aura_embed(

            "Invite Leaderboard",

            "\n".join(lines),

            AURA_PURPLE,

            "🏆"
        )
    )


# ==================== SETTINGS COMMANDS ====================

@bot.tree.command(
    name="ping",
    description="Check AuraGuard latency."
)
async def ping(interaction):

    await interaction.response.send_message(

        embed=aura_embed(

            "AuraGuard Online",

            f"⚡ Pong!\n"
            f"Latency: **{round(bot.latency * 1000)}ms**",

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
async def setstaffrole(
    interaction,
    role: discord.Role
):

    get_settings(
        interaction.guild.id
    )["staff_role"] = role.id

    save_data()

    await interaction.response.send_message(
        f"🛡️ Staff role set to {role.mention}.",
        ephemeral=True
    )


@bot.tree.command(
    name="setlogchannel",
    description="Set moderation log channel."
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
        f"📋 Log channel set to {channel.mention}.",
        ephemeral=True
    )


@bot.tree.command(
    name="setmessagelog",
    description="Set message activity log."
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
        f"💬 Message log set to {channel.mention}.",
        ephemeral=True
    )


# ==================== AUTOMOD ====================

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
    description="Disable AutoMod."
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
async def automod_addword(
    interaction,
    word: str
):

    automod = get_automod(
        interaction.guild.id
    )

    word = word.strip()

    if (
        not word
        or word.lower()
        in [
            item.lower()
            for item in automod["blocked_words"]
        ]
    ):

        await interaction.response.send_message(
            "❌ Invalid or already blocked.",
            ephemeral=True
        )

        return

    automod["blocked_words"].append(word)

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
            for item in automod["blocked_words"]
            if item.lower() == word.lower()
        ),

        None
    )

    if not match:

        await interaction.response.send_message(
            "❌ Not on blocked list.",
            ephemeral=True
        )

        return

    automod["blocked_words"].remove(match)

    save_data()

    await interaction.response.send_message(
        f"✅ Removed `{match}`.",
        ephemeral=True
    )


@automod_group.command(
    name="list",
    description="View blocked words."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def automod_list(interaction):

    automod = get_automod(
        interaction.guild.id
    )

    words = automod["blocked_words"]

    await interaction.response.send_message(

        embed=aura_embed(

            "AutoMod Settings",

            f"**Status:** "
            f"{'🟢 Enabled' if automod['enabled'] else '🔴 Disabled'}\n\n"
            + (
                "\n".join(
                    f"• `{word}`"
                    for word in words
                )
                if words
                else "No blocked words."
            ),

            AURA_PURPLE,

            "🛡️"
        ),

        ephemeral=True
    )


# ==================== MODERATION ====================

async def hierarchy_check(
    interaction,
    member
):

    if (
        member == interaction.user
        or member == interaction.guild.owner
    ):

        await interaction.response.send_message(
            "❌ You can't moderate that member.",
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
    description="Unban using user ID."
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

        await interaction.guild.unban(user)

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
        + timedelta(minutes=minutes),
        reason=reason
    )

    await interaction.response.send_message(
        f"⏳ {member.mention} timed out "
        f"for **{minutes} minutes**."
    )


@bot.tree.command(
    name="untimeout",
    description="Remove timeout."
)
@app_commands.checks.has_permissions(
    moderate_members=True
)
async def untimeout(
    interaction,
    member: discord.Member
):

    await member.timeout(None)

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

    warnings = data["warnings"].setdefault(
        str(interaction.guild.id),
        {}
    ).setdefault(
        str(member.id),
        []
    )

    warnings.append({

        "reason": reason,

        "moderator": interaction.user.id,

        "time": datetime.now(
            timezone.utc
        ).isoformat()
    })

    save_data()

    await interaction.response.send_message(
        f"⚠️ Warned {member.mention}. "
        f"Total warnings: **{len(warnings)}**"
    )


@bot.tree.command(
    name="warnings",
    description="View warnings."
)
@app_commands.checks.has_permissions(
    moderate_members=True
)
async def warnings(
    interaction,
    member: discord.Member
):

    member_warnings = data["warnings"].get(
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

    text = "\n".join(

        f"**{index}.** {warning['reason']} — "
        f"<@{warning['moderator']}>"

        for index, warning in enumerate(
            member_warnings,
            1
        )
    )

    await interaction.response.send_message(

        embed=aura_embed(

            f"Warnings - {member}",

            text[:4000],

            AURA_YELLOW,

            "⚠️"
        ),

        ephemeral=True
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
            "❌ Choose 1-100.",
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


# ==================== EVENTS ====================

@bot.event
async def on_ready():

    print("=" * 40)

    print(
        f"AuraGuard V6 online as {bot.user}"
    )

    print(
        f"Bot ID: {bot.user.id}"
    )

    print("=" * 40)

    await bot.change_presence(

        status=discord.Status.online,

        activity=discord.Activity(

            type=discord.ActivityType.watching,

            name="over your server 🛡️"
        )
    )

    # Persistent ticket buttons
    if not getattr(bot, "_auraguard_views_loaded", False):

        bot.add_view(TicketView())

        bot.add_view(TicketControls())

        for giveaway_id in data["giveaways"]:

            bot.add_view(
                GiveawayView(giveaway_id)
            )

        bot._auraguard_views_loaded = True

    # Load invite cache
    for guild in bot.guilds:

        try:

            invites = await guild.invites()

            invite_cache[guild.id] = {
                invite.code: invite.uses
                for invite in invites
            }

        except Exception as e:

            print(
                f"Could not load invites for "
                f"{guild.name}: {e}"
            )

    if not giveaway_loop.is_running():

        giveaway_loop.start()

    try:

        synced = await bot.tree.sync()

        print(
            f"Synced {len(synced)} slash commands."
        )

    except Exception as e:

        print(
            "Slash command sync error:",
            e
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

    except Exception as e:

        print(
            "Invite tracking error:",
            e
        )

    # Save invite
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

            f"Member: {member.mention}\n"
            f"Invited By: {inviter.mention}\n"
            f"Total Invites: **{inviter_data['total']}**",

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

    settings = get_settings(
        guild.id
    )

    if settings.get("welcome_enabled"):

        channel = guild.get_channel(
            settings.get("welcome_channel")
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

    if settings.get("leave_enabled"):

        channel = member.guild.get_channel(
            settings.get("leave_channel")
        )

        if isinstance(
            channel,
            discord.TextChannel
        ):

            await channel.send(

                embed=aura_embed(

                    "Member Left",

                    apply_placeholders(
                        settings["leave_message"],
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


@bot.event
async def on_message(message):

    if message.author.bot or not message.guild:
        return

    automod = get_automod(
        message.guild.id
    )

    if automod.get("enabled"):

        lower_content = message.content.lower()

        for word in automod.get(
            "blocked_words",
            []
        ):

            if word.lower() in lower_content:

                try:
                    await message.delete()

                except Exception:
                    pass

                try:

                    await message.channel.send(

                        f"⚠️ {message.author.mention}, "
                        f"that message contains a blocked word.",

                        delete_after=5
                    )

                except Exception:
                    pass

                await send_log(

                    message.guild,

                    "AutoMod Action",

                    f"Member: {message.author.mention}\n"
                    f"Channel: {message.channel.mention}",

                    AURA_RED
                )

                return

    await send_message_log(

        message.guild,

        "Message Sent",

        f"**Author:** {message.author.mention}\n"
        f"**Channel:** {message.channel.mention}\n\n"
        f"**Message:**\n"
        f"{clean_message_content(message.content)}"
    )

    await bot.process_commands(message)


@bot.event
async def on_message_delete(message):

    if message.author.bot or not message.guild:
        return

    await send_message_log(

        message.guild,

        "Message Deleted",

        f"**Author:** {message.author.mention}\n"
        f"**Channel:** {message.channel.mention}\n\n"
        f"**Deleted Message:**\n"
        f"{clean_message_content(message.content)}",

        AURA_RED
    )


@bot.event
async def on_message_edit(before, after):

    if (
        before.author.bot
        or not before.guild
        or before.content == after.content
    ):
        return

    await send_message_log(

        before.guild,

        "Message Edited",

        f"**Author:** {before.author.mention}\n"
        f"**Channel:** {before.channel.mention}\n\n"
        f"**Before:**\n"
        f"{clean_message_content(before.content)}\n\n"
        f"**After:**\n"
        f"{clean_message_content(after.content)}",

        AURA_YELLOW
    )


# ==================== GIVEAWAY LOOP ====================

@tasks.loop(seconds=15)
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

            except Exception as e:

                print(
                    "Giveaway error:",
                    e
                )


# ==================== HELP COMMAND ====================

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
`/leave test`

**🎫 Tickets**
`/tickets setup`
`/tickets panel`

**🎉 Giveaways**
`/giveaway start`
`/giveaway participants`
`/giveaway entries`
`/giveaway addentries`
`/giveaway end`

**📨 Invites**
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
`/clear`
`/lock`
`/unlock`

**🛡️ AutoMod**
`/automod enable`
`/automod disable`
`/automod addword`
`/automod removeword`
`/automod list`

**⚙️ Settings**
`/setstaffrole`
`/setlogchannel`
`/setmessagelog`

**⚡ Other**
`/ping`
"""

    await interaction.response.send_message(

        embed=aura_embed(

            "AuraGuard V6 Commands",

            text,

            AURA_PURPLE,

            "⚡"
        ),

        ephemeral=True
    )


# ==================== REGISTER GROUPS ====================

for group in [

    welcome_group,

    leave_group,

    tickets_group,

    giveaway_group,

    automod_group
]:

    bot.tree.add_command(group)


# ==================== ERROR HANDLER ====================

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


# ==================== START BOT ====================

bot.run(TOKEN)
