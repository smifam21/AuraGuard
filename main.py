
import discord
from discord.ext import commands, tasks
from discord import app_commands
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
    raise RuntimeError("DISCORD_TOKEN environment variable is missing.")

DATA_FILE = "auraguard_data.json"

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
    except:
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


def guild_settings(guild_id):
    guild_id = str(guild_id)

    if guild_id not in data["settings"]:
        data["settings"][guild_id] = {
            "welcome_channel": None,
            "leave_channel": None,
            "ticket_category": None,
            "staff_role": None,
            "log_channel": None
        }
        save_data()

    return data["settings"][guild_id]


# =========================================================
# EMBEDS
# =========================================================

def aura_embed(title, description="", color=0x8A2BE2):
    embed = discord.Embed(
        title=f"🛡️ {title}",
        description=description,
        color=color
    )

    embed.set_footer(text="AuraGuard • Powered by Aura")

    return embed


# =========================================================
# BOT READY
# =========================================================

@bot.event
async def on_ready():
    print("====================================")
    print(f"AuraGuard is online as {bot.user}")
    print(f"Bot ID: {bot.user.id}")
    print("====================================")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"Command sync error: {e}")

    if not giveaway_loop.is_running():
        giveaway_loop.start()


# =========================================================
# ERROR HANDLER
# =========================================================

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):

    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            embed=aura_embed(
                "Permission Denied",
                "You don't have permission to use this command.",
                0xFF0000
            ),
            ephemeral=True
        )
        return

    print(f"Command error: {error}")

    if interaction.response.is_done():
        await interaction.followup.send(
            "❌ Something went wrong.",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "❌ Something went wrong.",
            ephemeral=True
        )


# =========================================================
# BASIC COMMANDS
# =========================================================

@bot.tree.command(name="ping", description="Check if AuraGuard is online.")
async def ping(interaction: discord.Interaction):

    latency = round(bot.latency * 1000)

    await interaction.response.send_message(
        embed=aura_embed(
            "AuraGuard Online",
            f"⚡ Pong!\n\nLatency: **{latency}ms**"
        )
    )


@bot.tree.command(name="help", description="Show AuraGuard commands.")
async def help_command(interaction: discord.Interaction):

    embed = aura_embed(
        "AuraGuard Commands",
        """
**🛡️ Moderation**
`/kick`
`/ban`
`/timeout`
`/warn`
`/clear`

**⚙️ Setup**
`/setwelcome`
`/setleave`
`/settickets`
`/setstaffrole`
`/setlogchannel`

**🎫 Tickets**
`/ticketpanel`

**🎉 Giveaways**
`/giveaway`

**💾 Backups**
`/backup`
        """
    )

    await interaction.response.send_message(embed=embed)


# =========================================================
# MODERATION
# =========================================================

@bot.tree.command(name="kick", description="Kick a member.")
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
                f"👢 {member.mention} was kicked.\n\n"
                f"**Reason:** {reason}"
            )
        )

    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I don't have permission to kick that member.",
            ephemeral=True
        )


@bot.tree.command(name="ban", description="Ban a member.")
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
                f"🔨 {member.mention} was banned.\n\n"
                f"**Reason:** {reason}"
            )
        )

    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I don't have permission to ban that member.",
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
            "❌ Timeout must be between 1 minute and 28 days.",
            ephemeral=True
        )
        return

    until = discord.utils.utcnow() + timedelta(minutes=minutes)

    try:
        await member.timeout(until, reason=reason)

        await interaction.response.send_message(
            embed=aura_embed(
                "Member Timed Out",
                f"⏳ {member.mention} was timed out for "
                f"**{minutes} minutes**."
            )
        )

    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I don't have permission to timeout that member.",
            ephemeral=True
        )


@bot.tree.command(name="clear", description="Delete messages.")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(
    interaction: discord.Interaction,
    amount: int
):

    if amount < 1 or amount > 100:
        await interaction.response.send_message(
            "❌ Choose a number between 1 and 100.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    deleted = await interaction.channel.purge(limit=amount)

    await interaction.followup.send(
        f"🧹 Deleted **{len(deleted)}** messages.",
        ephemeral=True
    )


# =========================================================
# WARNINGS
# =========================================================

@bot.tree.command(name="warn", description="Warn a member.")
@app_commands.checks.has_permissions(moderate_members=True)
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
        "time": datetime.now(timezone.utc).isoformat()
    })

    save_data()

    count = len(data["warnings"][guild_id][user_id])

    await interaction.response.send_message(
        embed=aura_embed(
            "Warning Issued",
            f"⚠️ {member.mention} has been warned.\n\n"
            f"**Reason:** {reason}\n"
            f"**Total warnings:** {count}"
        )
    )


# =========================================================
# SERVER SETUP
# =========================================================

