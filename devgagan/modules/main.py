import time
import random
import string
import asyncio
import logging
from pyrogram import filters, Client
from devgagan import app, userrbot
from config import API_ID, API_HASH, BATCH_LIMIT, OWNER_ID, DEFAULT_SESSION
from devgagan.core.get_func import get_msg, telegram_bot
from devgagan.core.func import *
from devgagan.core.adaptive_throttle import AdaptiveThrottle
from devgagan.core.mongo import db
from pyrogram.errors import FloodWait
from datetime import datetime, timedelta
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

async def generate_random_name(length=8):
    return ''.join(random.choices(string.ascii_lowercase, k=length))

users_loop = {}  # True = running, False = graceful cancel requested
force_stop = {}  # True = force stop requested
throttle = AdaptiveThrottle()  # Adaptive inter-file delay
failed_links = {} # {user_id: [link1, link2, ...]}

async def process_and_upload_link(userbot, user_id, msg_id, link, retry_count, message):
    try:
        res = await get_msg(userbot, user_id, msg_id, link, retry_count, message)
        if res is False:
            return False
        return True
    except Exception as e:
        logger.error(f"Process link error: {e}")
        return False
    finally:
        try:
            await app.delete_messages(user_id, msg_id)
        except Exception:
            pass


@app.on_message(
    filters.regex(r'https?://(?:www\.)?t\.me/[^\s]+|tg://openmessage\?user_id=\w+&message_id=\d+')
    & filters.private
)
async def single_link(_, message):
    user_id = message.chat.id

    # Check if user is already in a loop
    if users_loop.get(user_id, False):
        await message.reply(
            "You already have an ongoing process. Please wait for it to finish or cancel it with /cancel."
        )
        return

    # Add user to the loop
    users_loop[user_id] = True

    link = message.text if "tg://openmessage" in message.text else get_link(message.text)
    msg = await message.reply("Processing...")
    userbot = await initialize_userbot(user_id)
    try:
        if await is_normal_tg_link(link):
            await process_and_upload_link(userbot, user_id, msg.id, link, 0, message)
        else:
            await process_special_links(userbot, user_id, msg, link)
            
    except FloodWait as fw:
        await msg.edit_text(f'FloodWait: Waiting {fw.x} seconds...')
        await asyncio.sleep(fw.x)
    except Exception as e:
        await msg.edit_text(f"Link: `{link}`\n\n**Error:** {str(e)}")
    finally:
        users_loop[user_id] = False
        try:
            await msg.delete()
        except Exception:
            pass


async def initialize_userbot(user_id):
    data = await db.get_data(user_id)
    if data and data.get("session"):
        try:
            device = 'iPhone 16 Pro'
            userbot = Client(
                "userbot",
                api_id=API_ID,
                api_hash=API_HASH,
                device_model=device,
                session_string=data.get("session")
            )
            await userbot.start()
            return userbot
        except Exception as e:
            logger.error(f"Userbot init error: {e}")
            await app.send_message(user_id, "Login Expired. Please re-login.")
            return None
    else:
        if DEFAULT_SESSION:
            return userrbot
        else:
            return None


async def is_normal_tg_link(link: str) -> bool:
    """Check if the link is a standard Telegram link."""
    special_identifiers = ['t.me/+', 't.me/c/', 't.me/b/', 'tg://openmessage']
    return 't.me/' in link and not any(x in link for x in special_identifiers)
    
async def process_special_links(userbot, user_id, msg, link):
    if userbot is None:
        return await msg.edit_text("Try logging in to the bot and try again.")
    if 't.me/+' in link:
        result = await userbot_join(userbot, link)
        await msg.edit_text(result)
        return
    special_patterns = ['t.me/c/', 't.me/b/', '/s/', 'tg://openmessage']
    if any(sub in link for sub in special_patterns):
        await process_and_upload_link(userbot, user_id, msg.id, link, 0, msg)
        return
    await msg.edit_text("Invalid link...")


