# =========================================================
#                    AURAGUARD V6
# =========================================================
# Features currently included:
# - Welcome & leave messages
# - Welcome cards
# - Invite tracking
# - Invite leaderboard
# - Set/add/remove/reset invite commands
# - Logging helpers
# =========================================================

import discord
from discord import app_commands
from discord.ext import commands

import os
import json
import random
import io
from datetime import datetime, timezone
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
    raise RuntimeError(
        "DISCORD_TOKEN is missing from Railway Variables."
    )


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


def get_member_invite_data(guild_id, member_id):
    invite_data = get_invite_data(guild_id)

    return invite_data.setdefault(
        str(member_id),
        {
            "total": 0,
            "regular": 0,
            "manual": 0
        }
    )


# ==================== HELPERS ====================

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


def is_staff(member):
    if member.guild_permissions.administrator:
        return True

    if member.guild_permissions.manage_guild:
        return True

    role_id = get_settings(member.guild.id).get(
        "staff_role"
    )

    role = (
        member.guild.get_role(role_id)
        if role_id
        else None
    )

    return bool(role and role in member.roles)


def apply_placeholders(text, member):
    return (
        text.replace("{user}", member.mention)
        .replace("{server}", member.guild.name)
        .replace(
            "{member_count}",
            str(member.guild.member_count)
        )
    )


def clean_message_content(content):
    return discord.utils.escape_markdown(
        content or "*No text content*"
    )[:3500]


def make_unique_id(collection):
    while True:
        giveaway_id = str(
            random.randint(100000, 999999)
        )

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

async def send_log(
    guild,
    title,
    description,
    color=AURA_PURPLE
):
    channel_id = get_settings(
        guild.id
    ).get("log_channel")

    channel = (
        guild.get_channel(channel_id)
        if channel_id
        else None
    )

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

        except Exception as e:
            print("Log error:", e)


async def send_message_log(
    guild,
    title,
    description,
    color=AURA_BLUE
):
    channel_id = get_settings(
        guild.id
    ).get("message_log_channel")

    channel = (
        guild.get_channel(channel_id)
        if channel_id
        else None
    )

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

        except Exception as e:
            print("Message log error:", e)


# ==================== WELCOME IMAGE ====================

