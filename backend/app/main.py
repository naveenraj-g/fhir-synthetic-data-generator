import asyncio
from contextlib import asynccontextmanager
from typing import cast

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from scalar_fastapi import get_scalar_api_reference

from app.core.config import settings
from app.core.database import Database
from app.core.logging import get_logger, setup_logging
from app.core.redis import redis_client
from app.di.container import container
from app.errors.base import ApplicationError
from app.errors.handlers import (
    application_error_handler,
    http_exception_handler,
    request_validation_exception_handler,
    generator_error_handler,
    unhandled_exception_handler,
)
from app.generator.errors import GeneratorError
from app.middleware import AccessLogMiddleware, RateLimitMiddleware, request_context_middleware
from app.routers import discover_routers
from app.workers.cleanup import run_periodically

setup_logging()
logger = get_logger(__name__)

db: Database = container.core.database()


def mount_routers(app: FastAPI) -> None:
    """Discovers + conditionally mounts every resource router based on
    settings.routes.enabled. Called from inside the lifespan handler (at
    real ASGI startup), not at module-import time."""
    available = discover_routers()
    mounted = []
    for name in settings.routes.enabled:
        router = available.get(name)
        if router is None:
            logger.warning(
                "routes.enabled names a router that doesn't exist",
                extra={"event": "startup.unknown_route", "name": name},
            )
            continue
        app.include_router(router, prefix="/api/v1")
        mounted.append(name)
    logger.info(
        "Mounted resource routers",
        extra={"event": "startup.routes_mounted", "count": len(mounted), "routes": mounted},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application...", extra={"event": "startup.begin"})
    mount_routers(app)

    # Jobs a previous process left queued/running can never finish.
    try:
        await container.generation.generation_service().recover_orphans()
    except Exception as exc:  # e.g. migrations not applied yet — surface it, don't block startup
        logger.error("Orphan job recovery failed", extra={"event": "startup.orphan_recovery_failed"}, exc_info=exc)

    if settings.redis.enabled:
        try:
            await cast(object, redis_client).ping()
            app.state.redis = redis_client
            logger.info("Redis connected", extra={"event": "startup.redis_connected"})
        except Exception as exc:
            logger.error(
                "Redis configured but unreachable at startup — degrading to in-process fallbacks",
                extra={"event": "startup.redis_failed"},
                exc_info=exc,
            )
            app.state.redis = None
    else:
        logger.info(
            "Redis disabled by config — every Redis-backed dependent already forced to its "
            "non-Redis fallback by Settings._apply_redis_switch().",
            extra={"event": "startup.redis_disabled"},
        )
        app.state.redis = None

    # Delete generated files once they pass their expiry (artifact_ttl_hours; metadata rows are kept).
    service = container.generation.generation_service()
    interval = container.generation.runtime().config.limits.cleanup_interval_minutes * 60
    cleanup_task = asyncio.create_task(
        run_periodically(service.cleanup_expired, interval, "cleanup_expired"), name="cleanup-expired"
    )

    yield

    cleanup_task.cancel()
    await asyncio.gather(cleanup_task, return_exceptions=True)
    logger.info("Shutting down application...", extra={"event": "shutdown.begin"})
    await db.disconnect()
    logger.info("Database engine disposed.", extra={"event": "shutdown.db_disposed"})


app: FastAPI = FastAPI(
    title=settings.app.title,
    version=settings.app.version,
    description="Configurable synthetic FHIR data generator. Pick a connector (Synthea first), "
    "slice the output (full record, resource types, ...), and deliver it (inline, zip, NDJSON).",
    docs_url="/docs" if settings.app.docs_enabled else None,
    redoc_url="/redoc" if settings.app.docs_enabled else None,
    lifespan=lifespan,
)

app.add_exception_handler(ApplicationError, application_error_handler)
app.add_exception_handler(GeneratorError, generator_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)
app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)

app.container = container

# Middleware order matters — Starlette runs the LAST-added one outermost:
#   cors (outermost, only if enabled)
#     -> request_context (establishes request_id before anything logs)
#       -> access_log      (records every response, including 429s below it)
#         -> rate_limit    (innermost)
app.add_middleware(
    RateLimitMiddleware,
    backend=settings.rate_limit.backend,
    read_limit=settings.rate_limit.read_limit,
    write_limit=settings.rate_limit.write_limit,
    window_seconds=settings.rate_limit.window_seconds,
)
app.add_middleware(AccessLogMiddleware)
app.middleware("http")(request_context_middleware)

if settings.cors.enabled:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors.allow_origins,
        allow_credentials=settings.cors.allow_credentials,
        allow_methods=settings.cors.allow_methods,
        allow_headers=settings.cors.allow_headers,
    )

# Scalar renders the same /openapi.json as /docs and /redoc — no spec
# changes, just a nicer UI with a built-in light/dark toggle neither of
# those ship with. Gated by docs_enabled the same way /docs and /redoc
# are — the route isn't registered at all when disabled.
if settings.app.docs_enabled:

    @app.get("/docs/scalar", include_in_schema=False)
    async def scalar_docs():
        return get_scalar_api_reference(openapi_url=app.openapi_url, title=app.title)


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}


@app.get("/health/ready", tags=["Health"])
async def health_ready(request: Request):
    checks = {}
    try:
        async with db.session() as session:
            from sqlalchemy import text

            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.error("Readiness: database check failed", exc_info=exc)
        checks["database"] = "unavailable"

    if not settings.redis.enabled:
        checks["redis"] = "disabled"
    else:
        redis = getattr(request.app.state, "redis", None)
        if redis is not None:
            try:
                await redis.ping()
                checks["redis"] = "ok"
            except Exception:
                checks["redis"] = "unavailable"
        else:
            checks["redis"] = "unavailable"

    all_ok = all(v in ("ok", "disabled") for v in checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "ok" if all_ok else "degraded", "checks": checks},
    )
