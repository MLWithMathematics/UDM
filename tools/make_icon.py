"""
Generates udm.ico (used as the .exe icon) from the same programmatic icon the
app draws at runtime. Run from the project root:  python tools/make_icon.py
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication  # noqa: E402
from udm.ui.widgets.system_tray import create_udm_icon  # noqa: E402

app = QApplication(sys.argv)
pixmap = create_udm_icon(256).pixmap(256, 256)
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "udm.ico")

if not pixmap.save(out, "ICO"):
    raise SystemExit("Could not write udm.ico (Qt ICO plugin missing?)")
print(f"Wrote {out}")
