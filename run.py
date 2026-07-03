import discord
from discord import app_commands
from discord.ext import commands, tasks
import google.generativeai as genai
import os
import asyncio
import random
import aiohttp
import json
import time
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# --- KEEP ALIVE SERVER ---
app = Flask('')

@app.route('/')
def home():
    return "PackBot is alive and watching."

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- CONFIGURATION ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('GEMINI_KEY')
try:
    MY_ID = int(os.getenv('MY_ID'))
except:
    MY_ID = 0

# --- DATA MANAGEMENT ---
DATA_FILE = "database.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            if "economy" not in data: data["economy"] = {}
            if "blacklist" not in data: data["blacklist"] = []
            if "stocks" not in data: data["stocks"] = {"DUDU": {"price": 20.0, "last_update": time.time()}}
            return data
    return {"economy": {}, "blacklist": [], "stocks": {"DUDU": {"price": 20.0, "last_update": time.time()}}}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# --- GEMINI AI INITIALIZATION ---
genai.configure(api_key=API_KEY)

SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

HIJACK_PHRASES = [
    "I sit down when I pee.", 
    "I'm genuinely terrified of women.", 
    "My brain is perfectly smooth.",
    "Please bully me, I have no self-esteem.", 
    "I just shit my pants a little bit.", 
    "I practice kissing on my own hand.",
    "I eat drywall when nobody is looking."
]

INSULTS = ["bum", "clown", "fraud", "loser", "troglodyte", "oxygen thief", "mistake"]

DEATH_LINES = [
    "Boom! You got blasted.",
    "Unlucky. You are out of the game.",
    "Click... BANG! Better luck next time.",
    "Eliminated."
]

class PackBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="+p ", intents=intents, help_command=None)
        self.user_pack_history = {} 
        self.haunt_targets = set()
        self.active_tasks = {}
        self.hijack_targets = {} 
        self.webhook_cache = {}
        self.session = None
        self.model_id = None 
        
        self.rr_chamber = []
        self.rr_shots_fired = 0
        
        self.db = load_data()
        self.downtime = False

    def _init_user(self, user_id):
        uid = str(user_id)
        if uid not in self.db["economy"]:
            self.db["economy"][uid] = {
                "balance": 100,
                "last_daily": 0,
                "last_work": 0,
                "last_crime": 0,
                "loan_amount": 0,
                "loan_due": 0,
                "loan_interest": 0.0,
                "shares": 0
            }
        else:
            defaults = {
                "last_work": 0,
                "last_crime": 0,
                "loan_amount": 0, 
                "loan_due": 0, 
                "loan_interest": 0.0,
                "shares": 0
            }
            for k, v in defaults.items():
                if k not in self.db["economy"][uid]:
                    self.db["economy"][uid][k] = v
        return uid

    def process_overdue_loans(self, user_id):
        uid = self._init_user(user_id)
        user_data = self.db["economy"][uid]
        
        if user_data["loan_due"] > 0 and time.time() > user_data["loan_due"]:
            owed_amount = int(user_data["loan_amount"] * (1 + user_data["loan_interest"]))
            user_data["balance"] -= owed_amount
            user_data["loan_amount"] = 0
            user_data["loan_due"] = 0
            user_data["loan_interest"] = 0.0
            save_data(self.db)
            return owed_amount
        return 0

    def get_balance(self, user_id):
        self.process_overdue_loans(user_id)
        uid = self._init_user(user_id)
        return self.db["economy"][uid]["balance"]

    def update_balance(self, user_id, amount):
        uid = self._init_user(user_id)
        self.db["economy"][uid]["balance"] += amount
        save_data(self.db)

    def is_ai_allowed(self, user_id):
        if user_id == MY_ID: return True
        if self.downtime or user_id in self.db["blacklist"]: return False
        return True

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        print("\n[SYSTEM] Scanning Google AI Studio for accessible models...")
        try:
            available_models = [
                m.name for m in genai.list_models() 
                if 'generateContent' in m.supported_generation_methods
            ]
            if available_models:
                for m in available_models:
                    if "flash" in m.lower():
                        self.model_id = m
                        break
                if not self.model_id:
                    self.model_id = available_models[0]
                print(f"[SUCCESS] Auto-selected Engine: {self.model_id}")
        except Exception as e:
            print(f"[ERROR] AI Auth Failure: {e}")

        self.update_stock_prices.start()
        await self.tree.sync()
        print(f"--- PACKBOT IS ONLINE ---\n")

    @tasks.loop(hours=1.0)
    async def update_stock_prices(self):
        """Fluctuates the Duducoin price every single hour."""
        old_price = self.db["stocks"]["DUDU"]["price"]
        change = random.uniform(-0.18, 0.25) # Down up to 18%, up to 25%
        new_price = max(1.0, round(old_price * (1 + change), 2))
        self.db["stocks"]["DUDU"]["price"] = new_price
        self.db["stocks"]["DUDU"]["last_update"] = time.time()
        save_data(self.db)

    async def close(self):
        await self.session.close()
        await super().close()

    async def generate_raw(self, prompt, context="FICTIONAL ROAST BATTLE", is_glaze=False):
        if not self.model_id: return "System offline: No AI active."
        if is_glaze:
            system_instruction = f"SYSTEM MODE: ULTIMATE GLAZER. CONTEXT: {context}. RULE: 1 TO 2 LINES ONLY."
        else:
            system_instruction = f"SYSTEM MODE: UNFILTERED MENACE. CONTEXT: {context}. USE INTENSE INSULTS AND ROASTS."
        try:
            model = genai.GenerativeModel(model_name=self.model_id, generation_config={"temperature": 1.0, "top_p": 0.95}, safety_settings=SAFETY_SETTINGS)
            res = model.generate_content(f"{system_instruction}\n\nTARGET: {prompt}")
            return res.text.strip() if res.text else "AI blocked output."
        except Exception as e:
            return f"Error: {str(e)[:50]}"

    async def on_message(self, message):
        if message.author.bot: return
        lower_content = message.content.strip().lower()
        if any(lower_content.startswith(f"+p {c}") for c in ["help", "downtime", "blacklist", "gift", "leaderboard", "award"]):
            await self.process_commands(message)
            return

        if message.author.id in self.hijack_targets:
            custom_text = self.hijack_targets[message.author.id]
            replacement = custom_text if custom_text else random.choice(HIJACK_PHRASES)
            try:
                await message.delete()
                wh = self.webhook_cache.get(message.channel.id)
                if not wh:
                    webhooks = await message.channel.webhooks()
                    wh = discord.utils.get(webhooks, name="Packbot_Hijack") or await message.channel.create_webhook(name="Packbot_Hijack")
                    self.webhook_cache[message.channel.id] = wh
                await wh.send(content=replacement, username=message.author.display_name, avatar_url=message.author.display_avatar.url)
            except: pass
            return 

        if message.reference and message.reference.message_id:
            try:
                replied_to = message.reference.resolved
                if replied_to and replied_to.author.id == self.user.id and self.is_ai_allowed(message.author.id):
                    async with message.channel.typing():
                        is_creator = (message.author.id == MY_ID)
                        text = await self.generate_raw(f"User said: '{message.content}'", is_glaze=is_creator)
                        self.user_pack_history[message.author.id] = text
                        await message.reply(text)
            except: pass
        await self.process_commands(message)

