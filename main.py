\import logging
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
BOT_TOKEN = "8603618322:AAHO3vW5ijXSbgdN_Ls9fxzwMcN-ewGKCuk"
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

# ========== БАЗА ДАННЫХ ДЛЯ БАН-ЛИСТА ==========
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

async def get_blacklist() -> list[str]:
    try:
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute("SELECT username FROM blacklist") as cursor:
                return [row[0] for row in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"Ошибка получения бан-листа: {e}")
        return []

# ========== ФУНКЦИИ ПАРСИНГА (С ПОДДЕРЖКОЙ _ ) ==========
async def parse_gift_owner(session: aiohttp.ClientSession, url: str) -> dict | None:
    """Парсит страницу подарка и возвращает информацию о владельце"""
    try:
        async with session.get(url, timeout=10, allow_redirects=False) as response:
            if response.status != 200:
                return None
            html = await response.text()
            soup = BeautifulSoup(html, "html.parser")
            
            # Ищем таблицу с владельцем
            owner_tag = soup.select_one('table.tgme_gift_table th:-soup-contains("Owner") + td a')
            if owner_tag and owner_tag.get('href'):
                username = owner_tag['href'].replace('https://t.me/', '')
                # Регулярка с поддержкой подчеркивания
                if re.match(r'^[a-zA-Z0-9_]{5,32}$', username):
                    return {
                        'url': url,
                        'owner': f"@{username}",
                        'success': True
                    }
            
            # Альтернативный поиск
            owner_link = soup.find('a', href=lambda x: x and x.startswith('https://t.me/') and not any(
                skip in x for skip in ['nft', 'gift', 'joinchat']))
            if owner_link:
                username = owner_link['href'].replace('https://t.me/', '')
                if re.match(r'^[a-zA-Z0-9_]{5,32}$', username):
                    return {
                        'url': url,
                        'owner': f"@{username}",
                        'success': True
                    }
            
            # Поиск по тексту страницы
            text = soup.get_text()
            username_match = re.search(r'@([a-zA-Z0-9_]{5,32})', text)
            if username_match:
                username = username_match.group(1)
                return {
                    'url': url,
                    'owner': f"@{username}",
                    'success': True
                }
                
            return None
    except Exception as e:
        logger.debug(f"Ошибка парсинга {url}: {e}")
        return None

async def find_real_owners_batch(urls: list, target_count: int = 100) -> list:
    """Параллельно проверяет все ссылки и возвращает до target_count результатов"""
    blacklist = await get_blacklist()
    blacklist_lower = [u.lower() for u in blacklist]
    
    async with aiohttp.ClientSession() as session:
        tasks = [parse_gift_owner(session, url) for url in urls]
        results = await asyncio.gather(*tasks)
        
        found = []
        for res in results:
            if res and res.get('success'):
                owner = res.get('owner')
                if owner and owner.lower() not in blacklist_lower:
                    found.append(res)
                    if len(found) >= target_count:
                        break
        
        return found[:target_count]

# ========== ПОЛНЫЙ СПИСОК NFT ==========
NFT_LIST = [
    {"name": "BDayCandle", "difficulty": "easy", "id_range": "1000-20000", "min_id": 1000, "max_id": 20000},
    {"name": "CandyCane", "difficulty": "easy", "id_range": "1000-150000", "min_id": 1000, "max_id": 150000},
    # ... остальные NFT (оставь как есть, я сократил для читаемости)
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
users_db = {}
user_settings = {}
last_message_ids = {}
blocked_nfts = {}

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

# ========== ФУНКЦИИ ДЛЯ УДАЛЕНИЯ СООБЩЕНИЙ ==========
async def delete_previous_messages(update: Update, context):
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

# ========== КОМАНДА START ==========
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
        [InlineKeyboardButton("🟡 Средний", callback_data="mode_medium")],
        [InlineKeyboardButton("🔴 Жирный", callback_data="mode_heavy")],
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

# ========== ПОКАЗ РЕЗУЛЬТАТОВ (С КЭШИРОВАНИЕМ, ПОДДЕРЖКОЙ _, 100 РЕЗУЛЬТАТОВ) ==========
async def show_paginated_results(message, found, mode, nft_name, page, title, context):
    """Отдельная функция для отображения страницы результатов"""
    items_per_page = 10
    total_pages = (len(found) + items_per_page - 1) // items_per_page
    start = (page - 1) * items_per_page
    end = min(start + items_per_page, len(found))
    page_results = found[start:end]
    
    # Заголовок
    text = f"🎯 *Найдено владельцев: {len(found)}*\n"
    if title:
        text += f"📌 {title}\n"
    text += f"📄 Страница {page}/{total_pages}\n"
    text += "─" * 30 + "\n\n"
    
    # Результаты с поддержкой подчеркивания
    for i, item in enumerate(page_results, start=start+1):
        owner = item['owner']
        # Убираем @ для ссылки
        clean_owner = owner[1:] if owner.startswith('@') else owner
        # Ссылка "Написать" работает с любыми символами
        write_link = f"tg://user?domain={clean_owner}"
        
        text += f"{i}. 🔗 [Подарок]({item['url']}) | [Написать]({write_link})\n\n"
    
    # Кнопки навигации
    keyboard = []
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"results_page_{mode}_{page-1}_{nft_name or ''}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"results_page_{mode}_{page+1}_{nft_name or ''}"))
        keyboard.append(nav)
    
    keyboard.append([InlineKeyboardButton("🔄 Новый поиск", callback_data="search_random")])
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    
    await message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )

