"""
Download scheduler - schedule downloads to start/stop at specific times.
"""

import logging
from datetime import datetime, time as dt_time
from typing import Optional, Callable

logger = logging.getLogger("udm.queue.scheduler")


class Scheduler:
    """
    Simple download scheduler.
    
    Supports:
    - Start queue at a specific time
    - Stop queue at a specific time  
    - Shutdown after queue completes
    """

    def __init__(self):
        self.enabled = False
        self.start_time: Optional[dt_time] = None
        self.stop_time: Optional[dt_time] = None
        self.shutdown_after_complete = False
        self._on_start: Optional[Callable] = None
        self._on_stop: Optional[Callable] = None
        self._timer_task = None

    def configure(
        self,
        enabled: bool = False,
        start_time: Optional[str] = None,
        stop_time: Optional[str] = None,
        shutdown_after_complete: bool = False,
    ):
        """
        Configure the scheduler.
        
        Args:
            enabled: Whether scheduling is active.
            start_time: Time to start queue (format "HH:MM").
            stop_time: Time to stop queue (format "HH:MM").
            shutdown_after_complete: Shutdown PC after all downloads complete.
        """
        self.enabled = enabled
        if start_time:
            h, m = map(int, start_time.split(":"))
            self.start_time = dt_time(h, m)
        if stop_time:
            h, m = map(int, stop_time.split(":"))
            self.stop_time = dt_time(h, m)
        self.shutdown_after_complete = shutdown_after_complete

    def set_callbacks(
        self,
        on_start: Optional[Callable] = None,
        on_stop: Optional[Callable] = None,
    ):
        """Set callbacks for start/stop events."""
        self._on_start = on_start
        self._on_stop = on_stop

    def is_within_schedule(self) -> bool:
        """Check if the current time is within the scheduled download window."""
        if not self.enabled or not self.start_time or not self.stop_time:
            return True  # No schedule = always allowed

        now = datetime.now().time()

        if self.start_time <= self.stop_time:
            return self.start_time <= now <= self.stop_time
        else:
            # Overnight schedule (e.g., 22:00 - 06:00)
            return now >= self.start_time or now <= self.stop_time

    @property
    def status_text(self) -> str:
        """Human-readable scheduler status."""
        if not self.enabled:
            return "Scheduler: Off"
        parts = []
        if self.start_time:
            parts.append(f"Start: {self.start_time.strftime('%H:%M')}")
        if self.stop_time:
            parts.append(f"Stop: {self.stop_time.strftime('%H:%M')}")
        return "Scheduler: " + " | ".join(parts)