bot = PackBot()

# --- MULTIPLAYER BLACKJACK ENGINE ---
class MultiplayerBlackjackView(discord.ui.View):
    def __init__(self, host, initial_bet):
        super().__init__(timeout=90)
        self.host = host
        self.initial_bet = initial_bet
        
        # Player tracking: {user_id: {"user": Member, "bet": int, "hand": [], "status": "playing" | "stood" | "bust"}}
        self.players = {host.id: {"user": host, "bet": initial_bet, "hand": [], "status": "playing"}}
        self.started = False
        self.current_turn_index = 0
        self.player_ids_order = []
        self.dealer_hand = []
        
        suits = ['♠', '♥', '♦', '♣']
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        self.deck = [{'rank': r, 'suit': s, 'value': 10 if r in ['J', 'Q', 'K'] else (11 if r == 'A' else int(r))} for s in suits for r in ranks]
        random.shuffle(self.deck)

    def calc_score(self, hand):
        score = sum(card['value'] for card in hand)
        aces = sum(1 for card in hand if card['rank'] == 'A')
        while score > 21 and aces:
            score -= 10
            aces -= 1
        return score

    def format_hand(self, hand, hide_second=False):
        if hide_second: return f"│ {hand[0]['rank']}{hand[0]['suit']} │  ??  │"
        return "  ".join([f"│ {c['rank']}{c['suit']} │" for c in hand])

    def generate_embed(self, finished=False):
        embed = discord.Embed(title="🃏 Multiplayer Blackjack Table", color=0x2b2d31)
        
        if not self.started:
            embed.description = f"**Host:** {self.host.mention}\n**Entry Bet:** {self.initial_bet} DDR\n\nClick **Join** to join the game!"
            players_list = "\n".join([f"• {p['user'].display_name} ({p['bet']} DDR)" for p in self.players.values()])
            embed.add_field(name="Players Waiting", value=players_list or "None", inline=False)
            return embed

        # Dealer field
        if not finished:
            embed.add_field(name="Dealer Hand", value=f"```\n{self.format_hand(self.dealer_hand, hide_second=True)}\n```", inline=False)
        else:
            d_score = self.calc_score(self.dealer_hand)
            embed.add_field(name=f"Dealer Hand [Score: {d_score}]", value=f"```\n{self.format_hand(self.dealer_hand)}\n```", inline=False)

        # Players fields
        for pid in self.player_ids_order:
            p = self.players[pid]
            score = self.calc_score(p['hand'])
            status_txt = f"Status: {p['status'].upper()}"
            
            if self.started and not finished:
                active_prefix = "➡️ " if pid == self.player_ids_order[self.current_turn_index] else ""
                field_name = f"{active_prefix}{p['user'].display_name} [Score: {score}]"
            else:
                field_name = f"{p['user'].display_name} [Score: {score}]"

            embed.add_field(
                name=field_name, 
                value=f"```\n{self.format_hand(p['hand'])}\n```*{status_txt} | Bet: {p['bet']} DDR*", 
                inline=False
            )
        return embed

    @discord.ui.button(label="Join Game", style=discord.ButtonStyle.success, custom_id="bj_join")
    async def join_lobby(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.started:
            return await interaction.response.send_message("The match has already started!", ephemeral=True)
        if interaction.user.id in self.players:
            return await interaction.response.send_message("You're already in the lobby.", ephemeral=True)
            
        bal = bot.get_balance(interaction.user.id)
        if bal < self.initial_bet:
            return await interaction.response.send_message("You don't have enough cash to match the bet!", ephemeral=True)
            
        bot.update_balance(interaction.user.id, -self.initial_bet)
        self.players[interaction.user.id] = {"user": interaction.user, "bet": self.initial_bet, "hand": [], "status": "playing"}
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Start Round", style=discord.ButtonStyle.primary, custom_id="bj_start")
    async def start_round(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id:
            return await interaction.response.send_message("Only the host can start the game.", ephemeral=True)
        if self.started:
            return await interaction.response.send_message("Already started.", ephemeral=True)
            
        self.started = True
        self.player_ids_order = list(self.players.keys())
        
        # Deal initial cards
        for pid in self.player_ids_order:
            self.players[pid]['hand'] = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]
        
        # Switch buttons to gameplay mode
        self.clear_items()
        self.add_item(discord.ui.Button(label="Hit", style=discord.ButtonStyle.primary, custom_id="bj_hit"))
        self.add_item(discord.ui.Button(label="Stand", style=discord.ButtonStyle.secondary, custom_id="bj_stand"))
        
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = interaction.data.get("custom_id")
        if custom_id in ["bj_join", "bj_start"]:
            return True
            
        # Gameplay button check
        current_player_id = self.player_ids_order[self.current_turn_index]
        if interaction.user.id != current_player_id:
            await interaction.response.send_message("It is not your turn yet!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, custom_id="bj_hit")
    async def gameplay_hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        pid = self.player_ids_order[self.current_turn_index]
        p = self.players[pid]
        
        p['hand'].append(self.deck.pop())
        if self.calc_score(p['hand']) > 21:
            p['status'] = "bust"
            await self.advance_turn(interaction)
        else:
            await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, custom_id="bj_stand")
    async def gameplay_stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        pid = self.player_ids_order[self.current_turn_index]
        self.players[pid]['status'] = "stood"
        await self.advance_turn(interaction)

    async def advance_turn(self, interaction):
        self.current_turn_index += 1
        if self.current_turn_index >= len(self.player_ids_order):
            await self.resolve_dealer_and_end(interaction)
        else:
            await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    async def resolve_dealer_and_end(self, interaction):
        # Dealer hits until 17
        while self.calc_score(self.dealer_hand) < 17:
            self.dealer_hand.append(self.deck.pop())
            
        d_score = self.calc_score(self.dealer_hand)
        self.clear_items()
        
        # Process payouts
        for pid, p in self.players.items():
            p_score = self.calc_score(p['hand'])
            if p['status'] == "bust":
                p['status'] = "Lost (Bust)"
            elif d_score > 21:
                bot.update_balance(pid, p['bet'] * 2)
                p['status'] = f"Won! (+{p['bet']} DDR)"
            elif p_score > d_score:
                bot.update_balance(pid, p['bet'] * 2)
                p['status'] = f"Won! (+{p['bet']} DDR)"
            elif d_score > p_score:
                p['status'] = "Lost"
            else:
                bot.update_balance(pid, p['bet'])
                p['status'] = "Push (Tie)"
                
        await interaction.response.edit_message(embed=self.generate_embed(finished=True), view=None)
        self.stop()

# --- GENERAL EMBED BUILDERS ---
def build_help_embed(user_id):
    embed = discord.Embed(title="Bot Commands menu", color=0x2b2d31, description="Prefix usage: `+p <command>` or use standard Slash Commands.")
    embed.add_field(name="💰 Money & Games", value="`/daily` - Claim free daily cash\n`/work` - Put in work for secure cash (5m cooldown)\n`/crime` - High risk high reward action (10m cooldown)\n`/balance` - Check your wallet & loans\n`/gift <user> <amount>` - Send cash to a friend\n`/leaderboard` - See richest users\n`/loan <action>` - Borrow or repay cash\n`/coinflip <bet> <side>` - Flip for double or nothing\n`/blackjack <bet>` - Open a multiplayer card table\n`/slots <bet>` - Play high-stakes slots\n`/rr` - Play a quick round of Russian Roulette", inline=False)
    embed.add_field(name="📈 Stock Market", value="`/stock view` - Check Duducoin market price\n`/stock buy <shares>` - Buy Duducoin stock shares\n`/stock sell <shares>` - Sell your shares back for cash", inline=False)
    embed.add_field(name="🤖 AI Systems", value="`/pack <user>` - Roast someone intensely\n`/glaze <user>` - Hyped praise\n`/lobotomy <user>` - Brainrot custom poetry\n`/lawyer <user> <claim>` - Simulate wild arguments\n`/ask <question>` - Ask the AI anything", inline=False)
    if user_id == MY_ID:
        embed.add_field(name="⚙️ Admin Settings", value="`/downtime` - Toggle bot AI access\n`/blacklist <user>` - Block user from AI\n`/award <user> <amount>` - Print free cash into existence", inline=False)
    return embed

def build_balance_embed(user, balance, loan_amt, loan_due, shares):
    embed = discord.Embed(title="🏦 Bank Account Details", color=0x2b2d31)
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Cash Balance", value=f"{balance} DDR", inline=True)
    embed.add_field(name="Owned Stocks", value=f"{shares} DUDU", inline=True)
    
    if loan_amt > 0:
        rem_time = int(max(0, loan_due - time.time()) / 3600)
        embed.add_field(name="⚠️ Active Loans", value=f"Borrowed: {loan_amt} DDR\nDeadline: {rem_time} Hours left", inline=False)
    else:
        embed.add_field(name="Loans", value="No outstanding debt.", inline=False)
    return embed

# --- PREFIX COMMAND MATRIX ---
@bot.command(name="help")
async def help_prefix(ctx): await ctx.send(embed=build_help_embed(ctx.author.id))

@bot.command(name="downtime")
async def downtime_prefix(ctx):
    if ctx.author.id != MY_ID: return
    bot.downtime = not bot.downtime
    await ctx.send(f"Global AI Maintenance: **{'ON' if bot.downtime else 'OFF'}**")

@bot.command(name="blacklist")
async def blacklist_prefix(ctx, target: discord.User):
    if ctx.author.id != MY_ID: return
    if target.id in bot.db["blacklist"]:
        bot.db["blacklist"].remove(target.id)
        await ctx.send(f"Restored AI access for {target.mention}.")
    else:
        bot.db["blacklist"].append(target.id)
        await ctx.send(f"Suspended AI access for {target.mention}.")
    save_data(bot.db)

@bot.command(name="award")
async def award_prefix(ctx, target: discord.User, amount: int):
    if ctx.author.id != MY_ID: return
    bot.update_balance(target.id, amount)
    await ctx.send(f"Added {amount} DDR to {target.mention}'s pocket.")

@bot.command(name="gift")
async def gift_prefix(ctx, target: discord.User, amount: int):
    if amount <= 0: return await ctx.send("Amount must be positive.")
    if bot.get_balance(ctx.author.id) < amount: return await ctx.send("You don't have enough cash.")
    bot.update_balance(ctx.author.id, -amount)
    bot.update_balance(target.id, amount)
    await ctx.send(f"Sent {amount} DDR to {target.mention}!")

@bot.command(name="leaderboard")
async def leaderboard_prefix(ctx):
    sorted_ledger = sorted(bot.db["economy"].items(), key=lambda x: x[1].get("balance", 0), reverse=True)
    lines = [f"`#{i+1}` <@{uid}> - **{data.get('balance', 0)} DDR**" for i, (uid, data) in enumerate(sorted_ledger[:10])]
    embed = discord.Embed(title="🏆 Richest Players Leaderboard", description="\n".join(lines) or "Empty market.", color=0x2b2d31)
    await ctx.send(embed=embed)

# --- SLASH COMMAND ADMINISTRATIVE INTERFACES ---
@bot.tree.command(name="help", description="View lists of all working commands.")
async def help_slash(interaction: discord.Interaction):
    await interaction.response.send_message(embed=build_help_embed(interaction.user.id))

@bot.tree.command(name="downtime", description="Freeze AI bot systems (Owner Only).")
async def downtime_slash(interaction: discord.Interaction):
    if interaction.user.id != MY_ID: return await interaction.response.send_message("Denied.", ephemeral=True)
    bot.downtime = not bot.downtime
    await interaction.response.send_message(f"AI functions: **{'Disabled' if bot.downtime else 'Enabled'}**")

@bot.tree.command(name="blacklist", description="Block a user from requesting AI tasks (Owner Only).")
async def blacklist_slash(interaction: discord.Interaction, target: discord.User):
    if interaction.user.id != MY_ID: return await interaction.response.send_message("Denied.", ephemeral=True)
    if target.id in bot.db["blacklist"]:
        bot.db["blacklist"].remove(target.id)
        msg = f"Allowed {target.name}."
    else:
        bot.db["blacklist"].append(target.id)
        msg = f"Blocked {target.name}."
    save_data(bot.db)
    await interaction.response.send_message(msg)

@bot.tree.command(name="award", description="Spawn cash out of nowhere (Owner Only).")
async def award_slash(interaction: discord.Interaction, target: discord.User, amount: int):
    if interaction.user.id != MY_ID: return await interaction.response.send_message("Denied.", ephemeral=True)
    bot.update_balance(target.id, amount)
    await interaction.response.send_message(f"Gave {amount} DDR to {target.mention}.")

# --- DUDUCOIN STOCK MARKET SCHEDULER ---
@bot.tree.group(name="stock", description="Interact with the Duducoin Stock Market.")
async def stock_group(interaction: discord.Interaction): pass

@stock_group.command(name="view", description="Check current Duducoin market prices.")
async def stock_view(interaction: discord.Interaction):
    info = bot.db["stocks"]["DUDU"]
    uid = bot._init_user(interaction.user.id)
    my_shares = bot.db["economy"][uid]["shares"]
    embed = discord.Embed(title="📈 Duducoin Stock Exchange", color=0x3498db)
    embed.add_field(name="Current Price", value=f"**{info['price']} DDR** per share", inline=False)
    embed.add_field(name="Your Holdings", value=f"You own **{my_shares}** shares", inline=False)
    embed.set_footer(text="Prices change randomly every hour!")
    await interaction.response.send_message(embed=embed)

@stock_group.command(name="buy", description="Buy shares of Duducoin.")
async def stock_buy(interaction: discord.Interaction, shares: int):
    if shares <= 0: return await interaction.response.send_message("Invalid amount.", ephemeral=True)
    uid = bot._init_user(interaction.user.id)
    price = bot.db["stocks"]["DUDU"]["price"]
    total_cost = int(price * shares)
    
    if bot.db["economy"][uid]["balance"] < total_cost:
        return await interaction.response.send_message(f"You can't afford this! Total cost is {total_cost} DDR.", ephemeral=True)
        
    bot.db["economy"][uid]["balance"] -= total_cost
    bot.db["economy"][uid]["shares"] += shares
    save_data(bot.db)
    await interaction.response.send_message(f"Bought **{shares}** DUDU shares for **{total_cost} DDR**!")

@stock_group.command(name="sell", description="Sell your Duducoin shares back for cash.")
async def stock_sell(interaction: discord.Interaction, shares: int):
    if shares <= 0: return await interaction.response.send_message("Invalid amount.", ephemeral=True)
    uid = bot._init_user(interaction.user.id)
    my_shares = bot.db["economy"][uid]["shares"]
    
    if shares > my_shares:
        return await interaction.response.send_message(f"You only have {my_shares} shares to sell.", ephemeral=True)
        
    price = bot.db["stocks"]["DUDU"]["price"]
    payout = int(price * shares)
    
    bot.db["economy"][uid]["shares"] -= shares
    bot.db["economy"][uid]["balance"] += payout
    save_data(bot.db)
    await interaction.response.send_message(f"Sold **{shares}** DUDU shares for **{payout} DDR** cash!")

# --- GENERAL ECONOMY PIECES ---
@bot.tree.command(name="daily", description="Claim your free daily allowance.")
async def daily(interaction: discord.Interaction):
    uid = bot._init_user(interaction.user.id)
    now = time.time()
    if now - bot.db["economy"][uid]["last_daily"] >= 86400:
        bot.db["economy"][uid]["balance"] += 300 # Increased to alleviate scarcity
        bot.db["economy"][uid]["last_daily"] = now
        save_data(bot.db)
        await interaction.response.send_message(f"Daily cash claimed! +300 DDR added. Wallet total: {bot.db['economy'][uid]['balance']} DDR.")
    else:
        hours = int((86400 - (now - bot.db["economy"][uid]["last_daily"])) / 3600)
        await interaction.response.send_message(f"Already claimed! Come back in {hours} hours.", ephemeral=True)

@bot.tree.command(name="work", description="Work a secure job to earn cash (5m cooldown).")
async def work(interaction: discord.Interaction):
    uid = bot._init_user(interaction.user.id)
    now = time.time()
    if now - bot.db["economy"][uid]["last_work"] < 300:
        left = int(300 - (now - bot.db["economy"][uid]["last_work"]))
        return await interaction.response.send_message(f"You are exhausted from working! Wait {left} more seconds.", ephemeral=True)
        
    earned = random.randint(30, 80)
    bot.db["economy"][uid]["balance"] += earned
    bot.db["economy"][uid]["last_work"] = now
    save_data(bot.db)
    await interaction.response.send_message(f"You worked hard and earned **{earned} DDR**!")

@bot.tree.command(name="crime", description="Commit a risky street crime. High risk, big payouts! (10m cooldown)")
async def crime(interaction: discord.Interaction):
    uid = bot._init_user(interaction.user.id)
    now = time.time()
    if now - bot.db["economy"][uid]["last_crime"] < 600:
        left = int(600 - (now - bot.db["economy"][uid]["last_crime"]))
        return await interaction.response.send_message(f"The heat is on! Wait {left} more seconds before committing another crime.", ephemeral=True)
        
    bot.db["economy"][uid]["last_crime"] = now
    
    # 45% success chance
    if random.random() < 0.45:
        payout = random.randint(150, 400)
        bot.db["economy"][uid]["balance"] += payout
        save_data(bot.db)
        await interaction.response.send_message(f"💸 Success! You pulled off a clean heist and got away with **{payout} DDR**!")
    else:
        loss = random.randint(80, 180)
        bot.db["economy"][uid]["balance"] = max(0, bot.db["economy"][uid]["balance"] - loss)
        save_data(bot.db)
        await interaction.response.send_message(f"🚓 Busted! You got caught by the cops and dropped **{loss} DDR** while running away.")

@bot.tree.command(name="balance", description="Check your cash, stocks, and loans.")
async def balance(interaction: discord.Interaction):
    uid = bot._init_user(interaction.user.id)
    bal = bot.db["economy"][uid]["balance"]
    loan_amt = bot.db["economy"][uid]["loan_amount"]
    loan_due = bot.db["economy"][uid]["loan_due"]
    shares = bot.db["economy"][uid]["shares"]
    await interaction.response.send_message(embed=build_balance_embed(interaction.user, bal, loan_amt, loan_due, shares))

@bot.tree.command(name="gift", description="Send some cash directly to a friend.")
async def gift_slash(interaction: discord.Interaction, target: discord.User, amount: int):
    if amount <= 0: return await interaction.response.send_message("Invalid total.", ephemeral=True)
    if bot.get_balance(interaction.user.id) < amount: return await interaction.response.send_message("Not enough cash.", ephemeral=True)
    
    bot.update_balance(interaction.user.id, -amount)
    bot.update_balance(target.id, amount)
    await interaction.response.send_message(f"Successfully transferred {amount} DDR to {target.mention}.")

@bot.tree.command(name="leaderboard", description="View server ranking status.")
async def leaderboard_slash(interaction: discord.Interaction):
    sorted_ledger = sorted(bot.db["economy"].items(), key=lambda x: x[1].get("balance", 0), reverse=True)
    lines = [f"`#{i+1}` <@{uid}> - **{data.get('balance', 0)} DDR**" for i, (uid, data) in enumerate(sorted_ledger[:10])]
    embed = discord.Embed(title="🏆 Richest Players Leaderboard", description="\n".join(lines) or "Empty market.", color=0x2b2d31)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="loan", description="Manage borrowing systems.")
