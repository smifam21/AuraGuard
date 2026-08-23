# =========================================================
#                    AURAGUARD V6
# =========================================================
# Updates:
# - Ticket close delay changed to 1 second
# - Giveaway Participate button
# - Giveaway Info button
# - Private "My Entries" button
# - Staff-only participant list
# - Giveaway IDs shown in giveaway embeds
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

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

DEFAULT_DATA = {
    "settings": {}, "warnings": {}, "giveaways": {},
    "giveaway_entries": {}, "giveaway_history": {},
    "backups": {}, "ticket_claims": {}, "automod": {}
}

def load_data():
    if not os.path.exists(DATA_FILE):
        return json.loads(json.dumps(DEFAULT_DATA))
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        for k, v in DEFAULT_DATA.items():
            d.setdefault(k, v)
        return d
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

def get_settings(guild_id):
    gid = str(guild_id)
    defaults = {
        "welcome_enabled": False, "welcome_channel": None,
        "welcome_message": "Welcome {user} to {server}! 🛡️",
        "welcome_image_enabled": True,
        "leave_enabled": False, "leave_channel": None,
        "leave_message": "{user} has left {server}. 👋",
        "ticket_category": None, "staff_role": None,
        "log_channel": None, "message_log_channel": None,
        "giveaway_bonus_roles": {}
    }
    if gid not in data["settings"]:
        data["settings"][gid] = defaults.copy()
        save_data()
    else:
        for k, v in defaults.items():
            data["settings"][gid].setdefault(k, v)
    return data["settings"][gid]

def get_automod(guild_id):
    gid = str(guild_id)
    data["automod"].setdefault(gid, {"enabled": False, "blocked_words": []})
    return data["automod"][gid]

def aura_embed(title, description="", color=AURA_PURPLE, emoji="🛡️"):
    e = discord.Embed(
        title=f"{emoji} {title}", description=description,
        color=color, timestamp=datetime.now(timezone.utc)
    )
    e.set_footer(text=FOOTER)
    return e

def is_staff(member):
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    rid = get_settings(member.guild.id).get("staff_role")
    role = member.guild.get_role(rid) if rid else None
    return bool(role and role in member.roles)

def apply_placeholders(text, member):
    return (text.replace("{user}", member.mention)
            .replace("{server}", member.guild.name)
            .replace("{member_count}", str(member.guild.member_count)))

def clean_message_content(content):
    return discord.utils.escape_markdown(content or "*No text content*")[:3500]

def make_unique_id(collection):
    while True:
        x = str(random.randint(100000, 999999))
        if x not in collection:
            return x

def weighted_winners(entries, amount):
    pool = {u: int(w) for u, w in entries.items() if int(w) > 0}
    result = []
    while pool and len(result) < amount:
        u = random.choices(list(pool), weights=list(pool.values()), k=1)[0]
        result.append(u)
        pool.pop(u)
    return result

async def send_log(guild, title, description, color=AURA_PURPLE):
    cid = get_settings(guild.id).get("log_channel")
    channel = guild.get_channel(cid) if cid else None
    if isinstance(channel, discord.TextChannel):
        try:
            await channel.send(embed=aura_embed(title, description, color, "📋"))
        except Exception:
            pass

async def send_message_log(guild, title, description, color=AURA_BLUE):
    cid = get_settings(guild.id).get("message_log_channel")
    channel = guild.get_channel(cid) if cid else None
    if isinstance(channel, discord.TextChannel):
        try:
            await channel.send(embed=aura_embed(title, description[:4000], color, "💬"))
        except Exception:
            pass

# ==================== WELCOME IMAGE ====================

def get_font(size, bold=False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ]
    for p in paths:
        try: return ImageFont.truetype(p, size)
        except Exception: pass
    return ImageFont.load_default()

async def create_welcome_card(member):
    image = Image.new("RGB", (1000, 360), (18, 8, 32))
    draw = ImageDraw.Draw(image)
    draw.ellipse((650, -100, 1150, 400), fill=(85, 25, 145))
    draw.rounded_rectangle((20, 20, 980, 340), radius=30,
                           outline=(170, 90, 255), width=5)
    avatar = Image.open(io.BytesIO(await member.display_avatar.read())).convert("RGB")
    avatar = avatar.resize((190, 190))
    mask = Image.new("L", (190, 190), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 189, 189), fill=255)
    image.paste(avatar, (70, 85), mask)
    draw.text((300, 70), "WELCOME TO", font=get_font(38, True), fill=(190,145,255))
    draw.text((300, 125), member.display_name[:22], font=get_font(56, True), fill="white")
    draw.text((302, 210), member.guild.name[:35], font=get_font(30), fill=(225,215,240))
    draw.text((302, 265), f"Member #{member.guild.member_count}",
              font=get_font(26), fill=(190,145,255))
    out = io.BytesIO()
    image.save(out, "PNG"); out.seek(0)
    return discord.File(out, filename="auraguard-welcome.png")

