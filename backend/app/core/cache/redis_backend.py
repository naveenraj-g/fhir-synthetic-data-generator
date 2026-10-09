import redis.exceptions
from redis.asyncio.client import Redis

from app.core.logging import get_logger

logger = get_logger(__name__)


class RedisCacheBackend:
    """Shared-across-instances CacheBackend over the project's existing
    Redis client (app/core/redis.py's redis_client) — not a separate
    connection, just a thin get/set/delete wrapper so callers depend on
    CacheBackend's interface instead of the raw redis-py client.

    Fails open on a Redis error: a `get()` that can't reach Redis returns
    None (the caller reads that as "not cached", falls through to its own
    source of truth) rather than raising, and a failed `set()`/`delete()`
    just logs and no-ops — a cache outage degrades to "always miss", never
    to a crash."""

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def get(self, key: str) -> str | None:
        try:
            return await self._client.get(key)
        except redis.exceptions.RedisError:
            logger.error(
                "Redis cache read failed — treating as a cache miss",
                extra={"event": "cache.backend_degraded", "reason": "redis_error", "op": "get"},
            )
            return None

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        try:
            await self._client.set(key, value, ex=ttl_seconds)
        except redis.exceptions.RedisError:
            logger.error(
                "Redis cache write failed — value will not be cached this time",
                extra={"event": "cache.backend_degraded", "reason": "redis_error", "op": "set"},
            )

    async def delete(self, key: str) -> None:
        try:
            await self._client.delete(key)
        except redis.exceptions.RedisError:
            logger.error(
                "Redis cache delete failed",
                extra={"event": "cache.backend_degraded", "reason": "redis_error", "op": "delete"},
            )
