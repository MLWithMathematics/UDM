"""
Network proxy manager - HTTP, HTTPS, and SOCKS5 proxy support.
"""

import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger("udm.network.proxy")


@dataclass
class ProxyConfig:
    """Proxy configuration."""
    enabled: bool = False
    proxy_type: str = "http"  # http, https, socks5
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""

    @property
    def url(self) -> Optional[str]:
        """Build the proxy URL string."""
        if not self.enabled or not self.host:
            return None

        auth = ""
        if self.username:
            auth = f"{self.username}"
            if self.password:
                auth += f":{self.password}"
            auth += "@"

        scheme = self.proxy_type
        if scheme == "socks5":
            scheme = "socks5"
        
        return f"{scheme}://{auth}{self.host}:{self.port}"


class ProxyManager:
    """Manages proxy configuration for downloads."""

    def __init__(self):
        self._global_proxy = ProxyConfig()
        self._download_proxies: dict[str, ProxyConfig] = {}

    def set_global_proxy(self, config: ProxyConfig):
        """Set the global proxy for all downloads."""
        self._global_proxy = config
        if config.enabled:
            logger.info(f"Global proxy set: {config.proxy_type}://{config.host}:{config.port}")
        else:
            logger.info("Global proxy disabled")

    def set_download_proxy(self, download_id: str, config: ProxyConfig):
        """Set a proxy for a specific download."""
        self._download_proxies[download_id] = config

    def get_proxy_url(self, download_id: Optional[str] = None) -> Optional[str]:
        """
        Get the proxy URL to use for a download.
        Per-download proxy takes precedence over global.
        """
        # Check per-download proxy
        if download_id and download_id in self._download_proxies:
            proxy = self._download_proxies[download_id]
            if proxy.enabled:
                return proxy.url

        # Fallback to global proxy
        if self._global_proxy.enabled:
            return self._global_proxy.url

        return None

    def remove_download_proxy(self, download_id: str):
        """Remove per-download proxy override."""
        self._download_proxies.pop(download_id, None)

    @staticmethod
    def from_config(config_data: dict) -> ProxyConfig:
        """Create ProxyConfig from config dictionary."""
        return ProxyConfig(
            enabled=config_data.get("enabled", False),
            proxy_type=config_data.get("type", "http"),
            host=config_data.get("host", ""),
            port=config_data.get("port", 0),
            username=config_data.get("username", ""),
            password=config_data.get("password", ""),
        )
