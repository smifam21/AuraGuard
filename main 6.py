# AuraGuard V8 — Updated & Fixed
# Requires: discord.py, Pillow

import asyncio
import io
import json
import os
import random
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks
from PIL import Image, ImageDraw, ImageFont

# Secure variable check modified for Wispbyte environment execution
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    try:
        TOKEN = os.environ.get("DISCORD_TOKEN")
    except Exception:
        pass

DATA_FILE = "auraguard_data.json"

AURA_PURPLE = 0x8A2BE2
AURA_GREEN = 0x2ECC71
AURA_RED = 0xE74C3C
AURA_YELLOW = 0xF1C40F
AURA_BLUE = 0x3498DB
FOOTER = "AuraGuard • Powered by Aura"

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN is missing. Add it in your Wispbyte server environment variables, "
        "then restart AuraGuard."
    )

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

DEFAULT_INVITE_STATS = {
    "total": 0, "regular": 0, "bonus": 0, "fake": 0, "left": 0
}

invite_cache = {}
data_lock = asyncio.Lock()

def load_data():
    if not os.path.exists(DATA_FILE):
        return deepcopy(DEFAULT_DATA)
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            raise ValueError("Data file is not a JSON object")
        for key, value in DEFAULT_DATA.items():
            loaded.setdefault(key, deepcopy(value))
        return loaded
    except Exception as e:
        print("Data load error:", repr(e))
        return deepcopy(DEFAULT_DATA)

data = load_data()

def save_data():
    try:
        temp = DATA_FILE + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp, DATA_FILE)
    except Exception as e:
        print("Data save error:", repr(e))

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
        "invite_channel": None,
        "giveaway_bonus_roles": {}
    }
    if gid not in data["settings"]:
        data["settings"][gid] = deepcopy(defaults)
        save_data()
    else:
        for key, value in defaults.items():
            data["settings"][gid].setdefault(key, deepcopy(value))
    return data["settings"][gid]

def get_automod(guild_id):
    gid = str(guild_id)
    data["automod"].setdefault(gid, {"enabled": False, "blocked_words": []})
    return data["automod"][gid]

def get_invite_data(guild_id):
    return data["invites"].setdefault(str(guild_id), {})

def get_member_invites(guild_id):
    return data["member_invites"].setdefault(str(guild_id), {})

def get_invite_stats(guild_id, user_id):
    return get_invite_data(guild_id).setdefault(str(user_id), deepcopy(DEFAULT_INVITE_STATS))

def aura_embed(title, description="", color=AURA_PURPLE, emoji="🛡️"):
    embed = discord.Embed(
        title=f"{emoji} {title}",
        description=description[:4096],
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text=FOOTER)
    return embed

def is_staff(member):
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    role_id = get_settings(member.guild.id).get("staff_role")
    role = member.guild.get_role(role_id) if role_id else None
    return bool(role and role in member.roles)

def apply_placeholders(text, member):
    return (text.replace("{user}", member.mention)
            .replace("{server}", member.guild.name)
            .replace("{member_count}", str(member.guild.member_count)))

def clean_message_content(content):
    return discord.utils.escape_markdown(content or "*No text content*")[:3500]

def make_unique_id(collection):
    while True:
        value = str(random.randint(100000, 999999))
        if value not in collection:
            return value

def weighted_winners(entries, amount):
    pool = {uid: max(0, int(weight)) for uid, weight in entries.items()}
    pool = {uid: weight for uid, weight in pool.items() if weight > 0}
    winners = []
    while pool and len(winners) < amount:
        winner = random.choices(list(pool), weights=list(pool.values()), k=1)[0]
        winners.append(winner)
        pool.pop(winner)
    return winners

async def send_log(guild, title, description, color=AURA_PURPLE):
    channel_id = get_settings(guild.id).get("log_channel")
    channel = guild.get_channel(channel_id) if channel_id else None
    if isinstance(channel, discord.TextChannel):
        try:
            await channel.send(embed=aura_embed(title, description, color, "📋"))
        except discord.HTTPException:
            pass