@app.on_message(filters.command("batch") & filters.private)
async def batch_link(_, message):
    user_id = message.chat.id
    
    # Check if a batch process is already running
    if users_loop.get(user_id, False):
        await app.send_message(
            message.chat.id,
            "You already have a process running. Please wait for it to complete or /cancel it."
        )
        return

    max_batch_size = BATCH_LIMIT

    # Start link input
    try:
        start_link_msg = await app.ask(message.chat.id, "Please send the **Start Message Link**.\n\n> Maximum tries 3", timeout=60)
        start_link = start_link_msg.text.strip()
    except asyncio.TimeoutError:
        await message.reply("⏰ Timed out. Please try again.")
        return

    # Determine connection type and chat info
    chat_id = None
    start_msg_id = None
    topic_id = None
    is_private = False

    if "t.me/c/" in start_link:
        is_private = True
        parts = start_link.split("/")
        try:
            chat_id_str = parts[parts.index('c') + 1]
            chat_id = int(f"-100{chat_id_str}")
            start_msg_id = int(parts[-1])
        except Exception as e:
            await message.reply(f"❌ Error parsing start link: {e}")
            return
    elif "t.me/b/" in start_link:
        is_private = True
        parts = start_link.split("/")
        try:
            start_msg_id = int(parts[-1])
        except Exception as e:
            await message.reply(f"❌ Error parsing start link: {e}")
            return
    else:
        # Normal public link
        parts = start_link.split("/")
        try:
            start_msg_id = int(parts[-1])
        except Exception as e:
            await message.reply(f"❌ Error parsing start link: {e}")
            return

    userbot = await initialize_userbot(user_id)
    if is_private and not userbot:
        await message.reply("❌ Userbot not initialized for private channel. Please /login first.")
        return

    if is_private and chat_id:
        try:
            start_message_obj = await userbot.get_messages(chat_id, start_msg_id)
            if start_message_obj and getattr(start_message_obj, 'message_thread_id', None):
                topic_id = start_message_obj.message_thread_id
        except Exception:
            pass

    # End link input
    try:
        end_link_msg = await app.ask(message.chat.id, "Please send the **End Message Link**, or type 'no' to download up to the latest message.", timeout=60)
        end_text = end_link_msg.text.strip()
        end_msg_id = None

        if end_text.lower() == 'no':
            if is_private and chat_id and userbot:
                last_message_list = [msg async for msg in userbot.get_chat_history(chat_id, limit=1)]
                end_msg_id = last_message_list[0].id if last_message_list else start_msg_id
            elif not is_private:
                try:
                    t_me_index = parts.index('t.me')
                    username = parts[t_me_index + 1]
                    last_message_list = [msg async for msg in app.get_chat_history(username, limit=1)]
                    end_msg_id = last_message_list[0].id if last_message_list else start_msg_id
                except Exception:
                    await message.reply("Could not fetch the last message. Please provide an exact end link.")
                    return
            else:
                await message.reply("'no' is not supported for this link type. Please provide an exact end link.")
                return
        else:
            end_link = end_text
            end_parts = end_link.split("/")
            try:
                end_msg_id = int(end_parts[-1])
            except Exception as e:
                await message.reply(f"❌ Error parsing end link: {e}")
                return
    except asyncio.TimeoutError:
        await message.reply("⏰ Timed out. Please try again.")
        return

    if end_msg_id is None or end_msg_id < start_msg_id:
        await message.reply("End message must be after start message.")
        return

    total_to_check = end_msg_id - start_msg_id + 1
    if total_to_check > max_batch_size:
        await message.reply(f"Range exceeds limit of {max_batch_size}. Please try a smaller range.")
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🛑 Cancel", callback_data="batch_cancel"),
        InlineKeyboardButton("⛔ Force Stop", callback_data="batch_stop")
    ]])
    
    users_loop[user_id] = True
    force_stop[user_id] = False
    processed_count = 0
    failed_links[user_id] = [] # Initialize failed links list for this batch

    # Save batch state to MongoDB for auto-resume
    batch_state = {
        "user_id": user_id,
        "start_link": start_link,
        "start_msg_id": start_msg_id,
        "end_msg_id": end_msg_id,
        "chat_id": chat_id,
        "topic_id": topic_id,
        "is_private": is_private,
        "last_processed_id": start_msg_id,
        "processed_count": 0,
        "status": "active"
    }
    await db.save_batch_state(user_id, batch_state)

    if topic_id:
        # Topic batch logic
        pin_msg = await app.send_message(user_id, f"Fetching topic messages ⚡\nTotal: {total_to_check}\n\n**Powered by Team SPY**", reply_markup=keyboard)
        valid_msg_ids = []
        try:
            chunk_size = 100
            for i in range(start_msg_id, end_msg_id + 1, chunk_size):
                if not users_loop.get(user_id) or force_stop.get(user_id):
                    break
                chunk_ids = list(range(i, min(i + chunk_size, end_msg_id + 1)))
                try:
                    msgs = await userbot.get_messages(chat_id, chunk_ids)
                    for msg in msgs:
                        if msg and getattr(msg, 'message_thread_id', None) == topic_id:
                            if msg.media or msg.text:
                                valid_msg_ids.append(msg.id)
                    
                    checked_so_far = min(i + chunk_size - 1, end_msg_id) - start_msg_id + 1
                    await pin_msg.edit(f"Fetching ⚡\nChecked: {checked_so_far}/{total_to_check}\nFound: {len(valid_msg_ids)}", reply_markup=keyboard)
                    await asyncio.sleep(2)
                except FloodWait as fw:
                    logger.warning(f"FloodWait during fetch: {fw.value}s")
                    await pin_msg.edit(f"⏳ FloodWait: {fw.value}s. Waiting...")
                    await asyncio.sleep(fw.value + 5)
                except Exception as e:
                    logger.error(f"Fetch error: {e}")
            
            if force_stop.get(user_id):
                await pin_msg.edit("⛔ Force stopped!")
                await db.clear_batch_state(user_id)
                telegram_bot.upload_queue.reset()
                return

            await db.set_topic_msg_ids(user_id, valid_msg_ids)
            await pin_msg.edit(f"✅ Found {len(valid_msg_ids)} messages. Processing...", reply_markup=keyboard)
            saved_msg_ids = await db.get_topic_msg_ids(user_id)
            
            for msg_id in saved_msg_ids:
                # Check for graceful cancel
                if not users_loop.get(user_id):
                    await pin_msg.edit(f"🛑 Gracefully cancelled after {processed_count} files.")
                    break
                
                # Check for force stop
                if force_stop.get(user_id):
                    await pin_msg.edit(f"⛔ Force stopped after {processed_count} files.")
                    break

                try:
                    current_msg = await userbot.get_messages(chat_id, msg_id)
                    if current_msg:
                        edit_msg = await app.send_message(user_id, f"Processing message {current_msg.id}...")
                        await telegram_bot._process_message(userbot, current_msg, user_id, edit_msg)
                        processed_count += 1
                        
                        # Update batch state in MongoDB
                        await db.update_batch_progress(user_id, msg_id, processed_count)
                        
                        await pin_msg.edit(f"⚡ Processing: {processed_count}/{len(saved_msg_ids)}", reply_markup=keyboard)
                        await asyncio.sleep(throttle.get_delay())
                except FloodWait as fw:
                    throttle.report_flood_wait(fw.value)
                    logger.warning(f"FloodWait during process: {fw.value}s")
                    await pin_msg.edit(f"⏳ FloodWait: {fw.value}s. Waiting...")
                    await asyncio.sleep(fw.value + 5)
                except Exception as e:
                    logger.error(f"Process error: {e}")
                    
            if users_loop.get(user_id) and not force_stop.get(user_id):
                await pin_msg.edit(f"✅ Batch completed! Processed {processed_count} messages. 🎉", reply_markup=keyboard)
            
            await db.clear_topic_msg_ids(user_id)
            await db.clear_batch_state(user_id)
        except Exception as e:
            logger.error(f"Topic batch error: {e}")
            await app.send_message(message.chat.id, f"Error: {e}")
        finally:
            telegram_bot.upload_queue.reset()
            users_loop.pop(user_id, None)
            force_stop.pop(user_id, None)

    else:
        # Normal batch logic
        pin_msg = await app.send_message(user_id, f"Batch started ⚡\nProcessing: 0/{total_to_check}", reply_markup=keyboard)
        await pin_msg.pin(both_sides=True)
        try:
            for i in range(start_msg_id, end_msg_id + 1):
                # Check for graceful cancel
                if user_id in users_loop and not users_loop[user_id]:
                    await pin_msg.edit_text(f"🛑 Gracefully cancelled after {processed_count} files.")
                    break
                
                # Check for force stop  
                if force_stop.get(user_id):
                    await pin_msg.edit_text(f"⛔ Force stopped after {processed_count} files.")
                    break

                if user_id in users_loop and users_loop[user_id]:
                    try:
                        url = f"{'/'.join(start_link.split('/')[:-1])}/{i}"
                        link = get_link(url)
                        if link:
                            msg = await app.send_message(message.chat.id, f"Processing...")
                            if await process_and_upload_link(userbot, user_id, msg.id, link, 0, message):
                                processed_count += 1
                                
                                # Update batch state in MongoDB
                                await db.update_batch_progress(user_id, i, processed_count)
                                
                                await pin_msg.edit_text(
                                    f"⚡ Processing: {processed_count}/{total_to_check}",
                                    reply_markup=keyboard
                                )
                                await asyncio.sleep(throttle.get_delay())
                            else:
                                failed_links[user_id].append(url)
                        else:
                            failed_links[user_id].append(url)
                    except FloodWait as fw:
                        throttle.report_flood_wait(fw.value)
                        logger.warning(f"FloodWait: {fw.value}s")
                        await pin_msg.edit_text(f"⏳ FloodWait: {fw.value}s. Waiting...")
                        await asyncio.sleep(fw.value + 5)
                    except Exception as e:
                        logger.error(f"Batch item error: {e}")
                        failed_links[user_id].append(url)
                else:
                    break

            if users_loop.get(user_id) and not force_stop.get(user_id):
                await pin_msg.edit_text(f"✅ Batch completed! {processed_count} messages 🎉", reply_markup=keyboard)
                await app.send_message(message.chat.id, "Batch completed successfully! 🎉")
            
            # Send failed links report if any
            if failed_links.get(user_id):
                report_file = f"failed_batch_{user_id}.txt"
                with open(report_file, "w") as f:
                    f.write("\n".join(failed_links[user_id]))
                await app.send_document(
                    message.chat.id, 
                    report_file, 
                    caption=f"❌ **Batch finished with {len(failed_links[user_id])} errors.**\n\nUse `/batch_txt` and upload this file to retry only these links."
                )
                if os.path.exists(report_file):
                    os.remove(report_file)

            await db.clear_batch_state(user_id)
        except Exception as e:
            logger.error(f"Batch error: {e}")
            await app.send_message(message.chat.id, f"Error: {e}")
        finally:
            telegram_bot.upload_queue.reset()
            users_loop.pop(user_id, None)
            force_stop.pop(user_id, None)


