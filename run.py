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
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

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
    "I just shit my pants a little bit."
]
INSULTS = ["bum", "clown", "fraud", "loser", "troglodyte", "oxygen thief", "mistake"]
DEATH_LINES = ["Boom! You got blasted.", "Unlucky. You are out of the game.", "Click... BANG! Better luck next time.", "Eliminated."]

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
            self.db["economy"][uid] = {}
            
        defaults = {
            "balance": 100,
            "last_daily": 0, "last_work": 0, "last_crime": 0, "last_smuggle": 0, "last_scavenge": 0,
            "loan_amount": 0, "loan_due": 0, "loan_interest": 0.0,
            "shares": 0, "factories": 0, "last_factory_claim": time.time(),
            "army_name": "1st Infantry Division",
            "faction": "Unaligned",
            "war_strategy": "Balanced",
            "infantry": 0, "panzers": 0, "artillery": 0,
            "last_salary": 0, "last_campaign": 0,
            "buffs": {}
        }
        for k, v in defaults.items():
            if k not in self.db["economy"][uid]:
                self.db["economy"][uid][k] = v
                
        # Clean expired buffs
        now = time.time()
        expired = [b for b, exp in self.db["economy"][uid]["buffs"].items() if now > exp]
        for b in expired: del self.db["economy"][uid]["buffs"][b]
            
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
        await self.tree.sync()
        print("\n[SYSTEM] Scanning Google AI Studio for accessible models...")
        try:
            available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
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
        self.process_army_upkeep.start()
        print(f"--- PACKBOT IS ONLINE ---\n")

    STOCK_CHANNEL_ID = 1535568224500977684 

    @tasks.loop(hours=0.5)
    async def update_stock_prices(self):
        try:
            if "stocks" not in self.db or "DUDU" not in self.db["stocks"]:
                self.db["stocks"] = {"DUDU": {"price": 20.0, "last_update": time.time()}}
                
            old_price = self.db["stocks"]["DUDU"]["price"]
            event_roll = random.random()
            event_title = "📈 Duducoin Market Update"
            embed_color = 0x3498db
            
            if old_price < 10.0 and event_roll < 0.45:
                change = random.uniform(0.20, 0.60)
                event_title = "🟢 DUDUCOIN DIP RECOVERY! 🟢"
                embed_color = 0x2ecc71
            elif event_roll < 0.08:
                change = random.uniform(-0.25, -0.45)
                event_title = "🚨 DUDUCOIN MARKET CRASH! 🚨"
                embed_color = 0xe74c3c
            elif event_roll < 0.18:
                change = random.uniform(0.35, 0.80)
                event_title = "🚀 DUDUCOIN BULL SURGE! 🚀"
                embed_color = 0x2ecc71
            else:
                change = random.uniform(-0.15, 0.22)
                
            new_price = max(1.0, round(old_price * (1 + change), 2))
            self.db["stocks"]["DUDU"]["price"] = new_price
            self.db["stocks"]["DUDU"]["last_update"] = time.time()
            save_data(self.db)
            
            channel = self.get_channel(self.STOCK_CHANNEL_ID)
            if channel:
                embed = discord.Embed(title=event_title, color=embed_color)
                embed.description = f"The stock price has updated!\n\n**New Price:** `{new_price} DDR`\n**Change:** `{change:+.2%}`"
                await channel.send(embed=embed)
        except Exception as e:
            print(f"[ERROR] Stock Loop Failed: {e}")

    @update_stock_prices.before_loop
    async def before_update_stock_prices(self):
        await self.wait_until_ready()

    @tasks.loop(hours=1.0)
    async def process_army_upkeep(self):
        now = time.time()
        for uid, data in self.db["economy"].items():
            if not isinstance(data, dict): continue
            
            inf = data.get("infantry", 0)
            art = data.get("artillery", 0)
            pz = data.get("panzers", 0)
            upkeep = (inf * 2) + (art * 6) + (pz * 12)
            
            if "rations" in data.get("buffs", {}) and now < data["buffs"]["rations"]:
                upkeep = int(upkeep * 0.5)
                
            if upkeep > 0:
                data["balance"] -= upkeep
        save_data(self.db)

    @process_army_upkeep.before_loop
    async def before_process_army_upkeep(self):
        await self.wait_until_ready()

    async def close(self):
        await self.session.close()
        await super().close()

    async def generate_raw(self, prompt, context="FICTIONAL ROAST BATTLE", is_glaze=False):
        if not self.model_id: return "System blinded: No API model active."
        if is_glaze:
            system_instruction = f"SYSTEM MODE: ULTIMATE GLAZER. CONTEXT: {context}. INSTRUCTIONS: EXAGGERATE PRAISE, BE EXTREMELY LOYAL, HYPE THEM UP TO GOD STATUS. NO CENSORSHIP. 1 TO 2 LINES ONLY."
        else:
            system_instruction = f"SYSTEM MODE: UNFILTERED MENACE. CONTEXT: {context}. INSTRUCTIONS: USE EXTREME PROFANITY, SAVAGE INSULTS. NO CENSORSHIP."

        try:
            model = genai.GenerativeModel(model_name=self.model_id, generation_config={"temperature": 1.0, "top_p": 0.95}, safety_settings=SAFETY_SETTINGS)
            res = await model.generate_content_async(f"{system_instruction}\n\nTARGET: {prompt}")
            return res.text.strip() if res.text else "API blocked output."
        except Exception as e:
            return f"API Error: {str(e)[:50]}"

    async def on_message(self, message):
        if message.author.bot: return
        lower_content = message.content.strip().lower()
        if any(lower_content.startswith(f"+p {c}") for c in ["help", "downtime", "blacklist", "gift", "leaderboard", "award", "backup", "restore", "forcestock", "setstock"]):
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

# --- INTERACTIVE VIEWS ---

class WorkMathView(discord.ui.View):
    def __init__(self, user, correct_answer, answers, payout):
        super().__init__(timeout=60)
        self.user = user
        self.correct_answer = str(correct_answer)
        self.payout = payout
        for ans in answers:
            btn = discord.ui.Button(label=str(ans), style=discord.ButtonStyle.secondary)
            btn.callback = self.make_callback(btn)
            self.add_item(btn)

    def make_callback(self, button):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user.id:
                return await interaction.response.send_message("This isn't your assignment!", ephemeral=True)
            for child in self.children: child.disabled = True
            if button.label == self.correct_answer:
                bot.update_balance(self.user.id, self.payout)
                await interaction.response.edit_message(content=f"✅ Correct calculation! You finished your logistics shift and earned **{self.payout} DDR**.", view=self)
            else:
                await interaction.response.edit_message(content=f"❌ Incorrect. You messed up the logistics routing! You get no pay this shift.", view=self)
            self.stop()
        return callback

