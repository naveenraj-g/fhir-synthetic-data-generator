"""Picks a CacheBackend for a feature's own `backend: "redis"|"memory"`
config field (e.g. settings.example_cache.backend) — "redis" automatically
falls back to the shared in-process memory backend whenever the Redis
client isn't actually available, not only when `backend` itself says
"memory". Centralized here so every cache consumer gets that fallback for
free instead of reimplementing it per feature."""

from app.core.cache.base import CacheBackend
from app.core.cache.memory_backend import MemoryCacheBackend
from app.core.cache.redis_backend import RedisCacheBackend
from app.core.logging import get_logger
from app.core.redis import redis_client

logger = get_logger(__name__)

# One shared in-process store for every "memory"-backed (or
# redis-degraded) cache consumer in this process.
_memory_backend = MemoryCacheBackend()


def get_cache_backend(backend: str) -> CacheBackend:
    if backend == "redis":
        if redis_client is not None:
            return RedisCacheBackend(redis_client)
        logger.error(
            "Configured for Redis caching but the Redis client is unavailable — "
            "falling back to in-process memory. Caching is degraded across instances.",
            extra={"event": "cache.backend_degraded", "reason": "redis_unavailable"},
        )
    return _memory_backend
