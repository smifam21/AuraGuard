# AuraGuard V9 - Complete V8 + Advanced Giveaways
import discord, os, json, random, asyncio, io
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from PIL import Image, ImageDraw, ImageFont

TOKEN=os.getenv("DISCORD_TOKEN"); DATA_FILE="auraguard_data.json"
PURPLE=0x8A2BE2; GREEN=0x2ECC71; RED=0xE74C3C; YELLOW=0xF1C40F; BLUE=0x3498DB
if not TOKEN: raise RuntimeError("DISCORD_TOKEN is missing from Railway Variables.")
intents=discord.Intents.default(); intents.guilds=True; intents.members=True; intents.message_content=True; intents.invites=True
bot=commands.Bot(command_prefix="!",intents=intents,help_command=None)
DEFAULT={"settings":{},"warnings":{},"giveaways":{},"giveaway_entries":{},"giveaway_history":{},"giveaway_blacklist":{},"ticket_claims":{},"automod":{},"invites":{},"member_invites":{}}

def load():
    try:
        with open(DATA_FILE,encoding="utf8") as f:d=json.load(f)
    except:d={}
    for k,v in DEFAULT.items():d.setdefault(k,v)
    return d
data=load()
def save():
    with open(DATA_FILE+".tmp","w",encoding="utf8") as f:json.dump(data,f,indent=2)
    os.replace(DATA_FILE+".tmp",DATA_FILE)
def settings(gid):
    x=data["settings"].setdefault(str(gid),{})
    defaults={"welcome_enabled":False,"welcome_channel":None,"welcome_message":"Welcome {user} to {server}! 🛡️","welcome_image_enabled":True,"leave_enabled":False,"leave_channel":None,"leave_message":"{user} has left {server}. 👋","ticket_category":None,"staff_role":None,"log_channel":None,"message_log_channel":None,"invite_channel":None,"giveaway_bonus_roles":{}}
    for k,v in defaults.items():x.setdefault(k,v)
    return x
def embed(title,desc="",color=PURPLE,emoji="🛡️"):
    e=discord.Embed(title=f"{emoji} {title}",description=desc,color=color,timestamp=datetime.now(timezone.utc));e.set_footer(text="AuraGuard • Powered by Aura");return e
def staff(m):
    if m.guild_permissions.administrator or m.guild_permissions.manage_guild:return True
    rid=settings(m.guild.id).get("staff_role"); r=m.guild.get_role(int(rid)) if rid else None
    return bool(r and r in m.roles)
def invdata(gid):return data["invites"].setdefault(str(gid),{})
def record(gid,uid):return invdata(gid).setdefault(str(uid),{"total":0,"regular":0,"bonus":0,"fake":0,"left":0})
def memberinv(gid):return data["member_invites"].setdefault(str(gid),{})
def automod(gid):return data["automod"].setdefault(str(gid),{"enabled":False,"blocked_words":[]})
def blacklist(gid):return data["giveaway_blacklist"].setdefault(str(gid),[])
async def textchannel(guild,cid):
    try:
        c=guild.get_channel(int(cid))
        return c if isinstance(c,discord.TextChannel) else None
    except:return None
async def category(guild,cid):
    try:
        c=guild.get_channel(int(cid));return c if isinstance(c,discord.CategoryChannel) else None
    except:return None
async def log(g,t,d,c=PURPLE):
    ch=await textchannel(g,settings(g.id).get("log_channel"))
    if ch:
        try:await ch.send(embed=embed(t,d,c,"📋"))
        except:pass
async def mlog(g,t,d,c=BLUE):
    ch=await textchannel(g,settings(g.id).get("message_log_channel"))
    if ch:
        try:await ch.send(embed=embed(t,d[:4000],c,"💬"))
        except:pass