@bot.tree.command(name="setwelcome", description="Set the welcome channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setwelcome(
    interaction: discord.Interaction,
    channel: discord.TextChannel
):

    settings = guild_settings(interaction.guild.id)
    settings["welcome_channel"] = channel.id
    save_data()

    await interaction.response.send_message(
        f"👋 Welcome messages will now be sent in {channel.mention}."
    )


@bot.tree.command(name="setleave", description="Set the leave channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setleave(
    interaction: discord.Interaction,
    channel: discord.TextChannel
):

    settings = guild_settings(interaction.guild.id)
    settings["leave_channel"] = channel.id
    save_data()

    await interaction.response.send_message(
        f"🚪 Leave messages will now be sent in {channel.mention}."
    )


@bot.tree.command(name="setstaffrole", description="Set the staff role.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setstaffrole(
    interaction: discord.Interaction,
    role: discord.Role
):

    settings = guild_settings(interaction.guild.id)
    settings["staff_role"] = role.id
    save_data()

    await interaction.response.send_message(
        f"🛡️ Staff role set to {role.mention}."
    )


@bot.tree.command(name="setlogchannel", description="Set the moderation log channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setlogchannel(
    interaction: discord.Interaction,
    channel: discord.TextChannel
):

    settings = guild_settings(interaction.guild.id)
    settings["log_channel"] = channel.id
    save_data()

    await interaction.response.send_message(
        f"📋 Log channel set to {channel.mention}."
    )


# =========================================================
# WELCOME / LEAVE
# =========================================================

@bot.event
async def on_member_join(member):

    settings = guild_settings(member.guild.id)

    channel_id = settings.get("welcome_channel")

    if not channel_id:
        return

    channel = member.guild.get_channel(channel_id)

    if not channel:
        return

    await channel.send(
        embed=aura_embed(
            "Welcome!",
            f"👋 Welcome {member.mention} to **{member.guild.name}**!\n\n"
            f"Enjoy your stay! 🛡️"
        )
    )


@bot.event
async def on_member_remove(member):

    settings = guild_settings(member.guild.id)

    channel_id = settings.get("leave_channel")

    if not channel_id:
        return

    channel = member.guild.get_channel(channel_id)

    if not channel:
        return

    await channel.send(
        embed=aura_embed(
            "Member Left",
            f"🚪 **{member}** has left the server."
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

        settings = guild_settings(guild.id)

        category = None

        if settings.get("ticket_category"):
            category = guild.get_channel(
                settings["ticket_category"]
            )

        existing = discord.utils.get(
            guild.text_channels,
            name=f"ticket-{user.id}"
        )

        if existing:
            await interaction.response.send_message(
                f"🎫 You already have a ticket: {existing.mention}",
                ephemeral=True
            )
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),
            user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )
        }

        staff_role_id = settings.get("staff_role")

        if staff_role_id:
            staff_role = guild.get_role(staff_role_id)

            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )

        channel = await guild.create_text_channel(
            name=f"ticket-{user.id}",
            overwrites=overwrites,
            category=category,
            reason="AuraGuard ticket"
        )

        await channel.send(
            content=user.mention,
            embed=aura_embed(
                "Ticket Opened",
                "🎫 Thanks for opening a ticket!\n\n"
                "A staff member will help you shortly."
            ),
            view=CloseTicketView()
        )

        await interaction.response.send_message(
            f"🎫 Ticket created: {channel.mention}",
            ephemeral=True
        )


class CloseTicketView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Close Ticket",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="auraguard_close_ticket"
    )
    async def close_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_message(
            "🔒 This ticket will be deleted in 5 seconds."
        )

        await asyncio.sleep(5)

        try:
            await interaction.channel.delete(
                reason="AuraGuard ticket closed"
            )
        except:
            pass


@bot.tree.command(name="settickets", description="Set the ticket category.")
@app_commands.checks.has_permissions(manage_guild=True)
async def settickets(
    interaction: discord.Interaction,
    category: discord.CategoryChannel
):

    settings = guild_settings(interaction.guild.id)

    settings["ticket_category"] = category.id

    save_data()

    await interaction.response.send_message(
        f"🎫 Ticket category set to **{category.name}**."
    )


