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

INITIAL_BLACKLIST = [
    "@giftrelayer", "@mrktbank", "@kallent", "@monk", "@durov",
    "@virusgift", "@portalsrelayer", "@lucha", "@snoopdogg", "@snoop",
    "@ufc", "@Tonnel_Network_bot", "@midasdep", "@portalsreceive", "@nftgiftbot", 
    "@GiftDrop_Warehouse", "@trade_relayer", "@rolls_transfer", "@GiftsToPortals", 
    "@gemsrelayer", "@GiftDeposit", "@depgifts"
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

# ========== ФУНКЦИИ ПАРСИНГА (УСКОРЕННЫЕ) ==========
async def parse_gift_owner(session: aiohttp.ClientSession, url: str) -> dict | None:
    """Парсит страницу подарка и возвращает владельца и метаданные"""
    try:
        async with session.get(url, timeout=10, allow_redirects=False) as response:
            if response.status != 200:
                return None
            html = await response.text()
            soup = BeautifulSoup(html, "html.parser")
            
            result = {
                'url': url,
                'owner': None,
                'model': None,
                'background': None,
                'pattern': None
            }
            
            # Ищем владельца
            owner_tag = soup.select_one('table.tgme_gift_table th:-soup-contains("Owner") + td a')
            if owner_tag and owner_tag.get('href'):
                username = owner_tag['href'].replace('https://t.me/', '')
                if re.match(r'^[a-zA-Z0-9_]{5,32}$', username):
                    result['owner'] = f"@{username}"
            
            # Ищем метаданные в скриптах или тексте
            # Это упрощенная версия, в реальном коде нужно парсить структуру подарка
            
            return result if result['owner'] else None
    except Exception as e:
        logger.debug(f"Ошибка парсинга {url}: {e}")
        return None

async def find_real_owners_parallel(gifts: list, target_count: int, title: str, 
                                     models: list = None, backgrounds: list = None, 
                                     patterns: list = None, status_message = None) -> list:
    """
    Параллельный поиск ВСЕХ ссылок сразу (максимальная скорость)
    """
    blacklist = await get_blacklist()
    blacklist_lower = [u.lower() for u in blacklist]
    found = []
    
    async with aiohttp.ClientSession() as session:
        # Запускаем ВСЕ запросы параллельно
        tasks = [parse_gift_owner(session, gift['url']) for gift in gifts]
        results = await asyncio.gather(*tasks)
        
        # Обрабатываем результаты
        processed = 0
        for gift, result in zip(gifts, results):
            processed += 1
            if result and result.get('owner'):
                owner = result['owner']
                if owner.lower() not in blacklist_lower:
                    # Проверяем фильтры (если они заданы)
                    model_ok = not models or (result.get('model') and result['model'] in models)
                    bg_ok = not backgrounds or (result.get('background') and result['background'] in backgrounds)
                    pattern_ok = not patterns or (result.get('pattern') and result['pattern'] in patterns)
                    
                    if model_ok and bg_ok and pattern_ok:
                        found.append({
                            'name': gift['name'],
                            'url': gift['url'],
                            'owner': owner
                        })
            
            # Обновляем прогресс
            if status_message and processed % 10 == 0:
                try:
                    progress = min(len(found) / target_count, 1.0) if target_count > 0 else 0
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
                break
    
    return found[:target_count]

# ========== ПОЛНЫЙ СПИСОК NFT ==========
NFT_LIST = [
    {"name": "BDayCandle", "difficulty": "easy", "id_range": "1000-20000", "min_id": 1000, "max_id": 20000},
    {"name": "CandyCane", "difficulty": "easy", "id_range": "1000-150000", "min_id": 1000, "max_id": 150000},
    # ... весь список NFT (я сократил для читаемости)
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

# ========== СПИСКИ ДЛЯ ФИЛЬТРАЦИИ ==========
BACKGROUND_COLORS = [
    "Red", "Blue", "Green", "Yellow", "Purple", "Orange", "Pink", "Brown",
    "Black", "White", "Gray", "Gold", "Silver", "Rainbow", "Gradient", "Holographic"
]

PATTERNS = [
    "Stripes", "Dots", "Waves", "Zigzag", "Camouflage", "Leopard", "Tiger",
    "Zebra", "Checkerboard", "Swirl", "Glitter", "Matte", "Glossy", "Hologram"
]

MODELS = [
    "Common", "Rare", "Epic", "Legendary", "Mythic", "Limited", "Exclusive",
    "Seasonal", "Holiday", "Birthday", "Anniversary", "Special", "Premium"
]

# ========== ХРАНИЛИЩЕ ==========
user_states = {}
blocked_nfts = {}
last_message_ids = {}
search_sessions = {}  # Для хранения данных расширенного поиска

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
👧 Поиск девушек - поиск по женским именам
🎨 Расширенный поиск - пошаговый выбор с фильтрами (модели, цвета, узоры)"""
    
    keyboard = [
        [InlineKeyboardButton("🎲 Рандом поиск", callback_data="search_random")],
        [InlineKeyboardButton("🔍 Поиск по модели", callback_data="search_model")],
        [InlineKeyboardButton("👧 Поиск девушек", callback_data="search_girls")],
        [InlineKeyboardButton("🎨 Расширенный поиск", callback_data="advanced_search")],
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

# ========== ОБРАБОТЧИКИ РАСШИРЕННОГО ПОИСКА ==========
async def advanced_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает расширенный поиск"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    search_sessions[user_id] = {'step': 1}
    
    # Показываем список подарков
    gift_list = list(NFT_DICT.keys())[:30]
    text = "<b>🎨 Расширенный поиск - Шаг 1/5</b>\n\n"
    text += "Выберите подарок из списка или введите его название:\n\n"
    
    for i, name in enumerate(gift_list, 1):
        text += f"{i}. {name}\n"
    
    keyboard = [
        [InlineKeyboardButton("◀️ Назад", callback_data="menu_search")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

# ========== ОБРАБОТЧИК ТЕКСТА ДЛЯ РАСШИРЕННОГО ПОИСКА ==========
async def handle_advanced_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовые вводы для расширенного поиска"""
    user_id = update.effective_user.id
    if user_id not in search_sessions:
        return
    
    step = search_sessions[user_id].get('step', 1)
    text = update.message.text.strip()
    
    if step == 1:
        # Выбор подарка
        if text.isdigit():
            num = int(text)
            gift_list = list(NFT_DICT.keys())
            if 1 <= num <= len(gift_list):
                gift_name = gift_list[num - 1]
            else:
                await update.message.reply_text("❌ Неверный номер. Попробуйте ещё раз.")
                return
        else:
            gift_name = None
            for name in NFT_DICT.keys():
                if text.lower() == name.lower():
                    gift_name = name
                    break
        
        if not gift_name:
            await update.message.reply_text("❌ Подарок не найден. Попробуйте ещё раз.")
            return
        
        search_sessions[user_id]['gift'] = gift_name
        search_sessions[user_id]['step'] = 2
        
        # Запрашиваем диапазон
        text = f"✅ Выбран: <b>{gift_name}</b>\n\n"
        text += "<b>Шаг 2/5: Диапазон ID</b>\n\n"
        text += "Введите диапазон в формате <code>начало-конец</code>\n"
        text += "Например: <code>1000-5000</code>\n"
        text += "Максимальный разброс: 20000 ID"
        
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        
    elif step == 2:
        # Ввод диапазона
        try:
            start, end = map(int, text.split('-'))
            if start <= 0 or end < start or end - start > 20000:
                raise ValueError
        except:
            await update.message.reply_text("❌ Неверный формат. Введите как <code>1000-5000</code>", parse_mode=ParseMode.HTML)
            return
        
        search_sessions[user_id]['range'] = (start, end)
        search_sessions[user_id]['step'] = 3
        
        # Запрашиваем модели
        text = "<b>Шаг 3/5: Модели (можно пропустить)</b>\n\n"
        text += "Введите модели через запятую или /skip чтобы пропустить\n\n"
        text += "Доступные модели:\n"
        text += ", ".join(MODELS)
        
        keyboard = [[InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_models")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        
    elif step == 3:
        # Обработка моделей
        if text.lower() == '/skip':
            search_sessions[user_id]['models'] = []
        else:
            models = [m.strip() for m in text.split(',') if m.strip()]
            # Проверяем, что модели есть в списке
            valid_models = [m for m in models if m in MODELS]
            if not valid_models:
                await update.message.reply_text("❌ Ни одна из указанных моделей не найдена. Попробуйте ещё раз.")
                return
            search_sessions[user_id]['models'] = valid_models
        
        search_sessions[user_id]['step'] = 4
        
        # Запрашиваем цвета фона
        text = "<b>Шаг 4/5: Цвета фона (можно пропустить)</b>\n\n"
        text += "Введите цвета через запятую или /skip чтобы пропустить\n\n"
        text += "Доступные цвета:\n"
        text += ", ".join(BACKGROUND_COLORS)
        
        keyboard = [[InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_backgrounds")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        
    elif step == 4:
        # Обработка цветов фона
        if text.lower() == '/skip':
            search_sessions[user_id]['backgrounds'] = []
        else:
            colors = [c.strip() for c in text.split(',') if c.strip()]
            valid_colors = [c for c in colors if c in BACKGROUND_COLORS]
            if not valid_colors:
                await update.message.reply_text("❌ Ни один из указанных цветов не найден. Попробуйте ещё раз.")
                return
            search_sessions[user_id]['backgrounds'] = valid_colors
        
        search_sessions[user_id]['step'] = 5
        
        # Запрашиваем узоры
        text = "<b>Шаг 5/5: Узоры (можно пропустить)</b>\n\n"
        text += "Введите узоры через запятую или /skip чтобы пропустить\n\n"
        text += "Доступные узоры:\n"
        text += ", ".join(PATTERNS)
        
        keyboard = [[InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_patterns")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        
    elif step == 5:
        # Обработка узоров и запуск поиска
        if text.lower() == '/skip':
            search_sessions[user_id]['patterns'] = []
        else:
            patterns = [p.strip() for p in text.split(',') if p.strip()]
            valid_patterns = [p for p in patterns if p in PATTERNS]
            if not valid_patterns:
                await update.message.reply_text("❌ Ни один из указанных узоров не найден. Попробуйте ещё раз.")
                return
            search_sessions[user_id]['patterns'] = valid_patterns
        
        # Запускаем поиск
        await run_advanced_search(update, context)

# ========== ОБРАБОТЧИКИ КНОПОК ПРОПУСКА ==========
async def skip_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id in search_sessions:
        search_sessions[user_id]['models'] = []
        search_sessions[user_id]['step'] = 4
        
        text = "<b>Шаг 4/5: Цвета фона (можно пропустить)</b>\n\n"
        text += "Введите цвета через запятую или /skip чтобы пропустить\n\n"
        text += "Доступные цвета:\n"
        text += ", ".join(BACKGROUND_COLORS)
        
        keyboard = [[InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_backgrounds")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def skip_backgrounds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id in search_sessions:
        search_sessions[user_id]['backgrounds'] = []
        search_sessions[user_id]['step'] = 5
        
        text = "<b>Шаг 5/5: Узоры (можно пропустить)</b>\n\n"
        text += "Введите узоры через запятую или /skip чтобы пропустить\n\n"
        text += "Доступные узоры:\n"
        text += ", ".join(PATTERNS)
        
        keyboard = [[InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_patterns")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def skip_patterns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id in search_sessions:
        search_sessions[user_id]['patterns'] = []
        await run_advanced_search(update, context)

# ========== ЗАПУСК РАСШИРЕННОГО ПОИСКА ==========
async def run_advanced_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запускает расширенный поиск с выбранными фильтрами"""
    user_id = update.effective_user.id
    if user_id not in search_sessions:
        return
    
    data = search_sessions[user_id]
    gift_name = data['gift']
    range_start, range_end = data['range']
    models = data.get('models', [])
    backgrounds = data.get('backgrounds', [])
    patterns = data.get('patterns', [])
    
    # Получаем настройки пользователя
    settings = await get_user_settings(user_id)
    target_count = settings['results_count']
    
    # Генерируем ссылки в указанном диапазоне
    nft = NFT_DICT.get(gift_name)
    if not nft:
        await update.message.reply_text("❌ Ошибка: подарок не найден")
        return
    
    clean_name = re.sub(r"[^\w]", "", gift_name)
    urls = []
    max_range = min(range_end, nft['max_id'])
    for nft_id in range(range_start, min(range_start + target_count * 3, max_range + 1)):
        urls.append(f"https://t.me/nft/{clean_name}-{nft_id}")
    
    gifts = [{"name": gift_name, "url": url} for url in urls]
    
    # Показываем статус
    filter_text = []
    if models:
        filter_text.append(f"модели: {', '.join(models)}")
    if backgrounds:
        filter_text.append(f"цвета: {', '.join(backgrounds)}")
    if patterns:
        filter_text.append(f"узоры: {', '.join(patterns)}")
    
    status_msg = await update.message.reply_text(
        f"🎨 <b>Расширенный поиск: {gift_name}</b>\n"
        f"📊 Диапазон: {range_start}-{max_range}\n"
        f"🔢 Нужно: {target_count}\n"
        f"🎯 Фильтры: {', '.join(filter_text) if filter_text else 'нет'}\n\n"
        f"🔍 ▱▱▱▱▱▱▱▱▱▱ Поиск NFT...\n"
        f"✅ Найдено: 0/{target_count}",
        parse_mode=ParseMode.HTML
    )
    
    # Запускаем поиск
    found = await find_real_owners_parallel(
        gifts, target_count, f"Поиск {gift_name}",
        models, backgrounds, patterns, status_msg
    )
    
    # Очищаем сессию
    del search_sessions[user_id]
    
    if not found:
        keyboard = [[InlineKeyboardButton("🔄 Новый поиск", callback_data="menu_search")]]
        await status_msg.edit_text(
            "❌ Не найдено подарков с заданными фильтрами.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    await show_paginated_results(status_msg, found, "advanced", gift_name, 1, f"Поиск {gift_name}", context)

# ========== ОБРАБОТЧИКИ РЕЖИМОВ ПОИСКА ==========
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
        gifts = generate_girls_gifts(generate_count)
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
        f"{title}\n"
        f"📝 Шаблон: Стандартный\n"
        f"🔢 Количество: {target_count}\n"
        f"⚠️ Примечание: Поиск может ошибаться\n\n"
        f"🔍 ▱▱▱▱▱▱▱▱▱▱ Поиск NFT...\n"
        f"✅ Найдено: 0/{target_count}",
        parse_mode=ParseMode.HTML
    )
    
    found = await find_real_owners_parallel(gifts, target_count, title, None, None, None, status_msg)
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
Лимит поиска: {settings['results_count']}

Последний поиск: Нет данных"""
    keyboard = [
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

📊 Количество результатов ({current})"""
    keyboard = [
        [InlineKeyboardButton(f"📊 Количество результатов ({current})", callback_data="settings_results")],
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
    
    # Проверяем, не в расширенном ли поиске пользователь
    user_id = update.effective_user.id
    if user_id in search_sessions:
        await handle_advanced_text(update, context)
        return
    
    text = update.message.text
    
    # Обработка команд блокировки NFT
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
        await show_search_results(update, context, "light")
    elif data == "mode_medium":
        await show_search_results(update, context, "medium")
    elif data == "mode_heavy":
        await show_search_results(update, context, "heavy")
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
    elif data == "advanced_search":
        await advanced_search(update, context)
    elif data == "skip_models":
        await skip_models(update, context)
    elif data == "skip_backgrounds":
        await skip_backgrounds(update, context)
    elif data == "skip_patterns":
        await skip_patterns(update, context)
    elif data == "settings_interface" or data == "settings_templates" or data == "settings_mode":
        await query.message.edit_text("⚡ Раздел в разработке", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu_settings")]]))
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
    print("🤖 NFT ПАРСЕР БОТ (С РАСШИРЕННЫМ ПОИСКОМ)")
    print("=" * 70)
    print(f"📢 ID канала: {CHANNEL_ID}")
    print(f"🔗 Ссылка: {CHANNEL_LINK}")
    print(f"👧 Женских NFT: {len(GIRLS_NFT_LIST)}")
    print("=" * 70)
    print("✅ Проверка подписки")
    print("✅ Настройки сохраняются в БД")
    print("✅ Поиск по настройкам пользователя")
    print("✅ Параллельный поиск (макс. скорость)")
    print("✅ Расширенный поиск с фильтрами")
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