@app.on_message(filters.command("cancel"))
async def graceful_cancel(_, message):
    """Graceful cancel: finish current file, then stop."""
    user_id = message.chat.id

    if user_id in users_loop and users_loop[user_id]:
        users_loop[user_id] = False  # Signal graceful stop
        await app.send_message(
            message.chat.id, 
            "🛑 **Graceful Cancel**: Current file will finish processing, then batch will stop."
        )
    else:
        await app.send_message(
            message.chat.id, 
            "No active batch to cancel."
        )


@app.on_message(filters.command("stop"))
async def force_stop_cmd(_, message):
    """Force stop: immediately terminate everything."""
    user_id = message.chat.id

    if user_id in users_loop and users_loop[user_id]:
        users_loop[user_id] = False
        force_stop[user_id] = True
        await app.send_message(
            message.chat.id,
            "⛔ **Force Stop**: Terminating immediately. Cleaning up..."
        )
        # Clear batch state
        await db.clear_batch_state(user_id)
        telegram_bot.upload_queue.reset()
    else:
        await app.send_message(
            message.chat.id,
            "No active batch to stop."
        )


@app.on_callback_query(filters.regex("batch_cancel"))
async def batch_cancel_callback(_, callback_query):
    user_id = callback_query.from_user.id
    if user_id in users_loop and users_loop[user_id]:
        users_loop[user_id] = False
        await callback_query.answer("🛑 Graceful cancel requested!", show_alert=True)
    else:
        await callback_query.answer("No active batch.", show_alert=True)


