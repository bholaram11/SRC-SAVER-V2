import logging
from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from devgagan import app
from config import OWNER_ID

logger = logging.getLogger(__name__)

# --- START COMMAND ---
@app.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    """Modern start command for personal use."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Settings", callback_data="open_settings")],
        [InlineKeyboardButton("📊 Status", callback_data="open_status")],
        [InlineKeyboardButton("❓ Help", callback_data="open_help")]
    ])
    
    await message.reply(
        "👋 **Welcome to SRC-V2 Elite!**\n\n"
        "Your high-performance personal content engine is ready.\n\n"
        "**Quick Start:**\n"
        "• Send a Telegram post link to save it\n"
        "• Use /batch for bulk range extraction\n"
        "• Use /batch_txt for recovery from logs\n"
        "• Use /login for private channels\n\n"
        "**__Powered by Team SPY__**",
        reply_markup=keyboard
    )

# --- HELP COMMAND ---
@app.on_message(filters.command("help") & filters.private)
async def help_handler(client, message):
    await show_help_page(message)

# --- SET COMMANDS ---
@app.on_message(filters.command("set") & filters.private)
async def set_commands(client, message):
    if message.from_user.id not in OWNER_ID:
        return
     
    await client.set_bot_commands([
        BotCommand("start", "🚀 Start the bot"),
        BotCommand("batch", "📦 Bulk range extraction"),
        BotCommand("batch_txt", "📄 Batch from TXT file"),
        BotCommand("status", "📊 Live pipeline status"),
        BotCommand("settings", "⚙️ Configure preferences"),
        BotCommand("login", "🔑 Session login"),
        BotCommand("logout", "🚪 Session logout"),
        BotCommand("dl", "🎬 Download external video"),
        BotCommand("adl", "🎵 Download external audio"),
        BotCommand("cancel", "🛑 Graceful stop"),
        BotCommand("stop", "⛔ Force stop"),
        BotCommand("restart", "🔄 Restart bot")
    ])
    await message.reply("✅ **Elite Commands Configured!**")

# --- UTILS ---
async def show_help_page(message, edit=False):
    help_text = (
        "❓ **Elite Bot Guide**\n\n"
        "1️⃣ **Link Extraction**: Just send any `t.me` link.\n"
        "2️⃣ **Batch Mode**: Use `/batch` to extract a range of messages.\n"
        "3️⃣ **TXT Batch**: Use `/batch_txt` to recover failed links from logs.\n"
        "4️⃣ **Private Channels**: Use `/login` first to bridge the connection.\n"
        "5️⃣ **Settings**: Use `/settings` to set Tag, Caption, and Regex Filters.\n"
        "6️⃣ **Status**: Use `/status` to monitor the pipeline health.\n\n"
        "**Pro Features:**\n"
        "• **Adaptive Throttle**: Prevents FloodWaits automatically.\n"
        "• **Parallel Downloader**: Speeds up slow Telegram DCs.\n"
        "• **Auto-Resume**: Continues work after restarts.\n\n"
        "**__Powered by Team SPY__**"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="open_start")]])
    if edit:
        await message.edit(help_text, reply_markup=keyboard)
    else:
        await message.reply(help_text, reply_markup=keyboard)

# Always verified for personal use
async def is_user_verified(user_id):
    return True
