"""
HTTP client with Range header support for segmented downloads.
Handles HEAD requests for file metadata, GET with byte ranges, resume verification,
redirect following, and connection management.
"""

import asyncio
import logging
import re
from typing import Optional, Tuple, Dict, AsyncIterator
from urllib.parse import urlparse, unquote, urlunparse
from pathlib import Path

import aiohttp

logger = logging.getLogger("udm.network")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_CHUNK_SIZE = 1048576  # 1 MB read chunks (improves speed dramatically)
MAX_REDIRECTS = 10
CONNECT_TIMEOUT = 30
READ_TIMEOUT = 60


class RangeNotSupportedError(aiohttp.ClientError):
    """Raised when a server returns 200 OK instead of 206 Partial Content for a range request."""
    pass

class HttpClient:
    """
    HTTP client optimized for download operations.
    Supports Range requests, connection pooling, and resume verification.
    """

    def __init__(
        self,
        user_agent: Optional[str] = None,
        proxy: Optional[str] = None,
        cookies: Optional[str] = None,
        auth: Optional[aiohttp.BasicAuth] = None,
    ):
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.proxy = proxy
        self.cookies = cookies
        self.auth = auth
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session with connection pooling."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(
                connect=CONNECT_TIMEOUT,
                sock_read=READ_TIMEOUT,
            )
            connector = aiohttp.TCPConnector(
                limit=32,  # max connections per host
                enable_cleanup_closed=True,
                force_close=False,
            )
            headers = {"User-Agent": self.user_agent}
            if self.cookies:
                headers["Cookie"] = self.cookies

            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers=headers,
                auth=self.auth,
            )
        return self._session

    @staticmethod
    def _derive_referrer(url: str) -> str:
        """Derive a Referer header from the URL's origin (scheme + host)."""
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))

    @staticmethod
    def _is_redirect_to_different_page(original_url: str, final_url: str) -> bool:
        """
        Detect if the server redirected us away from the expected resource.
        Common anti-hotlinking behaviour: redirect direct links to homepage.
        """
        orig = urlparse(original_url)
        final = urlparse(final_url)

        # Redirected to root / or a generic page while original had a longer path
        orig_path = orig.path.rstrip("/")
        final_path = final.path.rstrip("/")
        if orig_path and (not final_path or final_path == ""):
            return True

        # Original had a file extension, final doesn't (e.g. /file.mp3 → /)
        if "." in orig_path.split("/")[-1] and "." not in final_path.split("/")[-1]:
            return True

        return False

    @staticmethod
    def _looks_like_html(content_type: str) -> bool:
        """Check if content type indicates an HTML page rather than a file."""
        ct = content_type.lower().split(";")[0].strip()
        return ct in ("text/html", "application/xhtml+xml")

    @staticmethod
    def _url_has_media_extension(url: str) -> bool:
        """Check if the URL path suggests a media/binary file."""
        parsed = urlparse(url)
        path = unquote(parsed.path).lower()
        media_exts = {
            ".mp3", ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
            ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a", ".m4v", ".3gp",
            ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso",
            ".exe", ".msi", ".dmg", ".deb", ".rpm", ".apk", ".appx",
            ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
            ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp",
        }
        for ext in media_exts:
            if path.endswith(ext):
                return True
        return False

    async def get_file_info(
        self, url: str, referrer: Optional[str] = None
    ) -> Dict:
        """
        Send HEAD request to get file metadata.
        Includes anti-hotlink bypass: auto-derives Referer, detects redirects,
        and retries with GET if the server returned HTML for a media URL.
        
        Returns dict with:
            - total_size: int (file size in bytes, 0 if unknown)
            - supports_range: bool
            - etag: Optional[str]
            - last_modified: Optional[str]
            - content_type: Optional[str]
            - filename: Optional[str] (from Content-Disposition or URL)
            - final_url: str (after redirects)
            - redirected: bool (True if server redirected to a different page)
            - original_url: str (the URL before any redirects)
        """
        # Auto-derive Referer from URL origin if none provided
        if not referrer:
            referrer = self._derive_referrer(url)

        info = await self._head_probe(url, referrer)

        # Detect anti-hotlink redirect: server sent us to homepage/HTML page
        redirected = self._is_redirect_to_different_page(url, info["final_url"])
        got_html = self._looks_like_html(info.get("content_type", ""))
        expects_media = self._url_has_media_extension(url)

        if (redirected or got_html) and expects_media:
            logger.warning(
                f"Anti-hotlink detected: original={url}, "
                f"final={info['final_url']}, content_type={info.get('content_type')}"
            )
            # Retry with GET probe (some servers only respond to GET with Referer)
            retry_info = await self._fallback_get_info(url, referrer)
            retry_redirected = self._is_redirect_to_different_page(url, retry_info["final_url"])
            retry_html = self._looks_like_html(retry_info.get("content_type", ""))

            if not retry_html and not retry_redirected:
                # GET probe succeeded — use this info
                logger.info("GET probe bypassed anti-hotlink protection")
                info = retry_info
                redirected = False
            else:
                # Still blocked — keep original URL so user can fix referrer/cookies
                logger.warning(
                    "Anti-hotlink bypass failed. The download will use the original "
                    "URL but may need manual Referer/cookies."
                )
                # Preserve the original URL, not the redirected one
                info["final_url"] = url
                redirected = True

        info["redirected"] = redirected
        info["original_url"] = url
        return info

    async def _head_probe(
        self, url: str, referrer: Optional[str] = None
    ) -> Dict:
        """Send HEAD request to probe file metadata."""
        session = await self._get_session()
        headers = {}
        if referrer:
            headers["Referer"] = referrer

        try:
            async with session.head(
                url,
                headers=headers,
                allow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                proxy=self.proxy,
            ) as response:
                response.raise_for_status()

                total_size = int(response.headers.get("Content-Length", 0))
                accept_ranges = response.headers.get("Accept-Ranges", "")
                supports_range = accept_ranges.lower() == "bytes" or total_size > 0
                etag = response.headers.get("ETag")
                last_modified = response.headers.get("Last-Modified")
                content_type = response.headers.get("Content-Type", "")
                final_url = str(response.url)

                # Try to extract filename
                filename = self._extract_filename(response, url)

                return {
                    "total_size": total_size,
                    "supports_range": supports_range,
                    "etag": etag,
                    "last_modified": last_modified,
                    "content_type": content_type,
                    "filename": filename,
                    "final_url": final_url,
                }
        except aiohttp.ClientError as e:
            logger.error(f"HEAD request failed for {url}: {e}")
            # Fallback: try GET with range 0-0 for servers that don't support HEAD
            return await self._fallback_get_info(url, referrer)

    async def _fallback_get_info(
        self, url: str, referrer: Optional[str] = None
    ) -> Dict:
        """Fallback: use GET with Range: bytes=0-0 to probe file info."""
        session = await self._get_session()
        headers = {"Range": "bytes=0-0"}
        if referrer:
            headers["Referer"] = referrer

        try:
            async with session.get(
                url,
                headers=headers,
                allow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                proxy=self.proxy,
            ) as response:
                content_range = response.headers.get("Content-Range", "")
                total_size = 0
                supports_range = response.status == 206

                if content_range:
                    # Parse "bytes 0-0/12345"
                    try:
                        total_size = int(content_range.split("/")[-1])
                    except (ValueError, IndexError):
                        total_size = int(response.headers.get("Content-Length", 0))
                else:
                    total_size = int(response.headers.get("Content-Length", 0))

                filename = self._extract_filename(response, url)

                return {
                    "total_size": total_size,
                    "supports_range": supports_range,
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "content_type": response.headers.get("Content-Type", ""),
                    "filename": filename,
                    "final_url": str(response.url),
                }
        except aiohttp.ClientError as e:
            logger.error(f"Fallback GET probe failed for {url}: {e}")
            raise

    # Content-Type to file extension mapping
    CONTENT_TYPE_EXTENSIONS = {
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/flac": ".flac",
        "audio/aac": ".aac",
        "audio/ogg": ".ogg",
        "audio/x-m4a": ".m4a",
        "audio/mp4": ".m4a",
        "audio/webm": ".weba",
        "video/mp4": ".mp4",
        "video/x-matroska": ".mkv",
        "video/webm": ".webm",
        "video/x-msvideo": ".avi",
        "video/quicktime": ".mov",
        "video/x-flv": ".flv",
        "video/3gpp": ".3gp",
        "application/pdf": ".pdf",
        "application/zip": ".zip",
        "application/x-rar-compressed": ".rar",
        "application/x-7z-compressed": ".7z",
        "application/gzip": ".gz",
        "application/x-tar": ".tar",
        "application/x-iso9660-image": ".iso",
        "application/vnd.android.package-archive": ".apk",
        "application/x-msdownload": ".exe",
        "application/x-msi": ".msi",
        "application/octet-stream": "",  # generic binary, no extension to add
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
        "image/bmp": ".bmp",
    }

    def _extract_filename(
        self, response: aiohttp.ClientResponse, url: str
    ) -> str:
        """
        Extract filename using multiple strategies:
        1. Content-Disposition header (most reliable)
        2. Original request URL path
        3. Final response URL path (after redirects)
        4. content_type-based extension with generic name
        """
        from pathlib import PurePosixPath

        # Strategy 1: Content-Disposition header
        cd = response.headers.get("Content-Disposition", "")
        if "filename=" in cd:
            # Handle both filename="file.zip" and filename*=UTF-8''file.zip
            if "filename*=" in cd:
                parts = cd.split("filename*=")
                if len(parts) > 1:
                    name = parts[1].strip().strip('"').strip("'")
                    if "''" in name:
                        name = name.split("''", 1)[1]
                    decoded = unquote(name)
                    if decoded:
                        return decoded
            parts = cd.split("filename=")
            if len(parts) > 1:
                name = parts[1].strip().strip('"').strip("'").split(";")[0]
                if name:
                    return name

        # Strategy 2: Extract from the ORIGINAL request URL
        name_from_original = self._filename_from_url(url)
        if name_from_original:
            return name_from_original

        # Strategy 3: Extract from the FINAL response URL (after redirects)
        final_url = str(response.url) if response else url
        if final_url != url:
            name_from_final = self._filename_from_url(final_url)
            if name_from_final:
                return name_from_final

        # Strategy 4: Generate name from content_type
        content_type = response.headers.get("Content-Type", "") if response else ""
        ct_base = content_type.lower().split(";")[0].strip()
        ext = self.CONTENT_TYPE_EXTENSIONS.get(ct_base, "")
        if ext:
            return f"download{ext}"

        return "download"

    @staticmethod
    def _filename_from_url(url: str) -> str:
        """Extract a filename with extension from a URL path, or return empty string."""
        from pathlib import PurePosixPath
        try:
            parsed = urlparse(url)
            path = unquote(parsed.path).rstrip("/")
            if not path:
                return ""
            name = PurePosixPath(path).name
            # Only accept names that have a file extension
            if name and "." in name and not name.startswith("."):
                return name
        except Exception:
            pass
        return ""

    async def download_range(
        self,
        url: str,
        start_byte: int,
        end_byte: int,
        referrer: Optional[str] = None,
        etag: Optional[str] = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> AsyncIterator[bytes]:
        """
        Download a specific byte range of a file.
        Yields chunks of data as they arrive.
        
        Uses Range header and optionally If-Range for resume safety.
        """
        session = await self._get_session()
        headers = {
            "Range": f"bytes={start_byte}-{end_byte}",
        }
        if referrer:
            headers["Referer"] = referrer
        if etag:
            headers["If-Range"] = etag

        async with session.get(
            url,
            headers=headers,
            allow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            proxy=self.proxy,
        ) as response:
            if response.status == 200:
                # Server ignored Range header, sent full file
                # This can happen; we need to skip to our start_byte
                logger.warning(
                    f"Server returned 200 instead of 206 for range request. "
                    f"Range support may be limited."
                )
                if start_byte > 0:
                    raise RangeNotSupportedError("Server returned 200 OK instead of 206 Partial Content. Range requests/resume not supported by this link.")
                else:
                    raise RangeNotSupportedError("Server returned 200 OK instead of 206 Partial Content on first segment.")
            elif response.status == 206:
                pass  # Expected partial content
            elif response.status == 416:
                # Range not satisfiable
                logger.error(f"Range not satisfiable: {start_byte}-{end_byte}")
                return
            else:
                response.raise_for_status()

            async for chunk in response.content.iter_chunked(chunk_size):
                yield chunk

    async def download_full(
        self,
        url: str,
        referrer: Optional[str] = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> AsyncIterator[bytes]:
        """
        Download a full file without Range headers.
        Used when server doesn't support range requests.
        """
        session = await self._get_session()
        headers = {}
        if referrer:
            headers["Referer"] = referrer

        async with session.get(
            url,
            headers=headers,
            allow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            proxy=self.proxy,
        ) as response:
            response.raise_for_status()
            async for chunk in response.content.iter_chunked(chunk_size):
                yield chunk

    async def verify_resume(
        self, url: str, etag: Optional[str] = None, last_modified: Optional[str] = None
    ) -> bool:
        """
        Verify that the remote file hasn't changed since we started downloading.
        Returns True if the file is unchanged and resume is safe.
        """
        try:
            info = await self.get_file_info(url)
            if etag and info.get("etag"):
                return info["etag"] == etag
            if last_modified and info.get("last_modified"):
                return info["last_modified"] == last_modified
            # Can't verify, assume it's okay
            return True
        except Exception:
            return False

    async def close(self):
        """Close the HTTP session and release connections."""
        if self._session and not self._session.closed:
            await self._session.close()
            # Allow time for connections to close gracefully
            await asyncio.sleep(0.25)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