@app_commands.choices(action=[
    app_commands.Choice(name="Take out a loan", value="take"),
    app_commands.Choice(name="Repay active loan", value="repay"),
    app_commands.Choice(name="Check loan status", value="status")
])
async def loan_command(interaction: discord.Interaction, action: app_commands.Choice[str], amount: int = None):
    uid = bot._init_user(interaction.user.id)
    user_data = bot.db["economy"][uid]
    
    if action.value == "status":
        if user_data["loan_amount"] > 0:
            rem = int(max(0, user_data["loan_due"] - time.time()) / 3600)
            owed = int(user_data["loan_amount"] * (1 + user_data["loan_interest"]))
            await interaction.response.send_message(f"You owe **{owed} DDR** total. Time remaining: {rem} hours.")
        else:
            await interaction.response.send_message("You have no active loans right now.")
        return
        
    if action.value == "take":
        if amount is None or amount <= 0: return await interaction.response.send_message("Provide an amount.", ephemeral=True)
        if user_data["loan_amount"] > 0: return await interaction.response.send_message("Pay back your current loan first!", ephemeral=True)
        if amount > 1000: return await interaction.response.send_message("Max borrow limit is 1000 DDR.", ephemeral=True)
        
        user_data["loan_amount"] = amount
        user_data["loan_interest"] = 0.15 # 15% interest flat
        user_data["loan_due"] = time.time() + 86400
        user_data["balance"] += amount
        save_data(bot.db)
        await interaction.response.send_message(f"Loan approved! Added +{amount} DDR to your wallet. Repay within 24 hours.")
        
    elif action.value == "repay":
        if user_data["loan_amount"] == 0: return await interaction.response.send_message("You don't owe any money.", ephemeral=True)
        owed = int(user_data["loan_amount"] * (1 + user_data["loan_interest"]))
        if user_data["balance"] < owed: return await interaction.response.send_message(f"You don't have enough cash. You need {owed} DDR.", ephemeral=True)
        
        user_data["balance"] -= owed
        user_data["loan_amount"] = 0
        user_data["loan_due"] = 0
        user_data["loan_interest"] = 0.0
        save_data(bot.db)
        await interaction.response.send_message(f"Loan paid in full! Cleared {owed} DDR from your record.")

