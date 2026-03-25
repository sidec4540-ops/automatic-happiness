import logging
import random
import re
import asyncio
import aiohttp
import aiosqlite
from datetime import datetime, date
from bs4 import BeautifulSoup
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
    "@ufc", "@Tonnel_Network_bot", "@midasdep", "@portalsreceive", "@nftgiftbot", 
    "@GiftDrop_Warehouse", "@trade_relayer", "@rolls_transfer", "@GiftsToPortals", 
    "@gemsrelayer", "@GiftDeposit", "@depgifts", "@gbrelayer"
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
                (user_id, 
                 results_count or 20, 
                 message_template or 'Здравствуйте, заинтересовался вашим NFT подарком, могу купить у вас его.',
                 default_mode or 'light',
                 interface_style or 'list',
                 searches or 0,
                 found_users or 0)
            )
        await db.commit()

async def update_stats(user_id: int, found_count: int = 0):
    """Обновляет статистику пользователя"""
    current = await get_user_settings(user_id)
    await save_user_settings(
        user_id, 
        searches=current['searches'] + 1,
        found_users=current['found_users'] + found_count
    )

# ========== УЛУЧШЕННЫЙ ПАРСИНГ ==========
async def parse_gift_owner(session: aiohttp.ClientSession, url: str) -> tuple[str | None, str | None]:
    """
    Улучшенный парсинг страницы подарка
    Возвращает: (username, gift_name)
    """
    try:
        async with session.get(url, timeout=5, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }) as response:
            if response.status != 200:
                return None, None
            
            html = await response.text()
            
            # Парсим название подарка
            gift_name = None
            name_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
            if name_match:
                gift_name = name_match.group(1).replace('Gift ', '').strip()
            
            # Парсим владельца - несколько методов
            username = None
            
            # Метод 1: Ищем ссылку на профиль
            profile_match = re.search(r'<a[^>]*href="https://t\.me/([a-zA-Z0-9_]{5,32})"[^>]*>', html)
            if profile_match:
                candidate = profile_match.group(1)
                if candidate not in ['nft', 'gift', 'joinchat', 'addstickers', 'setlanguage']:
                    username = candidate
            
            # Метод 2: Ищем @username в тексте
            if not username:
                at_match = re.search(r'@([a-zA-Z0-9_]{5,32})', html)
                if at_match:
                    candidate = at_match.group(1)
                    if candidate not in ['nft', 'gift', 'joinchat']:
                        username = candidate
            
            # Метод 3: Ищем в таблице Owner
            if not username:
                owner_match = re.search(r'Owner</th>\s*<td[^>]*>\s*<a[^>]*href="https://t\.me/([a-zA-Z0-9_]+)"', html)
                if owner_match:
                    username = owner_match.group(1)
            
            if username:
                return f"@{username}", gift_name
            
            return None, gift_name
            
    except asyncio.TimeoutError:
        logger.debug(f"Таймаут {url}")
        return None, None
    except Exception as e:
        logger.debug(f"Ошибка парсинга {url}: {e}")
        return None, None

async def find_real_owners_parallel(gifts: list, target_count: int, title: str, status_message=None) -> list:
    """Параллельный поиск с дедупликацией и улучшенным парсингом"""
    blacklist = await get_blacklist()
    blacklist_lower = [u.lower() for u in blacklist]
    found = []
    seen_users = set()  # Уникальные пользователи
    seen_gifts = set()   # Уникальные подарки
    
    semaphore = asyncio.Semaphore(15)  # Увеличил до 15 для скорости
    
    async def parse_with_semaphore(session, gift):
        async with semaphore:
            return await parse_gift_owner(session, gift['url'])
    
    async with aiohttp.ClientSession() as session:
        tasks = [parse_with_semaphore(session, gift) for gift in gifts]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                continue
            
            owner, gift_name = result
            
            if owner and owner.strip() and owner.lower() not in blacklist_lower:
                # Проверка на уникальность пользователя
                if owner.lower() not in seen_users:
                    seen_users.add(owner.lower())
                    found.append({
                        'name': gift_name or gifts[i]['name'],
                        'url': gifts[i]['url'],
                        'owner': owner
                    })
            
            # Обновляем статус каждые 5 результатов
            if status_message and i % 5 == 0 and i > 0:
                try:
                    await status_message.edit_text(
                        f"<b>{title}</b>\n"
                        f"🔍 Поиск... {i}/{len(gifts)}\n"
                        f"✅ Найдено уникальных: {len(found)}/{target_count}",
                        parse_mode=ParseMode.HTML
                    )
                except:
                    pass
            
            if len(found) >= target_count:
                break
    
    return found[:target_count]

