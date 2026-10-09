from dependency_injector import containers, providers

from app.core.config import settings
from app.generator import registry  # noqa: F401  (also imports built-in connectors/slicers/sinks)
from app.generator.runtime import GeneratorRuntime
from app.repository.generation_job_repository import GenerationJobRepository
from app.services.catalog_service import CatalogService
from app.services.generation_service import GenerationService
from app.workers.job_runner import JobRunner


def _build_runtime() -> GeneratorRuntime:
    return GeneratorRuntime.from_path(settings.resolve_path(settings.CONNECTORS_CONFIG_PATH))


def _build_runner(runtime: GeneratorRuntime) -> JobRunner:
    return JobRunner(max_concurrent=runtime.config.limits.max_concurrent_jobs)


class GenerationContainer(containers.DeclarativeContainer):
    core = providers.DependenciesContainer()

    # Singletons: the config is loaded (and validated) once per process, and the runner
    # owns the in-flight job tasks, so there must be exactly one.
    runtime = providers.Singleton(_build_runtime)
    runner = providers.Singleton(_build_runner, runtime=runtime)

    generation_job_repository = providers.Factory(
        GenerationJobRepository,
        session_factory=core.database.provided.session,
    )

    generation_service = providers.Factory(
        GenerationService,
        repository=generation_job_repository,
        runtime=runtime,
        runner=runner,
    )

    catalog_service = providers.Factory(CatalogService, runtime=runtime)
