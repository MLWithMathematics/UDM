"""
Segment and DownloadTask data models for UDM.
These are the fundamental data structures that represent downloads and their segments.
"""

import uuid
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List
from pathlib import Path


class SegmentStatus(Enum):
    """Status of an individual download segment."""
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DONE = "DONE"
    ERROR = "ERROR"


class DownloadStatus(Enum):
    """Status of a download task."""
    QUEUED = "QUEUED"
    DOWNLOADING = "DOWNLOADING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"
    MERGING = "MERGING"


class FileCategory(Enum):
    """Category for organizing downloads."""
    GENERAL = "General"
    COMPRESSED = "Compressed"
    DOCUMENTS = "Documents"
    MUSIC = "Music"
    VIDEO = "Video"
    PROGRAMS = "Programs"
    IMAGES = "Images"


# File extension to category mapping (each extension belongs to exactly one
# category). Anything not listed falls into General.
CATEGORY_MAP = {
    FileCategory.COMPRESSED: {
        ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".xz", ".txz",
        ".zst", ".lz", ".lzma", ".cab", ".iso", ".img",
    },
    FileCategory.DOCUMENTS: {
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv",
        ".odt", ".ods", ".odp", ".rtf", ".md", ".epub", ".mobi", ".azw3", ".djvu", ".xps",
    },
    FileCategory.MUSIC: {
        ".mp3", ".wav", ".flac", ".aac", ".ogg", ".oga", ".opus", ".wma", ".m4a",
        ".aiff", ".ape", ".amr", ".mid", ".midi",
    },
    FileCategory.VIDEO: {
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".3gp",
        ".mpg", ".mpeg", ".ogv", ".vob", ".mts", ".m2ts",
    },
    FileCategory.PROGRAMS: {
        ".exe", ".msi", ".msix", ".appx", ".appxbundle", ".dmg", ".pkg", ".deb",
        ".rpm", ".apk", ".appimage",
    },
    FileCategory.IMAGES: {
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico", ".tiff",
        ".tif", ".heic", ".heif", ".avif", ".psd", ".ai", ".eps", ".raw", ".cr2", ".nef",
    },
}


def detect_category(filename: str) -> FileCategory:
    """Auto-detect file category from extension."""
    ext = Path(filename).suffix.lower()
    for category, extensions in CATEGORY_MAP.items():
        if ext in extensions:
            return category
    return FileCategory.GENERAL


@dataclass
class Segment:
    """Represents a single byte-range segment of a download."""
    id: int
    download_id: str
    start_byte: int
    end_byte: int
    downloaded_bytes: int = 0
    status: SegmentStatus = SegmentStatus.PENDING
    temp_file: str = ""
    speed: float = 0.0  # bytes per second
    error_count: int = 0
    max_retries: int = 3

    @property
    def total_bytes(self) -> int:
        """Total bytes this segment needs to download."""
        return self.end_byte - self.start_byte + 1

    @property
    def remaining_bytes(self) -> int:
        """Bytes left to download in this segment."""
        return self.total_bytes - self.downloaded_bytes

    @property
    def progress(self) -> float:
        """Progress as a percentage (0.0 to 100.0)."""
        if self.total_bytes == 0:
            return 100.0
        return (self.downloaded_bytes / self.total_bytes) * 100.0

    @property
    def is_complete(self) -> bool:
        return self.status == SegmentStatus.DONE

    @property
    def can_retry(self) -> bool:
        return self.error_count < self.max_retries

    @property
    def current_offset(self) -> int:
        """The next byte position to download from."""
        return self.start_byte + self.downloaded_bytes

    def to_dict(self) -> dict:
        """Serialize to dictionary for database storage."""
        return {
            "id": self.id,
            "download_id": self.download_id,
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "downloaded_bytes": self.downloaded_bytes,
            "status": self.status.value,
            "temp_file": self.temp_file,
            "error_count": self.error_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Segment":
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            download_id=data["download_id"],
            start_byte=data["start_byte"],
            end_byte=data["end_byte"],
            downloaded_bytes=data.get("downloaded_bytes", 0),
            status=SegmentStatus(data.get("status", "PENDING")),
            temp_file=data.get("temp_file", ""),
            error_count=data.get("error_count", 0),
        )


