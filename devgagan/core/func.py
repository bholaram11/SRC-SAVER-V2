import math
import time
import re
import os
import asyncio
import subprocess
import logging
from pyrogram import enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import FloodWait, InviteHashInvalid, InviteHashExpired, UserAlreadyParticipant, UserNotParticipant
from datetime import datetime as dt
from config import OWNER_ID

logger = logging.getLogger(__name__)

# Owner check (simplified - no premium needed for personal use)
async def chk_user(message, user_id):
    """Always returns 0 (premium) since this is personal use only."""
    return 0

async def subscribe(app, message):
    """No-op: subscription check disabled for personal use."""
    return 0

async def get_seconds(time_string):
    def extract_value_and_unit(ts):
        value = ""
        unit = ""
        index = 0
        while index < len(ts) and ts[index].isdigit():
            value += ts[index]
            index += 1
        unit = ts[index:].lstrip()
        if value:
            value = int(value)
        return value, unit

    value, unit = extract_value_and_unit(time_string)

    if unit == 's':
        return value
    elif unit == 'min':
        return value * 60
    elif unit == 'hour':
        return value * 3600
    elif unit == 'day':
        return value * 86400
    elif unit == 'month':
        return value * 86400 * 30
    elif unit == 'year':
        return value * 86400 * 365
    else:
        return 0

PROGRESS_BAR = """\n
│ **__Completed:__** {1}/{2}
│ **__Bytes:__** {0}%
│ **__Speed:__** {3}/s
│ **__ETA:__** {4}
╰─────────────────────╯
"""

async def progress_bar(current, total, ud_type, message, start, last_update=None):
    """
    Throttled progress bar with proper timing.
    - Telegram message edit ONLY when needed (every 5 seconds max)
    - Speed logging ALWAYS happens (for debugging)
    """
    from config import PROGRESS_UPDATE_INTERVAL
    from devgagan.core.get_func import telegram_bot
    from devgagan.core.flood_prevention import flood_preventor

    now = time.time()
    diff = now - start

    # Calculate speed and progress
    percentage = current * 100 / total
    speed = current / diff if diff > 0 else 0
    elapsed_time = round(diff) * 1000
    time_to_completion = round((total - current) / speed) * 1000 if speed > 0 else 0

    # ALWAYS log speed progress (no API call, just logging)
    if current % (1024 * 1024) == 0 or current == total:  # Log every 1MB or at end
        logger.info(
            f"📥 Download progress: {humanbytes(current)}/{humanbytes(total)} "
            f"({round(percentage, 1)}%) | Speed: {humanbytes(speed)}/s "
            f"| ETA: {TimeFormatter(time_to_completion)}"
        )

    # Initialize last_update if not provided
    if last_update is None:
        last_update = {'time': 0}

    # Only edit Telegram message if PROGRESS_UPDATE_INTERVAL seconds passed
    if now - last_update['time'] >= PROGRESS_UPDATE_INTERVAL or current == total:
        last_update['time'] = now

        elapsed_time_formatted = TimeFormatter(milliseconds=elapsed_time)
        eta_formatted = TimeFormatter(milliseconds=time_to_completion)

        # Build progress bar
        progress = "{0}{1}".format(
            ''.join(["♦" for i in range(math.floor(percentage / 10))]),
            ''.join(["◇" for i in range(10 - math.floor(percentage / 10))]))

        # Get pipeline stats
        try:
            q_stats = telegram_bot.upload_queue.get_status()
            fp_stats = flood_preventor.get_stats()

            status_line = f"│ 🚦 **Queue:** `{q_stats['pending_count']} files ({q_stats['pending_size_mb']}MB)`\n│ ⏱️ **Delay:** `{fp_stats['current_delay']}`"
        except:
            status_line = ""

        tmp = progress + f"\n\n{status_line}\n" + PROGRESS_BAR.format(
            round(percentage, 2),
            humanbytes(current),
            humanbytes(total),
            humanbytes(speed),
            eta_formatted if eta_formatted else "0 s"
        )

        try:
            await message.edit(text="{}\n│ {}".format(ud_type, tmp))
        except Exception:
            pass

    return last_update