# --- CASINO & GAMES ---
@bot.tree.command(name="coinflip", description="Flip a coin for double or nothing.")
@app_commands.choices(choice=[
    app_commands.Choice(name="Heads", value="heads"),
    app_commands.Choice(name="Tails", value="tails")
])
async def coinflip(interaction: discord.Interaction, bet: int, choice: app_commands.Choice[str]):
    if bet <= 0: return await interaction.response.send_message("Invalid bet amount.", ephemeral=True)
    if bot.get_balance(interaction.user.id) < bet: return await interaction.response.send_message("Too poor to afford this bet.", ephemeral=True)
    
    bot.update_balance(interaction.user.id, -bet)
    outcome = random.choice(["heads", "tails"])
    
    if choice.value == outcome:
        bot.update_balance(interaction.user.id, bet * 2)
        await interaction.response.send_message(f"🎉 It landed on **{outcome.upper()}**! You won **{bet * 2} DDR**!")
    else:
        await interaction.response.send_message(f"❌ It landed on **{outcome.upper()}**! You lost your bet of **{bet} DDR**.")

@bot.tree.command(name="blackjack", description="Open a multiplayer blackjack table lobby.")
async def blackjack(interaction: discord.Interaction, bet: int):
    if bet <= 0: return await interaction.response.send_message("Bet must be positive.", ephemeral=True)
    if bot.get_balance(interaction.user.id) < bet: return await interaction.response.send_message("Insufficient cash.", ephemeral=True)
    
    bot.update_balance(interaction.user.id, -bet)
    view = MultiplayerBlackjackView(interaction.user, bet)
    await interaction.response.send_message(embed=view.generate_embed(), view=view)

