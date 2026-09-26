"""
Download state machine - enforces valid state transitions.
"""

import logging
from typing import Optional
from udm.core.segment import DownloadStatus

logger = logging.getLogger("udm.queue.state_machine")

# Valid state transitions map
VALID_TRANSITIONS = {
    DownloadStatus.QUEUED: {
        DownloadStatus.DOWNLOADING,
        DownloadStatus.PAUSED,  # user can pause before it starts
    },
    DownloadStatus.DOWNLOADING: {
        DownloadStatus.PAUSED,
        DownloadStatus.COMPLETED,
        DownloadStatus.MERGING,
        DownloadStatus.ERROR,
    },
    DownloadStatus.PAUSED: {
        DownloadStatus.QUEUED,  # re-queue
        DownloadStatus.DOWNLOADING,
    },
    DownloadStatus.MERGING: {
        DownloadStatus.COMPLETED,
        DownloadStatus.ERROR,
    },
    DownloadStatus.ERROR: {
        DownloadStatus.QUEUED,
        DownloadStatus.DOWNLOADING,
    },
    DownloadStatus.COMPLETED: set(),  # terminal state
}


class StateMachine:
    """
    Enforces valid download state transitions.
    Emits transition events that UI can subscribe to.
    """

    def __init__(self):
        self._listeners = []

    def add_listener(self, callback):
        """Add a listener that gets called on state transitions.
        callback(download_id, old_status, new_status)
        """
        self._listeners.append(callback)

    def can_transition(
        self, current: DownloadStatus, target: DownloadStatus
    ) -> bool:
        """Check if a state transition is valid."""
        valid = VALID_TRANSITIONS.get(current, set())
        return target in valid

    def transition(
        self,
        download_id: str,
        current: DownloadStatus,
        target: DownloadStatus,
    ) -> bool:
        """
        Attempt a state transition.
        Returns True if transition was valid and applied.
        """
        if not self.can_transition(current, target):
            logger.warning(
                f"Invalid transition for {download_id}: "
                f"{current.value} → {target.value}"
            )
            return False

        logger.debug(
            f"State transition {download_id}: "
            f"{current.value} → {target.value}"
        )

        # Notify listeners
        for listener in self._listeners:
            try:
                listener(download_id, current, target)
            except Exception as e:
                logger.error(f"State listener error: {e}")

        return True
