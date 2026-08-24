# =========================================================
#                    AURAGUARD V8 FIXED
# =========================================================

import discord
from discord import app_commands
from discord.ext import commands, tasks
import os, json, asyncio, io, random
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
from PIL import Image, ImageDraw, ImageFont

TOKEN = os.getenv("DISCORD_TOKEN")
DATA_FILE = "auraguard_data.json"
AURA_PURPLE=0x8A2BE2; AURA_GREEN=0x2ECC71; AURA_RED=0xE74C3C
AURA_YELLOW=0xF1C40F; AURA_BLUE=0x3498DB
FOOTER="AuraGuard • Powered by Aura"

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from Railway Variables.")

intents=discord.Intents.default()
intents.guilds=True; intents.members=True; intents.message_content=True; intents.invites=True
bot=commands.Bot(command_prefix="!", intents=intents, help_command=None)

DEFAULT_DATA={"settings":{},"warnings":{},"giveaways":{},"giveaway_entries":{},
              "giveaway_history":{},"ticket_claims":{},"automod":{},"invites":{}}

def load_data():
    if not os.path.exists(DATA_FILE): return json.loads(json.dumps(DEFAULT_DATA))
    try:
        with open(DATA_FILE,"r",encoding="utf-8") as f: d=json.load(f)
        for k,v in DEFAULT_DATA.items(): d.setdefault(k,json.loads(json.dumps(v)))
        return d
    except Exception as e:
        print("Data load error:",repr(e)); return json.loads(json.dumps(DEFAULT_DATA))

data=load_data()

def save_data():
    try:
        tmp=DATA_FILE+".tmp"
        with open(tmp,"w",encoding="utf-8") as f: json.dump(data,f,indent=4,ensure_ascii=False)
        os.replace(tmp,DATA_FILE)
    except Exception as e: print("Data save error:",repr(e))

def get_settings(guild_id):
    gid=str(guild_id)
    defaults={
        "welcome_enabled":False,"welcome_channel":None,
        "welcome_message":"Welcome {user} to {server}! 🛡️",
        "welcome_image_enabled":True,
        "leave_enabled":False,"leave_channel":None,
        "leave_message":"{user} has left {server}. 👋",
        "ticket_category":None,"staff_role":None,
        "log_channel":None,"message_log_channel":None,
        "invite_channel":None,"giveaway_bonus_roles":{}
    }
    if gid not in data["settings"]: data["settings"][gid]=defaults.copy(); save_data()
    else:
        for k,v in defaults.items(): data["settings"][gid].setdefault(k,v)
    return data["settings"][gid]

def get_automod(guild_id):
    gid=str(guild_id)
    defaults={"enabled":False,"blocked_words":[],"anti_spam":False,"spam_limit":6,"spam_seconds":5}
    if gid not in data["automod"]: data["automod"][gid]=defaults.copy(); save_data()
    else:
        for k,v in defaults.items(): data["automod"][gid].setdefault(k,v)
    return data["automod"][gid]

def get_invite_data(guild_id):
    return data["invites"].setdefault(str(guild_id),{})

def aura_embed(title,description="",color=AURA_PURPLE,emoji="🛡️"):
    e=discord.Embed(title=f"{emoji} {title}",description=description,color=color,timestamp=datetime.now(timezone.utc))
    e.set_footer(text=FOOTER); return e

def get_message_channel(guild,channel_id):
    if not channel_id: return None
    try:
        ch=guild.get_channel(int(channel_id))
        return ch if isinstance(ch,discord.TextChannel) else None
    except Exception: return None

async def safe_send(channel,*args,**kwargs):
    try:
        if isinstance(channel,(discord.TextChannel,discord.Thread)): return await channel.send(*args,**kwargs)
    except Exception as e: print("Send error:",repr(e))

async def send_log(guild,title,description,color=AURA_PURPLE):
    ch=get_message_channel(guild,get_settings(guild.id).get("log_channel"))
    if ch: await safe_send(ch,embed=aura_embed(title,description,color,"📋"))