@bot.tree.command(name="slots", description="Spin the high risk slot machines.")
async def slots(interaction: discord.Interaction, bet: int):
    if bet <= 0: return await interaction.response.send_message("Invalid bet.", ephemeral=True)
    if bot.get_balance(interaction.user.id) < bet: return await interaction.response.send_message("Too poor.", ephemeral=True)
    
    bot.update_balance(interaction.user.id, -bet)
    symbols = ["🍒", "🍒", "🍒", "🍋", "🍋", "🍇", "🔔", "💎", "7️⃣"]
    s1, s2, s3 = random.choice(symbols), random.choice(symbols), random.choice(symbols)
    
    multiplier = 0
    if s1 == s2 == s3:
        if s1 == "7️⃣": multiplier = 40
        elif s1 == "💎": multiplier = 20
        else: multiplier = 6
    elif s1 == s2 or s2 == s3 or s1 == s3:
        multiplier = 1.5
        
    embed = discord.Embed(title="🎰 Slots Result", color=0x2b2d31)
    embed.add_field(name="Reels", value=f"```\n[ {s1} | {s2} | {s3} ]\n```", inline=False)
    
    if multiplier > 0:
        winnings = int(bet * multiplier)
        bot.update_balance(interaction.user.id, winnings)
        embed.description = f"Winner! Payout: **{winnings} DDR** (x{multiplier})"
        embed.color = 0x2ecc71
    else:
        embed.description = "Bust! Better luck on the next spin."
        embed.color = 0xe74c3c
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="rr", description="Take a risk playing Russian Roulette.")
async def rr(interaction: discord.Interaction):
    if not bot.rr_chamber:
        bot.rr_chamber = [True] + [False] * 5
        random.shuffle(bot.rr_chamber)
        bot.rr_shots_fired = 0
        
    fired = bot.rr_chamber.pop()
    bot.rr_shots_fired += 1
    
    if fired:
        bot.rr_chamber.clear()
        bot.rr_shots_fired = 0
        await interaction.response.send_message(f"💥 **BANG!** {interaction.user.mention} {random.choice(DEATH_LINES)}")
    else:
        await interaction.response.send_message(f"⌖ *Click...* {interaction.user.mention} survived the round safely!")

