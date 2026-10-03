# -*- mode: python ; coding: utf-8 -*-
#
# UDM — single-file Windows build.
# Build with:  build_exe.bat   (or:  pyinstaller --noconfirm --clean UDM.spec)

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(SPECPATH)

datas = [(os.path.join(ROOT, 'udm', 'ui', 'themes'), 'udm/ui/themes')]
binaries = []
hiddenimports = []


def _collect(pkg):
    """Bundle a package completely (code, data files, native libs)."""
    try:
        d, b, h = collect_all(pkg)
    except Exception as exc:  # package not installed -> skip
        print(f"[UDM.spec] skipping {pkg}: {exc}")
        return
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)


# yt-dlp loads its ~1800 site extractors dynamically; without this the exe
# can only download from a handful of sites. yt_dlp_ejs holds the JS
# challenge solver scripts yt-dlp needs for YouTube.
for pkg in ('yt_dlp', 'yt_dlp_ejs', 'pyqtgraph', 'certifi'):
    _collect(pkg)

# Packages that import submodules dynamically (entry points / lazy imports).
for pkg in ('udm', 'apscheduler', 'websockets', 'httpx', 'httpcore', 'anyio', 'aiohttp'):
    try:
        hiddenimports.extend(collect_submodules(pkg))
    except Exception as exc:
        print(f"[UDM.spec] skipping submodules of {pkg}: {exc}")

hiddenimports += ['aiosqlite', 'aiofiles', 'pyperclip', 'tzlocal']

# Helper tools fetched by build_exe.ps1 into vendor/ — placed in the bundle
# root; run.py puts that folder on PATH so yt-dlp finds them.
for tool in ('ffmpeg.exe', 'ffprobe.exe', 'deno.exe'):
    path = os.path.join(ROOT, 'vendor', tool)
    if os.path.exists(path):
        binaries.append((path, '.'))
    else:
        print(f"[UDM.spec] WARNING: vendor/{tool} not found - not bundled")

icon_path = os.path.join(ROOT, 'udm.ico')

a = Analysis(
    [os.path.join(ROOT, 'run.py')],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='UDM',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX can corrupt ffmpeg/Qt DLLs and triggers antivirus
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path if os.path.exists(icon_path) else None,
)