@app.on_message(filters.command("batch_txt") & filters.private)
async def batch_txt_handler(client, message):
    user_id = message.chat.id
    
    if users_loop.get(user_id, False):
        await message.reply("You already have an ongoing process.")
        return

    try:
        txt_msg = await app.ask(user_id, "Please upload the `.txt` file containing Telegram links (one per line).", timeout=60)
        if not txt_msg.document or not txt_msg.document.file_name.endswith(".txt"):
            await message.reply("❌ Invalid file. Please upload a `.txt` file.")
            return
        
        file_path = await txt_msg.download()
        with open(file_path, "r") as f:
            links = [line.strip() for line in f.readlines() if line.strip()]
        
        if os.path.exists(file_path):
            os.remove(file_path)

        if not links:
            await message.reply("❌ The file is empty.")
            return

        if len(links) > 2000:
            await message.reply("❌ Limit exceeded. Max 2000 links per TXT.")
            return

        # Start Batch from TXT
        users_loop[user_id] = True
        failed_links[user_id] = []
        processed_count = 0
        total = len(links)
        
        userbot = await initialize_userbot(user_id)
        pin_msg = await message.reply(f"📦 **TXT Batch Started**\nTotal: {total}\n\n**Powered by Team SPY**")
        
        for link in links:
            if not users_loop.get(user_id):
                break
            
            # Extract ID from link for process_and_upload_link
            try:
                parts = link.split("/")
                msg_id = int(parts[-1])
                
                msg_placeholder = await app.send_message(user_id, "Processing...")
                if await process_and_upload_link(userbot, user_id, msg_placeholder.id, link, 0, message):
                    processed_count += 1
                else:
                    failed_links[user_id].append(link)
            except Exception:
                failed_links[user_id].append(link)

            await pin_msg.edit(f"📦 **TXT Batch: {processed_count}/{total}**")
            await asyncio.sleep(throttle.get_delay())

        await message.reply(f"✅ TXT Batch completed! {processed_count} success, {len(failed_links[user_id])} failed.")
        
        if failed_links.get(user_id):
            report_file = f"retry_failed_{user_id}.txt"
            with open(report_file, "w") as f:
                f.write("\n".join(failed_links[user_id]))
            await app.send_document(user_id, report_file, caption="Re-failed links log.")
            if os.path.exists(report_file):
                os.remove(report_file)

    except asyncio.TimeoutError:
        await message.reply("⏰ Timed out.")
    except Exception as e:
        logger.error(f"TXT Batch error: {e}")
        await message.reply(f"Error: {e}")
    finally:
        users_loop.pop(user_id, None)

