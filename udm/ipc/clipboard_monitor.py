"""
Clipboard monitor - watches clipboard for URLs and offers to download them.
"""

import re
import logging
from typing import Optional, Callable

from PyQt6.QtCore import QTimer

logger = logging.getLogger("udm.ipc.clipboard")

URL_PATTERN = re.compile(
    r'https?://[^\s<>"{}|\\^`\[\]]+\.[^\s<>"{}|\\^`\[\]]+',
    re.IGNORECASE,
)


class ClipboardMonitor:
    """
    Monitors the system clipboard for URLs.
    When a URL is detected, calls the on_url callback.
    """

    def __init__(
        self,
        clipboard,
        on_url: Optional[Callable] = None,
        interval_ms: int = 1500,
    ):
        self.clipboard = clipboard
        self.on_url = on_url
        self._last_text = ""
        self._enabled = False

        self._timer = QTimer()
        self._timer.timeout.connect(self._check_clipboard)
        self._interval = interval_ms

    def start(self):
        """Start monitoring the clipboard."""
        self._enabled = True
        self._last_text = self.clipboard.text() if self.clipboard else ""
        self._timer.start(self._interval)
        logger.info("Clipboard monitor started")

    def stop(self):
        """Stop monitoring the clipboard."""
        self._enabled = False
        self._timer.stop()
        logger.info("Clipboard monitor stopped")

    def _check_clipboard(self):
        """Check if clipboard contains a new URL."""
        if not self._enabled or not self.clipboard:
            return

        text = self.clipboard.text().strip()
        if text == self._last_text:
            return

        self._last_text = text

        # Check if it's a URL
        match = URL_PATTERN.match(text)
        if match:
            url = match.group(0)
            logger.info(f"URL detected in clipboard: {url}")
            if self.on_url:
                self.on_url(url)

    @property
    def enabled(self) -> bool:
        return self._enabled
