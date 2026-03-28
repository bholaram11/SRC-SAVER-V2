import logging
from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from devgagan import app

logger = logging.getLogger(__name__)

# Simplified /start handler - no ads, no tokens
@app.on_message(filters.command("start"))
async def start_handler(client, message):
    """Simple start command for personal use."""
    user_id = message.chat.id
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Settings", callback_data="open_settings")],
        [InlineKeyboardButton("❓ Help", callback_data="open_help")]
    ])
    
    await message.reply(
        "👋 **Welcome!**\n\n"
        "I can save posts from channels/groups (even restricted ones) "
        "and download videos/audio from 30+ platforms.\n\n"
        "**Quick Start:**\n"
        "• Send a Telegram post link to save it\n"
        "• Use /batch for bulk extraction\n"
        "• Use /login for private channels\n"
        "• Use /settings to customize\n\n"
        "**__Powered by Team SPY__**",
        reply_markup=keyboard
    )

# Token verification is no longer needed for personal use
async def is_user_verified(user_id):
    """Always returns True - no token needed for personal use."""
    return True