import asyncio
from collections.abc import Awaitable, Callable

from app.core.logging import get_logger

logger = get_logger(__name__)


class JobRunner:
    """In-process background runner with bounded concurrency. Single-node by design for
    v1; the interface (`submit`) is what a queue-backed runner would replace
    (plan/02-architecture.md, 'Execution model for jobs')."""

    def __init__(self, max_concurrent: int):
        self._max = max_concurrent
        self._sem: asyncio.Semaphore | None = None
        self._tasks: dict[str, asyncio.Task] = {}

    def submit(self, job_id: str, work: Callable[[], Awaitable[None]]) -> None:
        if self._sem is None:  # created lazily so it binds to the running loop
            self._sem = asyncio.Semaphore(self._max)

        async def guarded() -> None:
            async with self._sem:  # type: ignore[union-attr]
                try:
                    await work()
                except Exception:  # work() records its own failure; this is a last-resort log
                    logger.exception("Job crashed", extra={"event": "job.crashed", "job_id": job_id})

        task = asyncio.create_task(guarded(), name=f"generation-{job_id}")
        self._tasks[job_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(job_id, None))

    async def wait_all(self) -> None:
        """Used by tests (and graceful shutdown) to let in-flight jobs finish."""
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
