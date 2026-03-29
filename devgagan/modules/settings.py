import logging
import re
import os
import psutil
from pyrogram import filters, Client
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from devgagan import app
from devgagan.core.mongo import db
from devgagan.core.get_func import telegram_bot
from config import OWNER_ID

logger = logging.getLogger(__name__)

# --- COMMAND HANDLERS ---

@app.on_message(filters.command("status") & filters.private)
async def status_command(client, message):
    """Live dashboard for bot internals."""
    from devgagan.modules.main import throttle
    # Queue stats
    q_stats = telegram_bot.upload_queue.get_status()
    t_stats = throttle.get_stats()
    
    # System stats
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent
    
    # Downloads folder size
    dl_path = 'downloads/'
    dl_size = 0
    if os.path.exists(dl_path):
        for f in os.listdir(dl_path):
            fp = os.path.join(dl_path, f)
            if os.path.isfile(fp):
                dl_size += os.path.getsize(fp)
    
    dl_size_mb = round(dl_size / (1024**2), 1)
    
    status_text = (
        "📊 **Bot Status Dashboard**\n\n"
        "**📁 Pipeline (Upload Queue):**\n"
        f"• Pending Files: `{q_stats['pending_count']}`\n"
        f"• Pending Size: `{q_stats['pending_size_mb']} MB`\n"
        f"• Downloads: `{'⏸️ Paused' if q_stats['downloads_paused'] else '▶️ Running'}`\n"
        f"• Total Processed: `{q_stats['total_processed']}`\n"
        f"• Total Uploaded: `{q_stats['total_uploaded_gb']} GB`\n\n"
        
        "**⏱️ Adaptive Throttle:**\n"
        f"• Current Delay: `{t_stats['current_delay']}s`\n"
        f"• Base Delay: `{t_stats['base_delay']}s`\n"
        f"• Success Streak: `{t_stats['success_streak']}`\n"
        f"• Total Floods: `{t_stats['flood_count']}`\n\n"
        
        "**🖥️ System Resources:**\n"
        f"• CPU Usage: `{cpu}%`\n"
        f"• RAM Usage: `{ram}%`\n"
        f"• Disk Usage: `{disk}%`\n"
        f"• Temp Files: `{dl_size_mb} MB`\n\n"
        
        "**__Powered by Team SPY__**"
    )
    
    await message.reply(status_text)

@app.on_message(filters.command("settings") & filters.private)
async def settings_handler(client, message):
    await show_settings_menu(message.chat.id, message)

# --- CALLBACK HANDLERS ---

@app.on_callback_query(filters.regex("open_settings"))
async def cb_open_settings(client, callback_query: CallbackQuery):
    await show_settings_menu(callback_query.message.chat.id, callback_query.message, edit=True)

@app.on_callback_query(filters.regex("open_help"))
async def cb_open_help(client, callback_query: CallbackQuery):
    from devgagan.modules.start import show_help_page
    await show_help_page(callback_query.message, edit=True)

@app.on_callback_query(filters.regex("open_status"))
async def cb_open_status(client, callback_query: CallbackQuery):
    await status_command(client, callback_query.message)
    await callback_query.answer()

@app.on_callback_query(filters.regex("open_start"))
async def cb_open_start(client, callback_query: CallbackQuery):
    from devgagan.modules.start import start_handler
    await start_handler(client, callback_query.message)
    await callback_query.answer()


# State tracking for settings conversations
user_states = {} # {user_id: "awaiting_target"}

async def show_settings_menu(user_id, message, edit=False):
    # Fetch current settings from DB
    data = await db.get_data(user_id) or {}
    
    target_chat = data.get("chat_id", "Not Set")
    rename_tag = data.get("rename_tag", "Not Set")
    custom_caption = data.get("caption", "Not Set")
    
    # regex_patterns is a list of [pat, repl]
    regex_count = len(data.get("regex_patterns", []))
    
    menu_text = (
        "⚙️ **Personalize Your Settings**\n\n"
        "Configure how you want the bot to extract and upload content.\n\n"
        f"📡 **Target Chat:** `{target_chat}`\n"
        f"🏷️ **Rename Tag:** `{rename_tag}`\n"
        f"📝 **Custom Caption:** `{custom_caption}`\n"
        f"🔍 **Regex Filters:** `{regex_count} active`\n"
    )
    
    thumb_exists = os.path.exists(f"{user_id}.jpg")
    menu_text += f"🖼️ **Custom Thumbnail:** `{'✅ Set' if thumb_exists else '❌ Not Set'}`\n"

    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Set Target Chat", callback_data="set_target"),
         InlineKeyboardButton("🏷️ Set Rename Tag", callback_data="set_rename")],
        [InlineKeyboardButton("📝 Set Caption", callback_data="set_caption"),
         InlineKeyboardButton("🔍 Set Regex", callback_data="set_regex")],
        [InlineKeyboardButton("🖼️ Set Thumb", callback_data="set_thumb"),
         InlineKeyboardButton("🗑️ Remove Thumb", callback_data="rem_thumb")],
        [InlineKeyboardButton("🗑️ Reset All", callback_data="reset_settings")],
        [InlineKeyboardButton("🔙 Back to Start", callback_data="open_start")]
    ])
    
    if edit:
        try:
            await message.edit(menu_text, reply_markup=keyboard)
        except Exception:
            await message.reply(menu_text, reply_markup=keyboard)
    else:
        await message.reply(menu_text, reply_markup=keyboard)

