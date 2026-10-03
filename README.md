# UDM — Ultimate Download Manager

UDM is a modern, open-source download manager for Windows built with Python and PyQt6. It offers multi-segment accelerated downloads, video downloading via `yt-dlp`, clipboard monitoring, scheduling, and one-click browser integration through a companion extension.

## ✨ Features

- **⚡ Accelerated downloads:** multi-connection, multi-segment downloading to use your full bandwidth.
- **🎬 Video downloading:** built-in `yt-dlp` integration for YouTube and hundreds of other sites, with quality selection and automatic video+audio merging.
- **🌐 Browser extension:** captures downloads and sniffs videos, talking to UDM over a local WebSocket.
- **📋 Clipboard monitor:** detects downloadable URLs you copy.
- **⏱️ Scheduler:** start and stop the queue at set times.
- **📈 Live analytics:** speed graph and per-segment progress bars (`pyqtgraph`).
- **🚀 Async core:** built on `aiohttp` and `aiofiles` for non-blocking I/O.

## 🛠️ Architecture

| Module | Purpose |
|---|---|
| `udm/core` | Segmented download engine, assembler, checksums, speed limiter |
| `udm/network` | HTTP client, proxy and authentication handling |
| `udm/queue` | Download queue, scheduler, state machine |
| `udm/ipc` | WebSocket server for the browser extension, clipboard monitor |
| `udm/video` | `yt-dlp` wrapper for video extraction and download |
| `udm/storage` | Config (`~/.udm/config.json`) and SQLite history (`aiosqlite`) |
| `udm/ui` | PyQt6 windows, dialogs, themes, tray icon |
| `extension/` | Chromium browser extension (Manifest V3) |

---

## 📋 Requirements

### To run or build UDM (Windows)

| Requirement | Details |
|---|---|
| **OS** | Windows 10 / 11, 64-bit |
| **Python** | 3.10 or newer. **3.12 or 3.13 recommended**, especially for building the `.exe` (very new Python releases can lag behind PyInstaller/PyQt6 support) |
| **pip** | Included with Python. Tick **"Add python.exe to PATH"** in the Python installer |
| **Git** | Optional, only needed to clone the repository |
| **PowerShell** | 5.1 or newer (already included in Windows 10/11); used by the build script |
| **Internet** | Needed to install dependencies and, when building, to download ffmpeg and deno |
| **Disk space** | ~1 GB free for the virtual environment and build files |

### Python packages

Installed automatically from `requirements.txt`:

`PyQt6`, `aiohttp`, `aiofiles`, `aiosqlite`, `httpx`, `yt-dlp[default]`, `websockets`, `pyperclip`, `pyqtgraph`, `apscheduler`, `pyinstaller`

### External tools (only when running from source)

These are needed for **video downloads**. The `.exe` build bundles them automatically, so end users of the `.exe` need nothing extra.

| Tool | Why it's needed | Install |
|---|---|---|
| **ffmpeg** (with `ffprobe`) | Merges separate video and audio streams (YouTube above 720p, HLS streams) | `winget install Gyan.FFmpeg`, then restart the terminal. Check with `ffmpeg -version` |
| **deno** | JavaScript runtime that recent `yt-dlp` versions use to solve YouTube challenges | `winget install DenoLand.Deno`. Check with `deno --version` |

Normal (non-video) file downloads work without either tool.

### Browser (for the extension)

Google Chrome, Microsoft Edge, Brave or any other Chromium-based browser (Manifest V3 support required).

---

## 🚀 Run from source

```powershell
# 1. Get the code
git clone https://github.com/yourusername/udm.git
cd udm

# 2. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start UDM
python run.py
```

Install **ffmpeg** and **deno** (see the table above) if you want video downloads.

---

## 🏗️ Build your own `UDM.exe`

You can produce a standalone, single-file `UDM.exe` that has every feature of `python run.py` (video downloads and merging, browser-extension bridge, clipboard monitor, scheduler, tray icon, themes). The build is automated.

### Steps

