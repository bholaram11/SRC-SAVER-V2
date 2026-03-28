# ---------------------------------------------------
# File Name: get_func.py
# Description: A Pyrogram bot for downloading files from Telegram channels or groups 
#              and uploading them back to Telegram.
# Author: Gagan
# GitHub: https://github.com/devgaganin/
# Telegram: https://t.me/team_spy_pro
# YouTube: https://youtube.com/@dev_gagan
# Created: 2025-01-11
# Last Modified: 2025-01-11
# Version: 2.0.5
# License: MIT License
# ---------------------------------------------------

import asyncio
import os
import re
import time
import gc
from typing import Dict, Set, Optional, Union, Any, Tuple, List
from pathlib import Path
from functools import lru_cache, wraps
from collections import defaultdict
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
import aiofiles
from motor.motor_asyncio import AsyncIOMotorClient as MongoClient
import logging

logger = logging.getLogger(__name__)
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import ChannelBanned, ChannelInvalid, ChannelPrivate, ChatIdInvalid, ChatInvalid, RPCError
from pyrogram.enums import MessageMediaType, ParseMode
from telethon.tl.types import DocumentAttributeVideo
from telethon import events, Button
from devgagan import app, sex as gf
from devgagan.core.func import *
from devgagan.core.mongo import db as odb
from devgagantools import fast_upload
from config import MONGO_DB as MONGODB_CONNECTION_STRING, LOG_GROUP, OWNER_ID, STRING, API_ID, API_HASH, MAX_PARALLEL_UPLOADS, INTER_FILE_DELAY
from devgagan.core.upload_queue import UploadQueue

# Import pro userbot if STRING is available
if STRING:
    from devgagan import pro
else:
    pro = None

# Constants and Configuration
@dataclass
class BotConfig:
    DB_NAME: str = "smart_users"
    COLLECTION_NAME: str = "super_user"
    VIDEO_EXTS: Set[str] = field(default_factory=lambda: {
        'mp4', 'mov', 'avi', 'mkv', 'flv', 'wmv', 'webm', 'mpg', 'mpeg', 
        '3gp', 'ts', 'm4v', 'f4v', 'vob'
    })
    DOC_EXTS: Set[str] = field(default_factory=lambda: {
        'pdf', 'docx', 'txt', 'epub', 'docs'
    })
    IMG_EXTS: Set[str] = field(default_factory=lambda: {
        'jpg', 'jpeg', 'png', 'webp'
    })
    AUDIO_EXTS: Set[str] = field(default_factory=lambda: {
        'mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg'
    })
    SIZE_LIMIT: int = 2 * 1024**3  # 2GB
    PART_SIZE: int = int(1.9 * 1024**3)  # 1.9GB for splitting
    SETTINGS_PIC: str = "settings.jpg"

@dataclass
class UserProgress:
    previous_done: int = 0
    previous_time: float = field(default_factory=time.time)

class DatabaseManager:
    """Enhanced database operations with async motor and caching"""
    def __init__(self, connection_string: str, db_name: str, collection_name: str):
        self.client = MongoClient(connection_string)
        self.collection = self.client[db_name][collection_name]
        self._cache = {}
    
    async def get_user_data(self, user_id: int, key: str, default=None) -> Any:
        cache_key = f"{user_id}:{key}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        try:
            doc = await self.collection.find_one({"_id": user_id})
            value = doc.get(key, default) if doc else default
            self._cache[cache_key] = value
            return value
        except Exception as e:
            logger.error(f"Database read error: {e}")
            return default
    
    async def save_user_data(self, user_id: int, key: str, value: Any) -> bool:
        cache_key = f"{user_id}:{key}"
        try:
            await self.collection.update_one(
                {"_id": user_id}, 
                {"$set": {key: value}}, 
                upsert=True
            )
            self._cache[cache_key] = value
            return True
        except Exception as e:
            logger.error(f"Database save error for {key}: {e}")
            return False
    
    def clear_user_cache(self, user_id: int):
        """Clear cache for specific user"""
        keys_to_remove = [key for key in self._cache.keys() if key.startswith(f"{user_id}:")]
        for key in keys_to_remove:
            del self._cache[key]
    
    async def get_protected_channels(self) -> Set[int]:
        try:
            channels = set()
            async for doc in self.collection.find({"channel_id": {"$exists": True}}):
                channels.add(doc["channel_id"])
            return channels
        except:
            return set()
    
    async def lock_channel(self, channel_id: int) -> bool:
        try:
            await self.collection.insert_one({"channel_id": channel_id})
            return True
        except:
            return False
    
    async def reset_user_data(self, user_id: int) -> bool:
        try:
            await self.collection.update_one(
                {"_id": user_id}, 
                {"$unset": {
                    "delete_words": "", "replacement_words": "", 
                    "watermark_text": "", "duration_limit": "",
                    "custom_caption": "", "rename_tag": "", "target_chat": ""
                }}
            )
            self.clear_user_cache(user_id)
            return True
        except Exception as e:
            logger.error(f"Reset error: {e}")
            return False

class MediaProcessor:
    """Advanced media processing and file type detection"""
    def __init__(self, config: BotConfig):
        self.config = config
    
    def get_file_type(self, filename: str) -> str:
        """Determine file type based on extension"""
        ext = Path(filename).suffix.lower().lstrip('.')
        if ext in self.config.VIDEO_EXTS:
            return 'video'
        elif ext in self.config.IMG_EXTS:
            return 'photo'
        elif ext in self.config.AUDIO_EXTS:
            return 'audio'
        elif ext in self.config.DOC_EXTS:
            return 'document'
        return 'document'
    
    @staticmethod
    def get_media_info(msg) -> Tuple[Optional[str], Optional[int], str]:
        """Extract filename, file size, and media type from message"""
        if msg.document:
            return msg.document.file_name or "document", msg.document.file_size, "document"
        elif msg.video:
            return msg.video.file_name or "video.mp4", msg.video.file_size, "video"
        elif msg.photo:
            return "photo.jpg", msg.photo.file_size, "photo"
        elif msg.audio:
            return msg.audio.file_name or "audio.mp3", msg.audio.file_size, "audio"
        elif msg.voice:
            return "voice.ogg", getattr(msg.voice, 'file_size', 1), "voice"
        elif msg.video_note:
            return "video_note.mp4", getattr(msg.video_note, 'file_size', 1), "video_note"
        elif msg.sticker:
            return "sticker.webp", getattr(msg.sticker, 'file_size', 1), "sticker"
        return "unknown", 1, "document"

