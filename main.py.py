import discord
from discord import app_commands
import random
import json
import os
import time
import asyncio


# =========================================================
# AURA STAFF ROLE
# =========================================================
# Members with this role can use Aura management commands.
AURA_STAFF_ROLE_ID = 1535711657873907742


async def has_aura_staff_role(interaction: discord.Interaction):
    if interaction.guild is None:
        return False

    member = interaction.user

    if not isinstance(member, discord.Member):
        try:
            member = await interaction.guild.fetch_member(
                interaction.user.id
            )
        except (
            discord.NotFound,
            discord.HTTPException,
            discord.Forbidden
        ):
            return False

    return any(
        role.id == AURA_STAFF_ROLE_ID
        for role in member.roles
    )


def aura_staff_only():
    async def predicate(interaction: discord.Interaction):
        return await has_aura_staff_role(interaction)

    return app_commands.check(predicate)


# =========================================================
# AURA COINFLIP
# =========================================================

# Put your bot token in an environment variable named:
# DISCORD_TOKEN

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN environment variable is missing!"
    )


# =========================================================
# SETTINGS
# =========================================================

# New users start with 0 Sab Bucks
STARTING_BALANCE = 0

# Coinflip cooldown in seconds
COINFLIP_COOLDOWN = 30

# Currency name
CURRENCY_NAME = "Sab Bucks"

# JSON files
BALANCE_FILE = "balances.json"
CODES_FILE = "codes.json"
RESET_ROLE_FILE = "reset_role.json"
REMOVE_ROLE_FILE = "remove_role.json"


# =========================================================
# JSON SYSTEM
# =========================================================

def load_json(filename):
    """Load a JSON file."""

    if not os.path.exists(filename):
        return {}

    try:

        with open(filename, "r") as file:
            return json.load(file)

    except (json.JSONDecodeError, OSError):

        return {}


def save_json(filename, data):
    """Save data to a JSON file."""

    with open(filename, "w") as file:

        json.dump(
            data,
            file,
            indent=4
        )


# =========================================================
# LOAD DATA
# =========================================================

balances = load_json(BALANCE_FILE)

codes = load_json(CODES_FILE)

reset_role_data = load_json(
    RESET_ROLE_FILE
)

remove_role_data = load_json(
    REMOVE_ROLE_FILE
)


# =========================================================
# BALANCE SYSTEM
# =========================================================

def get_balance(guild_id, user_id):
    """
    Get a user's balance for a specific server.
    """

    guild_id = str(guild_id)
    user_id = str(user_id)

    # Create server if it doesn't exist
    if guild_id not in balances:

        balances[guild_id] = {}

    # Create user if they don't exist
    if user_id not in balances[guild_id]:

        balances[guild_id][user_id] = STARTING_BALANCE

        save_json(
            BALANCE_FILE,
            balances
        )

    return balances[guild_id][user_id]


def change_balance(guild_id, user_id, amount):
    """
    Add or remove Sab Bucks for a user
    in a specific server.
    """

    guild_id = str(guild_id)
    user_id = str(user_id)

    # Create server if it doesn't exist
    if guild_id not in balances:

        balances[guild_id] = {}

    # Create user if they don't exist
    if user_id not in balances[guild_id]:

        balances[guild_id][user_id] = STARTING_BALANCE

    balances[guild_id][user_id] += amount

    save_json(
        BALANCE_FILE,
        balances
    )


# =========================================================
# COOLDOWNS
# =========================================================

# user_id -> timestamp
coinflip_cooldowns = {}


def get_cooldown(user_id):
    """
    Return remaining coinflip cooldown.
    """

    user_id = str(user_id)

    if user_id not in coinflip_cooldowns:

        return 0

    elapsed = (
        time.time()
        - coinflip_cooldowns[user_id]
    )

    remaining = (
        COINFLIP_COOLDOWN
        - elapsed
    )

    if remaining <= 0:

        del coinflip_cooldowns[user_id]

        return 0

    return remaining


def start_cooldown(user_id):
    """
    Start the coinflip cooldown.
    """

    coinflip_cooldowns[
        str(user_id)
    ] = time.time()


# =========================================================
# OPEN BETS
# =========================================================

# message_id -> bet information
open_bets = {}

# user_id -> message_id
# Makes sure a user can only have ONE active bet.
user_active_bets = {}


# =========================================================
# DISCORD BOT
# =========================================================

class AuraCoinflip(discord.Client):

    def __init__(self):

        intents = discord.Intents.default()

        # Needed for member information
        intents.members = True

        super().__init__(
            intents=intents
        )

        self.tree = app_commands.CommandTree(
            self
        )

    async def setup_hook(self):

        # Sync slash commands
        await self.tree.sync()

    async def on_ready(self):

        print(
            "==================================="
        )

        print(
            "✨ Aura Coinflip is online!"
        )

        print(
            f"Bot: {self.user}"
        )

        print(
            f"Bot ID: {self.user.id}"
        )

        print(
            "==================================="
        )

    # =====================================================
    # NEW MEMBER JOIN
    # =====================================================

    async def on_member_join(self, member):

        guild_id = str(
            member.guild.id
        )

        user_id = str(
            member.id
        )

        if guild_id not in balances:

            balances[guild_id] = {}

        if user_id not in balances[guild_id]:

            balances[guild_id][user_id] = (
                STARTING_BALANCE
            )

            save_json(
                BALANCE_FILE,
                balances
            )

        print(
            f"👋 {member} joined "
            f"{member.guild.name} "
            f"and received "
            f"{STARTING_BALANCE} "
            f"{CURRENCY_NAME}!"
        )