def humanbytes(size):
    if not size:
        return ""
    power = 2**10
    n = 0
    Dic_powerN = {0: ' ', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return str(round(size, 2)) + " " + Dic_powerN[n] + 'B'

def TimeFormatter(milliseconds: int) -> str:
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    tmp = ((str(days) + "d, ") if days else "") + \
        ((str(hours) + "h, ") if hours else "") + \
        ((str(minutes) + "m, ") if minutes else "") + \
        ((str(seconds) + "s, ") if seconds else "") + \
        ((str(milliseconds) + "ms, ") if milliseconds else "")
    return tmp[:-2] 

def convert(seconds):
    seconds = seconds % (24 * 3600)
    hour = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60      
    return "%d:%02d:%02d" % (hour, minutes, seconds)

async def userbot_join(userbot, invite_link):
    try:
        await userbot.join_chat(invite_link)
        return "Successfully joined the Channel"
    except UserAlreadyParticipant:
        return "User is already a participant."
    except (InviteHashInvalid, InviteHashExpired):
        return "Could not join. Maybe your link is expired or Invalid."
    except FloodWait:
        return "Too many requests, try again later."
    except Exception as e:
        logger.error(f"Join error: {e}")
        return "Could not join, try joining manually."

def get_link(string):
    regex = r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»""'']))"
    url = re.findall(regex, string)   
    try:
        link = [x[0] for x in url][0]
        if link:
            return link
        else:
            return False
    except Exception:
        return False

def video_metadata(file):
    """Get video metadata using ffprobe (lightweight) instead of cv2 (heavy)."""
    default_values = {'width': 1, 'height': 1, 'duration': 1}
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_streams', '-show_format', file
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return default_values
        
        import json
        data = json.loads(result.stdout)
        
        # Find video stream
        width, height, duration = 1, 1, 1
        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'video':
                width = int(stream.get('width', 1))
                height = int(stream.get('height', 1))
                break
        
        # Get duration from format
        fmt = data.get('format', {})
        dur = fmt.get('duration', '1')
        duration = round(float(dur))
        
        return {'width': width, 'height': height, 'duration': duration}
    except Exception as e:
        logger.error(f"Error in video_metadata: {e}")
        return default_values

def hhmmss(seconds):
    return time.strftime('%H:%M:%S', time.gmtime(seconds))

async def screenshot(video, duration, sender):
    if os.path.exists(f'{sender}.jpg'):
        return f'{sender}.jpg'
    time_stamp = hhmmss(int(duration)/2)
    out = dt.now().isoformat("_", "seconds") + ".jpg"
    cmd = ["ffmpeg",
           "-ss",
           f"{time_stamp}", 
           "-i",
           f"{video}",
           "-frames:v",
           "1", 
           f"{out}",
           "-y"
          ]
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if os.path.isfile(out):
        return out
    else:
        return None

async def progress_callback(current, total, progress_message):
    """Throttled upload progress callback."""
    from config import PROGRESS_UPDATE_INTERVAL
    percent = (current / total) * 100
    
    # Use a simple time-based throttle
    current_time = time.time()
    if not hasattr(progress_callback, '_last_update'):
        progress_callback._last_update = 0
    
    if current_time - progress_callback._last_update >= PROGRESS_UPDATE_INTERVAL or percent >= 100:
        completed_blocks = int(percent // 10)
        remaining_blocks = 10 - completed_blocks
        bar = "♦" * completed_blocks + "◇" * remaining_blocks
        current_mb = current / (1024 * 1024)  
        total_mb = total / (1024 * 1024)      
        try:
            await progress_message.edit(
                f"╭──────────────────╮\n"
                f"│        **__Uploading...__**       \n"
                f"├──────────\n"
                f"│ {bar}\n\n"
                f"│ **__Progress:__** {percent:.2f}%\n"
                f"│ **__Uploaded:__** {current_mb:.2f} MB / {total_mb:.2f} MB\n"
                f"╰──────────────────╯\n\n"
                f"**__Powered by Team SPY__**"
            )
        except Exception:
            pass
        progress_callback._last_update = current_time
