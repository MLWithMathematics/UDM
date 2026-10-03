#!/usr/bin/env python3
"""
UDM — Ultimate Download Manager
Launch script.

When running as a PyInstaller .exe (windowed, no console) this also makes the
bundled helper tools (ffmpeg / ffprobe / deno) discoverable and gives stdout /
stderr a harmless sink, so the .exe behaves exactly like `python run.py`.
"""

import multiprocessing
import os
import sys


def _prepare_frozen_environment():
    if not getattr(sys, "frozen", False):
        return

    # Bundled binaries (ffmpeg.exe, ffprobe.exe, deno.exe) live in the
    # extraction dir. yt-dlp looks them up on PATH, so put that dir first.
    bundle_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    os.environ["PATH"] = bundle_dir + os.pathsep + os.environ.get("PATH", "")

    # A windowed (console=False) exe has no stdout/stderr. Libraries that
    # print or log to them would crash, so point them at a null device.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


multiprocessing.freeze_support()
_prepare_frozen_environment()

import yt_dlp  # noqa: E402,F401  (explicit import so PyInstaller bundles it)
from udm.app import main  # noqa: E402

if __name__ == "__main__":
    main()
