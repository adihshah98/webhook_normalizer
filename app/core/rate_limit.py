"""In-memory sliding-window rate limiter."""

import asyncio
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import Request


class InMemoryRateLimiter:
    """Sliding-window rate limiter. Thread-safe via asyncio lock."""

    def __init__(
        self,
        requests_per_window: int,
        window_seconds: float,
        key_func: Callable[[Request], str] | None = None,
    ):
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self._key_func = key_func or _default_key
        self._timestamps: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    def _get_key(self, request: Request) -> str:
        return self._key_func(request)

    async def is_allowed(self, request: Request) -> bool:
        """Return True if request is within limit, False if rate limited."""
        key = self._get_key(request)
        now = time.monotonic()
        cutoff = now - self.window_seconds

        async with self._lock:
            # Periodically prune stale keys to prevent unbounded growth
            if len(self._timestamps) > 10_000:
                stale = [k for k, v in self._timestamps.items() if not v or v[-1] <= cutoff]
                for k in stale:
                    del self._timestamps[k]

            ts_list = self._timestamps[key]
            ts_list[:] = [t for t in ts_list if t > cutoff]
            if len(ts_list) >= self.requests_per_window:
                return False
            ts_list.append(now)
            return True


def _default_key(request: Request) -> str:
    """Key by X-API-Key if present, else client IP."""
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"key:{api_key}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


async def rate_limit_dep(request: Request) -> None:
    """FastAPI dependency. Raises 429 if rate limited. No-op if limiter disabled."""
    limiter = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        return
    if not await limiter.is_allowed(request):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(int(limiter.window_seconds))},
        )
