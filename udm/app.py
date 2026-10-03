"""
UDM Application - Main entry point.
Initializes all components and starts the application.
"""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from udm.core.segment import DownloadTask, DownloadStatus, Segment, SegmentStatus, detect_category

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

from udm.core.download_engine import DownloadEngine
from udm.core.speed_limiter import SpeedLimiter
from udm.storage.database import Database
from udm.storage.config import Config
from udm.queue.download_queue import DownloadQueue
from udm.queue.scheduler import Scheduler
from udm.ipc.ws_server import WebSocketServer
from udm.ipc.clipboard_monitor import ClipboardMonitor
from udm.ui.main_window import MainWindow

logger = logging.getLogger("udm")


class UDMApp:
    """
    Main UDM application class.
    Coordinates all subsystems: engine, queue, database, UI, IPC.
    """

    def __init__(self):
        self.config = Config()
        self.database = Database()
        self.speed_limiter = SpeedLimiter(
            self.config.get("speed.global_limit_bytes_per_sec", 0)
        )
        self.engine = DownloadEngine(
            speed_limiter=self.speed_limiter,
            temp_dir=self.config.get("general.temp_dir"),
            default_save_dir=self.config.get("general.default_save_dir"),
            category_dirs=self.config.get("categories", {}),
        )
        self.queue = DownloadQueue(
            engine=self.engine,
            database=self.database,
            max_concurrent=self.config.get("download.max_concurrent_downloads", 3),
        )
        self.scheduler = Scheduler()
        self.ws_server = WebSocketServer(
            port=self.config.get("browser.ws_port", 19615),
            token=self.config.get("security.pairing_token", ""),
            on_download=self._on_extension_download,
            on_video_download=self._on_extension_video_download,
            on_video_formats=self._on_extension_video_formats,
            on_show=self._on_show_request,
        )

        # Qt Application
        self.qt_app = QApplication(sys.argv)
        self.qt_app.setApplicationName("UDM")
        self.qt_app.setApplicationDisplayName("UDM — Ultimate Download Manager")

        # Main window
        self.window = MainWindow(self.config)
        self.window.set_queue(self.queue)

        # Clipboard monitor
        self.clipboard_monitor = ClipboardMonitor(
            clipboard=self.qt_app.clipboard(),
            on_url=self._on_clipboard_url,
        )

        # asyncio event loop integration with Qt
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        # Timer to process asyncio events
        self._async_timer = QTimer()
        self._async_timer.timeout.connect(self._process_async)
        self._async_timer.start(5)  # 5ms interval for faster async IO

    def _process_async(self):
        """Process pending asyncio events (integrates asyncio with Qt event loop)."""
        self._loop.stop()
        self._loop.run_forever()

    def _on_show_request(self):
        """Called when another instance tries to launch."""
        # Use Qt's event loop to safely interact with UI
        QTimer.singleShot(0, self.window._show_from_tray)

    async def _initialize(self):
        """Async initialization of all components."""
        # Initialize database
        await self.database.initialize()

        # Load existing downloads
        await self.queue.load_from_db()

        # Set up queue callbacks
        self.queue.set_callbacks(
            on_progress=self.window.on_progress,
            on_complete=self.window.on_complete,
            on_error=self.window.on_error,
            on_queue_changed=self.window.on_queue_changed,
        )

        # Load existing downloads into UI
        tasks = self.queue.get_all_tasks()
        self.window.load_existing_downloads(tasks)

        # Start WebSocket server for browser extension
        await self.ws_server.start()

        # Start clipboard monitor if enabled
        if self.config.get("browser.clipboard_monitor", True):
            self.clipboard_monitor.start()

        # Configure scheduler
        self.scheduler.configure(
            enabled=self.config.get("scheduler.enabled", False),
            start_time=self.config.get("scheduler.start_time"),
            stop_time=self.config.get("scheduler.stop_time"),
        )

        logger.info("UDM initialized successfully")

    def _show_extension_dialog(self, data: dict):
        """Show the Add Download dialog on the main UI thread."""
        from udm.ui.download_dialog import DownloadDialog
        dialog = DownloadDialog(
            self.window,
            url=data.get("url", ""),
            filename=data.get("filename", ""),
            save_dir=self.config.get("general.default_save_dir", ""),
            cookies=data.get("cookies", ""),
            referrer=data.get("referrer", ""),
            user_agent=data.get("user_agent", ""),
        )
        dialog.download_requested.connect(self.window._start_new_download)
        
        # Bring window to foreground and show dialog
        self.window._show_from_tray()
        dialog.exec()

    async def _on_extension_download(self, data: dict) -> tuple[bool, str]:
        """
        Handle a download request from the browser extension.

        Returns (success, message). The extension waits for this before
        deciding whether to erase its own copy of the download — so this
        must only report success once we've actually confirmed the file is
        real and queued, not just "message received". We deliberately do
        NOT wait for the full download to finish here, only for the quick
        probe + queue-add, so the extension isn't stuck waiting minutes for
        a large file.
        """
        try:
            url = data.get("url", "")
            if not url:
                return False, "No URL provided"

            if data.get("auto_start", False):
                task = await self.engine.prepare_download(
                    url=url,
                    filename=data.get("filename"),
                    cookies=data.get("cookies"),
                    referrer=data.get("referrer"),
                    user_agent=data.get("user_agent"),
                )
                await self.queue.add_download(task, start_immediately=True)
                self.window.on_queue_changed()
                self.window.tray.show_message("UDM Download Started", f"Downloading: {task.filename}")
                return True, f"Downloading: {task.filename}"
            else:
                # Schedule UI update on the Qt main loop thread
                QTimer.singleShot(0, lambda: self._show_extension_dialog(data))
                return True, "Opened Add Download dialog"

        except Exception as e:
            logger.error(f"Failed to handle extension download: {e}")
            return False, str(e)

    async def _on_extension_video_formats(self, data: dict) -> tuple[bool, str, dict]:
        """List the real qualities available for a video, for the extension's
        quality picker. Returns (success, message, {"options": [...]})."""
        url = data.get("url", "")
        if not url:
            return False, "No URL provided", {}

        try:
            from udm.video.grabber import VideoGrabber
        except Exception as e:
            return False, f"Video module unavailable: {e}", {}

        grabber = VideoGrabber()
        if not grabber.is_available:
            return False, "yt-dlp is not installed", {}

        options = await grabber.get_quality_options(
            url,
            referrer=data.get("referrer"),
            cookies=data.get("cookies"),
            user_agent=data.get("user_agent"),
        )
        if not options:
            return False, grabber.last_error or "Could not list qualities", {}
        return True, f"{len(options)} qualities available", {"options": options}

    @staticmethod
    def _quality_to_format(quality) -> str:
        """Map the extension's quality choice to a yt-dlp format selector.
        Only "best", "audio", or a plain height number are accepted — never
        a raw selector string from the browser."""
        q = str(quality or "best").strip().lower()
        if q == "audio":
            return "bestaudio/best"
        if q.isdigit():
            h = int(q)
            return f"bestvideo[height<={h}]+bestaudio/best[height<={h}]"
        return "best"

    async def _on_extension_video_download(self, data: dict) -> tuple[bool, str]:
        """
        Handle a "download this video" request from the browser extension's
        stream sniffer (used for non-YouTube video/HLS detection).

        Previously this callback didn't exist at all — the extension's
        floating "Download this video" button sent a `video_download`
        message that nothing on this side ever handled. Now it resolves the
        real media URL via yt-dlp (the same mechanism that already works for
        YouTube) rather than treating a sniffed manifest/fragment URL as a
        plain file for the segmented HTTP engine, which can't assemble an
        HLS stream and would previously just save whatever tiny fragment or
        placeholder response it got.
        """
        url = data.get("url", "")
        if not url:
            return False, "No URL provided"

        try:
            from udm.video.grabber import VideoGrabber
        except Exception as e:
            return False, f"Video module unavailable: {e}"

        grabber = VideoGrabber()
        if not grabber.is_available:
            return False, "yt-dlp is not installed — video downloads are unavailable"

        referrer = data.get("referrer")
        cookies = data.get("cookies")
        user_agent = data.get("user_agent")

        info = await grabber.get_direct_url(
            url, "best", referrer=referrer, cookies=cookies, user_agent=user_agent
        )
        # IMPORTANT: only treat "yt-dlp couldn't resolve this at all" (info is
        # None) as failure. info.get("url") being empty is normal and
        # expected for the majority of real videos — anything needing
        # separate video+audio streams merged (which is how YouTube serves
        # almost everything above 720p, and how most HLS/DASH sites work)
        # has no single flat URL to report here. That merge happens inside
        # download_video() below, which previously never even got a chance
        # to run for exactly these videos.
        if not info:
            msg = grabber.last_error or "Could not resolve this video (unsupported page or blocked)"
            return False, msg

        # A slow-but-legitimate request could still be retried by an
        # impatient click before the fix above ever gets a chance to send
        # a reply (or on a flaky connection in general) — don't queue the
        # same video twice if one is already in flight for this exact URL.
        for existing in self.queue.get_all_tasks():
            if existing.url == url and existing.status in (
                DownloadStatus.DOWNLOADING, DownloadStatus.QUEUED,
            ):
                return True, f"Already downloading: {existing.filename}"

        # Audio-only downloads belong in Music, everything else in Video.
        folder_key = (
            "categories.Music"
            if str(data.get("quality") or "").lower() == "audio"
            else "categories.Video"
        )
        save_dir = self.config.get(
            folder_key, self.config.get("general.default_save_dir", "")
        )
        title = info.get("title") or data.get("filename") or "video"
        filename = info.get("filename") or f"{title}.mp4"
        known_size = int(info.get("filesize") or 0)

        # Register the row BEFORE the actual download starts — previously
        # nothing existed in the queue until yt-dlp finished entirely, so
        # UDM showed nothing at all while a video was downloading and only
        # revealed it once already complete. status=DOWNLOADING plus one
        # ACTIVE segment mirrors exactly what a normal in-progress
        # single-file download looks like, so the existing progress bar/row
        # rendering handles it without any special-casing.
        task = DownloadTask(
            url=url,
            filename=filename,
            save_path=save_dir,
            total_size=known_size,
            status=DownloadStatus.DOWNLOADING,
            category=detect_category(filename),
            referrer=referrer,
            user_agent=user_agent,
        )
        task.segments = [
            Segment(
                id=0,
                download_id=task.id,
                start_byte=0,
                end_byte=max(known_size - 1, 0),
                status=SegmentStatus.ACTIVE,
            )
        ]
        await self.queue.add_download(task, start_immediately=False)

        asyncio.create_task(
            self._run_video_download(
                task, url, save_dir, referrer, cookies, user_agent,
                self._quality_to_format(data.get("quality")),
            )
        )
        return True, f"Downloading: {title}"

    async def _run_video_download(
        self,
        task: DownloadTask,
        url: str,
        save_dir: str,
        referrer: Optional[str] = None,
        cookies: Optional[str] = None,
        user_agent: Optional[str] = None,
        format_selector: str = "best",
    ):
        """Run the actual yt-dlp video download in the background, updating
        `task` live as progress comes in. The row for `task` already exists
        (added by the caller before this runs), so on_progress only needs to
        refresh it, not create it."""
        from udm.video.grabber import VideoGrabber
        grabber = VideoGrabber()

        def _on_progress(p: dict):
            task.downloaded_size = int(p.get("downloaded_bytes") or 0)
            total = int(p.get("total_bytes") or 0)
            if total:
                task.total_size = total
            if task.segments:
                seg = task.segments[0]
                seg.downloaded_bytes = task.downloaded_size
                if total:
                    seg.end_byte = max(total - 1, 0)
            task.speed = p.get("speed") or 0
            self.window.on_progress(task)

        try:
            result = await grabber.download_video(
                url, save_dir, format_selector,
                referrer=referrer, cookies=cookies, user_agent=user_agent,
                on_progress=_on_progress,
            )
        except Exception as e:
            logger.error(f"Video download failed: {e}")
            result = None

        if result:
            try:
                file_size = os.path.getsize(result)
            except OSError:
                file_size = 0

            task.filename = os.path.basename(result)
            task.category = detect_category(task.filename)
            task.save_path = os.path.dirname(result) or save_dir
            task.total_size = file_size
            task.downloaded_size = file_size
            task.status = DownloadStatus.COMPLETED
            task.completed_at = time.time()
            if task.segments:
                seg = task.segments[0]
                seg.end_byte = max(file_size - 1, 0)
                seg.downloaded_bytes = file_size
                seg.status = SegmentStatus.DONE

            await self.database.save_download(task)
            self.window.on_complete(task)
        else:
            reason = grabber.last_error or "unknown error"
            logger.error(f"Video download failed for {task.filename}: {reason}")
            task.status = DownloadStatus.ERROR
            task.error_message = reason
            await self.database.save_download(task)
            self.window.on_error(task, reason[:200])

    def _on_clipboard_url(self, url: str):
        """Handle URL detected in clipboard."""
        # Show the add download dialog with the URL pre-filled
        from udm.ui.download_dialog import DownloadDialog
        dialog = DownloadDialog(
            self.window,
            url=url,
            save_dir=self.config.get("general.default_save_dir", ""),
        )
        dialog.download_requested.connect(self.window._start_new_download)
        dialog.show()

    async def _shutdown(self):
        """Clean shutdown of all components."""
        logger.info("Shutting down UDM...")

        # Stop clipboard monitor
        self.clipboard_monitor.stop()

        # Stop WebSocket server
        await self.ws_server.stop()

        # Save all download states
        for task in self.queue.get_all_tasks():
            await self.database.save_download(task)

        # Close database
        await self.database.close()

        logger.info("UDM shutdown complete")

    def run(self):
        """Start the UDM application."""
        # Run async initialization
        self._loop.run_until_complete(self._initialize())

        # Show window
        if not self.config.get("general.start_minimized", False):
            self.window.show()

        # Run Qt event loop
        exit_code = self.qt_app.exec()

        # Cleanup
        self._loop.run_until_complete(self._shutdown())
        self._loop.close()

        return exit_code