async def send_message_log(guild, title, description, color=AURA_BLUE):
    channel_id = get_settings(guild.id).get("message_log_channel")
    channel = guild.get_channel(channel_id) if channel_id else None
    if isinstance(channel, discord.TextChannel):
        try:
            await channel.send(embed=aura_embed(title, description[:4000], color, "💬"))
        except discord.HTTPException:
            pass

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

    avatar = Image.open(io.BytesIO(await member.display_avatar.read())).convert("RGB").resize((190, 190))
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
    if settings.get("welcome_image_enabled", True):
        try:
            welcome_file = await create_welcome_card(member)
            embed.set_image(url="attachment://auraguard-welcome.png")
            await channel.send(embed=embed, file=welcome_file)
            return
        except Exception as e:
            print("Welcome card error:", repr(e))
    await channel.send(embed=embed)

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="auraguard_open_ticket")
    async def open_ticket(self, interaction, button):
        guild = interaction.guild
        if not guild:
            return
        user = interaction.user
        for channel in guild.text_channels:
            if channel.topic == f"AURAGUARD_TICKET_OWNER={user.id}":
                await interaction.response.send_message(f"🎫 You already have a ticket: {channel.mention}", ephemeral=True)
                return

        settings = get_settings(guild.id)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        }
        role_id = settings.get("staff_role")
        role = guild.get_role(role_id) if role_id else None
        if role:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        category_id = settings.get("ticket_category")
        category = guild.get_channel(category_id) if category_id else None
        channel = await guild.create_text_channel(
            f"ticket-{user.name}".lower()[:90],
            category=category if isinstance(category, discord.CategoryChannel) else None,
            overwrites=overwrites,
            topic=f"AURAGUARD_TICKET_OWNER={user.id}"
        )
        await channel.send(
            content=user.mention,
            embed=aura_embed("Ticket Opened", "A staff member will help you soon.\n\nUse the buttons below.", AURA_PURPLE, "🎫"),
            view=TicketControls()
        )
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
        if current and int(current) != interaction.user.id:
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
        try:
            await interaction.channel.delete(reason=f"Closed by {interaction.user}")
        except discord.HTTPException:
            pass

def giveaway_embed(giveaway_id, giveaway):
    entries = data["giveaway_entries"].get(giveaway_id, {})
    end = datetime.fromisoformat(giveaway["end_time"])
    return aura_embed(
        "GIVEAWAY",
        f"🎁 **Prize:** {giveaway['prize']}\n"
        f"🏆 **Winners:** {giveaway['winners']}\n"
        f"🆔 **Giveaway ID:** `{giveaway_id}`\n"
        f"👥 **Participants:** {len(entries)}
"
        f"🎟️ **Total Entries:** {sum(int(v) for v in entries.values())}\n"
        f"👤 **Hosted by:** <@{giveaway['created_by']}>\n"
        f"⏰ **Ends:** <t:{int(end.timestamp())}:R>\n\n"
        f"**Click Participate to enter!**",
        AURA_PURPLE, "🎉"
    )

class GiveawayView(discord.ui.View):
    def __init__(self, giveaway_id):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id

        enter = discord.ui.Button(label="Participate", emoji="🎉", style=discord.ButtonStyle.success,
                                  custom_id=f"auraguard_giveaway_enter_{giveaway_id}")
        enter.callback = self.enter
        self.add_item(enter)

        mine = discord.ui.Button(label="My Entries", emoji="🎟️", style=discord.ButtonStyle.primary,
                                 custom_id=f"auraguard_giveaway_entries_{giveaway_id}")
        mine.callback = self.my_entries
        self.add_item(mine)

    async def enter(self, interaction):
        giveaway = data["giveaways"].get(self.giveaway_id)
        if not giveaway:
            await interaction.response.send_message("❌ This giveaway is no longer active.", ephemeral=True)
            return

        entries = data["giveaway_entries"].setdefault(self.giveaway_id, {})
        user_id = str(interaction.user.id)
        if user_id in entries:
            await interaction.response.send_message(f"❌ You're already entered with **{entries[user_id]} entries**.", ephemeral=True)
            return

        entries[user_id] = 1
        save_data()
        await interaction.response.send_message("🎉 You're entered with **1 entry!**", ephemeral=True)

    async def my_entries(self, interaction):
        amount = data["giveaway_entries"].get(self.giveaway_id, {}).get(str(interaction.user.id), 0)
        await interaction.response.send_message(
            f"🎟️ You have **{amount} {'entry' if amount == 1 else 'entries'}**.", ephemeral=True
        )

async def finish_giveaway(guild, channel, giveaway_id):
    giveaway = data["giveaways"].get(giveaway_id)
    if not giveaway:
        return

    entries = data["giveaway_entries"].get(giveaway_id, {})
    winners = weighted_winners(entries, int(giveaway["winners"]))
    history = dict(giveaway)
    history["entries"] = dict(entries)
    history["winners_list"] = winners
    history["ended_at"] = datetime.now(timezone.utc).isoformat()

    data["giveaway_history"][giveaway_id] = history
    data["giveaways"].pop(giveaway_id, None)
    data["giveaway_entries"].pop(giveaway_id, None)
    save_data()

    if not isinstance(channel, discord.TextChannel):
        return

    if winners:
        winner_text = " ".join(f"<@{winner}>" for winner in winners)
        embed = aura_embed("Giveaway Winner!", f"🎁 **Prize:** {history['prize']}\n\n🏆 {winner_text}", AURA_GREEN, "🏆")
    else:
        embed = aura_embed("Giveaway Ended", f"🎁 **{history['prize']}**\n\nNobody entered.", AURA_YELLOW, "🎉")
    await channel.send(embed=embed)

