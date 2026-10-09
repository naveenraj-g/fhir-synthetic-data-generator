import asyncio
from collections.abc import Awaitable, Callable

from app.core.logging import get_logger

logger = get_logger(__name__)


async def run_periodically(task: Callable[[], Awaitable[object]], interval_seconds: float, name: str) -> None:
    """Run `task` now and then every `interval_seconds` until cancelled. A failing run is logged, never fatal."""
    while True:
        try:
            await task()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Periodic task failed", extra={"event": "worker.failed", "task": name})
        await asyncio.sleep(interval_seconds)
