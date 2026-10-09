import time

from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger
from app.core.request_context import get_request_actor

logger = get_logger(__name__)


class AccessLogMiddleware(BaseHTTPMiddleware):
    """One structured line per request — reads actor identity via
    request.state (get_request_actor), not the ContextVar, since this
    middleware runs *above* the route's own child task — see
    app/core/request_context.py's module docstring."""

    async def dispatch(self, request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        actor_user_id, actor_org_id = get_request_actor(request)

        level = logger.warning if response.status_code >= 400 else logger.info
        level(
            f"{request.method} {request.url.path} -> {response.status_code}",
            extra={
                "event": "http.request",
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "client_ip": request.client.host if request.client else None,
                "actor_user_id": actor_user_id,
                "actor_org_id": actor_org_id,
            },
        )
        return response