async def show_search_results(update: Update, context, mode, nft_name=None, page=1):
    query = update.callback_query
    user_id = query.from_user.id
    
    # Ключ для кэша
    cache_key = f"{user_id}_{mode}_{nft_name or ''}"
    
    # Инициализируем хранилище кэша в context.user_data
    if 'search_results' not in context.user_data:
        context.user_data['search_results'] = {}
    
    # Если результаты уже есть в кэше и мы не на первой странице - показываем без поиска
    if cache_key in context.user_data['search_results']:
        found = context.user_data['search_results'][cache_key]
        await show_paginated_results(query.message, found, mode, nft_name, page, None, context)
        return
    
    # Если нет результатов - запускаем поиск
    target_count = 100
    generate_count = target_count * 3
    
    # Генерация ссылок
    if nft_name:
        urls = generate_gift_links(nft_name, generate_count)
        title = f"Подарок: {nft_name}"
    elif mode == "girls":
        gifts = generate_girls_gifts(generate_count)
        urls = [g['url'] for g in gifts]
        title = "👧 Поиск девушек"
    else:
        gifts = generate_random_gifts(mode, generate_count)
        urls = [g['url'] for g in gifts]
        mode_names = {"light": "🟢 Легкий", "medium": "🟡 Средний", "heavy": "🔴 Жирный"}
        title = f"Режим: {mode_names[mode]}"
    
    status_msg = await query.message.edit_text(
        f"🔍 Ищу {target_count} реальных владельцев...\n"
        f"📊 Проверяю {len(urls)} ссылок параллельно\n"
        f"⏳ Ожидай..."
    )
    
    # Быстрый параллельный поиск
    found = await find_real_owners_batch(urls, target_count)
    
    # Сохраняем в кэш
    context.user_data['search_results'][cache_key] = found
    
    if user_id in users_db:
        users_db[user_id]['searches'] += 1
        users_db[user_id]['found'] += len(found)
    
    if not found:
        kb = [[InlineKeyboardButton("🔄 Ещё", callback_data="search_random")]]
        await status_msg.edit_text("❌ Никого не найдено.", reply_markup=InlineKeyboardMarkup(kb))
        return
    
    # Показываем первую страницу
    await show_paginated_results(status_msg, found, mode, nft_name, page, title, context)

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
    elif data.startswith("results_page_"):
        parts = data.split("_")
        mode = parts[2]
        page = int(parts[3])
        nft_name = parts[4] if len(parts) > 4 and parts[4] else None
        await show_search_results(update, context, mode, nft_name, page)
    elif data == "noop":
        pass

# ========== АДМИН-КОМАНДЫ ДЛЯ БАН-ЛИСТА ==========
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
            await db.execute(
                "INSERT OR IGNORE INTO blacklist (username) VALUES (?)",
                (username.lower(),)
            )
            await db.commit()
        await update.message.reply_text(f"✅ {username} добавлен в бан-лист")
    except (IndexError, ValueError):
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
            await db.execute(
                "DELETE FROM blacklist WHERE username = ?",
                (username.lower(),)
            )
            await db.commit()
        await update.message.reply_text(f"✅ {username} удален из бан-листа")
    except (IndexError, ValueError):
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
    
    text = "📋 **Бан-лист релеев:**\n\n"
    for i, username in enumerate(blacklist, 1):
        text += f"{i}. {username}\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ========== HELP ==========
async def help_command(update: Update, context):
    if not await require_subscription(update, context):
        return
    text = "🆘 СПРАВКА\n\n/start - Начать работу\n/help - Справка"
    await update.message.reply_text(text)

# ========== STATUS ==========
async def status_command(update: Update, context):
    if not await require_subscription(update, context):
        return
    user_id = update.effective_user.id
    subscribed = await check_subscription(user_id, context)
    text = f"""📊 ВАШ СТАТУС

Подписка: {'✅ В КАНАЛЕ' if subscribed else '❌ НЕТ'}
Поисков: {users_db.get(user_id, {}).get('searches', 0)}"""
    await update.message.reply_text(text)

# ========== ЗАПУСК ==========
def main():
    # Инициализация БД
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_blacklist_db())
    loop.run_until_complete(init_default_blacklist())
    
    print("=" * 60)
    print("🚀 NFT ПАРСЕР — 100+ РЕЗУЛЬТАТОВ")
    print("=" * 60)
    print(f"📢 ID канала: {CHANNEL_ID}")
    print(f"👧 Женских NFT: {len(GIRLS_NFT_LIST)}")
    print("✅ Поиск 100 результатов параллельно")
    print("✅ Поддержка _ в юзернеймах")
    print("✅ Кэширование при пагинации")
    print("✅ Выдача: Ссылка | Написать")
    print("✅ Бан-лист релеев")
    print("=" * 60)
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    
    # Админ-команды
    app.add_handler(CommandHandler("addban", add_blacklist))
    app.add_handler(CommandHandler("removeban", remove_blacklist))
    app.add_handler(CommandHandler("listban", list_blacklist))
    
    app.add_handler(CallbackQueryHandler(handle_menu))
    
    print("✅ Бот готов!")
    app.run_polling()

if __name__ == "__main__":
    main()