# --- SETTERS CALLBACKS ---

@app.on_callback_query(filters.regex(r"set_(target|rename|caption|regex)"))
async def cb_set_pref(client, callback_query: CallbackQuery):
    user_id = callback_query.message.chat.id
    pref = callback_query.data.split("_")[1]
    
    instr = {
        "target": "📡 **Set Target Chat**\n\nSend the Target Chat ID (starting with -100).\nExample: `-100123456789` or `ChatID/TopicID`.",
        "rename": "🏷️ **Set Rename Tag**\n\nSend the text you want to append/prepend to filenames.",
        "caption": "📝 **Set Custom Caption**\n\nSend your caption template. Use `{filename}` as a placeholder for the original name.",
        "regex": "🔍 **Set Regex Filters (Pro Cleaning)**\n\n"
                 "Use this to clean links, usernames, or specific patterns from captions.\n\n"
                 "**Format:** `pattern|replacement` (One per line)\n"
                 "• Use `|` as a separator.\n"
                 "• If you leave the replacement empty, the pattern will be **DELETED**.\n\n"
                 "**Examples:**\n"
                 "1️⃣ `https?://\\S+|` (Removes all web links)\n"
                 "2️⃣ `@\\S+|` (Removes all @usernames)\n"
                 "3️⃣ `Batch \\d+|Season` (Replaces 'Batch 1' with 'Season')\n"
                 "4️⃣ `(?i)Join Us|` (Removes 'Join Us' case-insensitively)",
        "thumb": "🖼️ **Set Custom Thumbnail**\n\nPlease upload a **Photo** to set it as your persistent thumbnail."
    }


    
    user_states[user_id] = f"awaiting_{pref}"
    
    await callback_query.message.edit(
        f"{instr[pref]}\n\n✨ _Type /cancel to abort._",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="open_settings")]])
    )

@app.on_callback_query(filters.regex("rem_thumb"))
async def cb_rem_thumb(client, callback_query: CallbackQuery):
    user_id = callback_query.message.chat.id
    thumb_path = f"{user_id}.jpg"
    if os.path.exists(thumb_path):
        os.remove(thumb_path)
        await callback_query.answer("✅ Thumbnail removed successfully!", show_alert=True)
    else:
        await callback_query.answer("❌ No thumbnail found to remove.", show_alert=True)
    await show_settings_menu(user_id, callback_query.message, edit=True)


@app.on_callback_query(filters.regex("reset_settings"))
async def cb_reset_settings(client, callback_query: CallbackQuery):
    user_id = callback_query.message.chat.id
    await db.remove_channel(user_id)
    await db.remove_caption(user_id)
    # Clear regex and rename tag manually as db.py might not have specific methods for all
    await db.db.update_one({"_id": user_id}, {"$unset": {"regex_patterns": "", "rename_tag": ""}})
    
    await callback_query.answer("✅ Settings reset to defaults!", show_alert=True)
    await show_settings_menu(user_id, callback_query.message, edit=True)

# --- MESSAGE HANDLER FOR SETTINGS INPUT ---

@app.on_message(filters.private & ~filters.command(["start", "batch", "login", "cancel", "status", "settings", "stop", "resume", "help"]))
async def handle_settings_input(client, message):
    user_id = message.chat.id
    state = user_states.get(user_id)
    
    if not state:
        return # Not in a settings conversation

    try:
        if state == "awaiting_target":
            target = message.text.strip()
            # Basic validation
            if "/" in target:
                chat, topic = target.split("/")
                await db.set_channel(user_id, target)
            else:
                await db.set_channel(user_id, int(target))
            await message.reply(f"✅ Target chat updated to: `{target}`")
            
        elif state == "awaiting_rename":
            await db.db.update_one({"_id": user_id}, {"$set": {"rename_tag": message.text.strip()}})
            await message.reply(f"✅ Rename tag updated to: `{message.text}`")
            
        elif state == "awaiting_caption":
            await db.set_caption(user_id, message.text.strip())
            await message.reply("✅ Custom caption updated!")
            
        elif state == "awaiting_regex":
            # Format: 'pattern|replacement' or just 'pattern' to delete
            lines = message.text.strip().split("\n")
            patterns = []
            for line in lines:
                if "|" in line:
                    pat, repl = line.split("|", 1)
                    patterns.append([pat.strip(), repl.strip()])
                else:
                    # If no | separator, assume user wants to delete the pattern
                    patterns.append([line.strip(), ""])
            
            await db.db.update_one({"_id": user_id}, {"$set": {"regex_patterns": patterns}})
            await message.reply(f"✅ Successfully updated {len(patterns)} Regex filters!\n\n"
                              "Bot will now apply these patterns to all future captions/filenames.")

        
        elif state == "awaiting_thumb":
            if message.photo:
                # Use Pyrogram's download method
                await message.download(file_name=f"{user_id}.jpg")
                await message.reply("✅ Custom thumbnail saved successfully!")
            else:
                await message.reply("❌ Please send a **Photo** to set it as a thumbnail.")
                return # Don't clear state if wrong format sent


    except Exception as e:
        await message.reply(f"❌ **Error:** `{str(e)}`\nPlease ensure you sent the correct format.")
    
    # Cleanup state and return to menu
    user_states.pop(user_id, None)
    await show_settings_menu(user_id, message)

