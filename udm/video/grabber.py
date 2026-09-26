"""
Video grabber - wraps yt-dlp for video URL extraction and download.
Supports YouTube, Vimeo, Dailymotion, and 1000+ other sites.
"""

import asyncio
import json
import logging
import shutil
from typing import Optional, List, Dict

logger = logging.getLogger("udm.video.grabber")


class VideoFormat:
    """Represents a single available video format/quality."""

    def __init__(self, format_id: str, ext: str, resolution: str,
                 filesize: int = 0, note: str = ""):
        self.format_id = format_id
        self.ext = ext
        self.resolution = resolution
        self.filesize = filesize
        self.note = note

    def __str__(self):
        size = f" ({self.filesize // (1024 * 1024)} MB)" if self.filesize else ""
        return f"{self.resolution} .{self.ext}{size} — {self.note}"


class VideoGrabber:
    """
    Wraps yt-dlp for video URL extraction.
    
    Usage:
        grabber = VideoGrabber()
        formats = await grabber.get_formats("https://youtube.com/watch?v=...")
        url = await grabber.get_direct_url("https://...", format_id="best")
    """

    def __init__(self):
        self._yt_dlp_path = shutil.which("yt-dlp")
        if not self._yt_dlp_path:
            logger.warning("yt-dlp not found in PATH. Video grabber will be limited.")

    @property
    def is_available(self) -> bool:
        return self._yt_dlp_path is not None

    async def get_formats(self, url: str) -> List[VideoFormat]:
        """
        Get available video formats for a URL.
        
        Returns list of VideoFormat objects sorted by quality.
        """
        if not self.is_available:
            logger.error("yt-dlp not installed")
            return []

        try:
            proc = await asyncio.create_subprocess_exec(
                self._yt_dlp_path,
                "--dump-json",
                "--no-download",
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error(f"yt-dlp error: {stderr.decode()}")
                return []

            data = json.loads(stdout.decode())
            formats = []

            for fmt in data.get("formats", []):
                vf = VideoFormat(
                    format_id=fmt.get("format_id", ""),
                    ext=fmt.get("ext", ""),
                    resolution=fmt.get("resolution", fmt.get("format_note", "unknown")),
                    filesize=fmt.get("filesize", 0) or fmt.get("filesize_approx", 0) or 0,
                    note=fmt.get("format_note", ""),
                )
                formats.append(vf)

            return formats

        except Exception as e:
            logger.error(f"Failed to get formats: {e}")
            return []

    async def get_direct_url(
        self, url: str, format_id: str = "best"
    ) -> Optional[Dict]:
        """
        Get the direct download URL for a video.
        
        Returns dict with:
            - url: direct download URL
            - filename: suggested filename
            - filesize: approximate size in bytes
            - ext: file extension
        """
        if not self.is_available:
            return None

        try:
            proc = await asyncio.create_subprocess_exec(
                self._yt_dlp_path,
                "--dump-json",
                "--no-download",
                "-f", format_id,
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error(f"yt-dlp error: {stderr.decode()}")
                return None

            data = json.loads(stdout.decode())

            return {
                "url": data.get("url", ""),
                "filename": f"{data.get('title', 'video')}.{data.get('ext', 'mp4')}",
                "filesize": data.get("filesize", 0) or data.get("filesize_approx", 0) or 0,
                "ext": data.get("ext", "mp4"),
                "title": data.get("title", ""),
                "headers": data.get("http_headers", {}),
            }

        except Exception as e:
            logger.error(f"Failed to get direct URL: {e}")
            return None

    async def download_video(
        self,
        url: str,
        output_dir: str,
        format_id: str = "best",
        on_progress: Optional[callable] = None,
    ) -> Optional[str]:
        """
        Download video directly via yt-dlp (fallback for unsegmented downloads).
        Returns the output file path.
        """
        if not self.is_available:
            return None

        try:
            output_template = f"{output_dir}/%(title)s.%(ext)s"

            proc = await asyncio.create_subprocess_exec(
                self._yt_dlp_path,
                "-f", format_id,
                "-o", output_template,
                "--newline",
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                line_str = line.decode().strip()
                if on_progress and "[download]" in line_str:
                    on_progress(line_str)

            await proc.wait()

            if proc.returncode == 0:
                return output_template
            return None

        except Exception as e:
            logger.error(f"Video download failed: {e}")
            return None