# WELCOME
async def card(member):
    im=Image.new("RGB",(1000,360),(18,8,32));dr=ImageDraw.Draw(im)
    dr.ellipse((650,-100,1150,400),fill=(85,25,145));dr.rounded_rectangle((20,20,980,340),30,outline=(170,90,255),width=5)
    av=Image.open(io.BytesIO(await member.display_avatar.read())).convert("RGB").resize((190,190));mask=Image.new("L",(190,190),0);ImageDraw.Draw(mask).ellipse((0,0,189,189),fill=255);im.paste(av,(70,85),mask)
    def font(n,b=False):
        try:return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if b else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",n)
        except:return ImageFont.load_default()
    dr.text((300,70),"WELCOME TO",font=font(38,True),fill=(190,145,255));dr.text((300,125),member.display_name[:22],font=font(56,True),fill="white");dr.text((302,210),member.guild.name[:35],font=font(30),fill=(225,215,240));dr.text((302,265),f"Member #{member.guild.member_count}",font=font(26),fill=(190,145,255))
    out=io.BytesIO();im.save(out,"PNG");out.seek(0);return discord.File(out,filename="auraguard-welcome.png")
async def welcome(member,ch,inviter=None):
    s=settings(member.guild.id);d=s["welcome_message"].replace("{user}",member.mention).replace("{server}",member.guild.name).replace("{member_count}",str(member.guild.member_count))
    if inviter:d+=f"\n\n📨 **Invited by:** {inviter.mention}"
    e=embed("Welcome!",d,PURPLE,"👋")
    if s["welcome_image_enabled"]:
        f=await card(member);e.set_image(url="attachment://auraguard-welcome.png");await ch.send(embed=e,file=f)
    else:await ch.send(embed=e)

# TICKETS
class TicketPanel(discord.ui.View):
    def __init__(self):super().__init__(timeout=None)
    @discord.ui.button(label="Open Ticket",style=discord.ButtonStyle.primary,emoji="🎫",custom_id="ag_open")
    async def open(self,i,b):
        g=i.guild;u=i.user
        for c in g.text_channels:
            if c.topic==f"AG_OWNER={u.id}":await i.response.send_message(f"🎫 You already have {c.mention}",ephemeral=True);return
        ow={g.default_role:discord.PermissionOverwrite(view_channel=False),u:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)}
        rid=settings(g.id).get("staff_role");r=g.get_role(int(rid)) if rid else None
        if r:ow[r]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)
        cat=await category(g,settings(g.id).get("ticket_category"));name="".join(x for x in u.name.lower() if x.isalnum() or x=="-")[:70]
        c=await g.create_text_channel(f"ticket-{name}",category=cat,overwrites=ow,topic=f"AG_OWNER={u.id}")
        await c.send(u.mention,embed=embed("Ticket Opened","A staff member will help you soon.",PURPLE,"🎫"),view=TicketControls());await i.response.send_message(f"🎫 Your ticket: {c.mention}",ephemeral=True)
class TicketControls(discord.ui.View):
    def __init__(self):super().__init__(timeout=None)
    @discord.ui.button(label="Claim",style=discord.ButtonStyle.success,emoji="🙋",custom_id="ag_claim")
    async def claim(self,i,b):
        if not staff(i.user):await i.response.send_message("❌ Staff only.",ephemeral=True);return
        cid=str(i.channel.id);cur=data["ticket_claims"].get(cid)
        if cur and cur!=i.user.id:await i.response.send_message(f"❌ Already claimed by <@{cur}>.",ephemeral=True);return
        data["ticket_claims"][cid]=i.user.id;save();await i.response.send_message(f"🙋 Claimed by {i.user.mention}.")
    @discord.ui.button(label="Close",style=discord.ButtonStyle.danger,emoji="🔒",custom_id="ag_close")
    async def close(self,i,b):
        if not staff(i.user):await i.response.send_message("❌ Staff only.",ephemeral=True);return
        await i.response.send_message("🔒 Closing...");data["ticket_claims"].pop(str(i.channel.id),None);save();await asyncio.sleep(1);await i.channel.delete()

# ADVANCED GIVEAWAYS
def gid():
    while True:
        x=str(random.randint(100000,999999))
        if x not in data["giveaways"] and x not in data["giveaway_history"]:return x
def entries(x):return data["giveaway_entries"].setdefault(x,{})
def winners(pool,n):
    p={str(k):max(0,int(v)) for k,v in pool.items() if int(v)>0};out=[]
    while p and len(out)<n:
        u=random.choices(list(p),weights=list(p.values()))[0];out.append(u);p.pop(u)
    return out