bot = AuraCoinflip()


# =========================================================
# COINFLIP BET VIEW
# =========================================================

class CoinflipView(discord.ui.View):

    def __init__(
        self,
        guild_id,
        creator_id,
        amount,
        choice
    ):

        # Bets never expire
        super().__init__(
            timeout=None
        )

        self.guild_id = guild_id
        self.creator_id = creator_id
        self.amount = amount
        self.choice = choice

        self.message_id = None
        self.channel_id = None

        self.finished = False

        # Prevent two people joining simultaneously
        self.join_lock = asyncio.Lock()

    # =====================================================
    # JOIN BET BUTTON
    # =====================================================

    @discord.ui.button(
        label="🎯 Join Bet",
        style=discord.ButtonStyle.green
    )
    async def join_bet(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        async with self.join_lock:

            # -------------------------------------------------
            # CHECK IF BET IS FINISHED
            # -------------------------------------------------

            if self.finished:

                await interaction.response.send_message(
                    "❌ This bet is already finished.",
                    ephemeral=True
                )

                return

            # -------------------------------------------------
            # CREATOR CANNOT JOIN OWN BET
            # -------------------------------------------------

            if interaction.user.id == self.creator_id:

                await interaction.response.send_message(
                    "❌ You can't join your own bet!",
                    ephemeral=True
                )

                return

            # -------------------------------------------------
            # CHECK BET STILL EXISTS
            # -------------------------------------------------

            if self.message_id not in open_bets:

                self.finished = True

                await interaction.response.send_message(
                    "❌ This bet is no longer available.",
                    ephemeral=True
                )

                return

            # -------------------------------------------------
            # CHECK JOINER BALANCE
            # -------------------------------------------------

            joiner_balance = get_balance(
                self.guild_id,
                interaction.user.id
            )

            if joiner_balance < self.amount:

                missing = (
                    self.amount
                    - joiner_balance
                )

                await interaction.response.send_message(
                    f"❌ You can't join this bet!\n\n"
                    f"🎲 Bet amount: "
                    f"**{self.amount:,} "
                    f"{CURRENCY_NAME}**\n"
                    f"💰 Your balance: "
                    f"**{joiner_balance:,} "
                    f"{CURRENCY_NAME}**\n"
                    f"💸 You need "
                    f"**{missing:,} more "
                    f"{CURRENCY_NAME}**.",
                    ephemeral=True
                )

                return

            # -------------------------------------------------
            # CLOSE BET
            # -------------------------------------------------

            self.finished = True

            open_bets.pop(
                self.message_id,
                None
            )

            user_active_bets.pop(
                self.creator_id,
                None
            )

            # -------------------------------------------------
            # TAKE JOINER'S MONEY
            # -------------------------------------------------

            change_balance(
                self.guild_id,
                interaction.user.id,
                -self.amount
            )

            # -------------------------------------------------
            # GET CREATOR
            # -------------------------------------------------

            try:

                creator = await bot.fetch_user(
                    self.creator_id
                )

            except Exception:

                creator = None

            # -------------------------------------------------
            # DETERMINE CHOICES
            # -------------------------------------------------

            creator_choice = self.choice

            if creator_choice == "heads":

                joiner_choice = "tails"

            else:

                joiner_choice = "heads"

            # -------------------------------------------------
            # FLIP COIN
            # -------------------------------------------------

            result = random.choice(
                [
                    "heads",
                    "tails"
                ]
            )

            # -------------------------------------------------
            # DETERMINE WINNER
            # -------------------------------------------------

            if result == creator_choice:

                winner_id = self.creator_id

                winner_name = (
                    creator.display_name
                    if creator
                    else f"User {self.creator_id}"
                )

                loser_name = (
                    interaction.user.display_name
                )

                winner_choice = creator_choice
                loser_choice = joiner_choice

            else:

                winner_id = interaction.user.id

                winner_name = (
                    interaction.user.display_name
                )

                loser_name = (
                    creator.display_name
                    if creator
                    else f"User {self.creator_id}"
                )

                winner_choice = joiner_choice
                loser_choice = creator_choice

            # -------------------------------------------------
            # PAY WINNER
            # -------------------------------------------------

            total_pot = self.amount * 2

            change_balance(
                self.guild_id,
                winner_id,
                total_pot
            )

            # -------------------------------------------------
            # DISABLE BUTTON
            # -------------------------------------------------

            for child in self.children:

                child.disabled = True

            # -------------------------------------------------
            # RESULT EMBED
            # -------------------------------------------------

            embed = discord.Embed(
                title="🪙 AURA COINFLIP",
                description=(
                    f"## The coin has been flipped!\n\n"
                    f"🪙 **Result:** "
                    f"# {result.upper()}!\n\n"
                    f"👤 **{winner_name}** — "
                    f"{winner_choice.upper()}\n"
                    f"👤 **{loser_name}** — "
                    f"{loser_choice.upper()}\n\n"
                    f"🏆 **{winner_name} WON!**\n\n"
                    f"💰 Bet: "
                    f"**{self.amount:,} "
                    f"{CURRENCY_NAME}**\n"
                    f"💵 Total Pot: "
                    f"**{total_pot:,} "
                    f"{CURRENCY_NAME}**\n\n"
                    f"🎉 Winner received "
                    f"**{total_pot:,} "
                    f"{CURRENCY_NAME}**!"
                ),
                color=discord.Color.green()
            )

            embed.set_footer(
                text="✨ Aura Coinflip"
            )

            await interaction.response.edit_message(
                embed=embed,
                view=self
            )


# =========================================================
# /BALANCE
# =========================================================

@bot.tree.command(
    name="balance",
    description="Check your Sab Bucks balance."
)
async def balance(
    interaction: discord.Interaction
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used "
            "inside a server.",
            ephemeral=True
        )

        return

    user_balance = get_balance(
        interaction.guild.id,
        interaction.user.id
    )

    embed = discord.Embed(
        title="💰 Sab Bucks",
        description=(
            f"**{interaction.user.display_name}**, "
            f"you currently have:\n\n"
            f"💵 **{user_balance:,} "
            f"{CURRENCY_NAME}**"
        ),
        color=discord.Color.gold()
    )

    embed.set_footer(
        text="✨ Aura Coinflip"
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# /USERBALANCE
# =========================================================

@bot.tree.command(
    name="userbalance",
    description="Check another user's Sab Bucks balance."
)
@app_commands.describe(
    user="The user whose Sab Bucks you want to check."
)
async def userbalance(
    interaction: discord.Interaction,
    user: discord.Member
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used "
            "inside a server.",
            ephemeral=True
        )

        return

    user_balance = get_balance(
        interaction.guild.id,
        user.id
    )

    embed = discord.Embed(
        title="💰 SAB BUCKS",
        description=(
            f"👤 **{user.display_name}** currently has:\n\n"
            f"💵 **{user_balance:,} "
            f"{CURRENCY_NAME}**"
        ),
        color=discord.Color.gold()
    )

    embed.set_thumbnail(
        url=user.display_avatar.url
    )

    embed.set_footer(
        text="✨ Aura Coinflip"
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# /COINFLIP
# =========================================================

@bot.tree.command(
    name="coinflip",
    description="Create a coinflip bet for another player to join."
)
@app_commands.describe(
    amount="How many Sab Bucks do you want to bet?",
    choice="Choose Heads or Tails."
)
@app_commands.choices(
    choice=[
        app_commands.Choice(
            name="Heads",
            value="heads"
        ),
        app_commands.Choice(
            name="Tails",
            value="tails"
        )
    ]
)
async def coinflip(
    interaction: discord.Interaction,
    amount: int,
    choice: app_commands.Choice[str]
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used "
            "inside a server.",
            ephemeral=True
        )

        return

    user_id = interaction.user.id
    guild_id = interaction.guild.id

    # -----------------------------------------------------
    # CHECK ACTIVE BET
    # -----------------------------------------------------

    if user_id in user_active_bets:

        existing_bet_id = (
            user_active_bets[user_id]
        )

        if existing_bet_id in open_bets:

            await interaction.response.send_message(
                "❌ You already have an active bet!\n\n"
                "You can only have **1 bet at a time**.\n\n"
                "Use `/cancelbet` if you want to "
                "cancel your current bet.",
                ephemeral=True
            )

            return

        else:

            user_active_bets.pop(
                user_id,
                None
            )

    # -----------------------------------------------------
    # CHECK COOLDOWN
    # -----------------------------------------------------

    remaining = get_cooldown(
        user_id
    )

    if remaining > 0:

        seconds = int(
            remaining
        ) + 1

        await interaction.response.send_message(
            f"⏳ You need to wait "
            f"**{seconds} seconds** before "
            f"creating another coinflip.",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # CHECK BET AMOUNT
    # -----------------------------------------------------

    if amount <= 0:

        await interaction.response.send_message(
            "❌ Your bet must be at least "
            "**1 Sab Buck**.",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # CHECK BALANCE
    # -----------------------------------------------------

    current_balance = get_balance(
        guild_id,
        user_id
    )

    if amount > current_balance:

        missing = (
            amount
            - current_balance
        )

        await interaction.response.send_message(
            f"❌ You don't have enough "
            f"**Sab Bucks**!\n\n"
            f"💰 Balance: "
            f"**{current_balance:,}**\n"
            f"🎲 Bet: "
            f"**{amount:,}**\n"
            f"💸 You need "
            f"**{missing:,} more**.",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # START COOLDOWN
    # -----------------------------------------------------

    start_cooldown(
        user_id
    )

    # -----------------------------------------------------
    # TAKE CREATOR'S MONEY
    # -----------------------------------------------------

    change_balance(
        guild_id,
        user_id,
        -amount
    )

    # -----------------------------------------------------
    # DETERMINE OPPONENT CHOICE
    # -----------------------------------------------------

    if choice.value == "heads":

        opponent_choice = "tails"

    else:

        opponent_choice = "heads"

    # -----------------------------------------------------
    # CREATE EMBED
    # -----------------------------------------------------

    embed = discord.Embed(
        title="🪙 AURA COINFLIP BET",
        description=(
            f"👤 **{interaction.user.mention}** "
            f"is looking for an opponent!\n\n"
            f"🎲 Bet: "
            f"**{amount:,} {CURRENCY_NAME}**\n"
            f"🟡 Their choice: "
            f"**{choice.value.upper()}**\n"
            f"🔵 Opponent choice: "
            f"**{opponent_choice.upper()}**\n\n"
            f"💰 Current Pot: "
            f"**{amount:,} {CURRENCY_NAME}**\n\n"
            f"🎯 Click **Join Bet** to match "
            f"the bet!\n\n"
            f"♾️ **This bet does not expire.**\n"
            f"👥 **Only one person can join.**"
        ),
        color=discord.Color.gold()
    )

    embed.set_footer(
        text="✨ Aura Coinflip"
    )

    # -----------------------------------------------------
    # CREATE VIEW
    # -----------------------------------------------------

    view = CoinflipView(
        guild_id=guild_id,
        creator_id=user_id,
        amount=amount,
        choice=choice.value
    )

    # -----------------------------------------------------
    # SEND BET
    # -----------------------------------------------------

    await interaction.response.send_message(
        embed=embed,
        view=view
    )

    # -----------------------------------------------------
    # GET MESSAGE
    # -----------------------------------------------------

    message = await interaction.original_response()

    view.message_id = message.id
    view.channel_id = interaction.channel_id

    # -----------------------------------------------------
    # STORE BET
    # -----------------------------------------------------

    open_bets[message.id] = {
        "guild_id": guild_id,
        "creator_id": user_id,
        "amount": amount,
        "channel_id": interaction.channel_id
    }

    # -----------------------------------------------------
    # STORE USER ACTIVE BET
    # -----------------------------------------------------

    user_active_bets[user_id] = message.id


# =========================================================
# /CANCELBET
# =========================================================

@bot.tree.command(
    name="cancelbet",
    description="Cancel your active coinflip bet and get your money back."
)
async def cancelbet(
    interaction: discord.Interaction
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used "
            "inside a server.",
            ephemeral=True
        )

        return

    user_id = interaction.user.id

    # -----------------------------------------------------
    # CHECK ACTIVE BET
    # -----------------------------------------------------

    if user_id not in user_active_bets:

        await interaction.response.send_message(
            "❌ You don't have an active bet to cancel.",
            ephemeral=True
        )

        return

    bet_message_id = (
        user_active_bets[user_id]
    )

    bet = open_bets.get(
        bet_message_id
    )

    if bet is None:

        user_active_bets.pop(
            user_id,
            None
        )

        await interaction.response.send_message(
            "❌ Your bet is no longer active.",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # REFUND CREATOR
    # -----------------------------------------------------

    change_balance(
        interaction.guild.id,
        user_id,
        bet["amount"]
    )

    # -----------------------------------------------------
    # REMOVE BET
    # -----------------------------------------------------

    open_bets.pop(
        bet_message_id,
        None
    )

    user_active_bets.pop(
        user_id,
        None
    )

    # -----------------------------------------------------
    # CREATE CANCELLED EMBED
    # -----------------------------------------------------

    embed = discord.Embed(
        title="❌ AURA COINFLIP CANCELLED",
        description=(
            f"👤 **{interaction.user.display_name}** "
            f"cancelled their coinflip bet.\n\n"
            f"🎲 Bet amount:\n"
            f"**{bet['amount']:,} "
            f"{CURRENCY_NAME}**\n\n"
            f"💰 **The full bet has been refunded.**"
        ),
        color=discord.Color.red()
    )

    embed.set_footer(
        text="✨ Aura Coinflip"
    )

    # -----------------------------------------------------
    # UPDATE ORIGINAL MESSAGE
    # -----------------------------------------------------

    channel = bot.get_channel(
        bet["channel_id"]
    )

    if channel is not None:

        try:

            message = await channel.fetch_message(
                bet_message_id
            )

            cancelled_view = discord.ui.View(
                timeout=None
            )

            cancelled_button = discord.ui.Button(
                label="❌ Bet Cancelled",
                style=discord.ButtonStyle.red,
                disabled=True
            )

            cancelled_view.add_item(
                cancelled_button
            )

            await message.edit(
                embed=embed,
                view=cancelled_view
            )

        except Exception:

            pass

    # -----------------------------------------------------
    # CONFIRM
    # -----------------------------------------------------

    await interaction.response.send_message(
        f"✅ Your bet of **{bet['amount']:,} "
        f"{CURRENCY_NAME}** was cancelled "
        f"and refunded.",
        ephemeral=True
    )


# =========================================================
# /GIFT
# =========================================================

@bot.tree.command(
    name="gift",
    description="Gift your Sab Bucks to another user."
)
@app_commands.describe(
    user="The user you want to gift Sab Bucks to.",
    amount="How many Sab Bucks you want to gift."
)
async def gift(
    interaction: discord.Interaction,
    user: discord.Member,
    amount: int
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used "
            "inside a server.",
            ephemeral=True
        )

        return

    guild_id = interaction.guild.id

    sender_id = interaction.user.id
    receiver_id = user.id

    # -----------------------------------------------------
    # CHECK SELF
    # -----------------------------------------------------

    if sender_id == receiver_id:

        await interaction.response.send_message(
            "❌ You can't gift Sab Bucks to yourself!",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # CHECK AMOUNT
    # -----------------------------------------------------

    if amount <= 0:

        await interaction.response.send_message(
            "❌ The gift amount must be greater than **0**.",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # GET SENDER BALANCE
    # -----------------------------------------------------

    sender_balance = get_balance(
        guild_id,
        sender_id
    )

    # -----------------------------------------------------
    # CHECK BALANCE
    # -----------------------------------------------------

    if sender_balance < amount:

        missing = (
            amount
            - sender_balance
        )

        await interaction.response.send_message(
            f"❌ You don't have enough "
            f"**{CURRENCY_NAME}**!\n\n"
            f"💰 Your balance: "
            f"**{sender_balance:,} "
            f"{CURRENCY_NAME}**\n"
            f"🎁 Gift amount: "
            f"**{amount:,} "
            f"{CURRENCY_NAME}**\n"
            f"💸 You need "
            f"**{missing:,} more "
            f"{CURRENCY_NAME}**.",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # TAKE MONEY FROM SENDER
    # -----------------------------------------------------

    change_balance(
        guild_id,
        sender_id,
        -amount
    )

    # -----------------------------------------------------
    # GIVE MONEY TO RECEIVER
    # -----------------------------------------------------

    change_balance(
        guild_id,
        receiver_id,
        amount
    )

    # -----------------------------------------------------
    # GET NEW BALANCES
    # -----------------------------------------------------

    sender_new_balance = get_balance(
        guild_id,
        sender_id
    )

    receiver_new_balance = get_balance(
        guild_id,
        receiver_id
    )

    # -----------------------------------------------------
    # GIFT EMBED
    # -----------------------------------------------------

    embed = discord.Embed(
        title="🎁 SAB BUCKS GIFT",
        description=(
            f"🎉 **{interaction.user.display_name}** "
            f"gifted **{amount:,} {CURRENCY_NAME}** "
            f"to **{user.display_name}**!\n\n"

            f"👤 **From:**\n"
            f"{interaction.user.mention}\n"
            f"💰 New Balance: "
            f"**{sender_new_balance:,} "
            f"{CURRENCY_NAME}**\n\n"

            f"👤 **To:**\n"
            f"{user.mention}\n"
            f"💰 New Balance: "
            f"**{receiver_new_balance:,} "
            f"{CURRENCY_NAME}**"
        ),
        color=discord.Color.green()
    )

    embed.set_footer(
        text="✨ Aura Coinflip"
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# /GIVEBUCKS
# =========================================================

@bot.tree.command(
    name="givebucks",
    description="Give Sab Bucks to a user."
)
@app_commands.describe(
    user="The user receiving the Sab Bucks.",
    amount="The amount of Sab Bucks to give."
)
@aura_staff_only()
async def givebucks(
    interaction: discord.Interaction,
    user: discord.Member,
    amount: int
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used "
            "inside a server.",
            ephemeral=True
        )

        return

    if amount <= 0:

        await interaction.response.send_message(
            "❌ Amount must be greater than **0**.",
            ephemeral=True
        )

        return

    change_balance(
        interaction.guild.id,
        user.id,
        amount
    )

    new_balance = get_balance(
        interaction.guild.id,
        user.id
    )

    embed = discord.Embed(
        title="👑 Sab Bucks Added",
        description=(
            f"💰 **{amount:,} "
            f"{CURRENCY_NAME}** "
            f"was given to {user.mention}.\n\n"
            f"💵 New Balance:\n"
            f"**{new_balance:,} "
            f"{CURRENCY_NAME}**"
        ),
        color=discord.Color.green()
    )

    embed.set_footer(
        text=f"Given by {interaction.user.display_name}"
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# GIVEBUCKS ERROR
# =========================================================

@givebucks.error
async def givebucks_error(
    interaction: discord.Interaction,
    error
):

    if isinstance(
        error,
        app_commands.errors.CheckFailure
    ):

        await interaction.response.send_message(
            "❌ You need the **Aura Staff** role "
            "to use this command.",
            ephemeral=True
        )

    else:

        await interaction.response.send_message(
            "❌ Something went wrong while giving "
            "Sab Bucks.",
            ephemeral=True
        )


# =========================================================
# /CREATECODE
# =========================================================

@bot.tree.command(
    name="createcode",
    description="Create a Sab Bucks redemption code."
)
@app_commands.describe(
    code_name="The name of the redemption code.",
    amount="How many Sab Bucks each redemption gives.",
    stock="How many different people can redeem the code."
)
@aura_staff_only()
async def createcode(
    interaction: discord.Interaction,
    code_name: str,
    amount: int,
    stock: int
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used "
            "inside a server.",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # CHECK CODE NAME
    # -----------------------------------------------------

    code_name = code_name.strip().upper()

    if not code_name:

        await interaction.response.send_message(
            "❌ The code name cannot be empty.",
            ephemeral=True
        )

        return

    if len(code_name) > 50:

        await interaction.response.send_message(
            "❌ The code name cannot be longer "
            "than **50 characters**.",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # CHECK AMOUNT
    # -----------------------------------------------------

    if amount <= 0:

        await interaction.response.send_message(
            "❌ The reward amount must be greater than **0**.",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # CHECK STOCK
    # -----------------------------------------------------

    if stock <= 0:

        await interaction.response.send_message(
            "❌ The stock must be greater than **0**.",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # CREATE SERVER DATA
    # -----------------------------------------------------

    guild_id = str(
        interaction.guild.id
    )

    if guild_id not in codes:

        codes[guild_id] = {}

    # -----------------------------------------------------
    # CHECK EXISTING CODE
    # -----------------------------------------------------

    if code_name in codes[guild_id]:

        await interaction.response.send_message(
            f"❌ The code **{code_name}** already exists!",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # SAVE CODE
    # -----------------------------------------------------

    codes[guild_id][code_name] = {
        "amount": amount,
        "stock": stock,
        "redeemed_by": []
    }

    save_json(
        CODES_FILE,
        codes
    )

    # -----------------------------------------------------
    # CREATE EMBED
    # -----------------------------------------------------

    embed = discord.Embed(
        title="🎟️ SAB BUCKS CODE CREATED",
        description=(
            f"✅ A new redemption code has been created!\n\n"
            f"🎟️ **Code:**\n"
            f"`{code_name}`\n\n"
            f"💰 **Reward per person:**\n"
            f"**{amount:,} {CURRENCY_NAME}**\n\n"
            f"📦 **Stock:**\n"
            f"**{stock} redemptions**\n\n"
            f"🔒 Each person can only redeem "
            f"this code **once**."
        ),
        color=discord.Color.green()
    )

    embed.set_footer(
        text=f"Created by {interaction.user.display_name}"
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# CREATECODE ERROR
# =========================================================

@createcode.error
async def createcode_error(
    interaction: discord.Interaction,
    error
):

    if isinstance(
        error,
        app_commands.errors.CheckFailure
    ):

        await interaction.response.send_message(
            "❌ You need the **Aura Staff** role "
            "to create codes.",
            ephemeral=True
        )

    else:

        await interaction.response.send_message(
            "❌ Something went wrong while creating "
            "the code.",
            ephemeral=True
        )


# =========================================================
# /REDEEMCODE
# =========================================================

@bot.tree.command(
    name="redeemcode",
    description="Redeem a Sab Bucks code."
)
@app_commands.describe(
    code_name="The code you want to redeem."
)
async def redeemcode(
    interaction: discord.Interaction,
    code_name: str
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used "
            "inside a server.",
            ephemeral=True
        )

        return

    guild_id = str(
        interaction.guild.id
    )

    user_id = str(
        interaction.user.id
    )

    code_name = code_name.strip().upper()

    # -----------------------------------------------------
    # CHECK SERVER CODES
    # -----------------------------------------------------

    if guild_id not in codes:

        await interaction.response.send_message(
            "❌ That code does not exist.",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # CHECK CODE
    # -----------------------------------------------------

    if code_name not in codes[guild_id]:

        await interaction.response.send_message(
            "❌ That code does not exist.",
            ephemeral=True
        )

        return

    code_data = codes[guild_id][code_name]

    # -----------------------------------------------------
    # CHECK IF USER ALREADY REDEEMED
    # -----------------------------------------------------

    redeemed_by = code_data.get(
        "redeemed_by",
        []
    )

    if user_id in redeemed_by:

        await interaction.response.send_message(
            "❌ You can only redeem this code once!",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # CHECK STOCK
    # -----------------------------------------------------

    if code_data["stock"] <= 0:

        await interaction.response.send_message(
            "❌ This code is out of stock.",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # GIVE REWARD
    # -----------------------------------------------------

    reward = code_data["amount"]

    change_balance(
        interaction.guild.id,
        interaction.user.id,
        reward
    )

    # -----------------------------------------------------
    # UPDATE CODE
    # -----------------------------------------------------

    code_data["stock"] -= 1

    code_data.setdefault(
        "redeemed_by",
        []
    )

    code_data["redeemed_by"].append(
        user_id
    )

    save_json(
        CODES_FILE,
        codes
    )

    # -----------------------------------------------------
    # GET NEW BALANCE
    # -----------------------------------------------------

    new_balance = get_balance(
        interaction.guild.id,
        interaction.user.id
    )

    # -----------------------------------------------------
    # CREATE EMBED
    # -----------------------------------------------------

    embed = discord.Embed(
        title="🎉 CODE REDEEMED",
        description=(
            f"🎟️ **Code:**\n"
            f"`{code_name}`\n\n"
            f"💰 **You received:**\n"
            f"**+{reward:,} {CURRENCY_NAME}**\n\n"
            f"💵 **New Balance:**\n"
            f"**{new_balance:,} {CURRENCY_NAME}**\n\n"
            f"📦 **Remaining Stock:**\n"
            f"**{code_data['stock']}**"
        ),
        color=discord.Color.green()
    )

    embed.set_footer(
        text="✨ Aura Coinflip"
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# /SETRESETROLE
# =========================================================

@bot.tree.command(
    name="setresetrole",
    description="Choose the role that can reset Sab Bucks."
)
@app_commands.describe(
    role="The role that will be allowed to reset Sab Bucks."
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def setresetrole(
    interaction: discord.Interaction,
    role: discord.Role
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used "
            "inside a server.",
            ephemeral=True
        )

        return

    guild_id = str(
        interaction.guild.id
    )

    reset_role_data[guild_id] = {
        "role_id": role.id
    }

    save_json(
        RESET_ROLE_FILE,
        reset_role_data
    )

    embed = discord.Embed(
        title="⚙️ RESET ROLE UPDATED",
        description=(
            f"✅ The role allowed to reset "
            f"Sab Bucks is now {role.mention}.\n\n"
            f"Members with this role can use:\n"
            f"• `/resetbucks`\n"
            f"• `/resetuserbucks`\n\n"
            f"⚠️ Administrator permission alone "
            f"does not allow resets."
        ),
        color=discord.Color.green()
    )

    embed.set_footer(
        text=f"Set by {interaction.user.display_name}"
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# SETRESETROLE ERROR
# =========================================================

@setresetrole.error
async def setresetrole_error(
    interaction: discord.Interaction,
    error
):

    if isinstance(
        error,
        app_commands.errors.MissingPermissions
    ):

        await interaction.response.send_message(
            "❌ You need **Administrator** permission "
            "to choose the reset role.",
            ephemeral=True
        )

    else:

        await interaction.response.send_message(
            "❌ Something went wrong while setting "
            "the reset role.",
            ephemeral=True
        )


# =========================================================
# RESET ROLE CHECK
# =========================================================

async def has_reset_role(interaction):
    """
    Reliably check whether the user has the server's
    selected reset role.

    The old version used guild.get_member(), which depends on
    Discord's member cache. If the cache did not contain the
    user, it incorrectly returned False even when the user
    actually had the role.
    """

    if interaction.guild is None:
        return False

    guild_id = str(interaction.guild.id)

    if guild_id not in reset_role_data:
        return False

    try:
        reset_role_id = int(
            reset_role_data[guild_id]["role_id"]
        )
    except (KeyError, TypeError, ValueError):
        return False

    # For slash commands used inside a server, Discord normally
    # gives us a Member object directly. Use it instead of the
    # guild member cache.
    member = interaction.user

    if not isinstance(member, discord.Member):
        try:
            member = await interaction.guild.fetch_member(
                interaction.user.id
            )
        except (discord.NotFound, discord.HTTPException, discord.Forbidden):
            return False

    return any(
        role.id == reset_role_id
        for role in member.roles
    )


# =========================================================
# /RESETBUCKS
# =========================================================

@bot.tree.command(
    name="resetbucks",
    description="Reset every user's Sab Bucks to 0."
)
async def resetbucks(
    interaction: discord.Interaction
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used "
            "inside a server.",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # CHECK RESET ROLE
    # -----------------------------------------------------

    guild_id = str(
        interaction.guild.id
    )

    if guild_id not in reset_role_data:

        await interaction.response.send_message(
            "❌ No reset role has been selected yet.\n\n"
            "An administrator needs to use:\n"
            "`/setresetrole @Role`",
            ephemeral=True
        )

        return

    if not await has_reset_role(interaction):

        await interaction.response.send_message(
            "❌ You don't have the role required "
            "to reset Sab Bucks.",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # RESET SERVER BALANCES
    # -----------------------------------------------------

    if guild_id not in balances:

        balances[guild_id] = {}

    for user_id in balances[guild_id]:

        balances[guild_id][user_id] = 0

    save_json(
        BALANCE_FILE,
        balances
    )

    # -----------------------------------------------------
    # CANCEL ACTIVE BETS FROM THIS SERVER
    # -----------------------------------------------------

    server_bet_ids = []

    for message_id, bet in open_bets.items():

        if str(
            bet["guild_id"]
        ) == guild_id:

            server_bet_ids.append(
                message_id
            )

    for message_id in server_bet_ids:

        bet = open_bets.pop(
            message_id,
            None
        )

        if bet:

            creator_id = bet["creator_id"]

            user_active_bets.pop(
                creator_id,
                None
            )

    # -----------------------------------------------------
    # RESET SUCCESS
    # -----------------------------------------------------

    embed = discord.Embed(
        title="🔄 SAB BUCKS RESET",
        description=(
            "💰 **The server's Sab Bucks economy "
            "has been completely reset!**\n\n"
            "Everyone now has:\n"
            "**0 Sab Bucks**\n\n"
            "🎲 Any active coinflip bets have "
            "also been cancelled."
        ),
        color=discord.Color.red()
    )

    embed.set_footer(
        text=f"Reset by {interaction.user.display_name}"
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# /RESETUSERBUCKS
# =========================================================

@bot.tree.command(
    name="resetuserbucks",
    description="Reset one user's Sab Bucks to 0."
)
@app_commands.describe(
    user="The user whose Sab Bucks you want to reset."
)
async def resetuserbucks(
    interaction: discord.Interaction,
    user: discord.Member
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used "
            "inside a server.",
            ephemeral=True
        )

        return

    guild_id = str(
        interaction.guild.id
    )

    # -----------------------------------------------------
    # CHECK RESET ROLE
    # -----------------------------------------------------

    if guild_id not in reset_role_data:

        await interaction.response.send_message(
            "❌ No reset role has been selected yet.\n\n"
            "An administrator needs to use:\n"
            "`/setresetrole @Role`",
            ephemeral=True
        )

        return

    if not await has_reset_role(interaction):

        await interaction.response.send_message(
            "❌ You don't have the role required "
            "to reset Sab Bucks.",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # GET CURRENT BALANCE
    # -----------------------------------------------------

    old_balance = get_balance(
        guild_id,
        user.id
    )

    # -----------------------------------------------------
    # CANCEL USER'S ACTIVE BET
    # -----------------------------------------------------

    if user.id in user_active_bets:

        bet_message_id = (
            user_active_bets[user.id]
        )

        open_bets.pop(
            bet_message_id,
            None
        )

        user_active_bets.pop(
            user.id,
            None
        )

    # -----------------------------------------------------
    # RESET USER BALANCE
    # -----------------------------------------------------

    balances[guild_id][str(user.id)] = 0

    save_json(
        BALANCE_FILE,
        balances
    )

    # -----------------------------------------------------
    # RESET SUCCESS
    # -----------------------------------------------------

    embed = discord.Embed(
        title="🔄 USER SAB BUCKS RESET",
        description=(
            f"👤 **{user.display_name}**'s "
            f"Sab Bucks have been reset.\n\n"
            f"💰 Previous Balance:\n"
            f"**{old_balance:,} "
            f"{CURRENCY_NAME}**\n\n"
            f"💵 New Balance:\n"
            f"**0 {CURRENCY_NAME}**"
        ),
        color=discord.Color.red()
    )

    embed.set_footer(
        text=f"Reset by {interaction.user.display_name}"
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# /SETREMOVEROLE
# =========================================================

@bot.tree.command(
    name="setremoverole",
    description="Choose the role that can remove Sab Bucks."
)
@app_commands.describe(
    role="The role that will be allowed to remove Sab Bucks."
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def setremoverole(
    interaction: discord.Interaction,
    role: discord.Role
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used "
            "inside a server.",
            ephemeral=True
        )

        return

    guild_id = str(
        interaction.guild.id
    )

    remove_role_data[guild_id] = {
        "role_id": role.id
    }

    save_json(
        REMOVE_ROLE_FILE,
        remove_role_data
    )

    embed = discord.Embed(
        title="⚙️ REMOVE ROLE UPDATED",
        description=(
            f"✅ The role allowed to remove "
            f"Sab Bucks is now {role.mention}.\n\n"
            f"Members with this role can use:\n"
            f"• `/removebucks`\n\n"
            f"⚠️ Administrator permission alone "
            f"does not allow members to remove Bucks."
        ),
        color=discord.Color.green()
    )

    embed.set_footer(
        text=f"Set by {interaction.user.display_name}"
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# SETREMOVEROLE ERROR
# =========================================================

@setremoverole.error
async def setremoverole_error(
    interaction: discord.Interaction,
    error
):

    if isinstance(
        error,
        app_commands.errors.MissingPermissions
    ):

        await interaction.response.send_message(
            "❌ You need **Administrator** permission "
            "to choose the remove role.",
            ephemeral=True
        )

    else:

        await interaction.response.send_message(
            "❌ Something went wrong while setting "
            "the remove role.",
            ephemeral=True
        )


# =========================================================
# /REMOVEBUCKS
# =========================================================

@bot.tree.command(
    name="removebucks",
    description="Remove Sab Bucks from a user."
)
@app_commands.describe(
    user="The user you want to remove Sab Bucks from.",
    amount="How many Sab Bucks you want to remove."
)
async def removebucks(
    interaction: discord.Interaction,
    user: discord.Member,
    amount: int
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used "
            "inside a server.",
            ephemeral=True
        )

        return

    guild_id = str(
        interaction.guild.id
    )

    # -----------------------------------------------------
    # CHECK REMOVE ROLE
    # -----------------------------------------------------

    if guild_id not in remove_role_data:

        await interaction.response.send_message(
            "❌ No remove role has been selected yet.\n\n"
            "An administrator needs to use:\n"
            "`/setremoverole @Role`",
            ephemeral=True
        )

        return

    remove_role_id = (
        remove_role_data[guild_id]["role_id"]
    )

    member = interaction.guild.get_member(
        interaction.user.id
    )

    if member is None:

        await interaction.response.send_message(
            "❌ Could not find your server member "
            "information.",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # CHECK REMOVE ROLE
    # -----------------------------------------------------

    has_remove_role = any(
        role.id == remove_role_id
        for role in member.roles
    )

    if not has_remove_role:

        await interaction.response.send_message(
            "❌ You don't have the role required "
            "to remove Sab Bucks.",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # CHECK AMOUNT
    # -----------------------------------------------------

    if amount <= 0:

        await interaction.response.send_message(
            "❌ The amount must be greater than **0**.",
            ephemeral=True
        )

        return

    # -----------------------------------------------------
    # GET USER BALANCE
    # -----------------------------------------------------

    current_balance = get_balance(
        guild_id,
        user.id
    )

    # -----------------------------------------------------
    # CALCULATE REMOVAL
    # -----------------------------------------------------

    amount_removed = min(
        amount,
        current_balance
    )

    new_balance = (
        current_balance
        - amount_removed
    )

    # -----------------------------------------------------
    # SET NEW BALANCE
    # -----------------------------------------------------

    balances[guild_id][str(user.id)] = (
        new_balance
    )

    save_json(
        BALANCE_FILE,
        balances
    )

    # -----------------------------------------------------
    # EMBED
    # -----------------------------------------------------

    embed = discord.Embed(
        title="💸 SAB BUCKS REMOVED",
        description=(
            f"👤 **{user.display_name}** had "
            f"Sab Bucks removed.\n\n"
            f"💸 Amount removed:\n"
            f"**-{amount_removed:,} "
            f"{CURRENCY_NAME}**\n\n"
            f"💰 Previous balance:\n"
            f"**{current_balance:,} "
            f"{CURRENCY_NAME}**\n\n"
            f"💵 New balance:\n"
            f"**{new_balance:,} "
            f"{CURRENCY_NAME}**"
        ),
        color=discord.Color.red()
    )

    embed.set_footer(
        text=f"Removed by {interaction.user.display_name}"
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# /LEADERBOARD
# =========================================================

@bot.tree.command(
    name="leaderboard",
    description="See the top 10 richest Sab Bucks users."
)
async def leaderboard(
    interaction: discord.Interaction
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used "
            "inside a server.",
            ephemeral=True
        )

        return

    guild_id = str(
        interaction.guild.id
    )

    if (
        guild_id not in balances
        or not balances[guild_id]
    ):

        await interaction.response.send_message(
            "❌ Nobody has any Sab Bucks yet!"
        )

        return

    # -----------------------------------------------------
    # SORT SERVER BALANCES
    # -----------------------------------------------------

    sorted_balances = sorted(
        balances[guild_id].items(),
        key=lambda item: item[1],
        reverse=True
    )

    top_10 = sorted_balances[:10]

    description = ""

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    # -----------------------------------------------------
    # BUILD LEADERBOARD
    # -----------------------------------------------------

    for position, (
        user_id,
        user_balance
    ) in enumerate(
        top_10,
        start=1
    ):

        # Only show members currently in this server
        member = interaction.guild.get_member(
            int(user_id)
        )

        if member is None:

            continue

        username = member.display_name

        if position <= 3:

            rank = medals[position - 1]

        else:

            rank = f"**#{position}**"

        description += (
            f"{rank} "
            f"**{username}** — "
            f"💰 **{user_balance:,} "
            f"{CURRENCY_NAME}**\n"
        )

    if not description:

        await interaction.response.send_message(
            "❌ Nobody has any Sab Bucks yet!"
        )

        return

    # -----------------------------------------------------
    # LEADERBOARD EMBED
    # -----------------------------------------------------

    embed = discord.Embed(
        title="🏆 AURA COINFLIP",
        description=(
            "## Sab Bucks Leaderboard\n\n"
            f"{description}"
        ),
        color=discord.Color.gold()
    )

    embed.set_footer(
        text="Top 10 richest Sab Bucks users"
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# START BOT
# =========================================================

bot.run(TOKEN)
