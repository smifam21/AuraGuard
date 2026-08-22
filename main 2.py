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


# =========================================================
#                    AURAGUARD v3
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
    raise RuntimeError("DISCORD_TOKEN is missing from Railway Variables.")


# =========================================================
# INTENTS
# =========================================================

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

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
    "backups": {},
    "ticket_claims": {},
    "automod": {}
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
        print(f"Data load error: {e}")
        return json.loads(json.dumps(DEFAULT_DATA))


data = load_data()


def save_data():
    try:
        temp = DATA_FILE + ".tmp"

        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

        os.replace(temp, DATA_FILE)

    except Exception as e:
        print(f"Data save error: {e}")


def get_settings(guild_id: int):
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

        "giveaway_bonus_roles": {}
    }

    if guild_id not in data["settings"]:
        data["settings"][guild_id] = defaults
        save_data()
    else:
        changed = False
        for key, value in defaults.items():
            if key not in data["settings"][guild_id]:
                data["settings"][guild_id][key] = value
                changed = True
        if changed:
            save_data()

    return data["settings"][guild_id]


def get_automod(guild_id: int):
    guild_id = str(guild_id)

    defaults = {
        "enabled": False,
        "blocked_words": []
    }

    if guild_id not in data["automod"]:
        data["automod"][guild_id] = defaults
        save_data()
    else:
        for key, value in defaults.items():
            data["automod"][guild_id].setdefault(key, value)

    return data["automod"][guild_id]


# =========================================================
# HELPERS
# =========================================================

def aura_embed(title: str, description: str = "", color: int = AURA_PURPLE,
               emoji: str = "🛡️"):
    embed = discord.Embed(
        title=f"{emoji} {title}",
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text=FOOTER)
    return embed


def is_staff(member: discord.Member):
    if member.guild_permissions.administrator:
        return True

    if member.guild_permissions.manage_guild:
        return True

    settings = get_settings(member.guild.id)
    role_id = settings.get("staff_role")

    if role_id:
        role = member.guild.get_role(role_id)
        if role and role in member.roles:
            return True

    return False


async def send_log(guild: discord.Guild, title: str, description: str,
                   color: int = AURA_PURPLE):
    settings = get_settings(guild.id)
    channel_id = settings.get("log_channel")

    if not channel_id:
        return

    channel = guild.get_channel(channel_id)

    if not isinstance(channel, discord.TextChannel):
        return

    try:
        await channel.send(
            embed=aura_embed(title, description, color, "📋")
        )
    except Exception:
        pass


async def send_message_log(guild: discord.Guild, title: str,
                           description: str, color: int = AURA_BLUE):
    settings = get_settings(guild.id)
    channel_id = settings.get("message_log_channel")

    if not channel_id:
        return

    channel = guild.get_channel(channel_id)

    if not isinstance(channel, discord.TextChannel):
        return

    try:
        await channel.send(
            embed=aura_embed(title, description[:4000], color, "💬")
        )
    except Exception:
        pass


def apply_placeholders(text: str, member: discord.Member):
    return (
        text.replace("{user}", member.mention)
        .replace("{server}", member.guild.name)
        .replace("{member_count}", str(member.guild.member_count))
    )


def make_unique_id(collection):
    while True:
        item_id = str(random.randint(100000, 999999))
        if item_id not in collection:
            return item_id


def weighted_winners(entries, amount: int):
    pool = {}

    for user_id, weight in entries.items():
        try:
            weight = int(weight)
            if weight > 0:
                pool[user_id] = weight
        except Exception:
            pass

    winners = []

    while pool and len(winners) < amount:
        users = list(pool.keys())
        weights = list(pool.values())

        winner = random.choices(users, weights=weights, k=1)[0]
        winners.append(winner)
        pool.pop(winner, None)

    return winners


def clean_message_content(content: str):
    if not content:
        return "*No text content*"
    return discord.utils.escape_markdown(content)[:3500]


# =========================================================
# WELCOME IMAGE
# =========================================================

def get_font(size: int, bold: bool = False):
    fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    ]

    for font_path in fonts:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass

    return ImageFont.load_default()


async def create_welcome_card(member: discord.Member):
    width, height = 1000, 360

    image = Image.new("RGB", (width, height), (18, 8, 32))
    draw = ImageDraw.Draw(image)

    draw.ellipse((650, -100, 1150, 400), fill=(85, 25, 145))
    draw.ellipse((730, -50, 1080, 350), fill=(110, 40, 185))

    draw.rounded_rectangle(
        (20, 20, 980, 340),
        radius=30,
        outline=(170, 90, 255),
        width=5
    )

    avatar_bytes = await member.display_avatar.read()
    avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGB")
    avatar = avatar.resize((190, 190))

    mask = Image.new("L", (190, 190), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 189, 189), fill=255)

    image.paste(avatar, (70, 85), mask)

    draw.text((300, 70), "WELCOME TO",
              font=get_font(38, True), fill=(190, 145, 255))

    draw.text((300, 125), member.display_name[:22],
              font=get_font(56, True), fill=(255, 255, 255))

    draw.text((302, 210), member.guild.name[:35],
              font=get_font(30), fill=(225, 215, 240))

    draw.text((302, 265), f"Member #{member.guild.member_count}",
              font=get_font(26), fill=(190, 145, 255))

    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)

    return discord.File(output, filename="auraguard-welcome.png")


async def send_welcome(member: discord.Member, channel: discord.TextChannel,
                       title: str = "Welcome!"):
    settings = get_settings(member.guild.id)

    message = apply_placeholders(settings["welcome_message"], member)

    embed = aura_embed(title, message, AURA_PURPLE, "👋")

    try:
        if settings.get("welcome_image_enabled", True):
            image_file = await create_welcome_card(member)
            embed.set_image(url="attachment://auraguard-welcome.png")
            await channel.send(embed=embed, file=image_file)
        else:
            await channel.send(embed=embed)
    except Exception as e:
        print(f"Welcome image error: {e}")
        await channel.send(embed=embed)


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():
    print("================================")
    print(f"AuraGuard v3 online as {bot.user}")
    print(f"Bot ID: {bot.user.id}")
    print("================================")

    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="over your server 🛡️"
        )
    )

    if not getattr(bot, "persistent_views", False):
        bot.add_view(TicketView())
        bot.add_view(TicketControls())
        bot.persistent_views = True

    if not giveaway_loop.is_running():
        giveaway_loop.start()

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"Slash command sync error: {e}")


