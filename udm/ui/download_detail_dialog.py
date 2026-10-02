"""
IDM-style Download Detail Dialog.

Opens when you double-click a download in the table.
Shows per-segment progress bars, file info, speed, elapsed time,
and control buttons (Pause/Resume/Cancel/Open Folder).
"""

import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QGroupBox, QProgressBar,
    QScrollArea, QWidget, QFrame, QSizePolicy, QLineEdit,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPainter, QPainterPath, QLinearGradient, QPen, QBrush

from udm.core.segment import (
    DownloadTask, DownloadStatus, SegmentStatus,
    format_size, format_speed, format_eta,
)

# Colors for segment status (Fluent Design)
SEG_COLORS = {
    SegmentStatus.DONE:    QColor(0, 120, 212),      # Fluent Blue
    SegmentStatus.ACTIVE:  QColor(100, 180, 250),    # Light Blue
    SegmentStatus.PENDING: QColor(220, 220, 220),    # Gray
    SegmentStatus.PAUSED:  QColor(255, 170, 0),      # Orange
    SegmentStatus.ERROR:   QColor(232, 17, 35),      # Red
}


class SegmentBar(QWidget):
    """A single segment progress bar with label."""

    def __init__(self, segment_id: int, parent=None):
        super().__init__(parent)
        self.segment_id = segment_id
        self._progress = 0.0
        self._status = SegmentStatus.PENDING
        self._downloaded = 0
        self._total = 0
        self.setMinimumHeight(24)
        self.setMaximumHeight(24)

    def update_data(self, progress: float, status: SegmentStatus,
                    downloaded: int, total: int):
        self._progress = progress
        self._status = status
        self._downloaded = downloaded
        self._total = total
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        radius = h / 2.0  # Perfect pill shape

        # Background container
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 15)))
        painter.drawRoundedRect(0, 0, w, h, radius, radius)

        # Fill
        fill_w = w * (self._progress / 100.0) if self._progress > 0 else 0
        if fill_w > 0:
            color = SEG_COLORS.get(self._status, SEG_COLORS[SegmentStatus.PENDING])
            
            # Clip path so the fill exactly matches the pill shape of the container
            clip_path = QPainterPath()
            clip_path.addRoundedRect(0, 0, w, h, radius, radius)
            painter.setClipPath(clip_path)

            painter.setBrush(QBrush(color))
            painter.drawRect(0, 0, int(fill_w), h)
            
            painter.setClipping(False)

        # Status text
        text = f"Seg {self.segment_id + 1}: {self._progress:.1f}%"
        if self._status == SegmentStatus.DONE:
            text = f"Seg {self.segment_id + 1}: ✅ Done"
        elif self._status == SegmentStatus.ERROR:
            text = f"Seg {self.segment_id + 1}: ❌ Error"
        elif self._status == SegmentStatus.PAUSED:
            text = f"Seg {self.segment_id + 1}: ⏸ Paused"

        painter.setFont(QFont("Segoe UI Variable", 9, QFont.Weight.DemiBold))
        
        # Draw dark text as base
        painter.setPen(QColor(26, 26, 26))
        painter.drawText(12, 0, w - 24, h, Qt.AlignmentFlag.AlignVCenter, text)
        
        # Draw white text where the fill covers it
        if fill_w > 12:
            clip_path_fill = QPainterPath()
            clip_path_fill.addRect(0, 0, fill_w, h)
            painter.setClipPath(clip_path_fill)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(12, 0, w - 24, h, Qt.AlignmentFlag.AlignVCenter, text)
            painter.setClipping(False)

        # Right Text (Size / Total)
        size_text = f"{format_size(self._downloaded)} / {format_size(self._total)}"
        painter.setFont(QFont("Segoe UI Variable", 8))
        
        # Base dark text for right side
        painter.setPen(QColor(100, 100, 100))
        painter.drawText(0, 0, w - 16, h, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, size_text)
        
        # White text where the fill covers it
        if fill_w > w - 100:
            clip_path_fill2 = QPainterPath()
            clip_path_fill2.addRect(0, 0, fill_w, h)
            painter.setClipPath(clip_path_fill2)
            painter.setPen(QColor(240, 240, 240))
            painter.drawText(0, 0, w - 16, h, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, size_text)
            painter.setClipping(False)

        painter.end()


