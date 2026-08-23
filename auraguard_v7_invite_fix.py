# =========================================================
# AURAGUARD V7 — INVITE SYSTEM PATCH
# =========================================================
# This patch fixes /setinvitechannel and keeps invite settings
# separate for every Discord server.
#
# 1) Add "invite_channel": None to get_settings() defaults.
# 2) Add the /setinvitechannel command below.
# 3) Add send_invite_join_message().
# 4) Call it from on_member_join() after invite data is updated.
#
# ---------------------------------------------------------

# ADD THIS TO YOUR get_settings() DEFAULTS:
# "invite_channel": None,


async def send_invite_join_message(guild, member, inviter, inviter_data=None):
    """Send the invite announcement to this guild's configured channel."""
    channel_id = get_settings(guild.id).get("invite_channel")
    channel = guild.get_channel(channel_id) if channel_id else None

    if not isinstance(channel, discord.TextChannel):
        return

    try:
        if inviter and inviter.id != member.id:
            total = (inviter_data or {}).get("total", 0)

            await channel.send(
                embed=aura_embed(
                    "New Member Invited!",
                    f"👋 **{member.mention}** joined the server!\n\n"
                    f"📨 **Invited by:** {inviter.mention}\n"
                    f"📈 **Total Invites:** **{total}**",
                    AURA_PURPLE,
                    "📮"
                )
            )
        else:
            await channel.send(
                embed=aura_embed(
                    "New Member Joined",
                    f"👋 **{member.mention}** joined the server.\n"
                    f"📨 **Inviter:** Unknown",
                    AURA_PURPLE,
                    "📮"
                )
            )
    except discord.Forbidden:
        print(f"No permission to send invite message in {guild.name}")
    except Exception as e:
        print(f"Invite announcement error: {e}")


@bot.tree.command(
    name="setinvitechannel",
    description="Set the channel where invite join messages are sent."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def setinvitechannel(
    interaction: discord.Interaction,
    channel: discord.abc.GuildChannel
):
    # Accept only regular text channels.
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "❌ Please select a normal text channel.",
            ephemeral=True
        )
        return

    settings = get_settings(interaction.guild.id)
    settings["invite_channel"] = channel.id
    save_data()

    await interaction.response.send_message(
        f"📮 Invite announcements will now be sent to {channel.mention}.",
        ephemeral=True
    )


@bot.tree.command(
    name="removeinvitechannel",
    description="Disable the invite join announcement channel."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def removeinvitechannel(interaction: discord.Interaction):
    settings = get_settings(interaction.guild.id)
    settings["invite_channel"] = None
    save_data()

    await interaction.response.send_message(
        "📮 Invite join announcements have been disabled.",
        ephemeral=True
    )


# ---------------------------------------------------------
# REPLACE THE INVITE-TRACKING PART OF on_member_join()
# WITH THIS LOGIC:
# ---------------------------------------------------------
#
# inviter_data = None
#
# if inviter and inviter.id != member.id:
#     invite_data = get_invite_data(guild.id)
#     inviter_data = invite_data.setdefault(
#         str(inviter.id),
#         {"total": 0, "regular": 0}
#     )
#     inviter_data["total"] += 1
#     inviter_data["regular"] += 1
#     save_data()
#
# await send_invite_join_message(
#     guild,
#     member,
#     inviter,
#     inviter_data
# )