def bonus(member):
    roles=settings(member.guild.id)["giveaway_bonus_roles"];return sum(max(0,int(roles.get(str(r.id),0))) for r in member.roles)
def gwembed(x,g):
    en=entries(x);end=datetime.fromisoformat(g["end_time"]);req=f"<@&{g['required_role']}>" if g.get("required_role") else "None"
    return embed("GIVEAWAY",f"╭─ 🎁 **Prize:** {g['prize']}\n├─ 🏆 **Winners:** {g['winners']}\n├─ 👥 **Participants:** {len(en)}\n├─ 🎟️ **Total Entries:** {sum(map(int,en.values()))}\n├─ 🔐 **Required Role:** {req}\n├─ 👤 **Hosted by:** <@{g['created_by']}>\n├─ ⏰ **Ends:** <t:{int(end.timestamp())}:R>\n╰─ 🆔 **ID:** `{x}`\n\n🎉 **Click Enter Giveaway to participate!**",PURPLE,"🎉")
class GiveawayView(discord.ui.View):
    def __init__(self,x):
        super().__init__(timeout=None);self.x=x
        a=discord.ui.Button(label="Enter Giveaway",emoji="🎉",style=discord.ButtonStyle.success,custom_id=f"ag_gwe_{x}");a.callback=self.enter;self.add_item(a)
        b=discord.ui.Button(label="My Entries",emoji="🎟️",style=discord.ButtonStyle.primary,custom_id=f"ag_gwm_{x}");b.callback=self.mine;self.add_item(b)
    async def enter(self,i):
        g=data["giveaways"].get(self.x)
        if not g:await i.response.send_message("❌ This giveaway is no longer active.",ephemeral=True);return
        if str(i.user.id) in blacklist(i.guild.id):await i.response.send_message("🚫 You are giveaway blacklisted.",ephemeral=True);return
        rr=g.get("required_role")
        if rr:
            r=i.guild.get_role(int(rr))
            if r and r not in i.user.roles:await i.response.send_message(f"🔐 You need {r.mention}.",ephemeral=True);return
        e=entries(self.x);u=str(i.user.id)
        if u in e:await i.response.send_message(f"❌ Already entered with **{e[u]} entries**.",ephemeral=True);return
        e[u]=1+bonus(i.user);save();await i.response.send_message(f"🎉 Entered with **{e[u]} entries**!",ephemeral=True)
    async def mine(self,i):await i.response.send_message(f"🎟️ You have **{entries(self.x).get(str(i.user.id),0)} entries**.",ephemeral=True)
async def finish(guild,ch,x):
    g=data["giveaways"].get(x)
    if not g:return
    e=entries(x);ws=winners(e,g["winners"]);h=dict(g);h.update({"entries":dict(e),"winners_list":ws,"ended_at":datetime.now(timezone.utc).isoformat()})
    data["giveaway_history"][x]=h;data["giveaways"].pop(x,None);data["giveaway_entries"].pop(x,None);save()
    if ch:
        if ws:await ch.send(embed=embed("Giveaway Winner!",f"🎉 Congratulations {' '.join(f'<@{u}>' for u in ws)}!\n\n🎁 **Prize:** {h['prize']}",GREEN,"🏆"))
        else:await ch.send(embed=embed("Giveaway Ended",f"🎁 **Prize:** {h['prize']}\n\nNobody entered.",YELLOW,"🎉"))

wg=app_commands.Group(name="welcome",description="Manage welcome messages.")
lg=app_commands.Group(name="leave",description="Manage leave messages.")
tg=app_commands.Group(name="tickets",description="Manage tickets.")
gg=app_commands.Group(name="giveaway",description="Advanced AuraGuard giveaways.")
ag=app_commands.Group(name="automod",description="Manage AutoMod.")