class DownloadDetailDialog(QDialog):
    """
    IDM-style per-download detail window.

    Shows:
    - File name, URL, save path
    - Per-segment progress bars
    - Overall progress bar
    - Speed, downloaded/total, time elapsed, ETA
    - Pause/Resume/Cancel/Open Folder buttons
    """

    pause_requested = pyqtSignal(str)   # download_id
    resume_requested = pyqtSignal(str)  # download_id
    cancel_requested = pyqtSignal(str)  # download_id

    def __init__(self, task: DownloadTask, parent=None):
        super().__init__(parent)
        self._task = task
        self._start_time = time.time()
        self._segment_bars: list[SegmentBar] = []

        self.setWindowTitle(f"📥  {task.filename}")
        self.setMinimumSize(620, 520)
        self.setModal(False)  # Non-modal so user can interact with main window

        self._setup_ui()

        # Auto-refresh timer
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._update_ui)
        self._refresh_timer.start(500)  # Refresh every 500ms

        self._update_ui()

    def set_task(self, task: DownloadTask):
        """Update the task reference (called from main window on progress)."""
        self._task = task

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # ─── File Info Group ──────────────────────────
        info_group = QGroupBox("📄  File Information")
        info_layout = QFormLayout(info_group)
        info_layout.setSpacing(8)

        self.lbl_filename = QLabel(self._task.filename)
        self.lbl_filename.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.lbl_filename.setStyleSheet("color: #0d47a1;")
        self.lbl_filename.setWordWrap(True)
        info_layout.addRow("File:", self.lbl_filename)

        self.lbl_url = QLineEdit(self._task.url)
        self.lbl_url.setReadOnly(True)
        self.lbl_url.setStyleSheet("color: #546e7a; font-size: 11px; border: none; background: transparent;")
        # QLineEdit handles long text in a single line natively.
        info_layout.addRow("URL:", self.lbl_url)

        self.lbl_save_path = QLabel(self._task.output_filepath)
        self.lbl_save_path.setWordWrap(True)
        self.lbl_save_path.setStyleSheet("color: #546e7a; font-size: 11px;")
        info_layout.addRow("Save To:", self.lbl_save_path)

        self.lbl_size = QLabel("—")
        self.lbl_size.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        info_layout.addRow("Size:", self.lbl_size)

        layout.addWidget(info_group)

        # ─── Segments Group ───────────────────────────
        seg_group = QGroupBox(f"📊  Segments ({self._task.num_segments})")
        seg_outer_layout = QVBoxLayout(seg_group)

        # Scrollable segment area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(180)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )

        seg_widget = QWidget()
        seg_layout = QVBoxLayout(seg_widget)
        seg_layout.setSpacing(4)
        seg_layout.setContentsMargins(4, 4, 4, 4)

        for seg in self._task.segments:
            bar = SegmentBar(seg.id)
            self._segment_bars.append(bar)
            seg_layout.addWidget(bar)

        seg_layout.addStretch()
        scroll.setWidget(seg_widget)
        seg_outer_layout.addWidget(scroll)

        layout.addWidget(seg_group)

        # ─── Overall Progress ─────────────────────────
        progress_group = QGroupBox("📈  Overall Progress")
        progress_layout = QVBoxLayout(progress_group)

        self.overall_progress = QProgressBar()
        self.overall_progress.setMinimumHeight(24)
        self.overall_progress.setTextVisible(True)
        self.overall_progress.setFormat(" %p% ")
        self.overall_progress.setStyleSheet("""
            QProgressBar {
                background-color: rgba(0, 0, 0, 0.05);
                border: none;
                border-radius: 12px;
                text-align: center;
                color: #1a1a1a;
                font-family: "Segoe UI Variable", "Segoe UI", sans-serif;
                font-weight: 600;
            }
            QProgressBar::chunk {
                background-color: #0078d4;
                border-radius: 12px;
            }
        """)
        progress_layout.addWidget(self.overall_progress)

        # Stats row
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(20)

        self.lbl_speed = self._make_stat_label("Speed", "—")
        stats_layout.addWidget(self.lbl_speed)

        self.lbl_downloaded = self._make_stat_label("Downloaded", "—")
        stats_layout.addWidget(self.lbl_downloaded)

        self.lbl_elapsed = self._make_stat_label("Elapsed", "—")
        stats_layout.addWidget(self.lbl_elapsed)

        self.lbl_eta = self._make_stat_label("Remaining", "—")
        stats_layout.addWidget(self.lbl_eta)

        progress_layout.addLayout(stats_layout)

        # Status label
        self.lbl_status = QLabel("QUEUED")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.lbl_status.setStyleSheet(
            "padding: 6px; border-radius: 6px; "
            "background: rgba(66, 165, 245, 0.15); color: #1565c0;"
        )
        progress_layout.addWidget(self.lbl_status)

        layout.addWidget(progress_group)

        # ─── Buttons ─────────────────────────────────
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_pause = QPushButton("⏸  Pause")
        self.btn_pause.setMinimumWidth(100)
        self.btn_pause.clicked.connect(self._on_pause)
        btn_layout.addWidget(self.btn_pause)

        self.btn_resume = QPushButton("▶  Resume")
        self.btn_resume.setMinimumWidth(100)
        self.btn_resume.clicked.connect(self._on_resume)
        btn_layout.addWidget(self.btn_resume)

        btn_layout.addStretch()

        self.btn_open_folder = QPushButton("📁  Open Folder")
        self.btn_open_folder.setMinimumWidth(120)
        self.btn_open_folder.clicked.connect(self._on_open_folder)
        btn_layout.addWidget(self.btn_open_folder)

        self.btn_close = QPushButton("Close")
        self.btn_close.setObjectName("btnCancel")
        self.btn_close.setMinimumWidth(80)
        self.btn_close.clicked.connect(self.close)
        btn_layout.addWidget(self.btn_close)

        layout.addLayout(btn_layout)

    def _make_stat_label(self, title: str, initial: str) -> QWidget:
        """Create a stat display widget with title and value."""
        container = QWidget()
        vl = QVBoxLayout(container)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(2)

        title_lbl = QLabel(title)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setStyleSheet("color: #78909c; font-size: 10px; font-weight: 600;")
        vl.addWidget(title_lbl)

        value_lbl = QLabel(initial)
        value_lbl.setObjectName(f"stat_{title}")
        value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        value_lbl.setStyleSheet("color: #1565c0;")
        vl.addWidget(value_lbl)

        return container

    def _find_stat_value(self, widget: QWidget) -> QLabel:
        """Find the value label inside a stat widget."""
        for child in widget.findChildren(QLabel):
            if child.objectName().startswith("stat_"):
                return child
        return None

    def _update_ui(self):
        """Refresh all UI elements from current task data."""
        task = self._task
        if not task:
            return

        # Update segment bars
        for i, seg in enumerate(task.segments):
            if i < len(self._segment_bars):
                self._segment_bars[i].update_data(
                    seg.progress, seg.status,
                    seg.downloaded_bytes, seg.total_bytes
                )

        # Overall progress
        progress = task.progress
        if progress >= 0:
            self.overall_progress.setValue(int(progress))
            self.overall_progress.setFormat(f"{progress:.1f}%")
        else:
            self.overall_progress.setRange(0, 0)  # indeterminate
            self.overall_progress.setFormat("Downloading...")

        # Size
        self.lbl_size.setText(
            f"{format_size(task.downloaded_size)} / {format_size(task.total_size)}"
        )

        # Speed
        speed_lbl = self._find_stat_value(self.lbl_speed)
        if speed_lbl:
            speed_lbl.setText(format_speed(task.speed) if task.is_active else "—")

        # Downloaded
        dl_lbl = self._find_stat_value(self.lbl_downloaded)
        if dl_lbl:
            dl_lbl.setText(format_size(task.downloaded_size))

        # Elapsed
        elapsed = time.time() - task.created_at
        elapsed_lbl = self._find_stat_value(self.lbl_elapsed)
        if elapsed_lbl:
            elapsed_lbl.setText(format_eta(elapsed))

        # ETA
        eta_lbl = self._find_stat_value(self.lbl_eta)
        if eta_lbl:
            eta_lbl.setText(format_eta(task.eta_seconds) if task.is_active else "—")

        # Status
        status_text = task.status.value
        status_styles = {
            DownloadStatus.DOWNLOADING: ("⬇ DOWNLOADING", "#1565c0", "rgba(66, 165, 245, 0.15)"),
            DownloadStatus.COMPLETED:   ("✅ COMPLETED",   "#2e7d32", "rgba(76, 175, 80, 0.15)"),
            DownloadStatus.PAUSED:      ("⏸ PAUSED",      "#e65100", "rgba(255, 152, 0, 0.15)"),
            DownloadStatus.ERROR:       ("❌ ERROR",        "#c62828", "rgba(239, 83, 80, 0.15)"),
            DownloadStatus.MERGING:     ("🔄 ASSEMBLING",  "#1565c0", "rgba(66, 165, 245, 0.15)"),
            DownloadStatus.QUEUED:      ("🕐 QUEUED",      "#546e7a", "rgba(144, 164, 174, 0.15)"),
        }
        text, fg, bg = status_styles.get(
            task.status, (status_text, "#546e7a", "rgba(144, 164, 174, 0.15)")
        )
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet(
            f"padding: 6px; border-radius: 6px; background: {bg}; color: {fg};"
        )

        # Button states
        is_active = task.status == DownloadStatus.DOWNLOADING
        is_paused = task.status in (DownloadStatus.PAUSED, DownloadStatus.ERROR)
        is_done = task.status == DownloadStatus.COMPLETED

        self.btn_pause.setEnabled(is_active)
        self.btn_resume.setEnabled(is_paused)
        self.btn_open_folder.setEnabled(is_done)

        # Stop timer if download is finished
        if is_done or task.status == DownloadStatus.ERROR:
            self._refresh_timer.stop()

    def _on_pause(self):
        self.pause_requested.emit(self._task.id)

    def _on_resume(self):
        self.resume_requested.emit(self._task.id)

    def _on_open_folder(self):
        from udm.storage.file_manager import FileManager
        FileManager.open_file_location(self._task.output_filepath)

    def closeEvent(self, event):
        self._refresh_timer.stop()
        event.accept()
