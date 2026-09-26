"""
Real-time download speed graph widget using pyqtgraph.
"""

from collections import deque
import time

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

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
        self._plot.setBackground("#f0f8ff")
        self._plot.setLabel("left", "Speed", units="KB/s")
        self._plot.setLabel("bottom", "Time", units="s")
        self._plot.showGrid(x=True, y=True, alpha=0.3)

        # Style the plot
        self._plot.getAxis("left").setPen(pg.mkPen(color="#1565c0", width=1))
        self._plot.getAxis("bottom").setPen(pg.mkPen(color="#1565c0", width=1))
        self._plot.getAxis("left").setTextPen(pg.mkPen(color="#1565c0"))
        self._plot.getAxis("bottom").setTextPen(pg.mkPen(color="#1565c0"))

        # Create the line
        pen = pg.mkPen(color="#42a5f5", width=2)
        self._curve = self._plot.plot(pen=pen)

        # Fill under curve
        self._fill = pg.FillBetweenItem(
            self._curve,
            pg.PlotDataItem([0], [0]),
            brush=pg.mkBrush(66, 165, 245, 50),
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