def setup_logging():
    """Configure application logging."""
    log_dir = Path.home() / ".udm" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    handlers = [logging.FileHandler(str(log_dir / "udm.log"), encoding="utf-8")]
    # The windowed .exe has no console, so sys.stdout is None there.
    if sys.stdout is not None:
        handlers.insert(0, logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )

def check_single_instance(port: int = 19615, token: str = "") -> bool:
    """
    Check if another instance of UDM is running by connecting to its WebSocket port.
    If it is, send a 'show' command to bring it to the foreground, then return True.
    """
    import socket
    import json
    try:
        # Quick check if the port is bound
        s = socket.create_connection(("127.0.0.1", port), timeout=0.1)
        s.close()
    except OSError:
        # Port is not open, safe to start
        return False

    # Port is open. Try sending the show command via websockets.
    try:
        import websockets
        async def wake_up():
            try:
                async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                    await ws.send(json.dumps({"type": "show", "token": token}))
                    await asyncio.wait_for(ws.recv(), timeout=1.0)
            except Exception:
                pass
        
        # Run the event loop to fire the connection
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(wake_up())
        loop.close()
    except ImportError:
        pass # Websockets not installed, can't wake it, but still exit
        
    return True


def main():
    """Application entry point."""
    setup_logging()
    
    # Enforce single instance
    config = Config()
    ws_port = config.get("browser.ws_port", 19615)
    token = config.get("security.pairing_token", "")
    if check_single_instance(ws_port, token):
        logger.info("UDM is already running. Showing existing instance and exiting.")
        sys.exit(0)
        
    logger.info("Starting UDM — Ultimate Download Manager")

    app = UDMApp()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
