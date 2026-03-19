import logging
import random
import re
import asyncio
import aiohttp
import aiosqlite
from datetime import datetime
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode, ChatMemberStatus

# ========== ТВОИ ДАННЫЕ ==========
BOT_TOKEN = "8621288234:AAHnKXRfCkRDKe4XoMmaY5-5IOgM3LjNHkU"
CHANNEL_LINK = "https://t.me/+WLiiYR7_ymZjYWY1"
CHANNEL_ID = -1003256576224
YOUR_TELEGRAM_ID = 571001160
ADMIN_ID = YOUR_TELEGRAM_ID

# ========== НАСТРОЙКИ ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== БАЗА ДАННЫХ ==========
DB_FILE = 'bot_database.db'

# === Бан-лист ===
INITIAL_BLACKLIST = [
    "@giftrelayer", "@mrktbank", "@kallent", "@monk", "@durov",
    "@virusgift", "@portalsrelayer", "@lucha", "@snoopdogg", "@snoop",
    "@ufc", "@nft", "@telegram", "@nftgift", "@nftgiftbot", "@ton", "@trade_relayer",
    "@rolls_transfer", "@GiftsToPortals", "@gemsrelayer", "@GiftDeposit", "@depgifts"
]

async def init_blacklist_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS blacklist (
                username TEXT PRIMARY KEY
            )
        ''')
        await db.commit()
    logging.info("✅ Таблица blacklist создана")

async def init_default_blacklist():
    async with aiosqlite.connect(DB_FILE) as db:
        for username in INITIAL_BLACKLIST:
            await db.execute(
                "INSERT OR IGNORE INTO blacklist (username) VALUES (?)",
                (username.lower(),)
            )
        await db.commit()
    logging.info(f"✅ Добавлено {len(INITIAL_BLACKLIST)} релеев")

async def get_blacklist() -> list[str]:
    try:
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute("SELECT username FROM blacklist") as cursor:
                return [row[0] for row in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"Ошибка получения бан-листа: {e}")
        return []

# === Настройки пользователей ===
async def init_user_settings_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                results_count INTEGER DEFAULT 20
            )
        ''')
        await db.commit()
    logging.info("✅ Таблица user_settings создана")

async def get_user_settings(user_id: int) -> dict:
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT results_count FROM user_settings WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {'results_count': row[0]}
            else:
                return {'results_count': 20}

async def save_user_settings(user_id: int, results_count: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, results_count) VALUES (?, ?)",
            (user_id, results_count)
        )
        await db.commit()

# ========== ФУНКЦИИ ПАРСИНГА ==========
async def parse_gift_owner(session: aiohttp.ClientSession, url: str) -> str | None:
    try:
        async with session.get(url, timeout=10, allow_redirects=False) as response:
            if response.status != 200:
                return None
            html = await response.text()
            soup = BeautifulSoup(html, "html.parser")
            
            owner_tag = soup.select_one('table.tgme_gift_table th:-soup-contains("Owner") + td a')
            if owner_tag and owner_tag.get('href'):
                username = owner_tag['href'].replace('https://t.me/', '')
                if re.match(r'^[a-zA-Z0-9_]{5,32}$', username):
                    return f"@{username}"
            
            owner_link = soup.find('a', href=lambda x: x and x.startswith('https://t.me/') and not any(
                skip in x for skip in ['nft', 'gift', 'joinchat']))
            if owner_link:
                username = owner_link['href'].replace('https://t.me/', '')
                if re.match(r'^[a-zA-Z0-9_]{5,32}$', username):
                    return f"@{username}"
            
            text = soup.get_text()
            match = re.search(r'@([a-zA-Z0-9_]{5,32})', text)
            if match:
                username = match.group(1)
                return f"@{username}"
                
            return None
    except Exception as e:
        logger.debug(f"Ошибка парсинга {url}: {e}")
        return None

async def find_real_owners_batch(gifts: list, target_count: int, title: str, status_message) -> list:
    blacklist = await get_blacklist()
    blacklist_lower = [u.lower() for u in blacklist]
    found = []
    total = len(gifts)
    batch_size = 20
    
    async with aiohttp.ClientSession() as session:
        for i in range(0, total, batch_size):
            batch = gifts[i:i+batch_size]
            tasks = [parse_gift_owner(session, gift['url']) for gift in batch]
            results = await asyncio.gather(*tasks)
            
            for gift, owner in zip(batch, results):
                if owner and owner.strip() and owner.lower() not in blacklist_lower:
                    found.append({
                        'name': gift['name'],
                        'url': gift['url'],
                        'owner': owner
                    })
                    if status_message and len(found) <= target_count:
                        try:
                            progress = min(len(found) / target_count, 1.0)
                            filled = int(progress * 10)
                            bar = "▰" * filled + "▱" * (10 - filled)
                            await status_message.edit_text(
                                f"{title}\n"
                                f"📝 Шаблон: Стандартный\n"
                                f"🔢 Количество: {target_count}\n"
                                f"⚠️ Примечание: Поиск может ошибаться\n\n"
                                f"🔍 {bar} Поиск NFT...\n"
                                f"✅ Найдено: {len(found)}/{target_count}",
                                parse_mode=ParseMode.HTML
                            )
                        except:
                            pass
                    if len(found) >= target_count:
                        return found
            await asyncio.sleep(0.1)
    return found[:target_count]