def get_font(size, bold=False):
    paths = [
        (
            "/usr/share/fonts/truetype/dejavu/"
            "DejaVuSans-Bold.ttf"
            if bold
            else
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

    try:
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

    except Exception as e:
        print("Avatar image error:", e)

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

    except Exception as e:
        print("Welcome card error:", e)

        try:
            await channel.send(
                embed=embed
            )

        except Exception:
            pass


# ==================== COMMAND GROUPS ====================

welcome_group = app_commands.Group(
    name="welcome",
    description="Manage welcome messages."
)

leave_group = app_commands.Group(
    name="leave",
    description="Manage leave messages."
)

automod_group = app_commands.Group(
    name="automod",
    description="Manage AuraGuard AutoMod."
)


# ==================== INVITE COMMANDS ====================

@bot.tree.command(
    name="invites",
    description="Check your or another member's invite count."
)
@app_commands.describe(
    member="The member whose invites you want to check."
)
async def invites(
    interaction: discord.Interaction,
    member: discord.Member = None
):
    member = member or interaction.user

    user_data = get_member_invite_data(
        interaction.guild.id,
        member.id
    )

    total = user_data.get(
        "total",
        0
    )

    regular = user_data.get(
        "regular",
        0
    )

    manual = user_data.get(
        "manual",
        0
    )

    await interaction.response.send_message(
        embed=aura_embed(
            "Invite Information",
            f"👤 **Member:** {member.mention}\n"
            f"📨 **Total Invites:** **{total}**\n"
            f"✅ **Regular Invites:** **{regular}**\n"
            f"➕ **Manual Invites:** **{manual}**",
            AURA_PURPLE,
            "📨"
        )
    )


@bot.tree.command(
    name="inviteleaderboard",
    description="Show the server invite leaderboard."
)
async def invite_leaderboard(
    interaction: discord.Interaction
):
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

    for position, (
        user_id,
        user_data
    ) in enumerate(
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


# ==================== SET INVITES ====================

@bot.tree.command(
    name="setinvites",
    description="Set a member's invite amount."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
@app_commands.describe(
    member="The member to update.",
    amount="The new invite amount."
)
async def setinvites(
    interaction: discord.Interaction,
    member: discord.Member,
    amount: int
):
    if amount < 0:
        await interaction.response.send_message(
            "❌ Invite amount cannot be negative.",
            ephemeral=True
        )

        return

    user_data = get_member_invite_data(
        interaction.guild.id,
        member.id
    )

    user_data["total"] = amount
    user_data["manual"] = amount
    user_data["regular"] = 0

    save_data()

    await interaction.response.send_message(
        embed=aura_embed(
            "Invites Updated",
            f"📨 {member.mention} now has "
            f"**{amount} invites**.",
            AURA_GREEN,
            "📨"
        )
    )

    await send_log(
        interaction.guild,
        "Invites Set",
        f"Moderator: {interaction.user.mention}\n"
        f"Member: {member.mention}\n"
        f"New Total: **{amount}**",
        AURA_GREEN
    )


# ==================== ADD INVITES ====================

@bot.tree.command(
    name="addinvites",
    description="Add invites to a member."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
@app_commands.describe(
    member="The member to add invites to.",
    amount="The number of invites to add."
)
async def addinvites(
    interaction: discord.Interaction,
    member: discord.Member,
    amount: int
):
    if amount < 1:
        await interaction.response.send_message(
            "❌ Amount must be at least 1.",
            ephemeral=True
        )

        return

    user_data = get_member_invite_data(
        interaction.guild.id,
        member.id
    )

    user_data["total"] += amount
    user_data["manual"] += amount

    save_data()

    await interaction.response.send_message(
        embed=aura_embed(
            "Invites Added",
            f"➕ Added **{amount} invites** to "
            f"{member.mention}.\n\n"
            f"📨 They now have "
            f"**{user_data['total']} invites**.",
            AURA_GREEN,
            "➕"
        )
    )

    await send_log(
        interaction.guild,
        "Invites Added",
        f"Moderator: {interaction.user.mention}\n"
        f"Member: {member.mention}\n"
        f"Added: **{amount}**\n"
        f"New Total: **{user_data['total']}**",
        AURA_GREEN
    )


# ==================== REMOVE INVITES ====================

@bot.tree.command(
    name="removeinvites",
    description="Remove invites from a member."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
@app_commands.describe(
    member="The member to remove invites from.",
    amount="The number of invites to remove."
)
async def removeinvites(
    interaction: discord.Interaction,
    member: discord.Member,
    amount: int
):
    if amount < 1:
        await interaction.response.send_message(
            "❌ Amount must be at least 1.",
            ephemeral=True
        )

        return

    user_data = get_member_invite_data(
        interaction.guild.id,
        member.id
    )

    old_total = user_data["total"]

    user_data["total"] = max(
        0,
        user_data["total"] - amount
    )

    removed = old_total - user_data["total"]

    manual_removed = min(
        user_data["manual"],
        removed
    )

    user_data["manual"] -= manual_removed

    remaining = removed - manual_removed

    if remaining > 0:
        user_data["regular"] = max(
            0,
            user_data["regular"] - remaining
        )

    save_data()

    await interaction.response.send_message(
        embed=aura_embed(
            "Invites Removed",
            f"➖ Removed **{removed} invites** from "
            f"{member.mention}.\n\n"
            f"📨 They now have "
            f"**{user_data['total']} invites**.",
            AURA_RED,
            "➖"
        )
    )


# ==================== RESET INVITES ====================

@bot.tree.command(
    name="resetinvites",
    description="Reset a member's invites."
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
@app_commands.describe(
    member="The member whose invites should be reset."
)
async def resetinvites(
    interaction: discord.Interaction,
    member: discord.Member
):
    invite_data = get_invite_data(
        interaction.guild.id
    )

    invite_data[str(member.id)] = {
        "total": 0,
        "regular": 0,
        "manual": 0
    }

    save_data()

    await interaction.response.send_message(
        embed=aura_embed(
            "Invites Reset",
            f"🔄 {member.mention}'s invites have "
            f"been reset to **0**.",
            AURA_YELLOW,
            "🔄"
        )
    )


@bot.tree.command(
    name="resetallinvites",
    description="Reset all tracked server invites."
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def resetallinvites(
    interaction: discord.Interaction
):
    data["invites"][
        str(interaction.guild.id)
    ] = {}

    save_data()

    await interaction.response.send_message(
        embed=aura_embed(
            "All Invites Reset",
            "🔄 All tracked invite data for this "
            "server has been reset.",
            AURA_RED,
            "🔄"
        ),
        ephemeral=True
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


# ==================== MEMBER JOIN / INVITE TRACKING ====================

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

    if inviter and inviter.id != member.id:
        inviter_data = get_member_invite_data(
            guild.id,
            inviter.id
        )

        inviter_data["total"] += 1
        inviter_data["regular"] += 1

        save_data()

        await send_log(
            guild,
            "Member Invited",
            f"👤 **{member.mention}** was invited by "
            f"**{inviter.mention}**!\n\n"
            f"📨 **{inviter.mention} now has "
            f"{inviter_data['total']} invites.**",
            AURA_GREEN
        )

    else:
        await send_log(
            guild,
            "Member Joined",
            f"👤 Member: {member.mention}\n"
            f"📨 Inviter: **Unknown**",
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


# ==================== REGISTER GROUPS ====================

for group in [
    welcome_group,
    leave_group,
    automod_group
]:
    try:
        bot.tree.add_command(group)

    except app_commands.CommandAlreadyRegistered:
        pass


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
