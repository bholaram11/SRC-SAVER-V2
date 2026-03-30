"""
Upload Queue System - Ordered Concurrent Upload Pipeline

Rules:
1. If pending downloaded files > 3 → allow 2 parallel uploads
2. Sequence preserved → File N+1 waits for File N to finish sending
3. If pending >= 7 OR total size > 2GB → PAUSE downloads until pending <= 3
"""

import asyncio
import os
import logging
import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field
from config import MAX_PARALLEL_UPLOADS, MAX_PENDING_FILES, MAX_PENDING_SIZE_GB

logger = logging.getLogger(__name__)


@dataclass
class PendingFile:
    """Tracks a single pending file in the queue."""
    file_path: str
    file_size: int
    order: int
    downloaded_at: float = field(default_factory=time.time)


class UploadQueue:
    """
    Manages ordered concurrent uploads with download throttling.
    
    Flow:
    1. Before download → wait_for_download_slot() blocks if too many pending
    2. After download → register_file() adds file to queue, returns order number
    3. Upload task → acquire_upload_slot() limits parallel uploads
    4. Before send → wait_for_send_turn() ensures ordering
    5. After send → mark_sent() signals next file and checks if downloads can resume
    """

    def __init__(self):
        # Concurrency control
        self._upload_semaphore = asyncio.Semaphore(MAX_PARALLEL_UPLOADS)
        
        # Download throttling (backpressure)
        self._download_gate = asyncio.Event()
        self._download_gate.set()  # Initially open
        
        # Pending file tracking
        self._pending_files: Dict[int, PendingFile] = {}
        self._pending_lock = asyncio.Lock()
        
        # Sequence ordering
        self._next_order = 0          # Next order number to assign
        self._next_send_order = 0     # Next order number allowed to send
        self._send_events: Dict[int, asyncio.Event] = {}
        self._order_lock = asyncio.Lock()
        
        # Thresholds
        self.max_pending_count = MAX_PENDING_FILES       # Default: 7
        self.max_pending_size = int(MAX_PENDING_SIZE_GB * 1024**3)  # Default: 2GB
        self.resume_threshold = 3                         # Resume downloads when pending <= 3
        self.parallel_trigger = 3                         # Start 2x uploads when pending > 3
        
        # Stats
        self._total_processed = 0
        self._total_bytes_uploaded = 0

    @property
    def pending_count(self) -> int:
        return len(self._pending_files)

    @property
    def pending_size(self) -> int:
        return sum(f.file_size for f in self._pending_files.values())

    @property
    def is_download_paused(self) -> bool:
        return not self._download_gate.is_set()

    async def wait_for_download_slot(self) -> None:
        """
        Called BEFORE downloading a file.
        Blocks if pending files >= max_pending_count OR total size > max_pending_size.
        Resumes when pending drops to resume_threshold.
        """
        await self._download_gate.wait()

    async def register_file(self, file_path: str, file_size: int) -> int:
        """
        Called AFTER downloading a file.
        Registers it in the queue, assigns an order number, and checks thresholds.
        
        Returns: order number for sequence tracking
        """
        async with self._order_lock:
            order = self._next_order
            self._next_order += 1
            
            # Create send event for this order
            self._send_events[order] = asyncio.Event()
            
            # If this is the first file (order 0), it can send immediately
            if order == self._next_send_order:
                self._send_events[order].set()

        async with self._pending_lock:
            self._pending_files[order] = PendingFile(
                file_path=file_path,
                file_size=file_size,
                order=order
            )
            
            # Check if we need to pause downloads
            if self.pending_count >= self.max_pending_count or self.pending_size >= self.max_pending_size:
                self._download_gate.clear()
                logger.warning(
                    f"⏸️ Download PAUSED: {self.pending_count} files pending "
                    f"({self.pending_size / (1024**2):.0f}MB). "
                    f"Will resume at {self.resume_threshold} pending."
                )

        logger.info(f"📋 File registered: order={order}, size={file_size/(1024**2):.1f}MB, pending={self.pending_count}")
        return order

    async def acquire_upload_slot(self) -> None:
        """
        Called before starting upload.
        Limits concurrent uploads via semaphore.
        """
        await self._upload_semaphore.acquire()

    def release_upload_slot(self) -> None:
        """Release the upload semaphore after upload is done."""
        self._upload_semaphore.release()

    async def wait_for_send_turn(self, order: int) -> None:
        """
        Called AFTER uploading to Telegram servers but BEFORE sending to target chat.
        Blocks until all previous files have been sent.
        
        This is the KEY to sequence preservation:
        - File N+1 can upload in parallel (slow part done)
        - But it MUST wait here until File N has been sent to chat
        """
        event = self._send_events.get(order)
        if event:
            logger.info(f"⏳ File order={order} waiting for send turn (next={self._next_send_order})")
            await event.wait()
            logger.info(f"✅ File order={order} got send turn!")

    async def mark_sent(self, order: int) -> None:
        """
        Called AFTER file has been sent to target chat.
        Signals the next file in sequence and checks if downloads can resume.
        """
        # Acquire locks in a consistent order (order -> pending) to prevent deadlocks.
        async with self._order_lock:
            # Clean up this event
            self._send_events.pop(order, None)
            
            # Advance send order and signal next file
            if order == self._next_send_order:
                self._next_send_order = order + 1
                next_event = self._send_events.get(self._next_send_order)
                if next_event:
                    next_event.set()
                    logger.info(f"🔔 Signaled file order={self._next_send_order} to send")

        async with self._pending_lock:
            # Remove from pending
            pending_file = self._pending_files.pop(order, None)
            if pending_file:
                self._total_processed += 1
                self._total_bytes_uploaded += pending_file.file_size
            
            # Check if downloads can resume (must be done under the same lock as pop)
            if self.is_download_paused and self.pending_count <= self.resume_threshold:
                self._download_gate.set()
                logger.info(
                    f"▶️ Download RESUMED: {self.pending_count} files pending. "
                    f"Total processed: {self._total_processed}"
                )
    async def cancel_file(self, order: int) -> None:
        """
        Called when a file upload fails or is cancelled.
        Must still signal next file to prevent queue deadlock.
        """
        # Acquire locks in a consistent order (order -> pending) to prevent deadlocks.
        async with self._order_lock:
            self._send_events.pop(order, None)
            
            # Still advance send order to prevent deadlock
            if order == self._next_send_order:
                self._next_send_order = order + 1
                next_event = self._send_events.get(self._next_send_order)
                if next_event:
                    next_event.set()

        async with self._pending_lock:
            self._pending_files.pop(order, None)
            # Check if downloads can resume
            if self.is_download_paused and self.pending_count <= self.resume_threshold:
                self._download_gate.set()

    def reset(self) -> None:
        """Reset the queue state. Called on batch complete or force stop."""
        self._pending_files.clear()
        self._send_events.clear()
        self._next_order = 0
        self._next_send_order = 0
        self._download_gate.set()
        # Reset semaphore by creating new one
        self._upload_semaphore = asyncio.Semaphore(MAX_PARALLEL_UPLOADS)
        logger.info(f"🔄 Upload queue reset. Stats: {self._total_processed} files, {self._total_bytes_uploaded/(1024**3):.2f}GB total")

    def get_status(self) -> dict:
        """Get current queue status for display."""
        return {
            "pending_count": self.pending_count,
            "pending_size_mb": round(self.pending_size / (1024**2), 1),
            "downloads_paused": self.is_download_paused,
            "next_send_order": self._next_send_order,
            "total_processed": self._total_processed,
            "total_uploaded_gb": round(self._total_bytes_uploaded / (1024**3), 2)
        }