# ========== ПОЛНЫЙ СПИСОК NFT ==========
NFT_LIST = [
    {"name": "BDayCandle", "difficulty": "easy", "id_range": "1000-20000", "min_id": 1000, "max_id": 20000},
    {"name": "CandyCane", "difficulty": "easy", "id_range": "1000-150000", "min_id": 1000, "max_id": 150000},
    {"name": "CloverPin", "difficulty": "easy", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "DeskCalendar", "difficulty": "easy", "id_range": "1000-13000", "min_id": 1000, "max_id": 13000},
    {"name": "FaithAmulet", "difficulty": "easy", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "FreshSocks", "difficulty": "easy", "id_range": "1000-100000", "min_id": 1000, "max_id": 100000},
    {"name": "GingerCookie", "difficulty": "easy", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "HappyBrownie", "difficulty": "easy", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "HolidayDrink", "difficulty": "easy", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "HomemadeCake", "difficulty": "easy", "id_range": "1000-130000", "min_id": 1000, "max_id": 130000},
    {"name": "IceCream", "difficulty": "easy", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "InstantRamen", "difficulty": "easy", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "JesterHat", "difficulty": "easy", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "JingleBells", "difficulty": "easy", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "LolPop", "difficulty": "easy", "id_range": "1000-130000", "min_id": 1000, "max_id": 130000},
    {"name": "LunarSnake", "difficulty": "easy", "id_range": "1000-250000", "min_id": 1000, "max_id": 250000},
    {"name": "PetSnake", "difficulty": "easy", "id_range": "1000-1000", "min_id": 1000, "max_id": 1000},
    {"name": "SnakeBox", "difficulty": "easy", "id_range": "1000-55000", "min_id": 1000, "max_id": 55000},
    {"name": "SnoopDogg", "difficulty": "easy", "id_range": "576241-576241", "min_id": 576241, "max_id": 576241},
    {"name": "SpicedWine", "difficulty": "easy", "id_range": "93557-93557", "min_id": 93557, "max_id": 93557},
    {"name": "WhipCupcake", "difficulty": "easy", "id_range": "1000-170000", "min_id": 1000, "max_id": 170000},
    {"name": "WinterWreath", "difficulty": "easy", "id_range": "65311-65311", "min_id": 65311, "max_id": 65311},
    {"name": "XmasStocking", "difficulty": "easy", "id_range": "177478-177478", "min_id": 177478, "max_id": 177478},
    {"name": "BerryBox", "difficulty": "medium", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "BigYear", "difficulty": "medium", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "BowTie", "difficulty": "medium", "id_range": "1000-47000", "min_id": 1000, "max_id": 47000},
    {"name": "BunnyMuffin", "difficulty": "medium", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "CookieHeart", "difficulty": "medium", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "EasterEgg", "difficulty": "medium", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "EternalCandle", "difficulty": "medium", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "EvilEye", "difficulty": "medium", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "HexPot", "difficulty": "medium", "id_range": "1000-50000", "min_id": 1000, "max_id": 50000},
    {"name": "HypnoLollipop", "difficulty": "medium", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "InputKey", "difficulty": "medium", "id_range": "1000-80000", "min_id": 1000, "max_id": 80000},
    {"name": "JackInTheBox", "difficulty": "medium", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "JellyBunny", "difficulty": "medium", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "JollyChimp", "difficulty": "medium", "id_range": "1000-25000", "min_id": 1000, "max_id": 25000},
    {"name": "JoyfulBundle", "difficulty": "medium", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "LightSword", "difficulty": "medium", "id_range": "1000-110000", "min_id": 1000, "max_id": 110000},
    {"name": "LushBouquet", "difficulty": "medium", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "MousseCake", "difficulty": "medium", "id_range": "119126-119126", "min_id": 119126, "max_id": 119126},
    {"name": "PartySparkler", "difficulty": "medium", "id_range": "161722-161722", "min_id": 161722, "max_id": 161722},
    {"name": "RestlessJar", "difficulty": "medium", "id_range": "1000-23000", "min_id": 1000, "max_id": 23000},
    {"name": "SantaHat", "difficulty": "medium", "id_range": "19289-19289", "min_id": 19289, "max_id": 19289},
    {"name": "SnoopCigar", "difficulty": "medium", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "SnowGlobe", "difficulty": "medium", "id_range": "48029-48029", "min_id": 48029, "max_id": 48029},
    {"name": "SnowMittens", "difficulty": "medium", "id_range": "64057-64057", "min_id": 64057, "max_id": 64057},
    {"name": "SpringBasket", "difficulty": "medium", "id_range": "140160-140160", "min_id": 140160, "max_id": 140160},
    {"name": "SpyAgaric", "difficulty": "medium", "id_range": "84274-84274", "min_id": 84274, "max_id": 84274},
    {"name": "StarNotepad", "difficulty": "medium", "id_range": "1000-25000", "min_id": 1000, "max_id": 25000},
    {"name": "StellarRocket", "difficulty": "medium", "id_range": "1000-35000", "min_id": 1000, "max_id": 35000},
    {"name": "SwagBag", "difficulty": "medium", "id_range": "1000-5000", "min_id": 1000, "max_id": 5000},
    {"name": "TamaGadget", "difficulty": "medium", "id_range": "95205-95205", "min_id": 95205, "max_id": 95205},
    {"name": "ValentineBox", "difficulty": "medium", "id_range": "229868-229868", "min_id": 229868, "max_id": 229868},
    {"name": "WitchHat", "difficulty": "medium", "id_range": "1000-7000", "min_id": 1000, "max_id": 7000},
    {"name": "UFCStrike", "difficulty": "medium", "id_range": "1000-56951", "min_id": 1000, "max_id": 56951},
    {"name": "ArtisanBrick", "difficulty": "hard", "id_range": "1000-7000", "min_id": 1000, "max_id": 7000},
    {"name": "AstralShard", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "BondedRing", "difficulty": "hard", "id_range": "1000-3000", "min_id": 1000, "max_id": 3000},
    {"name": "CupidCharm", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "DiamondRing", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "DurovsCap", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "EternalRose", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "FlyingBroom", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "GemSignet", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "GenieLamp", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "GustalBall", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "HeartLocket", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "HeroicHelmet", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "IonGem", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "IonicDryer", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "KissedFrog", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "LootBag", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "LoveCandle", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "LovePotion", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "LowRider", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "MadPumpkin", "difficulty": "hard", "id_range": "96227-96227", "min_id": 96227, "max_id": 96227},
    {"name": "MagicPotion", "difficulty": "hard", "id_range": "4764-4764", "min_id": 4764, "max_id": 4764},
    {"name": "MightyArm", "difficulty": "hard", "id_range": "150000-150000", "min_id": 150000, "max_id": 150000},
    {"name": "MiniOscar", "difficulty": "hard", "id_range": "4764-4764", "min_id": 4764, "max_id": 4764},
    {"name": "NailBracelet", "difficulty": "hard", "id_range": "119126-119126", "min_id": 119126, "max_id": 119126},
    {"name": "NekoHelmet", "difficulty": "hard", "id_range": "15431-15431", "min_id": 15431, "max_id": 15431},
    {"name": "PerfumeBottle", "difficulty": "hard", "id_range": "151632-151632", "min_id": 151632, "max_id": 151632},
    {"name": "PreciousPeach", "difficulty": "hard", "id_range": "2981-2981", "min_id": 2981, "max_id": 2981},
    {"name": "RecordPlayer", "difficulty": "hard", "id_range": "554-554", "min_id": 554, "max_id": 554},
    {"name": "ScaredCat", "difficulty": "hard", "id_range": "8029-8029", "min_id": 8029, "max_id": 8029},
    {"name": "SharpTongue", "difficulty": "hard", "id_range": "1000-16430", "min_id": 1000, "max_id": 16430},
    {"name": "SignetRing", "difficulty": "hard", "id_range": "1000-16430", "min_id": 1000, "max_id": 16430},
    {"name": "SkullFlower", "difficulty": "hard", "id_range": "1000-21428", "min_id": 1000, "max_id": 21428},
    {"name": "SkyStilettos", "difficulty": "hard", "id_range": "1000-47465", "min_id": 1000, "max_id": 47465},
    {"name": "SleighBell", "difficulty": "hard", "id_range": "1000-48029", "min_id": 1000, "max_id": 48029},
    {"name": "SwissWatch", "difficulty": "hard", "id_range": "1000-25121", "min_id": 1000, "max_id": 25121},
    {"name": "TopHat", "difficulty": "hard", "id_range": "1000-32648", "min_id": 1000, "max_id": 32648},
    {"name": "ToyBear", "difficulty": "hard", "id_range": "1000-60000", "min_id": 1000, "max_id": 60000},
    {"name": "TrappedHeart", "difficulty": "hard", "id_range": "1000-24656", "min_id": 1000, "max_id": 24656},
    {"name": "VintageCigar", "difficulty": "hard", "id_range": "1000-18000", "min_id": 1000, "max_id": 18000},
    {"name": "VoodooDoll", "difficulty": "hard", "id_range": "1000-26658", "min_id": 1000, "max_id": 26658}
]

