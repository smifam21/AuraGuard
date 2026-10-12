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
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
DATA_FILE = "auraguard_data.json"

AURA_PURPLE = 0x8A2BE2
AURA_GREEN = 0x2ECC71
AURA_RED = 0xE74C3C
AURA_YELLOW = 0xF1C40F
AURA_BLUE = 0x3498DB
FOOTER = "AuraGuard • Powered by Aura"

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from your system environment variables.")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
intents.invites = True

async def get_prefix(bot, message):
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
    "member_invites": {}
}

def load_data():
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
                    "ticket_claims", "invites", "member_invites", "warnings"):
            if not isinstance(loaded.get(key), dict):
                loaded[key] = {}
        return loaded
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print("Data load error:", repr(error))
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

async def require_text_channel(interaction, channel):
    resolved = await resolve_channel(interaction.guild, channel)
    if resolved is None:
        await interaction.response.send_message("❌ Please select a normal text channel.", ephemeral=True)
        return None
    return resolved

async def send_log(guild, title, description, color=AURA_PURPLE):
    return

def get_font(size, bold=False):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
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

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="auraguard_open_ticket")
    async def open_ticket(self, interaction, button):
        guild = interaction.guild
        user = interaction.user
        settings = get_settings(guild.id)
        for channel in guild.text_channels:
            if channel.topic == f"AURAGUARD_TICKET_OWNER={user.id}":
                await interaction.response.send_message(f"🎫 You already have a ticket: {channel.mention}", ephemeral=True)
                return
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        }
        role_id = normalize_channel_id(settings.get("staff_role"))
        role = guild.get_role(role_id) if role_id else None
        if role:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        category = await get_saved_category(guild, settings.get("ticket_category"))
        safe_name = "".join(c for c in user.name.lower() if c.isalnum() or c == "-")[:80]
        channel = await guild.create_text_channel(f"ticket-{safe_name}", category=category, overwrites=overwrites, topic=f"AURAGUARD_TICKET_OWNER={user.id}")
        await channel.send(content=user.mention, embed=aura_embed("Ticket Opened", "A staff member will help you soon.\n\nUse the buttons below.", AURA_PURPLE, "🎫"), view=TicketControls())
        await interaction.response.send_message(f"🎫 Your ticket: {channel.mention}", ephemeral=True)

class TicketControls(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success, emoji="🙋", custom_id="auraguard_claim_ticket")
    async def claim_ticket(self, interaction, button):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Only staff can claim tickets.", ephemeral=True)
            return
        channel_id = str(interaction.channel.id)
        current = data["ticket_claims"].get(channel_id)
        if current and current != interaction.user.id:
            await interaction.response.send_message(f"❌ Already claimed by <@{current}>.", ephemeral=True)
            return
        data["ticket_claims"][channel_id] = interaction.user.id
        save_data()
        await interaction.response.send_message(f"🙋 Ticket claimed by {interaction.user.mention}.")
    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="auraguard_close_ticket")
    async def close_ticket(self, interaction, button):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Only staff can close tickets.", ephemeral=True)
            return
        await interaction.response.send_message("🔒 Closing ticket...")
        await asyncio.sleep(1)
        data["ticket_claims"].pop(str(interaction.channel.id), None)
        save_data()
        await interaction.channel.delete()

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
        winner = random.choices(list(pool.keys()), weights=list(pool.values()), k=1)[0]
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
        f"╭─ 🎁 **Prize:** {giveaway['prize']}\n"
        f"├─ 🏆 **Winners:** {giveaway['winners']}\n"
        f"├─ 👥 **Participants:** {len(entries)}
"
        f"├─ 🎟️ **Total Entries:** {sum(int(v) for v in entries.values())}\n"
        f"├─ 🔐 **Required Role:** {giveaway_required_role_text(giveaway)}\n"
        f"├─ 👤 **Hosted by:** <@{giveaway['created_by']}>\n"
        f"├─ ⏰ **Ends:** <t:{int(end.timestamp())}:R>\n"
        f"╰─ 🆔 **ID:** `{giveaway_id}`\n\n"
        "🎉 **Click Enter Giveaway to participate!**",
        AURA_PURPLE,
        "🎉"
    )