# =========================================================
# MEMBER JOIN / LEAVE
# =========================================================

@bot.event
async def on_member_join(member: discord.Member):
    settings = get_settings(member.guild.id)

    if settings.get("welcome_enabled"):
        channel = member.guild.get_channel(settings.get("welcome_channel"))
        if isinstance(channel, discord.TextChannel):
            await send_welcome(member, channel)

    await send_log(
        member.guild,
        "Member Joined",
        f"Member: {member.mention}\nID: `{member.id}`",
        AURA_GREEN
    )


@bot.event
async def on_member_remove(member: discord.Member):
    settings = get_settings(member.guild.id)

    if settings.get("leave_enabled"):
        channel = member.guild.get_channel(settings.get("leave_channel"))

        if isinstance(channel, discord.TextChannel):
            message = settings.get(
                "leave_message",
                "{user} has left {server}. 👋"
            )

            message = (
                message.replace("{user}", str(member))
                .replace("{server}", member.guild.name)
                .replace("{member_count}", str(member.guild.member_count))
            )

            try:
                await channel.send(
                    embed=aura_embed(
                        "Member Left",
                        message,
                        AURA_YELLOW,
                        "🚪"
                    )
                )
            except Exception:
                pass

    await send_log(
        member.guild,
        "Member Left",
        f"Member: {member}\nID: `{member.id}`",
        AURA_YELLOW
    )


# =========================================================
# MESSAGE LOGGING + AUTOMOD
# =========================================================

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    automod = get_automod(message.guild.id)

    if automod.get("enabled"):
        content_lower = message.content.lower()

        for word in automod.get("blocked_words", []):
            if word.lower() in content_lower:
                try:
                    await message.delete()
                except discord.Forbidden:
                    pass

                try:
                    await message.channel.send(
                        f"⚠️ {message.author.mention}, that message contains a blocked word.",
                        delete_after=5
                    )
                except Exception:
                    pass

                await send_log(
                    message.guild,
                    "AutoMod Action",
                    f"Member: {message.author.mention}\n"
                    f"Channel: {message.channel.mention}\n"
                    f"Blocked word filter triggered.",
                    AURA_RED
                )
                return

    await send_message_log(
        message.guild,
        "Message Sent",
        f"**Author:** {message.author.mention}\n"
        f"**Channel:** {message.channel.mention}\n\n"
        f"**Message:**\n{clean_message_content(message.content)}",
        AURA_BLUE
    )


@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    await send_message_log(
        message.guild,
        "Message Deleted",
        f"**Author:** {message.author.mention}\n"
        f"**Channel:** {message.channel.mention}\n\n"
        f"**Deleted Message:**\n{clean_message_content(message.content)}",
        AURA_RED
    )


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.author.bot or not before.guild:
        return

    if before.content == after.content:
        return

    await send_message_log(
        before.guild,
        "Message Edited",
        f"**Author:** {before.author.mention}\n"
        f"**Channel:** {before.channel.mention}\n\n"
        f"**Before:**\n{clean_message_content(before.content)}\n\n"
        f"**After:**\n{clean_message_content(after.content)}",
        AURA_YELLOW
    )


# =========================================================
# BASIC COMMANDS
# =========================================================

@bot.tree.command(name="ping", description="Check AuraGuard's latency.")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)

    await interaction.response.send_message(
        embed=aura_embed(
            "AuraGuard Online",
            f"⚡ Pong!\n\nLatency: **{latency}ms**",
            AURA_PURPLE,
            "⚡"
        ),
        ephemeral=True
    )


@bot.tree.command(name="help", description="Show all AuraGuard commands.")
async def help_command(interaction: discord.Interaction):
    text = """
**👋 Welcome**
`/welcome setup` • `/welcome enable` • `/welcome disable`
`/welcome image` • `/welcome test` • `/welcome settings`

**🚪 Leave**
`/leave setup` • `/leave enable` • `/leave disable` • `/leave test`

**🎫 Tickets**
`/tickets setup` • `/tickets panel`

**🎉 Giveaways**
`/giveaway start` • `/giveaway end` • `/giveaway reroll`
`/giveaway entries` • `/giveaway addentries`
`/giveaway removeentries` • `/giveaway bonusrole`

**🛡️ Moderation**
`/kick` • `/ban` • `/unban` • `/timeout` • `/untimeout`
`/warn` • `/warnings` • `/removewarning` • `/clearwarnings`
`/clear` • `/lock` • `/unlock`

**📊 Information**
`/userinfo` • `/serverinfo` • `/serverstats`

**🛡️ AutoMod**
`/automod enable` • `/automod disable`
`/automod addword` • `/automod removeword` • `/automod list`

**💾 Backups**
`/backup create` • `/backup list` • `/backup info` • `/backup restore`

**⚙️ Settings**
`/setstaffrole` • `/setlogchannel` • `/setmessagelog`
"""

    await interaction.response.send_message(
        embed=aura_embed("AuraGuard v3 Commands", text, AURA_PURPLE, "⚡"),
        ephemeral=True
    )


# =========================================================
# SETTINGS
# =========================================================

