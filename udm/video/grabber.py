"""
Video grabber - wraps yt-dlp for video URL extraction and download.
Supports YouTube, Vimeo, Dailymotion, and 1000+ other sites.
"""

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
from typing import Optional, List, Dict, Tuple
from urllib.parse import urlparse

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
        try:
            import yt_dlp
            self._has_yt_dlp = True
        except ImportError:
            self._has_yt_dlp = False
            logger.warning("yt_dlp module not found. Video grabber will be disabled.")
        self.last_error: str = ""

    @property
    def is_available(self) -> bool:
        return self._has_yt_dlp

    @staticmethod
    def _write_cookie_file(cookies: str, site_url: str) -> Optional[str]:
        if not cookies:
            return None
        try:
            host = urlparse(site_url).hostname or ""
        except Exception:
            host = ""
        if not host:
            return None

        domain = host if host.startswith(".") else f".{host}"
        far_future = int(time.time()) + 3600 * 24 * 365 * 5  # 5 years out

        lines = ["# Netscape HTTP Cookie File"]
        for part in cookies.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            name, _, value = part.partition("=")
            name, value = name.strip(), value.strip()
            if not name:
                continue
            lines.append(f"{domain}\tTRUE\t/\tTRUE\t{far_future}\t{name}\t{value}")

        if len(lines) <= 1:
            return None

        fd, path = tempfile.mkstemp(prefix="udm_ytdlp_cookies_", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return path

    async def get_formats(
        self,
        url: str,
        referrer: Optional[str] = None,
        cookies: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> List[VideoFormat]:
        """
        Get available video formats for a URL.
        Returns list of VideoFormat objects sorted by quality.
        """
        if not self.is_available:
            logger.error("yt-dlp not installed")
            return []

        import yt_dlp
        cookie_file = self._write_cookie_file(cookies, referrer or url) if cookies else None
        
        def _extract():
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "nocheckcertificate": True,
            }
            if referrer:
                ydl_opts["referer"] = referrer
            if user_agent:
                ydl_opts["http_headers"] = {"User-Agent": user_agent}
            if cookie_file:
                ydl_opts["cookiefile"] = cookie_file

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)

        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, _extract)
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
            self.last_error = str(e)
            logger.error(f"Failed to get formats: {e}")
            return []
        finally:
            if cookie_file:
                try:
                    os.remove(cookie_file)
                except OSError:
                    pass

    async def get_direct_url(
        self,
        url: str,
        format_id: str = "best",
        referrer: Optional[str] = None,
        cookies: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Optional[Dict]:
        if not self.is_available:
            self.last_error = "yt-dlp is not installed"
            return None

        import yt_dlp
        cookie_file = self._write_cookie_file(cookies, referrer or url) if cookies else None
        
        def _extract():
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "nocheckcertificate": True,
            }
            if format_id != "best":
                ydl_opts["format"] = format_id
            if referrer:
                ydl_opts["referer"] = referrer
            if user_agent:
                ydl_opts["http_headers"] = {"User-Agent": user_agent}
            if cookie_file:
                ydl_opts["cookiefile"] = cookie_file

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)

        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, _extract)
            direct_url = data.get("url", "")
            if not direct_url:
                requested = data.get("requested_formats") or []
                if requested:
                    direct_url = requested[-1].get("url", "") or requested[0].get("url", "")

            return {
                "url": direct_url,
                "filename": f"{data.get('title', 'video')}.{data.get('ext', 'mp4')}",
                "filesize": data.get("filesize", 0) or data.get("filesize_approx", 0) or 0,
                "ext": data.get("ext", "mp4"),
                "title": data.get("title", ""),
                "headers": data.get("http_headers", {}),
            }
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Failed to get direct URL: {e}")
            return None
        finally:
            if cookie_file:
                try:
                    os.remove(cookie_file)
                except OSError:
                    pass

    async def get_quality_options(
        self,
        url: str,
        referrer: Optional[str] = None,
        cookies: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> List[Dict]:
        if not self.is_available:
            self.last_error = "yt-dlp is not installed"
            return []

        import yt_dlp
        cookie_file = self._write_cookie_file(cookies, referrer or url) if cookies else None
        
        def _extract():
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "nocheckcertificate": True,
            }
            if referrer:
                ydl_opts["referer"] = referrer
            if user_agent:
                ydl_opts["http_headers"] = {"User-Agent": user_agent}
            if cookie_file:
                ydl_opts["cookiefile"] = cookie_file

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)

        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, _extract)
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Failed to list qualities: {e}")
            return []
        finally:
            if cookie_file:
                try:
                    os.remove(cookie_file)
                except OSError:
                    pass

        formats = data.get("formats") or []

        def _size(f: dict) -> int:
            return int(f.get("filesize") or f.get("filesize_approx") or 0)

        audio_sizes = [
            _size(f) for f in formats
            if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")
        ]
        audio_size = max(audio_sizes, default=0)

        by_height: Dict[int, int] = {}
        for f in formats:
            height = f.get("height")
            if not height or f.get("vcodec") in (None, "none"):
                continue
            size = _size(f)
            if height not in by_height or size > by_height[height]:
                by_height[height] = size

        return [
            {
                "quality": str(h),
                "label": f"{h}p",
                "size": (s + audio_size) if s else 0,
            }
            for h, s in sorted(by_height.items(), reverse=True)
        ]

    async def download_video(
        self,
        url: str,
        output_dir: str,
        format_id: str = "best",
        referrer: Optional[str] = None,
        cookies: Optional[str] = None,
        user_agent: Optional[str] = None,
        on_progress: Optional[callable] = None,
    ) -> Optional[str]:
        if not self.is_available:
            self.last_error = "yt-dlp is not installed"
            return None

        import yt_dlp

        cookie_file = self._write_cookie_file(cookies, referrer or url) if cookies else None
        loop = asyncio.get_event_loop()

        def _hook(d: dict):
            if not on_progress or d.get("status") != "downloading":
                return
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            speed = d.get("speed") or 0
            loop.call_soon_threadsafe(
                on_progress,
                {"downloaded_bytes": downloaded, "total_bytes": total, "speed": speed},
            )

        def _run_download():
            ydl_opts = {
                "outtmpl": f"{output_dir}/%(title)s.%(ext)s",
                "merge_output_format": "mp4",
                "quiet": True,
                "no_warnings": True,
                "nocheckcertificate": True,
                "noplaylist": True,
                "progress_hooks": [_hook],
            }
            if format_id != "best":
                ydl_opts["format"] = format_id
            if referrer:
                ydl_opts["referer"] = referrer
            if user_agent:
                ydl_opts["http_headers"] = {"User-Agent": user_agent}
            if cookie_file:
                ydl_opts["cookiefile"] = cookie_file

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=True)

        try:
            info = await loop.run_in_executor(None, _run_download)
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Video download failed ({url}): {e}")
            return None
        finally:
            if cookie_file:
                try:
                    os.remove(cookie_file)
                except OSError:
                    pass

        if not info:
            self.last_error = "yt-dlp returned no result"
            return None

        requested = info.get("requested_downloads") or []
        final_path = (
            (requested[0].get("filepath") if requested else None)
            or info.get("filepath")
            or info.get("_filename")
        )

        if final_path and os.path.isfile(final_path):
            return final_path

        self.last_error = (
            "Download succeeded but UDM could not confirm the final file path/size."
        )
        logger.warning(f"{self.last_error} (info had keys: {list(info.keys())})")
        return None
