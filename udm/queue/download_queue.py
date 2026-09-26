"""
Download queue manager with priority support and concurrent download limiting.
"""

import asyncio
import logging
import time
from typing import Optional, Callable, List, Dict

from udm.core.segment import DownloadTask, DownloadStatus
from udm.core.download_engine import DownloadEngine
from udm.queue.state_machine import StateMachine
from udm.storage.database import Database

logger = logging.getLogger("udm.queue")


class DownloadQueue:
    """
    Manages the download queue with:
    - Configurable max concurrent downloads
    - Priority ordering
    - Auto-start next queued download when slot opens
    - Persistence via SQLite database
    """

    def __init__(
        self,
        engine: DownloadEngine,
        database: Database,
        max_concurrent: int = 3,
    ):
        self.engine = engine
        self.database = database
        self.max_concurrent = max_concurrent
        self.state_machine = StateMachine()

        # Task registry
        self._tasks: Dict[str, DownloadTask] = {}

        # UI callbacks
        self._on_progress: Optional[Callable] = None
        self._on_complete: Optional[Callable] = None
        self._on_error: Optional[Callable] = None
        self._on_queue_changed: Optional[Callable] = None

    def set_callbacks(
        self,
        on_progress: Optional[Callable] = None,
        on_complete: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        on_queue_changed: Optional[Callable] = None,
    ):
        """Set UI callback functions."""
        self._on_progress = on_progress
        self._on_complete = on_complete
        self._on_error = on_error
        self._on_queue_changed = on_queue_changed

    async def load_from_db(self):
        """Load all downloads from database on startup."""
        tasks = await self.database.get_all_downloads()
        for task in tasks:
            self._tasks[task.id] = task
            # Reset any downloads that were active when app closed
            if task.status == DownloadStatus.DOWNLOADING:
                task.status = DownloadStatus.PAUSED
                await self.database.save_download(task)
        logger.info(f"Loaded {len(tasks)} downloads from database")

    async def add_download(
        self,
        task: DownloadTask,
        start_immediately: bool = True,
    ) -> DownloadTask:
        """
        Add a new download to the queue.
        
        Args:
            task: The prepared DownloadTask.
            start_immediately: If True and slots available, start right away.
        
        Returns:
            The added DownloadTask.
        """
        self._tasks[task.id] = task
        await self.database.save_download(task)

        logger.info(f"Added to queue: {task.filename} ({task.id})")

        if start_immediately:
            await self._try_start_next()

        if self._on_queue_changed:
            self._on_queue_changed()

        return task

    async def _try_start_next(self):
        """Start the next queued download if a slot is available."""
        active_count = sum(
            1 for t in self._tasks.values()
            if t.status == DownloadStatus.DOWNLOADING
        )

        if active_count >= self.max_concurrent:
            return

        # Find next queued task (highest priority first, then FIFO)
        queued = [
            t for t in self._tasks.values()
            if t.status == DownloadStatus.QUEUED
        ]
        queued.sort(key=lambda t: (-t.priority, t.created_at))

        for task in queued:
            if active_count >= self.max_concurrent:
                break
            await self._start_task(task)
            active_count += 1

    async def _start_task(self, task: DownloadTask):
        """Start a specific download task."""
        logger.info(f"Starting download: {task.filename}")
        await self.engine.start_download(
            task,
            on_progress=self._handle_progress,
            on_complete=self._handle_complete,
            on_error=self._handle_error,
        )

    def _handle_progress(self, task: DownloadTask):
        """Handle progress update from engine."""
        self._tasks[task.id] = task
        if self._on_progress:
            self._on_progress(task)

    def _handle_complete(self, task: DownloadTask):
        """Handle download completion."""
        self._tasks[task.id] = task
        if self._on_complete:
            self._on_complete(task)
        # Save to DB
        asyncio.create_task(self.database.save_download(task))
        # Start next queued download
        asyncio.create_task(self._try_start_next())

        if self._on_queue_changed:
            self._on_queue_changed()

    def _handle_error(self, task: DownloadTask, error_msg: str):
        """Handle download error."""
        self._tasks[task.id] = task
        if self._on_error:
            self._on_error(task, error_msg)
        asyncio.create_task(self.database.save_download(task))
        # Try starting next
        asyncio.create_task(self._try_start_next())

    async def pause_download(self, download_id: str):
        """Pause a download."""
        task = self._tasks.get(download_id)
        if not task:
            return

        if self.state_machine.can_transition(task.status, DownloadStatus.PAUSED):
            await self.engine.pause_download(download_id)
            task.status = DownloadStatus.PAUSED
            await self.database.save_download(task)
            if self._on_queue_changed:
                self._on_queue_changed()

    async def resume_download(self, download_id: str):
        """Resume a paused download."""
        task = self._tasks.get(download_id)
        if not task:
            return

        if task.status in (DownloadStatus.PAUSED, DownloadStatus.ERROR):
            task.status = DownloadStatus.QUEUED
            await self.database.save_download(task)
            await self._try_start_next()
            if self._on_queue_changed:
                self._on_queue_changed()

    async def cancel_download(self, download_id: str):
        """Cancel and remove a download."""
        task = self._tasks.get(download_id)
        if not task:
            return

        await self.engine.cancel_download(download_id)
        await self.database.delete_download(download_id)
        del self._tasks[download_id]

        # Start next queued
        await self._try_start_next()
        if self._on_queue_changed:
            self._on_queue_changed()

    async def pause_all(self):
        """Pause all active downloads."""
        active = [
            t for t in self._tasks.values()
            if t.status == DownloadStatus.DOWNLOADING
        ]
        for task in active:
            await self.pause_download(task.id)

    async def resume_all(self):
        """Resume all paused downloads."""
        paused = [
            t for t in self._tasks.values()
            if t.status == DownloadStatus.PAUSED
        ]
        for task in paused:
            await self.resume_download(task.id)

    def get_task(self, download_id: str) -> Optional[DownloadTask]:
        """Get a download task by ID."""
        return self._tasks.get(download_id)

    def get_all_tasks(self) -> List[DownloadTask]:
        """Get all download tasks, sorted by creation time (newest first)."""
        return sorted(
            self._tasks.values(),
            key=lambda t: t.created_at,
            reverse=True,
        )

    def get_tasks_by_status(self, status: DownloadStatus) -> List[DownloadTask]:
        """Get downloads filtered by status."""
        return [t for t in self._tasks.values() if t.status == status]

    def get_tasks_by_category(self, category: str) -> List[DownloadTask]:
        """Get downloads filtered by category."""
        return [t for t in self._tasks.values() if t.category.value == category]

    async def clear_completed(self):
        """Remove all completed downloads from the queue and database."""
        completed_ids = [
            tid for tid, t in self._tasks.items()
            if t.status == DownloadStatus.COMPLETED
        ]
        for tid in completed_ids:
            del self._tasks[tid]

        await self.database.clear_completed()
        logger.info(f"Cleared {len(completed_ids)} completed downloads")

        if self._on_queue_changed:
            self._on_queue_changed()

    @property
    def active_count(self) -> int:
        return sum(
            1 for t in self._tasks.values()
            if t.status == DownloadStatus.DOWNLOADING
        )

    @property
    def total_speed(self) -> float:
        return sum(
            t.speed for t in self._tasks.values()
            if t.status == DownloadStatus.DOWNLOADING
        )
