from typing import Protocol


class CacheBackend(Protocol):
    """Generic cache contract — not tied to any specific feature. Both
    implementations here (redis_backend.py, memory_backend.py) store
    plain strings; callers own their own serialization (json.dumps/loads)."""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...