async def send_message_log(guild,title,description,color=AURA_BLUE):
    ch=get_message_channel(guild,get_settings(guild.id).get("message_log_channel"))
    if ch: await safe_send(ch,embed=aura_embed(title,description[:4000],color,"💬"))

async def hierarchy_check(interaction,member):
    if member==interaction.user:
        await interaction.response.send_message("❌ You can't moderate yourself.",ephemeral=True); return False
    if member==interaction.guild.owner:
        await interaction.response.send_message("❌ You can't moderate the server owner.",ephemeral=True); return False
    # FIX: top_role can be unavailable/None in edge cases, so compare only real roles.
    user_role=getattr(interaction.user,"top_role",None)
    target_role=getattr(member,"top_role",None)
    bot_member=interaction.guild.me
    bot_role=getattr(bot_member,"top_role",None) if bot_member else None
    if interaction.user!=interaction.guild.owner and user_role and target_role and target_role>=user_role:
        await interaction.response.send_message("❌ That member has an equal or higher role.",ephemeral=True); return False
    if bot_role and target_role and target_role>=bot_role:
        await interaction.response.send_message("❌ My role is not high enough.",ephemeral=True); return False
    return True

# -------------------- COMMANDS --------------------

@bot.tree.command(name="ping",description="Check AuraGuard latency.")
async def ping(interaction):
    await interaction.response.send_message(embed=aura_embed("AuraGuard Online",f"⚡ Pong!\nLatency: **{round(bot.latency*1000)}ms**"))

@bot.tree.command(name="setinvitechannel",description="Set the channel for invite announcements.")
@app_commands.checks.has_permissions(manage_guild=True)
async def set_invite_channel(interaction,channel: discord.TextChannel):
    get_settings(interaction.guild.id)["invite_channel"]=channel.id; save_data()
    await interaction.response.send_message(f"📮 Invite announcements will now be sent to {channel.mention}.",ephemeral=True)

@bot.tree.command(name="setstaffrole",description="Set staff role.")
@app_commands.checks.has_permissions(manage_guild=True)
async def set_staff_role(interaction,role: discord.Role):
    get_settings(interaction.guild.id)["staff_role"]=role.id; save_data()
    await interaction.response.send_message(f"🛡️ Staff role set to {role.mention}.",ephemeral=True)

