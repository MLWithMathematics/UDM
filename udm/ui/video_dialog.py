"""
Video Download Dialog - Paste a YouTube (or other) URL, pick quality, and download.
Integrates with yt-dlp for format extraction.
"""

import asyncio
import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QGroupBox, QProgressBar, QTextEdit, QFileDialog,
    QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSlot
from PyQt6.QtGui import QFont

from udm.video.grabber import VideoGrabber, VideoFormat

logger = logging.getLogger("udm.ui.video_dialog")


class FormatFetchWorker(QThread):
    """Background thread to fetch available video formats via yt-dlp."""
    formats_ready = pyqtSignal(list)        # list of VideoFormat
    error_occurred = pyqtSignal(str)         # error message
    info_ready = pyqtSignal(str, str)        # (title, thumbnail_url)

    def __init__(self, url: str):
        super().__init__()
        self.url = url
        self._grabber = VideoGrabber()

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Get formats
            formats = loop.run_until_complete(self._grabber.get_formats(self.url))
            if not formats:
                self.error_occurred.emit("No downloadable formats found. Check the URL.")
                return

            # Get video info for title
            info = loop.run_until_complete(self._grabber.get_direct_url(self.url, "best"))
            if info:
                self.info_ready.emit(info.get("title", ""), "")

            self.formats_ready.emit(formats)
            loop.close()
        except Exception as e:
            self.error_occurred.emit(str(e))


class VideoDownloadWorker(QThread):
    """Background thread to download a video via yt-dlp."""
    progress_update = pyqtSignal(str)    # progress line from yt-dlp
    download_finished = pyqtSignal(str)  # output filepath
    error_occurred = pyqtSignal(str)     # error message

    def __init__(self, url: str, output_dir: str, format_id: str = "best"):
        super().__init__()
        self.url = url
        self.output_dir = output_dir
        self.format_id = format_id
        self._grabber = VideoGrabber()

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            def on_progress(line):
                self.progress_update.emit(line)

            result = loop.run_until_complete(
                self._grabber.download_video(
                    self.url, self.output_dir, self.format_id, on_progress
                )
            )
            loop.close()

            if result:
                self.download_finished.emit(result)
            else:
                self.error_occurred.emit("Download failed. Check the URL and try again.")

        except Exception as e:
            self.error_occurred.emit(str(e))