@bot.tree.command(name="setstaffrole", description="Set AuraGuard's staff role.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setstaffrole(interaction: discord.Interaction, role: discord.Role):
    settings = get_settings(interaction.guild.id)
    settings["staff_role"] = role.id
    save_data()

    await interaction.response.send_message(
        f"🛡️ Staff role set to {role.mention}.",
        ephemeral=True
    )


@bot.tree.command(name="setlogchannel", description="Set AuraGuard's moderation log channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setlogchannel(interaction: discord.Interaction,
                        channel: discord.TextChannel):
    settings = get_settings(interaction.guild.id)
    settings["log_channel"] = channel.id
    save_data()

    await interaction.response.send_message(
        f"📋 Moderation log channel set to {channel.mention}.",
        ephemeral=True
    )


@bot.tree.command(name="setmessagelog", description="Set the message activity log channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setmessagelog(interaction: discord.Interaction,
                        channel: discord.TextChannel):
    settings = get_settings(interaction.guild.id)
    settings["message_log_channel"] = channel.id
    save_data()

    await interaction.response.send_message(
        f"💬 Message log channel set to {channel.mention}.",
        ephemeral=True
    )


# =========================================================
# WELCOME
# =========================================================

welcome_group = app_commands.Group(
    name="welcome",
    description="Manage welcome messages."
)


@welcome_group.command(name="setup", description="Set the welcome channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_setup(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    message: str = "Welcome {user} to {server}! 🛡️"
):
    settings = get_settings(interaction.guild.id)
    settings["welcome_channel"] = channel.id
    settings["welcome_message"] = message
    save_data()

    await interaction.response.send_message(
        embed=aura_embed(
            "Welcome Setup",
            f"👋 Channel: {channel.mention}\n\n"
            f"Message:\n{message}\n\n"
            "Placeholders:\n`{user}`\n`{server}`\n`{member_count}`",
            AURA_PURPLE,
            "👋"
        ),
        ephemeral=True
    )


@welcome_group.command(name="enable", description="Enable welcome messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_enable(interaction: discord.Interaction):
    settings = get_settings(interaction.guild.id)

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


@welcome_group.command(name="disable", description="Disable welcome messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_disable(interaction: discord.Interaction):
    settings = get_settings(interaction.guild.id)
    settings["welcome_enabled"] = False
    save_data()

    await interaction.response.send_message(
        "🔴 Welcome messages disabled.",
        ephemeral=True
    )


@welcome_group.command(name="image", description="Turn the welcome image on or off.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_image(interaction: discord.Interaction, enabled: bool):
    settings = get_settings(interaction.guild.id)
    settings["welcome_image_enabled"] = enabled
    save_data()

    await interaction.response.send_message(
        f"🖼️ Welcome image **{'enabled' if enabled else 'disabled'}**.",
        ephemeral=True
    )


@welcome_group.command(name="test", description="Test the welcome message.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_test(interaction: discord.Interaction):
    settings = get_settings(interaction.guild.id)
    channel = interaction.guild.get_channel(settings.get("welcome_channel"))

    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "❌ Run `/welcome setup` first.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)
    await send_welcome(interaction.user, channel, "Welcome Test")

    await interaction.followup.send(
        f"✅ Test sent to {channel.mention}.",
        ephemeral=True
    )


@welcome_group.command(name="settings", description="View welcome settings.")
async def welcome_settings(interaction: discord.Interaction):
    settings = get_settings(interaction.guild.id)
    channel = interaction.guild.get_channel(settings.get("welcome_channel"))

    channel_text = channel.mention if channel else "Not configured"

    await interaction.response.send_message(
        embed=aura_embed(
            "Welcome Settings",
            f"**Status:** {'🟢 Enabled' if settings['welcome_enabled'] else '🔴 Disabled'}\n"
            f"**Channel:** {channel_text}\n"
            f"**Image:** {'🟢 Enabled' if settings['welcome_image_enabled'] else '🔴 Disabled'}\n\n"
            f"**Message:**\n{settings['welcome_message']}",
            AURA_PURPLE,
            "👋"
        ),
        ephemeral=True
    )


bot.tree.add_command(welcome_group)


# =========================================================
# LEAVE
# =========================================================

leave_group = app_commands.Group(
    name="leave",
    description="Manage leave messages."
)


@leave_group.command(name="setup", description="Set the leave channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_setup(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    message: str = "{user} has left {server}. 👋"
):
    settings = get_settings(interaction.guild.id)
    settings["leave_channel"] = channel.id
    settings["leave_message"] = message
    save_data()

    await interaction.response.send_message(
        f"🚪 Leave channel set to {channel.mention}.",
        ephemeral=True
    )


@leave_group.command(name="enable", description="Enable leave messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_enable(interaction: discord.Interaction):
    settings = get_settings(interaction.guild.id)

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


@leave_group.command(name="disable", description="Disable leave messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_disable(interaction: discord.Interaction):
    settings = get_settings(interaction.guild.id)
    settings["leave_enabled"] = False
    save_data()

    await interaction.response.send_message(
        "🔴 Leave messages disabled.",
        ephemeral=True
    )


@leave_group.command(name="test", description="Test the leave message.")
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_test(interaction: discord.Interaction):
    settings = get_settings(interaction.guild.id)
    channel = interaction.guild.get_channel(settings.get("leave_channel"))

    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "❌ Run `/leave setup` first.",
            ephemeral=True
        )
        return

    message = apply_placeholders(settings["leave_message"], interaction.user)

    await channel.send(
        embed=aura_embed("Leave Test", message, AURA_YELLOW, "🚪")
    )

    await interaction.response.send_message(
        "✅ Leave test sent.",
        ephemeral=True
    )


bot.tree.add_command(leave_group)


# =========================================================
# TICKETS
# =========================================================

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Open Ticket",
        style=discord.ButtonStyle.primary,
        emoji="🎫",
        custom_id="auraguard_open_ticket"
    )
    async def open_ticket(self, interaction: discord.Interaction,
                          button: discord.ui.Button):
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
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )
        }

        staff_role_id = settings.get("staff_role")
        staff_role = guild.get_role(staff_role_id) if staff_role_id else None

        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )

        category_id = settings.get("ticket_category")
        category = guild.get_channel(category_id) if category_id else None

        channel = await guild.create_text_channel(
            name=f"ticket-{user.name}".lower()[:90],
            category=category if isinstance(category, discord.CategoryChannel) else None,
            overwrites=overwrites,
            topic=f"AURAGUARD_TICKET_OWNER={user.id}",
            reason="AuraGuard ticket opened"
        )

        await channel.send(
            content=user.mention,
            embed=aura_embed(
                "Ticket Opened",
                "A staff member will help you soon.\n\n"
                "Use the buttons below to claim or close this ticket.",
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
    async def claim_ticket(self, interaction: discord.Interaction,
                           button: discord.ui.Button):
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
                f"❌ This ticket is already claimed by <@{current}>.",
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
    async def close_ticket(self, interaction: discord.Interaction,
                           button: discord.ui.Button):
        if not is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ Only staff can close tickets.",
                ephemeral=True
            )
            return

        await interaction.response.send_message("🔒 Closing ticket in 5 seconds...")

        await send_log(
            interaction.guild,
            "Ticket Closed",
            f"Staff: {interaction.user.mention}\n"
            f"Channel: {interaction.channel.mention}",
            AURA_RED
        )

        await asyncio.sleep(5)

        data["ticket_claims"].pop(str(interaction.channel.id), None)
        save_data()

        await interaction.channel.delete(reason="AuraGuard ticket closed")


tickets_group = app_commands.Group(
    name="tickets",
    description="Manage AuraGuard tickets."
)


@tickets_group.command(name="setup", description="Set the ticket category.")
@app_commands.checks.has_permissions(manage_guild=True)
async def tickets_setup(interaction: discord.Interaction,
                        category: discord.CategoryChannel):
    settings = get_settings(interaction.guild.id)
    settings["ticket_category"] = category.id
    save_data()

    await interaction.response.send_message(
        f"🎫 Ticket category set to **{category.name}**.",
        ephemeral=True
    )


@tickets_group.command(name="panel", description="Send the ticket panel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def tickets_panel(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=aura_embed(
            "AuraGuard Support",
            "Need help?\n\nClick the button below to open a ticket.",
            AURA_PURPLE,
            "🎫"
        ),
        view=TicketView()
    )


bot.tree.add_command(tickets_group)


# =========================================================
# GIVEAWAYS
# =========================================================

class GiveawayView(discord.ui.View):
    def __init__(self, giveaway_id: str):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id

        button = discord.ui.Button(
            label="Enter Giveaway",
            style=discord.ButtonStyle.success,
            emoji="🎉",
            custom_id=f"auraguard_giveaway_{giveaway_id}"
        )
        button.callback = self.enter
        self.add_item(button)

    async def enter(self, interaction: discord.Interaction):
        giveaway = data["giveaways"].get(self.giveaway_id)

        if not giveaway:
            await interaction.response.send_message(
                "❌ This giveaway is no longer active.",
                ephemeral=True
            )
            return

        entries = data["giveaway_entries"].setdefault(self.giveaway_id, {})
        user_id = str(interaction.user.id)

        if user_id in entries:
            await interaction.response.send_message(
                f"❌ You're already entered with **{entries[user_id]} entries**.",
                ephemeral=True
            )
            return

        settings = get_settings(interaction.guild.id)
        amount = 1

        for role_id, bonus in settings.get("giveaway_bonus_roles", {}).items():
            role = interaction.guild.get_role(int(role_id))
            if role and role in interaction.user.roles:
                amount += int(bonus)

        entries[user_id] = amount
        save_data()

        word = "entry" if amount == 1 else "entries"

        await interaction.response.send_message(
            f"🎉 You're entered with **{amount} {word}**!",
            ephemeral=True
        )


giveaway_group = app_commands.Group(
    name="giveaway",
    description="Manage giveaways."
)


@giveaway_group.command(name="start", description="Start a giveaway.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_start(
    interaction: discord.Interaction,
    prize: str,
    minutes: int,
    winners: int = 1
):
    if minutes < 1 or winners < 1:
        await interaction.response.send_message(
            "❌ Minutes and winners must both be at least 1.",
            ephemeral=True
        )
        return

    giveaway_id = make_unique_id(data["giveaways"])
    end_time = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    data["giveaways"][giveaway_id] = {
        "guild": interaction.guild.id,
        "channel": interaction.channel.id,
        "prize": prize,
        "winners": winners,
        "end_time": end_time.isoformat(),
        "created_by": interaction.user.id
    }

    data["giveaway_entries"][giveaway_id] = {}
    save_data()

    await interaction.response.send_message(
        embed=aura_embed(
            "GIVEAWAY",
            f"🎁 **Prize:** {prize}\n"
            f"🏆 **Winners:** {winners}\n"
            f"🆔 **Giveaway ID:** `{giveaway_id}`\n"
            f"⏰ **Ends:** <t:{int(end_time.timestamp())}:R>\n\n"
            "Click below to enter!",
            AURA_PURPLE,
            "🎉"
        ),
        view=GiveawayView(giveaway_id)
    )


async def finish_giveaway(guild: discord.Guild,
                          channel: discord.TextChannel | None,
                          giveaway_id: str):
    giveaway = data["giveaways"].get(giveaway_id)

    if not giveaway:
        return []

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

    if channel:
        if winners:
            mentions = " ".join(f"<@{user_id}>" for user_id in winners)
            await channel.send(
                embed=aura_embed(
                    "Giveaway Winner!",
                    f"🎁 **Prize:** {history['prize']}\n\n🏆 {mentions}",
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


@giveaway_group.command(name="end", description="End a giveaway early.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_end(interaction: discord.Interaction, giveaway_id: str):
    giveaway = data["giveaways"].get(giveaway_id)

    if not giveaway or giveaway["guild"] != interaction.guild.id:
        await interaction.response.send_message(
            "❌ Giveaway not found.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    channel = interaction.guild.get_channel(giveaway["channel"])
    await finish_giveaway(
        interaction.guild,
        channel if isinstance(channel, discord.TextChannel) else None,
        giveaway_id
    )


@giveaway_group.command(name="reroll", description="Reroll a finished giveaway.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_reroll(interaction: discord.Interaction, giveaway_id: str):
    history = data["giveaway_history"].get(giveaway_id)

    if not history:
        await interaction.response.send_message(
            "❌ Finished giveaway not found.",
            ephemeral=True
        )
        return

    previous = set(history.get("winners_list", []))
    pool = {
        user_id: count
        for user_id, count in history.get("entries", {}).items()
        if user_id not in previous
    }

    if not pool:
        await interaction.response.send_message(
            "❌ No other entries available.",
            ephemeral=True
        )
        return

    winner = weighted_winners(pool, 1)[0]
    history.setdefault("rerolls", []).append(winner)
    save_data()

    await interaction.response.send_message(
        embed=aura_embed(
            "Giveaway Reroll",
            f"🎁 **Prize:** {history['prize']}\n\n🏆 New winner: <@{winner}>",
            AURA_GREEN,
            "🔄"
        )
    )


@giveaway_group.command(name="entries", description="Check your giveaway entries.")
async def giveaway_entries(interaction: discord.Interaction, giveaway_id: str):
    amount = data["giveaway_entries"].get(giveaway_id, {}).get(
        str(interaction.user.id), 0
    )

    await interaction.response.send_message(
        f"🎟️ You have **{amount} {'entry' if amount == 1 else 'entries'}**.",
        ephemeral=True
    )


@giveaway_group.command(name="addentries", description="Give a member extra giveaway entries.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_addentries(
    interaction: discord.Interaction,
    giveaway_id: str,
    member: discord.Member,
    amount: int
):
    if amount < 1:
        await interaction.response.send_message(
            "❌ Amount must be at least 1.",
            ephemeral=True
        )
        return

    if giveaway_id not in data["giveaways"]:
        await interaction.response.send_message(
            "❌ Active giveaway not found.",
            ephemeral=True
        )
        return

    entries = data["giveaway_entries"].setdefault(giveaway_id, {})
    user_id = str(member.id)
    entries[user_id] = entries.get(user_id, 0) + amount
    save_data()

    await interaction.response.send_message(
        f"➕ Added **{amount} entries** to {member.mention}.\n"
        f"They now have **{entries[user_id]} entries**.",
        ephemeral=True
    )


@giveaway_group.command(name="removeentries", description="Remove giveaway entries from a member.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_removeentries(
    interaction: discord.Interaction,
    giveaway_id: str,
    member: discord.Member,
    amount: int
):
    entries = data["giveaway_entries"].get(giveaway_id)

    if amount < 1 or not entries:
        await interaction.response.send_message(
            "❌ Giveaway, entries, or amount is invalid.",
            ephemeral=True
        )
        return

    user_id = str(member.id)

    if user_id not in entries:
        await interaction.response.send_message(
            "❌ That member has no entries.",
            ephemeral=True
        )
        return

    entries[user_id] -= amount
    if entries[user_id] <= 0:
        entries.pop(user_id)
        new_amount = 0
    else:
        new_amount = entries[user_id]

    save_data()

    await interaction.response.send_message(
        f"➖ {member.mention} now has **{new_amount} entries**.",
        ephemeral=True
    )


@giveaway_group.command(name="bonusrole", description="Give a role bonus giveaway entries.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_bonusrole(
    interaction: discord.Interaction,
    role: discord.Role,
    extra_entries: int
):
    if extra_entries < 1:
        await interaction.response.send_message(
            "❌ Extra entries must be at least 1.",
            ephemeral=True
        )
        return

    settings = get_settings(interaction.guild.id)
    settings.setdefault("giveaway_bonus_roles", {})[str(role.id)] = extra_entries
    save_data()

    await interaction.response.send_message(
        f"⭐ {role.mention} now receives **+{extra_entries} entries**.",
        ephemeral=True
    )


@giveaway_group.command(name="removebonusrole", description="Remove a role's giveaway bonus.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_removebonusrole(
    interaction: discord.Interaction,
    role: discord.Role
):
    settings = get_settings(interaction.guild.id)
    removed = settings.setdefault("giveaway_bonus_roles", {}).pop(str(role.id), None)
    save_data()

    if removed is None:
        await interaction.response.send_message(
            "❌ That role has no giveaway bonus.",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"✅ Removed {role.mention}'s giveaway bonus.",
            ephemeral=True
        )


bot.tree.add_command(giveaway_group)


# =========================================================
# GIVEAWAY AUTO END
# =========================================================

@tasks.loop(seconds=15)
async def giveaway_loop():
    now = datetime.now(timezone.utc)

    for giveaway_id, giveaway in list(data["giveaways"].items()):
        try:
            end_time = datetime.fromisoformat(giveaway["end_time"])
        except Exception:
            continue

        if now < end_time:
            continue

        guild = bot.get_guild(giveaway["guild"])

        if not guild:
            continue

        channel = guild.get_channel(giveaway["channel"])

        try:
            await finish_giveaway(
                guild,
                channel if isinstance(channel, discord.TextChannel) else None,
                giveaway_id
            )
        except Exception as e:
            print(f"Giveaway error: {e}")


# =========================================================
# MODERATION HELPERS
# =========================================================

async def hierarchy_check(interaction: discord.Interaction,
                          member: discord.Member):
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
            "❌ My role is not high enough to moderate that member.",
            ephemeral=True
        )
        return False

    return True


@bot.tree.command(name="kick", description="Kick a member.")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member,
               reason: str = "No reason provided"):
    if not await hierarchy_check(interaction, member):
        return

    try:
        await member.kick(reason=reason)

        await interaction.response.send_message(
            embed=aura_embed(
                "Member Kicked",
                f"👢 {member.mention}\n\nReason: {reason}",
                AURA_RED,
                "👢"
            )
        )

        await send_log(
            interaction.guild,
            "Member Kicked",
            f"Member: {member}\nModerator: {interaction.user}\nReason: {reason}",
            AURA_RED
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I don't have permission to kick them.",
            ephemeral=True
        )


@bot.tree.command(name="ban", description="Ban a member.")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member,
              reason: str = "No reason provided"):
    if not await hierarchy_check(interaction, member):
        return

    try:
        await member.ban(reason=reason)

        await interaction.response.send_message(
            embed=aura_embed(
                "Member Banned",
                f"🔨 {member.mention}\n\nReason: {reason}",
                AURA_RED,
                "🔨"
            )
        )

        await send_log(
            interaction.guild,
            "Member Banned",
            f"Member: {member}\nModerator: {interaction.user}\nReason: {reason}",
            AURA_RED
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I don't have permission to ban them.",
            ephemeral=True
        )


@bot.tree.command(name="unban", description="Unban a user using their ID.")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)

        await interaction.response.send_message(
            f"🔓 **{user}** has been unbanned."
        )

        await send_log(
            interaction.guild,
            "Member Unbanned",
            f"User: {user}\nModerator: {interaction.user}",
            AURA_GREEN
        )
    except Exception:
        await interaction.response.send_message(
            "❌ User not found or not banned.",
            ephemeral=True
        )


@bot.tree.command(name="timeout", description="Timeout a member.")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout(
    interaction: discord.Interaction,
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

    if not await hierarchy_check(interaction, member):
        return

    until = discord.utils.utcnow() + timedelta(minutes=minutes)

    try:
        await member.timeout(until, reason=reason)

        await interaction.response.send_message(
            f"⏳ {member.mention} was timed out for **{minutes} minutes**.\n"
            f"Reason: **{reason}**"
        )

        await send_log(
            interaction.guild,
            "Member Timed Out",
            f"Member: {member.mention}\nModerator: {interaction.user.mention}\n"
            f"Duration: {minutes} minutes\nReason: {reason}",
            AURA_YELLOW
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I don't have permission to timeout them.",
            ephemeral=True
        )


@bot.tree.command(name="untimeout", description="Remove a member's timeout.")
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout(interaction: discord.Interaction, member: discord.Member):
    try:
        await member.timeout(None)

        await interaction.response.send_message(
            f"🔓 Removed {member.mention}'s timeout."
        )

        await send_log(
            interaction.guild,
            "Timeout Removed",
            f"Member: {member.mention}\nModerator: {interaction.user.mention}",
            AURA_GREEN
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I can't remove their timeout.",
            ephemeral=True
        )


# =========================================================
# WARNINGS
# =========================================================

@bot.tree.command(name="warn", description="Warn a member.")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, member: discord.Member,
               reason: str = "No reason provided"):
    guild_id = str(interaction.guild.id)
    user_id = str(member.id)

    warning_list = data["warnings"].setdefault(guild_id, {}).setdefault(
        user_id, []
    )

    warning_list.append({
        "reason": reason,
        "moderator": interaction.user.id,
        "time": datetime.now(timezone.utc).isoformat()
    })

    save_data()

    await interaction.response.send_message(
        embed=aura_embed(
            "Warning Issued",
            f"⚠️ {member.mention}\n\nReason: **{reason}**\n"
            f"Total Warnings: **{len(warning_list)}**",
            AURA_YELLOW,
            "⚠️"
        )
    )

    await send_log(
        interaction.guild,
        "Warning Issued",
        f"Member: {member.mention}\nModerator: {interaction.user.mention}\n"
        f"Reason: {reason}",
        AURA_YELLOW
    )


@bot.tree.command(name="warnings", description="View a member's warnings.")
@app_commands.checks.has_permissions(moderate_members=True)
async def warnings(interaction: discord.Interaction, member: discord.Member):
    warning_list = data["warnings"].get(
        str(interaction.guild.id), {}
    ).get(str(member.id), [])

    if not warning_list:
        await interaction.response.send_message(
            f"✅ {member.mention} has no warnings.",
            ephemeral=True
        )
        return

    text = ""

    for i, warning_data in enumerate(warning_list, start=1):
        text += (
            f"**{i}.** {warning_data['reason']}\n"
            f"Moderator: <@{warning_data['moderator']}>\n"
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


@bot.tree.command(name="removewarning", description="Remove one warning from a member.")
@app_commands.checks.has_permissions(moderate_members=True)
async def removewarning(
    interaction: discord.Interaction,
    member: discord.Member,
    number: int
):
    warning_list = data["warnings"].get(
        str(interaction.guild.id), {}
    ).get(str(member.id), [])

    if number < 1 or number > len(warning_list):
        await interaction.response.send_message(
            "❌ That warning number does not exist.",
            ephemeral=True
        )
        return

    removed = warning_list.pop(number - 1)
    save_data()

    await interaction.response.send_message(
        f"🗑️ Removed warning **#{number}** from {member.mention}.\n"
        f"Reason was: **{removed['reason']}**",
        ephemeral=True
    )


@bot.tree.command(name="clearwarnings", description="Clear all warnings from a member.")
@app_commands.checks.has_permissions(moderate_members=True)
async def clearwarnings(interaction: discord.Interaction,
                        member: discord.Member):
    guild_warnings = data["warnings"].setdefault(
        str(interaction.guild.id), {}
    )

    count = len(guild_warnings.get(str(member.id), []))
    guild_warnings[str(member.id)] = []
    save_data()

    await interaction.response.send_message(
        f"🧹 Cleared **{count} warnings** from {member.mention}.",
        ephemeral=True
    )


# =========================================================
# CLEAR / LOCK / UNLOCK
# =========================================================

@bot.tree.command(name="clear", description="Delete messages.")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, amount: int):
    if amount < 1 or amount > 100:
        await interaction.response.send_message(
            "❌ Choose between 1 and 100 messages.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)

    await interaction.followup.send(
        f"🧹 Deleted **{len(deleted)} messages**.",
        ephemeral=True
    )

    await send_log(
        interaction.guild,
        "Messages Cleared",
        f"Moderator: {interaction.user.mention}\n"
        f"Channel: {interaction.channel.mention}\n"
        f"Amount: {len(deleted)}",
        AURA_BLUE
    )


@bot.tree.command(name="lock", description="Lock a text channel.")
@app_commands.checks.has_permissions(manage_channels=True)
async def lock(interaction: discord.Interaction,
               channel: discord.TextChannel | None = None):
    channel = channel or interaction.channel

    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "❌ This command can only lock text channels.",
            ephemeral=True
        )
        return

    await channel.set_permissions(
        interaction.guild.default_role,
        send_messages=False,
        reason=f"Locked by {interaction.user}"
    )

    await interaction.response.send_message(
        f"🔒 {channel.mention} has been locked."
    )

    await send_log(
        interaction.guild,
        "Channel Locked",
        f"Channel: {channel.mention}\nModerator: {interaction.user.mention}",
        AURA_RED
    )


@bot.tree.command(name="unlock", description="Unlock a text channel.")
@app_commands.checks.has_permissions(manage_channels=True)
async def unlock(interaction: discord.Interaction,
                 channel: discord.TextChannel | None = None):
    channel = channel or interaction.channel

    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "❌ This command can only unlock text channels.",
            ephemeral=True
        )
        return

    await channel.set_permissions(
        interaction.guild.default_role,
        send_messages=None,
        reason=f"Unlocked by {interaction.user}"
    )

    await interaction.response.send_message(
        f"🔓 {channel.mention} has been unlocked."
    )

    await send_log(
        interaction.guild,
        "Channel Unlocked",
        f"Channel: {channel.mention}\nModerator: {interaction.user.mention}",
        AURA_GREEN
    )


# =========================================================
# INFORMATION
# =========================================================

@bot.tree.command(name="userinfo", description="View information about a member.")
async def userinfo(interaction: discord.Interaction,
                   member: discord.Member | None = None):
    member = member or interaction.user

    roles = [
        role.mention for role in member.roles
        if not role.is_default()
    ]

    roles_text = ", ".join(roles[-10:]) if roles else "None"

    embed = aura_embed(
        f"User Info - {member}",
        f"**Username:** {member}\n"
        f"**User ID:** `{member.id}`\n"
        f"**Joined Server:** <t:{int(member.joined_at.timestamp())}:R>\n"
        f"**Account Created:** <t:{int(member.created_at.timestamp())}:R>\n"
        f"**Top Role:** {member.top_role.mention}\n"
        f"**Roles:** {roles_text}",
        AURA_PURPLE,
        "👤"
    )

    embed.set_thumbnail(url=member.display_avatar.url)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="serverinfo", description="View information about the server.")
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild

    embed = aura_embed(
        f"Server Info - {guild.name}",
        f"**Server ID:** `{guild.id}`\n"
        f"**Owner:** {guild.owner.mention if guild.owner else 'Unknown'}\n"
        f"**Members:** {guild.member_count}\n"
        f"**Roles:** {len(guild.roles)}\n"
        f"**Channels:** {len(guild.channels)}\n"
        f"**Created:** <t:{int(guild.created_at.timestamp())}:R>",
        AURA_PURPLE,
        "🏠"
    )

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="serverstats", description="View server statistics.")
async def serverstats(interaction: discord.Interaction):
    guild = interaction.guild

    humans = sum(1 for member in guild.members if not member.bot)
    bots = sum(1 for member in guild.members if member.bot)
    text_channels = len(guild.text_channels)
    voice_channels = len(guild.voice_channels)

    await interaction.response.send_message(
        embed=aura_embed(
            "Server Statistics",
            f"👥 **Members:** {guild.member_count}\n"
            f"🙋 **Humans:** {humans}\n"
            f"🤖 **Bots:** {bots}\n"
            f"💬 **Text Channels:** {text_channels}\n"
            f"🔊 **Voice Channels:** {voice_channels}\n"
            f"🛡️ **Roles:** {len(guild.roles)}",
            AURA_BLUE,
            "📊"
        )
    )