# ========== ЖЕНСКИЕ NFT ==========
GIRLS_NFT_LIST = [
    "Rose", "EternalRose", "LushBouquet", "SkullFlower", "Cherry", "Peach", 
    "PreciousPeach", "BerryBox", "LoveCandle", "LovePotion", "CupidCharm", 
    "HeartLocket", "TrappedHeart", "KissedFrog", "DiamondRing", "GemSignet", 
    "BondedRing", "SweetCookie", "CookieHeart", "BunnyMuffin", "MousseCake", 
    "PartySparkler", "JoyfulBundle", "SpicedWine", "HolidayDrink", "CandyCane", 
    "GingerCookie", "HappyBrownie", "HomemadeCake", "IceCream", "LolPop", 
    "WhipCupcake", "BowTie", "NailBracelet", "SkyStilettos", "EternalCandle", 
    "FaithAmulet", "EvilEye", "HypnoLollipop", "LightSword", "StarNotepad", 
    "SwagBag", "TamaGadget", "SpringBasket", "SnowGlobe", "SnowMittens", 
    "ValentineBox", "PerfumeBottle", "MagicPotion", "JellyBunny", "PetSnake", 
    "ScaredCat", "NekoHelmet", "ToyBear", "MadPumpkin", "SantaHat", 
    "WinterWreath", "XmasStocking", "JingleBells", "EasterEgg"
]
GIRLS_NFT_LIST = sorted(list(set(GIRLS_NFT_LIST)))

NFT_DICT = {nft["name"]: nft for nft in NFT_LIST}

# ========== ХРАНИЛИЩЕ ==========
user_states = {}
blocked_nfts = {}
last_message_ids = {}
EMOJIS = ["😀", "😎", "🚀", "🎮", "🍕", "🐱", "🌟", "🎯", "💻", "📱", "🎲", "⚡"]

# ========== ПРОВЕРКА ПОДПИСКИ ==========
async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status not in ["left", "kicked"]
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False