@bot.tree.command(name="ticketpanel", description="Create the ticket panel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def ticketpanel(interaction: discord.Interaction):

    await interaction.response.send_message(
        embed=aura_embed(
            "Support Tickets",
            "Need help? Click the button below to open a private ticket."
        ),
        view=TicketView()
    )


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

        gid = str(self.giveaway_id)

        if gid not in giveaway_entries:
            giveaway_entries[gid] = {}

        user_id = str(interaction.user.id)

        if user_id in giveaway_entries[gid]:
            await interaction.response.send_message(
                "❌ You're already entered!",
                ephemeral=True
            )
            return

        settings = data["giveaways"].get(gid, {})

        entries = 1

        bonus_roles = settings.get("bonus_roles", {})

        for role in interaction.user.roles:
            bonus = bonus_roles.get(str(role.id), 0)
            entries += bonus

        giveaway_entries[gid][user_id] = entries

        await interaction.response.send_message(
            f"🎉 You're entered with **{entries} entries**!",
            ephemeral=True
        )


@bot.tree.command(name="giveaway", description="Create a giveaway.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway(
    interaction: discord.Interaction,
    prize: str,
    minutes: int,
    winners: int = 1
):

    if minutes < 1:
        await interaction.response.send_message(
            "❌ Giveaway duration must be at least 1 minute.",
            ephemeral=True
        )
        return

    if winners < 1:
        await interaction.response.send_message(
            "❌ There must be at least 1 winner.",
            ephemeral=True
        )
        return

    giveaway_id = str(random.randint(100000, 999999))

    end_time = (
        datetime.now(timezone.utc)
        + timedelta(minutes=minutes)
    )

    data["giveaways"][giveaway_id] = {
        "guild": interaction.guild.id,
        "channel": interaction.channel.id,
        "prize": prize,
        "winners": winners,
        "end_time": end_time.isoformat()
    }

    giveaway_entries[giveaway_id] = {}

    save_data()

    embed = aura_embed(
        "🎉 GIVEAWAY",
        f"**Prize:** {prize}\n"
        f"**Winners:** {winners}\n"
        f"**Ends:** <t:{int(end_time.timestamp())}:R>\n\n"
        f"Click the button below to enter!"
    )

    await interaction.response.send_message(
        embed=embed,
        view=GiveawayView(giveaway_id)
    )


# =========================================================
# GIVEAWAY LOOP
# =========================================================

@tasks.loop(seconds=10)
async def giveaway_loop():

    now = datetime.now(timezone.utc)

    finished = []

    for giveaway_id, giveaway_data in list(
        data["giveaways"].items()
    ):

        end_time = datetime.fromisoformat(
            giveaway_data["end_time"]
        )

        if now < end_time:
            continue

        guild = bot.get_guild(giveaway_data["guild"])

        if not guild:
            finished.append(giveaway_id)
            continue

        channel = guild.get_channel(
            giveaway_data["channel"]
        )

        if not channel:
            finished.append(giveaway_id)
            continue

        entries = giveaway_entries.get(
            giveaway_id,
            {}
        )

        if not entries:

            await channel.send(
                embed=aura_embed(
                    "Giveaway Ended",
                    f"🎉 **{giveaway_data['prize']}**\n\n"
                    "Nobody entered the giveaway."
                )
            )

            finished.append(giveaway_id)
            continue

        weighted_users = []

        for user_id, entry_count in entries.items():

            weighted_users.extend(
                [user_id] * entry_count
            )

        winners = []

        for _ in range(
            min(
                giveaway_data["winners"],
                len(set(entries.keys()))
            )
        ):

            if not weighted_users:
                break

            chosen = random.choice(weighted_users)

            while chosen in winners:
                chosen = random.choice(weighted_users)

            winners.append(chosen)

        mentions = []

        for winner_id in winners:
            mentions.append(f"<@{winner_id}>")

        await channel.send(
            embed=aura_embed(
                "🎉 Giveaway Winner!",
                f"**Prize:** {giveaway_data['prize']}\n\n"
                f"🏆 Winner(s): {', '.join(mentions)}"
            )
        )

        finished.append(giveaway_id)

    for giveaway_id in finished:

        data["giveaways"].pop(
            giveaway_id,
            None
        )

        giveaway_entries.pop(
            giveaway_id,
            None
        )

    if finished:
        save_data()


# =========================================================
# BACKUP SYSTEM
# =========================================================

@bot.tree.command(name="backup-create", description="Create a server backup.")
@app_commands.checks.has_permissions(administrator=True)
async def backup_create(interaction: discord.Interaction):

    await interaction.response.defer(ephemeral=True)

    guild = interaction.guild

    backup = {
        "name": f"Backup {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "guild_name": guild.name,
        "roles": [],
        "categories": [],
        "channels": []
    }

    # -----------------------------
    # ROLES
    # -----------------------------

    for role in guild.roles:

        if role.is_default():
            continue

        backup["roles"].append({
            "name": role.name,
            "permissions": role.permissions.value,
            "color": role.color.value,
            "hoist": role.hoist,
            "mentionable": role.mentionable,
            "position": role.position
        })

    # -----------------------------
    # CATEGORIES
    # -----------------------------

    for category in guild.categories:

        backup["categories"].append({
            "name": category.name,
            "position": category.position
        })

        for channel in category.channels:

            if isinstance(channel, discord.TextChannel):

                backup["channels"].append({
                    "name": channel.name,
                    "type": "text",
                    "category": category.name,
                    "position": channel.position,
                    "topic": channel.topic,
                    "slowmode": channel.slowmode_delay
                })

            elif isinstance(channel, discord.VoiceChannel):

                backup["channels"].append({
                    "name": channel.name,
                    "type": "voice",
                    "category": category.name,
                    "position": channel.position
                })

    # -----------------------------
    # NO CATEGORY CHANNELS
    # -----------------------------

    for channel in guild.channels:

        if isinstance(channel, discord.TextChannel):

            if channel.category is None:

                backup["channels"].append({
                    "name": channel.name,
                    "type": "text",
                    "category": None,
                    "position": channel.position,
                    "topic": channel.topic,
                    "slowmode": channel.slowmode_delay
                })

    backup_id = str(
        random.randint(100000, 999999)
    )

    if str(guild.id) not in data["backups"]:
        data["backups"][str(guild.id)] = {}

    data["backups"][str(guild.id)][backup_id] = backup

    save_data()

    await interaction.followup.send(
        embed=aura_embed(
            "Backup Created",
            f"💾 Backup ID: **{backup_id}**\n\n"
            f"Saved **{len(backup['roles'])} roles**\n"
            f"Saved **{len(backup['channels'])} channels**"
        ),
        ephemeral=True
    )


# =========================================================
# LIST BACKUPS
# =========================================================

@bot.tree.command(name="backup-list", description="List server backups.")
@app_commands.checks.has_permissions(administrator=True)
async def backup_list(interaction: discord.Interaction):

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

    description = ""

    for backup_id, backup in backups.items():

        description += (
            f"**{backup_id}** — "
            f"{backup['name']}\n"
        )

    await interaction.response.send_message(
        embed=aura_embed(
            "Server Backups",
            description
        ),
        ephemeral=True
    )


# =========================================================
# BACKUP RESTORE
# =========================================================

@bot.tree.command(
    name="backup-restore",
    description="Restore a server backup."
)
@app_commands.checks.has_permissions(administrator=True)
async def backup_restore(
    interaction: discord.Interaction,
    backup_id: str
):

    await interaction.response.defer(ephemeral=True)

    guild_id = str(interaction.guild.id)

    backups = data["backups"].get(
        guild_id,
        {}
    )

    backup = backups.get(backup_id)

    if not backup:
        await interaction.followup.send(
            "❌ Backup not found.",
            ephemeral=True
        )
        return

    guild = interaction.guild

    # -----------------------------
    # CREATE ROLES
    # -----------------------------

    existing_roles = {
        role.name: role
        for role in guild.roles
    }

    for role_data in backup["roles"]:

        if role_data["name"] in existing_roles:
            continue

        try:

            await guild.create_role(
                name=role_data["name"],
                permissions=discord.Permissions(
                    role_data["permissions"]
                ),
                colour=discord.Colour(
                    role_data["color"]
                ),
                hoist=role_data["hoist"],
                mentionable=role_data["mentionable"],
                reason="AuraGuard backup restore"
            )

        except discord.Forbidden:
            pass

    # -----------------------------
    # CREATE CATEGORIES
    # -----------------------------

    existing_categories = {
        category.name: category
        for category in guild.categories
    }

    for category_data in backup["categories"]:

        if category_data["name"] in existing_categories:
            continue

        try:

            category = await guild.create_category(
                category_data["name"],
                reason="AuraGuard backup restore"
            )

            existing_categories[
                category_data["name"]
            ] = category

        except discord.Forbidden:
            pass

    # -----------------------------
    # CREATE CHANNELS
    # -----------------------------

    existing_channels = {
        channel.name
        for channel in guild.channels
    }

    for channel_data in backup["channels"]:

        if channel_data["name"] in existing_channels:
            continue

        category = None

        if channel_data["category"]:
            category = existing_categories.get(
                channel_data["category"]
            )

        try:

            if channel_data["type"] == "text":

                await guild.create_text_channel(
                    channel_data["name"],
                    category=category,
                    topic=channel_data.get("topic"),
                    slowmode_delay=channel_data.get(
                        "slowmode",
                        0
                    ),
                    reason="AuraGuard backup restore"
                )

            elif channel_data["type"] == "voice":

                await guild.create_voice_channel(
                    channel_data["name"],
                    category=category,
                    reason="AuraGuard backup restore"
                )

        except discord.Forbidden:
            pass

    await interaction.followup.send(
        embed=aura_embed(
            "Backup Restored",
            f"💾 Backup **{backup_id}** has been restored.\n\n"
            "Existing channels and roles were left alone."
        ),
        ephemeral=True
    )


# =========================================================
# RUN BOT
# =========================================================

bot.run(TOKEN)
