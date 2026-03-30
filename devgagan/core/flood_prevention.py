"""
FloodWait Prevention System - Proactive Rate Limiting

Instead of waiting AFTER FloodWait (reactive), this prevents FloodWait
from happening in the first place by tracking request patterns.

Rules:
1. Track all API requests per time window
2. If approaching limit → add pre-emptive delay BEFORE request
3. Conservative base delays, gradual increase only if needed
"""

import time
import asyncio
import logging
from collections import deque
from config import INTER_FILE_DELAY

logger = logging.getLogger(__name__)


class FloodWaitPreventor:
    """
    Proactive rate limiter that prevents FloodWait errors.

    Usage:
        preventor = FloodWaitPreventor()

        # Before any API call (download, get_messages, etc.)
        await preventor.before_request()

        # After successful API call
        preventor.after_request()

        # When FloodWait DOES occur (rare with prevention)
        preventor.on_flood_wait(wait_seconds)
    """

    def __init__(self):
        # Request tracking - sliding window
        self._request_times = deque(maxlen=100)  # Keep last 100 timestamps

        # Rate limiting config
        self._window_seconds = 30          # Check requests in last 30 seconds
        self._max_requests_per_window = 25 # Telegram limit ~30/sec, safe at 25

        # Delay settings (conservative start)
        self._base_delay = 1.5             # Start with 1.5s delay
        self._min_delay = 0.5              # Never below 0.5s
        self._max_delay = 5.0              # Never above 5s

        # Dynamic delay (adjusts based on conditions)
        self._current_delay = self._base_delay

        # Stats
        self._total_requests = 0
        self._flood_waits = 0
        self._last_flood_time = 0

        # Lock for thread safety
        self._lock = asyncio.Lock()

    def _clean_old_requests(self) -> int:
        """Remove requests older than window, return count in window"""
        now = time.time()
        cutoff = now - self._window_seconds

        # Count valid requests
        valid_count = 0
        while self._request_times and self._request_times[0] < cutoff:
            self._request_times.popleft()

        return len(self._request_times)

    def _current_utilization(self) -> float:
        """Returns 0.0 to 1.0+ showing how close to limit we are"""
        count = len(self._request_times)
        return count / self._max_requests_per_window

    async def before_request(self) -> None:
        """
        MUST be called BEFORE any Telegram API request.
        Adds delay if we're approaching the rate limit.
        """
        async with self._lock:
            current_count = self._clean_old_requests()
            utilization = current_count / self._max_requests_per_window

            # If we're at 80%+ utilization, add pre-emptive delay
            if utilization >= 0.8:
                # Delay proportional to how close we are
                delay = self._current_delay * (utilization - 0.7) * 2
                delay = max(self._min_delay, min(self._max_delay, delay))

                logger.debug(f"⏳ Flood prevention: waiting {delay:.1f}s (utilization: {utilization:.0%})")
                await asyncio.sleep(delay)

            # Add this request's timestamp
            self._request_times.append(time.time())
            self._total_requests += 1

    def after_request(self) -> None:
        """
        Call after successful API request.
        If things are smooth, gradually reduce delay.
        """
        current_count = len(self._request_times)
        utilization = current_count / self._max_requests_per_window

        # If we're well under limit, slowly reduce delay
        if utilization < 0.5 and self._current_delay > self._base_delay:
            self._current_delay = max(
                self._base_delay,
                self._current_delay * 0.95
            )

    def on_flood_wait(self, wait_seconds: int) -> None:
        """
        Call when FloodWait DOES occur (rare with prevention).
        Increases delay to be more conservative.
        """
        self._flood_waits += 1
        self._last_flood_time = time.time()

        # Aggressive backoff
        if wait_seconds > 30:
            self._current_delay = min(self._max_delay, self._current_delay * 3)
        elif wait_seconds > 10:
            self._current_delay = min(self._max_delay, self._current_delay * 2)
        else:
            self._current_delay = min(self._max_delay, self._current_delay * 1.5)

        logger.warning(f"🔴 FloodWait({wait_seconds}s) → prevention delay increased to {self._current_delay:.1f}s")

    def reset(self) -> None:
        """Reset between batches"""
        self._request_times.clear()
        self._current_delay = self._base_delay
        self._total_requests = 0
        logger.info(f"🔄 Flood prevention reset. Total requests: {self._total_requests}, FloodWaits: {self._flood_waits}")

    def get_stats(self) -> dict:
        """Get current prevention stats"""
        return {
            "current_utilization": f"{self._current_utilization():.0%}",
            "requests_in_window": len(self._request_times),
            "max_requests": self._max_requests_per_window,
            "current_delay": f"{self._current_delay:.1f}s",
            "total_requests": self._total_requests,
            "flood_waits": self._flood_waits
        }


# Global instance - use same preventor across all API calls
flood_preventor = FloodWaitPreventor()