class VideoDownloadDialog(QDialog):
    """
    Dialog for downloading videos from YouTube and 1000+ other sites.
    
    Workflow:
    1. User pastes a video URL
    2. Click "Fetch Formats" → yt-dlp extracts available qualities
    3. User picks quality from dropdown
    4. Click "Download" → yt-dlp downloads the video
    """

    def __init__(self, parent=None, save_dir: str = ""):
        super().__init__(parent)
        self.setWindowTitle("🎬  Download Video")
        self.setMinimumWidth(600)
        self.setMinimumHeight(480)
        self.setModal(True)

        self._save_dir = save_dir
        self._formats: list[VideoFormat] = []
        self._fetch_worker: Optional[FormatFetchWorker] = None
        self._download_worker: Optional[VideoDownloadWorker] = None
        self._video_title = ""

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        # ─── Title ────────────────────────────────────
        title = QLabel("🎬  Download Video")
        title.setObjectName("titleLabel")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel("Supports YouTube, Vimeo, Dailymotion, Twitter, Instagram, and 1000+ sites")
        subtitle.setObjectName("subtitleLabel")
        subtitle.setStyleSheet("color: #546e7a; font-size: 12px; margin-bottom: 8px;")
        layout.addWidget(subtitle)

        # ─── URL Input ────────────────────────────────
        url_group = QGroupBox("Video URL")
        url_layout = QHBoxLayout(url_group)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")
        self.url_input.returnPressed.connect(self._on_fetch_formats)
        url_layout.addWidget(self.url_input)

        self.fetch_btn = QPushButton("🔍  Fetch Formats")
        self.fetch_btn.setMinimumWidth(140)
        self.fetch_btn.clicked.connect(self._on_fetch_formats)
        url_layout.addWidget(self.fetch_btn)

        layout.addWidget(url_group)

        # ─── Video Info ───────────────────────────────
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: #1565c0; padding: 4px 0;"
        )
        self.info_label.setVisible(False)
        layout.addWidget(self.info_label)

        # ─── Quality Selection ────────────────────────
        quality_group = QGroupBox("Quality & Save Location")
        quality_layout = QFormLayout(quality_group)
        quality_layout.setSpacing(12)

        self.quality_combo = QComboBox()
        self.quality_combo.setEnabled(False)
        self.quality_combo.addItem("← Fetch formats first")
        quality_layout.addRow("Quality:", self.quality_combo)

        # Save location
        save_row = QHBoxLayout()
        self.save_path_input = QLineEdit()
        self.save_path_input.setText(self._save_dir)
        self.save_path_input.setReadOnly(True)
        save_row.addWidget(self.save_path_input)

        browse_btn = QPushButton("Browse")
        browse_btn.setMaximumWidth(90)
        browse_btn.clicked.connect(self._browse_save_dir)
        save_row.addWidget(browse_btn)
        quality_layout.addRow("Save To:", save_row)

        layout.addWidget(quality_group)

        # ─── Progress ────────────────────────────────
        progress_group = QGroupBox("Download Progress")
        progress_layout = QVBoxLayout(progress_group)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Ready")
        progress_layout.addWidget(self.progress_bar)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(120)
        self.log_output.setStyleSheet(
            "background: rgba(255,255,255,0.9); border: 1px solid #bbdefb; "
            "border-radius: 6px; font-family: 'Consolas', monospace; font-size: 11px; "
            "color: #37474f; padding: 6px;"
        )
        self.log_output.setPlaceholderText("Download log will appear here...")
        progress_layout.addWidget(self.log_output)

        layout.addWidget(progress_group)

        # ─── Buttons ─────────────────────────────────
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Close")
        cancel_btn.setObjectName("btnCancel")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.close)
        btn_layout.addWidget(cancel_btn)

        self.download_btn = QPushButton("⬇  Download Video")
        self.download_btn.setMinimumWidth(160)
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._on_download)
        btn_layout.addWidget(self.download_btn)

        layout.addLayout(btn_layout)

    # ─── Fetch Formats ────────────────────────────────────

    def _on_fetch_formats(self):
        url = self.url_input.text().strip()
        if not url:
            self.url_input.setFocus()
            return

        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("⏳  Fetching...")
        self.quality_combo.clear()
        self.quality_combo.addItem("Loading formats...")
        self.quality_combo.setEnabled(False)
        self.download_btn.setEnabled(False)
        self.progress_bar.setFormat("Fetching available formats...")
        self.progress_bar.setValue(0)
        self.log_output.append(f"🔍 Fetching formats for: {url}")

        self._fetch_worker = FormatFetchWorker(url)
        self._fetch_worker.formats_ready.connect(self._on_formats_ready)
        self._fetch_worker.error_occurred.connect(self._on_fetch_error)
        self._fetch_worker.info_ready.connect(self._on_info_ready)
        self._fetch_worker.start()

    @pyqtSlot(str, str)
    def _on_info_ready(self, title: str, thumbnail: str):
        self._video_title = title
        if title:
            self.info_label.setText(f"🎬  {title}")
            self.info_label.setVisible(True)

    @pyqtSlot(list)
    def _on_formats_ready(self, formats: list):
        self._formats = formats
        self.quality_combo.clear()

        # Add a "Best Quality (Recommended)" option first
        self.quality_combo.addItem("🏆  Best Quality (Recommended)", "best")

        # Add best video+audio combined
        self.quality_combo.addItem("📹  Best Video + Audio", "bestvideo+bestaudio/best")

        # Group and add individual formats
        video_formats = []
        audio_formats = []

        for fmt in formats:
            if not fmt.format_id:
                continue
            label = str(fmt)
            if any(kw in fmt.note.lower() for kw in ["audio", "m4a", "mp3", "opus", "aac"]):
                audio_formats.append((label, fmt.format_id))
            elif fmt.resolution and fmt.resolution != "audio only":
                video_formats.append((label, fmt.format_id))

        # Add video formats
        if video_formats:
            self.quality_combo.insertSeparator(self.quality_combo.count())
            for label, fid in video_formats[-10:]:  # Last 10 (highest quality)
                self.quality_combo.addItem(f"🎥  {label}", fid)

        # Add audio-only formats
        if audio_formats:
            self.quality_combo.insertSeparator(self.quality_combo.count())
            self.quality_combo.addItem("🎵  Best Audio Only", "bestaudio")
            for label, fid in audio_formats[-5:]:
                self.quality_combo.addItem(f"🎵  {label}", fid)

        self.quality_combo.setEnabled(True)
        self.download_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("🔍  Fetch Formats")
        self.progress_bar.setFormat("Ready to download")

        self.log_output.append(f"✅ Found {len(formats)} available formats")

    @pyqtSlot(str)
    def _on_fetch_error(self, error: str):
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("🔍  Fetch Formats")
        self.quality_combo.clear()
        self.quality_combo.addItem("❌ Failed to fetch")
        self.progress_bar.setFormat("Error")
        self.log_output.append(f"❌ Error: {error}")

        QMessageBox.warning(self, "Fetch Failed", f"Could not fetch video formats:\n\n{error}")

    # ─── Download ─────────────────────────────────────────

    def _on_download(self):
        url = self.url_input.text().strip()
        if not url:
            return

        format_id = self.quality_combo.currentData()
        if not format_id:
            format_id = "best"

        save_dir = self.save_path_input.text().strip() or self._save_dir

        self.download_btn.setEnabled(False)
        self.download_btn.setText("⏳  Downloading...")
        self.fetch_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Starting download...")
        self.log_output.append(f"⬇ Starting download: format={format_id}")

        self._download_worker = VideoDownloadWorker(url, save_dir, format_id)
        self._download_worker.progress_update.connect(self._on_progress)
        self._download_worker.download_finished.connect(self._on_download_finished)
        self._download_worker.error_occurred.connect(self._on_download_error)
        self._download_worker.start()

    @pyqtSlot(str)
    def _on_progress(self, line: str):
        self.log_output.append(line)
        # Auto-scroll to bottom
        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        # Parse percentage from yt-dlp output like "[download]  45.2% of 100.0MiB"
        if "%" in line:
            try:
                pct_str = line.split("%")[0].split()[-1]
                pct = float(pct_str)
                self.progress_bar.setValue(int(pct))
                self.progress_bar.setFormat(f"Downloading... {pct:.1f}%")
            except (ValueError, IndexError):
                pass

    @pyqtSlot(str)
    def _on_download_finished(self, filepath: str):
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("✅ Download Complete!")
        self.log_output.append(f"\n✅ Download complete!")
        self.log_output.append(f"📁 Saved to: {self.save_path_input.text()}")

        self.download_btn.setEnabled(True)
        self.download_btn.setText("⬇  Download Video")
        self.fetch_btn.setEnabled(True)

        QMessageBox.information(
            self, "Download Complete",
            f"✅ Video downloaded successfully!\n\nSaved to:\n{self.save_path_input.text()}"
        )

    @pyqtSlot(str)
    def _on_download_error(self, error: str):
        self.progress_bar.setFormat("❌ Error")
        self.log_output.append(f"\n❌ Download failed: {error}")

        self.download_btn.setEnabled(True)
        self.download_btn.setText("⬇  Download Video")
        self.fetch_btn.setEnabled(True)

        QMessageBox.warning(self, "Download Failed", f"Video download failed:\n\n{error}")

    # ─── Helpers ──────────────────────────────────────────

    def _browse_save_dir(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Select Save Directory", self._save_dir
        )
        if directory:
            self.save_path_input.setText(directory)
            self._save_dir = directory