@bot.tree.command(name="setlogchannel",description="Set moderation log channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def set_log_channel(interaction,channel: discord.TextChannel):
    get_settings(interaction.guild.id)["log_channel"]=channel.id; save_data()
    await interaction.response.send_message(f"📋 Log channel set to {channel.mention}.",ephemeral=True)

@bot.tree.command(name="setmessagelog",description="Set message log channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def set_message_log(interaction,channel: discord.TextChannel):
    get_settings(interaction.guild.id)["message_log_channel"]=channel.id; save_data()
    await interaction.response.send_message(f"💬 Message log set to {channel.mention}.",ephemeral=True)

welcome_group=app_commands.Group(name="welcome",description="Manage welcome messages.")

@welcome_group.command(name="setup",description="Set welcome channel and message.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_setup(interaction,channel: discord.TextChannel,message:str="Welcome {user} to {server}! 🛡️"):
    s=get_settings(interaction.guild.id); s["welcome_channel"]=channel.id; s["welcome_message"]=message; save_data()
    await interaction.response.send_message(f"✅ Welcome channel set to {channel.mention}.",ephemeral=True)

@welcome_group.command(name="enable",description="Enable welcome messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_enable(interaction):
    s=get_settings(interaction.guild.id)
    if not s.get("welcome_channel"):
        await interaction.response.send_message("❌ Run `/welcome setup` first.",ephemeral=True); return
    s["welcome_enabled"]=True; save_data()
    await interaction.response.send_message("🟢 Welcome messages enabled.",ephemeral=True)

@welcome_group.command(name="disable",description="Disable welcome messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def welcome_disable(interaction):
    get_settings(interaction.guild.id)["welcome_enabled"]=False; save_data()
    await interaction.response.send_message("🔴 Welcome messages disabled.",ephemeral=True)

leave_group=app_commands.Group(name="leave",description="Manage leave messages.")

@leave_group.command(name="setup",description="Set leave channel and message.")
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_setup(interaction,channel: discord.TextChannel,message:str="{user} has left {server}. 👋"):
    s=get_settings(interaction.guild.id); s["leave_channel"]=channel.id; s["leave_message"]=message; save_data()
    await interaction.response.send_message(f"✅ Leave channel set to {channel.mention}.",ephemeral=True)

@leave_group.command(name="enable",description="Enable leave messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_enable(interaction):
    s=get_settings(interaction.guild.id)
    if not s.get("leave_channel"):
        await interaction.response.send_message("❌ Run `/leave setup` first.",ephemeral=True); return
    s["leave_enabled"]=True; save_data()
    await interaction.response.send_message("🟢 Leave messages enabled.",ephemeral=True)

@leave_group.command(name="disable",description="Disable leave messages.")
@app_commands.checks.has_permissions(manage_guild=True)
async def leave_disable(interaction):
    get_settings(interaction.guild.id)["leave_enabled"]=False; save_data()
    await interaction.response.send_message("🔴 Leave messages disabled.",ephemeral=True)

@bot.tree.command(name="timeout",description="Timeout a member.")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout(interaction,member: discord.Member,minutes:int,reason:str="No reason provided"):
    if minutes<1 or minutes>40320:
        await interaction.response.send_message("❌ Choose between 1 minute and 28 days.",ephemeral=True); return
    if not await hierarchy_check(interaction,member): return
    await member.timeout(discord.utils.utcnow()+timedelta(minutes=minutes),reason=reason)
    await interaction.response.send_message(f"⏳ {member.mention} timed out for **{minutes} minutes**.")
    await send_log(interaction.guild,"Member Timed Out",f"Member: {member.mention}\nModerator: {interaction.user.mention}\nReason: {reason}",AURA_YELLOW)

@bot.tree.command(name="untimeout",description="Remove a timeout.")
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout(interaction,member: discord.Member):
    if not await hierarchy_check(interaction,member): return
    await member.timeout(None,reason=f"Timeout removed by {interaction.user}")
    await interaction.response.send_message(f"🔓 Removed {member.mention}'s timeout.")

@bot.tree.command(name="clear",description="Delete messages.")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction,amount:int):
    if amount<1 or amount>100:
        await interaction.response.send_message("❌ Choose between 1 and 100.",ephemeral=True); return
    if not isinstance(interaction.channel,discord.TextChannel):
        await interaction.response.send_message("❌ This command must be used in a text channel.",ephemeral=True); return
    perms=interaction.channel.permissions_for(interaction.guild.me)
    if not perms.read_message_history or not perms.manage_messages:
        await interaction.response.send_message("❌ I need **View Channel, Read Message History, and Manage Messages** in this channel.",ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    try:
        deleted=await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 Deleted **{len(deleted)} messages**.",ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("❌ I don't have access to delete messages in this channel.",ephemeral=True)

@bot.tree.command(name="kick",description="Kick a member.")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction,member:discord.Member,reason:str="No reason provided"):
    if not await hierarchy_check(interaction,member): return
    await member.kick(reason=reason); await interaction.response.send_message(f"👢 Kicked {member.mention}.")

@bot.tree.command(name="ban",description="Ban a member.")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction,member:discord.Member,reason:str="No reason provided"):
    if not await hierarchy_check(interaction,member): return
    await member.ban(reason=reason); await interaction.response.send_message(f"🔨 Banned {member.mention}.")

@bot.tree.command(name="unban",description="Unban a user using their ID.")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction,user_id:str):
    try:
        user=await bot.fetch_user(int(user_id)); await interaction.guild.unban(user)
        await interaction.response.send_message(f"🔓 **{user}** has been unbanned.")
    except Exception:
        await interaction.response.send_message("❌ User not found or not banned.",ephemeral=True)

@bot.tree.command(name="serverinfo",description="Show server information.")
async def serverinfo(interaction):
    g=interaction.guild
    await interaction.response.send_message(embed=aura_embed(g.name,f"👥 **Members:** {g.member_count}\n💬 **Channels:** {len(g.channels)}\n🎭 **Roles:** {len(g.roles)}\n🆔 **Server ID:** `{g.id}`","" if False else AURA_PURPLE,"🏠"))

@bot.event
async def on_member_join(member):
    s=get_settings(member.guild.id)
    if s.get("welcome_enabled"):
        ch=get_message_channel(member.guild,s.get("welcome_channel"))
        if ch:
            text=s["welcome_message"].replace("{user}",member.mention).replace("{server}",member.guild.name)
            await safe_send(ch,embed=aura_embed("Welcome!",text,AURA_PURPLE,"👋"))

@bot.event
async def on_member_remove(member):
    s=get_settings(member.guild.id)
    if s.get("leave_enabled"):
        ch=get_message_channel(member.guild,s.get("leave_channel"))
        if ch:
            text=s["leave_message"].replace("{user}",member.mention).replace("{server}",member.guild.name)
            await safe_send(ch,embed=aura_embed("Member Left",text,AURA_YELLOW,"🚪"))


# -------------------- MISSING FULL V8 FEATURES --------------------

def clean_message_content(content):
    return discord.utils.escape_markdown(content or "*No text content*")[:3500]

def apply_placeholders(text, member):
    return (text.replace("{user}", member.mention)
                .replace("{server}", member.guild.name)
                .replace("{member_count}", str(member.guild.member_count)))

def is_staff(member):
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    role_id=get_settings(member.guild.id).get("staff_role")
    role=member.guild.get_role(int(role_id)) if role_id else None
    return bool(role and role in member.roles)

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open Ticket",style=discord.ButtonStyle.primary,emoji="🎫",
                       custom_id="auraguard_open_ticket")
    async def open_ticket(self, interaction, button):
        guild=interaction.guild; user=interaction.user
        for ch in guild.text_channels:
            if ch.topic == f"AURAGUARD_TICKET_OWNER={user.id}":
                await interaction.response.send_message(f"🎫 You already have a ticket: {ch.mention}",ephemeral=True)
                return
        settings=get_settings(guild.id)
        overwrites={guild.default_role:discord.PermissionOverwrite(view_channel=False),
                    user:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)}
        role_id=settings.get("staff_role")
        role=guild.get_role(int(role_id)) if role_id else None
        if role:
            overwrites[role]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)
        cat_id=settings.get("ticket_category")
        category=guild.get_channel(int(cat_id)) if cat_id else None
        channel=await guild.create_text_channel(
            f"ticket-{user.name}".lower().replace(" ","-")[:90],
            category=category if isinstance(category,discord.CategoryChannel) else None,
            overwrites=overwrites,topic=f"AURAGUARD_TICKET_OWNER={user.id}",
            reason="AuraGuard ticket opened")
        await safe_send(channel,content=user.mention,
            embed=aura_embed("Ticket Opened","A staff member will help you soon.\n\nUse the buttons below."),
            view=TicketControls())
        await interaction.response.send_message(f"🎫 Your ticket: {channel.mention}",ephemeral=True)
        await send_log(guild,"Ticket Opened",f"User: {user.mention}\nChannel: {channel.mention}",AURA_BLUE)