async def send_welcome(member, channel, title="Welcome!"):
    s = get_settings(member.guild.id)
    embed = aura_embed(title, apply_placeholders(s["welcome_message"], member),
                       AURA_PURPLE, "👋")
    try:
        if s.get("welcome_image_enabled", True):
            f = await create_welcome_card(member)
            embed.set_image(url="attachment://auraguard-welcome.png")
            await channel.send(embed=embed, file=f)
        else:
            await channel.send(embed=embed)
    except Exception:
        await channel.send(embed=embed)

# ==================== TICKETS ====================

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary,
                       emoji="🎫", custom_id="auraguard_open_ticket")
    async def open_ticket(self, interaction, button):
        g, u, s = interaction.guild, interaction.user, get_settings(interaction.guild.id)
        for c in g.text_channels:
            if c.topic == f"AURAGUARD_TICKET_OWNER={u.id}":
                await interaction.response.send_message(
                    f"🎫 You already have a ticket: {c.mention}", ephemeral=True)
                return
        overwrites = {
            g.default_role: discord.PermissionOverwrite(view_channel=False),
            u: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                           read_message_history=True)
        }
        role = g.get_role(s["staff_role"]) if s.get("staff_role") else None
        if role:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True,
                send_messages=True, read_message_history=True)
        cat = g.get_channel(s["ticket_category"]) if s.get("ticket_category") else None
        c = await g.create_text_channel(
            f"ticket-{u.name}".lower()[:90],
            category=cat if isinstance(cat, discord.CategoryChannel) else None,
            overwrites=overwrites, topic=f"AURAGUARD_TICKET_OWNER={u.id}",
            reason="AuraGuard ticket opened")
        await c.send(content=u.mention, embed=aura_embed(
            "Ticket Opened", "A staff member will help you soon.\n\nUse the buttons below.",
            AURA_PURPLE, "🎫"), view=TicketControls())
        await interaction.response.send_message(f"🎫 Your ticket: {c.mention}", ephemeral=True)
        await send_log(g, "Ticket Opened", f"User: {u.mention}\nChannel: {c.mention}", AURA_BLUE)

class TicketControls(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success,
                       emoji="🙋", custom_id="auraguard_claim_ticket")
    async def claim_ticket(self, interaction, button):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Only staff can claim tickets.", ephemeral=True)
            return
        cid = str(interaction.channel.id)
        current = data["ticket_claims"].get(cid)
        if current and current != interaction.user.id:
            await interaction.response.send_message(
                f"❌ Already claimed by <@{current}>.", ephemeral=True); return
        data["ticket_claims"][cid] = interaction.user.id; save_data()
        await interaction.response.send_message(f"🙋 Ticket claimed by {interaction.user.mention}.")
        await send_log(interaction.guild, "Ticket Claimed",
                       f"Staff: {interaction.user.mention}\nChannel: {interaction.channel.mention}",
                       AURA_GREEN)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger,
                       emoji="🔒", custom_id="auraguard_close_ticket")
    async def close_ticket(self, interaction, button):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Only staff can close tickets.", ephemeral=True)
            return
        await interaction.response.send_message("🔒 Closing ticket in **1 second**...")
        await send_log(interaction.guild, "Ticket Closed",
                       f"Staff: {interaction.user.mention}\nChannel: {interaction.channel.mention}",
                       AURA_RED)
        await asyncio.sleep(1)  # V4: changed from 5 seconds to 1
        data["ticket_claims"].pop(str(interaction.channel.id), None); save_data()
        await interaction.channel.delete(reason="AuraGuard ticket closed")

# ==================== GIVEAWAYS V6 ===================

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
        "**Click Participate to enter!**",
        AURA_PURPLE, "🎉"
    )

