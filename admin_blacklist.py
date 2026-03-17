from telegram import Update
from telegram.ext import CommandHandler, ContextTypes
from telegram.constants import ParseMode
from blacklist import add_to_blacklist, remove_from_blacklist, get_blacklist

ADMIN_ID = 571001160

async def add_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Нет прав")
        return
    
    try:
        username = context.args[0]
        if not username.startswith('@'):
            username = '@' + username
        
        if await add_to_blacklist(username):
            await update.message.reply_text(f"✅ {username} добавлен в бан-лист")
        else:
            await update.message.reply_text("❌ Ошибка добавления")
    except IndexError:
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
        
        if await remove_from_blacklist(username):
            await update.message.reply_text(f"✅ {username} удален из бан-листа")
        else:
            await update.message.reply_text("❌ Ошибка удаления")
    except IndexError:
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