class TicketControls(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="Claim",style=discord.ButtonStyle.success,emoji="🙋",
                       custom_id="auraguard_claim_ticket")
    async def claim(self,interaction,button):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Only staff can claim tickets.",ephemeral=True); return
        cid=str(interaction.channel.id); current=data["ticket_claims"].get(cid)
        if current and current!=interaction.user.id:
            await interaction.response.send_message(f"❌ Already claimed by <@{current}>.",ephemeral=True); return
        data["ticket_claims"][cid]=interaction.user.id; save_data()
        await interaction.response.send_message(f"🙋 Ticket claimed by {interaction.user.mention}.")

    @discord.ui.button(label="Transcript",style=discord.ButtonStyle.secondary,emoji="📄",
                       custom_id="auraguard_transcript")
    async def transcript(self,interaction,button):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Only staff can create transcripts.",ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        lines=[]
        async for msg in interaction.channel.history(oldest_first=True,limit=None):
            lines.append(f"[{msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {msg.author}: {msg.content or '[No text content]'}")
        file=discord.File(io.BytesIO("\n".join(lines).encode("utf-8")),
                          filename=f"{interaction.channel.name}-transcript.txt")
        await interaction.followup.send("📄 Transcript created.",file=file,ephemeral=True)

    @discord.ui.button(label="Close",style=discord.ButtonStyle.danger,emoji="🔒",
                       custom_id="auraguard_close_ticket")
    async def close(self,interaction,button):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Only staff can close tickets.",ephemeral=True); return
        await interaction.response.send_message("🔒 Closing ticket in **3 seconds**...")
        await asyncio.sleep(3)
        data["ticket_claims"].pop(str(interaction.channel.id),None); save_data()
        await interaction.channel.delete(reason="AuraGuard ticket closed")

