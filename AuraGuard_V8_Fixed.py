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

for group in [welcome_group,leave_group]:
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
    try:
        synced=await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e: print("Slash command sync error:",repr(e))

bot.run(TOKEN)
