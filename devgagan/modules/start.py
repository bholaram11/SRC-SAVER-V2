import logging
from pyrogram import filters
from devgagan import app
from config import OWNER_ID
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand

logger = logging.getLogger(__name__)

@app.on_message(filters.command("set"))
async def set_commands(_, message):
    if message.from_user.id not in OWNER_ID:
        await message.reply("You are not authorized to use this command.")
        return
     
    await app.set_bot_commands([
        BotCommand("start", "🚀 Start the bot"),
        BotCommand("batch", "📦 Extract in bulk"),
        BotCommand("login", "🔑 Login for private channels"),
        BotCommand("logout", "🚪 Logout from session"),
        BotCommand("dl", "🎬 Download videos from 30+ sites"),
        BotCommand("adl", "🎵 Download audio from 30+ sites"),
        BotCommand("settings", "⚙️ Personalize settings"),
        BotCommand("stats", "📊 Bot statistics"),
        BotCommand("speedtest", "🚅 Server speed test"),
        BotCommand("lock", "🔒 Protect channel from extraction"),
        BotCommand("cancel", "🛑 Graceful cancel (finish current file)"),
        BotCommand("stop", "⛔ Force stop (immediate)"),
        BotCommand("resume", "🔄 Resume interrupted batch"),
        BotCommand("help", "❓ How to use"),
        BotCommand("session", "🧵 Generate Pyrogram V2 session"),
        BotCommand("restart", "🔄 Restart bot (owner only)")
    ])
 
    await message.reply("✅ Commands configured successfully!")


help_pages = [
    (
        "📝 **Bot Commands (1/2)**:\n\n"
        "1. **/batch** - Bulk extraction of posts\n"
        "2. **/login** - Login for private channel access\n"
        "3. **/logout** - Logout from session\n"
        "4. **/dl link** - Download videos\n"
        "5. **/adl link** - Download audio\n"
        "6. **/settings** - Configure bot settings\n"
        "7. **/lock** - Lock channel from extraction\n"
        "8. **/cancel** - Graceful stop (finish current file)\n"
        "9. **/stop** - Force stop (immediate)\n"
    ),
    (
        "📝 **Bot Commands (2/2)**:\n\n"
        "10. **/stats** - Bot statistics\n"
        "11. **/speedtest** - Server speed test\n"
        "12. **/session** - Generate Pyrogram V2 session\n"
        "13. **/restart** - Restart bot (owner only)\n\n"
        "**Settings options:**\n"
        "> SETCHATID: Upload to channel/group\n"
        "> SETRENAME: Custom rename tag\n"
        "> CAPTION: Custom caption\n"
        "> REPLACEWORDS: Word replacement\n"
        "> RESET: Reset to defaults\n\n"
        "**__Powered by Team SPY__**"
    )
]
 
 
async def send_or_edit_help_page(_, message, page_number):
    if page_number < 0 or page_number >= len(help_pages):
        return
 
    prev_button = InlineKeyboardButton("◀️ Previous", callback_data=f"help_prev_{page_number}")
    next_button = InlineKeyboardButton("Next ▶️", callback_data=f"help_next_{page_number}")
 
    buttons = []
    if page_number > 0:
        buttons.append(prev_button)
    if page_number < len(help_pages) - 1:
        buttons.append(next_button)
 
    keyboard = InlineKeyboardMarkup([buttons])
    await message.delete()
    await message.reply(help_pages[page_number], reply_markup=keyboard)
 
 
@app.on_message(filters.command("help"))
async def help_cmd(client, message):
    await send_or_edit_help_page(client, message, 0)
 
 
@app.on_callback_query(filters.regex(r"help_(prev|next)_(\d+)"))
async def on_help_navigation(client, callback_query):
    action, page_number = callback_query.data.split("_")[1], int(callback_query.data.split("_")[2])
    if action == "prev":
        page_number -= 1
    elif action == "next":
        page_number += 1
    await send_or_edit_help_page(client, callback_query.message, page_number)
    await callback_query.answer()
