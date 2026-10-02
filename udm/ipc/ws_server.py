"""
WebSocket server — bridges the browser extension to the desktop app.

TIER 1 HARDENING:
 - Origin check: a WebSocket connection carrying a browser `Origin` header
   must be `chrome-extension://...` or `moz-extension://...`. Plain web
   pages can open WebSockets to localhost too (this isn't blocked by
   same-origin policy the way fetch() is), so without this check any site
   could talk to this server directly. Connections with NO Origin header
   (e.g. the single-instance "wake up" ping sent by a second UDM launch,
   which uses a bare Python socket, not a browser) are allowed through to
   the token check below instead of being rejected outright — a webpage
   cannot spoof "no Origin", only non-browser clients produce that.
 - Pairing token: every message must include the token from
   config["security"]["pairing_token"]. Defense in depth against other
   locally-installed extensions.
 - Real confirmation, not fire-and-forget: previously a download request
   was handed to `asyncio.create_task()` and "ok" was sent back
   immediately, before anyone knew if the download actually started. The
   extension used that "ok" to decide whether to erase the browser's own
   copy of the file — so a dead link or slow server meant a permanently
   lost download with no visible error. Now we `await` the handler and
   only report success once it has actually resolved.
"""

import asyncio
import json
import logging

from websockets.asyncio.server import serve

logger = logging.getLogger("udm.ipc.ws_server")


def _get_origin(websocket) -> str:
    """Best-effort Origin header lookup across websockets library versions."""
    try:
        return websocket.request.headers.get("Origin", "") or ""
    except Exception:
        pass
    try:
        return websocket.request_headers.get("Origin", "") or ""
    except Exception:
        pass
    return ""


class WebSocketServer:
    """
    Local WebSocket server that the browser extension connects to.

    on_download(data) -> (success: bool, message: str)
    on_video_download(data) -> (success: bool, message: str)
    on_video_formats(data) -> (success: bool, message: str, extra: dict)
    on_show() -> None
    """

    def __init__(
        self,
        port: int = 19615,
        token: str = "",
        on_download=None,
        on_video_download=None,
        on_video_formats=None,
        on_show=None,
    ):
        self.port = port
        self.token = token
        self.on_download = on_download
        self.on_video_download = on_video_download
        self.on_video_formats = on_video_formats
        self.on_show = on_show
        self._server = None

    async def start(self):
        """Start the WebSocket server."""
        self._server = await serve(
            self._handle_connection,
            "localhost",
            self.port,
            # The `websockets` library pings idle connections and closes
            # them if a pong doesn't arrive in time. Some of our handlers
            # (yt-dlp resolving a video, especially with a real JS-challenge
            # solve involved) can legitimately take several seconds with no
            # traffic on the connection while we're still working — that's
            # long enough to trip the default keepalive and have the SERVER
            # itself kill the connection out from under a request that was
            # still being handled correctly. This is a local, single-user,
            # loopback-only server, so there's no real benefit to server-
            # initiated keepalive pings here — disabling them entirely
            # avoids the whole class of "died before ok could be sent" bug.
            ping_interval=None,
        )
        logger.info(f"WebSocket server started on ws://localhost:{self.port}")

    async def stop(self):
        """Stop the WebSocket server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("WebSocket server stopped")

    async def _handle_connection(self, websocket):
        origin = _get_origin(websocket)

        if origin and not (
            origin.startswith("chrome-extension://") or origin.startswith("moz-extension://")
        ):
            logger.warning(f"Rejected WebSocket connection with disallowed origin: {origin!r}")
            await websocket.close(code=4403, reason="Forbidden origin")
            return

        try:
            async for message in websocket:
                await self._handle_message(websocket, message)
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")

    async def _handle_message(self, websocket, message: str):
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            await websocket.send(json.dumps({"status": "error", "message": "Invalid JSON"}))
            return

        msg_type = data.get("type", "")

        if self.token and data.get("token") != self.token:
            logger.warning(f"Rejected message with invalid pairing token (type={msg_type})")
            await websocket.send(
                json.dumps(
                    {
                        "status": "error",
                        "message": "Invalid or missing pairing token. Set it in the UDM extension popup.",
                    }
                )
            )
            return

        if msg_type == "download":
            logger.info(f"Download request from extension: {data.get('url', '')}")
            if self.on_download:
                success, msg = await self.on_download(data)
            else:
                success, msg = False, "No download handler configured"
            await websocket.send(
                json.dumps({"status": "ok" if success else "error", "message": msg})
            )

        elif msg_type == "video_download":
            logger.info(f"Video download request from extension: {data.get('url', '')}")
            if self.on_video_download:
                success, msg = await self.on_video_download(data)
            else:
                success, msg = False, "No video handler configured"
            await websocket.send(
                json.dumps({"status": "ok" if success else "error", "message": msg})
            )

        elif msg_type == "video_formats":
            logger.info(f"Quality list request from extension: {data.get('url', '')}")
            if self.on_video_formats:
                success, msg, extra = await self.on_video_formats(data)
            else:
                success, msg, extra = False, "No formats handler configured", {}
            await websocket.send(
                json.dumps({"status": "ok" if success else "error", "message": msg, **extra})
            )

        elif msg_type == "ping":
            await websocket.send(json.dumps({"status": "ok", "message": "pong"}))

        elif msg_type == "show":
            logger.info("Show request received from another instance")
            if self.on_show:
                self.on_show()
            await websocket.send(json.dumps({"status": "ok", "message": "Window shown"}))

        else:
            await websocket.send(
                json.dumps({"status": "error", "message": f"Unknown message type: {msg_type}"})
            )