# --- GENERAL AI INTERACTION ROUTINES ---
@bot.tree.command(name="lawyer", description="Simulate wild courtroom arguments.")
@app_commands.choices(stance=[
    app_commands.Choice(name="Attack", value="against"),
    app_commands.Choice(name="Defend", value="for")
])
async def lawyer(interaction: discord.Interaction, target: discord.User, claim: str, stance: app_commands.Choice[str]):
    if not bot.is_ai_allowed(interaction.user.id): return await interaction.response.send_message("Blocked.", ephemeral=True)
    await interaction.response.defer()
    
    prompt = f"Act as a crazy unhinged lawyer arguing {'against' if stance.value == 'against' else 'in support of'} this claim: '{claim}' by {target.display_name}. Roast anyone in the way."
    text = await bot.generate_raw(prompt)
    await interaction.followup.send(f"**Court Argument:**\n{text[:1900]}")

@bot.tree.command(name="ask", description="Ask the bot a question.")
async def ask(interaction: discord.Interaction, question: str):
    if not bot.is_ai_allowed(interaction.user.id): return await interaction.response.send_message("Blocked.", ephemeral=True)
    await interaction.response.defer()
    text = await bot.generate_raw(f"Answer with pure sass: '{question}'")
    await interaction.followup.send(f"**Q:** {question}\n**A:** {text}")

