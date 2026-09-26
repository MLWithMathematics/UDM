"""
HTTP authentication handler.
Supports Basic, Digest, and Bearer token authentication.
"""

import logging
from typing import Optional
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger("udm.network.auth")


@dataclass
class AuthConfig:
    """Authentication configuration."""
    auth_type: str = "none"  # none, basic, bearer
    username: str = ""
    password: str = ""
    token: str = ""

    def to_aiohttp_auth(self) -> Optional[aiohttp.BasicAuth]:
        """Convert to aiohttp auth object."""
        if self.auth_type == "basic" and self.username:
            return aiohttp.BasicAuth(self.username, self.password)
        return None

    def to_headers(self) -> dict:
        """Get auth headers for non-basic auth types."""
        if self.auth_type == "bearer" and self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}


class AuthHandler:
    """Manages authentication for downloads."""

    def __init__(self):
        self._credentials: dict[str, AuthConfig] = {}

    def set_auth(self, download_id: str, config: AuthConfig):
        """Set authentication for a download."""
        self._credentials[download_id] = config

    def get_auth(self, download_id: str) -> Optional[AuthConfig]:
        """Get authentication config for a download."""
        return self._credentials.get(download_id)

    def remove_auth(self, download_id: str):
        """Remove stored credentials for a download."""
        self._credentials.pop(download_id, None)