async def require_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_subscription(user_id, context):
        await show_subscription_required(update, context)
        return False
    return True

async def show_subscription_required(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📢 Подписаться на канал", url=CHANNEL_LINK)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = "⚠️ Для использования бота подпишитесь на канал!"
    
    if update.callback_query:
        await update.callback_query.message.edit_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)

# ========== ФУНКЦИИ ДЛЯ УДАЛЕНИЯ СООБЩЕНИЙ ==========
async def delete_previous_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in last_message_ids:
        for msg_id in last_message_ids[user_id]:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
            except:
                pass
        last_message_ids[user_id] = []

async def save_message_id(update: Update, message):
    user_id = update.effective_user.id
    if user_id not in last_message_ids:
        last_message_ids[user_id] = []
    last_message_ids[user_id].append(message.message_id)
    if len(last_message_ids[user_id]) > 20:
        old_id = last_message_ids[user_id].pop(0)
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=old_id)
        except:
            pass

# ========== ФУНКЦИИ ГЕНЕРАЦИИ ССЫЛОК ==========
def generate_gift_links(nft_name, count=20):
    nft = NFT_DICT.get(nft_name)
    if not nft:
        return []
    clean_name = re.sub(r"[^\w]", "", nft_name)
    links = []
    for _ in range(count):
        nft_id = random.randint(nft["min_id"], nft["max_id"])
        links.append(f"https://t.me/nft/{clean_name}-{nft_id}")
    return links

def generate_random_gifts(mode="light", count=20):
    if mode == "light":
        available = [n for n in NFT_LIST if n["difficulty"] == "easy"]
    elif mode == "medium":
        available = [n for n in NFT_LIST if n["difficulty"] in ["easy", "medium"]]
    else:
        available = [n for n in NFT_LIST if n["difficulty"] in ["medium", "hard"]]
    if not available:
        available = NFT_LIST
    gifts = []
    for _ in range(count):
        nft = random.choice(available)
        clean_name = re.sub(r"[^\w]", "", nft["name"])
        nft_id = random.randint(nft["min_id"], nft["max_id"])
        gifts.append({"name": nft["name"], "url": f"https://t.me/nft/{clean_name}-{nft_id}"})
    return gifts

def generate_girls_gifts(count=20):
    gifts = []
    for _ in range(count):
        nft_name = random.choice(GIRLS_NFT_LIST)
        nft = NFT_DICT.get(nft_name)
        if nft:
            clean_name = re.sub(r"[^\w]", "", nft_name)
            nft_id = random.randint(nft["min_id"], nft["max_id"])
            gifts.append({"name": nft_name, "url": f"https://t.me/nft/{clean_name}-{nft_id}"})
    return gifts