@bot.tree.command(name="pack", description="Roast a targeted user.")
async def pack(interaction: discord.Interaction, target: discord.User):
    if not bot.is_ai_allowed(interaction.user.id): return await interaction.response.send_message("Blocked.", ephemeral=True)
    if target.id == MY_ID and interaction.user.id != MY_ID: return await interaction.response.send_message("Protected user.", ephemeral=True)
    
    await interaction.response.defer()
    text = await bot.generate_raw(f"Roast this user hard: {target.display_name}")
    bot.user_pack_history[target.id] = text
    await interaction.followup.send(f"{target.mention} {text}")

@bot.tree.command(name="glaze", description="Strategic hype machine.")
async def glaze(interaction: discord.Interaction, target: discord.User):
    if not bot.is_ai_allowed(interaction.user.id): return await interaction.response.send_message("Blocked.", ephemeral=True)
    await interaction.response.defer()
    text = await bot.generate_raw(f"Hype this user up like a god: {target.display_name}", is_glaze=True)
    await interaction.followup.send(f"{target.mention} {text}")

@bot.tree.command(name="lobotomy", description="Generate wild brainrot poem loops.")
async def lobotomy(interaction: discord.Interaction, target: discord.User):
    if not bot.is_ai_allowed(interaction.user.id): return await interaction.response.send_message("Blocked.", ephemeral=True)
    await interaction.response.defer()
    text = await bot.generate_raw(f"Write a funny caps lock brainrot poem about {target.display_name}")
    await interaction.followup.send(text[:2000])