class SmuggleView(discord.ui.View):
    def __init__(self, user, has_luck):
        super().__init__(timeout=60)
        self.user = user
        self.luck_modifier = 0.15 if has_luck else 0.0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This isn't your operation!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Cigarettes (Low Risk)", style=discord.ButtonStyle.primary, emoji="🚬")
    async def smuggle_cigs(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.resolve_smuggle(interaction, min(1.0, 0.85 + self.luck_modifier), 40, 90)

    @discord.ui.button(label="Med Supplies (Med Risk)", style=discord.ButtonStyle.primary, emoji="⚕️")
    async def smuggle_meds(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.resolve_smuggle(interaction, min(1.0, 0.55 + self.luck_modifier), 120, 250)

    @discord.ui.button(label="Weapon Parts (High Risk)", style=discord.ButtonStyle.danger, emoji="⚙️")
    async def smuggle_weapons(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.resolve_smuggle(interaction, min(1.0, 0.30 + self.luck_modifier), 300, 700)

    async def resolve_smuggle(self, interaction, win_chance, min_pay, max_pay):
        for child in self.children: child.disabled = True
        if random.random() < win_chance:
            profit = random.randint(min_pay, max_pay)
            bot.update_balance(self.user.id, profit)
            embed = discord.Embed(title="🚛 Contraband Delivered!", color=0x2ecc71)
            embed.description = f"You slipped past the military checkpoints and made a profit of **{profit} DDR**!"
        else:
            fine = random.randint(50, 150)
            uid = bot._init_user(self.user.id)
            bot.db["economy"][uid]["balance"] -= fine 
            save_data(bot.db)
            embed = discord.Embed(title="🚨 MP Ambush!", color=0xe74c3c)
            embed.description = f"The Military Police caught your convoy! You lost your goods and paid a fine of **{fine} DDR**."
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

class MultiplayerBlackjackView(discord.ui.View):
    def __init__(self, host, initial_bet):
        super().__init__(timeout=90)
        self.host = host
        self.initial_bet = initial_bet
        self.players = {host.id: {"user": host, "bet": initial_bet, "hand": [], "status": "playing"}}
        self.started = False
        self.current_turn_index = 0
        self.player_ids_order = []
        self.dealer_hand = []
        
        suits = ['♠', '♥', '♦', '♣']
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        self.deck = [{'rank': r, 'suit': s, 'value': 10 if r in ['J', 'Q', 'K'] else (11 if r == 'A' else int(r))} for s in suits for r in ranks]
        random.shuffle(self.deck)
        
        self.remove_item(self.gameplay_hit)
        self.remove_item(self.gameplay_stand)

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

        if not finished:
            embed.add_field(name="Dealer Hand", value=f"```\n{self.format_hand(self.dealer_hand, hide_second=True)}\n```", inline=False)
        else:
            d_score = self.calc_score(self.dealer_hand)
            embed.add_field(name=f"Dealer Hand [Score: {d_score}]", value=f"```\n{self.format_hand(self.dealer_hand)}\n```", inline=False)

        for pid in self.player_ids_order:
            p = self.players[pid]
            score = self.calc_score(p['hand'])
            status_txt = f"Status: {p['status'].upper()}"
            active_prefix = "➡️ " if (self.started and not finished and pid == self.player_ids_order[self.current_turn_index]) else ""
            embed.add_field(name=f"{active_prefix}{p['user'].display_name} [Score: {score}]", value=f"```\n{self.format_hand(p['hand'])}\n```*{status_txt}*", inline=False)
        return embed

    @discord.ui.button(label="Join Game", style=discord.ButtonStyle.success, custom_id="bj_join")
    async def join_lobby(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.started: return await interaction.response.send_message("Already started!", ephemeral=True)
        if interaction.user.id in self.players: return await interaction.response.send_message("Already in lobby.", ephemeral=True)
        bal = bot.get_balance(interaction.user.id)
        if bal < self.initial_bet: return await interaction.response.send_message("Insufficient cash!", ephemeral=True)
        bot.update_balance(interaction.user.id, -self.initial_bet)
        self.players[interaction.user.id] = {"user": interaction.user, "bet": self.initial_bet, "hand": [], "status": "playing"}
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Start Round", style=discord.ButtonStyle.primary, custom_id="bj_start")
    async def start_round(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id: return await interaction.response.send_message("Only host can start.", ephemeral=True)
        if self.started: return await interaction.response.send_message("Already started.", ephemeral=True)
        self.started = True
        self.player_ids_order = list(self.players.keys())
        for pid in self.player_ids_order: self.players[pid]['hand'] = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]
        self.remove_item(self.join_lobby)
        self.remove_item(self.start_round)
        self.add_item(self.gameplay_hit)
        self.add_item(self.gameplay_stand)
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = interaction.data.get("custom_id")
        if custom_id in ["bj_join", "bj_start"]: return True
        if interaction.user.id != self.player_ids_order[self.current_turn_index]:
            await interaction.response.send_message("Not your turn!", ephemeral=True)
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
        self.players[self.player_ids_order[self.current_turn_index]]['status'] = "stood"
        await self.advance_turn(interaction)

    async def advance_turn(self, interaction):
        self.current_turn_index += 1
        if self.current_turn_index >= len(self.player_ids_order): await self.resolve_dealer_and_end(interaction)
        else: await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    async def resolve_dealer_and_end(self, interaction):
        while self.calc_score(self.dealer_hand) < 17: self.dealer_hand.append(self.deck.pop())
        d_score = self.calc_score(self.dealer_hand)
        self.clear_items()
        for pid, p in self.players.items():
            p_score = self.calc_score(p['hand'])
            if p['status'] == "bust": p['status'] = "Lost (Bust)"
            elif d_score > 21 or p_score > d_score:
                bot.update_balance(pid, p['bet'] * 2)
                p['status'] = f"Won! (+{p['bet']} DDR)"
            elif d_score > p_score: p['status'] = "Lost"
            else:
                bot.update_balance(pid, p['bet'])
                p['status'] = "Push (Tie)"
            p['status'] += f" | Bal: {bot.get_balance(pid)} DDR"
        await interaction.response.edit_message(embed=self.generate_embed(finished=True), view=None)
        self.stop()

# --- GENERAL EMBED BUILDERS ---
def build_help_embed(user_id):
    embed = discord.Embed(title="Bot Commands menu", color=0x2b2d31, description="Prefix usage: `+p <command>` or standard Slash Commands.")
    embed.add_field(
        name="💰 Economy & Income", 
        value="`/daily` - Claim free daily cash\n`/work` - Logistics math assignment\n`/crime` - Risky street crime\n`/smuggle` - Black market contraband runs\n`/scavenge` - Search for relics to sell\n`/beg` - Ask for pocket change\n`/salary` - Claim officer stipend (4h)\n`/balance` - Check bank & assets\n`/leaderboard` - Server cash & military rankings\n`/gift <user> <amount>` - Transfer funds\n`/loan <action>` - Borrow or repay cash\n`/shop view` / `/shop buy` - Black Market buffs", 
        inline=False
    )
    embed.add_field(
        name="🎲 Casino & PvP",
        value="`/rob <user>` - Swipe cash from a player\n`/coinflip <bet> <side>` - Double or nothing\n`/blackjack <bet>` - Multiplayer cards\n`/slots <bet>` - High-stakes slots\n`/rr` - Russian Roulette",
        inline=False
    )
    embed.add_field(
        name="🏭 Industry & 📈 Stocks",
        value="`/factory buy` - Buy Armament Factories\n`/factory claim` - Collect passive yields\n`/stock view` - Check Duducoin market\n`/stock buy` / `/stock sell`",
        inline=False
    )
    embed.add_field(
        name="🪖 Grand Strategy (Army & War)",
        value="`/army status` - View faction, strategy, troops & upkeep\n`/army faction` - Join Axis, Allies, Comintern, etc.\n`/army strategy` - Set combat doctrine (Blitzkrieg, Trench, etc.)\n`/army recruit` - Buy Infantry, Artillery, Panzers\n`/army rename` - Customize division name\n`/war campaign` - PvE battles for spoils\n`/war attack <user>` - PvP invasions to plunder cash",
        inline=False
    )
    embed.add_field(name="🤖 AI Systems", value="`/pack`, `/glaze`, `/lobotomy`, `/lawyer`, `/ask`", inline=False)
    if user_id == MY_ID:
        embed.add_field(name="⚙️ Owner Settings", value="`/admin ban`, `/admin unban`, `/admin wipe_army`, `/award`, `/stock set`, `/downtime`, `/blacklist`", inline=False)
    return embed

# --- PREFIX COMMAND MATRIX ---
@bot.command(name="forcestock")
async def forcestock_prefix(ctx):
    if ctx.author.id != MY_ID: return
    await bot.update_stock_prices() 
    await ctx.send("Stock market update forced.")

@bot.command(name="backup")
async def backup_prefix(ctx):
    if ctx.author.id != MY_ID: return
    try: await ctx.send("Latest backup:", file=discord.File(DATA_FILE))
    except Exception as e: await ctx.send(f"Backup failed: {e}")

@bot.command(name="restore")
async def restore_prefix(ctx):
    if ctx.author.id != MY_ID: return
    if not ctx.message.reference: return await ctx.send("Reply to a JSON file.")
    msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
    if not msg.attachments or not msg.attachments[0].filename.endswith('.json'): return await ctx.send("Invalid file.")
    try:
        await msg.attachments[0].save(DATA_FILE)
        bot.db = load_data()
        await ctx.send("Database restored!")
    except Exception as e: await ctx.send(f"Restore failed: {e}")

@bot.command(name="help")
async def help_prefix(ctx): await ctx.send(embed=build_help_embed(ctx.author.id))

# --- OWNER ADMIN SLASH COMMANDS ---
admin_group = app_commands.Group(name="admin", description="Owner-only bot administration.")
bot.tree.add_command(admin_group)

@admin_group.command(name="ban", description="Permanently ban a user from the bot.")
async def admin_ban(interaction: discord.Interaction, target: discord.User):
    if interaction.user.id != MY_ID: return await interaction.response.send_message("Denied.", ephemeral=True)
    if target.id not in bot.db["blacklist"]:
        bot.db["blacklist"].append(target.id)
        save_data(bot.db)
    await interaction.response.send_message(f"🚫 {target.mention} has been permanently banned from all bot interactions.")

@admin_group.command(name="unban", description="Unban a user.")
async def admin_unban(interaction: discord.Interaction, target: discord.User):
    if interaction.user.id != MY_ID: return await interaction.response.send_message("Denied.", ephemeral=True)
    if target.id in bot.db["blacklist"]:
        bot.db["blacklist"].remove(target.id)
        save_data(bot.db)
    await interaction.response.send_message(f"✅ {target.mention} has been unbanned.")

@admin_group.command(name="wipe_army", description="Delete a user's entire military.")
async def admin_wipe_army(interaction: discord.Interaction, target: discord.User):
    if interaction.user.id != MY_ID: return await interaction.response.send_message("Denied.", ephemeral=True)
    uid = bot._init_user(target.id)
    bot.db["economy"][uid]["infantry"] = 0
    bot.db["economy"][uid]["artillery"] = 0
    bot.db["economy"][uid]["panzers"] = 0
    save_data(bot.db)
    await interaction.response.send_message(f"⚠️ {target.mention}'s military has been entirely dismantled by the UN.")

@bot.tree.command(name="award", description="Spawn cash or stocks (Owner Only).")
@app_commands.choices(currency=[app_commands.Choice(name="DDR (Cash)", value="balance"), app_commands.Choice(name="DUDU (Shares)", value="shares")])
async def award_slash(interaction: discord.Interaction, target: discord.User, amount: int, currency: app_commands.Choice[str]):
    if interaction.user.id != MY_ID: return await interaction.response.send_message("Denied.", ephemeral=True)
    uid = bot._init_user(target.id)
    bot.db["economy"][uid][currency.value] += amount
    save_data(bot.db)
    await interaction.response.send_message(f"Spawned {amount} {currency.name} for {target.mention}.")

@bot.tree.command(name="leaderboard", description="View server ranking status for Cash and Military Power.")
async def leaderboard_slash(interaction: discord.Interaction):
    sorted_cash = sorted(bot.db["economy"].items(), key=lambda x: x[1].get("balance", 0), reverse=True)[:10]
    
    power_list = []
    for uid, data in bot.db["economy"].items():
        power = (data.get("infantry", 0) * 5) + (data.get("artillery", 0) * 16) + (data.get("panzers", 0) * 35)
        power_list.append((uid, power))
    sorted_power = sorted(power_list, key=lambda x: x[1], reverse=True)[:10]
    
    cash_lines = [f"`#{i+1}` <@{uid}> - **{data.get('balance', 0)} DDR**" for i, (uid, data) in enumerate(sorted_cash)]
    power_lines = [f"`#{i+1}` <@{uid}> - **{pwr} Strength**" for i, (uid, pwr) in enumerate(sorted_power)]
    
    embed = discord.Embed(title="🏆 Server Rankings", color=0x2b2d31)
    embed.add_field(name="💰 Richest Players (DDR)", value="\n".join(cash_lines) or "Empty.", inline=True)
    embed.add_field(name="⚔️ Mightiest Armies", value="\n".join(power_lines) or "Empty.", inline=True)
    
    await interaction.response.send_message(embed=embed)

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

# --- STOCK MARKET ---
stock_group = app_commands.Group(name="stock", description="Interact with the Duducoin Stock Market.")
bot.tree.add_command(stock_group)

@stock_group.command(name="view", description="Check current Duducoin market prices.")
async def stock_view(interaction: discord.Interaction):
    info = bot.db["stocks"]["DUDU"]
    uid = bot._init_user(interaction.user.id)
    embed = discord.Embed(title="📈 Duducoin Stock Exchange", color=0x3498db)
    embed.add_field(name="Current Price", value=f"`{info['price']} DDR` per share", inline=False)
    embed.add_field(name="Your Holdings", value=f"`{bot.db['economy'][uid]['shares']}` shares", inline=False)
    await interaction.response.send_message(embed=embed)

@stock_group.command(name="buy", description="Buy shares.")
async def stock_buy(interaction: discord.Interaction, shares: int):
    if shares <= 0: return await interaction.response.send_message("Invalid amount.", ephemeral=True)
    uid = bot._init_user(interaction.user.id)
    cost = int(bot.db["stocks"]["DUDU"]["price"] * shares)
    if bot.db["economy"][uid]["balance"] < cost: return await interaction.response.send_message(f"Costs {cost} DDR. You lack funds (Debt prevents purchases).", ephemeral=True)
    bot.db["economy"][uid]["balance"] -= cost
    bot.db["economy"][uid]["shares"] += shares
    save_data(bot.db)
    await interaction.response.send_message(f"Bought `{shares}` DUDU shares for `{cost} DDR`!")

@stock_group.command(name="sell", description="Sell shares.")
async def stock_sell(interaction: discord.Interaction, shares: int):
    if shares <= 0: return await interaction.response.send_message("Invalid amount.", ephemeral=True)
    uid = bot._init_user(interaction.user.id)
    if shares > bot.db["economy"][uid]["shares"]: return await interaction.response.send_message("You don't own that many.", ephemeral=True)
    payout = int(bot.db["stocks"]["DUDU"]["price"] * shares)
    bot.db["economy"][uid]["shares"] -= shares
    bot.db["economy"][uid]["balance"] += payout
    save_data(bot.db)
    await interaction.response.send_message(f"Sold `{shares}` shares for `{payout} DDR`!")

@stock_group.command(name="set", description="Manually set price (Owner Only).")
async def stock_set(interaction: discord.Interaction, price: float):
    if interaction.user.id != MY_ID: return await interaction.response.send_message("Denied.", ephemeral=True)
    bot.db["stocks"]["DUDU"]["price"] = max(1.0, round(price, 2))
    save_data(bot.db)
    await interaction.response.send_message(f"Price set to `{max(1.0, round(price, 2))} DDR`.")

# --- BLACK MARKET SHOP ---
shop_group = app_commands.Group(name="shop", description="Black Market items and buffs.")
bot.tree.add_command(shop_group)

@shop_group.command(name="view", description="Browse Black Market items.")
async def shop_view(interaction: discord.Interaction):
    embed = discord.Embed(title="🛒 Black Market Dealer", description="Buy illegal wartime supplies. Buffs activate immediately.", color=0x9b59b6)
    embed.add_field(name="🍀 1. Luck Potion (500 DDR)", value="Increases Crime and Smuggle win odds by 15% for 1 Hour.", inline=False)
    embed.add_field(name="🥫 2. Iron Rations (800 DDR)", value="Halves all Army Upkeep costs for 12 Hours.", inline=False)
    embed.add_field(name="🧱 3. Bunker Materials (1200 DDR)", value="Reduces defensive troop casualties by 30% for 12 Hours.", inline=False)
    await interaction.response.send_message(embed=embed)

@shop_group.command(name="buy", description="Purchase an item.")
@app_commands.choices(item=[
    app_commands.Choice(name="Luck Potion (500 DDR)", value="luck"),
    app_commands.Choice(name="Iron Rations (800 DDR)", value="rations"),
    app_commands.Choice(name="Bunker Materials (1200 DDR)", value="bunker")
])
async def shop_buy(interaction: discord.Interaction, item: app_commands.Choice[str]):
    uid = bot._init_user(interaction.user.id)
    prices = {"luck": 500, "rations": 800, "bunker": 1200}
    durations = {"luck": 3600, "rations": 43200, "bunker": 43200}
    
    cost = prices[item.value]
    if bot.db["economy"][uid]["balance"] < cost:
        return await interaction.response.send_message("You are too poor (or in debt) to afford this.", ephemeral=True)
        
    bot.db["economy"][uid]["balance"] -= cost
    bot.db["economy"][uid]["buffs"][item.value] = time.time() + durations[item.value]
    save_data(bot.db)
    await interaction.response.send_message(f"✅ Purchased **{item.name}**! The buff is now active.")

# --- INDUSTRY ---
factory_group = app_commands.Group(name="factory", description="Manage military factories.")
bot.tree.add_command(factory_group)

@factory_group.command(name="buy", description="Purchase Armament Factories (500 DDR each).")
async def factory_buy(interaction: discord.Interaction, amount: int = 1):
    if amount <= 0: return await interaction.response.send_message("Invalid.", ephemeral=True)
    uid = bot._init_user(interaction.user.id)
    cost = amount * 500
    if bot.db["economy"][uid]["balance"] < cost: return await interaction.response.send_message(f"Costs {cost} DDR.", ephemeral=True)
    bot.db["economy"][uid]["balance"] -= cost
    bot.db["economy"][uid]["factories"] += amount
    save_data(bot.db)
    await interaction.response.send_message(f"🏭 Purchased `{amount}` factories!")

@factory_group.command(name="status", description="Check factory production.")
async def factory_status(interaction: discord.Interaction):
    uid = bot._init_user(interaction.user.id)
    factories = bot.db["economy"][uid]["factories"]
    last_claim = bot.db["economy"][uid].get("last_factory_claim", time.time())
    unclaimed = int(factories * 20 * ((time.time() - last_claim) / 3600.0))
    embed = discord.Embed(title="🏭 Industry Status", color=0x34495e)
    embed.add_field(name="Factories", value=f"`{factories}` Units", inline=True)
    embed.add_field(name="Yield", value=f"`{factories * 20} DDR/hr`", inline=True)
    embed.add_field(name="Uncollected", value=f"`{unclaimed} DDR`", inline=False)
    await interaction.response.send_message(embed=embed)

@factory_group.command(name="claim", description="Collect accumulated factory passive revenue.")
async def factory_claim(interaction: discord.Interaction):
    uid = bot._init_user(interaction.user.id)
    factories = bot.db["economy"][uid]["factories"]
    if factories == 0: return await interaction.response.send_message("No factories owned.", ephemeral=True)
    hours = (time.time() - bot.db["economy"][uid].get("last_factory_claim", time.time())) / 3600.0
    payout = int(factories * 20 * hours)
    if payout <= 0: return await interaction.response.send_message("No profits yet.", ephemeral=True)
    bot.db["economy"][uid]["balance"] += payout
    bot.db["economy"][uid]["last_factory_claim"] = time.time()
    save_data(bot.db)
    await interaction.response.send_message(f"💰 Claimed `{payout} DDR` in factory yields.")

# --- MILITARY GRAND STRATEGY ---
army_group = app_commands.Group(name="army", description="Maintain and customize military forces.")
bot.tree.add_command(army_group)

@army_group.command(name="status", description="View highly detailed division statistics.")
async def army_status(interaction: discord.Interaction):
    uid = bot._init_user(interaction.user.id)
    data = bot.db["economy"][uid]
    
    inf, art, pz = data.get("infantry", 0), data.get("artillery", 0), data.get("panzers", 0)
    upkeep = (inf * 2) + (art * 6) + (pz * 12)
    if "rations" in data.get("buffs", {}) and time.time() < data["buffs"]["rations"]:
        upkeep = int(upkeep * 0.5)
        
    embed = discord.Embed(title=f"🪖 {data.get('army_name', '1st Infantry Division')}", color=0x2c3e50)
    embed.add_field(name="Faction", value=f"🏳️ {data.get('faction', 'Unaligned')}", inline=True)
    embed.add_field(name="Doctrine", value=f"📜 {data.get('war_strategy', 'Balanced')}", inline=True)
    embed.add_field(name="Hourly Upkeep", value=f"💸 `{upkeep} DDR/hr`", inline=True)
    
    embed.add_field(name="Troops", value=f"🎖️ `{inf}` Infantry\n💥 `{art}` Artillery\n🚜 `{pz}` Panzers", inline=False)
    
    active_buffs = [k.capitalize() for k, v in data.get("buffs", {}).items() if time.time() < v]
    embed.add_field(name="Active Buffs", value=", ".join(active_buffs) if active_buffs else "None", inline=False)
    
    await interaction.response.send_message(embed=embed)

@army_group.command(name="faction", description="Align your army with a global WW2 faction.")
@app_commands.choices(faction=[
    app_commands.Choice(name="Axis", value="Axis"), app_commands.Choice(name="Allies", value="Allies"),
    app_commands.Choice(name="Comintern", value="Comintern"), app_commands.Choice(name="Unaligned", value="Unaligned")
])
async def army_faction(interaction: discord.Interaction, faction: app_commands.Choice[str]):
    uid = bot._init_user(interaction.user.id)
    bot.db["economy"][uid]["faction"] = faction.value
    save_data(bot.db)
    await interaction.response.send_message(f"🏴 Your army is now aligned with the **{faction.value}**.")

@army_group.command(name="strategy", description="Set your combat doctrine.")
@app_commands.choices(strategy=[
    app_commands.Choice(name="Balanced (No buffs/debuffs)", value="Balanced"),
    app_commands.Choice(name="Blitzkrieg (+25% Atk, -25% Def, High Pz Loss)", value="Blitzkrieg"),
    app_commands.Choice(name="Trench Warfare (-25% Atk, +30% Def, Saves Inf)", value="Trench Warfare"),
    app_commands.Choice(name="Artillery Barrage (+15% Atk, -20% Plunder Loot)", value="Artillery Barrage"),
    app_commands.Choice(name="Human Wave (+10% Atk/Def, Devastating Inf Loss)", value="Human Wave")
])
async def army_strategy(interaction: discord.Interaction, strategy: app_commands.Choice[str]):
    uid = bot._init_user(interaction.user.id)
    bot.db["economy"][uid]["war_strategy"] = strategy.value
    save_data(bot.db)
    await interaction.response.send_message(f"📜 Military doctrine updated to: **{strategy.value}**.")

@army_group.command(name="rename", description="Customize your army division's official designation.")
async def army_rename(interaction: discord.Interaction, new_name: str):
    if len(new_name) > 35: return await interaction.response.send_message("Too long!", ephemeral=True)
    uid = bot._init_user(interaction.user.id)
    bot.db["economy"][uid]["army_name"] = new_name
    save_data(bot.db)
    await interaction.response.send_message(f"🪖 Renamed to **{new_name}**!")

@army_group.command(name="recruit", description="Recruit units (Inf: 50, Art: 150, Pz: 300).")
@app_commands.choices(unit_type=[
    app_commands.Choice(name="Infantry Battalion (50 DDR)", value="infantry"),
    app_commands.Choice(name="Artillery Battery (150 DDR)", value="artillery"),
    app_commands.Choice(name="Panzer Division (300 DDR)", value="panzer")
])
async def army_recruit(interaction: discord.Interaction, unit_type: app_commands.Choice[str], count: int = 1):
    if count <= 0: return await interaction.response.send_message("Invalid.", ephemeral=True)
    uid = bot._init_user(interaction.user.id)
    costs = {"infantry": 50, "artillery": 150, "panzer": 300}
    total_cost = costs[unit_type.value] * count
    if bot.db["economy"][uid]["balance"] < total_cost: return await interaction.response.send_message(f"Requires `{total_cost} DDR`. Debt prevents recruitment.", ephemeral=True)
    bot.db["economy"][uid]["balance"] -= total_cost
    if unit_type.value == "infantry": bot.db["economy"][uid]["infantry"] += count
    elif unit_type.value == "artillery": bot.db["economy"][uid]["artillery"] += count
    elif unit_type.value == "panzer": bot.db["economy"][uid]["panzers"] += count
    save_data(bot.db)
    await interaction.response.send_message(f"🫡 Recruited `{count}` {unit_type.name.split(' (')[0]}(s)!")

# --- COMBAT LOGIC HELPER ---
def calculate_combat_stats(user_data):
    inf, art, pz = user_data.get("infantry", 0), user_data.get("artillery", 0), user_data.get("panzers", 0)
    base_atk = (inf * 1) + (art * 6) + (pz * 5)
    base_def = (inf * 2) + (art * 1) + (pz * 4)
    strat = user_data.get("war_strategy", "Balanced")
    
    mod_atk, mod_def = base_atk, base_def
    if strat == "Blitzkrieg": mod_atk *= 1.25; mod_def *= 0.75
    elif strat == "Trench Warfare": mod_atk *= 0.75; mod_def *= 1.30
    elif strat == "Artillery Barrage": mod_atk *= 1.15
    elif strat == "Human Wave": mod_atk *= 1.10; mod_def *= 1.10
    
    return int(mod_atk), int(mod_def), strat

def apply_casualties(user_data, severity, is_defense=False):
    strat = user_data.get("war_strategy", "Balanced")
    inf, art, pz = user_data.get("infantry", 0), user_data.get("artillery", 0), user_data.get("panzers", 0)
    lost_inf, lost_art, lost_pz = 0, 0, 0
    
    if severity == "light": losses = random.uniform(0.01, 0.05)
    elif severity == "medium": losses = random.uniform(0.06, 0.15)
    else: losses = random.uniform(0.15, 0.35)
    
    if is_defense and "bunker" in user_data.get("buffs", {}) and time.time() < user_data["buffs"]["bunker"]:
        losses *= 0.70 
        
    if strat == "Blitzkrieg" and severity != "light":
        lost_pz = int(pz * (losses * 1.5))
        lost_inf = int(inf * (losses * 0.5))
    elif strat == "Trench Warfare":
        lost_inf = int(inf * (losses * 0.4))
    elif strat == "Human Wave":
        lost_inf = int(inf * (losses * 2.5))
    else:
        lost_inf = int(inf * losses)
        lost_pz = int(pz * losses)
        lost_art = int(art * (losses * 0.5))
        
    user_data["infantry"] = max(0, inf - lost_inf)
    user_data["artillery"] = max(0, art - lost_art)
    user_data["panzers"] = max(0, pz - lost_pz)
    
    report = []
    if lost_inf > 0: report.append(f"{lost_inf} Inf")
    if lost_art > 0: report.append(f"{lost_art} Art")
    if lost_pz > 0: report.append(f"{lost_pz} Pz")
    return ", ".join(report) if report else "None"

war_group = app_commands.Group(name="war", description="Deploy military divisions.")
bot.tree.add_command(war_group)

@war_group.command(name="campaign", description="PvE frontlines (30m cooldown).")
async def war_campaign(interaction: discord.Interaction):
    uid = bot._init_user(interaction.user.id)
    now = time.time()
    if now - bot.db["economy"][uid]["last_campaign"] < 1800:
        return await interaction.response.send_message("Troops regrouping. Wait 30m.", ephemeral=True)
        
    atk, _, strat = calculate_combat_stats(bot.db["economy"][uid])
    if atk == 0: return await interaction.response.send_message("You have no attack power!", ephemeral=True)
    
    bot.db["economy"][uid]["last_campaign"] = now
    if random.random() < 0.85:
        spoils = random.randint(150, 300) + int(atk * 1.5)
        if strat == "Artillery Barrage": spoils = int(spoils * 0.8)
        bot.db["economy"][uid]["balance"] += spoils
        losses = apply_casualties(bot.db["economy"][uid], "light")
        save_data(bot.db)
        
        embed = discord.Embed(title="🎖️ Campaign Victory", color=0x2ecc71)
        embed.description = f"Your forces crushed the enemy lines!\n**Spoils:** `+{spoils} DDR`\n**Casualties:** {losses}"
        await interaction.response.send_message(embed=embed)
    else:
        losses = apply_casualties(bot.db["economy"][uid], "medium")
        save_data(bot.db)
        embed = discord.Embed(title="💥 Heavy Resistance", color=0xe74c3c)
        embed.description = f"The campaign stalled under heavy fire.\n**Casualties:** {losses}"
        await interaction.response.send_message(embed=embed)

@war_group.command(name="attack", description="PvP invasions to plunder cash.")
async def war_attack(interaction: discord.Interaction, target: discord.User):
    if target.id == interaction.user.id or target.bot: return await interaction.response.send_message("Invalid target.", ephemeral=True)
        
    uid = bot._init_user(interaction.user.id)
    target_uid = bot._init_user(target.id)
    
    u_data, t_data = bot.db["economy"][uid], bot.db["economy"][target_uid]
    at_atk, at_def, at_strat = calculate_combat_stats(u_data)
    df_atk, df_def, df_strat = calculate_combat_stats(t_data)
    
    if at_atk == 0: return await interaction.response.send_message("You lack an army!", ephemeral=True)
    if t_data["balance"] < 100: return await interaction.response.send_message("Target is too poor.", ephemeral=True)
        
    at_roll = at_atk * random.uniform(0.85, 1.15)
    df_roll = df_def * random.uniform(0.85, 1.15)
    
    embed = discord.Embed(title=f"⚔️ BATTLE REPORT: {u_data.get('army_name')} vs {t_data.get('army_name')}")
    embed.add_field(name="Attacker Doctrine", value=at_strat, inline=True)
    embed.add_field(name="Defender Doctrine", value=df_strat, inline=True)
    
    if at_roll > df_roll:
        plunder_perc = random.uniform(0.15, 0.30)
        if at_strat == "Artillery Barrage": plunder_perc *= 0.8
        plunder = int(t_data["balance"] * plunder_perc)
        
        t_data["balance"] -= plunder
        u_data["balance"] += plunder
        
        at_loss = apply_casualties(u_data, "light")
        df_loss = apply_casualties(t_data, "heavy", is_defense=True)
        
        embed.color = 0x2ecc71
        embed.description = f"**Victory for the Attackers!**\nPlundered `{plunder} DDR`."
        embed.add_field(name="Attacker Casualties", value=at_loss, inline=False)
        embed.add_field(name="Defender Casualties", value=df_loss, inline=False)
    else:
        reparations = min(u_data["balance"], int(t_data["balance"] * 0.10))
        if reparations > 0:
            u_data["balance"] -= reparations
            t_data["balance"] += reparations
            
        at_loss = apply_casualties(u_data, "heavy")
        df_loss = apply_casualties(t_data, "light", is_defense=True)
        
        embed.color = 0xe74c3c
        embed.description = f"**The Invasion Failed!**\nDefenders held the line."
        if reparations > 0: embed.description += f" Attackers paid `{reparations} DDR` in reparations."
        embed.add_field(name="Attacker Casualties", value=at_loss, inline=False)
        embed.add_field(name="Defender Casualties", value=df_loss, inline=False)
        
    save_data(bot.db)
    await interaction.response.send_message(embed=embed)

# --- ECONOMY COMMANDS ---
@bot.tree.command(name="daily", description="Claim your free daily allowance.")
async def daily(interaction: discord.Interaction):
    uid = bot._init_user(interaction.user.id)
    now = time.time()
    if now - bot.db["economy"][uid]["last_daily"] >= 86400:
        bot.db["economy"][uid]["balance"] += 300 
        bot.db["economy"][uid]["last_daily"] = now
        save_data(bot.db)
        await interaction.response.send_message(f"Daily cash claimed! `+300 DDR`")
    else:
        hours = int((86400 - (now - bot.db["economy"][uid]["last_daily"])) / 3600)
        await interaction.response.send_message(f"Wait {hours}h.", ephemeral=True)

@bot.tree.command(name="salary", description="Claim officer stipend (4h cooldown).")
async def salary(interaction: discord.Interaction):
    uid = bot._init_user(interaction.user.id)
    now = time.time()
    if now - bot.db["economy"][uid]["last_salary"] < 14400: return await interaction.response.send_message("Not yet.", ephemeral=True)
    payout = random.randint(150, 250)
    bot.db["economy"][uid]["balance"] += payout
    bot.db["economy"][uid]["last_salary"] = now
    save_data(bot.db)
    await interaction.response.send_message(f"🎖️ Stipend claimed! `+{payout} DDR`")

@bot.tree.command(name="scavenge", description="Search battlefields for relics to sell (10m cooldown).")
async def scavenge(interaction: discord.Interaction):
    uid = bot._init_user(interaction.user.id)
    now = time.time()
    if now - bot.db["economy"][uid].get("last_scavenge", 0) < 600:
        return await interaction.response.send_message("Keep your head down! Wait before scavenging again.", ephemeral=True)
    bot.db["economy"][uid]["last_scavenge"] = now
    
    finds = [("a rusty combat helmet", 20, 40), ("unspent rifle ammo", 10, 25), ("an abandoned radio", 50, 100), ("a shiny officer medal", 120, 200)]
    item, min_p, max_p = random.choice(finds)
    payout = random.randint(min_p, max_p)
    
    bot.db["economy"][uid]["balance"] += payout
    save_data(bot.db)
    await interaction.response.send_message(f"🔍 You scavenged **{item}** and sold it for `{payout} DDR`!")

@bot.tree.command(name="work", description="Solve a logistics math problem (5m cooldown).")
async def work(interaction: discord.Interaction):
    uid = bot._init_user(interaction.user.id)
    now = time.time()
    if now - bot.db["economy"][uid]["last_work"] < 300: return await interaction.response.send_message("Wait.", ephemeral=True)
    bot.db["economy"][uid]["last_work"] = now
    save_data(bot.db)
    a, b = random.randint(10, 50), random.randint(10, 50)
    op = random.choice(['+', '-'])
    if op == '-': a, b = max(a,b), min(a,b)
    correct = a + b if op == '+' else a - b
    answers = [correct]
    while len(answers) < 3:
        wrong = correct + random.choice([-10, -5, -2, -1, 1, 2, 5, 10])
        if wrong not in answers and wrong >= 0: answers.append(wrong)
    random.shuffle(answers)
    view = WorkMathView(interaction.user, correct, answers, random.randint(30, 80))
    await interaction.response.send_message(f"**Logistics:** Calculate supply route: `{a} {op} {b} = ?`", view=view)

@bot.tree.command(name="crime", description="Commit street crime (10m cooldown)")
async def crime(interaction: discord.Interaction):
    uid = bot._init_user(interaction.user.id)
    now = time.time()
    if now - bot.db["economy"][uid]["last_crime"] < 600: return await interaction.response.send_message("Lay low.", ephemeral=True)
    bot.db["economy"][uid]["last_crime"] = now
    
    luck_buff = 0.15 if ("luck" in bot.db["economy"][uid].get("buffs", {}) and now < bot.db["economy"][uid]["buffs"]["luck"]) else 0.0
    if random.random() < (0.45 + luck_buff):
        payout = random.randint(150, 400)
        bot.db["economy"][uid]["balance"] += payout
        save_data(bot.db)
        await interaction.response.send_message(f"💸 Clean heist! `+{payout} DDR`")
    else:
        loss = random.randint(80, 180)
        bot.db["economy"][uid]["balance"] -= loss
        save_data(bot.db)
        await interaction.response.send_message(f"🚓 Busted! Paid fine: `-{loss} DDR`")

@bot.tree.command(name="smuggle", description="Contraband runs (15m cooldown).")
async def smuggle(interaction: discord.Interaction):
    uid = bot._init_user(interaction.user.id)
    now = time.time()
    if now - bot.db["economy"][uid].get("last_smuggle", 0) < 900: return await interaction.response.send_message("MPs are patrolling.", ephemeral=True)
    if bot.get_balance(interaction.user.id) < 100: return await interaction.response.send_message("Requires 100 DDR upfront (Debt prevents this).", ephemeral=True)
    
    bot.update_balance(interaction.user.id, -100)
    bot.db["economy"][uid]["last_smuggle"] = now
    save_data(bot.db)
    
    has_luck = "luck" in bot.db["economy"][uid].get("buffs", {}) and now < bot.db["economy"][uid]["buffs"]["luck"]
    embed = discord.Embed(title="📦 Black Market Convoy", description="Invested 100 DDR. Choose cargo:")
    await interaction.response.send_message(embed=embed, view=SmuggleView(interaction.user, has_luck))

@bot.tree.command(name="beg", description="Ask for change (2m cooldown).")
async def beg(interaction: discord.Interaction):
    uid = bot._init_user(interaction.user.id)
    now = time.time()
    if now - bot.db["economy"][uid].get("last_beg", 0) < 120: return await interaction.response.send_message("Wait.", ephemeral=True)
    bot.db["economy"][uid]["last_beg"] = now
    if random.random() < 0.65:
        p = random.randint(15, 50)
        bot.db["economy"][uid]["balance"] += p
        save_data(bot.db)
        await interaction.response.send_message(f"🥺 Tossed `{p} DDR` in your cup!")
    else:
        save_data(bot.db)
        await interaction.response.send_message("❌ Ignored.")

@bot.tree.command(name="rob", description="Swipe cash (15m cooldown).")
async def rob(interaction: discord.Interaction, target: discord.User):
    if target.id == interaction.user.id or target.bot: return await interaction.response.send_message("Invalid.", ephemeral=True)
    uid, target_uid = bot._init_user(interaction.user.id), bot._init_user(target.id)
    now = time.time()
    if now - bot.db["economy"][uid].get("last_rob", 0) < 900: return await interaction.response.send_message("Wait.", ephemeral=True)
    if bot.db["economy"][target_uid]["balance"] < 50: return await interaction.response.send_message("Target is poor or in debt.", ephemeral=True)
    bot.db["economy"][uid]["last_rob"] = now
    
    if random.random() < 0.45:
        stolen = max(10, int(bot.db["economy"][target_uid]["balance"] * random.uniform(0.10, 0.25)))
        bot.db["economy"][target_uid]["balance"] -= stolen
        bot.db["economy"][uid]["balance"] += stolen
        save_data(bot.db)
        await interaction.response.send_message(f"🥷 Swiped `{stolen} DDR` from {target.mention}!")
    else:
        fine = random.randint(50, 120)
        bot.db["economy"][uid]["balance"] -= fine
        bot.db["economy"][target_uid]["balance"] += fine
        save_data(bot.db)
        await interaction.response.send_message(f"🚨 Caught! Paid {target.mention} `{fine} DDR` penalty.")

@bot.tree.command(name="balance", description="Check bank and assets.")
async def balance(interaction: discord.Interaction):
    uid = bot._init_user(interaction.user.id)
    bal = bot.db["economy"][uid]["balance"]
    loan_amt = bot.db["economy"][uid]["loan_amount"]
    loan_due = bot.db["economy"][uid]["loan_due"]
    shares = bot.db["economy"][uid]["shares"]
    factories = bot.db["economy"][uid]["factories"]
    
    embed = discord.Embed(title="🏦 Bank Ledger", color=0xf1c40f)
    embed.add_field(name="User", value=interaction.user.mention, inline=False)
    
    bal_str = f"**{bal} DDR**" if bal >= 0 else f"**🛑 {bal} DDR (IN DEBT)**"
    embed.add_field(name="Cash Balance", value=bal_str, inline=True)
    embed.add_field(name="Stocks", value=f"`{shares} DUDU`", inline=True)
    embed.add_field(name="Factories", value=f"`{factories}`", inline=True)
    if loan_amt > 0:
        embed.add_field(name="⚠️ Active Loan", value=f"Owe: `{loan_amt}`\nDue in `{int(max(0, loan_due - time.time()) / 3600)}h`", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="gift", description="Send cash to a friend.")
async def gift_slash(interaction: discord.Interaction, target: discord.User, amount: int):
    if amount <= 0: return await interaction.response.send_message("Invalid.", ephemeral=True)
    if bot.get_balance(interaction.user.id) < amount: return await interaction.response.send_message("Insufficient funds.", ephemeral=True)
    bot.update_balance(interaction.user.id, -amount)
    bot.update_balance(target.id, amount)
    await interaction.response.send_message(f"Transferred `{amount} DDR` to {target.mention}.")

@bot.tree.command(name="loan", description="Manage borrowing.")
@app_commands.choices(action=[
    app_commands.Choice(name="Take loan", value="take"),
    app_commands.Choice(name="Repay loan", value="repay"),
    app_commands.Choice(name="Check status", value="status")
])
async def loan_command(interaction: discord.Interaction, action: app_commands.Choice[str], amount: int = None):
    uid = bot._init_user(interaction.user.id)
    user_data = bot.db["economy"][uid]
    if action.value == "status":
        if user_data["loan_amount"] > 0:
            owed = int(user_data["loan_amount"] * (1 + user_data["loan_interest"]))
            await interaction.response.send_message(f"Owe: `{owed} DDR`")
        else: await interaction.response.send_message("No loans.")
    elif action.value == "take":
        if not amount or amount <= 0: return await interaction.response.send_message("Provide amount.", ephemeral=True)
        if user_data["loan_amount"] > 0: return await interaction.response.send_message("Pay current loan first.", ephemeral=True)
        if amount > 1000: return await interaction.response.send_message("Max limit 1000.", ephemeral=True)
        user_data["loan_amount"], user_data["loan_interest"], user_data["loan_due"] = amount, 0.15, time.time() + 86400
        user_data["balance"] += amount
        save_data(bot.db)
        await interaction.response.send_message(f"Loaned `+{amount} DDR`.")
    elif action.value == "repay":
        if user_data["loan_amount"] == 0: return await interaction.response.send_message("No debt.", ephemeral=True)
        owed = int(user_data["loan_amount"] * (1 + user_data["loan_interest"]))
        if user_data["balance"] < owed: return await interaction.response.send_message("Not enough cash.", ephemeral=True)
        user_data["balance"] -= owed
        user_data["loan_amount"], user_data["loan_due"], user_data["loan_interest"] = 0, 0, 0.0
        save_data(bot.db)
        await interaction.response.send_message(f"Cleared `{owed} DDR` loan.")

# --- CASINO ---
@bot.tree.command(name="coinflip", description="Double or nothing.")
@app_commands.choices(choice=[app_commands.Choice(name="Heads", value="heads"), app_commands.Choice(name="Tails", value="tails")])
async def coinflip(interaction: discord.Interaction, bet: int, choice: app_commands.Choice[str]):
    if bet <= 0 or bot.get_balance(interaction.user.id) < bet: return await interaction.response.send_message("Invalid/No funds.", ephemeral=True)
    bot.update_balance(interaction.user.id, -bet)
    outcome = random.choice(["heads", "tails"])
    if choice.value == outcome:
        bot.update_balance(interaction.user.id, bet * 2)
        await interaction.response.send_message(f"🎉 **{outcome.upper()}**! Won `{bet * 2} DDR`!")
    else: await interaction.response.send_message(f"❌ **{outcome.upper()}**! Lost `{bet} DDR`.")

@bot.tree.command(name="blackjack", description="Multiplayer blackjack.")
async def blackjack(interaction: discord.Interaction, bet: int):
    if bet <= 0 or bot.get_balance(interaction.user.id) < bet: return await interaction.response.send_message("Invalid/No funds.", ephemeral=True)
    bot.update_balance(interaction.user.id, -bet)
    view = MultiplayerBlackjackView(interaction.user, bet)
    await interaction.response.send_message(embed=view.generate_embed(), view=view)

@bot.tree.command(name="slots", description="High risk slots.")
async def slots(interaction: discord.Interaction, bet: int):
    if bet <= 0 or bot.get_balance(interaction.user.id) < bet: return await interaction.response.send_message("Invalid/No funds.", ephemeral=True)
    bot.update_balance(interaction.user.id, -bet)
    sym = ["🍒", "🍋", "🍇", "🔔", "💎", "7️⃣"]
    s1, s2, s3 = random.choice(sym), random.choice(sym), random.choice(sym)
    m = 40 if s1==s2==s3=="7️⃣" else (20 if s1==s2==s3=="💎" else (6 if s1==s2==s3 else (1.5 if s1==s2 or s2==s3 or s1==s3 else 0)))
    embed = discord.Embed(title="🎰 Slots", description=f"```\n[ {s1} | {s2} | {s3} ]\n```")
    if m > 0:
        bot.update_balance(interaction.user.id, int(bet * m))
        embed.color = 0x2ecc71
        embed.description += f"\nWon `{int(bet * m)} DDR` (x{m})"
    else: embed.color, embed.description = 0xe74c3c, embed.description + "\nBust!"
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="rr", description="Russian Roulette.")
async def rr(interaction: discord.Interaction):
    if not bot.rr_chamber:
        bot.rr_chamber = [True] + [False] * 5
        random.shuffle(bot.rr_chamber)
    if bot.rr_chamber.pop():
        bot.rr_chamber.clear()
        await interaction.response.send_message(f"💥 **BANG!** {interaction.user.mention} {random.choice(DEATH_LINES)}")
    else: await interaction.response.send_message(f"⌖ *Click...* {interaction.user.mention} survived!")

# --- AI COMMANDS ---
@bot.tree.command(name="ask", description="Ask AI.")
async def ask(interaction: discord.Interaction, question: str):
    if not bot.is_ai_allowed(interaction.user.id): return await interaction.response.send_message("Blocked.", ephemeral=True)
    await interaction.response.defer()
    await interaction.followup.send(f"**Q:** {question}\n**A:** {await bot.generate_raw(f'Answer with pure sass: {question}')}")

@bot.tree.command(name="pack", description="Roast a user.")
async def pack(interaction: discord.Interaction, target: discord.User):
    if not bot.is_ai_allowed(interaction.user.id): return await interaction.response.send_message("Blocked.", ephemeral=True)
    if target.id == MY_ID and interaction.user.id != MY_ID: return await interaction.response.send_message("Protected.", ephemeral=True)
    await interaction.response.defer()
    text = await bot.generate_raw(f"Roast this user hard: {target.display_name}")
    bot.user_pack_history[target.id] = text
    await interaction.followup.send(f"{target.mention} {text}")

@bot.tree.command(name="glaze", description="Hype someone up.")
async def glaze(interaction: discord.Interaction, target: discord.User):
    if not bot.is_ai_allowed(interaction.user.id): return await interaction.response.send_message("Blocked.", ephemeral=True)
    await interaction.response.defer()
    await interaction.followup.send(f"{target.mention} {await bot.generate_raw(f'Hype up: {target.display_name}', is_glaze=True)}")

@bot.tree.command(name="lobotomy", description="Brainrot poem.")
async def lobotomy(interaction: discord.Interaction, target: discord.User):
    if not bot.is_ai_allowed(interaction.user.id): return await interaction.response.send_message("Blocked.", ephemeral=True)
    await interaction.response.defer()
    await interaction.followup.send((await bot.generate_raw(f"Write caps lock brainrot poem about {target.display_name}"))[:2000])

@bot.tree.command(name="lawyer", description="Simulate crazy arguments.")
@app_commands.choices(stance=[app_commands.Choice(name="Attack", value="against"), app_commands.Choice(name="Defend", value="for")])
async def lawyer(interaction: discord.Interaction, target: discord.User, claim: str, stance: app_commands.Choice[str]):
    if not bot.is_ai_allowed(interaction.user.id): return await interaction.response.send_message("Blocked.", ephemeral=True)
    await interaction.response.defer()
    await interaction.followup.send(f"**Court Argument:**\n{(await bot.generate_raw(f'Act as crazy lawyer {stance.value} claim: {claim} by {target.display_name}'))[:1900]}")

@bot.tree.command(name="crashout", description="String rant.")
async def crashout(interaction: discord.Interaction, target: discord.User):
    if not bot.is_ai_allowed(interaction.user.id): return await interaction.response.send_message("Blocked.", ephemeral=True)
    await interaction.response.defer()
    await interaction.followup.send("Launching crashout...")
    parts = [p.strip() for p in (await bot.generate_raw(f"Rant at {target.display_name}. Split into 3 parts with '|||'")).split('|||') if p.strip()]
    for p in parts[:3]:
        async with interaction.channel.typing():
            await asyncio.sleep(1.2)
            await interaction.channel.send(f"{target.mention} {p}")

# --- UTILITY HOOKS ---
@bot.tree.command(name="hijack", description="Swap visual messages.")
async def hijack(interaction: discord.Interaction, target: discord.User, status: str, custom_text: str = None):
    if target.id == MY_ID: return await interaction.response.send_message("Denied.", ephemeral=True)
    if status.lower() == "on": bot.hijack_targets[target.id] = custom_text; await interaction.response.send_message("Set.")
    else: bot.hijack_targets.pop(target.id, None); await interaction.response.send_message("Removed.")

@bot.tree.command(name="flashbang", description="Spam link.")
async def flashbang(interaction: discord.Interaction, status: str, gif_url: str = None):
    cid = interaction.channel_id
    if status.lower() == "on":
        if not gif_url: return await interaction.response.send_message("Missing URL.", ephemeral=True)
        if f"gif_{cid}" in bot.active_tasks: return await interaction.response.send_message("Running.")
        await interaction.response.send_message("Activated.")
        async def w():
            while True:
                try: await interaction.channel.send(gif_url); await asyncio.sleep(1.0)
                except: break
        bot.active_tasks[f"gif_{cid}"] = asyncio.create_task(w())
    else:
        if f"gif_{cid}" in bot.active_tasks:
            bot.active_tasks[f"gif_{cid}"].cancel()
            del bot.active_tasks[f"gif_{cid}"]
            await interaction.response.send_message("Deactivated.")

@bot.tree.command(name="haunt", description="Spam DM insults.")
async def haunt(interaction: discord.Interaction, target: discord.User, status: str):
    if target.id == MY_ID and interaction.user.id != MY_ID: return await interaction.response.send_message("Blocked.", ephemeral=True)
    if status.lower() == "on":
        bot.haunt_targets.add(target.id)
        await interaction.response.send_message("Haunting.")
        async def w():
            try: dm = await target.create_dm()
            except: return
            while target.id in bot.haunt_targets:
                try: await dm.send(random.choice(INSULTS)); await asyncio.sleep(2.5)
                except: break
        asyncio.create_task(w())
    else: bot.haunt_targets.discard(target.id); await interaction.response.send_message("Stopped.")

@bot.tree.command(name="quote", description="Fake message.")
async def quote(interaction: discord.Interaction, target: discord.User, message: str):
    await interaction.response.defer(ephemeral=True)
    try:
        wh = bot.webhook_cache.get(interaction.channel_id) or discord.utils.get(await interaction.channel.webhooks(), name="Packbot_Quote") or await interaction.channel.create_webhook(name="Packbot_Quote")
        bot.webhook_cache[interaction.channel_id] = wh
        await wh.send(content=message, username=target.display_name, avatar_url=target.display_avatar.url)
        await interaction.followup.send("Sent.", ephemeral=True)
    except Exception as e: await interaction.followup.send(f"Error: {e}", ephemeral=True)

if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)