# ========== ГЛАВНОЕ МЕНЮ ==========
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = f"❗ Привет, @{user.username or 'user'}! Это парсер для поиска мамонтов."
    keyboard = [
        [InlineKeyboardButton("🔍 Поиск NFT", callback_data="menu_search")],
        [InlineKeyboardButton("👤 Мой профиль", callback_data="menu_profile")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="menu_settings")],
        [InlineKeyboardButton("🆘 Поддержка", callback_data="menu_support")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
    else:
        await delete_previous_messages(update, context)
        sent = await update.message.reply_text(text, reply_markup=reply_markup)
        await save_message_id(update, sent)

# ========== КОМАНДА /START ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    settings = await get_user_settings(user_id)
    context.user_data['results_count'] = settings['results_count']
    
    if not await check_subscription(user_id, context):
        keyboard = [[InlineKeyboardButton("📢 Подписаться", url=CHANNEL_LINK)]]
        await update.message.reply_text("⚠️ Подпишись на канал!", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    await show_main_menu(update, context)

# ========== HELP ==========
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_subscription(update, context):
        return
    text = """🆘 СПРАВКА ПО БОТУ

ТРЕБОВАНИЯ:
1. Быть участником канала

КОМАНДЫ:
/start - Начать работу
/help - Справка
/status - Статус
/block <номер> - Заблокировать NFT
/unblock <номер> - Разблокировать NFT
/myblock - Список блокировок"""
    await update.message.reply_text(text)

# ========== STATUS ==========
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_subscription(update, context):
        return
    user_id = update.effective_user.id
    subscribed = await check_subscription(user_id, context)
    text = f"""📊 ВАШ СТАТУС

Подписка: {'✅ В КАНАЛЕ' if subscribed else '❌ НЕТ'}
Поисков: 0
Блокировок: {len(blocked_nfts.get(user_id, []))}"""
    await update.message.reply_text(text)

# ========== МЕНЮ ПОИСКА ==========
async def show_search_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = """Выберите тип поиска:

🎲 Рандом поиск - поиск по режимам (легкий, средний, жирный)
🔍 Поиск по модели - точный поиск по конкретным NFT
👧 Поиск девушек - поиск по женским именам"""
    keyboard = [
        [InlineKeyboardButton("🎲 Рандом поиск", callback_data="search_random")],
        [InlineKeyboardButton("🔍 Поиск по модели", callback_data="search_model")],
        [InlineKeyboardButton("👧 Поиск девушек", callback_data="search_girls")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup)

# ========== МЕНЮ РЕЖИМОВ ==========
async def show_modes_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = """Выберите режим поиска:

🟢 Легкий режим  
  Недорогие подарки до 3 TON  
  Самые неопытные пользователи  

🟡 Средний режим  
  Хорошие подарки от 3 до 15 TON  
  Более опытные пользователи  

🔴 Жирный режим  
  Дорогие подарки от 15 до 600 TON  
  Опытные коллекционеры"""
    keyboard = [
        [InlineKeyboardButton("🟢 Легкий режим", callback_data="mode_light")],
        [InlineKeyboardButton("🟡 Средний режим", callback_data="mode_medium")],
        [InlineKeyboardButton("🔴 Жирный режим", callback_data="mode_heavy")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup)

# ========== ПОДТВЕРЖДЕНИЕ РЕЖИМА ==========
async def show_mode_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE, mode):
    query = update.callback_query
    mode_names = {"light": "🟢 Легкий режим", "medium": "🟡 Средний режим", "heavy": "🔴 Жирный режим"}
    text = f"""Выбран режим: ✅ {mode_names[mode]}
Шаблон: Стандартный

Нажмите кнопку ниже чтобы начать поиск:"""
    keyboard = [
        [InlineKeyboardButton("📌 Начать поиск NFT", callback_data=f"start_search_{mode}")],
        [InlineKeyboardButton("📌 Назад к режимам", callback_data="search_random")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup)

# ========== ПОКАЗ РЕЗУЛЬТАТОВ ==========
async def show_paginated_results(message, found, mode, nft_name, page, title, context):
    items_per_page = 10
    total_pages = (len(found) + items_per_page - 1) // items_per_page
    start = (page - 1) * items_per_page
    end = min(start + items_per_page, len(found))
    page_results = found[start:end]
    
    text = "<b>Результаты поиска</b>\n"
    text += f"📊 Найдено: {len(found)} владельцев\n"
    if title:
        text += f"📌 {title}\n"
    text += f"📄 Страница {page}/{total_pages}\n\n"
    
    for i, item in enumerate(page_results, start=start+1):
        clean_owner = item['owner'][1:] if item['owner'].startswith('@') else item['owner']
        text += f"{i}. @{clean_owner} | <a href=\"tg://resolve?domain={clean_owner}\">Написать</a>\n"
        text += f"   🎁 <a href=\"{item['url']}\">{item['name']}</a>\n\n"
    
    keyboard = []
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"results_page_{mode}_{page-1}_{nft_name or ''}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"results_page_{mode}_{page+1}_{nft_name or ''}"))
        keyboard.append(nav)
    
    if nft_name:
        keyboard.append([InlineKeyboardButton("🔄 Ещё такие же", callback_data=f"more_{mode}_{nft_name}")])
    
    keyboard.append([InlineKeyboardButton("🔄 Новый поиск", callback_data="search_random")])
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    
    await message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

async def show_search_results(update: Update, context, mode, nft_name=None, page=1):
    query = update.callback_query
    user_id = query.from_user.id
    
    settings = await get_user_settings(user_id)
    target_count = settings['results_count']
    
    cache_key = f"{user_id}_{mode}_{nft_name or ''}"
    
    if 'search_results' not in context.user_data:
        context.user_data['search_results'] = {}
    
    if cache_key in context.user_data['search_results'] and page != 1:
        found = context.user_data['search_results'][cache_key]
        await show_paginated_results(query.message, found, mode, nft_name, page, None, context)
        return
    
    generate_count = target_count * 3
    
    if mode == "girls":
        title = "👩 Поиск девушек"
    elif mode == "light":
        title = "🟢 Легкий режим"
    elif mode == "medium":
        title = "🟡 Средний режим"
    elif mode == "heavy":
        title = "🔴 Жирный режим"
    else:
        title = "Поиск"
    
    if nft_name:
        gifts = [{"name": nft_name, "url": url} for url in generate_gift_links(nft_name, generate_count)]
    elif mode == "girls":
        gifts = generate_girls_gifts(generate_count)
    else:
        gifts = generate_random_gifts(mode, generate_count)
    
    status_msg = await query.message.edit_text(
        f"{title}\n"
        f"📝 Шаблон: Стандартный\n"
        f"🔢 Количество: {target_count}\n"
        f"⚠️ Примечание: Поиск может ошибаться\n\n"
        f"🔍 ▱▱▱▱▱▱▱▱▱▱ Поиск NFT...\n"
        f"✅ Найдено: 0/{target_count}",
        parse_mode=ParseMode.HTML
    )
    
    found = await find_real_owners_batch(gifts, target_count, title, status_msg)
    context.user_data['search_results'][cache_key] = found
    
    if not found:
        keyboard = [[InlineKeyboardButton("🔄 Попробовать снова", callback_data="search_random")]]
        await status_msg.edit_text(
            "❌ Не найдено подарков с реальными владельцами.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    await show_paginated_results(status_msg, found, mode, nft_name, page, title, context)

# ========== МЕНЮ ВЫБОРА МОДЕЛИ ==========
async def show_model_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, page=1):
    query = update.callback_query
    items_per_page = 10
    total_pages = (len(NFT_LIST) + items_per_page - 1) // items_per_page
    start = (page - 1) * items_per_page
    end = min(start + items_per_page, len(NFT_LIST))
    page_nfts = NFT_LIST[start:end]
    keyboard = []
    for nft in page_nfts:
        keyboard.append([InlineKeyboardButton(f"🎁 {nft['name']} ({nft['difficulty']})", callback_data=f"select_model_{nft['name']}")])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"model_page_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"model_page_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"🔗 Выберите модель NFT для поиска:\n\nСтраница {page}/{total_pages}"
    await query.message.edit_text(text, reply_markup=reply_markup)

# ========== ПРОФИЛЬ ==========
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    settings = await get_user_settings(user_id)
    text = f"""ID: {user_id}
Имя: @{query.from_user.username or 'unknown'}
Дата регистрации: Неизвестно
Активных дней: 1

СТАТИСТИКА
Всего поисков: 0
Найдено пользователей: 0
Создано шаблонов: 0
Заблокировано NFT: {len(blocked_nfts.get(user_id, []))}

ТЕКУЩИЕ НАСТРОЙКИ
Режим: Легкий режим
Активный шаблон: Стандартный
Лимит поиска: {settings['results_count']}

Последний поиск: Нет данных

Детальная статистика"""
    keyboard = [
        [InlineKeyboardButton("📊 Статистика за неделю", callback_data="profile_weekly")],
        [InlineKeyboardButton("⚡ Быстрые настройки", callback_data="profile_quick")],
        [InlineKeyboardButton("🪞 Создать зеркало", callback_data="profile_mirror")],
        [InlineKeyboardButton("👥 Реферальная система", callback_data="profile_ref")],
        [InlineKeyboardButton("🔒 Приватка для vorkera", callback_data="profile_private")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup)

# ========== НАСТРОЙКИ ==========
async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    settings = await get_user_settings(user_id)
    current = settings['results_count']
    text = f"""Настройки
Выберите категорию настроек:

📊 Количество результатов ({current})
🎨 Интерфейс результатов (Список)
📝 Настройка шаблонов
🎮 Выбрать режим
🚫 Управление NFT"""
    keyboard = [
        [InlineKeyboardButton(f"📊 Количество результатов ({current})", callback_data="settings_results")],
        [InlineKeyboardButton("🎨 Интерфейс результатов (Список)", callback_data="settings_interface")],
        [InlineKeyboardButton("📝 Настройка шаблонов", callback_data="settings_templates")],
        [InlineKeyboardButton("🎮 Выбрать режим", callback_data="settings_mode")],
        [InlineKeyboardButton("🚫 Управление NFT", callback_data="settings_nft")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup)

async def show_results_count_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    settings = await get_user_settings(user_id)
    current = settings['results_count']
    text = f"""Установите количество результатов

Текущее значение: {current}
Максимум: 250"""
    keyboard = [
        [InlineKeyboardButton("20", callback_data="set_results_20"),
         InlineKeyboardButton("30", callback_data="set_results_30"),
         InlineKeyboardButton("50", callback_data="set_results_50")],
        [InlineKeyboardButton("100", callback_data="set_results_100"),
         InlineKeyboardButton("150", callback_data="set_results_150"),
         InlineKeyboardButton("200", callback_data="set_results_200")],
        [InlineKeyboardButton("250", callback_data="set_results_250")],
        [InlineKeyboardButton("◀️ Назад", callback_data="menu_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup)

async def set_results_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    value = int(query.data.split("_")[2])
    await save_user_settings(user_id, value)
    await query.answer(f"✅ Количество результатов установлено: {value}")
    await show_settings(update, context)

# ========== УПРАВЛЕНИЕ NFT ==========
async def show_nft_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = """Управление блокировками NFT
Выберите действие:"""
    keyboard = [
        [InlineKeyboardButton("🔒 Заблокировать NFT", callback_data="nft_block_menu")],
        [InlineKeyboardButton("🔓 Разблокировать NFT", callback_data="nft_unblock_menu")],
        [InlineKeyboardButton("📋 Список заблокированных", callback_data="nft_blocked_list")],
        [InlineKeyboardButton("📚 Весь список NFT", callback_data="nft_all_list")],
        [InlineKeyboardButton("◀️ Назад к настройкам", callback_data="menu_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup)

async def show_nft_block_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page=1):
    query = update.callback_query
    user_id = query.from_user.id
    items_per_page = 10
    total_pages = (len(NFT_LIST) + items_per_page - 1) // items_per_page
    start = (page - 1) * items_per_page
    end = min(start + items_per_page, len(NFT_LIST))
    page_nfts = NFT_LIST[start:end]
    blocked = blocked_nfts.get(user_id, [])
    keyboard = []
    for i, nft in enumerate(page_nfts, start=start + 1):
        status = "🔒" if nft["name"] in blocked else "🔓"
        keyboard.append([InlineKeyboardButton(f"{status} {i}. {nft['name']}", callback_data=f"block_nft_{nft['name']}")])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"nft_block_page_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"nft_block_page_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="settings_nft")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"""🔒 Выберите NFT для блокировки:

🟢 - доступно
🔴 - заблокировано

Страница {page}/{total_pages}"""
    await query.message.edit_text(text, reply_markup=reply_markup)

async def show_nft_unblock_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page=1):
    query = update.callback_query
    user_id = query.from_user.id
    blocked_list = [n for n in NFT_LIST if n["name"] in blocked_nfts.get(user_id, [])]
    if not blocked_list:
        await query.message.edit_text("📋 У вас нет заблокированных NFT", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="settings_nft")]]))
        return
    items_per_page = 10
    total_pages = (len(blocked_list) + items_per_page - 1) // items_per_page
    start = (page - 1) * items_per_page
    end = min(start + items_per_page, len(blocked_list))
    page_nfts = blocked_list[start:end]
    keyboard = []
    for i, nft in enumerate(page_nfts, start=start + 1):
        keyboard.append([InlineKeyboardButton(f"🔓 {i}. {nft['name']}", callback_data=f"unblock_nft_{nft['name']}")])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"nft_unblock_page_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"nft_unblock_page_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="settings_nft")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"""🔓 Выберите NFT для разблокировки:

Всего заблокировано: {len(blocked_list)}
Страница {page}/{total_pages}"""
    await query.message.edit_text(text, reply_markup=reply_markup)

async def show_nft_blocked_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    blocked = blocked_nfts.get(user_id, [])
    if not blocked:
        text = "📋 У вас нет заблокированных NFT"
    else:
        text = "📋 Ваши заблокированные NFT:\n\n"
        for i, name in enumerate(blocked, 1):
            text += f"{i}. {name}\n"
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="settings_nft")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup)

async def show_all_nft(update: Update, context: ContextTypes.DEFAULT_TYPE, page=1):
    query = update.callback_query
    user_id = query.from_user.id
    items_per_page = 10
    total_pages = (len(NFT_LIST) + items_per_page - 1) // items_per_page
    start = (page - 1) * items_per_page
    end = min(start + items_per_page, len(NFT_LIST))
    page_nfts = NFT_LIST[start:end]
    blocked = blocked_nfts.get(user_id, [])
    text = f"📋 Список всех NFT (страница {page}/{total_pages}):\n\n"
    for i, nft in enumerate(page_nfts, start=start + 1):
        status = "🔴" if nft["name"] in blocked else "🟢"
        text += f"{status} {i}. {nft['name']}\n"
        text += f"   🎯 {nft['difficulty']} | ID: {nft['id_range']}\n\n"
    text += f"🔢 Всего NFT: {len(NFT_LIST)}\n"
    text += f"🔒 Заблокировано: {len(blocked)}"
    keyboard = []
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"nft_page_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"nft_page_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="settings_nft")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup)