class GiveawayView(discord.ui.View):
    def __init__(self, giveaway_id):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id

        b = discord.ui.Button(label="Participate", emoji="🎉",
                              style=discord.ButtonStyle.success,
                              custom_id=f"auraguard_giveaway_enter_{giveaway_id}")
        b.callback = self.enter; self.add_item(b)
        b = discord.ui.Button(label="Giveaway Info", emoji="ℹ️",
                              style=discord.ButtonStyle.secondary,
                              custom_id=f"auraguard_giveaway_info_{giveaway_id}")
        b.callback = self.info; self.add_item(b)
        b = discord.ui.Button(label="My Entries", emoji="🎟️",
                              style=discord.ButtonStyle.primary,
                              custom_id=f"auraguard_giveaway_myentries_{giveaway_id}")
        b.callback = self.my_entries; self.add_item(b)

    async def enter(self, interaction):
        giveaway = data["giveaways"].get(self.giveaway_id)
        if not giveaway:
            await interaction.response.send_message("❌ This giveaway is no longer active.", ephemeral=True); return
        entries = data["giveaway_entries"].setdefault(self.giveaway_id, {})
        uid = str(interaction.user.id)
        if uid in entries:
            await interaction.response.send_message(
                f"❌ You're already entered with **{entries[uid]} entries**.", ephemeral=True); return
        amount = 1
        s = get_settings(interaction.guild.id)
        for rid, bonus in s.get("giveaway_bonus_roles", {}).items():
            role = interaction.guild.get_role(int(rid))
            if role and role in interaction.user.roles:
                amount += int(bonus)
        entries[uid] = amount; save_data()
        await interaction.response.send_message(
            f"🎉 You're entered with **{amount} {'entry' if amount == 1 else 'entries'}**!",
            ephemeral=True)

    async def info(self, interaction):
        g = data["giveaways"].get(self.giveaway_id)
        if not g:
            await interaction.response.send_message("❌ This giveaway is no longer active.", ephemeral=True); return
        await interaction.response.send_message(
            embed=giveaway_embed(self.giveaway_id, g), ephemeral=True)

    async def my_entries(self, interaction):
        g = data["giveaways"].get(self.giveaway_id)
        if not g:
            await interaction.response.send_message("❌ This giveaway is no longer active.", ephemeral=True); return
        entries = data["giveaway_entries"].get(self.giveaway_id, {})
        amount = entries.get(str(interaction.user.id), 0)
        end = datetime.fromisoformat(g["end_time"])
        await interaction.response.send_message(embed=aura_embed(
            "My Giveaway Entries",
            f"🎁 **Prize:** {g['prize']}\n"
            f"🆔 **Giveaway ID:** `{self.giveaway_id}`\n"
            f"🎟️ **Your Entries:** **{amount}**\n"
            f"⏰ **Ends:** <t:{int(end.timestamp())}:R>",
            AURA_PURPLE, "🎟️"), ephemeral=True)

async def finish_giveaway(guild, channel, giveaway_id):
    g = data["giveaways"].get(giveaway_id)
    if not g: return []
    entries = data["giveaway_entries"].get(giveaway_id, {})
    winners = weighted_winners(entries, g["winners"])
    history = dict(g)
    history["entries"] = dict(entries)
    history["winners_list"] = winners
    history["ended_at"] = datetime.now(timezone.utc).isoformat()
    data["giveaway_history"][giveaway_id] = history
    data["giveaways"].pop(giveaway_id, None)
    data["giveaway_entries"].pop(giveaway_id, None)
    save_data()
    if channel:
        if winners:
            await channel.send(embed=aura_embed(
                "Giveaway Winner!", f"🎁 **Prize:** {history['prize']}\n\n🏆 " +
                " ".join(f"<@{u}>" for u in winners), AURA_GREEN, "🏆"))
        else:
            await channel.send(embed=aura_embed(
                "Giveaway Ended", f"🎁 **{history['prize']}**\n\nNobody entered.",
                AURA_YELLOW, "🎉"))
    return winners

# ==================== COMMAND GROUPS ====================

welcome_group = app_commands.Group(name="welcome", description="Manage welcome messages.")
leave_group = app_commands.Group(name="leave", description="Manage leave messages.")
tickets_group = app_commands.Group(name="tickets", description="Manage AuraGuard tickets.")
giveaway_group = app_commands.Group(name="giveaway", description="Manage giveaways.")
automod_group = app_commands.Group(name="automod", description="Manage AuraGuard AutoMod.")
backup_group = app_commands.Group(name="backup", description="Manage server backups.")

@welcome_group.command(name="setup", description="Set welcome channel and message.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_setup(interaction, channel: discord.TextChannel,
                        message: str="Welcome {user} to {server}! 🛡️"):
    s=get_settings(interaction.guild.id); s["welcome_channel"]=channel.id
    s["welcome_message"]=message; save_data()
    await interaction.response.send_message("✅ Welcome setup saved.", ephemeral=True)