@dataclass
class DownloadTask:
    """Represents a complete download task with all its metadata."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    url: str = ""
    filename: str = ""
    save_path: str = ""
    total_size: int = 0
    downloaded_size: int = 0
    status: DownloadStatus = DownloadStatus.QUEUED
    segments: List[Segment] = field(default_factory=list)
    num_segments: int = 8
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    supports_range: bool = False
    content_type: Optional[str] = None
    category: FileCategory = FileCategory.GENERAL
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    speed: float = 0.0  # overall bytes/sec
    error_message: Optional[str] = None
    cookies: Optional[str] = None
    referrer: Optional[str] = None
    user_agent: Optional[str] = None
    priority: int = 0  # higher = higher priority

    @property
    def progress(self) -> float:
        """Overall download progress (0.0 to 100.0)."""
        if self.total_size == 0:
            if self.downloaded_size > 0:
                return -1.0  # unknown total, show indeterminate
            return 0.0
        return (self.downloaded_size / self.total_size) * 100.0

    @property
    def eta_seconds(self) -> Optional[float]:
        """Estimated time remaining in seconds."""
        if self.speed <= 0 or self.total_size <= 0:
            return None
        remaining = self.total_size - self.downloaded_size
        return remaining / self.speed

    @property
    def is_active(self) -> bool:
        return self.status == DownloadStatus.DOWNLOADING

    @property
    def is_complete(self) -> bool:
        return self.status == DownloadStatus.COMPLETED

    @property
    def is_resumable(self) -> bool:
        return self.status in (DownloadStatus.PAUSED, DownloadStatus.ERROR)

    @property
    def output_filepath(self) -> str:
        """Full path to the final output file."""
        return str(Path(self.save_path) / self.filename)

    def update_downloaded_size(self):
        """Recalculate total downloaded size from segments."""
        self.downloaded_size = sum(s.downloaded_bytes for s in self.segments)

    def to_dict(self) -> dict:
        """Serialize to dictionary for database storage."""
        return {
            "id": self.id,
            "url": self.url,
            "filename": self.filename,
            "save_path": self.save_path,
            "total_size": self.total_size,
            "downloaded_size": self.downloaded_size,
            "status": self.status.value,
            "num_segments": self.num_segments,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "supports_range": self.supports_range,
            "content_type": self.content_type,
            "category": self.category.value,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error_message": self.error_message,
            "cookies": self.cookies,
            "referrer": self.referrer,
            "user_agent": self.user_agent,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DownloadTask":
        """Deserialize from dictionary."""
        task = cls(
            id=data["id"],
            url=data["url"],
            filename=data.get("filename", ""),
            save_path=data.get("save_path", ""),
            total_size=data.get("total_size", 0),
            downloaded_size=data.get("downloaded_size", 0),
            status=DownloadStatus(data.get("status", "QUEUED")),
            num_segments=data.get("num_segments", 8),
            etag=data.get("etag"),
            last_modified=data.get("last_modified"),
            supports_range=data.get("supports_range", False),
            content_type=data.get("content_type"),
            category=FileCategory(data.get("category", "General")),
            created_at=data.get("created_at", time.time()),
            completed_at=data.get("completed_at"),
            error_message=data.get("error_message"),
            cookies=data.get("cookies"),
            referrer=data.get("referrer"),
            user_agent=data.get("user_agent"),
            priority=data.get("priority", 0),
        )
        return task


def format_size(size_bytes: int) -> str:
    """Format bytes into human-readable size string."""
    if size_bytes < 0:
        return "Unknown"
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    size = float(size_bytes)
    while size >= 1024.0 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    return f"{size:.1f} {units[idx]}"


def format_speed(speed_bps: float) -> str:
    """Format bytes/second into human-readable speed string."""
    if speed_bps <= 0:
        return "0 B/s"
    return f"{format_size(int(speed_bps))}/s"


def format_eta(seconds: Optional[float]) -> str:
    """Format seconds into human-readable ETA string."""
    if seconds is None or seconds < 0:
        return "∞"
    if seconds == 0:
        return "0s"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
