import asyncio
import importlib
import gc
import logging
from pyrogram import idle
from devgagan.modules import ALL_MODULES

logger = logging.getLogger(__name__)

# ----------------------------Bot-Start---------------------------- #

loop = asyncio.get_event_loop()

async def periodic_disk_cleanup():
    """Background task: sweep stale temp files every 5 minutes."""
    await asyncio.sleep(60)  # Initial delay
    while True:
        try:
            from devgagan.core.get_func import telegram_bot
            await telegram_bot.file_ops.cleanup_stale_files("downloads", max_age_minutes=10)
            gc.collect()
        except Exception as e:
            logger.debug(f"Periodic cleanup: {e}")
        await asyncio.sleep(300)  # Every 5 minutes

async def devggn_boot():
    for all_module in ALL_MODULES:
        importlib.import_module("devgagan.modules." + all_module)
    logger.info("""
---------------------------------------------------
📂 Bot Deployed successfully ...
📝 Optimized for personal use (single user)
🛠️ Version: 3.0.0 (Optimized)
---------------------------------------------------
""")

    # Auto-resume interrupted batches (runs in background)
    try:
        from devgagan.modules.main import auto_resume_batch
        asyncio.create_task(auto_resume_batch())
        logger.info("🔄 Auto-resume check scheduled.")
    except Exception as e:
        logger.warning(f"Could not schedule auto-resume: {e}")

    # Periodic disk cleanup (runs in background)
    asyncio.create_task(periodic_disk_cleanup())
    logger.info("🧹 Periodic disk cleanup scheduled.")

    logger.info("Bot is running...")
    await idle()
    logger.info("Bot stopped.")


if __name__ == "__main__":
    loop.run_until_complete(devggn_boot())

# ------------------------------------------------------------------ #
