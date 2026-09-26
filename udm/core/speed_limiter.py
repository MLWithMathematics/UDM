"""
Token bucket speed limiter for bandwidth throttling.
Supports per-download and global speed limits.
"""

import asyncio
import time
import logging

logger = logging.getLogger("udm.core.speed_limiter")


class TokenBucketLimiter:
    """
    Token bucket algorithm for bandwidth throttling.
    
    Tokens represent bytes. Tokens are added at a rate of `rate_bytes_per_sec`.
    When a download wants to write `n` bytes, it must acquire `n` tokens first.
    If not enough tokens are available, it waits until they are.
    """

    def __init__(self, rate_bytes_per_sec: int = 0):
        """
        Initialize the limiter.
        
        Args:
            rate_bytes_per_sec: Maximum bytes per second. 0 = unlimited.
        """
        self._rate = rate_bytes_per_sec
        self._tokens = float(rate_bytes_per_sec) if rate_bytes_per_sec > 0 else float('inf')
        self._max_tokens = float(rate_bytes_per_sec) if rate_bytes_per_sec > 0 else float('inf')
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        self._enabled = rate_bytes_per_sec > 0

    @property
    def rate(self) -> int:
        return self._rate

    @rate.setter
    def rate(self, value: int):
        """Update the rate limit. 0 = unlimited."""
        self._rate = value
        self._enabled = value > 0
        if value > 0:
            self._max_tokens = float(value)
            self._tokens = min(self._tokens, self._max_tokens)
        else:
            self._tokens = float('inf')
            self._max_tokens = float('inf')

    def _refill(self):
        """Add tokens based on elapsed time since last refill."""
        if not self._enabled:
            return
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        self._tokens = min(
            self._max_tokens,
            self._tokens + elapsed * self._rate
        )

    async def acquire(self, num_bytes: int) -> None:
        """
        Acquire tokens (bytes) from the bucket.
        Blocks until enough tokens are available.
        
        Args:
            num_bytes: Number of bytes to acquire permission for.
        """
        if not self._enabled:
            return

        async with self._lock:
            self._refill()

            while self._tokens < num_bytes:
                # Calculate wait time for enough tokens
                deficit = num_bytes - self._tokens
                wait_time = deficit / self._rate
                # Cap wait time to avoid extremely long waits
                wait_time = min(wait_time, 1.0)
                
                # Release lock while waiting
                self._lock.release()
                await asyncio.sleep(wait_time)
                await self._lock.acquire()
                self._refill()

            self._tokens -= num_bytes

    def reset(self):
        """Reset the token bucket."""
        self._tokens = self._max_tokens
        self._last_refill = time.monotonic()


class SpeedLimiter:
    """
    Manages both global and per-download speed limits.
    """

    def __init__(self, global_limit: int = 0):
        """
        Args:
            global_limit: Global bandwidth limit in bytes/sec. 0 = unlimited.
        """
        self.global_limiter = TokenBucketLimiter(global_limit)
        self._download_limiters: dict[str, TokenBucketLimiter] = {}

    def set_global_limit(self, rate_bytes_per_sec: int):
        """Set the global speed limit."""
        self.global_limiter.rate = rate_bytes_per_sec
        logger.info(f"Global speed limit set to {rate_bytes_per_sec} B/s")

    def set_download_limit(self, download_id: str, rate_bytes_per_sec: int):
        """Set per-download speed limit."""
        if download_id not in self._download_limiters:
            self._download_limiters[download_id] = TokenBucketLimiter(rate_bytes_per_sec)
        else:
            self._download_limiters[download_id].rate = rate_bytes_per_sec

    def remove_download_limit(self, download_id: str):
        """Remove per-download speed limit."""
        self._download_limiters.pop(download_id, None)

    async def acquire(self, download_id: str, num_bytes: int):
        """
        Acquire bandwidth for a specific download.
        Checks both per-download and global limits.
        """
        # Check per-download limit
        if download_id in self._download_limiters:
            await self._download_limiters[download_id].acquire(num_bytes)

        # Check global limit
        await self.global_limiter.acquire(num_bytes)