class GiveawayView(discord.ui.View):
    def __init__(self, giveaway_id):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        enter_button = discord.ui.Button(label="Enter Giveaway", emoji="🎉", style=discord.ButtonStyle.success, custom_id=f"auraguard_giveaway_enter_{giveaway_id}")
        enter_button.callback = self.enter
        self.add_item(enter_button)
        entries_button = discord.ui.Button(label="My Entries", emoji="🎟️", style=discord.ButtonStyle.primary, custom_id=f"auraguard_giveaway_entries_{giveaway_id}")
        entries_button.callback = self.my_entries
        self.add_item(entries_button)

    async def enter(self, interaction):
        giveaway = data["giveaways"].get(self.giveaway_id)
        if not interaction.guild or not giveaway or str(giveaway.get("guild")) != str(interaction.guild.id):
            await interaction.response.send_message("❌ This giveaway is no longer active in this server.", ephemeral=True)
            return
        try:
            end_time = datetime.fromisoformat(giveaway["end_time"])
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)
        except (KeyError, TypeError, ValueError):
            await interaction.response.send_message("❌ This giveaway has invalid saved timing data.", ephemeral=True)
            return
        if datetime.now(timezone.utc) >= end_time:
            await interaction.response.send_message("⏰ This giveaway has ended.", ephemeral=True)
            return
        if str(interaction.user.id) in get_giveaway_blacklist(interaction.guild.id):
            await interaction.response.send_message("🚫 You are blacklisted from AuraGuard giveaways.", ephemeral=True)
            return
        required_role_id = giveaway.get("required_role")
        if required_role_id:
            try:
                role = interaction.guild.get_role(int(required_role_id))
            except (TypeError, ValueError):
                role = None
            if role is None:
                await interaction.response.send_message("❌ The required giveaway role no longer exists.", ephemeral=True)
                return
            if role not in interaction.user.roles:
                await interaction.response.send_message(f"🔐 You need the {role.mention} role to enter.", ephemeral=True)
                return
        entries = get_giveaway_entries(self.giveaway_id)
        user_id = str(interaction.user.id)
        if user_id in entries:
            await interaction.response.send_message(f"❌ You're already entered with **{entries[user_id]} entries**.", ephemeral=True)
            return
        amount = 1 + get_bonus_entries(interaction.user)
        entries[user_id] = amount
        save_data()
        await interaction.response.send_message(f"🎉 You're entered with **{amount} entries**!", ephemeral=True)

    async def my_entries(self, interaction):
        amount = get_giveaway_entries(self.giveaway_id).get(str(interaction.user.id), 0)
        await interaction.response.send_message(f"🎟️ You have **{amount} entries**.", ephemeral=True)

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
            await channel.send(embed=aura_embed("Giveaway Winner!", f"🎁 **Prize:** {history['prize']}\n\n🏆 **Congratulations:** {winner_text}", AURA_GREEN, "🏆"))
        else:
            await channel.send(embed=aura_embed("Giveaway Ended", f"🎁 **Prize:** {history['prize']}\n\nNobody entered.", AURA_YELLOW, "🎉"))

welcome_group = app_commands.Group(name="welcome", description="Manage welcome messages.")
leave_group = app_commands.Group(name="leave", description="Manage leave messages.")
tickets_group = app_commands.Group(name="tickets", description="Manage tickets.")
giveaway_group = app_commands.Group(name="giveaway", description="Advanced AuraGuard giveaways.")
automod_group = app_commands.Group(name="automod", description="Manage AutoMod.")

@giveaway_group.command(name="start", description="Start an advanced giveaway.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_start(interaction: discord.Interaction, prize: str, minutes: int, winners: int = 1, required_role: discord.Role = None):
    if minutes < 1 or winners < 1:
        await interaction.response.send_message("❌ Minutes and winners must be at least 1.", ephemeral=True)
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
    await interaction.response.send_message(embed=giveaway_embed(giveaway_id, data["giveaways"][giveaway_id]), view=GiveawayView(giveaway_id))

@giveaway_group.command(name="list", description="Show active giveaways.")
async def giveaway_list(interaction: discord.Interaction):
    active = [(gid, g) for gid, g in data["giveaways"].items() if g["guild"] == interaction.guild.id]
    if not active:
        description = "No active giveaways."
    else:
        description = "\n\n".join([f"🎁 `{gid}` — **{g['prize']}**\n└ Ends <t:{int(datetime.fromisoformat(g['end_time']).timestamp())}:R>" for gid, g in active[:15]])
    await interaction.response.send_message(embed=aura_embed("Active Giveaways", description, AURA_PURPLE, "📋"), ephemeral=True)

@bot.tree.command(name="ping", description="Check AuraGuard latency.")
async def ping(interaction):
    await interaction.response.send_message(embed=aura_embed("AuraGuard Online", f"⚡ Pong!\nLatency: **{round(bot.latency * 1000)}ms**", AURA_PURPLE, "⚡"), ephemeral=True)

@bot.event
async def on_ready():
    print("=" * 45)
    print(f"AuraGuard V10 online as {bot.user}")
    print("=" * 45)
    await bot.change_presence(status=discord.Status.online, activity=discord.Activity(type=discord.ActivityType.watching, name="over your server 🛡️"))
    if not getattr(bot, "_auraguard_views_loaded", False):
        bot.add_view(TicketView())
        bot.add_view(TicketControls())
        for giveaway_id in list(data["giveaways"]):
            bot.add_view(GiveawayView(giveaway_id))
        bot._auraguard_views_loaded = True
    if not giveaway_loop.is_running():
        giveaway_loop.start()
    try:
        await bot.tree.sync()
    except Exception as e:
        print("Sync error:", e)

@tasks.loop(seconds=15)
async def giveaway_loop():
    now = datetime.now(timezone.utc)
    for giveaway_id, giveaway in list(data["giveaways"].items()):
        try:
            end = datetime.fromisoformat(giveaway["end_time"]).replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if now >= end:
            guild = bot.get_guild(giveaway["guild"])
            channel = await get_saved_text_channel(guild, giveaway["channel"]) if guild else None
            try:
                await finish_giveaway(guild, channel, giveaway_id)
            except Exception as e:
                print("Giveaway error:", e)

for group in [welcome_group, leave_group, tickets_group, giveaway_group, automod_group]:
    bot.tree.add_command(group)

bot.run(TOKEN)
