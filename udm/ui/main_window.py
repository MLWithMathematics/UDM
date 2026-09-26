"""
UDM Main Window - The primary application interface.
Features: toolbar, download table, category sidebar, status bar, speed graph.
"""

import asyncio
import os
import sys
from pathlib import Path
from functools import partial

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QToolBar, QStatusBar, QLabel, QListWidget, QListWidgetItem,
    QSplitter, QMenu, QMessageBox, QApplication,
    QAbstractItemView, QFrame, QInputDialog, QLineEdit,
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, pyqtSlot, QSize,
)
from PyQt6.QtGui import (
    QAction, QFont, QIcon, QColor, QKeySequence,
)

from udm.core.segment import (
    DownloadTask, DownloadStatus, FileCategory,
    format_size, format_speed, format_eta,
)
from udm.ui.download_dialog import DownloadDialog
from udm.ui.settings_dialog import SettingsDialog
from udm.ui.video_dialog import VideoDownloadDialog
from udm.ui.download_detail_dialog import DownloadDetailDialog
from udm.ui.widgets.progress_bar import SegmentedProgressBar
from udm.ui.widgets.speed_graph import SpeedGraph
from udm.ui.widgets.system_tray import SystemTray, create_udm_icon
from udm.storage.config import Config


# Status icons
STATUS_ICONS = {
    DownloadStatus.QUEUED: "🕐",
    DownloadStatus.DOWNLOADING: "⬇️",
    DownloadStatus.PAUSED: "⏸️",
    DownloadStatus.COMPLETED: "✅",
    DownloadStatus.ERROR: "❌",
    DownloadStatus.MERGING: "🔄",
}

# Category icons
CATEGORY_ICONS = {
    "All": "📁",
    "General": "📄",
    "Compressed": "📦",
    "Documents": "📝",
    "Music": "🎵",
    "Video": "🎬",
    "Programs": "💿",
    "Images": "🖼️",
}

# Table columns
COLUMNS = ["", "File Name", "Size", "Progress", "Speed", "ETA", "Status"]
COL_ICON = 0
COL_FILENAME = 1
COL_SIZE = 2
COL_PROGRESS = 3
COL_SPEED = 4
COL_ETA = 5
COL_STATUS = 6