1. Install **Python 3.12 or 3.13** (64-bit) with "Add python.exe to PATH" ticked. Confirm with `python --version`.
2. Get the project (clone it or download the ZIP) and open its folder.
3. Double-click **`build_exe.bat`**, or run in PowerShell:
   ```powershell
   .\build_exe.ps1
   ```
4. Wait for the build to finish (the first run takes several minutes). Your executable is at:
   ```
   dist\UDM.exe
   ```

### What the build script does

1. Creates `venv` (if missing) and installs `requirements.txt` plus the latest PyInstaller.
2. Downloads `ffmpeg.exe`, `ffprobe.exe` and `deno.exe` into `vendor/` (skipped on later runs if already there).
3. Uses the project logo `udm.ico` as the `.exe` icon and as the app's window/tray icon (it is bundled inside the `.exe`)
4. Runs PyInstaller with `UDM.spec`, which bundles the themes, the full `yt-dlp` extractor set and the helper tools into one windowed `.exe`.

To change the logo, replace `udm.ico` (a multi-size icon with 16, 32, 48, 64, 128 and 256 px) and rebuild. `udm_logo.jpg` is the source artwork.

### Build notes

- **Manual tools:** if the automatic download is blocked (firewall, proxy, offline), place `ffmpeg.exe` and `ffprobe.exe` (and optionally `deno.exe`) in a `vendor/` folder next to `UDM.spec`, then run the build again.
- **First launch is slower:** a single-file `.exe` unpacks itself to a temporary folder when it starts.
- **Antivirus warnings:** unsigned PyInstaller executables are sometimes flagged by Windows Defender or SmartScreen. This is a false positive. Choose "More info → Run anyway", or build it yourself from source.
- **Same data as source mode:** the `.exe` and `python run.py` share `~/.udm` (config, history database, pairing token, logs at `~/.udm/logs/udm.log`). Check the log first if something misbehaves.
- **Shipping a release:** copy `dist\UDM.exe` into the `Software Builds` folder with a versioned name (for example `UDM V4.exe`) so users can download it straight from the repository.

### Troubleshooting

| Problem | Fix |
|---|---|
| `python` is not recognized | Reinstall Python and tick "Add python.exe to PATH", or use the full path to `python.exe` |
| Build fails while installing packages | Python version too new or unsupported. Delete the `venv` folder and rebuild with Python 3.12 or 3.13 |
| PowerShell blocks the script | Use `build_exe.bat` (it bypasses the execution policy for this one script) |
| YouTube or merged videos fail in the `.exe` | Make sure `vendor\ffmpeg.exe` and `vendor\deno.exe` exist, delete `build/` and `dist/`, and rebuild |
| `.exe` closes immediately | Read `~/.udm/logs/udm.log`. Also make sure another UDM instance isn't already running (check the system tray) |

---

## 🧩 Browser extension setup

1. Start UDM (the `.exe` or `python run.py`). It must be running for the extension to connect.
2. Open `chrome://extensions/` (or `edge://extensions/`) in your browser.
3. Turn on **Developer mode**.
4. Click **Load unpacked** and select the `extension/` folder from this repository.
5. In UDM, open **Settings → General** and copy the **pairing token**.
6. Click the UDM extension icon in your browser toolbar and paste the token into the token field.

The pairing token stops other local web pages from sending downloads to UDM.

---

## 📦 Download prebuilt versions

Ready-to-run builds are in the [`Software Builds`](Software%20Builds) folder. Open a file and click **Download** (or **Download raw file**).

- **UDM V3.exe:** latest, all features including YouTube and other video sites. Just run it, no install needed.
- **UDM_App V2 with Extension.zip:** basic extension; downloads files only, no video support.
- **UDM_App V1.zip:** no browser extension.

If a prebuilt `.exe` won't run on your machine, build your own using the steps above.

## 🤝 Contributing

Contributions are welcome! Whether it's reporting a bug, proposing a feature or submitting a pull request, your help makes UDM better.

1. Fork the project.
2. Create your feature branch (`git checkout -b feature/AmazingFeature`).
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`).
4. Push to the branch (`git push origin feature/AmazingFeature`).
5. Open a pull request.

## 📄 License

This project is licensed under the MIT License. See the LICENSE file for details.

Developer: Shubhankar Sharma