# =========================================================
# AUTOMOD
# =========================================================

automod_group = app_commands.Group(
    name="automod",
    description="Manage AuraGuard AutoMod."
)


@automod_group.command(name="enable", description="Enable blocked-word AutoMod.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_enable(interaction: discord.Interaction):
    settings = get_automod(interaction.guild.id)
    settings["enabled"] = True
    save_data()

    await interaction.response.send_message(
        "🛡️ AutoMod is now enabled.",
        ephemeral=True
    )


@automod_group.command(name="disable", description="Disable blocked-word AutoMod.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_disable(interaction: discord.Interaction):
    settings = get_automod(interaction.guild.id)
    settings["enabled"] = False
    save_data()

    await interaction.response.send_message(
        "🔴 AutoMod is now disabled.",
        ephemeral=True
    )


@automod_group.command(name="addword", description="Add a blocked word or phrase.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_addword(interaction: discord.Interaction, word: str):
    settings = get_automod(interaction.guild.id)
    word = word.strip()

    if not word:
        await interaction.response.send_message(
            "❌ Enter a valid word or phrase.",
            ephemeral=True
        )
        return

    if word.lower() in [item.lower() for item in settings["blocked_words"]]:
        await interaction.response.send_message(
            "❌ That word is already blocked.",
            ephemeral=True
        )
        return

    settings["blocked_words"].append(word)
    save_data()

    await interaction.response.send_message(
        f"🛡️ Added `{word}` to the blocked-word list.",
        ephemeral=True
    )


@automod_group.command(name="removeword", description="Remove a blocked word or phrase.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_removeword(interaction: discord.Interaction, word: str):
    settings = get_automod(interaction.guild.id)

    match = next(
        (item for item in settings["blocked_words"]
         if item.lower() == word.lower()),
        None
    )

    if match is None:
        await interaction.response.send_message(
            "❌ That word is not on the blocked list.",
            ephemeral=True
        )
        return

    settings["blocked_words"].remove(match)
    save_data()

    await interaction.response.send_message(
        f"✅ Removed `{match}` from the blocked-word list.",
        ephemeral=True
    )


@automod_group.command(name="list", description="View blocked words.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_list(interaction: discord.Interaction):
    settings = get_automod(interaction.guild.id)
    words = settings.get("blocked_words", [])

    text = "\n".join(f"• `{word}`" for word in words) if words else "No blocked words."

    await interaction.response.send_message(
        embed=aura_embed(
            "AutoMod Settings",
            f"**Status:** {'🟢 Enabled' if settings['enabled'] else '🔴 Disabled'}\n\n"
            f"**Blocked Words:**\n{text[:3500]}",
            AURA_PURPLE,
            "🛡️"
        ),
        ephemeral=True
    )


bot.tree.add_command(automod_group)


# =========================================================
# BACKUPS
# =========================================================

backup_group = app_commands.Group(
    name="backup",
    description="Manage server backups."
)


@backup_group.command(name="create", description="Create a server structure backup.")
@app_commands.checks.has_permissions(administrator=True)
async def backup_create(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild

    backup = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "guild_name": guild.name,
        "roles": [],
        "categories": [],
        "channels": []
    }

    for role in guild.roles:
        if role.is_default() or role.managed:
            continue

        backup["roles"].append({
            "name": role.name,
            "permissions": role.permissions.value,
            "color": role.color.value,
            "hoist": role.hoist,
            "mentionable": role.mentionable
        })

    for category in guild.categories:
        backup["categories"].append({"name": category.name})

    for channel in guild.channels:
        category_name = channel.category.name if getattr(channel, "category", None) else None

        if isinstance(channel, discord.TextChannel):
            backup["channels"].append({
                "name": channel.name,
                "type": "text",
                "category": category_name,
                "topic": channel.topic,
                "nsfw": channel.is_nsfw(),
                "slowmode": channel.slowmode_delay
            })

        elif isinstance(channel, discord.VoiceChannel):
            backup["channels"].append({
                "name": channel.name,
                "type": "voice",
                "category": category_name,
                "bitrate": channel.bitrate,
                "user_limit": channel.user_limit
            })

    guild_backups = data["backups"].setdefault(str(guild.id), {})
    backup_id = make_unique_id(guild_backups)
    guild_backups[backup_id] = backup
    save_data()

    await interaction.followup.send(
        embed=aura_embed(
            "Backup Created",
            f"💾 **Backup ID:** `{backup_id}`\n\n"
            f"🛡️ Roles: {len(backup['roles'])}\n"
            f"📁 Categories: {len(backup['categories'])}\n"
            f"📋 Channels: {len(backup['channels'])}\n\n"
            "Keep your Backup ID safe.",
            AURA_GREEN,
            "💾"
        ),
        ephemeral=True
    )


@backup_group.command(name="list", description="List server backups.")
@app_commands.checks.has_permissions(administrator=True)
async def backup_list(interaction: discord.Interaction):
    backups = data["backups"].get(str(interaction.guild.id), {})

    if not backups:
        await interaction.response.send_message(
            "💾 No backups found.",
            ephemeral=True
        )
        return

    text = "".join(
        f"💾 `{backup_id}` — {backup.get('created_at', 'Unknown')}\n"
        for backup_id, backup in backups.items()
    )

    await interaction.response.send_message(
        embed=aura_embed("AuraGuard Backups", text[:4000], AURA_PURPLE, "💾"),
        ephemeral=True
    )


@backup_group.command(name="info", description="View backup information.")
@app_commands.checks.has_permissions(administrator=True)
async def backup_info(interaction: discord.Interaction, backup_id: str):
    backup = data["backups"].get(str(interaction.guild.id), {}).get(backup_id)

    if not backup:
        await interaction.response.send_message(
            "❌ Backup not found.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        embed=aura_embed(
            "Backup Information",
            f"🆔 ID: `{backup_id}`\n"
            f"📅 Created: {backup['created_at']}\n"
            f"🛡️ Roles: {len(backup['roles'])}\n"
            f"📁 Categories: {len(backup['categories'])}\n"
            f"📋 Channels: {len(backup['channels'])}",
            AURA_PURPLE,
            "💾"
        ),
        ephemeral=True
    )


@backup_group.command(name="restore", description="Restore missing roles, categories and channels.")
@app_commands.checks.has_permissions(administrator=True)
async def backup_restore(
    interaction: discord.Interaction,
    backup_id: str,
    confirm: bool = False
):
    backup = data["backups"].get(str(interaction.guild.id), {}).get(backup_id)

    if not backup:
        await interaction.response.send_message(
            "❌ Backup not found.",
            ephemeral=True
        )
        return

    if not confirm:
        await interaction.response.send_message(
            embed=aura_embed(
                "Restore Confirmation",
                f"⚠️ Backup `{backup_id}` will recreate missing roles, "
                "categories and channels.\n\n"
                "It will **not delete** existing server content.\n\n"
                "Run the command again with `confirm: True`.",
                AURA_YELLOW,
                "⚠️"
            ),
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild

    created_roles = 0
    created_categories = 0
    created_channels = 0

    role_names = {role.name for role in guild.roles}

    for role_data in backup["roles"]:
        if role_data["name"] in role_names:
            continue

        try:
            await guild.create_role(
                name=role_data["name"],
                permissions=discord.Permissions(role_data["permissions"]),
                colour=discord.Colour(role_data["color"]),
                hoist=role_data["hoist"],
                mentionable=role_data["mentionable"],
                reason="AuraGuard backup restore"
            )
            created_roles += 1
        except Exception as e:
            print(f"Role restore error: {e}")

    category_map = {category.name: category for category in guild.categories}

    for category_data in backup["categories"]:
        name = category_data["name"]

        if name in category_map:
            continue

        try:
            category = await guild.create_category(
                name,
                reason="AuraGuard backup restore"
            )
            category_map[name] = category
            created_categories += 1
        except Exception as e:
            print(f"Category restore error: {e}")

    existing_channels = {
        (
            channel.name,
            channel.category.name if getattr(channel, "category", None) else None,
            type(channel).__name__
        )
        for channel in guild.channels
    }

    for channel_data in backup["channels"]:
        channel_type = channel_data["type"]
        key_type = "TextChannel" if channel_type == "text" else "VoiceChannel"

        key = (
            channel_data["name"],
            channel_data["category"],
            key_type
        )

        if key in existing_channels:
            continue

        category = category_map.get(channel_data["category"])

        try:
            if channel_type == "text":
                await guild.create_text_channel(
                    channel_data["name"],
                    category=category,
                    topic=channel_data.get("topic"),
                    nsfw=channel_data.get("nsfw", False),
                    slowmode_delay=channel_data.get("slowmode", 0),
                    reason="AuraGuard backup restore"
                )
            elif channel_type == "voice":
                await guild.create_voice_channel(
                    channel_data["name"],
                    category=category,
                    bitrate=channel_data.get("bitrate", 64000),
                    user_limit=channel_data.get("user_limit", 0),
                    reason="AuraGuard backup restore"
                )

            created_channels += 1

        except Exception as e:
            print(f"Channel restore error: {e}")

    await interaction.followup.send(
        embed=aura_embed(
            "Backup Restore Complete",
            f"🛡️ Roles created: **{created_roles}**\n"
            f"📁 Categories created: **{created_categories}**\n"
            f"📋 Channels created: **{created_channels}**\n\n"
            "Existing server content was not deleted.",
            AURA_GREEN,
            "💾"
        ),
        ephemeral=True
    )


bot.tree.add_command(backup_group)


# =========================================================
# ERROR HANDLER
# =========================================================

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction,
                               error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        message = "❌ You don't have permission to use that command."
    elif isinstance(error, app_commands.CheckFailure):
        message = "❌ You can't use that command."
    else:
        print(f"Command error: {error}")
        message = "❌ Something went wrong while running that command."

    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except Exception:
        pass


# =========================================================
# START BOT
# =========================================================

bot.run(TOKEN)
