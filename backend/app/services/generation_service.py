import asyncio
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger, trace_methods
from app.errors.domain import BusinessRuleViolationError, GoneError, NotFoundError
from app.generator import bundle_reader
from app.generator.errors import GeneratorError
from app.generator.runtime import GeneratorRuntime, PipelineResult
from app.generator.spec import GenerationRequest, ResolvedSpec
from app.models.generation_job import GenerationJobModel
from app.repository.generation_job_repository import GenerationJobRepository
from app.schemas.generation import (
    ArtifactResponse,
    BundleIndexResponse,
    GenerationResultResponse,
    JobResponse,
    PreviewResponse,
)
from app.workers.job_runner import JobRunner

logger = get_logger(__name__)

# The last result opened for viewing: the flow page asks for the index and then one bundle at a time, so parse once.
# Module-level because the service itself is created per request.
_bundle_cache: tuple[object, list[dict]] = (None, [])


def _error_dict(exc: Exception) -> dict:
    if isinstance(exc, GeneratorError):
        return {"code": exc.code, "message": exc.message, "details": exc.details}
    return {"code": "INTERNAL_ERROR", "message": "Unexpected error during generation", "details": []}


@trace_methods
class GenerationService:
    """Orchestrates a generation: resolve spec -> persist job -> run pipeline (inline for
    inline sinks, otherwise on the background runner) -> record outcome."""

    def __init__(
        self,
        repository: GenerationJobRepository,
        runtime: GeneratorRuntime,
        runner: JobRunner,
    ):
        self.repository = repository
        self.runtime = runtime
        self.runner = runner

    # ── paths ────────────────────────────────────────────────────────────
    @property
    def _artifacts_root(self) -> Path:
        return settings.resolve_path(settings.ARTIFACTS_DIR)

    def _artifact_dir(self, job_id: str) -> Path:
        return self._artifacts_root / job_id

    # ── response shaping ─────────────────────────────────────────────────
    @staticmethod
    def to_response(job: GenerationJobModel) -> JobResponse:
        return JobResponse(**GenerationService._job_fields(job))

    @staticmethod
    def _job_fields(job: GenerationJobModel) -> dict:
        return {
            "id": job.id,
            "status": job.status,
            "connector": job.connector,
            "preset": job.preset,
            "request": job.request,
            "resolved_spec": job.resolved_spec,
            "provenance": job.provenance,
            "summary": job.summary,
            "error": job.error,
            "artifacts": [
                ArtifactResponse(
                    id=a["id"],
                    filename=a["filename"],
                    size=a["size"],
                    content_type=a["content_type"],
                    download_url=f"/api/v1/generations/{job.id}/artifacts/{a['id']}",
                )
                for a in (job.artifacts or [])
            ],
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "expires_at": job.expires_at,
        }

    # ── use cases ────────────────────────────────────────────────────────
    async def preview(self, request: GenerationRequest) -> PreviewResponse:
        spec = self.runtime.resolve(request)
        return PreviewResponse(
            resolved_spec=spec,
            mode="sync" if self.runtime.sink_is_inline(spec) else "async",
            warnings=spec.warnings,
        )

    async def submit(self, request: GenerationRequest) -> tuple[GenerationResultResponse, bool]:
        """Returns (response, completed_inline). Raises GeneratorError for invalid specs and
        for failures of inline runs; async failures are recorded on the job instead."""
        spec = self.runtime.resolve(request)
        job = await self.repository.create(
            id=str(uuid.uuid4()),
            status="queued",
            connector=spec.connector,
            preset=spec.preset,
            request=request.model_dump(mode="json", exclude_none=True),
            resolved_spec=spec.model_dump(mode="json"),
            artifacts=[],
        )

        if self.runtime.sink_is_inline(spec):
            result, error = await self._execute(job.id, spec)
            if error is not None:
                raise error
            job = await self.repository.get(job.id)
            return GenerationResultResponse(**self._job_fields(job), data=result.inline), True

        self.runner.submit(job.id, lambda: self._execute_discarding(job.id, spec))
        return GenerationResultResponse(**self._job_fields(job)), False

    async def get_job(self, job_id: str) -> GenerationJobModel:
        job = await self.repository.get(job_id)
        if job is None:
            raise NotFoundError(f"Generation {job_id} not found")
        return job

    async def list_jobs(
        self, *, status: str | None, limit: int, offset: int
    ) -> tuple[list[GenerationJobModel], int]:
        return await self.repository.list(status=status, limit=limit, offset=offset)

    async def get_artifact_path(self, job_id: str, artifact_id: str) -> tuple[Path, dict]:
        job = await self.get_job(job_id)
        if job.status == "expired":
            raise GoneError(
                f"The files of generation {job_id} expired and were deleted. Run it again with the same "
                "request (and seed) to regenerate them.",
                code="ARTIFACT_EXPIRED",
            )
        for artifact in job.artifacts or []:
            if artifact["id"] == artifact_id:
                path = (self._artifact_dir(job_id) / artifact["filename"]).resolve()
                if not path.is_relative_to(self._artifact_dir(job_id).resolve()) or not path.is_file():
                    break
                return path, artifact
        raise NotFoundError(f"Artifact {artifact_id} not found for generation {job_id}")

    # ── viewing the stored bundles (the flow graph) ──────────────────────
    async def _stored_bundles(self, job_id: str) -> list[dict]:
        job = await self.get_job(job_id)
        if job.status == "expired":
            raise GoneError(
                f"The files of generation {job_id} expired and were deleted. Run it again to draw it.",
                code="ARTIFACT_EXPIRED",
            )
        directory = self._artifact_dir(job_id).resolve()
        files = [directory / a["filename"] for a in job.artifacts or []]
        files = [f for f in files if f.resolve().is_relative_to(directory) and f.is_file()]
        if job.status != "succeeded" or not files:
            raise NotFoundError("This job has no stored result to show. Only finished jobs with stored files can be drawn.")
        global _bundle_cache
        key = (job_id, tuple((str(f), f.stat().st_mtime_ns) for f in files))
        if _bundle_cache[0] == key:
            return _bundle_cache[1]
        try:
            bundles = await asyncio.to_thread(bundle_reader.load_bundles, files)
        except ValueError as exc:
            raise BusinessRuleViolationError(str(exc)) from exc
        _bundle_cache = (key, bundles)
        return bundles

    async def bundle_index(self, job_id: str) -> BundleIndexResponse:
        bundles = await self._stored_bundles(job_id)
        return BundleIndexResponse(count=len(bundles), items=bundle_reader.summarize(bundles))

    async def get_bundle(self, job_id: str, index: int) -> dict:
        bundles = await self._stored_bundles(job_id)
        if not 0 <= index < len(bundles):
            raise NotFoundError(f"Bundle {index} not found: this job has {len(bundles)}")
        return bundles[index]

    async def delete_job(self, job_id: str) -> None:
        if not await self.repository.delete(job_id):
            raise NotFoundError(f"Generation {job_id} not found")
        shutil.rmtree(self._artifact_dir(job_id), ignore_errors=True)

    async def cleanup_expired(self) -> int:
        """Delete the files of jobs past `expires_at`; keep the metadata row (status becomes 'expired')."""
        expired = await self.repository.list_expired(datetime.now(UTC))
        for job in expired:
            shutil.rmtree(self._artifact_dir(job.id), ignore_errors=True)
            await self.repository.update(job.id, status="expired", artifacts=[])
        if expired:
            logger.info("Expired artifacts deleted", extra={"event": "job.expired", "count": len(expired)})
        return len(expired)

    async def recover_orphans(self) -> int:
        """Run at startup: jobs a previous process left queued/running can never finish."""
        count = await self.repository.fail_orphans(
            {"code": "SERVER_RESTART", "message": "Server restarted while the job was in flight", "details": []}
        )
        if count:
            logger.warning(
                "Marked orphaned jobs failed", extra={"event": "job.orphans_failed", "count": count}
            )
        return count

    # ── execution ────────────────────────────────────────────────────────
    async def _execute_discarding(self, job_id: str, spec: ResolvedSpec) -> None:
        await self._execute(job_id, spec)

    async def _execute(
        self, job_id: str, spec: ResolvedSpec
    ) -> tuple[PipelineResult | None, Exception | None]:
        await self.repository.update(job_id, status="running", started_at=datetime.now(UTC))
        workdir = settings.resolve_path(settings.WORK_DIR) / job_id[:8]
        try:
            result = await self.runtime.run(
                spec, workdir=workdir, artifact_dir=self._artifact_dir(job_id)
            )
        except asyncio.CancelledError:
            # The HTTP client went away mid-run (browser closed, proxy timeout) while an `inline` request was waiting.
            # Without this the row would stay "running" until the next restart mislabels it SERVER_RESTART.
            shutil.rmtree(self._artifact_dir(job_id), ignore_errors=True)
            await asyncio.shield(
                self.repository.update(
                    job_id,
                    status="failed",
                    error={
                        "code": "REQUEST_CANCELLED",
                        "message": "The request was cancelled before the run finished (the client disconnected or a "
                        "proxy timed out). Use ZIP or JSON delivery for runs that take long.",
                        "details": [],
                    },
                    finished_at=datetime.now(UTC),
                )
            )
            raise
        except Exception as exc:
            if not isinstance(exc, GeneratorError):
                logger.exception("Generation failed", extra={"event": "job.failed", "job_id": job_id})
            shutil.rmtree(self._artifact_dir(job_id), ignore_errors=True)
            await self.repository.update(
                job_id, status="failed", error=_error_dict(exc), finished_at=datetime.now(UTC)
            )
            return None, exc
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        now = datetime.now(UTC)
        ttl = timedelta(hours=self.runtime.config.limits.artifact_ttl_hours)
        await self.repository.update(
            job_id,
            status="succeeded",
            provenance=result.provenance,
            summary=result.summary,
            artifacts=[
                {
                    "id": uuid.uuid4().hex[:12],
                    "filename": a.filename,
                    "size": a.size,
                    "content_type": a.content_type,
                }
                for a in result.artifacts
            ],
            finished_at=now,
            expires_at=(now + ttl) if result.artifacts else None,
        )
        return result, None
