"""
App configuration and settings persistence.
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("udm.storage.config")

DEFAULT_CONFIG = {
    "general": {
        "default_save_dir": str(Path.home() / "Downloads"),
        "temp_dir": str(Path.home() / ".udm" / "temp"),
        "start_minimized": False,
        "minimize_to_tray": True,
        "show_notifications": True,
        "auto_start_download": True,
        "theme": "skyblue",
    },
    "download": {
        "max_concurrent_downloads": 3,
        "default_segments": 8,
        "max_segments": 32,
        "retry_count": 3,
        "retry_delay_seconds": 5,
        "chunk_size": 1048576,
    },
    "speed": {
        "global_limit_bytes_per_sec": 0,  # 0 = unlimited
    },
    "proxy": {
        "enabled": False,
        "type": "http",  # http, https, socks5
        "host": "",
        "port": 0,
        "username": "",
        "password": "",
    },
    "scheduler": {
        "enabled": False,
        "start_time": "02:00",
        "stop_time": "06:00",
        "shutdown_after_complete": False,
    },
    "browser": {
        "ws_port": 19615,
        "clipboard_monitor": True,
    },
    "categories": {
        "Compressed": str(Path.home() / "Downloads" / "Compressed"),
        "Documents": str(Path.home() / "Downloads" / "Documents"),
        "Music": str(Path.home() / "Downloads" / "Music"),
        "Video": str(Path.home() / "Downloads" / "Video"),
        "Programs": str(Path.home() / "Downloads" / "Programs"),
        "Images": str(Path.home() / "Downloads" / "Images"),
        "General": str(Path.home() / "Downloads"),
    },
}


class Config:
    """Application configuration manager with file persistence."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or str(
            Path.home() / ".udm" / "config.json"
        )
        self._data: dict = {}
        self.load()

    def load(self):
        """Load config from file, merging with defaults."""
        self._data = self._deep_copy(DEFAULT_CONFIG)
        
        if Path(self.config_path).exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._deep_merge(self._data, saved)
                logger.info(f"Config loaded from {self.config_path}")
            except Exception as e:
                logger.warning(f"Failed to load config: {e}, using defaults")

    def save(self):
        """Save current config to file."""
        Path(self.config_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)
        logger.debug(f"Config saved to {self.config_path}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a config value using dot notation.
        Example: config.get("download.max_concurrent_downloads")
        """
        keys = key.split(".")
        value = self._data
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key: str, value: Any):
        """
        Set a config value using dot notation.
        Example: config.set("download.max_concurrent_downloads", 5)
        """
        keys = key.split(".")
        data = self._data
        for k in keys[:-1]:
            if k not in data:
                data[k] = {}
            data = data[k]
        data[keys[-1]] = value
        self.save()

    @property
    def data(self) -> dict:
        return self._data

    @staticmethod
    def _deep_merge(base: dict, override: dict):
        """Deep merge override dict into base dict."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                Config._deep_merge(base[key], value)
            else:
                base[key] = value

    @staticmethod
    def _deep_copy(d: dict) -> dict:
        """Deep copy a nested dict."""
        return json.loads(json.dumps(d))
