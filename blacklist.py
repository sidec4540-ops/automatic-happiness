import aiosqlite
import logging

DB_FILE = 'bot_database.db'

# Стартовый список релеев
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
    logging.info("✅ Таблица blacklist инициализирована")

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
        logging.error(f"❌ Ошибка получения ЧС: {e}")
        return []

async def add_to_blacklist(username: str) -> bool:
    try:
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute(
                "INSERT OR IGNORE INTO blacklist (username) VALUES (?)",
                (username.lower(),)
            )
            await db.commit()
            return True
    except Exception as e:
        logging.error(f"❌ Ошибка добавления: {e}")
        return False

async def remove_from_blacklist(username: str) -> bool:
    try:
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute(
                "DELETE FROM blacklist WHERE username = ?",
                (username.lower(),)
            )
            await db.commit()
            return True
    except Exception as e:
        logging.error(f"❌ Ошибка удаления: {e}")
        return False