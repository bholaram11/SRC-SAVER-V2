# ---------------------------------------------------
# File Name: db.py
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

from config import MONGO_DB
from motor.motor_asyncio import AsyncIOMotorClient as MongoCli
mongo = MongoCli(MONGO_DB)
db = mongo.user_data
db = db.users_data_db
async def get_data(user_id):
    x = await db.find_one({"_id": user_id})
    return x
async def set_thumbnail(user_id, thumb):
    data = await get_data(user_id)
    if data and data.get("_id"):
        await db.update_one({"_id": user_id}, {"$set": {"thumb": thumb}})
    else:
        await db.insert_one({"_id": user_id, "thumb": thumb})
async def set_caption(user_id, caption):
    data = await get_data(user_id)
    if data and data.get("_id"):
        await db.update_one({"_id": user_id}, {"$set": {"caption": caption}})
    else:
        await db.insert_one({"_id": user_id, "caption": caption})
async def replace_caption(user_id, replace_txt, to_replace):
    data = await get_data(user_id)
    if data and data.get("_id"):
        await db.update_one({"_id": user_id}, {"$set": {"replace_txt": replace_txt, "to_replace": to_replace}})
    else:
        await db.insert_one({"_id": user_id, "replace_txt": replace_txt, "to_replace": to_replace})
async def set_session(user_id, session):
    data = await get_data(user_id)
    if data and data.get("_id"):
        await db.update_one({"_id": user_id}, {"$set": {"session": session}})
    else:
        await db.insert_one({"_id": user_id, "session": session})
async def clean_words(user_id, new_clean_words):
    data = await get_data(user_id)
    if data and data.get("_id"):
        existing_words = data.get("clean_words", [])
         
        if existing_words is None:
            existing_words = []
        updated_words = list(set(existing_words + new_clean_words))
        await db.update_one({"_id": user_id}, {"$set": {"clean_words": updated_words}})
    else:
        await db.insert_one({"_id": user_id, "clean_words": new_clean_words})
async def remove_clean_words(user_id, words_to_remove):
    data = await get_data(user_id)
    if data and data.get("_id"):
        existing_words = data.get("clean_words", [])
        updated_words = [word for word in existing_words if word not in words_to_remove]
        await db.update_one({"_id": user_id}, {"$set": {"clean_words": updated_words}})
    else:
        await db.insert_one({"_id": user_id, "clean_words": []})
async def set_channel(user_id, chat_id):
    data = await get_data(user_id)
    if data and data.get("_id"):
        await db.update_one({"_id": user_id}, {"$set": {"chat_id": chat_id}})
    else:
        await db.insert_one({"_id": user_id, "chat_id": chat_id})
async def all_words_remove(user_id):
    await db.update_one({"_id": user_id}, {"$set": {"clean_words": None}})
async def remove_thumbnail(user_id):
    await db.update_one({"_id": user_id}, {"$set": {"thumb": None}})
async def remove_caption(user_id):
    await db.update_one({"_id": user_id}, {"$set": {"caption": None}})
async def remove_replace(user_id):
    await db.update_one({"_id": user_id}, {"$set": {"replace_txt": None, "to_replace": None}})
 
async def remove_session(user_id):
    await db.update_one({"_id": user_id}, {"$set": {"session": None}})
async def remove_channel(user_id):
    await db.update_one({"_id": user_id}, {"$set": {"chat_id": None}})
async def delete_session(user_id):
    """Delete the session associated with the given user_id from the database."""
    await db.update_one({"_id": user_id}, {"$unset": {"session": ""}})

# Topic batch ID storage helpers
async def set_topic_msg_ids(user_id, msg_ids):
    data = await get_data(user_id)
    if data and data.get("_id"):
        await db.update_one({"_id": user_id}, {"$set": {"topic_msg_ids": msg_ids}})
    else:
        await db.insert_one({"_id": user_id, "topic_msg_ids": msg_ids})

async def get_topic_msg_ids(user_id):
    data = await get_data(user_id)
    return data.get("topic_msg_ids", []) if data else []

async def clear_topic_msg_ids(user_id):
    await db.update_one({"_id": user_id}, {"$unset": {"topic_msg_ids": ""}})

# Batch state persistence for auto-resume
async def save_batch_state(user_id, batch_data):
    """Save current batch state for recovery after crash/FloodWait."""
    data = await get_data(user_id)
    if data and data.get("_id"):
        await db.update_one({"_id": user_id}, {"$set": {"batch_state": batch_data}})
    else:
        await db.insert_one({"_id": user_id, "batch_state": batch_data})

async def get_active_batch(user_id=None):
    """Get active batch state. If user_id is None, find any active batch."""
    if user_id:
        data = await get_data(user_id)
        if data and data.get("batch_state", {}).get("status") == "active":
            batch = data["batch_state"]
            batch["user_id"] = user_id
            return batch
    else:
        # Find any active batch across all users
        async for doc in db.find({"batch_state.status": "active"}):
            batch = doc.get("batch_state", {})
            batch["user_id"] = doc["_id"]
            return batch
    return None

async def update_batch_progress(user_id, last_processed_id, processed_count):
    """Update the progress of an active batch."""
    await db.update_one(
        {"_id": user_id},
        {"$set": {
            "batch_state.last_processed_id": last_processed_id,
            "batch_state.processed_count": processed_count
        }}
    )

async def clear_batch_state(user_id):
    """Clear batch state after completion or force stop."""
    await db.update_one({"_id": user_id}, {"$unset": {"batch_state": ""}})