class MainWindow(QMainWindow):
    """Main UDM application window."""

    # Signals for async operations (thread-safe UI updates)
    sig_progress = pyqtSignal(object)
    sig_complete = pyqtSignal(object)
    sig_error = pyqtSignal(object, str)
    sig_queue_changed = pyqtSignal()

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self._download_queue = None  # Set by app.py
        self._engine = None  # Set by app.py

        # Map download_id → table row index
        self._row_map: dict[str, int] = {}
        # Map download_id → progress bar widget
        self._progress_bars: dict[str, SegmentedProgressBar] = {}
        # Map download_id → detail dialog (IDM-style)
        self._detail_dialogs: dict[str, DownloadDetailDialog] = {}

        self._setup_window()
        self._setup_theme()
        self._setup_toolbar()
        self._setup_ui()
        self._setup_statusbar()
        self._setup_tray()
        self._setup_signals()
        self._setup_refresh_timer()

    def set_queue(self, queue):
        """Set the download queue (called by app.py after initialization)."""
        self._download_queue = queue
        self._engine = queue.engine if queue else None

    def _setup_window(self):
        """Configure main window properties."""
        self.setWindowTitle("UDM — Ultimate Download Manager")
        self.setWindowIcon(create_udm_icon())
        self.setMinimumSize(960, 640)
        self.resize(1100, 720)

        # Center on screen
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = (geo.width() - self.width()) // 2
            y = (geo.height() - self.height()) // 2
            self.move(x, y)

    def _setup_theme(self):
        """Load and apply the sky blue theme stylesheet."""
        theme_path = Path(__file__).parent / "themes" / "skyblue.qss"
        if theme_path.exists():
            with open(theme_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())

    def _setup_toolbar(self):
        """Create the main toolbar with action buttons."""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        self.addToolBar(toolbar)

        # Add URL
        self.action_add = QAction("➕  Add URL", self)
        self.action_add.setShortcut(QKeySequence("Ctrl+N"))
        self.action_add.setToolTip("Add a new download (Ctrl+N)")
        self.action_add.triggered.connect(self._on_add_download)
        toolbar.addAction(self.action_add)

        # Video Download
        self.action_video = QAction("🎬  Video", self)
        self.action_video.setShortcut(QKeySequence("Ctrl+D"))
        self.action_video.setToolTip("Download video from YouTube & more (Ctrl+D)")
        self.action_video.triggered.connect(self._on_video_download)
        toolbar.addAction(self.action_video)

        toolbar.addSeparator()

        # Resume
        self.action_resume = QAction("▶  Resume", self)
        self.action_resume.setShortcut(QKeySequence("Ctrl+R"))
        self.action_resume.setToolTip("Resume selected download")
        self.action_resume.triggered.connect(self._on_resume)
        toolbar.addAction(self.action_resume)

        # Pause
        self.action_pause = QAction("⏸  Pause", self)
        self.action_pause.setShortcut(QKeySequence("Ctrl+P"))
        self.action_pause.setToolTip("Pause selected download")
        self.action_pause.triggered.connect(self._on_pause)
        toolbar.addAction(self.action_pause)

        toolbar.addSeparator()

        # Delete
        self.action_delete = QAction("🗑  Delete", self)
        self.action_delete.setShortcut(QKeySequence("Delete"))
        self.action_delete.setToolTip("Delete selected download")
        self.action_delete.triggered.connect(self._on_delete)
        toolbar.addAction(self.action_delete)

        toolbar.addSeparator()

        # Pause All
        self.action_pause_all = QAction("⏸  Pause All", self)
        self.action_pause_all.triggered.connect(self._on_pause_all)
        toolbar.addAction(self.action_pause_all)

        # Resume All
        self.action_resume_all = QAction("▶  Resume All", self)
        self.action_resume_all.triggered.connect(self._on_resume_all)
        toolbar.addAction(self.action_resume_all)

        toolbar.addSeparator()

        # Clear Completed
        self.action_clear_completed = QAction("🧹  Clear Completed", self)
        self.action_clear_completed.setToolTip("Remove all completed downloads from the list")
        self.action_clear_completed.triggered.connect(self._on_clear_completed)
        toolbar.addAction(self.action_clear_completed)

        toolbar.addSeparator()

        # Settings
        self.action_settings = QAction("⚙  Settings", self)
        self.action_settings.setShortcut(QKeySequence("Ctrl+,"))
        self.action_settings.triggered.connect(self._on_settings)
        toolbar.addAction(self.action_settings)

    def _setup_ui(self):
        """Create the main UI layout."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(8)

        # Main splitter: sidebar | content
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ─── Sidebar (Categories) ──────────────────────
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)

        sidebar_title = QLabel("📁 Categories")
        sidebar_title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        sidebar_title.setStyleSheet("color: #1565c0; padding: 8px 4px;")
        sidebar_layout.addWidget(sidebar_title)

        self.category_list = QListWidget()
        self.category_list.setMaximumWidth(200)

        # Add category items
        all_item = QListWidgetItem(f"{CATEGORY_ICONS['All']}  All Downloads")
        all_item.setData(Qt.ItemDataRole.UserRole, "All")
        self.category_list.addItem(all_item)

        for cat in FileCategory:
            icon = CATEGORY_ICONS.get(cat.value, "📄")
            item = QListWidgetItem(f"{icon}  {cat.value}")
            item.setData(Qt.ItemDataRole.UserRole, cat.value)
            self.category_list.addItem(item)

        self.category_list.setCurrentRow(0)
        self.category_list.currentItemChanged.connect(self._on_category_changed)
        sidebar_layout.addWidget(self.category_list)

        splitter.addWidget(sidebar)

        # ─── Content Area ──────────────────────────────
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        # Download table
        self.table = QTableWidget()
        self.table.setColumnCount(len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.doubleClicked.connect(self._on_table_double_click)

        # Column sizing
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_ICON, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(COL_ICON, 36)
        header.setSectionResizeMode(COL_FILENAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_SIZE, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(COL_SIZE, 90)
        header.setSectionResizeMode(COL_PROGRESS, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(COL_PROGRESS, 200)
        header.setSectionResizeMode(COL_SPEED, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(COL_SPEED, 100)
        header.setSectionResizeMode(COL_ETA, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(COL_ETA, 90)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(COL_STATUS, 100)

        # Row height
        self.table.verticalHeader().setDefaultSectionSize(44)

        content_layout.addWidget(self.table, stretch=3)

        # Speed graph (collapsible bottom panel)
        self.speed_graph = SpeedGraph()
        self.speed_graph.setMaximumHeight(150)
        self.speed_graph.setMinimumHeight(80)
        content_layout.addWidget(self.speed_graph, stretch=1)

        splitter.addWidget(content)

        # Splitter proportions
        splitter.setSizes([180, 800])
        main_layout.addWidget(splitter)

    def _setup_statusbar(self):
        """Create the status bar with download stats."""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)

        self.status_active = QLabel("Active: 0")
        self.status_speed = QLabel("Speed: 0 KB/s")
        self.status_scheduler = QLabel("Scheduler: Off")

        self.statusbar.addPermanentWidget(self.status_active)
        self.statusbar.addPermanentWidget(self.status_speed)
        self.statusbar.addPermanentWidget(self.status_scheduler)

        self.statusbar.showMessage("UDM Ready — Add a download to get started!")

    def _setup_tray(self):
        """Set up system tray icon."""
        self.tray = SystemTray(self)
        self.tray.show_window.connect(self._show_from_tray)
        self.tray.pause_all.connect(self._on_pause_all)
        self.tray.resume_all.connect(self._on_resume_all)
        self.tray.exit_app.connect(self._on_exit)
        self.tray.show()

    def _setup_signals(self):
        """Connect thread-safe signals to UI update slots."""
        self.sig_progress.connect(self._update_download_row)
        self.sig_complete.connect(self._on_download_complete)
        self.sig_error.connect(self._on_download_error)
        self.sig_queue_changed.connect(self._refresh_table)

    def _setup_refresh_timer(self):
        """Periodic UI refresh timer."""
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._periodic_refresh)
        self._refresh_timer.start(1000)  # 1 second refresh

    # ─── Download Actions ────────────────────────────────────

    def _on_add_download(self):
        """Show the Add Download dialog."""
        save_dir = self.config.get("general.default_save_dir", "")
        dialog = DownloadDialog(self, save_dir=save_dir)
        dialog.download_requested.connect(self._start_new_download)
        dialog.exec()

    def _start_new_download(self, config: dict):
        """Start a new download from dialog config."""
        if not self._download_queue:
            return

        # Run async operation via event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(self._async_add_download(config))
        else:
            loop.run_until_complete(self._async_add_download(config))

    async def _async_add_download(self, config: dict):
        """Async: prepare and add download to queue."""
        try:
            task = await self._engine.prepare_download(
                url=config["url"],
                save_path=config.get("save_path"),
                filename=config.get("filename"),
                num_segments=config.get("num_segments", 8),
                cookies=config.get("cookies"),
                referrer=config.get("referrer"),
                user_agent=config.get("user_agent"),
            )
            await self._download_queue.add_download(
                task,
                start_immediately=config.get("start_immediately", True),
            )
            # Auto-open IDM-style detail dialog
            self._open_detail_dialog(task)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add download:\n{str(e)}")

    def _on_resume(self):
        """Resume selected download."""
        task = self._get_selected_task()
        if task and self._download_queue:
            asyncio.ensure_future(self._download_queue.resume_download(task.id))

    def _on_pause(self):
        """Pause selected download."""
        task = self._get_selected_task()
        if task and self._download_queue:
            asyncio.ensure_future(self._download_queue.pause_download(task.id))

    def _on_delete(self):
        """Delete selected download."""
        task = self._get_selected_task()
        if not task or not self._download_queue:
            return

        reply = QMessageBox.question(
            self, "Delete Download",
            f"Delete '{task.filename}'?\n\nThis will remove the download from the list.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            asyncio.ensure_future(self._download_queue.cancel_download(task.id))
            self._remove_download_row(task.id)

    def _on_pause_all(self):
        if self._download_queue:
            asyncio.ensure_future(self._download_queue.pause_all())

    def _on_resume_all(self):
        if self._download_queue:
            asyncio.ensure_future(self._download_queue.resume_all())

    def _on_clear_completed(self):
        """Remove all completed downloads from the list."""
        if not self._download_queue:
            return

        completed = self._download_queue.get_tasks_by_status(DownloadStatus.COMPLETED)
        if not completed:
            self.statusbar.showMessage("No completed downloads to clear.", 3000)
            return

        reply = QMessageBox.question(
            self, "Clear Completed Downloads",
            f"Remove {len(completed)} completed download(s) from the list?\n\n"
            "This will not delete the downloaded files from disk.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            asyncio.ensure_future(self._download_queue.clear_completed())
            self.statusbar.showMessage(
                f"Cleared {len(completed)} completed downloads.", 3000
            )

    def _on_table_double_click(self, index):
        """Handle double-click on a download row — open IDM-style detail dialog."""
        task = self._get_selected_task()
        if task:
            self._open_detail_dialog(task)

    def _open_detail_dialog(self, task):
        """Open (or bring to front) the IDM-style download detail dialog."""
        # Reuse existing dialog if still open
        if task.id in self._detail_dialogs:
            dialog = self._detail_dialogs[task.id]
            if dialog.isVisible():
                dialog.set_task(task)
                dialog.raise_()
                dialog.activateWindow()
                return
            else:
                # Dialog was closed, remove reference
                del self._detail_dialogs[task.id]

        # Create new detail dialog
        dialog = DownloadDetailDialog(task, self)
        dialog.pause_requested.connect(
            lambda did: asyncio.ensure_future(
                self._download_queue.pause_download(did)
            ) if self._download_queue else None
        )
        dialog.resume_requested.connect(
            lambda did: asyncio.ensure_future(
                self._download_queue.resume_download(did)
            ) if self._download_queue else None
        )
        self._detail_dialogs[task.id] = dialog
        dialog.show()

    def _on_video_download(self):
        """Show the Video Download dialog."""
        save_dir = self.config.get(
            "categories.Video",
            self.config.get("general.default_save_dir", "")
        )
        dialog = VideoDownloadDialog(self, save_dir=save_dir)
        dialog.exec()

    def _on_settings(self):
        dialog = SettingsDialog(self.config, self)
        dialog.settings_changed.connect(self._apply_settings)
        dialog.exec()

    def _apply_settings(self):
        """Apply settings changes."""
        if self._download_queue:
            self._download_queue.max_concurrent = self.config.get(
                "download.max_concurrent_downloads", 3
            )
        if self._engine:
            speed_limit = self.config.get("speed.global_limit_bytes_per_sec", 0)
            self._engine.speed_limiter.set_global_limit(speed_limit)

    # ─── Table Management ────────────────────────────────────

    def _add_download_row(self, task: DownloadTask):
        """Add a new row to the download table."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._row_map[task.id] = row

        # Icon
        icon_item = QTableWidgetItem(STATUS_ICONS.get(task.status, ""))
        icon_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_item.setData(Qt.ItemDataRole.UserRole, task.id)
        icon_item.setFlags(icon_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, COL_ICON, icon_item)

        # Filename
        name_item = QTableWidgetItem(task.filename)
        name_item.setToolTip(task.url)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, COL_FILENAME, name_item)

        # Size
        size_item = QTableWidgetItem(format_size(task.total_size))
        size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, COL_SIZE, size_item)

        # Progress bar (custom widget)
        progress_bar = SegmentedProgressBar()
        progress_bar.set_task(task)
        self.table.setCellWidget(row, COL_PROGRESS, progress_bar)
        self._progress_bars[task.id] = progress_bar

        # Speed
        speed_item = QTableWidgetItem(format_speed(task.speed))
        speed_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        speed_item.setFlags(speed_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, COL_SPEED, speed_item)

        # ETA
        eta_item = QTableWidgetItem(format_eta(task.eta_seconds))
        eta_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        eta_item.setFlags(eta_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, COL_ETA, eta_item)

        # Status
        status_item = QTableWidgetItem(task.status.value)
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, COL_STATUS, status_item)

    @pyqtSlot(object)
    def _update_download_row(self, task: DownloadTask):
        """Update an existing row with new task data."""
        if task.id not in self._row_map:
            return

        row = self._row_map[task.id]
        if row >= self.table.rowCount():
            return

        # Update icon
        icon_item = self.table.item(row, COL_ICON)
        if icon_item:
            icon_item.setText(STATUS_ICONS.get(task.status, ""))

        # Update size (might be discovered after HEAD request)
        size_item = self.table.item(row, COL_SIZE)
        if size_item:
            size_item.setText(format_size(task.total_size))

        # Update progress bar
        if task.id in self._progress_bars:
            self._progress_bars[task.id].set_task(task)

        # Update speed
        speed_item = self.table.item(row, COL_SPEED)
        if speed_item:
            speed_item.setText(
                format_speed(task.speed) if task.is_active else ""
            )

        # Update ETA
        eta_item = self.table.item(row, COL_ETA)
        if eta_item:
            eta_item.setText(
                format_eta(task.eta_seconds) if task.is_active else ""
            )

        # Update status
        status_item = self.table.item(row, COL_STATUS)
        if status_item:
            status_item.setText(task.status.value)

    def _remove_download_row(self, download_id: str):
        """Remove a row from the table."""
        if download_id in self._row_map:
            row = self._row_map[download_id]
            self.table.removeRow(row)
            del self._row_map[download_id]
            self._progress_bars.pop(download_id, None)

            # Rebuild row map after removal
            self._rebuild_row_map()

    def _rebuild_row_map(self):
        """Rebuild the download_id → row mapping after table changes."""
        self._row_map.clear()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, COL_ICON)
            if item:
                download_id = item.data(Qt.ItemDataRole.UserRole)
                if download_id:
                    self._row_map[download_id] = row

    @pyqtSlot()
    def _refresh_table(self):
        """Full refresh of the download table from queue."""
        if not self._download_queue:
            return

        # Get current category filter
        current_cat = self._get_selected_category()

        tasks = self._download_queue.get_all_tasks()

        # Filter by category
        if current_cat and current_cat != "All":
            tasks = [t for t in tasks if t.category.value == current_cat]

        # Clear and rebuild
        self.table.setRowCount(0)
        self._row_map.clear()
        self._progress_bars.clear()

        for task in tasks:
            self._add_download_row(task)

    @pyqtSlot(object)
    def _on_download_complete(self, task: DownloadTask):
        """Handle download completion."""
        self._update_download_row(task)
        if self.config.get("general.show_notifications", True):
            self.tray.show_message(
                "Download Complete",
                f"✅ {task.filename} has finished downloading!"
            )

    @pyqtSlot(object, str)
    def _on_download_error(self, task: DownloadTask, error_msg: str):
        """Handle download error."""
        self._update_download_row(task)
        if self.config.get("general.show_notifications", True):
            self.tray.show_message(
                "Download Error",
                f"❌ {task.filename}: {error_msg}"
            )

    # ─── Context Menu ────────────────────────────────────────

    def _on_context_menu(self, pos):
        """Show right-click context menu on download item."""
        task = self._get_selected_task()
        if not task:
            return

        menu = QMenu(self)

        if task.status == DownloadStatus.DOWNLOADING:
            menu.addAction("⏸  Pause", self._on_pause)
        elif task.status in (DownloadStatus.PAUSED, DownloadStatus.ERROR):
            menu.addAction("▶  Resume", self._on_resume)
        elif task.status == DownloadStatus.QUEUED:
            menu.addAction("▶  Start Now", self._on_resume)

        menu.addSeparator()

        if task.status == DownloadStatus.COMPLETED:
            menu.addAction("📂  Open File", lambda: self._open_file(task))
            menu.addAction("📁  Open Folder", lambda: self._open_folder(task))
            menu.addSeparator()

        menu.addAction("🔄  Refresh Link", lambda: self._on_refresh_link(task))
        menu.addAction("📋  Copy URL", lambda: self._copy_url(task))
        menu.addSeparator()
        menu.addAction("🗑  Delete", self._on_delete)

        # Add "Clear All Completed" if there are completed downloads
        completed = self._download_queue.get_tasks_by_status(DownloadStatus.COMPLETED) if self._download_queue else []
        if completed:
            menu.addSeparator()
            menu.addAction("🧹  Clear All Completed", self._on_clear_completed)

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _on_refresh_link(self, task: DownloadTask):
        """Update the download URL for a task (e.g., if link expired)."""
        new_url, ok = QInputDialog.getText(
            self, "Refresh Link",
            "Enter the new URL for this download (to resume an expired link):",
            QLineEdit.EchoMode.Normal,
            task.url
        )
        if ok and new_url.strip():
            task.url = new_url.strip()
            task.etag = None  # Clear old ETag so If-Range doesn't trigger 200 OK fallback
            task.last_modified = None # Clear last_modified so resume verification doesn't fail on fresh links
            # Save to database
            if self._download_queue:
                asyncio.ensure_future(self._download_queue.database.save_download(task))
            self.statusbar.showMessage("Link updated successfully.", 3000)
            
            # If the download detail dialog is open, update its URL label too
            if task.id in self._detail_dialogs:
                dialog = self._detail_dialogs[task.id]
                if hasattr(dialog, 'lbl_url'):
                    dialog.lbl_url.setText(task.url)

    # ─── Helpers ─────────────────────────────────────────────

    def _get_selected_task(self) -> DownloadTask | None:
        """Get the currently selected download task."""
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        item = self.table.item(row, COL_ICON)
        if item:
            download_id = item.data(Qt.ItemDataRole.UserRole)
            if self._download_queue:
                return self._download_queue.get_task(download_id)
        return None

    def _get_selected_category(self) -> str | None:
        """Get the currently selected category from sidebar."""
        item = self.category_list.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return "All"

    def _on_category_changed(self, current, previous):
        """Filter downloads by selected category."""
        self._refresh_table()

    def _periodic_refresh(self):
        """Called every second to update status bar and speed graph."""
        if not self._download_queue:
            return

        active = self._download_queue.active_count
        total_speed = self._download_queue.total_speed

        self.status_active.setText(f"Active: {active}")
        self.status_speed.setText(f"Speed: {format_speed(total_speed)}")
        self.speed_graph.update_speed(total_speed)

        # Update all active download rows
        for task in self._download_queue.get_tasks_by_status(DownloadStatus.DOWNLOADING):
            self._update_download_row(task)

    def _open_file(self, task: DownloadTask):
        from udm.storage.file_manager import FileManager
        FileManager.open_file(task.output_filepath)

    def _open_folder(self, task: DownloadTask):
        from udm.storage.file_manager import FileManager
        FileManager.open_file_location(task.output_filepath)

    def _copy_url(self, task: DownloadTask):
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(task.url)

    def _show_from_tray(self):
        self.showNormal()
        self.activateWindow()

    def _on_exit(self):
        """Exit the application."""
        self.tray.hide()
        QApplication.quit()

    # ─── Window Events ───────────────────────────────────────

    def closeEvent(self, event):
        """Handle window close — minimize to tray if enabled."""
        if self.config.get("general.minimize_to_tray", True):
            event.ignore()
            self.hide()
            self.tray.show_message(
                "UDM",
                "UDM is still running in the system tray."
            )
        else:
            self.tray.hide()
            event.accept()

    # ─── Public API for app.py ───────────────────────────────

    def on_progress(self, task: DownloadTask):
        """Thread-safe progress update callback."""
        self.sig_progress.emit(task)
        # Also update any open detail dialog for this download
        if task.id in self._detail_dialogs:
            dialog = self._detail_dialogs[task.id]
            if dialog.isVisible():
                dialog.set_task(task)

    def on_complete(self, task: DownloadTask):
        """Thread-safe completion callback."""
        self.sig_complete.emit(task)

    def on_error(self, task: DownloadTask, error_msg: str):
        """Thread-safe error callback."""
        self.sig_error.emit(task, error_msg)

    def on_queue_changed(self):
        """Thread-safe queue change callback."""
        self.sig_queue_changed.emit()

    def load_existing_downloads(self, tasks: list):
        """Load existing downloads into the table (called on startup)."""
        for task in tasks:
            self._add_download_row(task)
