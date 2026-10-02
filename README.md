# UDM — Ultimate Download Manager

UDM is a powerful, modern, and open-source download manager built with Python and PyQt6. It provides advanced features like multi-segment downloading, video extraction, clipboard monitoring, and seamless browser integration via WebSockets.

## ✨ Features

- **⚡ Accelerated Downloads:** Multi-connection/multi-segment downloading to maximize your bandwidth.
- **🎬 Video Downloading:** Built-in `yt-dlp` integration allows you to easily download videos from hundreds of supported sites. 
- **🌐 Browser Extension:** Comes with a companion browser extension that communicates directly with UDM via WebSockets to catch your downloads instantly.
- **📋 Clipboard Monitor:** Automatically detects downloadable URLs copied to your clipboard.
- **⏱️ Download Scheduling:** Schedule your downloads to start when you are away or during off-peak hours.
- **📈 Real-time Analytics:** Visual download speed graphs and progress tracking using `pyqtgraph`.
- **🚀 Asynchronous Core:** Built heavily on `aiohttp` and `aiofiles` for high-performance, non-blocking I/O.

## 🛠️ Architecture

UDM is composed of several modules:
- **Core Engine:** Handles the heavy lifting of segmenting files and managing asynchronous downloads.
- **UI:** A sleek graphical interface built on PyQt6.
- **IPC (Inter-Process Communication):** Houses the WebSocket server that bridges the gap between the desktop app and the browser extension.
- **Storage:** SQLite backend (via `aiosqlite`) to persist download history, queues, and configuration.
- **Extension:** A Chrome/Firefox compatible extension for quick download capture.

## 📦 Installation & Setup

### Prerequisites
- Python 3.9+
- `pip` (Python package manager)

### Development Setup
1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/udm.git
   cd udm
   ```

2. **Create and activate a virtual environment (recommended):**
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On Linux/MacOS:
   source venv/bin/activate
   ```

3. **Install the dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run UDM:**
   ```bash
   python run.py
   ```

## 🧩 Browser Extension Setup
To enable one-click downloads from your browser, you need to load the included extension:

1. Open your browser and go to the extensions page (e.g., `chrome://extensions/`).
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select the `extension/` directory from this repository.
5. Make sure UDM desktop app is running so the WebSocket connection can be established!

## 🏗️ Building for Production
You can build a standalone executable for UDM using PyInstaller.

Run the following command to build the `.exe` file:
```powershell
.\venv\Scripts\pyinstaller.exe -y --name "UDM" --windowed --add-data "udm/ui/themes/skyblue.qss;udm/ui/themes" --add-binary "C:\Program Files\Python314\python314.dll;_internal" run.py
```

To create a release `.zip` archive containing the built application:
```powershell
Compress-Archive -Path "dist\UDM" -DestinationPath "dist\UDM_App.zip" -Force
```

The compiled executable will be available in the `dist/UDM/` directory, and the zipped archive as `dist/UDM_App.zip`.

## Version 1

There A Version Without Browser Extension Check it From Software Builds/UDM_App V1.zip

## Version 2
its contains basic extension not support video Downloading from Youtube. It just download Files with help of extension. Software Builds/UDM_App V2 with Extension.zip

## Version 3

Final Version With all the Features Check it From software Builds/UDM_App V3.zip




## 🤝 Contributing
Contributions are welcome! Whether it's reporting a bug, proposing a new feature, or submitting a Pull Request, your help makes UDM better.
1. Fork the project.
2. Create your feature branch (`git checkout -b feature/AmazingFeature`).
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`).
4. Push to the branch (`git push origin feature/AmazingFeature`).
5. Open a Pull Request.

## 📄 License
This project is licensed under the MIT License - see the LICENSE file for details.

Developer : Shubhankar Sharma