@wg.command(name="setup",description="Set welcome channel and message.")
@app_commands.checks.has_permissions(manage_guild=True)
async def ws(i,ch:discord.TextChannel,message:str="Welcome {user} to {server}! 🛡️"):settings(i.guild.id).update({"welcome_channel":ch.id,"welcome_message":message});save();await i.response.send_message(f"✅ Welcome channel: {ch.mention}",ephemeral=True)
@wg.command(name="enable",description="Enable welcome.")
@app_commands.checks.has_permissions(manage_guild=True)
async def we(i):settings(i.guild.id)["welcome_enabled"]=True;save();await i.response.send_message("🟢 Welcome enabled.",ephemeral=True)
@wg.command(name="disable",description="Disable welcome.")
@app_commands.checks.has_permissions(manage_guild=True)
async def wd(i):settings(i.guild.id)["welcome_enabled"]=False;save();await i.response.send_message("🔴 Welcome disabled.",ephemeral=True)
@wg.command(name="image",description="Enable or disable welcome card.")
@app_commands.checks.has_permissions(manage_guild=True)
async def wi(i,enabled:bool):settings(i.guild.id)["welcome_image_enabled"]=enabled;save();await i.response.send_message(f"🖼️ Image {'enabled' if enabled else 'disabled'}.",ephemeral=True)
@wg.command(name="test",description="Test welcome.")
@app_commands.checks.has_permissions(manage_guild=True)
async def wt(i):
    ch=await textchannel(i.guild,settings(i.guild.id).get("welcome_channel"))
    if not ch:await i.response.send_message("❌ Run `/welcome setup` first.",ephemeral=True);return
    await i.response.defer(ephemeral=True);await welcome(i.user,ch);await i.followup.send("✅ Test sent.",ephemeral=True)

