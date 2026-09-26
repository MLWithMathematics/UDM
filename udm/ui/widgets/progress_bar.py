"""
Custom segmented progress bar widget.
Shows individual segment progress like IDM's detailed view.
Color coded: green (done), blue (active), gray (pending), red (error).
"""

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QFont, QPen, QBrush

from udm.core.segment import Segment, SegmentStatus, DownloadTask


# Segment status colors
STATUS_COLORS = {
    SegmentStatus.DONE: {
        "start": QColor(76, 175, 80),    # Green
        "end": QColor(56, 142, 60),
    },
    SegmentStatus.ACTIVE: {
        "start": QColor(66, 165, 245),   # Blue
        "end": QColor(30, 136, 229),
    },
    SegmentStatus.PENDING: {
        "start": QColor(189, 189, 189),  # Gray
        "end": QColor(158, 158, 158),
    },
    SegmentStatus.PAUSED: {
        "start": QColor(255, 183, 77),   # Orange
        "end": QColor(255, 152, 0),
    },
    SegmentStatus.ERROR: {
        "start": QColor(239, 83, 80),    # Red
        "end": QColor(229, 57, 53),
    },
}

BACKGROUND_COLOR = QColor(224, 224, 224, 80)
BORDER_COLOR = QColor(187, 222, 251, 150)
TEXT_COLOR = QColor(255, 255, 255)
SEPARATOR_COLOR = QColor(255, 255, 255, 100)


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
        self._animation_offset = 0
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

        # Background
        painter.setPen(QPen(BORDER_COLOR, 1))
        painter.setBrush(QBrush(BACKGROUND_COLOR))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        if not self._task or not self._task.segments:
            # Draw empty state
            if self._show_text:
                painter.setPen(QColor(120, 144, 156))
                painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "0%")
            painter.end()
            return

        # Calculate overall progress
        task = self._task
        total = task.total_size if task.total_size > 0 else 1
        overall_progress = min(task.downloaded_size / total, 1.0)

        if self._show_segments and len(task.segments) > 1:
            self._draw_segmented(painter, rect, radius)
        else:
            self._draw_simple(painter, rect, radius, overall_progress)

        # Draw percentage text
        if self._show_text:
            pct = overall_progress * 100
            text = f"{pct:.1f}%"
            painter.setPen(Qt.PenStyle.NoPen)

            # Shadow behind text
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            shadow_rect = rect.adjusted(1, 1, 1, 1)
            painter.setPen(QColor(0, 0, 0, 80))
            painter.drawText(shadow_rect, Qt.AlignmentFlag.AlignCenter, text)

            # Actual text
            painter.setPen(TEXT_COLOR if overall_progress > 0.5 else QColor(26, 58, 92))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

        painter.end()

    def _draw_segmented(self, painter: QPainter, rect: QRectF, radius: float):
        """Draw individual segment blocks."""
        task = self._task
        total_bytes = task.total_size if task.total_size > 0 else 1
        w = rect.width() - 2  # account for border
        h = rect.height() - 2
        x_offset = 1

        for i, seg in enumerate(task.segments):
            seg_width = (seg.total_bytes / total_bytes) * w
            if seg_width < 1:
                continue

            # Calculate segment fill based on its own progress
            fill_ratio = seg.downloaded_bytes / seg.total_bytes if seg.total_bytes > 0 else 0
            fill_width = seg_width * fill_ratio

            if fill_width > 0:
                colors = STATUS_COLORS.get(seg.status, STATUS_COLORS[SegmentStatus.PENDING])
                gradient = QLinearGradient(x_offset, 0, x_offset, h)
                gradient.setColorAt(0, colors["start"])
                gradient.setColorAt(1, colors["end"])

                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(gradient))

                # Clip to the overall rounded rect
                fill_rect = QRectF(x_offset, 1, fill_width, h)

                # Handle rounded corners for first and last segment
                if i == 0 and i == len(task.segments) - 1:
                    painter.drawRoundedRect(fill_rect, radius, radius)
                elif i == 0:
                    painter.drawRoundedRect(
                        QRectF(fill_rect.x(), fill_rect.y(),
                               fill_rect.width() + radius, fill_rect.height()),
                        radius, radius
                    )
                    if fill_width < seg_width:
                        painter.drawRect(
                            QRectF(fill_rect.x() + radius, fill_rect.y(),
                                   fill_rect.width() - radius, fill_rect.height())
                        )
                elif i == len(task.segments) - 1 and fill_ratio >= 0.95:
                    painter.drawRoundedRect(fill_rect, radius, radius)
                else:
                    painter.drawRect(fill_rect)

            # Draw segment separator
            if i > 0:
                painter.setPen(QPen(SEPARATOR_COLOR, 1))
                painter.drawLine(
                    int(x_offset), 2,
                    int(x_offset), int(h)
                )

            x_offset += seg_width

    def _draw_simple(self, painter: QPainter, rect: QRectF, radius: float, progress: float):
        """Draw a simple single-bar progress."""
        if progress <= 0:
            return

        w = rect.width() - 2
        h = rect.height() - 2
        fill_width = w * progress

        gradient = QLinearGradient(0, 0, fill_width, 0)
        gradient.setColorAt(0, QColor(66, 165, 245))
        gradient.setColorAt(0.5, QColor(41, 182, 246))
        gradient.setColorAt(1, QColor(38, 198, 218))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(
            QRectF(1, 1, fill_width, h),
            radius, radius
        )