@app.on_callback_query(filters.regex("batch_stop"))
async def batch_stop_callback(_, callback_query):
    user_id = callback_query.from_user.id
    if user_id in users_loop and users_loop[user_id]:
        users_loop[user_id] = False
        force_stop[user_id] = True
        await db.clear_batch_state(user_id)
        telegram_bot.upload_queue.reset()
        await callback_query.answer("⛔ Force stop! Terminating...", show_alert=True)
    else:
        await callback_query.answer("No active batch.", show_alert=True)


async def auto_resume_batch():
    """
    Called on bot startup. Checks MongoDB for interrupted batches and resumes them.
    This handles recovery after FloodWait crashes, Heroku restarts, etc.
    """
    await asyncio.sleep(5)  # Wait for bot to fully initialize
    
    try:
        # Find any active batch in the database
        batch_state = await db.get_active_batch()
        if not batch_state:
            logger.info("✅ No interrupted batches found.")
            return
        
        user_id = batch_state.get("user_id")
        if not user_id:
            return
        
        # Check if user already has a running loop
        if users_loop.get(user_id):
            return
        
        start_link = batch_state.get("start_link", "")
        start_msg_id = batch_state.get("start_msg_id", 0)
        end_msg_id = batch_state.get("end_msg_id", 0)
        last_processed_id = batch_state.get("last_processed_id", start_msg_id)
        processed_count = batch_state.get("processed_count", 0)
        chat_id = batch_state.get("chat_id")
        topic_id = batch_state.get("topic_id")
        is_private = batch_state.get("is_private", False)
        
        # Calculate remaining
        resume_from = last_processed_id + 1
        remaining = end_msg_id - resume_from + 1
        
        if remaining <= 0:
            logger.info(f"Batch for user {user_id} was already complete. Clearing state.")
            await db.clear_batch_state(user_id)
            return
        
        logger.info(f"🔄 Auto-resuming batch for user {user_id}: {remaining} messages remaining (from {resume_from} to {end_msg_id})")
        
        # Notify user
        try:
            await app.send_message(
                user_id,
                f"🔄 **Auto-Resume Detected!**\n\n"
                f"Found interrupted batch:\n"
                f"• Already processed: **{processed_count}** files\n"
                f"• Remaining: **{remaining}** messages\n"
                f"• Resuming from message `{resume_from}`\n\n"
                f"⚡ Resuming automatically..."
            )
        except Exception:
            pass
        
        # Initialize userbot
        userbot = await initialize_userbot(user_id)
        if not userbot:
            await app.send_message(user_id, "❌ Auto-resume failed: Could not initialize userbot. Please /login and try /resume manually.")
            return
        
        # Set up loop state
        users_loop[user_id] = True
        force_stop[user_id] = False
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🛑 Cancel", callback_data="batch_cancel"),
            InlineKeyboardButton("⛔ Force Stop", callback_data="batch_stop")
        ]])
        
        if topic_id:
            # Topic batch resume - use saved message IDs
            saved_msg_ids = await db.get_topic_msg_ids(user_id)
            if not saved_msg_ids:
                await app.send_message(user_id, "❌ Could not find saved topic message IDs. Please restart batch manually.")
                await db.clear_batch_state(user_id)
                users_loop.pop(user_id, None)
                return
            
            # Filter to only unprocessed IDs
            unprocessed_ids = [mid for mid in saved_msg_ids if mid > last_processed_id]
            
            pin_msg = await app.send_message(
                user_id,
                f"🔄 Resuming topic batch: {len(unprocessed_ids)} remaining",
                reply_markup=keyboard
            )
            
            try:
                for msg_id in unprocessed_ids:
                    if not users_loop.get(user_id) or force_stop.get(user_id):
                        break
                    
                    try:
                        current_msg = await userbot.get_messages(chat_id, msg_id)
                        if current_msg:
                            edit_msg = await app.send_message(user_id, f"Processing message {msg_id}...")
                            await telegram_bot._process_message(userbot, current_msg, user_id, edit_msg)
                            processed_count += 1
                            await db.update_batch_progress(user_id, msg_id, processed_count)
                            await pin_msg.edit(f"⚡ Resumed: {processed_count} processed", reply_markup=keyboard)
                            await asyncio.sleep(throttle.get_delay())
                    except FloodWait as fw:
                        throttle.report_flood_wait(fw.value)
                        logger.warning(f"FloodWait during resume: {fw.value}s")
                        await pin_msg.edit(f"⏳ FloodWait: {fw.value}s. Waiting...")
                        await asyncio.sleep(fw.value + 5)
                    except Exception as e:
                        logger.error(f"Resume process error: {e}")
                
                if users_loop.get(user_id) and not force_stop.get(user_id):
                    await pin_msg.edit(f"✅ Batch resumed and completed! {processed_count} total 🎉")
                
                await db.clear_topic_msg_ids(user_id)
                await db.clear_batch_state(user_id)
            except Exception as e:
                logger.error(f"Topic resume error: {e}")
            finally:
                telegram_bot.upload_queue.reset()
                users_loop.pop(user_id, None)
                force_stop.pop(user_id, None)
        
        else:
            # Normal batch resume
            pin_msg = await app.send_message(
                user_id,
                f"🔄 Resuming batch: {remaining} remaining",
                reply_markup=keyboard
            )
            await pin_msg.pin(both_sides=True)
            
            try:
                for i in range(resume_from, end_msg_id + 1):
                    if not users_loop.get(user_id) or force_stop.get(user_id):
                        break
                    
                    try:
                        url = f"{'/'.join(start_link.split('/')[:-1])}/{i}"
                        link = get_link(url)
                        if link:
                            msg = await app.send_message(user_id, "Processing...")
                            if await process_and_upload_link(userbot, user_id, msg.id, link, 0, None):
                                processed_count += 1
                                await db.update_batch_progress(user_id, i, processed_count)
                                await pin_msg.edit_text(
                                    f"⚡ Resumed: {processed_count} processed",
                                    reply_markup=keyboard
                                )
                                await asyncio.sleep(throttle.get_delay())
                    except FloodWait as fw:
                        throttle.report_flood_wait(fw.value)
                        logger.warning(f"FloodWait during resume: {fw.value}s")
                        await pin_msg.edit_text(f"⏳ FloodWait: {fw.value}s. Waiting...")
                        await asyncio.sleep(fw.value + 5)
                    except Exception as e:
                        logger.error(f"Resume item error: {e}")
                
                if users_loop.get(user_id) and not force_stop.get(user_id):
                    await pin_msg.edit_text(f"✅ Batch resumed and completed! {processed_count} total 🎉")
                    await app.send_message(user_id, "Batch completed successfully! 🎉")
                
                await db.clear_batch_state(user_id)
            except Exception as e:
                logger.error(f"Normal resume error: {e}")
            finally:
                telegram_bot.upload_queue.reset()
                users_loop.pop(user_id, None)
                force_stop.pop(user_id, None)
    
    except Exception as e:
        logger.error(f"Auto-resume failed: {e}")


@app.on_message(filters.command("resume") & filters.private)
async def manual_resume(_, message):
    """Manual trigger for batch resume."""
    user_id = message.chat.id
    
    if users_loop.get(user_id):
        await message.reply("You already have an active batch running.")
        return
    
    batch_state = await db.get_active_batch(user_id)
    if not batch_state:
        await message.reply("No interrupted batch found to resume.")
        return
    
    await message.reply("🔄 Starting manual resume...")
    asyncio.create_task(auto_resume_batch())
