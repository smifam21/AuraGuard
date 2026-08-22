import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import json
import random
import asyncio
from datetime import datetime, timedelta, timezone

# =========================================================
# AURAGUARD
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from Railway Variables.")

DATA_FILE = "auraguard_data.json"

# =========================================================
# AURA BRANDING
# =========================================================

AURA_PURPLE = 0x8A2BE2
AURA_GREEN = 0x2ECC71
AURA_RED = 0xE74C3C
AURA_YELLOW = 0xF1C40F
AURA_BLUE = 0x3498DB

FOOTER = "AuraGuard • Powered by Aura"

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

def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "settings": {},
            "warnings": {},
            "giveaways": {},
            "backups": {}
        }

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "settings": {},
            "warnings": {},
            "giveaways": {},
            "backups": {}
        }


data = load_data()


def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def get_settings(guild_id):
    guild_id = str(guild_id)

    if guild_id not in data["settings"]:
        data["settings"][guild_id] = {
            "welcome_enabled": False,
            "welcome_channel": None,
            "welcome_message": "Welcome {user} to {server}! 🛡️",

            "leave_enabled": False,
            "leave_channel": None,
            "leave_message": "{user} has left {server}. 👋",

            "ticket_category": None,
            "staff_role": None,
            "log_channel": None
        }
        save_data()

    return data["settings"][guild_id]


# =========================================================
# EMBEDS
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
        timestamp=datetime.now(timezone.utc)
    )

    embed.set_footer(text=FOOTER)

    return embed


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    print("================================")
    print(f"AuraGuard online as {bot.user}")
    print(f"Bot ID: {bot.user.id}")
    print("================================")

    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="over your server 🛡️"
        )
    )

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"Sync error: {e}")

    if not giveaway_loop.is_running():
        giveaway_loop.start()


# =========================================================
# LOGGING
# =========================================================

async def send_log(
    guild,
    title,
    description,
    color=AURA_PURPLE
):

    settings = get_settings(guild.id)
    channel_id = settings.get("log_channel")

    if not channel_id:
        return

    channel = guild.get_channel(channel_id)

    if not channel:
        return

    try:
        await channel.send(
            embed=aura_embed(
                title,
                description,
                color
            )
        )
    except discord.HTTPException:
        pass


# =========================================================
# PING
# =========================================================

@bot.tree.command(
    name="ping",
    description="Check AuraGuard's latency."
)
async def ping(interaction: discord.Interaction):

    latency = round(bot.latency * 1000)

    await interaction.response.send_message(
        embed=aura_embed(
            "AuraGuard Online",
            f"⚡ Pong!\n\nLatency: **{latency}ms**",
            AURA_PURPLE,
            "⚡"
        )
    )


# =========================================================
# HELP
# =========================================================

@bot.tree.command(
    name="help",
    description="Show AuraGuard commands."
)
async def help_command(interaction: discord.Interaction):

    embed = aura_embed(
        "AuraGuard",
        """
**👋 Welcome**
`/welcome setup`
`/welcome enable`
`/welcome disable`
`/welcome test`
`/welcome settings`

**🚪 Leave**
`/leave setup`
`/leave enable`
`/leave disable`
`/leave test`
`/leave settings`

**🎫 Tickets**
`/tickets setup`
`/tickets panel`

**🎉 Giveaways**
`/giveaway start`
`/giveaway end`
`/giveaway reroll`
`/giveaway entries`

**🛡️ Moderation**
`/kick`
`/ban`
`/unban`
`/timeout`
`/untimeout`
`/warn`
`/clear`

**💾 Backups**
`/backup create`
`/backup list`
`/backup restore`

**⚙️ Server**
`/setstaffrole`
`/setlogchannel`

⚡ **Powered by Aura**
        """,
        AURA_PURPLE,
        "⚡"
    )

    await interaction.response.send_message(embed=embed)


# =========================================================
# WELCOME SYSTEM
# =========================================================

welcome_group = app_commands.Group(
    name="welcome",
    description="Manage welcome messages."
)


@welcome_group.command(
    name="setup",
    description="Set the welcome channel and message."
)
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
            f"👋 **Channel:** {channel.mention}\n\n"
            f"**Message:**\n{message}\n\n"
            f"**Status:** "
            f"{'🟢 Enabled' if settings['welcome_enabled'] else '🔴 Disabled'}\n\n"
            f"Use `/welcome enable` to turn it on.",
            AURA_PURPLE,
            "👋"
        ),
        ephemeral=True
    )