class ProgressManager:
    """Enhanced progress tracking with better formatting"""
    def __init__(self):
        self.user_progress: Dict[int, UserProgress] = defaultdict(UserProgress)
    
    def calculate_progress(self, done: int, total: int, user_id: int, uploader: str = "SpyLib") -> str:
        user_data = self.user_progress[user_id]
        percent = (done / total) * 100
        progress_bar = "♦" * int(percent // 10) + "◇" * (10 - int(percent // 10))
        done_mb, total_mb = done / (1024**2), total / (1024**2)
        
        # Calculate speed and ETA
        speed = max(0, done - user_data.previous_done)
        elapsed_time = max(0.1, time.time() - user_data.previous_time)
        speed_mbps = (speed * 8) / (1024**2 * elapsed_time) if elapsed_time > 0 else 0
        eta_seconds = ((total - done) / speed) if speed > 0 else 0
        eta_min = eta_seconds / 60
        
        # Update progress
        user_data.previous_done = done
        user_data.previous_time = time.time()
        
        return (
            f"╭──────────────────╮\n"
            f"│     **__{uploader} ⚡ Uploader__**\n"
            f"├──────────\n"
            f"│ {progress_bar}\n\n"
            f"│ **__Progress:__** {percent:.2f}%\n"
            f"│ **__Done:__** {done_mb:.2f} MB / {total_mb:.2f} MB\n"
            f"│ **__Speed:__** {speed_mbps:.2f} Mbps\n"
            f"│ **__ETA:__** {eta_min:.2f} min\n"
            f"╰──────────────────╯\n\n"
            f"**__Powered by Team SPY__**"
        )

class CaptionFormatter:
    """Advanced caption processing with markdown to HTML conversion"""
    
    @staticmethod
    async def markdown_to_html(caption: str) -> str:
        """Convert markdown formatting to HTML"""
        if not caption:
            return ""
        
        replacements = [
            (r"^> (.*)", r"<blockquote>\1</blockquote>"),
            (r"```(.*?)```", r"<pre>\1</pre>"),
            (r"`(.*?)`", r"<code>\1</code>"),
            (r"\*\*(.*?)\*\*", r"<b>\1</b>"),
            (r"\*(.*?)\*", r"<b>\1</b>"),
            (r"__(.*?)__", r"<i>\1</i>"),
            (r"_(.*?)_", r"<i>\1</i>"),
            (r"~~(.*?)~~", r"<s>\1</s>"),
            (r"\|\|(.*?)\|\|", r"<details>\1</details>"),
            (r"\[(.*?)\]\((.*?)\)", r'<a href="\2">\1</a>')
        ]
        
        result = caption
        for pattern, replacement in replacements:
            result = re.sub(pattern, replacement, result, flags=re.MULTILINE | re.DOTALL)
        
        return result.strip()

class FileOperations:
    """File operations with enhanced error handling"""
    def __init__(self, config: BotConfig, db: DatabaseManager):
        self.config = config
        self.db = db
    
    @asynccontextmanager
    async def safe_file_operation(self, file_path: str):
        """Safe file operations with automatic cleanup"""
        try:
            yield file_path
        finally:
            await self._cleanup_file(file_path)
    
    async def _cleanup_file(self, file_path: str):
        """Safely remove file"""
        if file_path and os.path.exists(file_path):
            try:
                await asyncio.to_thread(os.remove, file_path)
            except Exception as e:
                logger.error(f"Error removing file {file_path}: {e}")
    
    async def cleanup_stale_files(self, directory: str = "downloads", max_age_minutes: int = 10):
        """
        Sweep stale temp files from disk. Prevents accumulation on Heroku.
        Called periodically or after batch completion.
        """
        if not os.path.exists(directory):
            return 0
        
        cleaned = 0
        cutoff = time.time() - (max_age_minutes * 60)
        
        try:
            for root, dirs, files in os.walk(directory):
                for f in files:
                    filepath = os.path.join(root, f)
                    try:
                        if os.path.getmtime(filepath) < cutoff:
                            os.remove(filepath)
                            cleaned += 1
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Stale file cleanup error: {e}")
        
        if cleaned > 0:
            logger.info(f"🧹 Cleaned {cleaned} stale files from {directory}")
        return cleaned
    
    async def process_filename(self, file_path: str, user_id: int) -> str:
        """Process filename with user preferences"""
        delete_words = set(await self.db.get_user_data(user_id, "delete_words", []))
        replacements = await self.db.get_user_data(user_id, "replacement_words", {})
        rename_tag = await self.db.get_user_data(user_id, "rename_tag", "Team SPY")
        
        path = Path(file_path)
        name = path.stem
        extension = path.suffix.lstrip('.')
        
        # Process filename
        for word in delete_words:
            name = name.replace(word, "")
        
        for word, replacement in replacements.items():
            name = name.replace(word, replacement)
        
        # Normalize extension for videos
        if extension.lower() in self.config.VIDEO_EXTS and extension.lower() not in ['mp4']:
            extension = 'mp4'
        
        new_name = f"{name.strip()} {rename_tag}.{extension}"
        new_path = path.parent / new_name
        
        await asyncio.to_thread(os.rename, file_path, new_path)
        return str(new_path)
    
    async def split_large_file(self, file_path: str, app_client, sender: int, target_chat_id: int, caption: str, topic_id: Optional[int] = None):
        """Split large files into smaller parts"""
        if not os.path.exists(file_path):
            await app_client.send_message(sender, "❌ File not found!")
            return

        file_size = os.path.getsize(file_path)
        start_msg = await app_client.send_message(
            sender, f"ℹ️ File size: {file_size / (1024**2):.2f} MB\n🔄 Splitting and uploading..."
        )

        part_number = 0
        base_path = Path(file_path)
        
        try:
            async with aiofiles.open(file_path, mode="rb") as f:
                while True:
                    chunk = await f.read(self.config.PART_SIZE)
                    if not chunk:
                        break

                    part_file = f"{base_path.stem}.part{str(part_number).zfill(3)}{base_path.suffix}"

                    async with aiofiles.open(part_file, mode="wb") as part_f:
                        await part_f.write(chunk)

                    part_caption = f"{caption}\n\n**Part: {part_number + 1}**" if caption else f"**Part: {part_number + 1}**"
                    
                    edit_msg = await app_client.send_message(target_chat_id, f"⬆️ Uploading part {part_number + 1}...")
                    
                    try:
                        result = await app_client.send_document(
                            target_chat_id,
                            document=part_file,
                            caption=part_caption,
                            reply_to_message_id=topic_id,
                            progress=progress_bar,
                            progress_args=("╭──────────────╮\n│ **__Pyro Uploader__**\n├────────", edit_msg, time.time())
                        )
                        await result.copy(LOG_GROUP)
                        await edit_msg.delete()
                    finally:
                        if os.path.exists(part_file):
                            os.remove(part_file)
                    
                    part_number += 1

        finally:
            await start_msg.delete()
            if os.path.exists(file_path):
                os.remove(file_path)

class SmartTelegramBot:
    """Main bot class with all functionality"""
    def __init__(self):
        self.config = BotConfig()
        self.db = DatabaseManager(MONGODB_CONNECTION_STRING, self.config.DB_NAME, self.config.COLLECTION_NAME)
        self.media_processor = MediaProcessor(self.config)
        self.progress_manager = ProgressManager()
        self.file_ops = FileOperations(self.config, self.db)
        self.caption_formatter = CaptionFormatter()
        
        # Upload queue for ordered concurrent uploads
        self.upload_queue = UploadQueue()
        
        # User session management
        self.user_sessions: Dict[int, str] = {}
        self.pending_photos: Set[int] = set()
        self.user_rename_prefs: Dict[str, str] = {}
        self.user_caption_prefs: Dict[str, str] = {}
        
        # Pro userbot reference
        self.pro_client = pro
        logger.info(f"Pro client available: {'Yes' if self.pro_client else 'No'}")
    
    def get_thumbnail_path(self, user_id: int) -> Optional[str]:
        """Get user's custom thumbnail path"""
        thumb_path = f'{user_id}.jpg'
        return thumb_path if os.path.exists(thumb_path) else None
    
    def parse_target_chat(self, target: str) -> Tuple[int, Optional[int]]:
        """Parse chat ID and topic ID from target string"""
        if '/' in target:
            parts = target.split('/')
            return int(parts[0]), int(parts[1])
        return int(target), None
    
    async def process_user_caption(self, original_caption: str, user_id: int) -> str:
        """Process caption with user preferences"""
        custom_caption = self.user_caption_prefs.get(str(user_id), "") or await self.db.get_user_data(user_id, "custom_caption", "")
        delete_words = set(await self.db.get_user_data(user_id, "delete_words", []))
        replacements = await self.db.get_user_data(user_id, "replacement_words", {})
        
        # Process original caption
        processed = original_caption or ""
        
        # Remove markdown hyperlinks but keep the visible text and formatting
        import re
        processed = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', processed)
        
        # Remove raw URLs
        processed = re.sub(r'https?://[^\s]+', '', processed)
        
        # Remove delete words
        for word in delete_words:
            processed = processed.replace(word, "")
        
        # Apply replacements
        for word, replacement in replacements.items():
            processed = processed.replace(word, replacement)
        
        # Add custom caption
        if custom_caption:
            processed = f"{processed}\n\n{custom_caption}".strip()
        
        return processed if processed else None

    async def upload_with_pyrogram(self, file_path: str, user_id: int, target_chat_id: int, caption: str, topic_id: Optional[int] = None, edit_msg=None):
        """Upload using Pyrogram with proper file type detection"""
        file_type = self.media_processor.get_file_type(file_path)
        thumb_path = self.get_thumbnail_path(user_id)
        
        progress_args = ("╭──────────────╮\n│ **__Pyro Uploader__**\n├────────", edit_msg, time.time())
        
        try:
            if file_type == 'video':
                # Get video metadata
                metadata = {}
                if 'video_metadata' in globals():
                    metadata = video_metadata(file_path)
                
                width = metadata.get('width', 0)
                height = metadata.get('height', 0)
                duration = metadata.get('duration', 0)
                
                # Generate thumbnail if not exists
                if not thumb_path and 'screenshot' in globals():
                    try:
                        thumb_path = await screenshot(file_path, duration, user_id)
                    except:
                        pass
                
                result = await app.send_video(
                    chat_id=target_chat_id,
                    video=file_path,
                    caption=caption,
                    height=height,
                    width=width,
                    duration=duration,
                    thumb=thumb_path,
                    message_thread_id=topic_id,
                    parse_mode=ParseMode.MARKDOWN,
                    progress=progress_bar,
                    progress_args=progress_args
                )
                
            elif file_type == 'photo':
                result = await app.send_photo(
                    chat_id=target_chat_id,
                    photo=file_path,
                    caption=caption,
                    message_thread_id=topic_id,
                    parse_mode=ParseMode.MARKDOWN,
                    progress=progress_bar,
                    progress_args=progress_args
                )
                
            elif file_type == 'audio':
                result = await app.send_audio(
                    chat_id=target_chat_id,
                    audio=file_path,
                    caption=caption,
                    message_thread_id=topic_id,
                    parse_mode=ParseMode.MARKDOWN,
                    progress=progress_bar,
                    progress_args=progress_args
                )
                
            else:  # document
                result = await app.send_document(
                    chat_id=target_chat_id,
                    document=file_path,
                    caption=caption,
                    thumb=thumb_path,
                    message_thread_id=topic_id,
                    parse_mode=ParseMode.MARKDOWN,
                    progress=progress_bar,
                    progress_args=progress_args
                )
            
            # Copy to log group (skip if already uploaded to LOG_GROUP)
            if str(target_chat_id) != str(LOG_GROUP):
                await result.copy(LOG_GROUP)
            return result
            
        except Exception as e:
            await app.send_message(LOG_GROUP, f"**Pyrogram Upload Failed:** {str(e)}")
            raise
        finally:
            if edit_msg:
                try:
                    await edit_msg.delete()
                except:
                    pass

    async def upload_with_telethon(self, file_path: str, user_id: int, target_chat_id: int, caption: str, topic_id: Optional[int] = None, edit_msg=None):
        """Upload using Telethon (SpyLib) with enhanced features"""
        try:
            if edit_msg:
                await edit_msg.delete()
            
            progress_message = await gf.send_message(user_id, "**__SpyLib ⚡ Uploading...__**")
            html_caption = await self.caption_formatter.markdown_to_html(caption)
            
            # Upload file using fast_upload
            uploaded = await fast_upload(
                gf, file_path,
                reply=progress_message,
                name=None,
                progress_bar_function=lambda done, total: self.progress_manager.calculate_progress(done, total, user_id, "SpyLib"),
                user_id=user_id
            )
            
            await progress_message.delete()
            
            # Prepare attributes based on file type
            attributes = []
            file_type = self.media_processor.get_file_type(file_path)
            
            if file_type == 'video':
                if 'video_metadata' in globals():
                    metadata = video_metadata(file_path)
                    duration = metadata.get('duration', 0)
                    width = metadata.get('width', 0)
                    height = metadata.get('height', 0)
                    attributes = [DocumentAttributeVideo(
                        duration=duration, w=width, h=height, supports_streaming=True
                    )]
            
            thumb_path = self.get_thumbnail_path(user_id)
            
            # Send to target chat
            await gf.send_file(
                target_chat_id,
                uploaded,
                caption=html_caption,
                attributes=attributes,
                reply_to=topic_id,
                parse_mode='html',
                thumb=thumb_path
            )
            
            # Send to log group
            await gf.send_file(
                LOG_GROUP,
                uploaded,
                caption=html_caption,
                attributes=attributes,
                parse_mode='html',
                thumb=thumb_path
            )
            
        except Exception as e:
            await app.send_message(LOG_GROUP, f"**SpyLib Upload Failed:** {str(e)}")
            raise

    async def handle_large_file_upload(self, file_path: str, sender: int, edit_msg, caption: str):
        """Handle files larger than 2GB using pro client"""
        if not self.pro_client:
            await edit_msg.edit('**❌ 4GB upload not available - Pro client not configured**')
            return

        await edit_msg.edit('**✅ 4GB upload starting...**')
        
        target_chat_str = await self.db.get_user_data(sender, "target_chat", str(sender))
        target_chat_id, topic_id = self.parse_target_chat(target_chat_str)
        
        file_type = self.media_processor.get_file_type(file_path)
        thumb_path = self.get_thumbnail_path(sender)
        
        progress_args = ("╭──────────────╮\n│ **__4GB Uploader ⚡__**\n├────────", edit_msg, time.time())
        
        try:
            if file_type == 'video':
                metadata = {}
                if 'video_metadata' in globals():
                    metadata = video_metadata(file_path)
                
                result = await self.pro_client.send_video(
                    LOG_GROUP,
                    video=file_path,
                    caption=caption,
                    thumb=thumb_path,
                    height=metadata.get('height', 0),
                    width=metadata.get('width', 0),
                    duration=metadata.get('duration', 0),
                    message_thread_id=topic_id,
                    progress=progress_bar,
                    progress_args=progress_args
                )
            else:
                result = await self.pro_client.send_document(
                    LOG_GROUP,
                    document=file_path,
                    caption=caption,
                    thumb=thumb_path,
                    message_thread_id=topic_id,
                    progress=progress_bar,
                    progress_args=progress_args
                )

            # Send to target chat (always premium - personal use)
            await app.copy_message(target_chat_id, LOG_GROUP, result.id, message_thread_id=topic_id)

        except Exception as e:
            logger.error(f"Large file upload error: {e}")
            await app.send_message(LOG_GROUP, f"**4GB Upload Error:** {str(e)}")
        finally:
            await edit_msg.delete()

    async def _process_message(self, userbot, msg: Message, sender: int, edit_msg: Message):
        """Processes a fetched message with ordered concurrent upload pipeline."""
        file_path = None
        order = None
        try:
            # Get target chat configuration
            target_chat_str = await self.db.get_user_data(sender, "target_chat", str(sender))
            target_chat_id, topic_id = self.parse_target_chat(target_chat_str)
            
            if not msg or msg.service or msg.empty:
                await edit_msg.delete()
                return
            
            # Handle special message types
            if await self._handle_special_messages(msg, target_chat_id, topic_id, edit_msg.id, sender):
                return
                
            # Process media files
            if not msg.media:
                await edit_msg.delete()
                return
            
            filename, file_size, media_type = self.media_processor.get_media_info(msg)
            
            # Handle direct media types (voice, video_note, sticker)
            if await self._handle_direct_media(msg, target_chat_id, topic_id, edit_msg.id, media_type):
                return
            
            # === PIPELINE STEP 1: Wait for download slot (backpressure) ===
            if self.upload_queue.is_download_paused:
                await edit_msg.edit("**⏸️ Waiting for upload queue...**")
            await self.upload_queue.wait_for_download_slot()
            
            # === PIPELINE STEP 2: Download file ===
            await edit_msg.edit("**📥 Downloading...**")
            
            progress_args = ("╭──────────────╮\n│ **__Downloading...__**\n├────────", edit_msg, time.time())
            file_path = await userbot.download_media(
                msg, file_name=filename, progress=progress_bar, progress_args=progress_args
            )
            
            # Process caption and filename
            caption = await self.process_user_caption(msg.caption.markdown if msg.caption else "", sender)
            file_path = await self.file_ops.process_filename(file_path, sender)
            
            # Handle photos separately (small, no queue needed)
            if media_type == "photo":
                result = await app.send_photo(target_chat_id, file_path, caption=caption, message_thread_id=topic_id)
                await result.copy(LOG_GROUP)
                await edit_msg.delete()
                if file_path:
                    await self.file_ops._cleanup_file(file_path)
                return
            
            # === PIPELINE STEP 3: Register file in queue ===
            actual_size = os.path.getsize(file_path) if file_path and os.path.exists(file_path) else file_size
            order = await self.upload_queue.register_file(file_path, actual_size)
            
            upload_method = await self.db.get_user_data(sender, "upload_method", "Pyrogram")
            
            async def upload_task():
                nonlocal file_path, order
                try:
                    # === PIPELINE STEP 4: Acquire upload slot (max 2 parallel) ===
                    await self.upload_queue.acquire_upload_slot()
                    
                    try:
                        if file_size > self.config.SIZE_LIMIT:
                            if not self.pro_client:
                                await edit_msg.delete()
                                await self.file_ops.split_large_file(file_path, app, sender, target_chat_id, caption, topic_id)
                            else:
                                await self.handle_large_file_upload(file_path, sender, edit_msg, caption)
                            return
                        
                        if upload_method == "Telethon" and gf:
                            # === Telethon: Upload to servers, then wait for send turn ===
                            # Step A: Upload to Telegram servers (slow, runs in parallel)
                            if edit_msg:
                                await edit_msg.delete()
                            progress_message = await gf.send_message(sender, "**__⚡ Uploading...__**")
                            html_caption = await self.caption_formatter.markdown_to_html(caption)
                            
                            uploaded = await fast_upload(
                                gf, file_path,
                                reply=progress_message,
                                name=None,
                                progress_bar_function=lambda done, total: self.progress_manager.calculate_progress(done, total, sender, "SpyLib"),
                                user_id=sender
                            )
                            await progress_message.delete()
                            
                            # Prepare attributes
                            attributes = []
                            file_type = self.media_processor.get_file_type(file_path)
                            if file_type == 'video':
                                if 'video_metadata' in globals():
                                    metadata = video_metadata(file_path)
                                    attributes = [DocumentAttributeVideo(
                                        duration=metadata.get('duration', 0),
                                        w=metadata.get('width', 0),
                                        h=metadata.get('height', 0),
                                        supports_streaming=True
                                    )]
                            thumb_path = self.get_thumbnail_path(sender)
                            
                            # Step B: Wait for send turn (sequence preservation)
                            await self.upload_queue.wait_for_send_turn(order)
                            
                            # Step C: Send to chat (instant - already uploaded)
                            await gf.send_file(
                                target_chat_id, uploaded,
                                caption=html_caption, attributes=attributes,
                                reply_to=topic_id, parse_mode='html', thumb=thumb_path
                            )
                            await gf.send_file(
                                LOG_GROUP, uploaded,
                                caption=html_caption, attributes=attributes,
                                parse_mode='html', thumb=thumb_path
                            )
                        else:
                            # === Pyrogram: Upload to LOG_GROUP, then wait for send turn ===
                            # Step A: Upload to LOG_GROUP (order doesn't matter there)
                            result = await self.upload_with_pyrogram(file_path, sender, int(LOG_GROUP), caption, None, edit_msg)
                            
                            # Step B: Wait for send turn (sequence preservation)
                            await self.upload_queue.wait_for_send_turn(order)
                            
                            # Step C: Copy from LOG_GROUP to target chat (instant)
                            if result:
                                await app.copy_message(target_chat_id, int(LOG_GROUP), result.id, message_thread_id=topic_id)
                    finally:
                        self.upload_queue.release_upload_slot()
                    
                    # === PIPELINE STEP 5: Mark as sent, signal next file ===
                    await self.upload_queue.mark_sent(order)
                    
                except Exception as e:
                    logger.error(f"Upload error (order={order}): {e}")
                    # Cancel to prevent deadlock
                    if order is not None:
                        await self.upload_queue.cancel_file(order)
                    try:
                        await edit_msg.edit(f"**Error:** {str(e)}")
                    except:
                        pass
                finally:
                    if file_path:
                        await self.file_ops._cleanup_file(file_path)
                    gc.collect()

            asyncio.create_task(upload_task())
                    
        except Exception as e:
            logger.error(f"Error in _process_message: {e}")
            try:
                await edit_msg.edit(f"**Error:** {str(e)}")
            except:
                pass
            if file_path:
                await self.file_ops._cleanup_file(file_path)
            gc.collect()

    async def handle_message_download(self, userbot, sender: int, edit_id: int, msg_link: str, offset: int, message):
        """Main message processing function with enhanced error handling"""
        edit_msg = None
        
        try:
            edit_msg = await app.get_messages(sender, edit_id)
            # Parse and validate message link
            msg_link = msg_link.split("?single")[0]
            protected_channels = await self.db.get_protected_channels()
            
            # Extract chat and message info
            chat_id, msg_id = await self._parse_message_link(msg_link, offset, protected_channels, sender, edit_id)
            if not chat_id:
                return
            
            # Fetch message
            msg = await userbot.get_messages(chat_id, msg_id)

            # Call the new processing function
            await self._process_message(userbot, msg, sender, edit_msg)

        except (ChannelBanned, ChannelInvalid, ChannelPrivate, ChatIdInvalid, ChatInvalid) as e:
            if edit_msg:
                await edit_msg.edit("❌ Access denied. Have you joined the channel?")
        except Exception as e:
            logger.error(f"Error in message handling: {e}")
            if edit_msg:
                try:
                    await edit_msg.edit(f"**Error:** {str(e)}")
                except:
                    pass

    async def _parse_message_link(self, msg_link: str, offset: int, protected_channels: Set[int], sender: int, edit_id: int) -> Tuple[Optional[int], Optional[int]]:
        """Parse different types of message links"""
        if 't.me/c/' in msg_link or 't.me/b/' in msg_link:
            parts = msg_link.split("/")
            if 't.me/b/' in msg_link:
                chat_id = parts[-2]
                msg_id = int(parts[-1]) + offset
            else:
                chat_id = int('-100' + parts[parts.index('c') + 1])
                msg_id = int(parts[-1]) + offset
            
            if chat_id in protected_channels:
                await app.edit_message_text(sender, edit_id, "❌ This channel is protected by **Team SPY**.")
                return None, None
                
            return chat_id, msg_id
        
        elif '/s/' in msg_link:
            # Handle story links
            await app.edit_message_text(sender, edit_id, "📖 Story Link Detected...")
            if not gf:
                await app.edit_message_text(sender, edit_id, "❌ Login required to save stories...")
                return None, None
            
            parts = msg_link.split("/")
            chat = f"-100{parts[3]}" if parts[3].isdigit() else parts[3]
            msg_id = int(parts[-1])
            await self._download_user_stories(gf, chat, msg_id, sender, edit_id)
            return None, None
        
        else:
            # Handle public links
            await app.edit_message_text(sender, edit_id, "🔗 Public link detected...")
            chat = msg_link.split("t.me/")[1].split("/")[0]
            msg_id = int(msg_link.split("/")[-1])
            await self._copy_public_message(app, gf, sender, chat, msg_id, edit_id)
            return None, None

    async def _handle_special_messages(self, msg, target_chat_id: int, topic_id: Optional[int], edit_id: int, sender: int) -> bool:
        """Handle special message types that don't require downloading"""
        if msg.media == MessageMediaType.WEB_PAGE_PREVIEW:
            result = await app.send_message(target_chat_id, msg.text.markdown, message_thread_id=topic_id)
            await result.copy(LOG_GROUP)
            await app.delete_messages(sender, edit_id)
            return True
        
        if msg.text:
            result = await app.send_message(target_chat_id, msg.text.markdown, message_thread_id=topic_id)
            await result.copy(LOG_GROUP)
            await app.delete_messages(sender, edit_id)
            return True
            
        return False

    async def _handle_direct_media(self, msg, target_chat_id: int, topic_id: Optional[int], edit_id: int, media_type: str) -> bool:
        """Handle media that can be sent directly without downloading"""
        result = None
        
        try:
            if media_type == "sticker":
                result = await app.send_sticker(target_chat_id, msg.sticker.file_id, message_thread_id=topic_id)
            elif media_type == "voice":
                result = await app.send_voice(target_chat_id, msg.voice.file_id, message_thread_id=topic_id)
            elif media_type == "video_note":
                result = await app.send_video_note(target_chat_id, msg.video_note.file_id, message_thread_id=topic_id)
            
            if result:
                await result.copy(LOG_GROUP)
                await app.delete_messages(msg.chat.id, edit_id)
                return True
                
        except Exception as e:
            logger.error(f"Direct media send failed: {e}")
            return False
            
        return False

    async def _download_user_stories(self, userbot, chat_id: str, msg_id: int, sender: int, edit_id: int):
        """Download and send user stories"""
        try:
            edit_msg = await app.edit_message_text(sender, edit_id, "📖 Downloading Story...")
            story = await userbot.get_stories(chat_id, msg_id)
            
            if not story or not story.media:
                await edit_msg.edit("❌ No story available or no media.")
                return
            
            file_path = await userbot.download_media(story)
            await edit_msg.edit("📤 Uploading Story...")
            
            if story.media == MessageMediaType.VIDEO:
                await app.send_video(sender, file_path)
            elif story.media == MessageMediaType.DOCUMENT:
                await app.send_document(sender, file_path)
            elif story.media == MessageMediaType.PHOTO:
                await app.send_photo(sender, file_path)
            
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
            await edit_msg.edit("✅ Story processed successfully.")
            
        except RPCError as e:
            await app.edit_message_text(sender, edit_id, f"❌ Error: {e}")

    async def _copy_public_message(self, app_client, userbot, sender: int, chat_id: str, message_id: int, edit_id: int):
        """Handle copying from public channels/groups"""
        target_chat_str = await self.db.get_user_data(sender, "target_chat", str(sender))
        target_chat_id, topic_id = self.parse_target_chat(target_chat_str)
        file_path = None
        
        try:
            # Try direct copy first
            msg = await app_client.get_messages(chat_id, message_id)
            custom_caption = self.user_caption_prefs.get(str(sender), "")
            final_caption = await self._format_caption_with_custom(msg.caption or '', sender, custom_caption)

            if msg.media and not msg.document and not msg.video:
                # For photos and other simple media
                if msg.photo:
                    result = await app_client.send_photo(target_chat_id, msg.photo.file_id, caption=final_caption, message_thread_id=topic_id)
                elif msg.video:
                    result = await app_client.send_video(target_chat_id, msg.video.file_id, caption=final_caption, message_thread_id=topic_id)
                elif msg.document:
                    result = await app_client.send_document(target_chat_id, msg.document.file_id, caption=final_caption, message_thread_id=topic_id)
                
                if 'result' in locals():
                    await result.copy(LOG_GROUP)
                    await app.delete_messages(sender, edit_id)
                    return

            elif msg.text:
                result = await app_client.copy_message(target_chat_id, chat_id, message_id, message_thread_id=topic_id)
                await result.copy(LOG_GROUP)
                await app.delete_messages(sender, edit_id)
                return

            # If direct copy failed, try with userbot
            if userbot:
                edit_msg = await app.edit_message_text(sender, edit_id, "🔄 Trying alternative method...")
                try:
                    await userbot.join_chat(chat_id)
                except:
                    pass
                
                chat_id = (await userbot.get_chat(f"@{chat_id}")).id
                msg = await userbot.get_messages(chat_id, message_id)

                if not msg or msg.service or msg.empty:
                    await edit_msg.edit("❌ Message not found or inaccessible")
                    return

                if msg.text:
                    await app_client.send_message(target_chat_id, msg.text.markdown, message_thread_id=topic_id)
                    await edit_msg.delete()
                    return

                # Download and upload media
                final_caption = await self._format_caption_with_custom(msg.caption.markdown if msg.caption else "", sender, custom_caption)
                
                progress_args = ("Downloading...", edit_msg, time.time())
                file_path = await userbot.download_media(msg, progress=progress_bar, progress_args=progress_args)
                file_path = await self.file_ops.process_filename(file_path, sender)

                filename, file_size, media_type = self.media_processor.get_media_info(msg)

                if media_type == "photo":
                    result = await app_client.send_photo(target_chat_id, file_path, caption=final_caption, message_thread_id=topic_id)
                elif file_size > self.config.SIZE_LIMIT:
                    if not self.pro_client:
                        await edit_msg.delete()
                        await self.file_ops.split_large_file(file_path, app_client, sender, target_chat_id, final_caption, topic_id)
                        return
                    else:
                        await self.handle_large_file_upload(file_path, sender, edit_msg, final_caption)
                        return
                else:
                    upload_method = await self.db.get_user_data(sender, "upload_method", "Pyrogram")
                    if upload_method == "Telethon":
                        await self.upload_with_telethon(file_path, sender, target_chat_id, final_caption, topic_id, edit_msg)
                    else:
                        await self.upload_with_pyrogram(file_path, sender, target_chat_id, final_caption, topic_id, edit_msg)

        except Exception as e:
            logger.error(f"Public message copy error: {e}")
        finally:
            if file_path:
                await self.file_ops._cleanup_file(file_path)

    async def _format_caption_with_custom(self, original_caption: str, sender: int, custom_caption: str) -> str:
        """Format caption with user preferences"""
        delete_words = set(await self.db.get_user_data(sender, "delete_words", []))
        replacements = await self.db.get_user_data(sender, "replacement_words", {})
        
        processed = original_caption
        for word in delete_words:
            processed = processed.replace(word, '  ')
        
        for word, replace_word in replacements.items():
            processed = processed.replace(word, replace_word)
        
        if custom_caption:
            return f"{processed}\n\n__**{custom_caption}**__" if processed else f"__**{custom_caption}**__"
        return processed

    async def send_settings_panel(self, chat_id: int, user_id: int):
        """Send enhanced settings panel"""
        buttons = [
            [Button.inline("Set Chat ID", b'setchat'), Button.inline("Set Rename Tag", b'setrename')],
            [Button.inline("Caption", b'setcaption'), Button.inline("Replace Words", b'setreplacement')],
            [Button.inline("Remove Words", b'delete'), Button.inline("Reset All", b'reset')],
            [Button.inline("Session Login", b'addsession'), Button.inline("Logout", b'logout')],
            [Button.inline("Set Thumbnail", b'setthumb'), Button.inline("Remove Thumbnail", b'remthumb')],
            [Button.inline("PDF Watermark", b'pdfwt'), Button.inline("Video Watermark", b'watermark')],
            [Button.inline("Upload Method", b'uploadmethod')],
            [Button.url("Report Issues", "https://t.me/team_spy_pro")]
        ]
        
        message = (
            "🛠 **Advanced Settings Panel**\n\n"
            "Customize your bot experience with these options:\n"
            "• Configure upload methods\n"
            "• Set custom captions and rename tags\n"
            "• Manage word filters and replacements\n"
            "• Handle thumbnails and watermarks\n\n"
            "Select an option to get started!"
        )
        
        await gf.send_file(chat_id, file=self.config.SETTINGS_PIC, caption=message, buttons=buttons)

# Initialize the main bot instance
telegram_bot = SmartTelegramBot()

# Event Handlers
@gf.on(events.NewMessage(incoming=True, pattern='/settings'))
async def settings_command_handler(event):
    """Handle /settings command"""
    await telegram_bot.send_settings_panel(event.chat_id, event.sender_id)

@gf.on(events.CallbackQuery)
async def callback_query_handler(event):
    """Enhanced callback query handler with all features"""
    user_id = event.sender_id
    data = event.data
    
    # Upload method selection
    if data == b'uploadmethod':
        current_method = await telegram_bot.db.get_user_data(user_id, "upload_method", "Pyrogram")
        pyro_check = " ✅" if current_method == "Pyrogram" else ""
        tele_check = " ✅" if current_method == "Telethon" else ""
        
        buttons = [
            [Button.inline(f"Pyrogram v2{pyro_check}", b'pyrogram')],
            [Button.inline(f"SpyLib v1 ⚡{tele_check}", b'telethon')]
        ]
        await event.edit(
            "📤 **Choose Upload Method:**\n\n"
            "**Pyrogram v2:** Standard, reliable uploads\n"
            "**SpyLib v1 ⚡:** Advanced features, beta version\n\n"
            "**Note:** SpyLib is built on Telethon and offers enhanced capabilities.",
            buttons=buttons
        )

    elif data == b'pyrogram':
        await telegram_bot.db.save_user_data(user_id, "upload_method", "Pyrogram")
        await event.edit("✅ Upload method set to **Pyrogram v2**")

    elif data == b'telethon':
        await telegram_bot.db.save_user_data(user_id, "upload_method", "Telethon")
        await event.edit("✅ Upload method set to **SpyLib v1 ⚡**\n\nThanks for helping us test this advanced library!")

    # Session management
    elif data == b'logout':
        await odb.remove_session(user_id)
        user_data = await odb.get_data(user_id)
        message = "✅ Logged out successfully!" if user_data and user_data.get("session") is None else "❌ You are not logged in."
        await event.respond(message)

    elif data == b'addsession':
        telegram_bot.user_sessions[user_id] = 'addsession'
        await event.respond("🔑 **Session Login**\n\nSend your Pyrogram V2 session string:")

    # Settings configuration
    elif data == b'setchat':
        telegram_bot.user_sessions[user_id] = 'setchat'
        await event.respond("💬 **Set Target Chat**\n\nSend the chat ID where files should be sent:")

    elif data == b'setrename':
        telegram_bot.user_sessions[user_id] = 'setrename'
        await event.respond("🏷 **Set Rename Tag**\n\nSend the tag to append to filenames:")

    elif data == b'setcaption':
        telegram_bot.user_sessions[user_id] = 'setcaption'
        await event.respond("📝 **Set Custom Caption**\n\nSend the caption to add to all files:")

    elif data == b'setreplacement':
        telegram_bot.user_sessions[user_id] = 'setreplacement'
        await event.respond(
            "🔄 **Word Replacement**\n\n"
            "Send replacement rules in format:\n"
            "`'OLD_WORD' 'NEW_WORD'`\n\n"
            "Example: `'sample' 'example'`"
        )

    elif data == b'delete':
        telegram_bot.user_sessions[user_id] = 'deleteword'
        await event.respond(
            "🗑 **Delete Words**\n\n"
            "Send words separated by spaces to remove them from captions/filenames:"
        )

    # Thumbnail management
    elif data == b'setthumb':
        telegram_bot.pending_photos.add(user_id)
        await event.respond("🖼 **Set Thumbnail**\n\nSend a photo to use as thumbnail for videos:")

    elif data == b'remthumb':
        thumb_path = f'{user_id}.jpg'
        if os.path.exists(thumb_path):
            os.remove(thumb_path)
            await event.respond('✅ Thumbnail removed successfully!')
        else:
            await event.respond("❌ No thumbnail found to remove.")

    # Watermark features (placeholder)
    elif data == b'pdfwt':
        await event.respond("🚧 **PDF Watermark**\n\nThis feature is under development...")

    elif data == b'watermark':
        await event.respond("🚧 **Video Watermark**\n\nThis feature is under development...")

    # Reset all settings
    elif data == b'reset':
        try:
            success = await telegram_bot.db.reset_user_data(user_id)
            telegram_bot.db.clear_user_cache(user_id)
            telegram_bot.user_rename_prefs.pop(str(user_id), None)
            telegram_bot.user_caption_prefs.pop(str(user_id), None)
            
            # Remove thumbnail
            thumb_path = f"{user_id}.jpg"
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
            
            if success:
                await event.respond("✅ All settings reset successfully!\n\nUse /logout to remove session.")
            else:
                await event.respond("❌ Error occurred while resetting settings.")
        except Exception as e:
            await event.respond(f"❌ Reset failed: {e}")

@gf.on(events.NewMessage(func=lambda e: e.sender_id in telegram_bot.pending_photos))
async def thumbnail_handler(event):
    """Handle thumbnail upload"""
    user_id = event.sender_id
    if event.photo:
        temp_path = await event.download_media()
        thumb_path = f'{user_id}.jpg'
        
        if os.path.exists(thumb_path):
            os.remove(thumb_path)
        
        os.rename(temp_path, f'./{user_id}.jpg')
        await event.respond('✅ Thumbnail saved successfully!')
    else:
        await event.respond('❌ Please send a photo. Try again.')
    
    telegram_bot.pending_photos.discard(user_id)

@gf.on(events.NewMessage)
async def user_input_handler(event):
    """Handle user input based on current session state"""
    user_id = event.sender_id
    
    if user_id in telegram_bot.user_sessions:
        session_type = telegram_bot.user_sessions[user_id]
        
        if session_type == 'setchat':
            try:
                chat_id = event.text.strip()
                if not re.match(r'^-?\d+(/\d+)?$', chat_id):
                    await event.respond("❌ Invalid format. Use `chat_id` or `chat_id/topic_id`.")
                    del telegram_bot.user_sessions[user_id]
                    return
                await telegram_bot.db.save_user_data(user_id, "target_chat", chat_id)
                await event.respond(f"✅ Target chat set to: `{chat_id}`")
            except ValueError:
                await event.respond("❌ Invalid chat ID format!")
        elif session_type == 'setrename':
            rename_tag = event.text.strip()
            telegram_bot.user_rename_prefs[str(user_id)] = rename_tag
            await telegram_bot.db.save_user_data(user_id, "rename_tag", rename_tag)
            await event.respond(f"✅ Rename tag set to: **{rename_tag}**")
        
        elif session_type == 'setcaption':
            custom_caption = event.text.strip()
            telegram_bot.user_caption_prefs[str(user_id)] = custom_caption
            await telegram_bot.db.save_user_data(user_id, "custom_caption", custom_caption)
            await event.respond(f"✅ Custom caption set to:\n\n**{custom_caption}**")

        elif session_type == 'setreplacement':
            match = re.match(r"'(.+)' '(.+)'", event.text)
            if not match:
                await event.respond("❌ **Invalid format!**\n\nUse: `'OLD_WORD' 'NEW_WORD'`")
            else:
                old_word, new_word = match.groups()
                delete_words = set(await telegram_bot.db.get_user_data(user_id, "delete_words", []))
                
                if old_word in delete_words:
                    await event.respond(f"❌ '{old_word}' is in delete list and cannot be replaced.")
                else:
                    replacements = await telegram_bot.db.get_user_data(user_id, "replacement_words", {})
                    replacements[old_word] = new_word
                    await telegram_bot.db.save_user_data(user_id, "replacement_words", replacements)
                    await event.respond(f"✅ Replacement saved:\n**'{old_word}' → '{new_word}'**")

        elif session_type == 'addsession':
            session_string = event.text.strip()
            await odb.set_session(user_id, session_string)
            await event.respond("✅ Session string added successfully!")
                
        elif session_type == 'deleteword':
            words_to_delete = event.text.split()
            delete_words = set(await telegram_bot.db.get_user_data(user_id, "delete_words", []))
            delete_words.update(words_to_delete)
            await telegram_bot.db.save_user_data(user_id, "delete_words", list(delete_words))
            await event.respond(f"✅ Words added to delete list:\n**{', '.join(words_to_delete)}**")
               
        # Clear session after handling
        del telegram_bot.user_sessions[user_id]

@gf.on(events.NewMessage(incoming=True, pattern='/lock'))
async def lock_channel_handler(event):
    """Handle channel locking command (owner only)"""
    if event.sender_id not in OWNER_ID:
        await event.respond("❌ You are not authorized to use this command.")
        return
    
    try:
        channel_id = int(event.text.split(' ')[1])
        success = await telegram_bot.db.lock_channel(channel_id)
        
        if success:
            await event.respond(f"✅ Channel ID `{channel_id}` locked successfully.")
        else:
            await event.respond(f"❌ Failed to lock channel ID `{channel_id}`.")
    except (ValueError, IndexError):
        await event.respond("❌ **Invalid command format.**\n\nUse: `/lock CHANNEL_ID`")
    except Exception as e:
        await event.respond(f"❌ Error: {str(e)}")

# Main message handler function (integration point with existing get_msg function)
async def get_msg(userbot, sender, edit_id, msg_link, i, message):
    """Main integration function - enhanced version of original get_msg"""
    await telegram_bot.handle_message_download(userbot, sender, edit_id, msg_link, i, message)

logger.info("✅ Smart Telegram Bot initialized successfully!")
logger.info(f"📊 Features loaded:")
logger.info(f"   • Database: {'✅' if telegram_bot.db else '❌'}")
logger.info(f"   • Pro Client (4GB): {'✅' if telegram_bot.pro_client else '❌'}")
logger.info(f"   • Userbot: {'✅' if gf else '❌'}")
logger.info(f"   • App Client: {'✅' if app else '❌'}")