@welcome_group.command(name="enable", description="Enable welcome messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_enable(interaction):
    s=get_settings(interaction.guild.id)
    if not s["welcome_channel"]:
        await interaction.response.send_message("❌ Run `/welcome setup` first.", ephemeral=True); return
    s["welcome_enabled"]=True; save_data()
    await interaction.response.send_message("🟢 Welcome messages enabled.", ephemeral=True)

@welcome_group.command(name="disable", description="Disable welcome messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_disable(interaction):
    get_settings(interaction.guild.id)["welcome_enabled"]=False; save_data()
    await interaction.response.send_message("🔴 Welcome messages disabled.", ephemeral=True)

@welcome_group.command(name="image", description="Turn welcome image on or off.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_image(interaction, enabled: bool):
    get_settings(interaction.guild.id)["welcome_image_enabled"]=enabled; save_data()
    await interaction.response.send_message(f"🖼️ Welcome image {'enabled' if enabled else 'disabled'}.", ephemeral=True)

@welcome_group.command(name="test", description="Test welcome message.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_test(interaction):
    c=interaction.guild.get_channel(get_settings(interaction.guild.id).get("welcome_channel"))
    if not isinstance(c, discord.TextChannel):
        await interaction.response.send_message("❌ Run `/welcome setup` first.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True); await send_welcome(interaction.user,c,"Welcome Test")
    await interaction.followup.send(f"✅ Test sent to {c.mention}.", ephemeral=True)

@leave_group.command(name="setup", description="Set leave channel and message.")
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_setup(interaction, channel: discord.TextChannel,
                      message: str="{user} has left {server}. 👋"):
    s=get_settings(interaction.guild.id); s["leave_channel"]=channel.id; s["leave_message"]=message; save_data()
    await interaction.response.send_message("✅ Leave setup saved.", ephemeral=True)

@leave_group.command(name="enable", description="Enable leave messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_enable(interaction):
    s=get_settings(interaction.guild.id)
    if not s["leave_channel"]:
        await interaction.response.send_message("❌ Run `/leave setup` first.", ephemeral=True); return
    s["leave_enabled"]=True; save_data()
    await interaction.response.send_message("🟢 Leave messages enabled.", ephemeral=True)

@leave_group.command(name="disable", description="Disable leave messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_disable(interaction):
    get_settings(interaction.guild.id)["leave_enabled"]=False; save_data()
    await interaction.response.send_message("🔴 Leave messages disabled.", ephemeral=True)

@leave_group.command(name="test", description="Test leave message.")
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_test(interaction):
    s=get_settings(interaction.guild.id); c=interaction.guild.get_channel(s.get("leave_channel"))
    if not isinstance(c, discord.TextChannel):
        await interaction.response.send_message("❌ Run `/leave setup` first.", ephemeral=True); return
    await c.send(embed=aura_embed("Leave Test",apply_placeholders(s["leave_message"],interaction.user),AURA_YELLOW,"🚪"))
    await interaction.response.send_message("✅ Leave test sent.", ephemeral=True)

@tickets_group.command(name="setup", description="Set ticket category.")
@app_commands.checks.has_permissions(manage_guild=True)
async def tickets_setup(interaction, category: discord.CategoryChannel):
    get_settings(interaction.guild.id)["ticket_category"]=category.id; save_data()
    await interaction.response.send_message(f"🎫 Ticket category set to **{category.name}**.", ephemeral=True)

@tickets_group.command(name="panel", description="Send ticket panel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def tickets_panel(interaction):
    await interaction.response.send_message(embed=aura_embed(
        "AuraGuard Support","Need help?\n\nClick below to open a ticket.",AURA_PURPLE,"🎫"),view=TicketView())

@giveaway_group.command(name="start", description="Start a giveaway.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_start(interaction, prize: str, minutes: int, winners: int=1):
    if minutes < 1 or winners < 1:
        await interaction.response.send_message("❌ Minutes and winners must be at least 1.",ephemeral=True); return
    gid=make_unique_id(data["giveaways"]); end=datetime.now(timezone.utc)+timedelta(minutes=minutes)
    data["giveaways"][gid]={"guild":interaction.guild.id,"channel":interaction.channel.id,
        "prize":prize,"winners":winners,"end_time":end.isoformat(),"created_by":interaction.user.id}
    data["giveaway_entries"][gid]={}; save_data()
    await interaction.response.send_message(embed=giveaway_embed(gid,data["giveaways"][gid]),view=GiveawayView(gid))

@giveaway_group.command(name="participants", description="View giveaway participants.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_participants(interaction, giveaway_id: str):
    g=data["giveaways"].get(giveaway_id)
    entries=data["giveaway_entries"].get(giveaway_id)
    if g is None or entries is None:
        await interaction.response.send_message("❌ Active giveaway not found.",ephemeral=True); return
    if not entries:
        text="Nobody has entered yet."
    else:
        lines=[]
        for i,(uid,count) in enumerate(entries.items(),1):
            lines.append(f"**{i}.** <@{uid}> — **{count} entries**")
        text="\n".join(lines)
    await interaction.response.send_message(embed=aura_embed(
        f"Giveaway Participants • {giveaway_id}",
        f"👥 **Participants:** {len(entries)}\n🎟️ **Total Entries:** {sum(entries.values())}\n\n{text[:3500]}",
        AURA_PURPLE,"👥"),ephemeral=True)

@giveaway_group.command(name="entries", description="Check your entries.")
async def giveaway_entries(interaction, giveaway_id: str):
    amount=data["giveaway_entries"].get(giveaway_id,{}).get(str(interaction.user.id),0)
    await interaction.response.send_message(f"🎟️ You have **{amount} {'entry' if amount==1 else 'entries'}**.",ephemeral=True)

@giveaway_group.command(name="addentries", description="Give extra entries.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_addentries(interaction,giveaway_id:str,member:discord.Member,amount:int):
    if amount<1 or giveaway_id not in data["giveaways"]:
        await interaction.response.send_message("❌ Invalid amount or active giveaway.",ephemeral=True); return
    e=data["giveaway_entries"].setdefault(giveaway_id,{}); uid=str(member.id)
    e[uid]=e.get(uid,0)+amount; save_data()
    await interaction.response.send_message(f"➕ {member.mention} now has **{e[uid]} entries**.",ephemeral=True)

@giveaway_group.command(name="removeentries", description="Remove entries.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_removeentries(interaction,giveaway_id:str,member:discord.Member,amount:int):
    e=data["giveaway_entries"].get(giveaway_id,{})
    uid=str(member.id)
    if amount<1 or uid not in e:
        await interaction.response.send_message("❌ Invalid amount or member has no entries.",ephemeral=True); return
    e[uid]-=amount
    if e[uid]<=0:e.pop(uid)
    save_data()
    await interaction.response.send_message(f"➖ {member.mention}'s entries updated.",ephemeral=True)

@giveaway_group.command(name="bonusrole", description="Set role bonus entries.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_bonusrole(interaction,role:discord.Role,extra_entries:int):
    if extra_entries<1:
        await interaction.response.send_message("❌ Extra entries must be at least 1.",ephemeral=True); return
    get_settings(interaction.guild.id)["giveaway_bonus_roles"][str(role.id)]=extra_entries; save_data()
    await interaction.response.send_message(f"⭐ {role.mention} gets **+{extra_entries} entries**.",ephemeral=True)

@giveaway_group.command(name="removebonusrole", description="Remove role giveaway bonus.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_removebonusrole(interaction,role:discord.Role):
    x=get_settings(interaction.guild.id)["giveaway_bonus_roles"].pop(str(role.id),None);save_data()
    await interaction.response.send_message("✅ Bonus removed." if x is not None else "❌ That role has no bonus.",ephemeral=True)

@giveaway_group.command(name="end", description="End giveaway early.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_end(interaction,giveaway_id:str):
    g=data["giveaways"].get(giveaway_id)
    if not g or g["guild"]!=interaction.guild.id:
        await interaction.response.send_message("❌ Giveaway not found.",ephemeral=True);return
    await interaction.response.defer()
    c=interaction.guild.get_channel(g["channel"])
    await finish_giveaway(interaction.guild,c if isinstance(c,discord.TextChannel) else None,giveaway_id)

@giveaway_group.command(name="reroll", description="Reroll a finished giveaway.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_reroll(interaction,giveaway_id:str):
    h=data["giveaway_history"].get(giveaway_id)
    if not h: await interaction.response.send_message("❌ Finished giveaway not found.",ephemeral=True);return
    pool={u:n for u,n in h["entries"].items() if u not in set(h.get("winners_list",[]))}
    if not pool: await interaction.response.send_message("❌ No other entries available.",ephemeral=True);return
    w=weighted_winners(pool,1)[0];h.setdefault("rerolls",[]).append(w);save_data()
    await interaction.response.send_message(embed=aura_embed("Giveaway Reroll",f"🎁 **Prize:** {h['prize']}\n\n🏆 New winner: <@{w}>",AURA_GREEN,"🔄"))

# ==================== BASIC / SETTINGS ====================

@bot.tree.command(name="ping",description="Check AuraGuard latency.")
async def ping(interaction):
    await interaction.response.send_message(embed=aura_embed("AuraGuard Online",f"⚡ Pong!\nLatency: **{round(bot.latency*1000)}ms**",AURA_PURPLE,"⚡"),ephemeral=True)

@bot.tree.command(name="setstaffrole",description="Set staff role.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setstaffrole(interaction,role:discord.Role):
    get_settings(interaction.guild.id)["staff_role"]=role.id;save_data()
    await interaction.response.send_message(f"🛡️ Staff role set to {role.mention}.",ephemeral=True)

@bot.tree.command(name="setlogchannel",description="Set moderation log channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setlogchannel(interaction,channel:discord.TextChannel):
    get_settings(interaction.guild.id)["log_channel"]=channel.id;save_data()
    await interaction.response.send_message(f"📋 Log channel set to {channel.mention}.",ephemeral=True)

@bot.tree.command(name="setmessagelog",description="Set message activity log.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setmessagelog(interaction,channel:discord.TextChannel):
    get_settings(interaction.guild.id)["message_log_channel"]=channel.id;save_data()
    await interaction.response.send_message(f"💬 Message log set to {channel.mention}.",ephemeral=True)

# ==================== AUTOMOD ====================

@automod_group.command(name="enable",description="Enable blocked-word AutoMod.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_enable(interaction):
    get_automod(interaction.guild.id)["enabled"]=True;save_data()
    await interaction.response.send_message("🛡️ AutoMod enabled.",ephemeral=True)

@automod_group.command(name="disable",description="Disable AutoMod.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_disable(interaction):
    get_automod(interaction.guild.id)["enabled"]=False;save_data()
    await interaction.response.send_message("🔴 AutoMod disabled.",ephemeral=True)

@automod_group.command(name="addword",description="Add blocked word.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_addword(interaction,word:str):
    s=get_automod(interaction.guild.id);word=word.strip()
    if not word or word.lower() in [x.lower() for x in s["blocked_words"]]:
        await interaction.response.send_message("❌ Invalid or already blocked.",ephemeral=True);return
    s["blocked_words"].append(word);save_data()
    await interaction.response.send_message(f"🛡️ Added `{word}`.",ephemeral=True)

@automod_group.command(name="removeword",description="Remove blocked word.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_removeword(interaction,word:str):
    s=get_automod(interaction.guild.id)
    match=next((x for x in s["blocked_words"] if x.lower()==word.lower()),None)
    if not match: await interaction.response.send_message("❌ Not on blocked list.",ephemeral=True);return
    s["blocked_words"].remove(match);save_data()
    await interaction.response.send_message(f"✅ Removed `{match}`.",ephemeral=True)

@automod_group.command(name="list",description="View blocked words.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_list(interaction):
    s=get_automod(interaction.guild.id);words=s["blocked_words"]
    await interaction.response.send_message(embed=aura_embed("AutoMod Settings",
        f"**Status:** {'🟢 Enabled' if s['enabled'] else '🔴 Disabled'}\n\n"+
        ("\n".join(f"• `{x}`" for x in words) if words else "No blocked words."),
        AURA_PURPLE,"🛡️"),ephemeral=True)

# ==================== MODERATION ====================

async def hierarchy_check(interaction,member):
    if member==interaction.user or member==interaction.guild.owner:
        await interaction.response.send_message("❌ You can't moderate that member.",ephemeral=True);return False
    if interaction.user!=interaction.guild.owner and member.top_role>=interaction.user.top_role:
        await interaction.response.send_message("❌ That member has an equal or higher role.",ephemeral=True);return False
    if member.top_role>=interaction.guild.me.top_role:
        await interaction.response.send_message("❌ My role is not high enough.",ephemeral=True);return False
    return True

@bot.tree.command(name="kick",description="Kick a member.")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction,member:discord.Member,reason:str="No reason provided"):
    if not await hierarchy_check(interaction,member):return
    await member.kick(reason=reason);await interaction.response.send_message(f"👢 Kicked {member.mention}.")
    await send_log(interaction.guild,"Member Kicked",f"Member: {member}\nModerator: {interaction.user}\nReason: {reason}",AURA_RED)

@bot.tree.command(name="ban",description="Ban a member.")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction,member:discord.Member,reason:str="No reason provided"):
    if not await hierarchy_check(interaction,member):return
    await member.ban(reason=reason);await interaction.response.send_message(f"🔨 Banned {member.mention}.")
    await send_log(interaction.guild,"Member Banned",f"Member: {member}\nModerator: {interaction.user}\nReason: {reason}",AURA_RED)

@bot.tree.command(name="unban",description="Unban using user ID.")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction,user_id:str):
    try:
        u=await bot.fetch_user(int(user_id));await interaction.guild.unban(u)
        await interaction.response.send_message(f"🔓 **{u}** has been unbanned.")
    except Exception: await interaction.response.send_message("❌ User not found or not banned.",ephemeral=True)

@bot.tree.command(name="timeout",description="Timeout a member.")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout(interaction,member:discord.Member,minutes:int,reason:str="No reason provided"):
    if minutes<1 or minutes>40320:
        await interaction.response.send_message("❌ Choose between 1 minute and 28 days.",ephemeral=True);return
    if not await hierarchy_check(interaction,member):return
    await member.timeout(discord.utils.utcnow()+timedelta(minutes=minutes),reason=reason)
    await interaction.response.send_message(f"⏳ {member.mention} timed out for **{minutes} minutes**.")

@bot.tree.command(name="untimeout",description="Remove timeout.")
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout(interaction,member:discord.Member):
    await member.timeout(None);await interaction.response.send_message(f"🔓 Removed {member.mention}'s timeout.")

@bot.tree.command(name="warn",description="Warn a member.")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction,member:discord.Member,reason:str="No reason provided"):
    w=data["warnings"].setdefault(str(interaction.guild.id),{}).setdefault(str(member.id),[])
    w.append({"reason":reason,"moderator":interaction.user.id,"time":datetime.now(timezone.utc).isoformat()});save_data()
    await interaction.response.send_message(f"⚠️ Warned {member.mention}. Total warnings: **{len(w)}**")

@bot.tree.command(name="warnings",description="View warnings.")
@app_commands.checks.has_permissions(moderate_members=True)
async def warnings(interaction,member:discord.Member):
    w=data["warnings"].get(str(interaction.guild.id),{}).get(str(member.id),[])
    if not w: await interaction.response.send_message(f"✅ {member.mention} has no warnings.",ephemeral=True);return
    text="\n".join(f"**{i}.** {x['reason']} — <@{x['moderator']}>" for i,x in enumerate(w,1))
    await interaction.response.send_message(embed=aura_embed(f"Warnings - {member}",text[:4000],AURA_YELLOW,"⚠️"),ephemeral=True)

@bot.tree.command(name="clear",description="Delete messages.")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction,amount:int):
    if amount<1 or amount>100:await interaction.response.send_message("❌ Choose 1-100.",ephemeral=True);return
    await interaction.response.defer(ephemeral=True);deleted=await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 Deleted **{len(deleted)} messages**.",ephemeral=True)

@bot.tree.command(name="lock",description="Lock a text channel.")
@app_commands.checks.has_permissions(manage_channels=True)
async def lock(interaction,channel:discord.TextChannel=None):
    c=channel or interaction.channel
    if not isinstance(c,discord.TextChannel):await interaction.response.send_message("❌ Text channels only.",ephemeral=True);return
    await c.set_permissions(interaction.guild.default_role,send_messages=False);await interaction.response.send_message(f"🔒 {c.mention} locked.")

@bot.tree.command(name="unlock",description="Unlock a text channel.")
@app_commands.checks.has_permissions(manage_channels=True)
async def unlock(interaction,channel:discord.TextChannel=None):
    c=channel or interaction.channel
    if not isinstance(c,discord.TextChannel):await interaction.response.send_message("❌ Text channels only.",ephemeral=True);return
    await c.set_permissions(interaction.guild.default_role,send_messages=None);await interaction.response.send_message(f"🔓 {c.mention} unlocked.")

# ==================== EVENTS ====================

@bot.event
async def on_ready():
    print("="*40);print(f"AuraGuard V5 online as {bot.user}");print(f"Bot ID: {bot.user.id}");print("="*40)
    await bot.change_presence(status=discord.Status.online,
        activity=discord.Activity(type=discord.ActivityType.watching,name="over your server 🛡️"))
    if not getattr(bot,"persistent_views",False):
        bot.add_view(TicketView());bot.add_view(TicketControls())
        # Re-add active giveaway buttons after restart
        for gid in data["giveaways"]:
            bot.add_view(GiveawayView(gid))
        bot.persistent_views=True
    if not giveaway_loop.is_running(): giveaway_loop.start()
    try:
        synced=await bot.tree.sync();print(f"Synced {len(synced)} slash commands.")
    except Exception as e:print("Slash command sync error:",e)

@bot.event
async def on_member_join(member):
    s=get_settings(member.guild.id)
    if s.get("welcome_enabled"):
        c=member.guild.get_channel(s.get("welcome_channel"))
        if isinstance(c,discord.TextChannel):await send_welcome(member,c)
    await send_log(member.guild,"Member Joined",f"Member: {member.mention}\nID: `{member.id}`",AURA_GREEN)

@bot.event
async def on_member_remove(member):
    s=get_settings(member.guild.id)
    if s.get("leave_enabled"):
        c=member.guild.get_channel(s.get("leave_channel"))
        if isinstance(c,discord.TextChannel):
            await c.send(embed=aura_embed("Member Left",
                apply_placeholders(s["leave_message"],member),AURA_YELLOW,"🚪"))
    await send_log(member.guild,"Member Left",f"Member: {member}\nID: `{member.id}`",AURA_YELLOW)

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:return
    a=get_automod(message.guild.id)
    if a.get("enabled"):
        lower=message.content.lower()
        for word in a.get("blocked_words",[]):
            if word.lower() in lower:
                try:await message.delete()
                except Exception:pass
                try:await message.channel.send(f"⚠️ {message.author.mention}, that message contains a blocked word.",delete_after=5)
                except Exception:pass
                await send_log(message.guild,"AutoMod Action",f"Member: {message.author.mention}\nChannel: {message.channel.mention}",AURA_RED)
                return
    await send_message_log(message.guild,"Message Sent",
        f"**Author:** {message.author.mention}\n**Channel:** {message.channel.mention}\n\n**Message:**\n{clean_message_content(message.content)}")

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild:return
    await send_message_log(message.guild,"Message Deleted",
        f"**Author:** {message.author.mention}\n**Channel:** {message.channel.mention}\n\n**Deleted Message:**\n{clean_message_content(message.content)}",AURA_RED)

@bot.event
async def on_message_edit(before,after):
    if before.author.bot or not before.guild or before.content==after.content:return
    await send_message_log(before.guild,"Message Edited",
        f"**Author:** {before.author.mention}\n**Channel:** {before.channel.mention}\n\n**Before:**\n{clean_message_content(before.content)}\n\n**After:**\n{clean_message_content(after.content)}",AURA_YELLOW)

@tasks.loop(seconds=15)
async def giveaway_loop():
    now=datetime.now(timezone.utc)
    for gid,g in list(data["giveaways"].items()):
        try:end=datetime.fromisoformat(g["end_time"])
        except Exception:continue
        if now>=end:
            guild=bot.get_guild(g["guild"]);c=guild.get_channel(g["channel"]) if guild else None
            try:await finish_giveaway(guild,c if isinstance(c,discord.TextChannel) else None,gid)
            except Exception as e:print("Giveaway error:",e)

@bot.tree.command(name="help",description="Show AuraGuard commands.")
async def help_command(interaction):
    text="""**👋 Welcome** `/welcome setup` `/welcome enable` `/welcome disable` `/welcome image` `/welcome test`
**🚪 Leave** `/leave setup` `/leave enable` `/leave disable` `/leave test`
**🎫 Tickets** `/tickets setup` `/tickets panel`
**🎉 Giveaways** `/giveaway start` `/giveaway participants` `/giveaway entries` `/giveaway addentries` `/giveaway removeentries` `/giveaway bonusrole` `/giveaway removebonusrole` `/giveaway end` `/giveaway reroll`
**🛡️ Moderation** `/kick` `/ban` `/unban` `/timeout` `/untimeout` `/warn` `/warnings` `/clear` `/lock` `/unlock`
**🛡️ AutoMod** `/automod enable` `/automod disable` `/automod addword` `/automod removeword` `/automod list`
**⚙️ Settings** `/setstaffrole` `/setlogchannel` `/setmessagelog`"""
    await interaction.response.send_message(embed=aura_embed("AuraGuard V4 Commands",text,AURA_PURPLE,"⚡"),ephemeral=True)

for group in [welcome_group,leave_group,tickets_group,giveaway_group,automod_group,backup_group]:
    bot.tree.add_command(group)

@bot.tree.error
async def on_app_command_error(interaction,error):
    print("Command error:",repr(error))
    msg="❌ You don't have permission to use that command." if isinstance(error,app_commands.MissingPermissions) else "❌ Something went wrong while running that command."
    try:
        if interaction.response.is_done():await interaction.followup.send(msg,ephemeral=True)
        else:await interaction.response.send_message(msg,ephemeral=True)
    except Exception:pass

bot.run(TOKEN)