@welcome_group.command(
    name="enable",
    description="Enable welcome messages."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_enable(interaction: discord.Interaction):

    settings = get_settings(interaction.guild.id)

    if not settings.get("welcome_channel"):

        await interaction.response.send_message(
            "❌ Run `/welcome setup` first.",
            ephemeral=True
        )
        return

    settings["welcome_enabled"] = True
    save_data()

    await interaction.response.send_message(
        embed=aura_embed(
            "Welcome Enabled",
            "🟢 AuraGuard will now welcome new members.",
            AURA_GREEN,
            "👋"
        )
    )


@welcome_group.command(
    name="disable",
    description="Disable welcome messages."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_disable(interaction: discord.Interaction):

    settings = get_settings(interaction.guild.id)

    settings["welcome_enabled"] = False
    save_data()

    await interaction.response.send_message(
        embed=aura_embed(
            "Welcome Disabled",
            "🔴 Welcome messages are now disabled.",
            AURA_RED,
            "👋"
        )
    )


@welcome_group.command(
    name="test",
    description="Test the welcome message."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_test(interaction: discord.Interaction):

    settings = get_settings(interaction.guild.id)

    channel_id = settings.get("welcome_channel")

    if not channel_id:

        await interaction.response.send_message(
            "❌ Run `/welcome setup` first.",
            ephemeral=True
        )
        return

    channel = interaction.guild.get_channel(channel_id)

    if not channel:

        await interaction.response.send_message(
            "❌ The configured welcome channel no longer exists.",
            ephemeral=True
        )
        return

    message = settings.get(
        "welcome_message",
        "Welcome {user} to {server}! 🛡️"
    )

    message = message.replace(
        "{user}",
        interaction.user.mention
    ).replace(
        "{server}",
        interaction.guild.name
    )

    await channel.send(
        embed=aura_embed(
            "Welcome Test",
            message,
            AURA_PURPLE,
            "👋"
        )
    )

    await interaction.response.send_message(
        f"✅ Test sent to {channel.mention}.",
        ephemeral=True
    )


@welcome_group.command(
    name="settings",
    description="View welcome settings."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_settings(interaction: discord.Interaction):

    settings = get_settings(interaction.guild.id)

    channel = interaction.guild.get_channel(
        settings.get("welcome_channel")
    )

    channel_text = (
        channel.mention
        if channel
        else "Not configured"
    )

    status = (
        "🟢 Enabled"
        if settings.get("welcome_enabled")
        else "🔴 Disabled"
    )

    await interaction.response.send_message(
        embed=aura_embed(
            "Welcome Settings",
            f"**Status:** {status}\n"
            f"**Channel:** {channel_text}\n\n"
            f"**Message:**\n"
            f"{settings.get('welcome_message')}",
            AURA_PURPLE,
            "👋"
        ),
        ephemeral=True
    )


bot.tree.add_command(welcome_group)


# =========================================================
# LEAVE SYSTEM
# =========================================================

leave_group = app_commands.Group(
    name="leave",
    description="Manage leave messages."
)


@leave_group.command(
    name="setup",
    description="Set the leave channel and message."
)
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
        embed=aura_embed(
            "Leave Setup",
            f"🚪 **Channel:** {channel.mention}\n\n"
            f"**Message:**\n{message}\n\n"
            f"**Status:** "
            f"{'🟢 Enabled' if settings['leave_enabled'] else '🔴 Disabled'}\n\n"
            f"Use `/leave enable` to turn it on.",
            AURA_PURPLE,
            "🚪"
        ),
        ephemeral=True
    )


@leave_group.command(
    name="enable",
    description="Enable leave messages."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_enable(interaction: discord.Interaction):

    settings = get_settings(interaction.guild.id)

    if not settings.get("leave_channel"):

        await interaction.response.send_message(
            "❌ Run `/leave setup` first.",
            ephemeral=True
        )
        return

    settings["leave_enabled"] = True
    save_data()

    await interaction.response.send_message(
        embed=aura_embed(
            "Leave Enabled",
            "🟢 AuraGuard will now send leave messages.",
            AURA_GREEN,
            "🚪"
        )
    )


@leave_group.command(
    name="disable",
    description="Disable leave messages."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_disable(interaction: discord.Interaction):

    settings = get_settings(interaction.guild.id)

    settings["leave_enabled"] = False
    save_data()

    await interaction.response.send_message(
        embed=aura_embed(
            "Leave Disabled",
            "🔴 Leave messages are now disabled.",
            AURA_RED,
            "🚪"
        )
    )


@leave_group.command(
    name="test",
    description="Test the leave message."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_test(interaction: discord.Interaction):

    settings = get_settings(interaction.guild.id)

    channel_id = settings.get("leave_channel")

    if not channel_id:

        await interaction.response.send_message(
            "❌ Run `/leave setup` first.",
            ephemeral=True
        )
        return

    channel = interaction.guild.get_channel(channel_id)

    if not channel:

        await interaction.response.send_message(
            "❌ The configured leave channel no longer exists.",
            ephemeral=True
        )
        return

    message = settings.get(
        "leave_message",
        "{user} has left {server}. 👋"
    )

    message = message.replace(
        "{user}",
        interaction.user.mention
    ).replace(
        "{server}",
        interaction.guild.name
    )

    await channel.send(
        embed=aura_embed(
            "Leave Test",
            message,
            AURA_YELLOW,
            "🚪"
        )
    )

    await interaction.response.send_message(
        f"✅ Test sent to {channel.mention}.",
        ephemeral=True
    )


@leave_group.command(
    name="settings",
    description="View leave settings."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_settings(interaction: discord.Interaction):

    settings = get_settings(interaction.guild.id)

    channel = interaction.guild.get_channel(
        settings.get("leave_channel")
    )

    channel_text = (
        channel.mention
        if channel
        else "Not configured"
    )

    status = (
        "🟢 Enabled"
        if settings.get("leave_enabled")
        else "🔴 Disabled"
    )

    await interaction.response.send_message(
        embed=aura_embed(
            "Leave Settings",
            f"**Status:** {status}\n"
            f"**Channel:** {channel_text}\n\n"
            f"**Message:**\n"
            f"{settings.get('leave_message')}",
            AURA_PURPLE,
            "🚪"
        ),
        ephemeral=True
    )


bot.tree.add_command(leave_group)


# =========================================================
# MEMBER JOIN / LEAVE
# =========================================================

@bot.event
async def on_member_join(member):

    settings = get_settings(member.guild.id)

    if not settings.get("welcome_enabled"):
        return

    channel_id = settings.get("welcome_channel")

    if not channel_id:
        return

    channel = member.guild.get_channel(channel_id)

    if not channel:
        return

    message = settings.get(
        "welcome_message",
        "Welcome {user} to {server}! 🛡️"
    )

    message = message.replace(
        "{user}",
        member.mention
    ).replace(
        "{server}",
        member.guild.name
    )

    try:
        await channel.send(
            embed=aura_embed(
                "Welcome!",
                message,
                AURA_PURPLE,
                "👋"
            )
        )
    except discord.HTTPException:
        pass


@bot.event
async def on_member_remove(member):

    settings = get_settings(member.guild.id)

    if not settings.get("leave_enabled"):
        return

    channel_id = settings.get("leave_channel")

    if not channel_id:
        return

    channel = member.guild.get_channel(channel_id)

    if not channel:
        return

    message = settings.get(
        "leave_message",
        "{user} has left {server}. 👋"
    )

    message = message.replace(
        "{user}",
        str(member)
    ).replace(
        "{server}",
        member.guild.name
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
    except discord.HTTPException:
        pass


# =========================================================
# STAFF ROLE / LOG CHANNEL
# =========================================================

@bot.tree.command(
    name="setstaffrole",
    description="Set AuraGuard's staff role."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def setstaffrole(
    interaction: discord.Interaction,
    role: discord.Role
):

    settings = get_settings(interaction.guild.id)

    settings["staff_role"] = role.id

    save_data()

    await interaction.response.send_message(
        embed=aura_embed(
            "Staff Role Set",
            f"🛡️ Staff role: {role.mention}",
            AURA_GREEN,
            "🛡️"
        )
    )


@bot.tree.command(
    name="setlogchannel",
    description="Set the moderation log channel."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def setlogchannel(
    interaction: discord.Interaction,
    channel: discord.TextChannel
):

    settings = get_settings(interaction.guild.id)

    settings["log_channel"] = channel.id

    save_data()

    await interaction.response.send_message(
        embed=aura_embed(
            "Log Channel Set",
            f"📋 Logs will be sent to {channel.mention}.",
            AURA_GREEN,
            "📋"
        )
    )


# =========================================================
# MODERATION
# =========================================================

@bot.tree.command(
    name="kick",
    description="Kick a member."
)
@app_commands.checks.has_permissions(kick_members=True)
async def kick(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):

    if member == interaction.user:

        await interaction.response.send_message(
            "❌ You can't kick yourself.",
            ephemeral=True
        )
        return

    try:

        await member.kick(reason=reason)

        await interaction.response.send_message(
            embed=aura_embed(
                "Member Kicked",
                f"👢 {member.mention}\n\n"
                f"**Reason:** {reason}",
                AURA_RED,
                "👢"
            )
        )

        await send_log(
            interaction.guild,
            "Member Kicked",
            f"**Member:** {member}\n"
            f"**Moderator:** {interaction.user.mention}\n"
            f"**Reason:** {reason}",
            AURA_RED
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I can't kick that member.",
            ephemeral=True
        )


@bot.tree.command(
    name="ban",
    description="Ban a member."
)
@app_commands.checks.has_permissions(ban_members=True)
async def ban(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):

    try:

        await member.ban(reason=reason)

        await interaction.response.send_message(
            embed=aura_embed(
                "Member Banned",
                f"🔨 {member.mention}\n\n"
                f"**Reason:** {reason}",
                AURA_RED,
                "🔨"
            )
        )

        await send_log(
            interaction.guild,
            "Member Banned",
            f"**Member:** {member}\n"
            f"**Moderator:** {interaction.user.mention}\n"
            f"**Reason:** {reason}",
            AURA_RED
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I can't ban that member.",
            ephemeral=True
        )


@bot.tree.command(
    name="unban",
    description="Unban a user by ID."
)
@app_commands.checks.has_permissions(ban_members=True)
async def unban(
    interaction: discord.Interaction,
    user_id: str
):

    try:

        user = await bot.fetch_user(int(user_id))

        await interaction.guild.unban(user)

        await interaction.response.send_message(
            embed=aura_embed(
                "User Unbanned",
                f"🔓 {user} has been unbanned.",
                AURA_GREEN,
                "🔓"
            )
        )

    except (ValueError, discord.NotFound):

        await interaction.response.send_message(
            "❌ User not found or isn't banned.",
            ephemeral=True
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I can't unban that user.",
            ephemeral=True
        )


@bot.tree.command(
    name="timeout",
    description="Timeout a member."
)
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

    until = discord.utils.utcnow() + timedelta(
        minutes=minutes
    )

    try:

        await member.timeout(
            until,
            reason=reason
        )

        await interaction.response.send_message(
            embed=aura_embed(
                "Member Timed Out",
                f"⏳ {member.mention}\n"
                f"**Duration:** {minutes} minutes\n"
                f"**Reason:** {reason}",
                AURA_YELLOW,
                "⏳"
            )
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I can't timeout that member.",
            ephemeral=True
        )


@bot.tree.command(
    name="untimeout",
    description="Remove a member's timeout."
)
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout(
    interaction: discord.Interaction,
    member: discord.Member
):

    try:

        await member.timeout(None)

        await interaction.response.send_message(
            embed=aura_embed(
                "Timeout Removed",
                f"🔓 {member.mention} can speak again.",
                AURA_GREEN,
                "🔓"
            )
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I can't remove that timeout.",
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
    interaction: discord.Interaction,
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
        embed=aura_embed(
            "Messages Cleared",
            f"🧹 Deleted **{len(deleted)}** messages.",
            AURA_GREEN,
            "🧹"
        ),
        ephemeral=True
    )


# =========================================================
# WARN
# =========================================================

@bot.tree.command(
    name="warn",
    description="Warn a member."
)
@app_commands.checks.has_permissions(
    moderate_members=True
)
async def warn(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):

    guild_id = str(interaction.guild.id)
    user_id = str(member.id)

    if guild_id not in data["warnings"]:
        data["warnings"][guild_id] = {}

    if user_id not in data["warnings"][guild_id]:
        data["warnings"][guild_id][user_id] = []

    data["warnings"][guild_id][user_id].append({
        "reason": reason,
        "moderator": interaction.user.id,
        "time": datetime.now(
            timezone.utc
        ).isoformat()
    })

    save_data()

    count = len(
        data["warnings"][guild_id][user_id]
    )

    await interaction.response.send_message(
        embed=aura_embed(
            "Warning Issued",
            f"⚠️ {member.mention}\n\n"
            f"**Reason:** {reason}\n"
            f"**Warnings:** {count}",
            AURA_YELLOW,
            "⚠️"
        )
    )


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
    async def open_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        guild = interaction.guild
        user = interaction.user

        existing = discord.utils.get(
            guild.text_channels,
            name=f"ticket-{user.id}"
        )

        if existing:

            await interaction.response.send_message(
                f"🎫 You already have {existing.mention}.",
                ephemeral=True
            )
            return

        settings = get_settings(guild.id)

        category = guild.get_channel(
            settings.get("ticket_category")
        )

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

        staff_role = guild.get_role(
            settings.get("staff_role")
        )

        if staff_role:

            overwrites[staff_role] = (
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )
            )

        channel = await guild.create_text_channel(
            f"ticket-{user.id}",
            category=category,
            overwrites=overwrites,
            reason="AuraGuard ticket"
        )

        await channel.send(
            embed=aura_embed(
                "Ticket Opened",
                f"Welcome {user.mention}!\n\n"
                "A staff member will help you soon.",
                AURA_PURPLE,
                "🎫"
            ),
            view=TicketControls()
        )

        await interaction.response.send_message(
            f"🎫 Ticket created: {channel.mention}",
            ephemeral=True
        )


class TicketControls(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Claim",
        style=discord.ButtonStyle.success,
        emoji="🙋",
        custom_id="auraguard_claim"
    )
    async def claim(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        settings = get_settings(
            interaction.guild.id
        )

        role = interaction.guild.get_role(
            settings.get("staff_role")
        )

        if not role or role not in interaction.user.roles:

            await interaction.response.send_message(
                "❌ Only staff can claim tickets.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            embed=aura_embed(
                "Ticket Claimed",
                f"🙋 Claimed by {interaction.user.mention}.",
                AURA_GREEN,
                "🙋"
            )
        )

    @discord.ui.button(
        label="Close",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="auraguard_close"
    )
    async def close(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        settings = get_settings(
            interaction.guild.id
        )

        role = interaction.guild.get_role(
            settings.get("staff_role")
        )

        if (
            not role
            or role not in interaction.user.roles
        ) and not interaction.user.guild_permissions.manage_channels:

            await interaction.response.send_message(
                "❌ Only staff can close tickets.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            embed=aura_embed(
                "Ticket Closing",
                "🔒 Closing in **5 seconds**.",
                AURA_RED,
                "🔒"
            )
        )

        await asyncio.sleep(5)

        try:
            await interaction.channel.delete(
                reason="AuraGuard ticket closed"
            )
        except discord.HTTPException:
            pass


tickets_group = app_commands.Group(
    name="tickets",
    description="Manage AuraGuard tickets."
)


@tickets_group.command(
    name="setup",
    description="Set the ticket category."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def tickets_setup(
    interaction: discord.Interaction,
    category: discord.CategoryChannel
):

    settings = get_settings(
        interaction.guild.id
    )

    settings["ticket_category"] = category.id

    save_data()

    await interaction.response.send_message(
        embed=aura_embed(
            "Tickets Setup",
            f"🎫 Category: **{category.name}**",
            AURA_GREEN,
            "🎫"
        )
    )


@tickets_group.command(
    name="panel",
    description="Send the ticket panel."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def tickets_panel(
    interaction: discord.Interaction
):

    await interaction.response.send_message(
        embed=aura_embed(
            "Support Tickets",
            "Need help?\n\n"
            "Click **Open Ticket** below.",
            AURA_PURPLE,
            "🎫"
        ),
        view=TicketView()
    )


bot.tree.add_command(tickets_group)


# =========================================================
# GIVEAWAYS
# =========================================================

giveaway_entries = {}


class GiveawayView(discord.ui.View):

    def __init__(self, giveaway_id):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id

    @discord.ui.button(
        label="Enter Giveaway",
        style=discord.ButtonStyle.success,
        emoji="🎉"
    )
    async def enter(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        gid = self.giveaway_id

        if gid not in giveaway_entries:
            giveaway_entries[gid] = {}

        user_id = str(interaction.user.id)

        if user_id in giveaway_entries[gid]:

            await interaction.response.send_message(
                "❌ You're already entered.",
                ephemeral=True
            )
            return

        giveaway_entries[gid][user_id] = 1

        await interaction.response.send_message(
            "🎉 You're entered with **1 entry**!",
            ephemeral=True
        )


giveaway_group = app_commands.Group(
    name="giveaway",
    description="Manage giveaways."
)


@giveaway_group.command(
    name="start",
    description="Start a giveaway."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_start(
    interaction: discord.Interaction,
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

    giveaway_id = str(
        random.randint(100000, 999999)
    )

    end = (
        datetime.now(timezone.utc)
        + timedelta(minutes=minutes)
    )

    data["giveaways"][giveaway_id] = {
        "guild": interaction.guild.id,
        "channel": interaction.channel.id,
        "prize": prize,
        "winners": winners,
        "end_time": end.isoformat()
    }

    giveaway_entries[giveaway_id] = {}

    save_data()

    await interaction.response.send_message(
        embed=aura_embed(
            "GIVEAWAY",
            f"🎁 **Prize:** {prize}\n"
            f"🏆 **Winners:** {winners}\n"
            f"⏰ **Ends:** <t:{int(end.timestamp())}:R>\n\n"
            f"Click below to enter!",
            AURA_PURPLE,
            "🎉"
        ),
        view=GiveawayView(giveaway_id)
    )


@giveaway_group.command(
    name="end",
    description="End a giveaway."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_end(
    interaction: discord.Interaction,
    giveaway_id: str
):

    giveaway = data["giveaways"].get(giveaway_id)

    if not giveaway:

        await interaction.response.send_message(
            "❌ Giveaway not found.",
            ephemeral=True
        )
        return

    entries = giveaway_entries.get(
        giveaway_id,
        {}
    )

    if not entries:

        await interaction.response.send_message(
            "🎉 Giveaway ended, but nobody entered."
        )

    else:

        count = min(
            giveaway["winners"],
            len(entries)
        )

        winners = random.sample(
            list(entries.keys()),
            count
        )

        mentions = " ".join(
            f"<@{x}>"
            for x in winners
        )

        await interaction.response.send_message(
            embed=aura_embed(
                "Giveaway Winner!",
                f"🎁 **Prize:** {giveaway['prize']}\n\n"
                f"🏆 {mentions}",
                AURA_GREEN,
                "🏆"
            )
        )

    data["giveaways"].pop(
        giveaway_id,
        None
    )

    giveaway_entries.pop(
        giveaway_id,
        None
    )

    save_data()


@giveaway_group.command(
    name="reroll",
    description="Reroll a giveaway."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_reroll(
    interaction: discord.Interaction,
    giveaway_id: str
):

    entries = giveaway_entries.get(
        giveaway_id,
        {}
    )

    if not entries:

        await interaction.response.send_message(
            "❌ No entries found.",
            ephemeral=True
        )
        return

    winner = random.choice(
        list(entries.keys())
    )

    await interaction.response.send_message(
        embed=aura_embed(
            "Giveaway Reroll",
            f"🔄 New winner: <@{winner}>",
            AURA_GREEN,
            "🔄"
        )
    )


@giveaway_group.command(
    name="entries",
    description="Check your giveaway entries."
)
async def giveaway_entries_command(
    interaction: discord.Interaction,
    giveaway_id: str
):

    entries = giveaway_entries.get(
        giveaway_id,
        {}
    )

    amount = entries.get(
        str(interaction.user.id),
        0
    )

    await interaction.response.send_message(
        f"🎟️ You have **{amount} entries**.",
        ephemeral=True
    )


bot.tree.add_command(giveaway_group)


# =========================================================
# GIVEAWAY LOOP
# =========================================================

@tasks.loop(seconds=10)
async def giveaway_loop():

    now = datetime.now(timezone.utc)

    finished = []

    for gid, giveaway in list(
        data["giveaways"].items()
    ):

        end = datetime.fromisoformat(
            giveaway["end_time"]
        )

        if now < end:
            continue

        guild = bot.get_guild(
            giveaway["guild"]
        )

        if not guild:
            finished.append(gid)
            continue

        channel = guild.get_channel(
            giveaway["channel"]
        )

        if not channel:
            finished.append(gid)
            continue

        entries = giveaway_entries.get(
            gid,
            {}
        )

        if entries:

            count = min(
                giveaway["winners"],
                len(entries)
            )

            winners = random.sample(
                list(entries.keys()),
                count
            )

            mentions = " ".join(
                f"<@{x}>"
                for x in winners
            )

            await channel.send(
                embed=aura_embed(
                    "Giveaway Winner!",
                    f"🎁 **Prize:** {giveaway['prize']}\n\n"
                    f"🏆 {mentions}",
                    AURA_GREEN,
                    "🏆"
                )
            )

        else:

            await channel.send(
                embed=aura_embed(
                    "Giveaway Ended",
                    f"🎁 **{giveaway['prize']}**\n\n"
                    "Nobody entered.",
                    AURA_YELLOW,
                    "🎉"
                )
            )

        finished.append(gid)

    for gid in finished:

        data["giveaways"].pop(
            gid,
            None
        )

        giveaway_entries.pop(
            gid,
            None
        )

    if finished:
        save_data()


# =========================================================
# BACKUPS
# =========================================================

backup_group = app_commands.Group(
    name="backup",
    description="Manage server backups."
)


@backup_group.command(
    name="create",
    description="Create a server structure backup."
)
@app_commands.checks.has_permissions(administrator=True)
async def backup_create(
    interaction: discord.Interaction
):

    await interaction.response.defer(
        ephemeral=True
    )

    guild = interaction.guild

    backup = {
        "name": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "roles": [],
        "categories": [],
        "channels": []
    }

    for role in guild.roles:

        if role.is_default():
            continue

        backup["roles"].append({
            "name": role.name,
            "permissions": role.permissions.value,
            "color": role.color.value,
            "hoist": role.hoist,
            "mentionable": role.mentionable
        })

    for category in guild.categories:

        backup["categories"].append({
            "name": category.name
        })

    for channel in guild.channels:

        if isinstance(
            channel,
            discord.TextChannel
        ):

            backup["channels"].append({
                "name": channel.name,
                "type": "text",
                "category": (
                    channel.category.name
                    if channel.category
                    else None
                ),
                "topic": channel.topic
            })

        elif isinstance(
            channel,
            discord.VoiceChannel
        ):

            backup["channels"].append({
                "name": channel.name,
                "type": "voice",
                "category": (
                    channel.category.name
                    if channel.category
                    else None
                )
            })

    backup_id = str(
        random.randint(100000, 999999)
    )

    gid = str(guild.id)

    if gid not in data["backups"]:
        data["backups"][gid] = {}

    data["backups"][gid][backup_id] = backup

    save_data()

    await interaction.followup.send(
        embed=aura_embed(
            "Backup Created",
            f"💾 **Backup ID:** `{backup_id}`\n\n"
            f"🛡️ Roles: **{len(backup['roles'])}**\n"
            f"📁 Categories: **{len(backup['categories'])}**\n"
            f"📋 Channels: **{len(backup['channels'])}**",
            AURA_GREEN,
            "💾"
        ),
        ephemeral=True
    )


@backup_group.command(
    name="list",
    description="List your server backups."
)
@app_commands.checks.has_permissions(administrator=True)
async def backup_list(
    interaction: discord.Interaction
):

    backups = data["backups"].get(
        str(interaction.guild.id),
        {}
    )

    if not backups:

        await interaction.response.send_message(
            "💾 No backups found.",
            ephemeral=True
        )
        return

    text = ""

    for backup_id, backup in backups.items():

        text += (
            f"💾 `{backup_id}` — "
            f"{backup['name']}\n"
        )

    await interaction.response.send_message(
        embed=aura_embed(
            "AuraGuard Backups",
            text,
            AURA_PURPLE,
            "💾"
        ),
        ephemeral=True
    )


@backup_group.command(
    name="restore",
    description="Restore a backup safely."
)
@app_commands.checks.has_permissions(administrator=True)
async def backup_restore(
    interaction: discord.Interaction,
    backup_id: str
):

    await interaction.response.send_message(
        embed=aura_embed(
            "Backup Restore",
            "⚠️ **Restore is not automatic yet.**\n\n"
            "This safety message prevents an accidental "
            "server-wide change while we finish the "
            "full restore system.",
            AURA_YELLOW,
            "⚠️"
        ),
        ephemeral=True
    )


bot.tree.add_command(backup_group)


# =========================================================
# PERSISTENT TICKET VIEWS
# =========================================================

bot.add_view(TicketView())
bot.add_view(TicketControls())


# =========================================================
# START BOT
# =========================================================

bot.run(TOKEN)
