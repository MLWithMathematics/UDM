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
        self._yt_dlp_path = shutil.which("yt-dlp")
        if not self._yt_dlp_path:
            logger.warning("yt-dlp not found in PATH. Video grabber will be limited.")
        self.last_error: str = ""

    @property
    def is_available(self) -> bool:
        return self._yt_dlp_path is not None

    def _common_args(
        self,
        referrer: Optional[str] = None,
        cookies: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> List[str]:
        """
        Shared flags for every yt-dlp invocation. Several sites (and plenty
        of non-YouTube video hosts) refuse to serve anything to a bare
        request without the same Referer/cookies/User-Agent the browser
        used — these were previously never passed at all, so any site that
        gates its video behind a session check failed silently.
        """
        args = ["--no-playlist", "--no-warnings"]
        if referrer:
            args += ["--referer", referrer]
        if user_agent:
            args += ["--user-agent", user_agent]
        return args

    @staticmethod
    def _write_cookie_file(cookies: str, site_url: str) -> Optional[str]:
        """
        Write a proper Netscape-format cookie file for yt-dlp's --cookies
        flag, scoped to the site's own domain.

        We used to pass cookies via `--add-header "Cookie: ..."`, which
        yt-dlp itself flags as a "potential security risk" — that header
        gets attached to EVERY request yt-dlp makes for this run, including
        ones to a completely different domain (e.g. googlevideo.com for a
        youtube.com page). Sending youtube.com session cookies to
        googlevideo.com — or an incomplete cookie set the site wasn't
        expecting — can make the target think you're half-authenticated and
        serve a degraded response (this is what produced the exact
        "Requested format is not available" failure with zero formats: not
        a real absence of formats, but YouTube reacting badly to a Cookie
        header it doesn't recognize as a normal session).
        A --cookies file properly scopes each cookie to a domain, so it's
        only ever sent where a real browser would send it.
        """
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
            # domain / include_subdomains / path / secure / expiry / name / value
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

        cookie_file = self._write_cookie_file(cookies, referrer or url) if cookies else None
        try:
            cookie_args = ["--cookies", cookie_file] if cookie_file else []
            proc = await asyncio.create_subprocess_exec(
                self._yt_dlp_path,
                "--dump-json",
                "--no-download",
                *self._common_args(referrer, cookies, user_agent),
                *cookie_args,
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                self.last_error = stderr.decode(errors="replace").strip()
                logger.error(f"yt-dlp error: {self.last_error}")
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
        """
        Resolve metadata (and, where possible, a direct download URL) for a
        video. Returns None only when yt-dlp genuinely could not recognize
        or reach the page at all — NOT when a flat "url" happens to be
        missing.

        A missing top-level "url" is normal and expected for most non-trivial
        videos: whenever yt-dlp needs to merge separate video+audio streams
        (which is how YouTube serves almost everything above 720p, and how
        many other sites serve HLS/DASH), there is no single combined URL to
        report here — that merge only happens during an actual
        `download_video()` call. Callers should treat "we got info back" as
        the success signal, not "info.get('url') is truthy".

        Returns dict with:
            - url: direct download URL if a single combined stream exists,
              else the best single-stream URL we could find (informational
              only — do not rely on this alone for a complete download)
            - filename: suggested filename
            - filesize: approximate size in bytes
            - ext: file extension
            - title: video title
        """
        if not self.is_available:
            self.last_error = "yt-dlp is not installed"
            return None

        cookie_file = self._write_cookie_file(cookies, referrer or url) if cookies else None
        try:
            cookie_args = ["--cookies", cookie_file] if cookie_file else []
            # "best" (yt-dlp's legacy single-combined-file selector) is what
            # was actually causing "Requested format is not available" —
            # modern YouTube mostly doesn't serve a single file with both
            # video and audio anymore, so explicitly asking for one can
            # genuinely match nothing. Omitting -f entirely lets yt-dlp use
            # its own current default (bestvideo*+bestaudio/best as of this
            # yt-dlp release), which is exactly what a bare `yt-dlp <url>`
            # does — and that's confirmed working. Only pass -f when the
            # caller wants a *specific* format id (e.g. from a format-picker
            # UI), not for our generic "best available" case.
            format_args = [] if format_id == "best" else ["-f", format_id]
            proc = await asyncio.create_subprocess_exec(
                self._yt_dlp_path,
                "--dump-json",
                "--no-download",
                *format_args,
                *self._common_args(referrer, cookies, user_agent),
                *cookie_args,
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                self.last_error = stderr.decode(errors="replace").strip()
                logger.error(f"yt-dlp error: {self.last_error}")
                return None

            data = json.loads(stdout.decode())

            direct_url = data.get("url", "")
            if not direct_url:
                # Adaptive/merged selection (very common: YouTube >720p, most
                # HLS/DASH sites) — grab the best available single-stream URL
                # as informational metadata. The real download still goes
                # through download_video(), which lets yt-dlp handle the
                # merge properly.
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
        """
        List the video qualities that actually exist for this URL, highest
        first, e.g. [{"quality": "1080", "label": "1080p", "size": 52428800}, ...].
        `size` is an approximate video+audio total in bytes (0 if unknown).
        Returns [] if the page can't be resolved (see self.last_error).
        """
        if not self.is_available:
            self.last_error = "yt-dlp is not installed"
            return []

        cookie_file = self._write_cookie_file(cookies, referrer or url) if cookies else None
        try:
            cookie_args = ["--cookies", cookie_file] if cookie_file else []
            proc = await asyncio.create_subprocess_exec(
                self._yt_dlp_path,
                "--dump-json",
                "--no-download",
                *self._common_args(referrer, cookies, user_agent),
                *cookie_args,
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                self.last_error = stderr.decode("utf-8", errors="replace").strip()
                logger.error(f"yt-dlp error listing qualities: {self.last_error}")
                return []

            data = json.loads(stdout.decode("utf-8", errors="replace"))
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

        # Video-only streams still need an audio track merged in, so add the
        # best audio stream's size to each height for a realistic total.
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
        """
        Download video directly via yt-dlp (fallback for unsegmented downloads).
        yt-dlp handles any required video+audio merge itself (requires ffmpeg
        on PATH for formats that need it). Returns the actual output file path.
        """
        if not self.is_available:
            self.last_error = "yt-dlp is not installed"
            return None

        # Two separate subprocess-stdout-parsing bugs in a row (the final
        # path, then --progress-template coming back unusable — a long-
        # standing, documented yt-dlp quirk) is a sign that parsing yt-dlp's
        # CLI text output is the wrong approach for this. yt-dlp's own
        # Python API gives progress_hooks a real dict with guaranteed keys
        # and types — no text, no formatting, no field-name guessing — and
        # the final file path straight from its own return value instead of
        # scraping stdout for it.
        import yt_dlp

        cookie_file = self._write_cookie_file(cookies, referrer or url) if cookies else None
        loop = asyncio.get_event_loop()

        def _hook(d: dict):
            if not on_progress or d.get("status") != "downloading":
                return
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            speed = d.get("speed") or 0
            # This hook runs on yt-dlp's own worker thread (we call it via
            # run_in_executor below), never the main/Qt thread. Touching Qt
            # objects from here directly would be unsafe; call_soon_threadsafe
            # is the correct way to hand work back to the main event loop,
            # which is what on_progress ultimately needs (it updates a Qt
            # table row and possibly an open detail dialog).
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
            # "best" was the actual cause of "Requested format is not
            # available" on modern YouTube (a legacy single-combined-file
            # selector most videos no longer have). Omitting "format"
            # entirely lets yt-dlp use its own current smarter default,
            # same as a bare `yt-dlp <url>` does.
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

        # The definitive final path, straight from yt-dlp's own return
        # value — not a guess, not scraped from stdout text.
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
