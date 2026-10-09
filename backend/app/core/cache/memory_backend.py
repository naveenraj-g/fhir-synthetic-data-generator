import asyncio
import time


class MemoryCacheBackend:
    """Per-process, in-memory CacheBackend — no cross-instance
    coordination. Used when a feature's own `backend` config field is
    "memory", or whenever the global `redis.enabled` switch is false
    (see Settings._apply_redis_switch(), app/core/config.py) regardless of
    what that field says."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> str | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at is not None and expires_at < time.monotonic():
                del self._store[key]
                return None
            return value

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        expires_at = time.monotonic() + ttl_seconds if ttl_seconds else None
        async with self._lock:
            self._store[key] = (value, expires_at)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)