tickets_group=app_commands.Group(name="tickets",description="Manage AuraGuard tickets.")

@tickets_group.command(name="setup",description="Set ticket category.")
@app_commands.checks.has_permissions(manage_guild=True)
async def tickets_setup(interaction,category:discord.CategoryChannel):
    get_settings(interaction.guild.id)["ticket_category"]=category.id; save_data()
    await interaction.response.send_message(f"🎫 Ticket category set to **{category.name}**.",ephemeral=True)

@tickets_group.command(name="panel",description="Send ticket panel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def tickets_panel(interaction):
    await interaction.response.send_message(
        embed=aura_embed("AuraGuard Support","Need help?\n\nClick the button below to open a ticket.",AURA_PURPLE,"🎫"),
        view=TicketView())

automod_group=app_commands.Group(name="automod",description="Manage AuraGuard AutoMod.")

@automod_group.command(name="enable",description="Enable blocked-word AutoMod.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_enable(interaction):
    get_automod(interaction.guild.id)["enabled"]=True; save_data()
    await interaction.response.send_message("🛡️ AutoMod enabled.",ephemeral=True)

@automod_group.command(name="disable",description="Disable blocked-word AutoMod.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_disable(interaction):
    get_automod(interaction.guild.id)["enabled"]=False; save_data()
    await interaction.response.send_message("🔴 AutoMod disabled.",ephemeral=True)

@automod_group.command(name="addword",description="Add blocked word.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_addword(interaction,word:str):
    a=get_automod(interaction.guild.id); word=word.strip()
    if not word: await interaction.response.send_message("❌ Invalid word.",ephemeral=True); return
    if word.lower() in [x.lower() for x in a["blocked_words"]]:
        await interaction.response.send_message("❌ That word is already blocked.",ephemeral=True); return
    a["blocked_words"].append(word); save_data()
    await interaction.response.send_message(f"🛡️ Added `{word}`.",ephemeral=True)

@automod_group.command(name="removeword",description="Remove blocked word.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_removeword(interaction,word:str):
    a=get_automod(interaction.guild.id)
    match=next((x for x in a["blocked_words"] if x.lower()==word.lower()),None)
    if not match: await interaction.response.send_message("❌ That word is not blocked.",ephemeral=True); return
    a["blocked_words"].remove(match); save_data()
    await interaction.response.send_message(f"✅ Removed `{match}`.",ephemeral=True)

@automod_group.command(name="antispam",description="Enable or disable anti-spam.")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod_antispam(interaction,enabled:bool):
    get_automod(interaction.guild.id)["anti_spam"]=enabled; save_data()
    await interaction.response.send_message(f"🚨 Anti-spam {'enabled' if enabled else 'disabled'}.",ephemeral=True)

@bot.tree.command(name="warn",description="Warn a member.")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction,member:discord.Member,reason:str="No reason provided"):
    if not await hierarchy_check(interaction,member): return
    lst=data["warnings"].setdefault(str(interaction.guild.id),{}).setdefault(str(member.id),[])
    lst.append({"reason":reason,"moderator":interaction.user.id,"time":datetime.now(timezone.utc).isoformat()}); save_data()
    await interaction.response.send_message(f"⚠️ Warned {member.mention}.\nTotal warnings: **{len(lst)}**")
    await send_log(interaction.guild,"Member Warned",f"Member: {member.mention}\nModerator: {interaction.user.mention}\nReason: {reason}",AURA_YELLOW)

@bot.tree.command(name="warnings",description="View member warnings.")
@app_commands.checks.has_permissions(moderate_members=True)
async def warnings(interaction,member:discord.Member):
    lst=data["warnings"].get(str(interaction.guild.id),{}).get(str(member.id),[])
    if not lst: await interaction.response.send_message(f"✅ {member.mention} has no warnings.",ephemeral=True); return
    lines=[f"**{i}.** {w['reason']} — <@{w['moderator']}>" for i,w in enumerate(lst,1)]
    await interaction.response.send_message(embed=aura_embed(f"Warnings • {member}","\n".join(lines)[:4000],AURA_YELLOW,"⚠️"),ephemeral=True)

@bot.tree.command(name="clearwarnings",description="Clear all warnings.")
@app_commands.checks.has_permissions(moderate_members=True)
async def clearwarnings(interaction,member:discord.Member):
    gw=data["warnings"].setdefault(str(interaction.guild.id),{})
    count=len(gw.get(str(member.id),[])); gw[str(member.id)]=[]; save_data()
    await interaction.response.send_message(f"🗑️ Cleared **{count}** warnings from {member.mention}.")

@bot.tree.command(name="lock",description="Lock a text channel.")
@app_commands.checks.has_permissions(manage_channels=True)
async def lock(interaction,channel:discord.TextChannel=None):
    target=channel or interaction.channel
    if not isinstance(target,discord.TextChannel):
        await interaction.response.send_message("❌ Text channels only.",ephemeral=True); return
    await target.set_permissions(interaction.guild.default_role,send_messages=False)
    await interaction.response.send_message(f"🔒 {target.mention} locked.")

@bot.tree.command(name="unlock",description="Unlock a text channel.")
@app_commands.checks.has_permissions(manage_channels=True)
async def unlock(interaction,channel:discord.TextChannel=None):
    target=channel or interaction.channel
    if not isinstance(target,discord.TextChannel):
        await interaction.response.send_message("❌ Text channels only.",ephemeral=True); return
    await target.set_permissions(interaction.guild.default_role,send_messages=None)
    await interaction.response.send_message(f"🔓 {target.mention} unlocked.")

@bot.tree.command(name="userinfo",description="Show member information.")
async def userinfo(interaction,member:discord.Member=None):
    member=member or interaction.user
    joined=f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "Unknown"
    e=aura_embed("User Information",f"👤 **User:** {member.mention}\n🆔 **ID:** `{member.id}`\n📅 **Joined Discord:** <t:{int(member.created_at.timestamp())}:R>\n📥 **Joined Server:** {joined}",AURA_PURPLE,"👤")
    e.set_thumbnail(url=member.display_avatar.url)
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="invites",description="Check invite count.")
async def invites(interaction,member:discord.Member=None):
    member=member or interaction.user; u=get_invite_data(interaction.guild.id).get(str(member.id),{})
    await interaction.response.send_message(embed=aura_embed("Invite Information",f"👤 **Member:** {member.mention}\n📨 **Total Invites:** **{u.get('total',0)}**\n✅ **Regular Invites:** **{u.get('regular',0)}**",AURA_PURPLE,"📨"))

@bot.tree.command(name="inviteleaderboard",description="Show invite leaderboard.")
async def inviteleaderboard(interaction):
    items=sorted(get_invite_data(interaction.guild.id).items(),key=lambda x:x[1].get("total",0),reverse=True)
    if not items: await interaction.response.send_message(embed=aura_embed("Invite Leaderboard","No invite data has been recorded yet.",AURA_PURPLE,"🏆")); return
    lines=[f"**{i}.** <@{uid}> — **{u.get('total',0)} invites**" for i,(uid,u) in enumerate(items[:10],1)]
    await interaction.response.send_message(embed=aura_embed("Invite Leaderboard","\n".join(lines),AURA_PURPLE,"🏆"))

@bot.tree.command(name="help",description="Show AuraGuard commands.")
async def help_command(interaction):
    text="""**👋 Welcome** `/welcome setup` `/welcome enable` `/welcome disable`
**🚪 Leave** `/leave setup` `/leave enable` `/leave disable`
**🎫 Tickets** `/tickets setup` `/tickets panel`
**📮 Invites** `/setinvitechannel` `/invites` `/inviteleaderboard`
**🛡️ Moderation** `/kick` `/ban` `/unban` `/timeout` `/untimeout` `/warn` `/warnings` `/clearwarnings`
**🧹 Channels** `/clear` `/lock` `/unlock`
**🤖 AutoMod** `/automod enable` `/automod disable` `/automod addword` `/automod removeword` `/automod antispam`
**⚙️ Settings** `/setstaffrole` `/setlogchannel` `/setmessagelog`
**ℹ️ Info** `/serverinfo` `/userinfo` `/ping`"""
    await interaction.response.send_message(embed=aura_embed("AuraGuard V8 Commands",text,AURA_PURPLE,"🛡️"),ephemeral=True)

# Message logging and AutoMod events
message_cache=defaultdict(deque)

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    a=get_automod(message.guild.id)
    if a.get("anti_spam"):
        key=(message.guild.id,message.author.id); now=datetime.now(timezone.utc).timestamp(); q=message_cache[key]; q.append(now)
        while q and now-q[0]>a.get("spam_seconds",5): q.popleft()
        if len(q)>=a.get("spam_limit",6):
            try: await message.delete()
            except Exception: pass
            await safe_send(message.channel,f"🚨 {message.author.mention}, please slow down.",delete_after=5); q.clear(); return
    if a.get("enabled"):
        lower=message.content.lower()
        if any(word.lower() in lower for word in a.get("blocked_words",[])):
            try: await message.delete()
            except Exception: pass
            await safe_send(message.channel,f"⚠️ {message.author.mention}, that message contains a blocked word.",delete_after=5); return
    await send_message_log(message.guild,"Message Sent",f"**Author:** {message.author.mention}\n**Channel:** {message.channel.mention}\n\n**Message:**\n{clean_message_content(message.content)}")
    await bot.process_commands(message)

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild: return
    await send_message_log(message.guild,"Message Deleted",f"**Author:** {message.author.mention}\n**Channel:** {message.channel.mention}\n\n**Deleted Message:**\n{clean_message_content(message.content)}",AURA_RED)

@bot.event
async def on_message_edit(before,after):
    if before.author.bot or not before.guild or before.content==after.content: return
    await send_message_log(before.guild,"Message Edited",f"**Author:** {before.author.mention}\n**Channel:** {before.channel.mention}\n\n**Before:**\n{clean_message_content(before.content)}\n\n**After:**\n{clean_message_content(after.content)}",AURA_YELLOW)


for group in [welcome_group, leave_group, tickets_group, automod_group]:
    bot.tree.add_command(group)
@bot.tree.error
async def on_app_command_error(interaction,error):
    print("Command error:",repr(error))
    if isinstance(error,app_commands.MissingPermissions):
        msg="❌ You don't have permission to use that command."
    elif isinstance(error,app_commands.BotMissingPermissions):
        msg="❌ I don't have the required Discord permissions."
    elif isinstance(error,app_commands.TransformerError):
        msg="❌ Please select a valid option from Discord's command menu."
    else:
        msg="❌ Something went wrong while running that command."
    try:
        if interaction.response.is_done(): await interaction.followup.send(msg,ephemeral=True)
        else: await interaction.response.send_message(msg,ephemeral=True)
    except Exception: pass

@bot.event
async def on_ready():
    print("="*45)
    print(f"AuraGuard V8 Fixed online as {bot.user}")
    print(f"Bot ID: {bot.user.id}")
    print("="*45)
    await bot.change_presence(status=discord.Status.online,activity=discord.Activity(type=discord.ActivityType.watching,name="over your server 🛡️"))
    if not getattr(bot,"_auraguard_views_loaded",False):
        bot.add_view(TicketView())
        bot.add_view(TicketControls())
        bot._auraguard_views_loaded=True
    try:
        synced=await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e: print("Slash command sync error:",repr(e))

bot.run(TOKEN)
