"""
SQLite database for persisting download state, segments, and history.
Uses aiosqlite for async operations.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import List, Optional

import aiosqlite

from udm.core.segment import (
    DownloadTask, DownloadStatus, Segment, SegmentStatus, FileCategory
)

logger = logging.getLogger("udm.storage.database")

DB_FILENAME = "udm.db"


def get_db_path() -> str:
    """Get the default database file path."""
    app_data = Path.home() / ".udm"
    app_data.mkdir(parents=True, exist_ok=True)
    return str(app_data / DB_FILENAME)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS downloads (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    filename TEXT NOT NULL DEFAULT 'download',
    save_path TEXT NOT NULL,
    total_size INTEGER DEFAULT 0,
    downloaded_size INTEGER DEFAULT 0,
    status TEXT DEFAULT 'QUEUED',
    num_segments INTEGER DEFAULT 8,
    etag TEXT,
    last_modified TEXT,
    supports_range INTEGER DEFAULT 0,
    content_type TEXT,
    category TEXT DEFAULT 'General',
    created_at REAL,
    completed_at REAL,
    error_message TEXT,
    cookies TEXT,
    referrer TEXT,
    user_agent TEXT,
    priority INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS segments (
    id INTEGER NOT NULL,
    download_id TEXT NOT NULL,
    start_byte INTEGER NOT NULL,
    end_byte INTEGER NOT NULL,
    downloaded_bytes INTEGER DEFAULT 0,
    status TEXT DEFAULT 'PENDING',
    temp_file TEXT,
    error_count INTEGER DEFAULT 0,
    PRIMARY KEY (download_id, id),
    FOREIGN KEY (download_id) REFERENCES downloads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status);
CREATE INDEX IF NOT EXISTS idx_downloads_created ON downloads(created_at);
CREATE INDEX IF NOT EXISTS idx_segments_download ON segments(download_id);
"""


class Database:
    """Async SQLite database for UDM state persistence."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_db_path()
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self):
        """Open the database connection and create tables."""
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA_SQL)
        await self._db.execute("PRAGMA journal_mode=WAL")  # Better concurrency
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.commit()
        logger.info(f"Database initialized: {self.db_path}")

    async def close(self):
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    # ─── Download CRUD ──────────────────────────────────────────

    async def save_download(self, task: DownloadTask):
        """Insert or update a download task."""
        data = task.to_dict()
        await self._db.execute(
            """
            INSERT OR REPLACE INTO downloads
            (id, url, filename, save_path, total_size, downloaded_size, status,
             num_segments, etag, last_modified, supports_range, content_type,
             category, created_at, completed_at, error_message, cookies,
             referrer, user_agent, priority)
            VALUES
            (:id, :url, :filename, :save_path, :total_size, :downloaded_size,
             :status, :num_segments, :etag, :last_modified, :supports_range,
             :content_type, :category, :created_at, :completed_at,
             :error_message, :cookies, :referrer, :user_agent, :priority)
            """,
            data,
        )

        # Save segments
        for seg in task.segments:
            seg_data = seg.to_dict()
            await self._db.execute(
                """
                INSERT OR REPLACE INTO segments
                (id, download_id, start_byte, end_byte, downloaded_bytes,
                 status, temp_file, error_count)
                VALUES
                (:id, :download_id, :start_byte, :end_byte, :downloaded_bytes,
                 :status, :temp_file, :error_count)
                """,
                seg_data,
            )

        await self._db.commit()

    async def get_download(self, download_id: str) -> Optional[DownloadTask]:
        """Load a download task with its segments."""
        async with self._db.execute(
            "SELECT * FROM downloads WHERE id = ?", (download_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None

            task = DownloadTask.from_dict(dict(row))

            # Load segments
            async with self._db.execute(
                "SELECT * FROM segments WHERE download_id = ? ORDER BY id",
                (download_id,),
            ) as seg_cursor:
                rows = await seg_cursor.fetchall()
                task.segments = [Segment.from_dict(dict(r)) for r in rows]

            return task

    async def get_all_downloads(
        self, status: Optional[DownloadStatus] = None
    ) -> List[DownloadTask]:
        """Load all downloads, optionally filtered by status."""
        if status:
            query = "SELECT * FROM downloads WHERE status = ? ORDER BY created_at DESC"
            params = (status.value,)
        else:
            query = "SELECT * FROM downloads ORDER BY created_at DESC"
            params = ()

        tasks = []
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                task = DownloadTask.from_dict(dict(row))
                # Load segments
                async with self._db.execute(
                    "SELECT * FROM segments WHERE download_id = ? ORDER BY id",
                    (task.id,),
                ) as seg_cursor:
                    seg_rows = await seg_cursor.fetchall()
                    task.segments = [Segment.from_dict(dict(r)) for r in seg_rows]
                tasks.append(task)

        return tasks

    async def update_download_status(
        self, download_id: str, status: DownloadStatus, error_msg: Optional[str] = None
    ):
        """Update just the status of a download."""
        await self._db.execute(
            "UPDATE downloads SET status = ?, error_message = ? WHERE id = ?",
            (status.value, error_msg, download_id),
        )
        await self._db.commit()

    async def update_download_progress(
        self, download_id: str, downloaded_size: int
    ):
        """Update downloaded size for a download."""
        await self._db.execute(
            "UPDATE downloads SET downloaded_size = ? WHERE id = ?",
            (downloaded_size, download_id),
        )
        await self._db.commit()

    async def update_segment_progress(
        self, download_id: str, segment_id: int, downloaded_bytes: int, status: str
    ):
        """Update a specific segment's progress."""
        await self._db.execute(
            "UPDATE segments SET downloaded_bytes = ?, status = ? WHERE download_id = ? AND id = ?",
            (downloaded_bytes, status, download_id, segment_id),
        )
        await self._db.commit()

    async def delete_download(self, download_id: str):
        """Delete a download and its segments from the database."""
        await self._db.execute(
            "DELETE FROM segments WHERE download_id = ?", (download_id,)
        )
        await self._db.execute(
            "DELETE FROM downloads WHERE id = ?", (download_id,)
        )
        await self._db.commit()

    async def get_download_count(self, status: Optional[DownloadStatus] = None) -> int:
        """Get the count of downloads, optionally filtered by status."""
        if status:
            query = "SELECT COUNT(*) FROM downloads WHERE status = ?"
            params = (status.value,)
        else:
            query = "SELECT COUNT(*) FROM downloads"
            params = ()

        async with self._db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def clear_completed(self):
        """Remove all completed downloads from history."""
        await self._db.execute(
            "DELETE FROM segments WHERE download_id IN "
            "(SELECT id FROM downloads WHERE status = ?)",
            (DownloadStatus.COMPLETED.value,),
        )
        await self._db.execute(
            "DELETE FROM downloads WHERE status = ?",
            (DownloadStatus.COMPLETED.value,),
        )
        await self._db.commit()
