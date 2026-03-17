import logging
import random
import re
import asyncio
import aiohttp
import aiosqlite
from datetime import datetime
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

# ========== ТВОИ ДАННЫЕ ==========
BOT_TOKEN = "8430585997:AAFE8C3ostnoTQiwSlwVmYpnVQI5FjbsCRc"
CHANNEL_LINK = "https://t.me/+WLiiYR7_ymZjYWY1"
CHANNEL_ID = -1003256576224
ADMIN_ID = 571001160

# ========== НАСТРОЙКИ ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== БАЗА ДАННЫХ ==========
DB_FILE = 'bot_database.db'

INITIAL_BLACKLIST = [
    "@giftrelayer", "@mrktbank", "@kallent", "@monk", "@durov",
    "@virusgift", "@portalsrelayer", "@lucha", "@snoopdogg", "@snoop",
    "@ufc", "@nft", "@telegram", "@nftgift", "@nftgiftbot", "@ton", "@gift"
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

async def get_blacklist():
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT username FROM blacklist") as cursor:
            return [row[0] for row in await cursor.fetchall()]

# ========== ПАРСЕР ==========
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
                return f"@{username}"
            
            owner_link = soup.find('a', href=lambda x: x and x.startswith('https://t.me/') and not any(
                skip in x for skip in ['nft', 'gift', 'joinchat']))
            if owner_link:
                username = owner_link['href'].replace('https://t.me/', '')
                return f"@{username}"
                
            return None
    except Exception as e:
        logging.debug(f"Ошибка парсинга {url}: {e}")
        return None

async def find_real_owners(urls: list, limit: int = 20) -> list:
    blacklist = await get_blacklist()
    blacklist_lower = [u.lower() for u in blacklist]
    
    async with aiohttp.ClientSession() as session:
        tasks = [parse_gift_owner(session, url) for url in urls]
        results = await asyncio.gather(*tasks)
        
        found = []
        for i, owner in enumerate(results):
            if owner and len(found) < limit:
                if owner.lower() in blacklist_lower:
                    continue
                found.append({
                    'url': urls[i],
                    'owner': owner
                })
        return found

# ========== NFT СПИСОК ==========
NFT_LIST = [
    {"name": "BDayCandle", "min_id": 1000, "max_id": 20000},
    {"name": "CandyCane", "min_id": 1000, "max_id": 150000},
    {"name": "CloverPin", "min_id": 1000, "max_id": 60000},
    {"name": "DeskCalendar", "min_id": 1000, "max_id": 13000},
    {"name": "FaithAmulet", "min_id": 1000, "max_id": 60000},
    {"name": "FreshSocks", "min_id": 1000, "max_id": 100000},
    {"name": "GingerCookie", "min_id": 1000, "max_id": 60000},
    {"name": "HappyBrownie", "min_id": 1000, "max_id": 60000},
    {"name": "HolidayDrink", "min_id": 1000, "max_id": 60000},
    {"name": "HomemadeCake", "min_id": 1000, "max_id": 130000},
    {"name": "IceCream", "min_id": 1000, "max_id": 60000},
    {"name": "InstantRamen", "min_id": 1000, "max_id": 60000},
    {"name": "JesterHat", "min_id": 1000, "max_id": 60000},
    {"name": "JingleBells", "min_id": 1000, "max_id": 60000},
    {"name": "LolPop", "min_id": 1000, "max_id": 130000},
    {"name": "LunarSnake", "min_id": 1000, "max_id": 250000},
    {"name": "PetSnake", "min_id": 1000, "max_id": 1000},
    {"name": "SnakeBox", "min_id": 1000, "max_id": 55000},
    {"name": "SnoopDogg", "min_id": 576241, "max_id": 576241},
    {"name": "SpicedWine", "min_id": 93557, "max_id": 93557},
    {"name": "WhipCupcake", "min_id": 1000, "max_id": 170000},
    {"name": "WinterWreath", "min_id": 65311, "max_id": 65311},
    {"name": "XmasStocking", "min_id": 177478, "max_id": 177478},
]

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
users_db = {}
user_settings = {}
last_message_ids = {}

# ========== ПРОВЕРКА ПОДПИСКИ ==========
async def check_subscription(user_id: int, context) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status not in ["left", "kicked"]
    except:
        return False

async def require_subscription(update: Update, context):
    user_id = update.effective_user.id
    if not await check_subscription(user_id, context):
        await show_subscription_required(update, context)
        return False
    return True

async def show_subscription_required(update: Update, context):
    keyboard = [[InlineKeyboardButton("📢 Подписаться", url=CHANNEL_LINK)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = "⚠️ Подпишись на канал!"
    if update.callback_query:
        await update.callback_query.message.edit_text(msg, reply_markup=reply_markup)
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup)

# ========== ФУНКЦИИ ГЕНЕРАЦИИ ==========
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
        available = [n for n in NFT_LIST]
    else:
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
async def show_main_menu(update: Update, context):
    user = update.effective_user
    text = f"❗ Привет, @{user.username or 'user'}! Это парсер для поиска мамонтов."
    keyboard = [
        [InlineKeyboardButton("🔍 Поиск NFT", callback_data="menu_search")],
        [InlineKeyboardButton("👤 Мой профиль", callback_data="menu_profile")],
        [InlineKeyboardButton("📢 Канал", url=CHANNEL_LINK)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

# ========== START ==========
async def start(update: Update, context):
    user_id = update.effective_user.id
    if not await require_subscription(update, context):
        return
    if user_id not in users_db:
        users_db[user_id] = {
            'username': update.effective_user.username or f"user{user_id}",
            'registered': datetime.now().strftime("%Y-%m-%d"),
            'searches': 0,
            'found': 0
        }
    await show_main_menu(update, context)

# ========== МЕНЮ ПОИСКА ==========
async def show_search_menu(update: Update, context):
    query = update.callback_query
    text = "Выбери тип поиска:"
    keyboard = [
        [InlineKeyboardButton("🎲 Рандом поиск", callback_data="search_random")],
        [InlineKeyboardButton("👧 Поиск девушек", callback_data="search_girls")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# ========== МЕНЮ РЕЖИМОВ ==========
async def show_modes_menu(update: Update, context):
    query = update.callback_query
    text = "Выбери режим:"
    keyboard = [
        [InlineKeyboardButton("🟢 Легкий", callback_data="mode_light")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# ========== ПРОФИЛЬ ==========
async def show_profile(update: Update, context):
    query = update.callback_query
    user_id = query.from_user.id
    user = users_db.get(user_id, {})
    text = f"ID: {user_id}\nUsername: @{user.get('username','unknown')}\nПоисков: {user.get('searches',0)}\nНайдено: {user.get('found',0)}"
    kb = [[InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))

# ========== ПОКАЗ РЕЗУЛЬТАТОВ ==========
async def show_search_results(update: Update, context, mode, nft_name=None, page=1):
    query = update.callback_query
    user_id = query.from_user.id
    count = user_settings.get(user_id, {}).get('results_count', 20)

    if nft_name:
        urls = generate_gift_links(nft_name, count)
        title = f"Подарок: {nft_name}"
    elif mode == "girls":
        gifts = generate_girls_gifts(count)
        urls = [g['url'] for g in gifts]
        title = "👧 Поиск девушек"
    else:
        gifts = generate_random_gifts(mode, count)
        urls = [g['url'] for g in gifts]
        title = "Режим: Легкий"

    await query.message.edit_text("🔍 Ищу реальных владельцев...")

    found = await find_real_owners(urls, limit=20)

    if user_id in users_db:
        users_db[user_id]['searches'] += 1
        users_db[user_id]['found'] += len(found)

    if not found:
        kb = [[InlineKeyboardButton("🔄 Ещё", callback_data="search_random")]]
        await query.message.edit_text("❌ Никого нет.", reply_markup=InlineKeyboardMarkup(kb))
        return

    text = f"*Найдено владельцев:* {len(found)}\n\n"
    for i, item in enumerate(found, 1):
        text += f"{i}. 👤 {item['owner']}\n   🎁 [Ссылка]({item['url']})\n\n"

    kb = [
        [InlineKeyboardButton("🔄 Новый поиск", callback_data="search_random")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='Markdown',
        disable_web_page_preview=True
    )

# ========== ОБРАБОТЧИК МЕНЮ ==========
async def handle_menu(update: Update, context):
    query = update.callback_query
    await query.answer()
    if not await require_subscription(update, context):
        return
    data = query.data
    if data == "main_menu":
        await show_main_menu(update, context)
    elif data == "menu_search":
        await show_search_menu(update, context)
    elif data == "menu_profile":
        await show_profile(update, context)
    elif data == "search_random":
        await show_modes_menu(update, context)
    elif data == "search_girls":
        await show_search_results(update, context, "girls")
    elif data.startswith("mode_"):
        mode = data.replace("mode_", "")
        await show_search_results(update, context, mode)

# ========== АДМИН-КОМАНДЫ ==========
async def add_blacklist(update: Update, context):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Нет прав")
        return
    try:
        username = context.args[0]
        if not username.startswith('@'):
            username = '@' + username
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("INSERT OR IGNORE INTO blacklist (username) VALUES (?)", (username.lower(),))
            await db.commit()
        await update.message.reply_text(f"✅ {username} добавлен в бан-лист")
    except:
        await update.message.reply_text("❌ Использование: /addban @username")

async def remove_blacklist(update: Update, context):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Нет прав")
        return
    try:
        username = context.args[0]
        if not username.startswith('@'):
            username = '@' + username
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("DELETE FROM blacklist WHERE username = ?", (username.lower(),))
            await db.commit()
        await update.message.reply_text(f"✅ {username} удален из бан-листа")
    except:
        await update.message.reply_text("❌ Использование: /removeban @username")

async def list_blacklist(update: Update, context):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Нет прав")
        return
    blacklist = await get_blacklist()
    if not blacklist:
        await update.message.reply_text("📋 Бан-лист пуст")
        return
    text = "📋 **Бан-лист:**\n"
    for i, username in enumerate(blacklist, 1):
        text += f"{i}. {username}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ========== ЗАПУСК ==========
def main():
    # Создаем новый цикл событий
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Инициализация БД в этом цикле
    loop.run_until_complete(init_blacklist_db())
    loop.run_until_complete(init_default_blacklist())
    
    print("=" * 50)
    print("🚀 NFT ПАРСЕР С БАН-ЛИСТОМ")
    print("=" * 50)
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_menu))
    
    app.add_handler(CommandHandler("addban", add_blacklist))
    app.add_handler(CommandHandler("removeban", remove_blacklist))
    app.add_handler(CommandHandler("listban", list_blacklist))
    
    print("✅ Бот готов!")
    
    # Запускаем бота в том же цикле
    loop.run_until_complete(app.run_polling())

if __name__ == "__main__":
    main()
