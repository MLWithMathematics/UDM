"""
Real-time download speed graph widget using pyqtgraph.
"""

from collections import deque
import time

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QLinearGradient, QBrush, QColor

try:
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False


class SpeedGraph(QWidget):
    """
    Real-time line chart showing download speed over time.
    Falls back to text display if pyqtgraph is not available.
    """

    MAX_POINTS = 120  # 2 minutes at 1 update/sec

    def __init__(self, parent=None):
        super().__init__(parent)
        self._speed_data = deque(maxlen=self.MAX_POINTS)
        self._time_data = deque(maxlen=self.MAX_POINTS)
        self._start_time = time.monotonic()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if HAS_PYQTGRAPH:
            self._setup_graph(layout)
        else:
            self._speed_label = QLabel("Speed: 0 KB/s")
            self._speed_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
            self._speed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self._speed_label)

    def _setup_graph(self, layout):
        """Set up pyqtgraph plot widget."""
        pg.setConfigOptions(antialias=True)

        self._plot = pg.PlotWidget()
        self._plot.setBackground("transparent")  # Fluent background
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.setMenuEnabled(False)
        self._plot.hideButtons()
        
        # Minimalist sparkline style
        self._plot.getAxis("bottom").hide()
        self._plot.getAxis("left").setPen(pg.mkPen(color=QColor(0,0,0,0)))
        self._plot.getAxis("left").setTextPen(pg.mkPen(color=QColor(150, 150, 150)))
        self._plot.showGrid(x=False, y=True, alpha=0.1)

        # Create the line
        pen = pg.mkPen(color="#0078d4", width=3)  # Fluent Blue
        self._curve = self._plot.plot(pen=pen)

        # Fill under curve with gradient
        gradient = QLinearGradient(0, 0, 0, 1)
        gradient.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectMode)
        gradient.setColorAt(0, QColor(0, 120, 212, 80))
        gradient.setColorAt(1, QColor(0, 120, 212, 0))

        self._fill = pg.FillBetweenItem(
            self._curve,
            pg.PlotDataItem([0], [0]),
            brush=QBrush(gradient),
            pen=None
        )
        self._plot.addItem(self._fill)

        layout.addWidget(self._plot)

    def update_speed(self, speed_bytes_per_sec: float):
        """Add a new speed data point."""
        now = time.monotonic() - self._start_time
        speed_kb = speed_bytes_per_sec / 1024

        self._time_data.append(now)
        self._speed_data.append(speed_kb)

        if HAS_PYQTGRAPH:
            self._curve.setData(list(self._time_data), list(self._speed_data))
        else:
            if speed_kb >= 1024:
                text = f"Speed: {speed_kb / 1024:.1f} MB/s"
            else:
                text = f"Speed: {speed_kb:.0f} KB/s"
            self._speed_label.setText(text)

    def reset(self):
        """Clear the graph."""
        self._speed_data.clear()
        self._time_data.clear()
        self._start_time = time.monotonic()
        if HAS_PYQTGRAPH:
            self._curve.setData([], [])
