"""
UDM Application - Main entry point.
Initializes all components and starts the application.
"""

import asyncio
import logging
import sys
from pathlib import Path

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
        )
        self.queue = DownloadQueue(
            engine=self.engine,
            database=self.database,
            max_concurrent=self.config.get("download.max_concurrent_downloads", 3),
        )
        self.scheduler = Scheduler()
        self.ws_server = WebSocketServer(
            port=self.config.get("browser.ws_port", 19615),
            on_download=self._on_extension_download,
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

    async def _on_extension_download(self, data: dict):
        """Handle download request from browser extension."""
        try:
            url = data.get("url", "")
            if not url:
                return

            if data.get("auto_start", False):
                filename = data.get("filename") or "download"
                # Show instant tray notification so the user doesn't feel a latency gap
                self.window.tray.show_message("UDM Connecting...", f"Preparing download for {filename}")

                # Bypass dialog and start instantly (used for web floating buttons)
                task = await self.engine.prepare_download(
                    url=url,
                    filename=data.get("filename"),
                    cookies=data.get("cookies"),
                    referrer=data.get("referrer"),
                    user_agent=data.get("user_agent"),
                )
                await self.queue.add_download(task, start_immediately=True)
                self.window.on_queue_changed()
                
                # Show started notification
                self.window.tray.show_message("UDM Download Started", f"Downloading: {task.filename}")
            else:
                # Schedule UI update on the Qt main loop thread
                QTimer.singleShot(0, lambda: self._show_extension_dialog(data))

        except Exception as e:
            logger.error(f"Failed to handle extension download: {e}")

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

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(str(log_dir / "udm.log"), encoding="utf-8"),
        ],
    )

def check_single_instance(port: int = 19615) -> bool:
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
                    await ws.send(json.dumps({"type": "show"}))
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
    if check_single_instance(ws_port):
        logger.info("UDM is already running. Showing existing instance and exiting.")
        sys.exit(0)
        
    logger.info("Starting UDM — Ultimate Download Manager")

    app = UDMApp()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
