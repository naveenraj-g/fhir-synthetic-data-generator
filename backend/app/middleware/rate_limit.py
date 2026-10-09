import asyncio
import time
from collections import defaultdict
from typing import Literal

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.http_paths import EXCLUDED_PATHS, EXCLUDED_PREFIXES
from app.core.logging import get_logger

logger = get_logger(__name__)


def _make_429(limit: int, window: int) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"error": {"code": "RATE_LIMITED", "message": "Rate limit exceeded"}},
        headers={
            "Retry-After": str(window),
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Window": str(window),
        },
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        read_limit: int = 100,
        write_limit: int = 20,
        window_seconds: int = 60,
        backend: Literal["redis", "memory"] = "redis",
    ):
        super().__init__(app)
        self.read_limit = read_limit
        self.write_limit = write_limit
        self.window = window_seconds
        self.backend = backend

        self.EXCLUDED_PATHS = EXCLUDED_PATHS
        self.EXCLUDED_PREFIXES = EXCLUDED_PREFIXES

        # Per-process fallback used when Redis is unavailable. Not
        # coordinated across instances — but better than no limiting at all.
        self._local_windows: dict[str, list[float]] = defaultdict(list)
        self._local_lock = asyncio.Lock()

    async def _check_local(self, key: str, limit: int) -> tuple[bool, int]:
        now = time.time()
        cutoff = now - self.window
        async with self._local_lock:
            timestamps = self._local_windows[key]
            self._local_windows[key] = [t for t in timestamps if t > cutoff]
            count = len(self._local_windows[key])
            if count >= limit:
                return False, 0
            self._local_windows[key].append(now)
            return True, max(limit - count - 1, 0)

    async def _check_redis(self, redis, key: str, limit: int) -> tuple[bool, int]:
        now = int(time.time())
        window_start = now - self.window
        await redis.zremrangebyscore(key, 0, window_start)
        count = await redis.zcard(key)
        if count >= limit:
            return False, 0
        await redis.zadd(key, {str(now): now})
        await redis.expire(key, self.window)
        return True, max(limit - count - 1, 0)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in self.EXCLUDED_PATHS or path.startswith(self.EXCLUDED_PREFIXES):
            return await call_next(request)

        user = getattr(request.state, "user", None)
        if user:
            user_id = user.get("sub", "unknown")
        else:
            forwarded = request.headers.get("x-forwarded-for")
            user_id = (
                forwarded.split(",")[0].strip()
                if forwarded
                else (request.client.host if request.client else "unknown")
            )

        is_read = request.method in ("GET", "HEAD", "OPTIONS")
        limit = self.read_limit if is_read else self.write_limit
        key = f"rate:{user_id}:{request.method}"

        redis = getattr(request.app.state, "redis", None) if self.backend == "redis" else None

        if redis is not None:
            try:
                allowed, remaining = await self._check_redis(redis, key, limit)
                backend_used = "redis"
            except Exception as exc:
                logger.error(
                    "Rate limit Redis error, falling back to in-process limiter",
                    extra={"event": "ratelimit.backend_degraded", "reason": "redis_error"},
                    exc_info=exc,
                )
                allowed, remaining = await self._check_local(key, limit)
                backend_used = "local"
        else:
            if self.backend == "redis":
                logger.error(
                    "Redis unavailable — rate limiting is process-local only. "
                    "Protection is degraded in multi-instance deployments.",
                    extra={"event": "ratelimit.backend_degraded", "reason": "redis_unavailable"},
                )
            allowed, remaining = await self._check_local(key, limit)
            backend_used = "local"

        if not allowed:
            logger.warning(
                "Rate limit exceeded",
                extra={
                    "event": "ratelimit.exceeded",
                    "rate_limit_key": user_id,
                    "method": request.method,
                    "path": path,
                    "limit": limit,
                    "backend": backend_used,
                },
            )
            return _make_429(limit, self.window)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Window"] = str(self.window)
        return response
