"""
Temp file and output file management.
"""

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger("udm.storage.file_manager")


class FileManager:
    """Manages temp directories, file paths, and cleanup operations."""

    def __init__(self, temp_dir: str, default_save_dir: str):
        self.temp_dir = temp_dir
        self.default_save_dir = default_save_dir
        self._ensure_dirs()

    def _ensure_dirs(self):
        """Create temp and download directories if they don't exist."""
        Path(self.temp_dir).mkdir(parents=True, exist_ok=True)
        Path(self.default_save_dir).mkdir(parents=True, exist_ok=True)

    def get_temp_path(self, download_id: str, segment_id: int) -> str:
        """Get temp file path for a segment."""
        return str(Path(self.temp_dir) / f"{download_id}.seg{segment_id}.part")

    def get_output_path(self, save_dir: str, filename: str) -> str:
        """
        Get the final output file path.
        Auto-renames if file already exists (adds number suffix).
        """
        path = Path(save_dir) / filename
        if not path.exists():
            return str(path)

        stem = path.stem
        ext = path.suffix
        counter = 1
        while path.exists():
            path = Path(save_dir) / f"{stem} ({counter}){ext}"
            counter += 1
        return str(path)

    def ensure_save_dir(self, save_dir: str):
        """Create save directory if needed."""
        Path(save_dir).mkdir(parents=True, exist_ok=True)

    def get_category_dir(self, base_dir: str, category: str) -> str:
        """Get category-specific save directory."""
        cat_dir = Path(base_dir) / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        return str(cat_dir)

    def cleanup_download_temps(self, download_id: str):
        """Remove all temp files for a download."""
        temp_path = Path(self.temp_dir)
        for f in temp_path.glob(f"{download_id}.*"):
            try:
                f.unlink()
            except OSError as e:
                logger.warning(f"Failed to delete temp file {f}: {e}")

    def get_temp_dir_size(self) -> int:
        """Get total size of temp directory in bytes."""
        total = 0
        for f in Path(self.temp_dir).rglob("*"):
            if f.is_file():
                total += f.stat().st_size
        return total

    def cleanup_orphaned_temps(self, active_ids: set):
        """Remove temp files that don't belong to any active download."""
        temp_path = Path(self.temp_dir)
        for f in temp_path.glob("*.part"):
            # Extract download_id from filename (format: {id}.seg{n}.part)
            parts = f.stem.split(".")
            if parts and parts[0] not in active_ids:
                try:
                    f.unlink()
                    logger.info(f"Removed orphaned temp: {f}")
                except OSError:
                    pass

    @staticmethod
    def open_file_location(filepath: str):
        """Open the file's parent directory in explorer."""
        import subprocess
        try:
            path = Path(filepath)
            if path.exists():
                # Highlight the file in explorer
                subprocess.Popen(
                    ['explorer', '/select,', str(path)],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                # Fall back to opening the parent folder
                folder = str(path.parent) if path.parent.exists() else str(Path.home() / "Downloads")
                os.startfile(folder)
        except Exception as e:
            logger.error(f"Failed to open file location: {filepath} — {e}")

    @staticmethod
    def open_file(filepath: str):
        """Open the downloaded file with the system's default application."""
        import subprocess
        try:
            path = Path(filepath)
            if not path.exists():
                logger.warning(f"Cannot open file — does not exist: {filepath}")
                return
            # Use subprocess.Popen with 'start' for safer execution on Windows
            subprocess.Popen(
                ['cmd', '/c', 'start', '', str(path)],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as e:
            logger.error(f"Failed to open file: {filepath} — {e}")
