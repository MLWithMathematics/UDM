"""
Add Download dialog - lets user configure and add a new download.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QSpinBox, QFileDialog, QGroupBox, QCheckBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from pathlib import Path

from udm.core.segment import FileCategory


class DownloadDialog(QDialog):
    """Dialog for adding a new download."""

    download_requested = pyqtSignal(dict)  # Emits download config dict

    def __init__(self, parent=None, url: str = "", filename: str = "", save_dir: str = "",
                 cookies: str = "", referrer: str = "", user_agent: str = "",
                 category_dirs: dict = None):
        super().__init__(parent)
        self.setWindowTitle("Add New Download")
        self.setMinimumWidth(560)
        self.setModal(True)

        self._save_dir = save_dir
        # Per-category folders (the "categories" section of config.json), so
        # this dialog and the download engine always agree on where each file
        # type goes. Loaded from the config file if the caller didn't pass them.
        self._category_dirs = category_dirs if category_dirs is not None else self._load_category_dirs()
        # Becomes True once the user picks a folder with Browse — from then on
        # their choice is respected and changing the category won't move it.
        self._custom_dir = False
        self.cookies = cookies
        self.referrer = referrer
        self.user_agent = user_agent

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Title
        title = QLabel("⬇  Add New Download")
        title.setObjectName("titleLabel")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        layout.addWidget(title)

        # URL Section
        url_group = QGroupBox("Download URL")
        url_layout = QVBoxLayout(url_group)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://example.com/file.zip")
        self.url_input.setText(url)
        self.url_input.textChanged.connect(self._on_url_changed)
        url_layout.addWidget(self.url_input)

        layout.addWidget(url_group)

        # File Details Section
        details_group = QGroupBox("File Details")
        details_layout = QFormLayout(details_group)
        details_layout.setSpacing(12)

        # Filename
        self.filename_input = QLineEdit()
        self.filename_input.setPlaceholderText("Auto-detected from URL")
        self.filename_input.setText(filename)
        self.filename_input.textChanged.connect(self._on_filename_changed)
        details_layout.addRow("File Name:", self.filename_input)

        # Save location
        save_row = QHBoxLayout()
        self.save_path_input = QLineEdit()
        self.save_path_input.setText(save_dir)
        self.save_path_input.setReadOnly(True)
        save_row.addWidget(self.save_path_input)

        browse_btn = QPushButton("Browse")
        browse_btn.setMaximumWidth(90)
        browse_btn.clicked.connect(self._browse_save_dir)
        save_row.addWidget(browse_btn)
        details_layout.addRow("Save To:", save_row)

        # Category
        self.category_combo = QComboBox()
        for cat in FileCategory:
            self.category_combo.addItem(cat.value)
        self.category_combo.currentTextChanged.connect(self._on_category_changed)
        details_layout.addRow("Category:", self.category_combo)

        layout.addWidget(details_group)
        
        # Initial categorization
        self._on_filename_changed(self.filename_input.text())
        self._on_category_changed(self.category_combo.currentText())

        # Download Settings
        settings_group = QGroupBox("Download Settings")
        settings_layout = QFormLayout(settings_group)
        settings_layout.setSpacing(12)

        # Number of segments
        self.segments_spin = QSpinBox()
        self.segments_spin.setRange(1, 32)
        self.segments_spin.setValue(8)
        self.segments_spin.setToolTip("More segments = faster download (if server supports)")
        settings_layout.addRow("Segments:", self.segments_spin)

        # Start immediately
        self.start_now_check = QCheckBox("Start download immediately")
        self.start_now_check.setChecked(True)
        settings_layout.addRow("", self.start_now_check)

        layout.addWidget(settings_group)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("btnCancel")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        self.download_btn = QPushButton("⬇  Download")
        self.download_btn.setMinimumWidth(140)
        self.download_btn.setDefault(True)
        self.download_btn.clicked.connect(self._on_download)
        btn_layout.addWidget(self.download_btn)

        layout.addLayout(btn_layout)

    def _on_url_changed(self, url: str):
        """Auto-detect filename from URL."""
        if url and not self.filename_input.text():
            from urllib.parse import urlparse, unquote
            from pathlib import Path
            try:
                parsed = urlparse(url)
                name = unquote(Path(parsed.path).name)
                if name and "." in name:
                    self.filename_input.setText(name)
            except Exception:
                pass

    def _on_filename_changed(self, text: str):
        if text:
            from udm.core.segment import detect_category
            cat = detect_category(text)
            self.category_combo.setCurrentText(cat.value)

    @staticmethod
    def _load_category_dirs() -> dict:
        try:
            from udm.storage.config import Config
            return dict(Config().get("categories", {}) or {})
        except Exception:
            return {}

    def _folder_for_category(self, category_text: str) -> str:
        folder = self._category_dirs.get(category_text)
        if folder:
            return str(folder)
        if not self._save_dir:
            return ""
        if category_text == "General":
            return self._save_dir
        return str(Path(self._save_dir) / category_text)

    def _on_category_changed(self, category_text: str):
        if self._custom_dir:
            return
        folder = self._folder_for_category(category_text)
        if folder:
            self.save_path_input.setText(folder)

    def _browse_save_dir(self):
        """Open directory picker."""
        directory = QFileDialog.getExistingDirectory(
            self, "Select Download Directory", self._save_dir
        )
        if directory:
            self.save_path_input.setText(directory)
            self._save_dir = directory
            self._custom_dir = True

    def _on_download(self):
        """Validate and emit download request."""
        url = self.url_input.text().strip()
        if not url:
            self.url_input.setFocus()
            return

        config = {
            "url": url,
            "filename": self.filename_input.text().strip(),
            "save_path": self.save_path_input.text().strip() or self._save_dir,
            "category": self.category_combo.currentText(),
            "num_segments": self.segments_spin.value(),
            "start_immediately": self.start_now_check.isChecked(),
            "cookies": self.cookies,
            "referrer": self.referrer,
            "user_agent": self.user_agent,
        }

        self.download_requested.emit(config)
        self.accept()

    def get_config(self) -> dict:
        """Get the current dialog configuration."""
        return {
            "url": self.url_input.text().strip(),
            "filename": self.filename_input.text().strip(),
            "save_path": self.save_path_input.text().strip() or self._save_dir,
            "category": self.category_combo.currentText(),
            "num_segments": self.segments_spin.value(),
            "start_immediately": self.start_now_check.isChecked(),
            "cookies": self.cookies,
            "referrer": self.referrer,
            "user_agent": self.user_agent,
        }