@lg.command(name="setup",description="Set leave channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def ls(i,ch:discord.TextChannel,message:str="{user} has left {server}. 👋"):settings(i.guild.id).update({"leave_channel":ch.id,"leave_message":message});save();await i.response.send_message(f"✅ Leave channel: {ch.mention}",ephemeral=True)
@lg.command(name="enable",description="Enable leave.")
@app_commands.checks.has_permissions(manage_guild=True)
async def le(i):settings(i.guild.id)["leave_enabled"]=True;save();await i.response.send_message("🟢 Leave enabled.",ephemeral=True)
@lg.command(name="disable",description="Disable leave.")
@app_commands.checks.has_permissions(manage_guild=True)
async def ld(i):settings(i.guild.id)["leave_enabled"]=False;save();await i.response.send_message("🔴 Leave disabled.",ephemeral=True)

@tg.command(name="setup",description="Set ticket category.")
@app_commands.checks.has_permissions(manage_guild=True)
async def ts(i,cat:discord.CategoryChannel):settings(i.guild.id)["ticket_category"]=cat.id;save();await i.response.send_message(f"🎫 Category set to **{cat.name}**.",ephemeral=True)
@tg.command(name="panel",description="Send ticket panel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def tp(i):await i.response.send_message(embed=embed("AuraGuard Support","Need help? Click below to open a ticket.",PURPLE,"🎫"),view=TicketPanel())

@gg.command(name="start",description="Start an advanced giveaway.")
@app_commands.checks.has_permissions(manage_guild=True)
async def gs(i,prize:str,minutes:int,winner_count:int=1,required_role:discord.Role=None):
    if minutes<1 or winner_count<1:await i.response.send_message("❌ Minutes and winners must be at least 1.",ephemeral=True);return
    x=gid();data["giveaways"][x]={"guild":i.guild.id,"channel":i.channel.id,"prize":prize,"winners":winner_count,"end_time":(datetime.now(timezone.utc)+timedelta(minutes=minutes)).isoformat(),"created_by":i.user.id,"required_role":required_role.id if required_role else None};entries(x);save();await i.response.send_message(embed=gwembed(x,data["giveaways"][x]),view=GiveawayView(x))
@gg.command(name="entries",description="Check giveaway entries.")
async def ge(i,giveaway_id:str):await i.response.send_message(f"🎟️ You have **{entries(giveaway_id).get(str(i.user.id),0)} entries**.",ephemeral=True)
@gg.command(name="addentries",description="Add giveaway entries.")
@app_commands.checks.has_permissions(manage_guild=True)
async def gae(i,giveaway_id:str,member:discord.Member,amount:int):
    if giveaway_id not in data["giveaways"] or amount<1:await i.response.send_message("❌ Invalid giveaway or amount.",ephemeral=True);return
    e=entries(giveaway_id);u=str(member.id);e[u]=e.get(u,0)+amount;save();await i.response.send_message(f"➕ {member.mention}: **{e[u]} entries**.",ephemeral=True)
@gg.command(name="removeentries",description="Remove giveaway entries.")
@app_commands.checks.has_permissions(manage_guild=True)
async def gre(i,giveaway_id:str,member:discord.Member,amount:int):
    if giveaway_id not in data["giveaways"] or amount<1:await i.response.send_message("❌ Invalid giveaway or amount.",ephemeral=True);return
    e=entries(giveaway_id);u=str(member.id);e[u]=max(0,e.get(u,0)-amount)
    if not e[u]:e.pop(u,None)
    save();await i.response.send_message(f"➖ Removed **{amount} entries**.",ephemeral=True)
@gg.command(name="bonusrole",description="Set bonus entries for a role.")
@app_commands.checks.has_permissions(manage_guild=True)
async def gbr(i,role:discord.Role,amount:int):
    if amount<0:await i.response.send_message("❌ Amount cannot be negative.",ephemeral=True);return
    settings(i.guild.id)["giveaway_bonus_roles"][str(role.id)]=amount;save();await i.response.send_message(f"🎟️ {role.mention}: **+{amount} entries**.",ephemeral=True)
@gg.command(name="removebonusrole",description="Remove giveaway bonus role.")
@app_commands.checks.has_permissions(manage_guild=True)
async def grbr(i,role:discord.Role):settings(i.guild.id)["giveaway_bonus_roles"].pop(str(role.id),None);save();await i.response.send_message("✅ Bonus role removed.",ephemeral=True)
@gg.command(name="bonusroles",description="Show bonus roles.")
async def gbrl(i):
    r=settings(i.guild.id)["giveaway_bonus_roles"];d="\n".join(f"<@&{k}> — **+{v} entries**" for k,v in r.items()) or "No bonus roles configured.";await i.response.send_message(embed=embed("Bonus Roles",d,PURPLE,"🎟️"),ephemeral=True)
@gg.command(name="blacklist",description="Blacklist member from giveaways.")
@app_commands.checks.has_permissions(manage_guild=True)
async def gbl(i,member:discord.Member):
    b=blacklist(i.guild.id)
    if str(member.id) not in b:b.append(str(member.id));save()
    await i.response.send_message(f"🚫 {member.mention} blacklisted.",ephemeral=True)
@gg.command(name="unblacklist",description="Remove giveaway blacklist.")
@app_commands.checks.has_permissions(manage_guild=True)
async def gubl(i,member:discord.Member):
    b=blacklist(i.guild.id)
    if str(member.id) in b:b.remove(str(member.id));save()
    await i.response.send_message(f"✅ {member.mention} unblacklisted.",ephemeral=True)
@gg.command(name="list",description="Show active giveaways.")
async def glist(i):
    a=[(x,g) for x,g in data["giveaways"].items() if g["guild"]==i.guild.id];d="\n\n".join(f"🎁 `{x}` — **{g['prize']}**\n└ <t:{int(datetime.fromisoformat(g['end_time']).timestamp())}:R>" for x,g in a) or "No active giveaways.";await i.response.send_message(embed=embed("Active Giveaways",d,PURPLE,"📋"),ephemeral=True)
@gg.command(name="end",description="End giveaway early.")
@app_commands.checks.has_permissions(manage_guild=True)
async def gend(i,giveaway_id:str):
    g=data["giveaways"].get(giveaway_id)
    if not g or g["guild"]!=i.guild.id:await i.response.send_message("❌ Giveaway not found.",ephemeral=True);return
    await i.response.defer(ephemeral=True);await finish(i.guild,await textchannel(i.guild,g["channel"]),giveaway_id);await i.followup.send("✅ Giveaway ended.",ephemeral=True)
@gg.command(name="reroll",description="Reroll a finished giveaway.")
@app_commands.checks.has_permissions(manage_guild=True)
async def greroll(i,giveaway_id:str,winner_count:int=1):
    h=data["giveaway_history"].get(giveaway_id)
    if not h or h["guild"]!=i.guild.id:await i.response.send_message("❌ Finished giveaway not found.",ephemeral=True);return
    ws=winners(h["entries"],winner_count);h.setdefault("rerolls",[]).append({"winners":ws,"at":datetime.now(timezone.utc).isoformat()});h["winners_list"]=ws;save();await i.response.send_message(embed=embed("Giveaway Rerolled!",f"🎁 **Prize:** {h['prize']}\n🏆 **New Winners:** {' '.join(f'<@{u}>' for u in ws) or 'Nobody'}",GREEN,"🔄"))

# INVITES
@bot.tree.command(name="setinvitechannel",description="Set invite notification channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def sic(i,ch:discord.TextChannel):settings(i.guild.id)["invite_channel"]=ch.id;save();await i.response.send_message(f"📨 Invite channel: {ch.mention}",ephemeral=True)
@bot.tree.command(name="invites",description="Check invite information.")
async def inv(i,member:discord.Member=None):
    m=member or i.user;d=invdata(i.guild.id).get(str(m.id),{"total":0,"regular":0,"bonus":0,"left":0});await i.response.send_message(embed=embed("Invite Information",f"👤 **Member:** {m.mention}\n📨 **Total:** **{d.get('total',0)}**\n✅ **Regular:** **{d.get('regular',0)}**\n➕ **Bonus:** **{d.get('bonus',0)}**\n👋 **Left:** **{d.get('left',0)}**",PURPLE,"📨"))
@bot.tree.command(name="inviteleaderboard",description="Show invite leaderboard.")
async def il(i):
    a=sorted(invdata(i.guild.id).items(),key=lambda z:z[1].get("total",0),reverse=True);d="\n".join(f"**{n}.** <@{u}> — **{v.get('total',0)} invites**" for n,(u,v) in enumerate(a[:10],1)) or "No invite data.";await i.response.send_message(embed=embed("Invite Leaderboard",d,PURPLE,"🏆"))
@bot.tree.command(name="setinvite",description="Set member invite amount.")
@app_commands.checks.has_permissions(manage_guild=True)
async def si(i,member:discord.Member,amount:int):d=record(i.guild.id,member.id);d["total"]=max(0,amount);save();await i.response.send_message(f"📨 {member.mention}: **{d['total']} invites**.",ephemeral=True)
@bot.tree.command(name="addinvites",description="Add invites.")
@app_commands.checks.has_permissions(manage_guild=True)
async def ai(i,member:discord.Member,amount:int):
    if amount<1:await i.response.send_message("❌ Amount must be at least 1.",ephemeral=True);return
    d=record(i.guild.id,member.id);d["total"]+=amount;d["bonus"]+=amount;save();await i.response.send_message(f"➕ {member.mention}: **{d['total']} invites**.")
@bot.tree.command(name="removeinvites",description="Remove invites.")
@app_commands.checks.has_permissions(manage_guild=True)
async def ri(i,member:discord.Member,amount:int):d=record(i.guild.id,member.id);d["total"]=max(0,d["total"]-max(0,amount));save();await i.response.send_message(f"➖ {member.mention}: **{d['total']} invites**.")
@bot.tree.command(name="resetinvites",description="Reset member invites.")
@app_commands.checks.has_permissions(manage_guild=True)
async def reset(i,member:discord.Member):invdata(i.guild.id)[str(member.id)]={"total":0,"regular":0,"bonus":0,"fake":0,"left":0};save();await i.response.send_message(f"🔄 Reset {member.mention}.")

# SETTINGS + AUTOMOD + MODERATION
@bot.tree.command(name="ping",description="Check AuraGuard latency.")
async def ping(i):await i.response.send_message(embed=embed("AuraGuard Online",f"⚡ Pong! **{round(bot.latency*1000)}ms**",PURPLE,"⚡"),ephemeral=True)
@bot.tree.command(name="setstaffrole",description="Set staff role.")
@app_commands.checks.has_permissions(manage_guild=True)
async def ssr(i,role:discord.Role):settings(i.guild.id)["staff_role"]=role.id;save();await i.response.send_message(f"🛡️ Staff role: {role.mention}",ephemeral=True)
@bot.tree.command(name="setlogchannel",description="Set moderation log channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def slc(i,ch:discord.TextChannel):settings(i.guild.id)["log_channel"]=ch.id;save();await i.response.send_message("📋 Log channel saved.",ephemeral=True)
@bot.tree.command(name="setmessagelog",description="Set message log channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def sml(i,ch:discord.TextChannel):settings(i.guild.id)["message_log_channel"]=ch.id;save();await i.response.send_message("💬 Message log saved.",ephemeral=True)
@ag.command(name="enable",description="Enable AutoMod.")
@app_commands.checks.has_permissions(manage_guild=True)
async def ae(i):automod(i.guild.id)["enabled"]=True;save();await i.response.send_message("🛡️ AutoMod enabled.",ephemeral=True)
@ag.command(name="disable",description="Disable AutoMod.")
@app_commands.checks.has_permissions(manage_guild=True)
async def ad(i):automod(i.guild.id)["enabled"]=False;save();await i.response.send_message("🔴 AutoMod disabled.",ephemeral=True)
@ag.command(name="addword",description="Add blocked word.")
@app_commands.checks.has_permissions(manage_guild=True)
async def aaw(i,word:str):automod(i.guild.id)["blocked_words"].append(word.strip());save();await i.response.send_message(f"🛡️ Added `{word}`.",ephemeral=True)
@ag.command(name="removeword",description="Remove blocked word.")
@app_commands.checks.has_permissions(manage_guild=True)
async def arw(i,word:str):
    a=automod(i.guild.id)["blocked_words"];m=next((x for x in a if x.lower()==word.lower()),None)
    if not m:await i.response.send_message("❌ Not blocked.",ephemeral=True);return
    a.remove(m);save();await i.response.send_message(f"✅ Removed `{m}`.",ephemeral=True)
async def hier(i,m):
    if m==i.user or m==i.guild.owner or (i.user!=i.guild.owner and m.top_role>=i.user.top_role) or (i.guild.me and m.top_role>=i.guild.me.top_role):await i.response.send_message("❌ I can't moderate that member.",ephemeral=True);return False
    return True
@bot.tree.command(name="kick",description="Kick member.")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(i,member:discord.Member,reason:str="No reason provided"):
    if not await hier(i,member):return
    await member.kick(reason=reason);await i.response.send_message(f"👢 Kicked {member.mention}.");await log(i.guild,"Member Kicked",f"Member: {member.mention}\nModerator: {i.user.mention}\nReason: {reason}",RED)
@bot.tree.command(name="ban",description="Ban member.")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(i,member:discord.Member,reason:str="No reason provided"):
    if not await hier(i,member):return
    await member.ban(reason=reason);await i.response.send_message(f"🔨 Banned {member.mention}.");await log(i.guild,"Member Banned",f"Member: {member.mention}\nModerator: {i.user.mention}\nReason: {reason}",RED)
@bot.tree.command(name="unban",description="Unban by ID.")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(i,user_id:str):
    try:u=await bot.fetch_user(int(user_id));await i.guild.unban(u);await i.response.send_message(f"🔓 **{u}** unbanned.")
    except:await i.response.send_message("❌ User not found or not banned.",ephemeral=True)
@bot.tree.command(name="timeout",description="Timeout member.")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout(i,member:discord.Member,minutes:int,reason:str="No reason provided"):
    if minutes<1 or minutes>40320:await i.response.send_message("❌ Choose 1 minute to 28 days.",ephemeral=True);return
    if not await hier(i,member):return
    await member.timeout(discord.utils.utcnow()+timedelta(minutes=minutes),reason=reason);await i.response.send_message(f"⏳ {member.mention} timed out for **{minutes} minutes**.")
@bot.tree.command(name="untimeout",description="Remove timeout.")
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout(i,member:discord.Member):
    if not await hier(i,member):return
    await member.timeout(None);await i.response.send_message(f"🔓 Removed {member.mention}'s timeout.")

invite_cache={}
@bot.event
async def on_ready():
    print(f"AuraGuard V9 online as {bot.user}");await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching,name="over your server 🛡️"))
    if not getattr(bot,"views",False):
        bot.add_view(TicketPanel());bot.add_view(TicketControls())
        for x in data["giveaways"]:bot.add_view(GiveawayView(x))
        bot.views=True
    for g in bot.guilds:
        try:invite_cache[g.id]={x.code:x.uses for x in await g.invites()}
        except:pass
    if not giveaway_loop.is_running():giveaway_loop.start()
    try:print(f"Synced {len(await bot.tree.sync())} slash commands.")
    except Exception as e:print(e)
@bot.event
async def on_member_join(m):
    g=m.guild;iv=None
    try:
        old=invite_cache.get(g.id,{});new=await g.invites()
        for x in new:
            if x.uses and x.uses>old.get(x.code,0):iv=x.inviter;break
        invite_cache[g.id]={x.code:x.uses for x in new}
    except:pass
    if iv and iv.id!=m.id:
        d=record(g.id,iv.id);d["total"]+=1;d["regular"]+=1;memberinv(g.id)[str(m.id)]=iv.id;save()
        ch=await textchannel(g,settings(g.id).get("invite_channel"))
        if ch:await ch.send(embed=embed("New Invite!",f"👋 **Member:** {m.mention}\n📨 **Invited By:** {iv.mention}\n📊 **Total Invites:** **{d['total']}**",GREEN,"📨"))
    if settings(g.id)["welcome_enabled"]:
        ch=await textchannel(g,settings(g.id).get("welcome_channel"))
        if ch:await welcome(m,ch,iv)
@bot.event
async def on_member_remove(m):
    g=m.guild;uid=memberinv(g.id).pop(str(m.id),None)
    if uid:
        d=invdata(g.id).get(str(uid))
        if d:d["total"]=max(0,d["total"]-1);d["regular"]=max(0,d["regular"]-1);d["left"]+=1;save()
    s=settings(g.id)
    if s["leave_enabled"]:
        ch=await textchannel(g,s["leave_channel"])
        if ch:await ch.send(embed=embed("Member Left",s["leave_message"].replace("{user}",m.mention).replace("{server}",g.name),YELLOW,"🚪"))
@bot.event
async def on_invite_create(x):invite_cache.setdefault(x.guild.id,{})[x.code]=x.uses
@bot.event
async def on_invite_delete(x):invite_cache.setdefault(x.guild.id,{}).pop(x.code,None)
@bot.event
async def on_message(m):
    if m.author.bot or not m.guild:return
    a=automod(m.guild.id)
    if a["enabled"]:
        for w in a["blocked_words"]:
            if w.lower() in m.content.lower():
                try:await m.delete();await m.channel.send(f"⚠️ {m.author.mention}, blocked word.",delete_after=5)
                except:pass
                await log(m.guild,"AutoMod Action",f"Member: {m.author.mention}\nChannel: {m.channel.mention}",RED);return
    await mlog(m.guild,"Message Sent",f"**Author:** {m.author.mention}\n**Channel:** {m.channel.mention}\n\n**Message:**\n{discord.utils.escape_markdown(m.content or '*No text*')}")
    await bot.process_commands(m)
@bot.event
async def on_message_delete(m):
    if not m.author.bot and m.guild:await mlog(m.guild,"Message Deleted",f"**Author:** {m.author.mention}\n**Channel:** {m.channel.mention}\n\n{discord.utils.escape_markdown(m.content or '*No text*')}",RED)
@bot.event
async def on_message_edit(b,a):
    if not b.author.bot and b.guild and b.content!=a.content:await mlog(b.guild,"Message Edited",f"**Author:** {b.author.mention}\n**Before:**\n{discord.utils.escape_markdown(b.content)}\n\n**After:**\n{discord.utils.escape_markdown(a.content)}",YELLOW)
@tasks.loop(seconds=15)
async def giveaway_loop():
    now=datetime.now(timezone.utc)
    for x,g in list(data["giveaways"].items()):
        try:
            if now>=datetime.fromisoformat(g["end_time"]):
                guild=bot.get_guild(g["guild"]);await finish(guild,await textchannel(guild,g["channel"]) if guild else None,x)
        except Exception as e:print("Giveaway error:",e)
for group in [wg,lg,tg,gg,ag]:bot.tree.add_command(group)
@bot.tree.error
async def error(i,e):
    print(repr(e));msg="❌ You don't have permission to use that command." if isinstance(e,(app_commands.MissingPermissions,app_commands.CheckFailure)) else "❌ Something went wrong."
    try:await (i.followup.send(msg,ephemeral=True) if i.response.is_done() else i.response.send_message(msg,ephemeral=True))
    except:pass
bot.run(TOKEN)
