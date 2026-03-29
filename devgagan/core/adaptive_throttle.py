"""
Adaptive Throttle - Smart inter-file delay that adjusts based on conditions.

Instead of a fixed INTER_FILE_DELAY, this system:
1. Starts with a base delay
2. INCREASES delay when FloodWait is detected (exponential backoff)
3. DECREASES delay when things are smooth (gradual cooldown)
4. Adjusts based on file size (big file upload = less delay needed)
5. Never goes below a minimum floor
"""

import time
import logging
from config import INTER_FILE_DELAY

logger = logging.getLogger(__name__)


class AdaptiveThrottle:
    """
    Smart delay calculator that adapts to Telegram API behavior.
    
    Usage:
        throttle = AdaptiveThrottle()
        
        # After each file upload:
        delay = throttle.get_delay(file_size_bytes)
        await asyncio.sleep(delay)
        
        # When FloodWait happens:
        throttle.report_flood_wait(seconds)
        
        # Reset between batches:
        throttle.reset()
    """

    def __init__(self):
        # Base delay from config (default 3s) - this is the starting point
        self.base_delay = INTER_FILE_DELAY
        
        # Bounds
        self.min_delay = 1.0       # Never go below 1 second
        self.max_delay = 30.0      # Never go above 30 seconds
        
        # Current state
        self._current_delay = float(self.base_delay)
        self._last_flood_time = 0.0
        self._flood_count = 0      # Number of FloodWaits in current session
        self._success_streak = 0   # Consecutive successful uploads without FloodWait
        
        # Tuning knobs
        self._flood_multiplier = 2.0    # How much to multiply delay on FloodWait
        self._cooldown_factor = 0.85    # How much to reduce delay per successful file
        self._cooldown_after = 5        # Start reducing delay after N successful files
        
        # File size thresholds (bytes)
        self._small_file = 10 * 1024 * 1024     # < 10MB
        self._medium_file = 100 * 1024 * 1024   # < 100MB
        self._large_file = 500 * 1024 * 1024    # < 500MB

    def get_delay(self, file_size_bytes: int = 0) -> float:
        """
        Calculate the optimal delay before processing the next file.
        
        Args:
            file_size_bytes: Size of the file that was just uploaded.
                             Larger files = less delay needed (upload itself was slow).
        
        Returns:
            Delay in seconds (float)
        """
        delay = self._current_delay
        
        # === FILE SIZE ADJUSTMENT ===
        # Big files took longer to upload → API had rest time → less delay needed
        # Small files uploaded fast → API got hammered → more delay needed
        if file_size_bytes > 0:
            if file_size_bytes >= self._large_file:
                # 500MB+ file: upload took minutes, API is rested
                delay *= 0.3
            elif file_size_bytes >= self._medium_file:
                # 100-500MB file: significant upload time
                delay *= 0.5
            elif file_size_bytes >= self._small_file:
                # 10-100MB file: moderate upload time
                delay *= 0.7
            else:
                # <10MB file: uploaded instantly, need full delay
                delay *= 1.2
        
        # === RECENT FLOOD CHECK ===
        # If FloodWait happened in last 2 minutes, keep delay elevated
        time_since_flood = time.time() - self._last_flood_time
        if self._last_flood_time > 0 and time_since_flood < 120:
            # Closer to the FloodWait = more cautious
            flood_urgency = max(0.0, 1.0 - (time_since_flood / 120))
            delay += delay * flood_urgency * 0.5
        
        # === SUCCESS STREAK COOLDOWN ===
        # If many files went through without FloodWait, gradually reduce
        if self._success_streak >= self._cooldown_after:
            streak_bonus = min(self._success_streak - self._cooldown_after, 20)
            reduction = (self._cooldown_factor ** streak_bonus)
            delay *= reduction
        
        # === CLAMP ===
        delay = max(self.min_delay, min(self.max_delay, delay))
        
        # Track success
        self._success_streak += 1
        
        logger.debug(
            f"⏱️ Adaptive delay: {delay:.1f}s "
            f"(base={self._current_delay:.1f}, streak={self._success_streak}, "
            f"floods={self._flood_count}, size={file_size_bytes/(1024*1024):.0f}MB)"
        )
        
        return round(delay, 1)

    def report_flood_wait(self, wait_seconds: int) -> None:
        """
        Called when a FloodWait error is received.
        Increases the base delay using exponential backoff.
        
        Args:
            wait_seconds: The FloodWait duration from Telegram
        """
        self._last_flood_time = time.time()
        self._flood_count += 1
        self._success_streak = 0  # Reset streak
        
        # Exponential backoff: double the delay, but cap based on FloodWait severity
        old_delay = self._current_delay
        
        if wait_seconds > 60:
            # Severe FloodWait (>1min): aggressive backoff
            self._current_delay = min(self.max_delay, self._current_delay * 3)
        elif wait_seconds > 15:
            # Moderate FloodWait: standard backoff
            self._current_delay = min(self.max_delay, self._current_delay * self._flood_multiplier)
        else:
            # Light FloodWait (<15s): gentle increase
            self._current_delay = min(self.max_delay, self._current_delay * 1.5)
        
        logger.warning(
            f"🔴 FloodWait({wait_seconds}s) → delay increased: "
            f"{old_delay:.1f}s → {self._current_delay:.1f}s "
            f"(total floods: {self._flood_count})"
        )

    def report_success(self) -> None:
        """Called after a successful operation (no FloodWait)."""
        # Gradual cooldown: after enough successes, start reducing base delay
        if self._success_streak >= self._cooldown_after * 2:
            # Only reduce base delay if we've had a long streak of successes
            old = self._current_delay
            self._current_delay = max(
                float(self.base_delay) * 0.5,  # Never go below half of original config
                self._current_delay * 0.95
            )
            if old != self._current_delay:
                logger.info(f"🟢 Delay cooldown: {old:.1f}s → {self._current_delay:.1f}s (streak={self._success_streak})")

    def reset(self) -> None:
        """Reset to initial state. Called between batches."""
        logger.info(
            f"🔄 Throttle reset. Session stats: {self._flood_count} floods, "
            f"final delay was {self._current_delay:.1f}s"
        )
        self._current_delay = float(self.base_delay)
        self._last_flood_time = 0.0
        self._flood_count = 0
        self._success_streak = 0

    def get_stats(self) -> dict:
        """Get current throttle stats for display."""
        return {
            "current_delay": round(self._current_delay, 1),
            "base_delay": self.base_delay,
            "flood_count": self._flood_count,
            "success_streak": self._success_streak,
            "time_since_flood": round(time.time() - self._last_flood_time, 0) if self._last_flood_time > 0 else None
        }