# ========== ПОДДЕРЖКА ==========
async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = """Меню поддержки

Выберите нужный раздел:"""
    keyboard = [
        [InlineKeyboardButton("📢 Купить рекламу", callback_data="support_ads")],
        [InlineKeyboardButton("💡 Предложить идею", callback_data="support_idea")],
        [InlineKeyboardButton("👨‍💻 Манаул по ворку", callback_data="support_manual")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup)

# ========== ОБРАБОТКА ТЕКСТОВЫХ КОМАНД ==========
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_subscription(update, context):
        return
    text = update.message.text
    user_id = update.effective_user.id
    if text.startswith('/block'):
        parts = text.split()
        if len(parts) == 2 and parts[1].isdigit():
            num = int(parts[1])
            if 1 <= num <= len(NFT_LIST):
                nft = NFT_LIST[num - 1]
                if user_id not in blocked_nfts:
                    blocked_nfts[user_id] = []
                if nft['name'] not in blocked_nfts[user_id]:
                    blocked_nfts[user_id].append(nft['name'])
                    await update.message.reply_text(f"✅ NFT {nft['name']} заблокирован")
                else:
                    await update.message.reply_text(f"⚠️ NFT {nft['name']} уже заблокирован")
            else:
                await update.message.reply_text("❌ Неверный номер")
    elif text.startswith('/unblock'):
        parts = text.split()
        if len(parts) == 2 and parts[1].isdigit():
            num = int(parts[1])
            if 1 <= num <= len(NFT_LIST):
                nft = NFT_LIST[num - 1]
                if user_id in blocked_nfts and nft['name'] in blocked_nfts[user_id]:
                    blocked_nfts[user_id].remove(nft['name'])
                    await update.message.reply_text(f"✅ NFT {nft['name']} разблокирован")
                else:
                    await update.message.reply_text(f"⚠️ NFT {nft['name']} не заблокирован")
            else:
                await update.message.reply_text("❌ Неверный номер")
    elif text == '/myblock':
        blocked = blocked_nfts.get(user_id, [])
        if not blocked:
            await update.message.reply_text("📋 У вас нет заблокированных NFT")
        else:
            msg = "📋 Ваши заблокированные NFT:\n\n"
            for i, name in enumerate(blocked, 1):
                msg += f"{i}. {name}\n"
            await update.message.reply_text(msg)

# ========== АДМИН-КОМАНДЫ ДЛЯ БАН-ЛИСТА ==========
async def add_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Нет прав")
        return
    
    try:
        username = context.args[0]
        if not username.startswith('@'):
            username = '@' + username
        
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute(
                "INSERT OR IGNORE INTO blacklist (username) VALUES (?)",
                (username.lower(),)
            )
            await db.commit()
        await update.message.reply_text(f"✅ {username} добавлен в бан-лист")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Использование: /addban @username")

async def remove_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Нет прав")
        return
    
    try:
        username = context.args[0]
        if not username.startswith('@'):
            username = '@' + username
        
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute(
                "DELETE FROM blacklist WHERE username = ?",
                (username.lower(),)
            )
            await db.commit()
        await update.message.reply_text(f"✅ {username} удален из бан-листа")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Использование: /removeban @username")

async def list_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Нет прав")
        return
    
    blacklist = await get_blacklist()
    if not blacklist:
        await update.message.reply_text("📋 Бан-лист пуст")
        return
    
    text = "📋 **Бан-лист релеев:**\n\n"
    for i, username in enumerate(blacklist, 1):
        text += f"{i}. {username}\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ========== ОБРАБОТЧИК МЕНЮ ==========
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not await require_subscription(update, context):
        return
    
    data = query.data
    user_id = query.from_user.id
    
    if data == "main_menu":
        await show_main_menu(update, context)
    elif data == "menu_search":
        await show_search_menu(update, context)
    elif data == "menu_profile":
        await show_profile(update, context)
    elif data == "menu_settings":
        await show_settings(update, context)
    elif data == "menu_support":
        await show_support(update, context)
    elif data == "search_random":
        await show_modes_menu(update, context)
    elif data == "search_model":
        await show_model_selection(update, context)
    elif data == "search_girls":
        await show_search_results(update, context, "girls")
    elif data == "mode_light":
        await show_mode_confirmation(update, context, "light")
    elif data == "mode_medium":
        await show_mode_confirmation(update, context, "medium")
    elif data == "mode_heavy":
        await show_mode_confirmation(update, context, "heavy")
    elif data.startswith("start_search_"):
        mode = data.replace("start_search_", "")
        await show_search_results(update, context, mode)
    elif data.startswith("model_page_"):
        page = int(data.split("_")[2])
        await show_model_selection(update, context, page)
    elif data.startswith("select_model_"):
        nft_name = data.replace("select_model_", "")
        await show_search_results(update, context, "light", nft_name)
    elif data.startswith("results_page_"):
        parts = data.split("_")
        mode = parts[2]
        page = int(parts[3])
        nft_name = parts[4] if len(parts) > 4 and parts[4] else None
        await show_search_results(update, context, mode, nft_name, page)
    elif data.startswith("more_"):
        parts = data.split("_")
        mode = parts[1]
        nft_name = "_".join(parts[2:])
        await show_search_results(update, context, mode, nft_name)
    elif data == "settings_results":
        await show_results_count_menu(update, context)
    elif data.startswith("set_results_"):
        await set_results_count(update, context)
    elif data == "settings_interface" or data == "settings_templates" or data == "settings_mode":
        await query.message.edit_text("⚡ Раздел в разработке", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu_settings")]]))
    elif data == "settings_nft":
        await show_nft_management(update, context)
    elif data == "nft_block_menu":
        await show_nft_block_menu(update, context)
    elif data.startswith("nft_block_page_"):
        page = int(data.split("_")[3])
        await show_nft_block_menu(update, context, page)
    elif data.startswith("block_nft_"):
        nft_name = data.replace("block_nft_", "")
        if user_id not in blocked_nfts:
            blocked_nfts[user_id] = []
        if nft_name not in blocked_nfts[user_id]:
            blocked_nfts[user_id].append(nft_name)
            await query.answer(f"✅ NFT {nft_name} заблокирован", show_alert=True)
        else:
            await query.answer(f"⚠️ NFT {nft_name} уже заблокирован", show_alert=True)
        await show_nft_block_menu(update, context)
    elif data == "nft_unblock_menu":
        await show_nft_unblock_menu(update, context)
    elif data.startswith("nft_unblock_page_"):
        page = int(data.split("_")[3])
        await show_nft_unblock_menu(update, context, page)
    elif data.startswith("unblock_nft_"):
        nft_name = data.replace("unblock_nft_", "")
        if user_id in blocked_nfts and nft_name in blocked_nfts[user_id]:
            blocked_nfts[user_id].remove(nft_name)
            await query.answer(f"✅ NFT {nft_name} разблокирован", show_alert=True)
        else:
            await query.answer(f"⚠️ NFT {nft_name} не заблокирован", show_alert=True)
        await show_nft_unblock_menu(update, context)
    elif data == "nft_blocked_list":
        await show_nft_blocked_list(update, context)
    elif data == "nft_all_list":
        await show_all_nft(update, context, 1)
    elif data.startswith("nft_page_"):
        page = int(data.split("_")[2])
        await show_all_nft(update, context, page)
    elif data == "support_ads":
        await query.message.edit_text("📢 Купить рекламу\n\nПо вопросам рекламы: @zotlu\n\n💰 Цены:\n• Пост в канале: 5 ТОН\n• Реклама в боте: 4 ТОНА", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu_support")]]))
    elif data == "support_idea":
        await query.message.edit_text("💡 Предложить идею\n\nЕсть идея? Пишите @zotlu", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu_support")]]))
    elif data == "support_manual":
        await query.message.edit_text("👨‍💻 Манаул по ворку\n\nРаздел в разработке", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu_support")]]))
    elif data.startswith("profile_"):
        await query.message.edit_text("⚡ Раздел в разработке", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu_profile")]]))
    elif data == "noop":
        pass

# ========== ЗАПУСК БОТА ==========
def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_blacklist_db())
    loop.run_until_complete(init_default_blacklist())
    loop.run_until_complete(init_user_settings_db())
    
    print("=" * 70)
    print("🤖 NFT ПАРСЕР БОТ (С НАСТРОЙКАМИ В БД)")
    print("=" * 70)
    print(f"📢 ID канала: {CHANNEL_ID}")
    print(f"🔗 Ссылка: {CHANNEL_LINK}")
    print(f"👧 Женских NFT: {len(GIRLS_NFT_LIST)}")
    print("=" * 70)
    print("✅ Проверка подписки")
    print("✅ Настройки сохраняются в БД")
    print("✅ Поиск по настройкам пользователя")
    print("✅ Прогресс-бар с обновлением")
    print("✅ HTML-форматирование")
    print("✅ Кнопка 'Написать' работает")
    print("=" * 70)
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    
    app.add_handler(CommandHandler("addban", add_blacklist))
    app.add_handler(CommandHandler("removeban", remove_blacklist))
    app.add_handler(CommandHandler("listban", list_blacklist))
    
    app.add_handler(CallbackQueryHandler(handle_menu))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("✅ Бот готов!")
    app.run_polling()

if __name__ == "__main__":
    main()