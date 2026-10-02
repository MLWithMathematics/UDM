"""
Custom segmented progress bar widget.
Shows individual segment progress like IDM's detailed view.
Styled for Fluent Light theme.
"""

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QFont, QPen, QBrush

from udm.core.segment import Segment, SegmentStatus, DownloadTask

# Fluent Design Colors
STATUS_COLORS = {
    SegmentStatus.DONE: QColor(0, 120, 212),       # Fluent Blue (Completed)
    SegmentStatus.ACTIVE: QColor(100, 180, 250),   # Light Blue (Downloading)
    SegmentStatus.PENDING: QColor(220, 220, 220),  # Light Gray
    SegmentStatus.PAUSED: QColor(255, 170, 0),     # Orange
    SegmentStatus.ERROR: QColor(232, 17, 35),      # Fluent Red
}

BACKGROUND_COLOR = QColor(0, 0, 0, 15)
BORDER_COLOR = QColor(0, 0, 0, 20)
TEXT_COLOR_DARK = QColor(26, 26, 26)
TEXT_COLOR_LIGHT = QColor(255, 255, 255)


class SegmentedProgressBar(QWidget):
    """
    Custom progress bar that shows per-segment progress.
    Each segment is drawn as a separate colored block.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._task: DownloadTask = None
        self._show_text = True
        self._show_segments = True
        self.setMinimumHeight(24)
        self.setMaximumHeight(28)

    def set_task(self, task: DownloadTask):
        """Update the task and repaint."""
        self._task = task
        self.update()

    def set_show_text(self, show: bool):
        self._show_text = show
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        rect = QRectF(0, 0, w, h)
        radius = h / 2

        # Draw Background
        painter.setPen(QPen(BORDER_COLOR, 1))
        painter.setBrush(QBrush(BACKGROUND_COLOR))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        if not self._task or not self._task.segments:
            # Draw empty state
            if self._show_text:
                painter.setPen(TEXT_COLOR_DARK)
                painter.setFont(QFont("Segoe UI Variable", 9, QFont.Weight.DemiBold))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "0%")
            painter.end()
            return

        # Calculate overall progress
        task = self._task
        total = task.total_size if task.total_size > 0 else 1
        overall_progress = min(task.downloaded_size / total, 1.0)

        # Create clipping path for perfectly rounded segments
        clip_path = QPainterPath()
        clip_path.addRoundedRect(rect.adjusted(1, 1, -1, -1), radius - 0.5, radius - 0.5)
        painter.setClipPath(clip_path)

        if self._show_segments and len(task.segments) > 1:
            self._draw_segmented(painter, rect)
        else:
            self._draw_simple(painter, rect, overall_progress)

        # Remove clipping for text
        painter.setClipping(False)

        # Draw percentage text
        if self._show_text:
            pct = overall_progress * 100
            text = f"{pct:.1f}%"
            painter.setFont(QFont("Segoe UI Variable", 9, QFont.Weight.DemiBold))
            
            # Text color depends on progress (white if mostly filled, dark if mostly empty)
            painter.setPen(TEXT_COLOR_LIGHT if overall_progress > 0.55 else TEXT_COLOR_DARK)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

        painter.end()

    def _draw_segmented(self, painter: QPainter, rect: QRectF):
        """Draw individual segment blocks."""
        task = self._task
        total_bytes = task.total_size if task.total_size > 0 else 1
        w = rect.width() - 2
        h = rect.height() - 2
        x_offset = 1

        for seg in sorted(task.segments, key=lambda s: s.start_byte):
            seg_width = (seg.total_bytes / total_bytes) * w
            if seg_width < 0.5:
                continue

            fill_ratio = seg.downloaded_bytes / seg.total_bytes if seg.total_bytes > 0 else 0
            fill_width = seg_width * fill_ratio

            if fill_width > 0:
                color = STATUS_COLORS.get(seg.status, STATUS_COLORS[SegmentStatus.PENDING])
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(color))
                fill_rect = QRectF(x_offset, 1, fill_width, h)
                painter.drawRect(fill_rect)

            x_offset += seg_width

    def _draw_simple(self, painter: QPainter, rect: QRectF, progress: float):
        """Draw a simple single-bar progress."""
        if progress <= 0:
            return

        w = rect.width() - 2
        h = rect.height() - 2
        fill_width = w * progress

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(STATUS_COLORS[SegmentStatus.ACTIVE]))
        painter.drawRect(QRectF(1, 1, fill_width, h))
