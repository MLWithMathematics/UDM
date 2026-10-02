"""
Settings dialog - configure proxy, speed limits, scheduler, and general preferences.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QSpinBox, QCheckBox, QGroupBox, QTabWidget,
    QWidget, QFileDialog, QApplication, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from udm.storage.config import Config


class SettingsDialog(QDialog):
    """Settings dialog with tabs for General, Downloads, Speed, Proxy, and Scheduler."""

    settings_changed = pyqtSignal()

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("UDM Settings")
        self.setMinimumSize(520, 480)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title = QLabel("⚙  Settings")
        title.setObjectName("titleLabel")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        layout.addWidget(title)

        # Tab widget
        tabs = QTabWidget()
        tabs.addTab(self._create_general_tab(), "General")
        tabs.addTab(self._create_download_tab(), "Downloads")
        tabs.addTab(self._create_speed_tab(), "Speed")
        tabs.addTab(self._create_proxy_tab(), "Proxy")
        tabs.addTab(self._create_scheduler_tab(), "Scheduler")
        layout.addWidget(tabs)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("btnCancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("💾  Save Settings")
        save_btn.clicked.connect(self._save_settings)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    def _create_general_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(12)

        # Default save directory
        save_row = QHBoxLayout()
        self.save_dir_input = QLineEdit(
            self.config.get("general.default_save_dir", "")
        )
        save_row.addWidget(self.save_dir_input)
        browse_btn = QPushButton("Browse")
        browse_btn.setMaximumWidth(90)
        browse_btn.clicked.connect(self._browse_default_dir)
        save_row.addWidget(browse_btn)
        layout.addRow("Default Save Directory:", save_row)

        # Start minimized
        self.start_minimized = QCheckBox()
        self.start_minimized.setChecked(
            self.config.get("general.start_minimized", False)
        )
        layout.addRow("Start Minimized:", self.start_minimized)

        # Minimize to tray
        self.minimize_to_tray = QCheckBox()
        self.minimize_to_tray.setChecked(
            self.config.get("general.minimize_to_tray", True)
        )
        layout.addRow("Minimize to Tray:", self.minimize_to_tray)

        # Show notifications
        self.show_notifications = QCheckBox()
        self.show_notifications.setChecked(
            self.config.get("general.show_notifications", True)
        )
        layout.addRow("Show Notifications:", self.show_notifications)

        # Auto start download
        self.auto_start = QCheckBox()
        self.auto_start.setChecked(
            self.config.get("general.auto_start_download", True)
        )
        layout.addRow("Auto-start Downloads:", self.auto_start)

        # --- Browser extension pairing token ---
        token_group = QGroupBox("Browser Extension")
        token_layout = QVBoxLayout(token_group)

        token_hint = QLabel(
            "Paste this token into the UDM extension's popup so it can "
            "talk to this app. Without it, downloads from the browser "
            "will be rejected."
        )
        token_hint.setWordWrap(True)
        token_layout.addWidget(token_hint)

        token_row = QHBoxLayout()
        self.token_display = QLineEdit(self.config.get("security.pairing_token", ""))
        self.token_display.setReadOnly(True)
        token_row.addWidget(self.token_display)

        copy_btn = QPushButton("Copy")
        copy_btn.setMaximumWidth(70)
        copy_btn.clicked.connect(self._copy_token)
        token_row.addWidget(copy_btn)

        regen_btn = QPushButton("Regenerate")
        regen_btn.setMaximumWidth(100)
        regen_btn.clicked.connect(self._regenerate_token)
        token_row.addWidget(regen_btn)

        token_layout.addLayout(token_row)
        layout.addRow(token_group)

        return widget

    def _copy_token(self):
        QApplication.clipboard().setText(self.token_display.text())

    def _regenerate_token(self):
        reply = QMessageBox.question(
            self,
            "Regenerate Pairing Token",
            "This invalidates the current token — you'll need to paste the "
            "new one into the extension popup again. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            new_token = self.config.regenerate_pairing_token()
            self.token_display.setText(new_token)

    def _create_download_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(12)

        # Max concurrent downloads
        self.max_concurrent = QSpinBox()
        self.max_concurrent.setRange(1, 10)
        self.max_concurrent.setValue(
            self.config.get("download.max_concurrent_downloads", 3)
        )
        layout.addRow("Max Concurrent Downloads:", self.max_concurrent)

        # Default segments
        self.default_segments = QSpinBox()
        self.default_segments.setRange(1, 32)
        self.default_segments.setValue(
            self.config.get("download.default_segments", 8)
        )
        layout.addRow("Default Segments:", self.default_segments)

        # Retry count
        self.retry_count = QSpinBox()
        self.retry_count.setRange(0, 10)
        self.retry_count.setValue(
            self.config.get("download.retry_count", 3)
        )
        layout.addRow("Retry Count:", self.retry_count)

        return widget

    def _create_speed_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(12)

        speed_group = QGroupBox("Global Speed Limit")
        speed_layout = QFormLayout(speed_group)

        self.speed_limit = QSpinBox()
        self.speed_limit.setRange(0, 100000)
        self.speed_limit.setSuffix(" KB/s")
        self.speed_limit.setSpecialValueText("Unlimited")
        current_limit = self.config.get("speed.global_limit_bytes_per_sec", 0)
        self.speed_limit.setValue(current_limit // 1024 if current_limit > 0 else 0)
        speed_layout.addRow("Max Speed:", self.speed_limit)

        layout.addRow(speed_group)
        return widget

    def _create_proxy_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(12)

        self.proxy_enabled = QCheckBox()
        self.proxy_enabled.setChecked(
            self.config.get("proxy.enabled", False)
        )
        layout.addRow("Enable Proxy:", self.proxy_enabled)

        self.proxy_type = QComboBox()
        self.proxy_type.addItems(["HTTP", "HTTPS", "SOCKS5"])
        current_type = self.config.get("proxy.type", "http").upper()
        idx = self.proxy_type.findText(current_type)
        if idx >= 0:
            self.proxy_type.setCurrentIndex(idx)
        layout.addRow("Proxy Type:", self.proxy_type)

        self.proxy_host = QLineEdit(self.config.get("proxy.host", ""))
        self.proxy_host.setPlaceholderText("proxy.example.com")
        layout.addRow("Host:", self.proxy_host)

        self.proxy_port = QSpinBox()
        self.proxy_port.setRange(0, 65535)
        self.proxy_port.setValue(self.config.get("proxy.port", 0))
        layout.addRow("Port:", self.proxy_port)

        self.proxy_username = QLineEdit(self.config.get("proxy.username", ""))
        self.proxy_username.setPlaceholderText("Optional")
        layout.addRow("Username:", self.proxy_username)

        self.proxy_password = QLineEdit(self.config.get("proxy.password", ""))
        self.proxy_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.proxy_password.setPlaceholderText("Optional")
        layout.addRow("Password:", self.proxy_password)

        return widget

    def _create_scheduler_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(12)

        self.sched_enabled = QCheckBox()
        self.sched_enabled.setChecked(
            self.config.get("scheduler.enabled", False)
        )
        layout.addRow("Enable Scheduler:", self.sched_enabled)

        self.sched_start = QLineEdit(
            self.config.get("scheduler.start_time", "02:00")
        )
        self.sched_start.setPlaceholderText("HH:MM (e.g. 02:00)")
        layout.addRow("Start Time:", self.sched_start)

        self.sched_stop = QLineEdit(
            self.config.get("scheduler.stop_time", "06:00")
        )
        self.sched_stop.setPlaceholderText("HH:MM (e.g. 06:00)")
        layout.addRow("Stop Time:", self.sched_stop)

        self.sched_shutdown = QCheckBox()
        self.sched_shutdown.setChecked(
            self.config.get("scheduler.shutdown_after_complete", False)
        )
        layout.addRow("Shutdown After Complete:", self.sched_shutdown)

        return widget

    def _browse_default_dir(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Select Default Download Directory",
            self.save_dir_input.text()
        )
        if directory:
            self.save_dir_input.setText(directory)

    def _save_settings(self):
        """Save all settings to config."""
        # General
        self.config.set("general.default_save_dir", self.save_dir_input.text())
        self.config.set("general.start_minimized", self.start_minimized.isChecked())
        self.config.set("general.minimize_to_tray", self.minimize_to_tray.isChecked())
        self.config.set("general.show_notifications", self.show_notifications.isChecked())
        self.config.set("general.auto_start_download", self.auto_start.isChecked())

        # Downloads
        self.config.set("download.max_concurrent_downloads", self.max_concurrent.value())
        self.config.set("download.default_segments", self.default_segments.value())
        self.config.set("download.retry_count", self.retry_count.value())

        # Speed
        speed_kb = self.speed_limit.value()
        self.config.set("speed.global_limit_bytes_per_sec", speed_kb * 1024)

        # Proxy
        self.config.set("proxy.enabled", self.proxy_enabled.isChecked())
        self.config.set("proxy.type", self.proxy_type.currentText().lower())
        self.config.set("proxy.host", self.proxy_host.text())
        self.config.set("proxy.port", self.proxy_port.value())
        self.config.set("proxy.username", self.proxy_username.text())
        self.config.set("proxy.password", self.proxy_password.text())

        # Scheduler
        self.config.set("scheduler.enabled", self.sched_enabled.isChecked())
        self.config.set("scheduler.start_time", self.sched_start.text())
        self.config.set("scheduler.stop_time", self.sched_stop.text())
        self.config.set("scheduler.shutdown_after_complete", self.sched_shutdown.isChecked())

        self.config.save()
        self.settings_changed.emit()
        self.accept()
