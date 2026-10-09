# 2. Architecture

## The pipeline

```
 GenerationSpec ──► Planner ──► Connector ──► Raw FHIR ──► Slicer chain ──► Sink
 (API / preset)    (validate,   (Synthea,     (Bundle per   (full record,    (response,
                    pick         others)       patient +     resource-type   zip, NDJSON,
                    connector)                 hospital/     filter, one     FHIR server
                                               practitioner) encounter…)     POST)
```

Each stage has one interface and one job:

| Stage | Interface | Responsibility |
|-------|-----------|----------------|
| Spec | `GenerationSpec` (pydantic) | Cohort + shape + destination, validated |
| Planner | `GenerationService` | Resolve preset → spec, pick connector, create job |
| Connector | `Connector` (ABC) | Produce raw FHIR for a cohort. Knows nothing about slicing |
| Slicer | `Slicer` (protocol) | Pure `Bundle → Bundle(s)` function. Knows nothing about generation |
| Sink | `Sink` (ABC) | Deliver result. Knows nothing about either |

Separation matters: **a new scenario is usually a new slicer or preset; a new data
source is a new connector; a new destination is a new sink.** Never a cross-cutting change.

## Core interfaces (sketch)

```python
class Connector(ABC):
    name: ClassVar[str]

    def __init__(self, options: dict[str, Any]): ...        # plain dict from synthetic_data_connectors.yaml

    @abstractmethod
    async def capabilities(self) -> ConnectorCapabilities: ...   # filters it can honor natively
    @abstractmethod
    async def generate(self, cohort: CohortSpec, workdir: Path) -> RawOutput: ...
    async def healthcheck(self) -> HealthStatus: ...

class Slicer(Protocol):
    name: str
    def apply(self, bundles: Iterable[Bundle], params: dict) -> Iterable[Bundle]: ...

class Sink(ABC):
    async def deliver(self, bundles: Iterable[Bundle], params: dict) -> DeliveryResult: ...
```

- Registries (`ConnectorRegistry`, `SlicerRegistry`, `SinkRegistry`) map the `type`
  string in config/spec to a class. Registration is a decorator; discovery is import-time.
- `capabilities()` lets the planner decide **what to push down vs. post-filter**
  (e.g. Synthea natively honors gender/age/module; "has condition X" is verified by a
  post-filter slicer because native filtering is only approximate).
- Bundles are handled as **plain dicts / lightweight wrappers**, not fully typed
  `fhir.resources` models, by default. Reason: speed on large cohorts and tolerance for
  profile extensions. Optional validation step (config flag) can parse with
  `fhir.resources` to confirm R4 conformance.

## Folder layout (target)

```
fhir-synthetic-data-genetator/
├── plan/                      # these documents
├── backend/                   # built from fastapi-starter-kit
│   ├── pyproject.toml         # uv-managed
│   ├── configs/
│   │   ├── config.yaml                      (starter) app behavior: logging, cors, rate limit
│   │   └── synthetic_data_connectors.yaml   NEW: connectors, sinks, specialties, presets
│   ├── app/
│   │   ├── core/              #   (starter) settings, logging, db, cache
│   │   ├── errors/            #   (starter) + GenerationError family
│   │   ├── generator/         #   NEW — domain code, framework-free
│   │   │   ├── spec.py            GenerationSpec, CohortSpec, ShapeSpec, SinkSpec
│   │   │   ├── config_loader.py   load synthetic_data_connectors.yaml → dicts, env interpolation, validation
│   │   │   ├── registry.py
│   │   │   ├── connectors/
│   │   │   │   ├── base.py
│   │   │   │   └── synthea/       connector.py, runner.py, flags.py, output.py
│   │   │   ├── slicers/
│   │   │   │   ├── base.py
│   │   │   │   ├── full_record.py
│   │   │   │   ├── resource_types.py
│   │   │   │   ├── encounter.py        (encounter + reference closure)
│   │   │   │   ├── date_window.py
│   │   │   │   ├── condition_filter.py
│   │   │   │   └── reference_closure.py  shared helper
│   │   │   ├── sinks/             file.py, zip.py, ndjson.py, fhir_server.py, inline.py
│   │   │   └── validate.py        optional R4 validation
│   │   ├── models/            #   SQLAlchemy: GenerationJob, Artifact
│   │   ├── schemas/           #   API DTOs
│   │   ├── repository/        #   job + artifact persistence
│   │   ├── services/          #   generation_service.py (orchestrates the pipeline)
│   │   ├── routers/           #   generations.py, presets.py, connectors.py, meta.py
│   │   ├── di/                #   wire the above (one container per resource, per starter)
│   │   └── workers/           #   background runner (see below)
│   ├── tests/
│   │   ├── unit/              #   slicers, spec, config loader (fixture bundles, no Java)
│   │   ├── integration/       #   API + fake connector
│   │   └── e2e/               #   real Synthea, marked slow, skipped if no Java
│   └── vendor/synthea/        # (git-ignored) downloaded jar + pinned version file
└── frontend/                  # later
```

**Rule:** `app/generator/` never imports FastAPI, SQLAlchemy, or the DI container. It's a
library the service layer calls. That keeps it testable and lets a CLI reuse it later
(`uv run fhirgen run --preset full-patient-10`).

## Fitting the starter kit

| Starter piece | How we use it |
|---|---|
| Router → Service → Repository | `generations` router → `GenerationService` → `JobRepository` |
| `pydantic-settings` + `configs/*.yaml` | Keep for app behavior. Add a `CONNECTORS_CONFIG_PATH` setting (default `configs/synthetic_data_connectors.yaml`) |
| DI (`dependency-injector`) | New `GeneratorContainer` providing registries + service |
| Error envelope | Add `GenerationError`, `ConnectorUnavailableError`, `InvalidSpecError` subclasses |
| `@trace_methods`, JSON logs, request IDs | Reused as-is; job id added to log context |
| Rate limiting | Write-limit applies to `POST /generations` — tune low |
| DB + Alembic | Persist jobs/artifact metadata. Postgres in Docker; SQLite for tests (already the starter's test pattern) |
| Redis (optional) | Optional job queue/progress later; **v1 does not require it** |
| Example `items` resource | Removed in Phase 0 once `generations` exists (it's the template, not product code) |

## Execution model for jobs

Synthea is CPU-heavy and slow (seconds per patient on cold start, JVM startup ~ few seconds).
Options considered:

| Option | Pros | Cons |
|---|---|---|
| A. FastAPI `BackgroundTasks` + subprocess | Zero infra | Dies with the server; poor visibility |
| **B. In-process job runner (asyncio task pool + DB job table) — chosen for v1** | No extra infra, restart-recoverable (mark orphaned `running` → `failed` at boot), bounded concurrency via semaphore | Single-node |
| C. Celery/RQ/arq + Redis | Scales out | Heavy for v1; the interface makes it a drop-in later |

The `JobRunner` is behind an interface so C can replace B without touching services.
Small requests (`count <= sync_max_patients`, default 5) can run inline and return the payload directly.

## Storage

- Job metadata: DB.
- Artifact metadata is embedded as a JSON list on the job row (no separate table — always read/written with the job).
- Artifacts (generated files): local disk under `data/artifacts/<job_id>/` behind a
  `ArtifactStore` interface (S3/Blob later). TTL cleanup job removes old artifacts.
- Synthea scratch output: per-job temp dir, deleted after slicing unless `keep_raw: true`.
