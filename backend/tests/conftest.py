import os

# Must be set before any app module is imported so pydantic-settings reads them.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# app.main MUST be imported before app.di.container here: the container's
# own wire() call scans the whole `app` package (including app.main) at
# construction time, and app.main imports the container back — importing
# app.main first means that module is already fully loaded by the time
# wire() reaches it, avoiding a circular-import error at collection time.
from app.main import app, mount_routers  # noqa: I001
from app.core.config import settings
from app.core.database import Base
from app.di.container import container
from app.middleware.rate_limit import RateLimitMiddleware

# Router mounting happens inside app.main's lifespan at real ASGI startup,
# not at module-import time — but httpx's ASGITransport (used by every
# test client fixture below) never triggers the ASGI lifespan protocol.
# Mount routes once here instead, synchronously, before any test runs.
mount_routers(app)

# Tests use a config whose default connector is static_fixtures (no Docker/Synthea needed).
settings.CONNECTORS_CONFIG_PATH = "tests/connectors_test.yaml"

# ── Disable rate limiting for tests ───────────────────────────────────────
# The in-process sliding-window limiter accumulates across tests when
# Redis is unavailable, causing 429s. Bypass dispatch entirely in tests.


async def _no_rate_limit(self, request, call_next):
    return await call_next(request)


RateLimitMiddleware.dispatch = _no_rate_limit

# Note: this starter kit's example_cache config (app/core/cache/) has no
# consumer wired into the generator yet — nothing in this test suite
# calls through it. If you wire a cache-backed repository/service later,
# override its cache_backend provider with MemoryCacheBackend() here the
# same way container.core.database is overridden below, so tests never
# depend on a real Redis being reachable.

# ── TestDatabase ────────────────────────────────────────────────────────────


class TestDatabase:
    """Drop-in replacement for app.core.database.Database using a pre-built engine."""

    def __init__(self, engine):
        self.engine = engine
        self.session_maker = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )

    async def disconnect(self) -> None:
        pass  # lifecycle is managed by the fixture

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        session: AsyncSession = self.session_maker()
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@pytest.fixture
async def _engine():
    """Single in-memory SQLite engine per test (StaticPool -> one connection)."""
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def client(_engine, tmp_path):
    """AsyncClient against the app, with the DB swapped for a fresh in-memory SQLite and
    artifacts/scratch redirected to a temp dir."""
    test_db = TestDatabase(_engine)
    container.core.database.override(test_db)
    settings.ARTIFACTS_DIR = str(tmp_path / "artifacts")
    settings.WORK_DIR = str(tmp_path / "work")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    await container.generation.runner().wait_all()
    container.core.database.reset_override()
