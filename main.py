import logging
import random
import re
import asyncio
import aiohttp
import aiosqlite
from datetime import datetime
from urllib.parse import quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode

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

INITIAL_BLACKLIST = [
    "@giftrelayer", "@mrktbank", "@kallent", "@monk", "@durov",
    "@virusgift", "@portalsrelayer", "@lucha", "@snoopdogg", "@snoop",
    "@telegram", "@Tonnel_Network_bot", "@midasdep", "@portalsreceive", "@nftgiftbot", 
    "@GiftDrop_Warehouse", "@trade_relayer", "@rolls_transfer", "@GiftsToPortals", 
    "@gemsrelayer", "@GiftDeposit", "@depgifts", "@marixyana57", "@gbrelayer"
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
                results_count INTEGER DEFAULT 20,
                message_template TEXT DEFAULT 'Здравствуйте, заинтересовался вашим NFT подарком, могу купить у вас его.',
                default_mode TEXT DEFAULT 'light',
                interface_style TEXT DEFAULT 'list',
                searches INTEGER DEFAULT 0,
                found_users INTEGER DEFAULT 0
            )
        ''')
        await db.commit()
    logging.info("✅ Таблица user_settings создана")

async def get_user_settings(user_id: int) -> dict:
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT results_count, message_template, default_mode, interface_style, searches, found_users FROM user_settings WHERE user_id = ?", 
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    'results_count': row[0],
                    'message_template': row[1],
                    'default_mode': row[2],
                    'interface_style': row[3],
                    'searches': row[4],
                    'found_users': row[5]
                }
            else:
                return {
                    'results_count': 20,
                    'message_template': 'Здравствуйте, заинтересовался вашим NFT подарком, могу купить у вас его.',
                    'default_mode': 'light',
                    'interface_style': 'list',
                    'searches': 0,
                    'found_users': 0
                }

async def save_user_settings(user_id: int, results_count: int = None, message_template: str = None, 
                              default_mode: str = None, interface_style: str = None,
                              searches: int = None, found_users: int = None):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT 1 FROM user_settings WHERE user_id = ?", (user_id,)) as cursor:
            exists = await cursor.fetchone() is not None
        
        if exists:
            current = await get_user_settings(user_id)
            new_results = results_count if results_count is not None else current['results_count']
            new_template = message_template if message_template is not None else current['message_template']
            new_mode = default_mode if default_mode is not None else current['default_mode']
            new_interface = interface_style if interface_style is not None else current['interface_style']
            new_searches = searches if searches is not None else current['searches']
            new_found = found_users if found_users is not None else current['found_users']
            
            await db.execute(
                "UPDATE user_settings SET results_count = ?, message_template = ?, default_mode = ?, interface_style = ?, searches = ?, found_users = ? WHERE user_id = ?",
                (new_results, new_template, new_mode, new_interface, new_searches, new_found, user_id)
            )
        else:
            await db.execute(
                "INSERT INTO user_settings (user_id, results_count, message_template, default_mode, interface_style, searches, found_users) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, results_count or 20, message_template or 'Здравствуйте, заинтересовался вашим NFT подарком, могу купить у вас его.', default_mode or 'light', interface_style or 'list', searches or 0, found_users or 0)
            )
        await db.commit()

async def update_stats(user_id: int, found_count: int = 0):
    current = await get_user_settings(user_id)
    await save_user_settings(user_id, searches=current['searches'] + 1, found_users=current['found_users'] + found_count)

# ========== ПАРСИНГ ==========
async def parse_gift_owner(session: aiohttp.ClientSession, url: str) -> tuple:
    try:
        async with session.get(url, timeout=3) as response:
            if response.status != 200:
                return None, None
            html = await response.text()
            
            username = None
            match = re.search(r'<a[^>]*href="https://t\.me/([a-zA-Z0-9_]{5,32})"[^>]*>', html)
            if match:
                username = match.group(1)
                if username in ['nft', 'gift', 'joinchat', 'addstickers']:
                    username = None
            
            if not username:
                match = re.search(r'@([a-zA-Z0-9_]{5,32})', html)
                if match:
                    username = match.group(1)
            
            gift_name = None
            match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
            if match:
                gift_name = match.group(1).replace('Gift ', '').strip()
            
            return f"@{username}" if username else None, gift_name
    except:
        return None, None

async def parse_user_gift_count(session: aiohttp.ClientSession, username: str) -> int:
    """Парсит количество отправленных подарков (цифра в синей рамочке)"""
    try:
        url = f"https://t.me/{username}"
        async with session.get(url, timeout=3) as response:
            if response.status != 200:
                return 0
            html = await response.text()
            
            # Ищем цифру в синей рамочке - количество подарков
            match = re.search(r'<span[^>]*class="[^"]*tgme_gift_count[^"]*"[^>]*>(\d+)</span>', html)
            if match:
                return int(match.group(1))
            
            # Ищем цифру рядом с иконкой подарка
            match = re.search(r'[🎁🎀]\s*(\d+)', html)
            if match:
                return int(match.group(1))
            
            return 0
    except:
        return 0

async def find_real_owners_parallel(gifts: list, target_count: int, title: str, status_message=None) -> list:
    blacklist = await get_blacklist()
    blacklist_lower = [u.lower() for u in blacklist]
    found = []
    seen_users = set()
    
    semaphore = asyncio.Semaphore(50)
    
    async def parse_with_semaphore(session, gift):
        async with semaphore:
            return await parse_gift_owner(session, gift['url'])
    
    async with aiohttp.ClientSession() as session:
        tasks = [parse_with_semaphore(session, gift) for gift in gifts]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, Exception) or not result[0]:
                continue
            
            owner = result[0]
            gift_name = result[1]
            
            if owner.lower() not in blacklist_lower and owner.lower() not in seen_users:
                seen_users.add(owner.lower())
                found.append({
                    'name': gift_name or gifts[i]['name'],
                    'url': gifts[i]['url'],
                    'owner': owner
                })
            
            if status_message and (len(found) % 5 == 0 or len(found) >= target_count):
                try:
                    progress = min(len(found) / target_count, 1.0) if target_count > 0 else 0
                    filled = int(progress * 10)
                    bar = "▰" * filled + "▱" * (10 - filled)
                    await status_message.edit_text(
                        f"🎯 Режим: {title}\n"
                        f"📝 Шаблон: Стандартный\n"
                        f"🔢 Количество: {target_count}\n\n"
                        f"🔍 {bar} Поиск NFT...\n"
                        f"✅ Найдено: {len(found)}/{target_count}",
                        parse_mode=ParseMode.HTML
                    )
                except:
                    pass
            
            if len(found) >= target_count:
                break
    
    return found

# ========== СПИСОК NFT ==========
NFT_LIST = [
    {"name": "BDayCandle", "difficulty": "easy", "min_id": 1000, "max_id": 20000},
    {"name": "CandyCane", "difficulty": "easy", "min_id": 1000, "max_id": 150000},
    {"name": "CloverPin", "difficulty": "easy", "min_id": 1000, "max_id": 60000},
    {"name": "DeskCalendar", "difficulty": "easy", "min_id": 1000, "max_id": 13000},
    {"name": "FaithAmulet", "difficulty": "easy", "min_id": 1000, "max_id": 60000},
    {"name": "FreshSocks", "difficulty": "easy", "min_id": 1000, "max_id": 100000},
    {"name": "GingerCookie", "difficulty": "easy", "min_id": 1000, "max_id": 60000},
    {"name": "HappyBrownie", "difficulty": "easy", "min_id": 1000, "max_id": 60000},
    {"name": "HolidayDrink", "difficulty": "easy", "min_id": 1000, "max_id": 60000},
    {"name": "HomemadeCake", "difficulty": "easy", "min_id": 1000, "max_id": 130000},
    {"name": "IceCream", "difficulty": "easy", "min_id": 1000, "max_id": 60000},
    {"name": "InstantRamen", "difficulty": "easy", "min_id": 1000, "max_id": 60000},
    {"name": "JesterHat", "difficulty": "easy", "min_id": 1000, "max_id": 60000},
    {"name": "JingleBells", "difficulty": "easy", "min_id": 1000, "max_id": 60000},
    {"name": "LolPop", "difficulty": "easy", "min_id": 1000, "max_id": 130000},
    {"name": "LunarSnake", "difficulty": "easy", "min_id": 1000, "max_id": 250000},
    {"name": "PetSnake", "difficulty": "easy", "min_id": 1000, "max_id": 1000},
    {"name": "SnakeBox", "difficulty": "easy", "min_id": 1000, "max_id": 55000},
    {"name": "SnoopDogg", "difficulty": "easy", "min_id": 576241, "max_id": 576241},
    {"name": "SpicedWine", "difficulty": "easy", "min_id": 93557, "max_id": 93557},
    {"name": "WhipCupcake", "difficulty": "easy", "min_id": 1000, "max_id": 170000},
    {"name": "WinterWreath", "difficulty": "easy", "min_id": 65311, "max_id": 65311},
    {"name": "XmasStocking", "difficulty": "easy", "min_id": 177478, "max_id": 177478},
    {"name": "BerryBox", "difficulty": "medium", "min_id": 1000, "max_id": 60000},
    {"name": "BigYear", "difficulty": "medium", "min_id": 1000, "max_id": 60000},
    {"name": "BowTie", "difficulty": "medium", "min_id": 1000, "max_id": 47000},
    {"name": "BunnyMuffin", "difficulty": "medium", "min_id": 1000, "max_id": 60000},
    {"name": "CookieHeart", "difficulty": "medium", "min_id": 1000, "max_id": 60000},
    {"name": "EasterEgg", "difficulty": "medium", "min_id": 1000, "max_id": 60000},
    {"name": "EternalCandle", "difficulty": "medium", "min_id": 1000, "max_id": 60000},
    {"name": "EvilEye", "difficulty": "medium", "min_id": 1000, "max_id": 60000},
    {"name": "HexPot", "difficulty": "medium", "min_id": 1000, "max_id": 50000},
    {"name": "HypnoLollipop", "difficulty": "medium", "min_id": 1000, "max_id": 60000},
    {"name": "InputKey", "difficulty": "medium", "min_id": 1000, "max_id": 80000},
    {"name": "JackInTheBox", "difficulty": "medium", "min_id": 1000, "max_id": 60000},
    {"name": "JellyBunny", "difficulty": "medium", "min_id": 1000, "max_id": 60000},
    {"name": "JollyChimp", "difficulty": "medium", "min_id": 1000, "max_id": 25000},
    {"name": "JoyfulBundle", "difficulty": "medium", "min_id": 1000, "max_id": 60000},
    {"name": "LightSword", "difficulty": "medium", "min_id": 1000, "max_id": 110000},
    {"name": "LushBouquet", "difficulty": "medium", "min_id": 1000, "max_id": 60000},
    {"name": "MousseCake", "difficulty": "medium", "min_id": 119126, "max_id": 119126},
    {"name": "PartySparkler", "difficulty": "medium", "min_id": 161722, "max_id": 161722},
    {"name": "RestlessJar", "difficulty": "medium", "min_id": 1000, "max_id": 23000},
    {"name": "SantaHat", "difficulty": "medium", "min_id": 19289, "max_id": 19289},
    {"name": "SnoopCigar", "difficulty": "medium", "min_id": 1000, "max_id": 60000},
    {"name": "SnowGlobe", "difficulty": "medium", "min_id": 48029, "max_id": 48029},
    {"name": "SnowMittens", "difficulty": "medium", "min_id": 64057, "max_id": 64057},
    {"name": "SpringBasket", "difficulty": "medium", "min_id": 140160, "max_id": 140160},
    {"name": "SpyAgaric", "difficulty": "medium", "min_id": 84274, "max_id": 84274},
    {"name": "StarNotepad", "difficulty": "medium", "min_id": 1000, "max_id": 25000},
    {"name": "StellarRocket", "difficulty": "medium", "min_id": 1000, "max_id": 35000},
    {"name": "SwagBag", "difficulty": "medium", "min_id": 1000, "max_id": 5000},
    {"name": "TamaGadget", "difficulty": "medium", "min_id": 95205, "max_id": 95205},
    {"name": "ValentineBox", "difficulty": "medium", "min_id": 229868, "max_id": 229868},
    {"name": "WitchHat", "difficulty": "medium", "min_id": 1000, "max_id": 7000},
    {"name": "UFCStrike", "difficulty": "medium", "min_id": 1000, "max_id": 56951},
    {"name": "ArtisanBrick", "difficulty": "hard", "min_id": 1000, "max_id": 7000},
    {"name": "AstralShard", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "BondedRing", "difficulty": "hard", "min_id": 1000, "max_id": 3000},
    {"name": "CupidCharm", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "DiamondRing", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "DurovsCap", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "EternalRose", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "FlyingBroom", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "GemSignet", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "GenieLamp", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "GustalBall", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "HeartLocket", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "HeroicHelmet", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "IonGem", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "IonicDryer", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "KissedFrog", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "LootBag", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "LoveCandle", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "LovePotion", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "LowRider", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "MadPumpkin", "difficulty": "hard", "min_id": 96227, "max_id": 96227},
    {"name": "MagicPotion", "difficulty": "hard", "min_id": 4764, "max_id": 4764},
    {"name": "MightyArm", "difficulty": "hard", "min_id": 150000, "max_id": 150000},
    {"name": "MiniOscar", "difficulty": "hard", "min_id": 4764, "max_id": 4764},
    {"name": "NailBracelet", "difficulty": "hard", "min_id": 119126, "max_id": 119126},
    {"name": "NekoHelmet", "difficulty": "hard", "min_id": 15431, "max_id": 15431},
    {"name": "PerfumeBottle", "difficulty": "hard", "min_id": 151632, "max_id": 151632},
    {"name": "PreciousPeach", "difficulty": "hard", "min_id": 2981, "max_id": 2981},
    {"name": "RecordPlayer", "difficulty": "hard", "min_id": 554, "max_id": 554},
    {"name": "ScaredCat", "difficulty": "hard", "min_id": 8029, "max_id": 8029},
    {"name": "SharpTongue", "difficulty": "hard", "min_id": 1000, "max_id": 16430},
    {"name": "SignetRing", "difficulty": "hard", "min_id": 1000, "max_id": 16430},
    {"name": "SkullFlower", "difficulty": "hard", "min_id": 1000, "max_id": 21428},
    {"name": "SkyStilettos", "difficulty": "hard", "min_id": 1000, "max_id": 47465},
    {"name": "SleighBell", "difficulty": "hard", "min_id": 1000, "max_id": 48029},
    {"name": "SwissWatch", "difficulty": "hard", "min_id": 1000, "max_id": 25121},
    {"name": "TopHat", "difficulty": "hard", "min_id": 1000, "max_id": 32648},
    {"name": "ToyBear", "difficulty": "hard", "min_id": 1000, "max_id": 60000},
    {"name": "TrappedHeart", "difficulty": "hard", "min_id": 1000, "max_id": 24656},
    {"name": "VintageCigar", "difficulty": "hard", "min_id": 1000, "max_id": 18000},
    {"name": "VoodooDoll", "difficulty": "hard", "min_id": 1000, "max_id": 26658}
]

NFT_DICT = {nft["name"]: nft for nft in NFT_LIST}

# ========== ХРАНИЛИЩЕ ==========
blocked_nfts = {}
last_message_ids = {}

# ========== ПРОВЕРКА ПОДПИСКИ ==========
async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status not in ["left", "kicked"]
    except:
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

# ========== ФУНКЦИИ ГЕНЕРАЦИИ ==========
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
    """Для поиска девушек используем легкие и средние подарки"""
    gifts = []
    easy_nfts = [n for n in NFT_LIST if n["difficulty"] == "easy"]
    medium_nfts = [n for n in NFT_LIST if n["difficulty"] == "medium"]
    available_nfts = easy_nfts + medium_nfts
    
    for _ in range(count):
        nft = random.choice(available_nfts)
        clean_name = re.sub(r"[^\w]", "", nft["name"])
        nft_id = random.randint(nft["min_id"], nft["max_id"])
        gifts.append({"name": nft["name"], "url": f"https://t.me/nft/{clean_name}-{nft_id}"})
    return gifts

def generate_model_gifts(nft_name, count=20):
    gifts = []
    clean_name = re.sub(r"[^\w]", "", nft_name)
    nft = NFT_DICT.get(nft_name)
    if nft:
        for _ in range(count):
            nft_id = random.randint(nft["min_id"], nft["max_id"])
            gifts.append({"name": nft_name, "url": f"https://t.me/nft/{clean_name}-{nft_id}"})
    return gifts

# ========== ФИЛЬТРАЦИЯ ДЕВУШЕК ==========
async def filter_female_users(found_users: list) -> list:
    """Фильтрует пользователей, оставляя только девушек с уровнем подарков <= 2"""
    filtered = []
    seen_users = set()
    
    # Женские окончания
    FEMALE_ENDINGS = ['a', 'я', 'ina', 'ova', 'eva', 'iya', 'ia', 'ka', 'sha', 'na', 'la', 'ya', 'va',
                      'а', 'я', 'ина', 'ова', 'ева', 'ия', 'ка', 'ша', 'на', 'ла']
    
    # Женские имена
    FEMALE_NAMES = {
        "анна", "аня", "оля", "олга", "маша", "мария", "лена", "елена", "наташа", "наталья",
        "катя", "екатерина", "таня", "татьяна", "света", "светлана", "ира", "ирина", "юля", "юлия",
        "саша", "александра", "настя", "анастасия", "даша", "дария", "лиза", "елизавета",
        "кристина", "вика", "виктория", "валя", "валентина", "вероника", "алина", "карина",
        "кира", "мая", "диана", "ангелина", "мила", "нина", "полина", "ульяна", "арина", "софия",
        "anna", "olga", "maria", "elena", "natalia", "ekaterina", "tatyana", "svetlana", "irina",
        "julia", "alexandra", "anastasia", "daria", "elizaveta", "kristina", "victoria", "alina",
        "sophia", "emma", "mia", "luna", "chloe", "zoe", "ava", "isabella", "olivia"
    }
    
    # Мужские имена - исключаем
    MALE_NAMES = {
        "алекс", "алексей", "макс", "максим", "антон", "сергей", "дмитрий", "андрей",
        "влад", "владимир", "никита", "иван", "артем", "павел", "михаил", "николай", "олег",
        "alex", "max", "anton", "sergey", "dmitry", "andrey", "vlad", "nikita", "ivan", "artem"
    }
    
    async with aiohttp.ClientSession() as session:
        for user in found_users:
            username = user['owner']
            username_clean = username.lower().strip('@')
            
            if username_clean in seen_users:
                continue
            
            # Проверяем количество отправленных подарков (цифра в синей рамочке)
            try:
                gift_count = await parse_user_gift_count(session, username_clean)
                if gift_count > 2:
                    continue  # больше 2 подарков - активный пользователь, скипаем
            except:
                pass
            
            # Проверка на женский пол
            is_female = False
            
            if username_clean in FEMALE_NAMES:
                is_female = True
            else:
                parts = re.split(r'[_.\-]', username_clean)
                for part in parts:
                    part_clean = re.sub(r'\d+$', '', part)
                    if part_clean in FEMALE_NAMES:
                        is_female = True
                        break
                
                if not is_female:
                    for ending in FEMALE_ENDINGS:
                        if username_clean.endswith(ending) and len(username_clean) > 3:
                            is_female = True
                            break
            
            # Проверка на мужские имена
            is_male = False
            for name in MALE_NAMES:
                if name in username_clean:
                    is_male = True
                    break
            
            male_endings = ['ov', 'ev', 'in', 'ов', 'ев', 'ин']
            for ending in male_endings:
                if username_clean.endswith(ending):
                    is_male = True
                    break
            
            if is_female and not is_male:
                seen_users.add(username_clean)
                filtered.append(user)
    
    return filtered

# ========== ГЛАВНОЕ МЕНЮ ==========
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = f"🔷 Привет, @{user.username or 'user'}! Это парсер для поиска мамонтов."
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    settings = await get_user_settings(user_id)
    context.user_data['results_count'] = settings['results_count']
    
    if not await check_subscription(user_id, context):
        keyboard = [[InlineKeyboardButton("📢 Подписаться", url=CHANNEL_LINK)]]
        await update.message.reply_text("⚠️ Подпишись на канал!", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    await show_main_menu(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_subscription(update, context):
        return
    text = """🔷 СПРАВКА ПО БОТУ

📋 ТРЕБОВАНИЯ:
1. Быть участником канала

⌨️ КОМАНДЫ:
/start - Начать работу
/help - Справка
/status - Статус
/block <номер> - Заблокировать NFT
/unblock <номер> - Разблокировать NFT
/myblock - Список блокировок"""
    await update.message.reply_text(text)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_subscription(update, context):
        return
    user_id = update.effective_user.id
    subscribed = await check_subscription(user_id, context)
    blacklist = await get_blacklist()
    settings = await get_user_settings(user_id)
    text = f"""🔷 ВАШ СТАТУС

📊 Подписка: {'✅ В КАНАЛЕ' if subscribed else '❌ НЕТ'}
🔍 Всего поисков: {settings['searches']}
🎯 Найдено пользователей: {settings['found_users']}
🚫 Всего в бане: {len(blacklist)} релеев"""
    await update.message.reply_text(text)

# ========== МЕНЮ ПОИСКА ==========
async def show_search_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = """🔷 Выберите тип поиска:

🎲 Рандом поиск - поиск по режимам (легкий, средний, жирный)
🔍 Поиск по модели - точный поиск по конкретным NFT
👧 Поиск девушек - поиск по женским именам"""
    
    keyboard = [
        [InlineKeyboardButton("🎲 Рандом поиск", callback_data="search_random")],
        [InlineKeyboardButton("🔍 Поиск по модели", callback_data="search_model")],
        [InlineKeyboardButton("👧 Поиск девушек", callback_data="search_girls")],
        [InlineKeyboardButton("🔷 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup)

# ========== МЕНЮ РЕЖИМОВ ==========
async def show_modes_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = """🔷 Выберите режим поиска:

🟢 Легкий режим  
  💰 Недорогие подарки до 3 TON  
  👶 Самые неопытные пользователи  

🟡 Средний режим  
  💰 Хорошие подарки от 3 до 15 TON  
  🧑 Более опытные пользователи  

🔴 Жирный режим  
  💰 Дорогие подарки от 15 до 600 TON  
  👑 Опытные коллекционеры"""
    keyboard = [
        [InlineKeyboardButton("🟢 Легкий режим", callback_data="mode_light")],
        [InlineKeyboardButton("🟡 Средний режим", callback_data="mode_medium")],
        [InlineKeyboardButton("🔴 Жирный режим", callback_data="mode_heavy")],
        [InlineKeyboardButton("🔷 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup)

# ========== ПОКАЗ РЕЗУЛЬТАТОВ ==========
async def show_paginated_results(message, found, mode, nft_name, page, title, context, is_girls=False):
    items_per_page = 10
    total_pages = (len(found) + items_per_page - 1) // items_per_page
    start = (page - 1) * items_per_page
    end = min(start + items_per_page, len(found))
    page_results = found[start:end]
    
    user_id = message.chat.id
    settings = await get_user_settings(user_id)
    message_template = settings['message_template']
    interface_style = settings['interface_style']
    
    mode_names = {
        "light": "🟢 Легкий",
        "medium": "🟡 Средний",
        "heavy": "🔴 Жирный",
        "girls": "👧 Девушки"
    }
    
    display_title = mode_names.get(mode, title or "Поиск")
    
    if is_girls:
        text = f"🔷 <b>Найдено девушек в режиме «{display_title}»:</b>\n\n"
    else:
        text = f"🔷 <b>Найдено в режиме «{display_title}»:</b>\n\n"
    
    for i, item in enumerate(page_results, start=start+1):
        clean_owner = item['owner'][1:] if item['owner'].startswith('@') else item['owner']
        encoded_text = quote(message_template)
        
        gift_url = item['url']
        write_url = f"https://t.me/{clean_owner}?text={encoded_text}"
        
        if interface_style == "fast":
            text += f"{i}. @{clean_owner} | <a href=\"{write_url}\">Написать</a>\n"
        elif interface_style == "cards":
            text += f"┌─────────────┐\n│ {i}. @{clean_owner}\n│ 🔗 <a href=\"{gift_url}\">Подарок</a>\n│ ✉️ <a href=\"{write_url}\">Написать</a>\n└─────────────┘\n\n"
        else:
            text += f"{i}. <a href=\"{gift_url}\">🔗</a> | @{clean_owner} | <a href=\"{write_url}\">Написать</a>\n"
    
    text += f"\n📊 Страница {page}/{total_pages}"
    
    keyboard = []
    
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"results_page_{mode}_{page-1}_{nft_name or ''}_{is_girls}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"results_page_{mode}_{page+1}_{nft_name or ''}_{is_girls}"))
        keyboard.append(nav)
    
    if nft_name:
        keyboard.append([InlineKeyboardButton("🔄 Ещё такие же", callback_data=f"more_{mode}_{nft_name}")])
    
    keyboard.append([InlineKeyboardButton("🎲 Новый поиск", callback_data="search_random")])
    keyboard.append([InlineKeyboardButton("🔷 Главное меню", callback_data="main_menu")])
    
    try:
        await message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Ошибка: {e}")

# ========== ОСНОВНОЙ ПОИСК ==========
async def show_search_results(update: Update, context, mode, nft_name=None, page=1, is_girls=False):
    query = update.callback_query
    user_id = query.from_user.id
    
    settings = await get_user_settings(user_id)
    target_count = settings['results_count']
    
    cache_key = f"{user_id}_{mode}_{nft_name or ''}_{is_girls}"
    
    if 'search_results' not in context.user_data:
        context.user_data['search_results'] = {}
    
    if cache_key in context.user_data['search_results'] and page != 1:
        found = context.user_data['search_results'][cache_key]
        await show_paginated_results(query.message, found, mode, nft_name, page, None, context, is_girls)
        return
    
    generate_count = target_count * 20
    
    mode_names = {
        "light": "🟢 Легкий режим",
        "medium": "🟡 Средний режим", 
        "heavy": "🔴 Жирный режим",
        "girls": "👧 Поиск девушек"
    }
    display_title = mode_names.get(mode, "Поиск")
    
    if is_girls:
        title = "👧 Поиск девушек"
        gifts = generate_girls_gifts(generate_count)
    elif nft_name:
        title = f"🔍 Поиск {nft_name}"
        gifts = generate_model_gifts(nft_name, generate_count)
    elif mode == "light":
        title = "🟢 Легкий режим"
        gifts = generate_random_gifts("light", generate_count)
    elif mode == "medium":
        title = "🟡 Средний режим"
        gifts = generate_random_gifts("medium", generate_count)
    elif mode == "heavy":
        title = "🔴 Жирный режим"
        gifts = generate_random_gifts("heavy", generate_count)
    else:
        title = "Поиск"
        gifts = generate_random_gifts("light", generate_count)
    
    status_msg = await query.message.edit_text(
        f"🎯 Режим: {display_title}\n"
        f"📝 Шаблон: Стандартный\n"
        f"🔢 Количество: {target_count}\n\n"
        f"🔍 ▰▱▱▱▱▱▱▱▱▱ Поиск NFT...\n"
        f"✅ Найдено: 0/{target_count}",
        parse_mode=ParseMode.HTML
    )
    
    found = await find_real_owners_parallel(gifts, target_count, title, status_msg)
    
    if len(found) < target_count:
        additional_needed = target_count - len(found)
        additional_gifts = generate_random_gifts(mode, additional_needed * 15)
        more_found = await find_real_owners_parallel(additional_gifts, additional_needed, title, None)
        found.extend(more_found)
    
    if is_girls and found:
        found = await filter_female_users(found)
        await update_stats(user_id, len(found))
    else:
        await update_stats(user_id, len(found))
    
    context.user_data['search_results'][cache_key] = found
    
    if not found:
        keyboard = [[InlineKeyboardButton("🔄 Попробовать снова", callback_data="search_random")]]
        await status_msg.edit_text(
            "❌ Ничего не найдено.\n💡 Попробуйте увеличить количество результатов в настройках",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    await show_paginated_results(status_msg, found, mode, nft_name, page, title, context, is_girls)

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
    keyboard.append([InlineKeyboardButton("🔷 Назад", callback_data="menu_search")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"🔗 Выберите модель NFT для поиска:\n\nСтраница {page}/{total_pages}"
    await query.message.edit_text(text, reply_markup=reply_markup)

# ========== ПРОФИЛЬ ==========
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    settings = await get_user_settings(user_id)
    text = f"""🔷 <b>ПРОФИЛЬ</b>

🆔 <b>ID:</b> {user_id}
👤 <b>Имя:</b> @{query.from_user.username or 'unknown'}

📊 <b>Статистика</b>
🔍 Всего поисков: {settings['searches']}
🎯 Найдено пользователей: {settings['found_users']}
🚫 Заблокировано NFT: {len(blocked_nfts.get(user_id, []))}

⚙️ <b>Настройки</b>
📊 Лимит поиска: {settings['results_count']}
🎮 Режим: {settings['default_mode']}
🎨 Интерфейс: {settings['interface_style']}"""
    
    keyboard = [[InlineKeyboardButton("🔷 Назад", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

# ========== НАСТРОЙКИ ==========
async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    settings = await get_user_settings(user_id)
    current = settings['results_count']
    
    text = f"""🔷 <b>НАСТРОЙКИ</b>

Выберите категорию:

📊 Количество результатов ({current})
🎨 Интерфейс результатов ({settings['interface_style']})
📝 Настройка шаблонов
🎮 Выбрать режим
🚫 Управление NFT"""
    
    keyboard = [
        [InlineKeyboardButton(f"📊 Количество ({current})", callback_data="settings_results")],
        [InlineKeyboardButton("🎨 Интерфейс", callback_data="settings_interface")],
        [InlineKeyboardButton("📝 Шаблоны", callback_data="settings_template")],
        [InlineKeyboardButton("🎮 Режим", callback_data="settings_mode")],
        [InlineKeyboardButton("🚫 NFT", callback_data="settings_nft")],
        [InlineKeyboardButton("🔷 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def show_results_count_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = f"""🔷 <b>Количество результатов</b>

Максимум: 250"""
    keyboard = [
        [InlineKeyboardButton("20", callback_data="set_results_20"),
         InlineKeyboardButton("30", callback_data="set_results_30"),
         InlineKeyboardButton("50", callback_data="set_results_50")],
        [InlineKeyboardButton("100", callback_data="set_results_100"),
         InlineKeyboardButton("150", callback_data="set_results_150"),
         InlineKeyboardButton("200", callback_data="set_results_200")],
        [InlineKeyboardButton("250", callback_data="set_results_250")],
        [InlineKeyboardButton("🔷 Назад", callback_data="menu_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def set_results_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    value = int(query.data.split("_")[2])
    await save_user_settings(user_id, results_count=value)
    await query.answer(f"✅ Установлено: {value}")
    await show_settings(update, context)

async def show_interface_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    text = """🔷 <b>Интерфейс результатов</b>

Выберите формат отображения:

📋 Список - компактный вывод
🖼️ Карточки - подробный вывод
⚡ Быстрый - только юзернеймы"""
    
    keyboard = [
        [InlineKeyboardButton("📋 Список", callback_data="interface_list"),
         InlineKeyboardButton("🖼️ Карточки", callback_data="interface_cards")],
        [InlineKeyboardButton("⚡ Быстрый", callback_data="interface_fast")],
        [InlineKeyboardButton("🔷 Назад", callback_data="menu_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def show_template_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    settings = await get_user_settings(user_id)
    current_template = settings['message_template']
    
    text = f"""🔷 <b>Настройка шаблона сообщения</b>

📝 Текущий шаблон:
<code>{current_template}</code>

✏️ Введите новый текст в чат, или нажмите кнопку ниже чтобы сбросить на стандартный."""
    
    keyboard = [
        [InlineKeyboardButton("🔄 Сбросить", callback_data="reset_template")],
        [InlineKeyboardButton("🔷 Назад", callback_data="menu_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    context.user_data['editing_template'] = True
    
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def reset_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    default_template = 'Здравствуйте, заинтересовался вашим NFT подарком, могу купить у вас его.'
    await save_user_settings(user_id, message_template=default_template)
    
    await query.answer("✅ Шаблон сброшен")
    await show_template_settings(update, context)

async def show_mode_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    text = """🔷 <b>Выбор режима по умолчанию</b>

Какой режим использовать при поиске?

🟢 Легкий - дешёвые подарки, новички
🟡 Средний - средние цены, опытные
🔴 Жирный - дорогие подарки, коллекционеры"""
    
    keyboard = [
        [InlineKeyboardButton("🟢 Легкий", callback_data="set_mode_light"),
         InlineKeyboardButton("🟡 Средний", callback_data="set_mode_medium")],
        [InlineKeyboardButton("🔴 Жирный", callback_data="set_mode_heavy")],
        [InlineKeyboardButton("🔷 Назад", callback_data="menu_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def show_nft_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = """🔷 <b>Управление NFT</b>

Выберите действие:"""
    keyboard = [
        [InlineKeyboardButton("🔒 Заблокировать NFT", callback_data="nft_block_menu")],
        [InlineKeyboardButton("🔓 Разблокировать NFT", callback_data="nft_unblock_menu")],
        [InlineKeyboardButton("📋 Список заблокированных", callback_data="nft_blocked_list")],
        [InlineKeyboardButton("📚 Весь список NFT", callback_data="nft_all_list")],
        [InlineKeyboardButton("🔷 Назад", callback_data="menu_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def show_nft_blocked_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    blocked = blocked_nfts.get(user_id, [])
    if not blocked:
        text = "🔷 <b>У вас нет заблокированных NFT</b>"
    else:
        text = "🔷 <b>Ваши заблокированные NFT:</b>\n\n"
        for i, name in enumerate(blocked, 1):
            text += f"{i}. {name}\n"
    keyboard = [[InlineKeyboardButton("🔷 Назад", callback_data="settings_nft")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def show_all_nft(update: Update, context: ContextTypes.DEFAULT_TYPE, page=1):
    query = update.callback_query
    user_id = query.from_user.id
    items_per_page = 10
    total_pages = (len(NFT_LIST) + items_per_page - 1) // items_per_page
    start = (page - 1) * items_per_page
    end = min(start + items_per_page, len(NFT_LIST))
    page_nfts = NFT_LIST[start:end]
    blocked = blocked_nfts.get(user_id, [])
    
    text = f"🔷 <b>Список всех NFT (страница {page}/{total_pages}):</b>\n\n"
    for i, nft in enumerate(page_nfts, start=start + 1):
        status = "🔴" if nft["name"] in blocked else "🟢"
        text += f"{status} {i}. {nft['name']} ({nft['difficulty']})\n"
    
    keyboard = []
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"nft_page_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"nft_page_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔷 Назад", callback_data="settings_nft")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

# ========== ПОДДЕРЖКА ==========
async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = """🔷 <b>ПОДДЕРЖКА</b>

Выберите нужный раздел:"""
    keyboard = [
        [InlineKeyboardButton("📢 Купить рекламу", callback_data="support_ads")],
        [InlineKeyboardButton("💡 Предложить идею", callback_data="support_idea")],
        [InlineKeyboardButton("👨‍💻 Мануал", callback_data="support_manual")],
        [InlineKeyboardButton("🔷 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

# ========== ОБРАБОТКА ТЕКСТА ==========
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_subscription(update, context):
        return
    
    if context.user_data.get('editing_template'):
        user_id = update.effective_user.id
        new_template = update.message.text.strip()
        
        if len(new_template) > 200:
            await update.message.reply_text("❌ Максимум 200 символов.")
            return
        
        await save_user_settings(user_id, message_template=new_template)
        context.user_data['editing_template'] = False
        
        await update.message.reply_text(
            f"✅ Шаблон сохранён!\n\n<code>{new_template}</code>",
            parse_mode=ParseMode.HTML
        )
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
                    await update.message.reply_text(f"⚠️ Уже заблокирован")
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
                    await update.message.reply_text(f"⚠️ Не заблокирован")
            else:
                await update.message.reply_text("❌ Неверный номер")
    elif text == '/myblock':
        blocked = blocked_nfts.get(user_id, [])
        if not blocked:
            await update.message.reply_text("📋 Нет заблокированных NFT")
        else:
            msg = "📋 Заблокированные NFT:\n\n"
            for i, name in enumerate(blocked, 1):
                msg += f"{i}. {name}\n"
            await update.message.reply_text(msg)

# ========== АДМИН-КОМАНДЫ ==========
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
        await update.message.reply_text(f"✅ {username} добавлен")
    except:
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
        await update.message.reply_text(f"✅ {username} удален")
    except:
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
    
    text = "🔷 <b>Бан-лист:</b>\n\n"
    for i, username in enumerate(blacklist, 1):
        text += f"{i}. {username}\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

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
        await show_search_results(update, context, "girls", is_girls=True)
    elif data == "mode_light":
        await show_search_results(update, context, "light")
    elif data == "mode_medium":
        await show_search_results(update, context, "medium")
    elif data == "mode_heavy":
        await show_search_results(update, context, "heavy")
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
        nft_name = parts[4] if len(parts) > 4 and parts[4] != 'False' and parts[4] != 'True' else None
        is_girls = parts[5] == 'True' if len(parts) > 5 else False
        await show_search_results(update, context, mode, nft_name, page, is_girls)
    elif data.startswith("more_"):
        parts = data.split("_")
        mode = parts[1]
        nft_name = "_".join(parts[2:])
        await show_search_results(update, context, mode, nft_name)
    elif data == "settings_results":
        await show_results_count_menu(update, context)
    elif data.startswith("set_results_"):
        await set_results_count(update, context)
    elif data == "settings_interface":
        await show_interface_settings(update, context)
    elif data == "settings_template":
        await show_template_settings(update, context)
    elif data == "settings_mode":
        await show_mode_settings(update, context)
    elif data == "settings_nft":
        await show_nft_management(update, context)
    elif data == "reset_template":
        await reset_template(update, context)
    elif data.startswith("interface_"):
        interface = data.split("_")[1]
        await save_user_settings(user_id, interface_style=interface)
        await query.answer(f"✅ Интерфейс: {interface}")
        await show_settings(update, context)
    elif data.startswith("set_mode_"):
        mode = data.split("_")[2]
        await save_user_settings(user_id, default_mode=mode)
        await query.answer(f"✅ Режим: {mode}")
        await show_settings(update, context)
    elif data == "nft_blocked_list":
        await show_nft_blocked_list(update, context)
    elif data == "nft_all_list":
        await show_all_nft(update, context, 1)
    elif data.startswith("nft_page_"):
        page = int(data.split("_")[2])
        await show_all_nft(update, context, page)
    elif data == "support_ads":
        await query.message.edit_text("📢 <b>Купить рекламу</b>\n\nПо вопросам рекламы: @zotlu\n\n💰 Цены:\n• Пост в канале: 5 ТОН\n• Реклама в боте: 4 ТОНА", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔷 Назад", callback_data="menu_support")]]), parse_mode=ParseMode.HTML)
    elif data == "support_idea":
        await query.message.edit_text("💡 <b>Предложить идею</b>\n\nЕсть идея? Пишите @zotlu", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔷 Назад", callback_data="menu_support")]]), parse_mode=ParseMode.HTML)
    elif data == "support_manual":
        await query.message.edit_text("👨‍💻 <b>Мануал</b>\n\nРаздел в разработке", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔷 Назад", callback_data="menu_support")]]), parse_mode=ParseMode.HTML)
    elif data == "noop":
        pass

# ========== ЗАПУСК ==========
def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_blacklist_db())
    loop.run_until_complete(init_default_blacklist())
    loop.run_until_complete(init_user_settings_db())
    
    print("=" * 60)
    print("🤖 NFT ПАРСЕР БОТ (ФИНАЛЬНАЯ ВЕРСИЯ)")
    print("=" * 60)
    print("✅ Проверка уровня подарков (цифра в синей рамочке)")
    print("✅ Если >2 - скипаем")
    print("✅ Русские и английские имена")
    print("✅ Женские окончания")
    print("✅ Мужские имена - скип")
    print("=" * 60)
    
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