# ========== ПОЛНЫЙ СПИСОК NFT ==========
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

# ========== ФИЛЬТРАЦИЯ МОЛОДЫХ ДЕВУШЕК ==========
async def check_female_username(username: str) -> tuple[bool, float, str]:
    """Проверяет юзернейм на принадлежность девушке"""
    username_clean = username.lower().strip('@')
    
    FEMALE_NAMES = {
        "anna", "olga", "maria", "elena", "natalia", "ekaterina", "tatyana", 
        "svetlana", "irina", "julia", "alexandra", "anastasia", "daria", "elizaveta",
        "kristina", "victoria", "valentina", "veronika", "alina", "karina",
        "lily", "rose", "violet", "jasmine", "kate", "sophia", "emma", "mia",
        "luna", "chloe", "zoe", "ava", "isabella", "olivia", "amelia", "sofia",
        "alice", "eva", "mila", "nina", "tina", "lina", "dina", "kira", "maya"
    }
    
    if username_clean in FEMALE_NAMES:
        return (True, 0.95, f"имя {username_clean}")
    
    parts = re.split(r'[_.\-]', username_clean)
    for part in parts:
        if part in FEMALE_NAMES:
            return (True, 0.85, f"часть '{part}'")
    
    female_endings = ['a', 'я', 'ina', 'ova', 'eva', 'iya', 'ia', 'ka', 'sha']
    for ending in female_endings:
        if username_clean.endswith(ending) and len(username_clean) > 3:
            if not any(x in username_clean for x in ['bot', 'admin', 'support']):
                return (True, 0.70, f"окончание '{ending}'")
    
    return (False, 0.5, "не определена")

async def filter_young_female_users(found_users: list, min_confidence: float = 0.6) -> list:
    """Фильтрует только молодых девушек с уникальными пользователями"""
    filtered = []
    seen_users = set()
    
    for user in found_users:
        username = user['owner']
        username_clean = username.lower().strip('@')
        
        if username_clean in seen_users:
            continue
        
        is_female, female_conf, female_reason = await check_female_username(username_clean)
        
        if not is_female or female_conf < min_confidence:
            continue
        
        is_young = False
        age_reason = []
        
        # Проверка по году рождения
        year_match = re.search(r'(20[0-2][0-9]|200[5-9]|201[0-9])', username_clean)
        if year_match:
            year = int(year_match.group())
            age = 2024 - year
            if age <= 25:
                is_young = True
                age_reason.append(f"{age} лет")
            else:
                continue
        
        # Молодежные паттерны
        young_patterns = [
            r'[a-z]{3}[0-9]{1,2}$',
            r'[a-z]{2,4}[0-9]{2,4}',
            r'x{2,}', r'q{2,}', r'w{2,}',
            r'[a-z]{4,}[0-9]{3,}',
        ]
        
        for pattern in young_patterns:
            if re.search(pattern, username_clean):
                is_young = True
                age_reason.append("молодежный паттерн")
                break
        
        # Взрослые имена
        adult_names = ['olga', 'svetlana', 'tatyana', 'elena', 'natalia', 'irina', 
                       'lyudmila', 'galina', 'nadezhda', 'vera', 'lubov', 'marina']
        if any(name in username_clean for name in adult_names):
            continue
        
        # Короткие юзернеймы
        if not is_young and len(username_clean) <= 8:
            is_young = True
            age_reason.append("короткий юзернейм")
        
        if is_young or female_conf > 0.85:
            seen_users.add(username_clean)
            user['age'] = 'young'
            user['gender_reason'] = f"{female_reason}, {', '.join(age_reason) if age_reason else 'молодая'}"
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

# ========== STATUS ==========
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