@bot.tree.command(name="crashout", description="Unleash an unhinged string rant.")
async def crashout(interaction: discord.Interaction, target: discord.User):
    if not bot.is_ai_allowed(interaction.user.id): return await interaction.response.send_message("Blocked.", ephemeral=True)
    await interaction.response.defer()
    await interaction.followup.send("Launching crashout script...")
    
    text = await bot.generate_raw(f"Rant angrily at {target.display_name}. Split into three pieces with '|||'.")
    parts = [p.strip() for p in text.split('|||') if p.strip()]
    for part in parts[:3]:
        async with interaction.channel.typing():
            await asyncio.sleep(1.2)
            await interaction.channel.send(f"{target.mention} {part}")

# --- UTILITY HOOK CLUSTERS ---
@bot.tree.command(name="hijack", description="Swap visual messages when a user talks.")
async def hijack(interaction: discord.Interaction, target: discord.User, status: str, custom_text: str = None):
    if target.id == MY_ID: return await interaction.response.send_message("Access denied.", ephemeral=True)
    if status.lower() == "on":
        bot.hijack_targets[target.id] = custom_text
        await interaction.response.send_message(f"Hijack routing set up on {target.name}.")
    else:
        bot.hijack_targets.pop(target.id, None)
        await interaction.response.send_message(f"Hijack cut from {target.name}.")

@bot.tree.command(name="flashbang", description="Spam a specific link fast.")
async def flashbang(interaction: discord.Interaction, status: str, gif_url: str = None):
    cid = interaction.channel_id
    if status.lower() == "on":
        if not gif_url: return await interaction.response.send_message("Missing URL link.", ephemeral=True)
        if f"gif_{cid}" in bot.active_tasks: return await interaction.response.send_message("Task already running.")
        await interaction.response.send_message("Activated.")
        async def worker():
            while True:
                try: 
                    await interaction.channel.send(gif_url)
                    await asyncio.sleep(1.0)
                except: break
        bot.active_tasks[f"gif_{cid}"] = asyncio.create_task(worker())
    else:
        key = f"gif_{cid}"
        if key in bot.active_tasks:
            bot.active_tasks[key].cancel()
            del bot.active_tasks[key]
            await interaction.response.send_message("Deactivated flashbang.")

@bot.tree.command(name="haunt", description="Spam simple insults to someone's direct messages.")
async def haunt(interaction: discord.Interaction, target: discord.User, status: str):
    if target.id == MY_ID and interaction.user.id != MY_ID: return await interaction.response.send_message("Blocked.", ephemeral=True)
    if status.lower() == "on":
        bot.haunt_targets.add(target.id)
        await interaction.response.send_message(f"Haunting process initiated on {target.name}.")
        async def worker():
            try: dm = await target.create_dm()
            except: return
            while target.id in bot.haunt_targets:
                try:
                    await dm.send(random.choice(INSULTS))
                    await asyncio.sleep(2.5)
                except: break
        asyncio.create_task(worker())
    else:
        bot.haunt_targets.discard(target.id)
        await interaction.response.send_message(f"Stopped haunting {target.name}.")

@bot.tree.command(name="quote", description="Fake a message block clone.")
async def quote(interaction: discord.Interaction, target: discord.User, message: str):
    await interaction.response.defer(ephemeral=True)
    try:
        wh = bot.webhook_cache.get(interaction.channel_id)
        if not wh:
            webhooks = await interaction.channel.webhooks()
            wh = discord.utils.get(webhooks, name="Packbot_Quote") or await interaction.channel.create_webhook(name="Packbot_Quote")
            bot.webhook_cache[interaction.channel_id] = wh
        await wh.send(content=message, username=target.display_name, avatar_url=target.display_avatar.url)
        await interaction.followup.send("Sent.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)

if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)
