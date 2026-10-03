"""
System tray icon with context menu for UDM.
"""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QLinearGradient, QFont
from PyQt6.QtCore import pyqtSignal, QSize


def _icon_file() -> Path:
    """Location of udm.ico (inside the .exe bundle, or the project root)."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "udm.ico"
    return Path(__file__).resolve().parents[3] / "udm.ico"


def create_udm_icon(px: int = 64, use_file: bool = True) -> QIcon:
    """Return the UDM app icon.

    Uses the real logo (udm.ico) when it is available; otherwise falls back to
    a programmatically drawn icon (sky blue download arrow). `use_file=False`
    forces the drawn version (used by tools/make_icon.py).

    `px` is the rendered pixel size of the drawn fallback; it is defined on a
    64-unit grid and scaled, so larger sizes stay sharp.
    """
    if use_file:
        path = _icon_file()
        if path.exists():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon

    size = 64
    pixmap = QPixmap(px, px)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(px / size, px / size)

    # Background circle
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0, QColor(66, 165, 245))
    gradient.setColorAt(1, QColor(21, 101, 192))
    painter.setBrush(gradient)
    painter.setPen(QColor(0, 0, 0, 0))
    painter.drawEllipse(2, 2, size - 4, size - 4)

    # Down arrow
    painter.setPen(QColor(255, 255, 255))
    painter.setBrush(QColor(255, 255, 255))
    # Arrow body
    painter.drawRect(26, 14, 12, 24)
    # Arrow head (triangle)
    arrow = [
        (32, 50),  # bottom point
        (16, 34),  # left
        (48, 34),  # right
    ]
    from PyQt6.QtGui import QPolygon
    from PyQt6.QtCore import QPoint
    polygon = QPolygon([QPoint(x, y) for x, y in arrow])
    painter.drawPolygon(polygon)

    painter.end()
    return QIcon(pixmap)


class SystemTray(QSystemTrayIcon):
    """System tray icon with context menu."""

    show_window = pyqtSignal()
    hide_window = pyqtSignal()
    pause_all = pyqtSignal()
    resume_all = pyqtSignal()
    exit_app = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIcon(create_udm_icon())
        self.setToolTip("UDM - Ultimate Download Manager")

        # Create context menu
        menu = QMenu()

        show_action = menu.addAction("📂  Show UDM")
        show_action.triggered.connect(self.show_window.emit)

        menu.addSeparator()

        pause_action = menu.addAction("⏸  Pause All")
        pause_action.triggered.connect(self.pause_all.emit)

        resume_action = menu.addAction("▶  Resume All")
        resume_action.triggered.connect(self.resume_all.emit)

        menu.addSeparator()

        exit_action = menu.addAction("✖  Exit")
        exit_action.triggered.connect(self.exit_app.emit)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_window.emit()

    def show_message(self, title: str, message: str, icon=None):
        """Show a system tray notification."""
        self.showMessage(
            title, message,
            icon or QSystemTrayIcon.MessageIcon.Information,
            3000
        )