🎲 Рандом поиск - поиск по режимам
🔍 Поиск по модели - точный поиск по NFT
👧 Поиск девушек - только молодые (до 25 лет)"""
    
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

🟢 Легкий режим - до 3 TON
🟡 Средний режим - 3-15 TON
🔴 Жирный режим - 15-600 TON"""
    keyboard = [
        [InlineKeyboardButton("🟢 Легкий режим", callback_data="mode_light")],
        [InlineKeyboardButton("🟡 Средний режим", callback_data="mode_medium")],
        [InlineKeyboardButton("🔴 Жирный режим", callback_data="mode_heavy")],
        [InlineKeyboardButton("🔷 Назад", callback_data="menu_search")]
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
    
    mode_names = {
        "light": "🟢 Легкий",
        "medium": "🟡 Средний",
        "heavy": "🔴 Жирный",
        "girls": "👧 Девушки"
    }
    
    display_title = mode_names.get(mode, title or "Поиск")
    
    if is_girls:
        text = f"🔷 <b>Найдено молодых девушек в режиме «{display_title}»:</b>\n\n"
    else:
        text = f"🔷 <b>Найдено в режиме «{display_title}»:</b>\n\n"
    
    for i, item in enumerate(page_results, start=start+1):
        clean_owner = item['owner'][1:] if item['owner'].startswith('@') else item['owner']
        encoded_text = quote(message_template)
        
        write_url = f"https://t.me/{clean_owner}?text={encoded_text}"
        text += f"{i}. LINK NFT | @{clean_owner} | <a href=\"{write_url}\">Написать</a>\n"
    
    text += f"\n📊 Страница {page}/{total_pages} | 👥 Уникальные пользователи"
    
    keyboard = []
    
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"results_page_{mode}_{page-1}_{nft_name or ''}_{is_girls}"))
        nav.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="noop"))
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
    
    generate_count = target_count * 3
    
    if is_girls:
        title = "👧 Поиск девушек"
        gifts = generate_girls_gifts(generate_count)
    elif nft_name:
        title = f"🔍 Поиск {nft_name}"
        gifts = []
        for _ in range(generate_count):
            clean_name = re.sub(r"[^\w]", "", nft_name)
            nft = NFT_DICT.get(nft_name)
            if nft:
                nft_id = random.randint(nft["min_id"], nft["max_id"])
                gifts.append({"name": nft_name, "url": f"https://t.me/nft/{clean_name}-{nft_id}"})
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
        f"🔍 <b>{title}</b>\n⏳ Ищем уникальных владельцев...",
        parse_mode=ParseMode.HTML
    )
    
    found = await find_real_owners_parallel(gifts, target_count, title, status_msg)
    
    if is_girls and found:
        await status_msg.edit_text(
            f"👧 Найдено {len(found)} пользователей\n🎀 Отбираем молодых девушек...",
            parse_mode=ParseMode.HTML
        )
        found = await filter_young_female_users(found)
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
    nav.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="noop"))
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
🎮 Режим: {settings['default_mode']}"""
    
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

📊 Количество результатов: {current}
📝 Шаблон сообщения
🎮 Режим по умолчанию: {settings['default_mode']}"""
    
    keyboard = [
        [InlineKeyboardButton(f"📊 Количество ({current})", callback_data="settings_results")],
        [InlineKeyboardButton("📝 Шаблон сообщения", callback_data="settings_template")],
        [InlineKeyboardButton("🎮 Режим по умолчанию", callback_data="settings_mode")],
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

async def show_template_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    settings = await get_user_settings(user_id)
    current_template = settings['message_template']
    
    text = f"""🔷 <b>Настройка шаблона сообщения</b>

📝 Текущий шаблон:
<code>{current_template}</code>

✏️ Введите новый текст в чат"""
    
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

🟢 Легкий - до 3 TON
🟡 Средний - 3-15 TON
🔴 Жирный - 15-600 TON"""
    
    keyboard = [
        [InlineKeyboardButton("🟢 Легкий", callback_data="set_mode_light"),
         InlineKeyboardButton("🟡 Средний", callback_data="set_mode_medium")],
        [InlineKeyboardButton("🔴 Жирный", callback_data="set_mode_heavy")],
        [InlineKeyboardButton("🔷 Назад", callback_data="menu_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

# ========== ПОДДЕРЖКА ==========
async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = """🔷 <b>ПОДДЕРЖКА</b>

По всем вопросам: @zotlu"""
    keyboard = [[InlineKeyboardButton("🔷 Главное меню", callback_data="main_menu")]]
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
    elif data == "settings_template":
        await show_template_settings(update, context)
    elif data == "settings_mode":
        await show_mode_settings(update, context)
    elif data == "reset_template":
        await reset_template(update, context)
    elif data.startswith("set_mode_"):
        mode = data.split("_")[2]
        await save_user_settings(user_id, default_mode=mode)
        await query.answer(f"✅ Режим: {mode}")
        await show_settings(update, context)
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
    print("✅ Улучшенный парсинг (3 метода поиска)")
    print("✅ Дедупликация пользователей")
    print("✅ Быстрый поиск (15 одновременных запросов)")
    print("✅ Фильтр молодых девушек (до 25 лет)")
    print("✅ Статистика пользователей")
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