import logging
from os import getenv

logger = logging.getLogger(__name__)

# VPS --- FILL COOKIES in """ ... """
INST_COOKIES = """
# write up here insta cookies
"""

YTUB_COOKIES = """
# write here yt cookies
"""

API_ID = int(getenv("API_ID", ""))
API_HASH = getenv("API_HASH", "")
BOT_TOKEN = getenv("BOT_TOKEN", "")
OWNER_ID = list(map(int, getenv("OWNER_ID", "").split()))
MONGO_DB = getenv("MONGO_DB", "")
LOG_GROUP = getenv("LOG_GROUP", "")
CHANNEL_ID = int(getenv("CHANNEL_ID", "0"))
STRING = getenv("STRING", None)
YT_COOKIES = getenv("YT_COOKIES", YTUB_COOKIES)
DEFAULT_SESSION = getenv("DEFAULT_SESSION", None)  # Fixed typo: was DEFAUL_SESSION
INSTA_COOKIES = getenv("INSTA_COOKIES", INST_COOKIES)

# Performance tuning
BATCH_LIMIT = int(getenv("BATCH_LIMIT", "500"))
MAX_PARALLEL_UPLOADS = int(getenv("MAX_PARALLEL_UPLOADS", "2"))
MAX_PENDING_FILES = int(getenv("MAX_PENDING_FILES", "7"))
MAX_PENDING_SIZE_GB = float(getenv("MAX_PENDING_SIZE_GB", "2"))
PROGRESS_UPDATE_INTERVAL = int(getenv("PROGRESS_UPDATE_INTERVAL", "10"))  # seconds
INTER_FILE_DELAY = int(getenv("INTER_FILE_DELAY", "3"))  # seconds