welcome_group = app_commands.Group(name="welcome", description="Manage welcome messages.")
leave_group = app_commands.Group(name="leave", description="Manage leave messages.")
tickets_group = app_commands.Group(name="tickets", description="Manage tickets.")
giveaway_group = app_commands.Group(name="giveaway", description="Manage giveaways.")
automod_group = app_commands.Group(name="automod", description="Manage AutoMod.")

@welcome_group.command(name="setup", description="Set the welcome channel and message.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_setup(interaction: discord.Interaction, welcome_channel: discord.TextChannel,
                        message: str = "Welcome {user} to {server}! 🛡️"):
    settings = get_settings(interaction.guild.id)
    settings["welcome_channel"] = welcome_channel.id
    settings["welcome_message"] = message
    save_data()
    await interaction.response.send_message(
        f"✅ Welcome channel set to {welcome_channel.mention}.\n💬 Welcome message saved.", ephemeral=True)

@welcome_group.command(name="enable", description="Enable welcome messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_enable(interaction):
    settings = get_settings(interaction.guild.id)
    if not settings["welcome_channel"]:
        await interaction.response.send_message("❌ Run `/welcome setup` first.", ephemeral=True)
        return
    settings["welcome_enabled"] = True
    save_data()
    await interaction.response.send_message("🟢 Welcome messages enabled.", ephemeral=True)

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
    await interaction.response.send_message(f"🖼️ Welcome image {'enabled' if enabled else 'disabled'}.", ephemeral=True)

@welcome_group.command(name="test", description="Test the welcome message.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_test(interaction):
    channel_id = get_settings(interaction.guild.id).get("welcome_channel")
    channel = interaction.guild.get_channel(channel_id) if channel_id else None
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("❌ Run `/welcome setup` first.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    await send_welcome(interaction.user, channel)
    await interaction.followup.send("✅ Welcome test sent.", ephemeral=True)

@leave_group.command(name="setup", description="Set leave channel and message.")
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_setup(interaction, leave_channel: discord.TextChannel,
                      message: str = "{user} has left {server}. 👋"):
    settings = get_settings(interaction.guild.id)
    settings["leave_channel"] = leave_channel.id
    settings["leave_message"] = message
    save_data()
    await interaction.response.send_message(f"✅ Leave channel set to {leave_channel.mention}.", ephemeral=True)

@leave_group.command(name="enable", description="Enable leave messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_enable(interaction):
    settings = get_settings(interaction.guild.id)
    if not settings["leave_channel"]:
        await interaction.response.send_message("❌ Run `/leave setup` first.", ephemeral=True)
        return
    settings["leave_enabled"] = True
    save_data()
    await interaction.response.send_message("🟢 Leave messages enabled.", ephemeral=True)

@leave_group.command(name="disable", description="Disable leave messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_disable(interaction):
    get_settings(interaction.guild.id)["leave_enabled"] = False
    save_data()
    await interaction.response.send_message("🔴 Leave messages disabled.", ephemeral=True)

@tickets_group.command(name="setup", description="Set ticket category.")
@app_commands.checks.has_permissions(manage_guild=True)
async def tickets_setup(interaction, category: discord.CategoryChannel):
    get_settings(interaction.guild.id)["ticket_category"] = category.id
    save_data()
    await interaction.response.send_message(f"🎫 Ticket category set to **{category.name}**.", ephemeral=True)

@tickets_group.command(name="panel", description="Send the ticket panel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def tickets_panel(interaction):
    await interaction.response.send_message(
        embed=aura_embed("AuraGuard Support", "Need help?\n\nClick below to open a ticket.", AURA_PURPLE, "🎫"),
        view=TicketView()
    )

@giveaway_group.command(name="start", description="Start a giveaway.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_start(interaction, prize: str, minutes: int, winners: int = 1):
    if minutes < 1 or winners < 1:
        await interaction.response.send_message("❌ Minutes and winners must be at least 1.", ephemeral=True)
        return

    giveaway_id = make_unique_id(data["giveaways"])
    end = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    data["giveaways"][giveaway_id] = {
        "guild": interaction.guild.id, "channel": interaction.channel.id, "prize": prize,
        "winners": winners, "end_time": end.isoformat(), "created_by": interaction.user.id
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
        f"🎟️ You have **{amount} {'entry' if amount == 1 else 'entries'}**.", ephemeral=True)

@giveaway_group.command(name="addentries", description="Give a member extra entries.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_addentries(interaction, giveaway_id: str, member: discord.Member, amount: int):
    giveaway = data["giveaways"].get(giveaway_id)
    if amount < 1 or not giveaway or giveaway["guild"] != interaction.guild.id:
        await interaction.response.send_message("❌ Invalid amount or giveaway.", ephemeral=True)
        return
    entries = data["giveaway_entries"].setdefault(giveaway_id, {})
    uid = str(member.id)
    entries[uid] = int(entries.get(uid, 0)) + amount
    save_data()
    await interaction.response.send_message(f"➕ {member.mention} now has **{entries[uid]} entries**.", ephemeral=True)

@giveaway_group.command(name="end", description="End a giveaway early.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_end(interaction, giveaway_id: str):
    giveaway = data["giveaways"].get(giveaway_id)
    if not giveaway or giveaway["guild"] != interaction.guild.id:
        await interaction.response.send_message("❌ Giveaway not found.", ephemeral=True)
        return
    await interaction.response.defer()
    channel = interaction.guild.get_channel(giveaway["channel"])
    await finish_giveaway(interaction.guild, channel, giveaway_id)
    await interaction.followup.send("Base: Giveaway ended.")

@bot.tree.command(name="setinvitechannel", description="Set the channel for invite notifications.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setinvitechannel(interaction, invite_channel: discord.TextChannel):
    get_settings(interaction.guild.id)["invite_channel"] = invite_channel.id
    save_data()
    await interaction.response.send_message(f"📨 Invite channel set to {invite_channel.mention}.", ephemeral=True)

@bot.tree.command(name="invites", description="Check invite information.")
async def invites(interaction, member: discord.Member | None = None):
    member = member or interaction.user
    stats = get_invite_data(interaction.guild.id).get(str(member.id), deepcopy(DEFAULT_INVITE_STATS))
    await interaction.response.send_message(embed=aura_embed(
        "Invite Information",
        f"👤 **Member:** {member.mention}\n"
        f"📨 **Total Invites:** **{stats.get('total', 0)}**\n"
        f"✅ **Regular:** **{stats.get('regular', 0)}**\n"
        f"➕ **Bonus:** **{stats.get('bonus', 0)}**\n"
        f"👋 **Left:** **{stats.get('left', 0)}**",
        AURA_PURPLE, "📨"))

@bot.tree.command(name="inviteleaderboard", description="Show the invite leaderboard.")
async def inviteleaderboard(interaction):
    invite_data = get_invite_data(interaction.guild.id)
    ranked = sorted(invite_data.items(), key=lambda item: item[1].get("total", 0), reverse=True)
    if not ranked:
        await interaction.response.send_message(embed=aura_embed(
            "Invite Leaderboard", "No invite data has been recorded yet.", AURA_PURPLE, "🏆"))
        return
    lines = [f"**{i}.** <@{uid}> — **{stats.get('total', 0)} invites**"
             for i, (uid, stats) in enumerate(ranked[:10], 1)]
    await interaction.response.send_message(embed=aura_embed(
        "Invite Leaderboard", "\n".join(lines), AURA_PURPLE, "🏆"))

@bot.tree.command(name="setinvite", description="Set a member's invite amount.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setinvite(interaction, member: discord.Member, amount: int):
    if amount < 0:
        await interaction.response.send_message("❌ Invite amount cannot be negative.", ephemeral=True)
        return
    stats = get_invite_stats(interaction.guild.id, member.id)
    old = int(stats.get("total", 0))
    stats["total"] = amount
    stats["bonus"] = max(0, amount - stats.get("regular", 0))
    save_data()
    await interaction.response.send_message(
        f"📨 Updated {member.mention}: **{old} → {amount} invites**.", ephemeral=True)

@bot.tree.command(name="addinvites", description="Add invites to a member.")
@app_commands.checks.has_permissions(manage_guild=True)
async def addinvites(interaction, member: discord.Member, amount: int):
    if amount < 1:
        await interaction.response.send_message("❌ Amount must be at least 1.", ephemeral=True)
        return
    stats = get_invite_stats(interaction.guild.id, member.id)
    stats["total"] += amount
    stats["bonus"] += amount
    save_data()
    await interaction.response.send_message(
        f"➕ Added **{amount} invites** to {member.mention}. They now have **{stats['total']} invites**.")

@bot.tree.command(name="removeinvites", description="Remove invites from a member.")
@app_commands.checks.has_permissions(manage_guild=True)
async def removeinvites(interaction, member: discord.Member, amount: int):
    if amount < 1:
        await interaction.response.send_message("❌ Amount must be at least 1.", ephemeral=True)
        return
    stats = get_invite_stats(interaction.guild.id, member.id)
    stats["total"] = max(0, stats["total"] - amount)
    overflow = max(0, stats["regular"] + stats["bonus"] - stats["total"])
    bonus_removed = min(stats["bonus"], overflow)
    stats["bonus"] -= bonus_removed
    stats["regular"] = min(stats["regular"], stats["total"] - stats["bonus"])
    save_data()
    await interaction.response.send_message(
        f"➖ Removed **{amount} invites** from {member.mention}. They now have **{stats['total']} invites**.")

@bot.tree.command(name="resetinvites", description="Reset a member's invites.")
@app_commands.checks.has_permissions(manage_guild=True)
async def resetinvites(interaction, member: discord.Member):
    get_invite_data(interaction.guild.id)[str(member.id)] = deepcopy(DEFAULT_INVITE_STATS)
    save_data()
    await interaction.response.send_message(f"🔄 Reset all invite data for {member.mention}.")

@bot.tree.command(name="ping", description="Check AuraGuard latency.")
async def ping(interaction):
    await interaction.response.send_message(embed=aura_embed(
        "AuraGuard Online", f"⚡ Pong!\nLatency: **{round(bot.latency * 1000)}ms**",
        AURA_PURPLE, "⚡"), ephemeral=True)

@bot.tree.command(name="setstaffrole", description="Set the staff role.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setstaffrole(interaction, role: discord.Role):
    get_settings(interaction.guild.id)["staff_role"] = role.id
    save_data()
    await interaction.response.send_message(f"🛡️ Staff role set to {role.mention}.", ephemeral=True)

@bot.tree.command(name="setlogchannel", description="Set the moderation log channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setlogchannel(interaction, log_channel: discord.TextChannel):
    get_settings(interaction.guild.id)["log_channel"] = log_channel.id
    save_data()
    await interaction.response.send_message(f"📋 Log channel set to {log_channel.mention}.", ephemeral=True)

@bot.tree.command(name="setmessagelog", description="Set the message log channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setmessagelog(interaction, message_log_channel: discord.TextChannel):
    get_settings(interaction.guild.id)["message_log_channel"] = message_log_channel.id
    save_data()
    await interaction.response.send_message(f"💬 Message log set to {message_log_channel.mention}.", ephemeral=True)

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
    if word.lower() in {item.lower() for item in automod["blocked_words"]}:
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

async def hierarchy_check(interaction, member):
    guild = interaction.guild
    me = guild.me or guild.get_member(bot.user.id)

    if member == interaction.user or member == guild.owner:
        await interaction.response.send_message("❌ You can't moderate that member.", ephemeral=True)
        return False

    if interaction.user != guild.owner and member.top_role >= interaction.user.top_role:
        await interaction.response.send_message("❌ That member has an equal or higher role.", ephemeral=True)
        return False

    if me and member.top_role >= me.top_role:
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
    await send_log(interaction.guild, "Member Kicked",
                   f"Member: {member.mention}\nModerator: {interaction.user.mention}\nReason: {reason}", AURA_RED)

@bot.tree.command(name="ban", description="Ban a member.")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await hierarchy_check(interaction, member):
        return
    await member.ban(reason=reason)
    await interaction.response.send_message(f"🔨 Banned {member.mention}.")
    await send_log(interaction.guild, "Member Banned",
                   f"Member: {member.mention}\nModerator: {interaction.user.mention}\nReason: {reason}", AURA_RED)

@bot.tree.command(name="unban", description="Unban a user by ID.")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction, user_id: str):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user, reason=f"Unbanned by {interaction.user}")
        await interaction.response.send_message(f"🔓 **{user}** has been unbanned.")
        await send_log(interaction.guild, "Member Unbanned",
                       f"User: {user}\nModerator: {interaction.user.mention}", AURA_GREEN)
    except (ValueError, discord.NotFound, discord.Forbidden):
        await interaction.response.send_message("❌ User not found or not banned.", ephemeral=True)

@bot.tree.command(name="timeout", description="Timeout a member.")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout(interaction, member: discord.Member, minutes: int, reason: str = "No reason provided"):
    if minutes < 1 or minutes > 40320:
        await interaction.response.send_message("❌ Choose between 1 minute and 28 days.", ephemeral=True)
        return
    if not await hierarchy_check(interaction, member):
        return
    await member.timeout(discord.utils.utcnow() + timedelta(minutes=minutes), reason=reason)
    await interaction.response.send_message(f"⏳ {member.mention} timed out for **{minutes} minutes**.")
    await send_log(interaction.guild, "Member Timed Out",
                   f"Member: {member.mention}\nModerator: {interaction.user.mention}\nReason: {reason}", AURA_RED)

@bot.tree.command(name="untimeout", description="Remove a timeout.")
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout(interaction, member: discord.Member):
    if not await hierarchy_check(interaction, member):
        return
    await member.timeout(None, reason=f"Timeout removed by {interaction.user}")
    await interaction.response.send_message(f"🔓 Removed {member.mention}'s timeout.")

# -------------------- PREFIX MODERATION COMMANDS --------------------

def parse_duration(value: str) -> timedelta | None:
    """Parse CHIB-style durations: 1s/1sec, 10m, 2h, 1d, or 1w."""
    value = value.strip().lower()
    match = re.fullmatch(r"(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|week|weeks)", value)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    if amount < 1:
        return None
    multipliers = {
        "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
        "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
        "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
        "d": 86400, "day": 86400, "days": 86400,
        "w": 604800, "week": 604800, "weeks": 604800,
    }
    seconds = amount * multipliers[unit]
    if seconds > 28 * 86400:
        return None
    return timedelta(seconds=seconds)

def prefix_can_moderate(ctx, member: discord.Member) -> bool:
    guild = ctx.guild
    if member == ctx.author or member == guild.owner:
        return False
    if ctx.author != guild.owner and member.top_role >= ctx.author.top_role:
        return False
    me = guild.me
    if me and member.top_role >= me.top_role:
        return False
    return True

@bot.command(name="mute", aliases=["timeout"])
@commands.has_guild_permissions(moderate_members=True)
async def prefix_mute(ctx, member: discord.Member, *, details: str = ""):
    """Timeout a member. CHIB-style: !mute @user <reason> <duration>."""
    parts = details.split()
    duration = parts[-1] if parts else ""
    reason = " ".join(parts[:-1]).strip() or "No reason provided"
    delta = parse_duration(duration)
    if delta is None:
        await ctx.send(embed=aura_embed(
            "Invalid Duration",
            "Use formats like `3m`, `1h`, `1d`, or `1sec` (maximum 28 days).\n"
            "Usage: `!mute @user <reason> <duration>`\n"
            "Example: `!mute @user testing 1sec`",
            AURA_YELLOW, "⚠️"))
        return
    if not prefix_can_moderate(ctx, member):
        await ctx.send(embed=aura_embed("Can't Mute Member", "You can't moderate that member. Check role hierarchy.", AURA_RED, "❌"))
        return
    try:
        await member.timeout(discord.utils.utcnow() + delta, reason=f"{reason} | Moderator: {ctx.author}")
    except discord.Forbidden:
        await ctx.send(embed=aura_embed("Permission Error", "I don't have permission to timeout that member, or my role is too low.", AURA_RED, "❌"))
        return
    await ctx.send(embed=aura_embed(
        "Mute Successfully Issued",
        f"✅ {member.mention} was timed out.\n**Duration:** `{duration}`\n**Reason:** {reason}\n**Moderator:** {ctx.author.mention}",
        AURA_GREEN, "✅"))

@bot.command(name="unmute", aliases=["untimeout"])
@commands.has_guild_permissions(moderate_members=True)
async def prefix_unmute(ctx, member: discord.Member):
    if not prefix_can_moderate(ctx, member):
        await ctx.send(embed=aura_embed("Can't Unmute Member", "You can't moderate that member. Check role hierarchy.", AURA_RED, "❌"))
        return
    try:
        await member.timeout(None, reason=f"Timeout removed by {ctx.author}")
    except discord.Forbidden:
        await ctx.send(embed=aura_embed("Permission Error", "I don't have permission to remove that timeout.", AURA_RED, "❌"))
        return
    await ctx.send(embed=aura_embed("Unmute Successful", f"🔓 Removed {member.mention}'s timeout.", AURA_GREEN, "✅"))

@bot.command(name="warn")
@commands.has_guild_permissions(moderate_members=True)
async def prefix_warn(ctx, member: discord.Member, *, reason: str):
    if not prefix_can_moderate(ctx, member):
        await ctx.send(embed=aura_embed("Can't Warn Member", "You can't moderate that member. Check role hierarchy.", AURA_RED, "❌"))
        return
    guild_warnings = data["warnings"].setdefault(str(ctx.guild.id), {})
    member_warnings = guild_warnings.setdefault(str(member.id), [])
    member_warnings.append({
        "reason": reason,
        "moderator_id": ctx.author.id,
        "moderator": str(ctx.author),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    save_data()
    await ctx.send(embed=aura_embed(
        "Warning Successfully Issued",
        f"Thanks for doing your job {ctx.author.mention}!\n\n"
        f"The warning for {member.mention} was recorded.\n**Reason:** {reason}\n"
        f"**Total warnings:** {len(member_warnings)}",
        AURA_GREEN, "✅"))

@bot.command(name="warnings", aliases=["warns"])
@commands.has_guild_permissions(moderate_members=True)
async def prefix_warnings(ctx, member: discord.Member):
    entries = data["warnings"].get(str(ctx.guild.id), {}).get(str(member.id), [])
    if not entries:
        await ctx.send(embed=aura_embed("No Warnings", f"{member.mention} has no recorded warnings.", AURA_BLUE, "📋"))
        return
    lines = [f"**{i}.** {item.get('reason', 'No reason provided')} — {item.get('moderator', 'Unknown moderator')}"
             for i, item in enumerate(entries[-10:], start=max(1, len(entries)-9))]
    await ctx.send(embed=aura_embed("Member Warnings", f"Warnings for {member.mention} ({len(entries)} total):\n" + "\n".join(lines), AURA_YELLOW, "📋"))

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        command_name = ctx.command.qualified_name if ctx.command else "command"
        if command_name in ("mute", "timeout", "unmute", "untimeout"):
            usage = "!mute @user <reason> <duration>" if command_name in ("mute", "timeout") else "!unmute @user"
            title = "Missing User" if not ctx.message.mentions else "Missing Argument"
        elif command_name == "warn":
            usage, title = "!warn @user <reason>", "Missing User or Reason"
        elif command_name in ("warnings", "warns"):
            usage, title = "!warnings @user", "Missing User"
        else:
            usage, title = f"!{command_name} <required arguments>", "Missing Argument"
        await ctx.send(embed=aura_embed(title, f"Usage: `{usage}`", AURA_YELLOW, "⚠️"))
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=aura_embed("Permission Denied", "❌ You don't have permission to use this command.", AURA_RED, "❌"))
        return
    if isinstance(error, commands.BotMissingPermissions):
        await ctx.send(embed=aura_embed("Permission Error", "❌ I don't have the permissions needed for that command.", AURA_RED, "❌"))
        return
    if isinstance(error, commands.BadArgument):
        await ctx.send(embed=aura_embed("Invalid User", "Mention a valid server member. Example: `!mute @user 10m Spamming`", AURA_RED, "❌"))
        return
    print("Prefix command error:", repr(error))

@bot.event
async def on_ready():
    print("=" * 45)
    print(f"AuraGuard V8 online as {bot.user}")
    print(f"Bot ID: {bot.user.id}")
    print("=" * 45)

    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Activity(type=discord.ActivityType.watching, name="over your server 🛡️")
    )

    if not getattr(bot, "_auraguard_views_loaded", False):
        bot.add_view(TicketView())
        bot.add_view(TicketControls())
        for giveaway_id in list(data["giveaways"]):
            bot.add_view(GiveawayView(giveaway_id))
        bot._auraguard_views_loaded = True

    for guild in bot.guilds:
        try:
            invites = await guild.invites()
            invite_cache[guild.id] = {invite.code: invite.uses or 0 for invite in invites}
        except (discord.Forbidden, discord.HTTPException) as e:
            print(f"Could not load invites for {guild.name}: {e}")

    if not giveaway_loop.is_running():
        giveaway_loop.start()

    if not getattr(bot, "_auraguard_synced", False):
        try:
            synced = await bot.tree.sync()
            bot._auraguard_synced = True
            print(f"Synced {len(synced)} top-level slash commands.")
        except Exception as e:
            print("Slash command sync error:", repr(e))

@bot.event
async def on_member_join(member):
    guild = member.guild
    inviter = None

    try:
        old_invites = invite_cache.get(guild.id, {})
        new_invites = await guild.invites()
        used = next(
            (invite for invite in new_invites if (invite.uses or 0) > old_invites.get(invite.code, 0)),
            None
        )
        if used:
            inviter = used.inviter
        invite_cache[guild.id] = {invite.code: invite.uses or 0 for invite in new_invites}
    except (discord.Forbidden, discord.HTTPException) as e:
        print("Invite tracking error:", repr(e))

    if inviter and inviter.id != member.id:
        stats = get_invite_stats(guild.id, inviter.id)
        stats["total"] += 1
        stats["regular"] += 1
        get_member_invites(guild.id)[str(member.id)] = inviter.id
        save_data()

        channel_id = get_settings(guild.id).get("invite_channel")
        invite_channel = guild.get_channel(channel_id) if channel_id else None
        if isinstance(invite_channel, discord.TextChannel):
            try:
                await invite_channel.send(embed=aura_embed(
                    "New Invite!",
                    f"👋 **Member:** {member.mention}\n\n📨 **Invited By:** {inviter.mention}\n\n"
                    f"📊 **Total Invites:** **{stats['total']}**",
                    AURA_GREEN, "📨"))
            except discord.HTTPException:
                pass

        await send_log(guild, "Member Joined",
                       f"👤 **Member:** {member.mention}\n📨 **Invited By:** {inviter.mention}\n"
                       f"📊 **Their Invites:** **{stats['total']}**", AURA_GREEN)
    else:
        await send_log(guild, "Member Joined",
                       f"👤 **Member:** {member.mention}\n📨 **Inviter:** Unknown", AURA_GREEN)

    settings = get_settings(guild.id)
    if settings.get("welcome_enabled"):
        channel_id = settings.get("welcome_channel")
        channel = guild.get_channel(channel_id) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            await send_welcome(member, channel, inviter)

@bot.event
async def on_member_remove(member):
    guild = member.guild
    inviter_id = get_member_invites(guild.id).pop(str(member.id), None)

    if inviter_id:
        stats = get_invite_data(guild.id).get(str(inviter_id))
        if stats:
            stats["total"] = max(0, stats.get("total", 0) - 1)
            stats["regular"] = max(0, stats.get("regular", 0) - 1)
            stats["left"] = stats.get("left", 0) + 1
            save_data()

    settings = get_settings(guild.id)
    if settings.get("leave_enabled"):
        channel_id = settings.get("leave_channel")
        channel = guild.get_channel(channel_id) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            await channel.send(embed=aura_embed(
                "Member Left",
                apply_placeholders(settings["leave_message"], member),
                AURA_YELLOW, "🚪"))

    await send_log(guild, "Member Left", f"Member: {member}\nID: `{member.id}`", AURA_YELLOW)

@bot.event
async def on_invite_create(invite):
    if invite.guild:
        invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses or 0

@bot.event
async def on_invite_delete(invite):
    if invite.guild:
        invite_cache.setdefault(invite.guild.id, {}).pop(invite.code, None)

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
                except discord.HTTPException:
                    pass
                try:
                    await message.channel.send(
                        f"⚠️ {message.author.mention}, that message contains a blocked word.",
                        delete_after=5
                    )
                except discord.HTTPException:
                    pass
                await send_log(message.guild, "AutoMod Action",
                               f"Member: {message.author.mention}\nChannel: {message.channel.mention}",
                               AURA_RED)
                return

    await send_message_log(
        message.guild, "Message Sent",
        f"**Author:** {message.author.mention}\n**Channel:** {message.channel.mention}\n\n"
        f"**Message:**\n{clean_message_content(message.content)}"
    )
    await bot.process_commands(message)

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild:
        return
    await send_message_log(
        message.guild, "Message Deleted",
        f"**Author:** {message.author.mention}\n**Channel:** {message.channel.mention}\n\n"
        f"**Deleted Message:**\n{clean_message_content(message.content)}",
        AURA_RED
    )

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild or before.content == after.content:
        return
    await send_message_log(
        before.guild, "Message Edited",
        f"**Author:** {before.author.mention}\n**Channel:** {before.channel.mention}\n\n"
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
            channel = guild.get_channel(giveaway["channel"]) if guild else None
            try:
                await finish_giveaway(guild, channel, giveaway_id)
            except Exception as e:
                print("Giveaway error:", repr(e))

@giveaway_loop.before_loop
async def before_giveaway_loop():
    await bot.wait_until_ready()

for group in [welcome_group, leave_group, tickets_group, giveaway_group, automod_group]:
    bot.tree.add_command(group)

@bot.tree.error
async def on_app_command_error(interaction, error):
    print("Command error:", repr(error))

    if isinstance(error, app_commands.MissingPermissions):
        message = "❌ You don't have permission to use that command."
    elif isinstance(error, app_commands.BotMissingPermissions):
        message = "❌ I don't have the required permissions to do that."
    elif isinstance(error, app_commands.TransformerError):
        message = "❌ Please select a valid channel, role, or member from Discord's menu."
    elif isinstance(error, app_commands.CommandOnCooldown):
        message = "❌ Please wait a moment before using that command again."
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
