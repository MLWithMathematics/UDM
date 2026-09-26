"""
WebSocket server for browser extension communication.
Listens on localhost for download requests from the extension.
"""

import asyncio
import json
import logging
from typing import Optional, Callable

logger = logging.getLogger("udm.ipc.ws_server")

try:
    import websockets
    from websockets.asyncio.server import serve
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    logger.warning("websockets not installed, browser extension IPC disabled")


class WebSocketServer:
    """
    WebSocket server that accepts download requests from browser extension.
    
    Protocol:
        Extension sends JSON: {
            "type": "download",
            "url": "https://...",
            "filename": "file.zip",
            "cookies": "...",
            "referrer": "https://...",
            "user_agent": "..."
        }
        
        Server responds: {
            "status": "ok",
            "message": "Download added"
        }
    """

    def __init__(self, port: int = 19615, on_download: Optional[Callable] = None, on_show: Optional[Callable] = None):
        self.port = port
        self.on_download = on_download
        self.on_show = on_show
        self._server = None
        self._running = False

    async def start(self):
        """Start the WebSocket server."""
        if not HAS_WEBSOCKETS:
            logger.warning("Cannot start WebSocket server: websockets not installed")
            return

        try:
            self._server = await serve(
                self._handle_connection,
                "localhost",
                self.port,
            )
            self._running = True
            logger.info(f"WebSocket server started on ws://localhost:{self.port}")
        except OSError as e:
            logger.error(f"Failed to start WebSocket server: {e}")

    async def _handle_connection(self, websocket):
        """Handle a WebSocket connection from browser extension."""
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type", "")

                    if msg_type == "download":
                        logger.info(f"Download request from extension: {data.get('url', '')}")
                        if self.on_download:
                            asyncio.create_task(self.on_download(data))
                        await websocket.send(json.dumps({
                            "status": "ok",
                            "message": "Download added to UDM"
                        }))

                    elif msg_type == "ping":
                        await websocket.send(json.dumps({
                            "status": "ok",
                            "message": "pong"
                        }))
                        
                    elif msg_type == "show":
                        logger.info("Show request received from another instance")
                        if self.on_show:
                            # Must be called on main thread or via signal if UI touches it,
                            # but qt handles this gracefully in our setup or we'll ensure it does.
                            self.on_show()
                        await websocket.send(json.dumps({
                            "status": "ok",
                            "message": "Window shown"
                        }))

                    else:
                        await websocket.send(json.dumps({
                            "status": "error",
                            "message": f"Unknown message type: {msg_type}"
                        }))

                except json.JSONDecodeError:
                    await websocket.send(json.dumps({
                        "status": "error",
                        "message": "Invalid JSON"
                    }))
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")

    async def stop(self):
        """Stop the WebSocket server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._running = False
            logger.info("WebSocket server stopped")

    @property
    def is_running(self) -> bool:
        return self._running
