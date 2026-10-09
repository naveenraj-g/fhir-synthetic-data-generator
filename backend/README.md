# FHIR Synthetic Data Generator — backend

Configurable synthetic FHIR data service. Pick a **connector** (Synthea, run in
Docker; plus a no-Java fixtures connector), shape the output with
**slicers** (full record, resource types, ...), deliver it with a **sink** (inline,
zip, NDJSON). Design: [`../plan/`](../plan/README.md).

Built on a layered FastAPI starter: `Router → Service → Repository → Model`, DI,
structured JSON logging, a consistent `{"error": {code, message, details}}` envelope.

## Run it

Deploying? `backend/Dockerfile` bundles Java and the pinned Synthea jar (`SYNTHEA_MODE=local`), so the container needs no Docker
socket: `docker build -t fhir-gen-api backend && docker run -p 8000:8000 fhir-gen-api`. (Verified.)


Synthea runs in Docker (default). Build its image once:

```bash
just synthea-build                # docker build -t fhir-gen-synthea:4.0.0 docker/synthea
curl localhost:8000/api/v1/connectors/synthea/health   # once the API is up: confirms Docker + image
```

No Docker? Use `demo-fixture-patient` / `connector: static_fixtures` (sample bundles, instant), or set
`mode: local` on the synthea connector (JDK 17+ and the jar in `vendor/synthea/`).

```bash
uv sync
uv run alembic upgrade head      # creates backend/data/app.db (SQLite) by default
just dev                          # http://localhost:8000/docs  (also /docs/scalar, /redoc)
just test                         # fast: no Docker needed
just test-e2e                     # real Synthea in Docker (~1 min)
```

Postgres instead: set `DATABASE_URL=postgresql+asyncpg://...` (see `.env.example`) or `docker compose up -d`.

## Try it

```bash
# one full patient, returned inline
curl -X POST localhost:8000/api/v1/generations/ -H 'content-type: application/json' \
  -d '{"preset": "full-patient", "cohort": {"seed": 42}}'

# 50 patients, Observations only, as NDJSON files (async job -> 202)
curl -X POST localhost:8000/api/v1/presets/vitals-only/run -H 'content-type: application/json' -d '{}'
curl localhost:8000/api/v1/generations/<id>        # status + artifact download URLs

# dry-run: see the resolved spec and warnings without generating
curl -X POST localhost:8000/api/v1/generations/preview -d '{"preset": "vitals-only"}' -H 'content-type: application/json'
```

Shapes - cut exactly the slice you need from each patient's record:

```bash
# one surgical episode: the appendectomy visit + everything belonging to it (13 resources instead of ~500)
curl -X POST localhost:8000/api/v1/presets/single-surgery-episode/run -H 'content-type: application/json' -d '{"cohort": {"seed": 3}}'

# every ER visit as its own bundle; the story of a condition; only the last two years
curl -X POST localhost:8000/api/v1/presets/er-visits/run          -H 'content-type: application/json' -d '{}'
curl -X POST localhost:8000/api/v1/presets/diabetes-journey/run   -H 'content-type: application/json' -d '{}'
curl -X POST localhost:8000/api/v1/presets/recent-history/run     -H 'content-type: application/json' -d '{}'

# or compose your own: any cohort x any chain of slicers x any sink
curl -X POST localhost:8000/api/v1/generations/ -H 'content-type: application/json' -d '{
  "cohort": {"count": 5, "specialty": "cardiology", "seed": 1},
  "shape": [{"slicer": "date_window", "params": {"last_n_days": 365}}, {"slicer": "redact_infra"}],
  "sink": {"name": "ndjson"}}'
```

Slicers: `full_record`, `resource_types`, `resource_filter`, `infrastructure`, `encounter`, `date_window`,
`condition_scoped`, `condition_filter`, `limit`, `redact_infra` (`GET /api/v1/slicers` has each one's parameter schema). Episode-style slicers never leave dangling
references, and a shape that matches nothing fails with `UNSATISFIABLE_COHORT` instead of returning an empty success.

Specialty cohorts (Synthea keeps generating until `count` patients have the condition):

```bash
curl -X POST localhost:8000/api/v1/presets/diabetes-cohort/run -H 'content-type: application/json' -d '{"cohort": {"count": 5, "seed": 1}}'
# rare conditions can take minutes; if Synthea can't find enough matches you get UNSATISFIABLE_COHORT (422), never a short result
```

Discovery: `GET /api/v1/{connectors,slicers,sinks,specialties,presets}`.

## Delivery: which sink?

| Sink | Use it for | Notes |
|---|---|---|
| `json` | **Viewing in the UI + one downloadable file** (the UI's default "View here + download") | Background job; one `bundles.json` (a list of bundles) kept 72 h |
| `zip` | Any size: one JSON file per bundle, compressed | Background job, kept 72 h |
| `ndjson` | One file per resource type (Bulk Data style) | Background job, kept 72 h |
| `inline` | API callers with small/fast runs (fixtures) | **Holds the HTTP request open** for the whole run and the result is never stored: a proxy timeout or dropped connection loses it. Not offered in the UI. Real Synthea runs: use `json` |

## What do you need? (pick any combination: who x what slice x delivery)

| You need | Send |
|---|---|
| Whole patient history | preset `full-patient` / `diabetes-cohort`, or `shape: [{slicer: full_record}]` |
| Only the **past 5 years** | `shape: [{slicer: date_window, params: {last_n_years: 5}}]` (or preset `last-5-years`) |
| **Only patients** (demographics) | `shape: [{slicer: resource_types, params: {groups: [demographics]}}]` |
| **Only administration** (providers, organizations, locations) | `shape: [{slicer: infrastructure}]` (preset `administrative-data`) |
| **Only billing** | `resource_types` with `groups: [financial]` (preset `financial-data`) |
| Only **vitals** / only **labs** | `resource_types` + `resource_filter` with `categories: [vital-signs]` / `[laboratory]` |
| One specific **disease** | `cohort: {conditions: ["44054006"]}` (+ `condition_scoped` to keep just that disease's story) |
| A **specialty** (disease **or** operations) | `cohort: {specialty: "gastroenterology"}`, or your own: `{conditions: [...], procedures: [...], match: "any"}` |
| One **operation** with everything around it | `cohort: {procedures: ["80146002"]}` + `encounter` slicer with `with_procedure` |
| Anything not listed | combine slicers: they chain in order, each one's output feeds the next |

### Specialties and targeting

20 specialties (`GET /api/v1/specialties`): cardiology, pulmonology, neurology, mental health, endocrinology, nephrology,
oncology, dermatology, ENT, infectious disease, ophthalmology, rheumatology, women's health, hematology, pediatrics,
geriatrics, gastroenterology, orthopedics, diabetes, cardiac surgery. Each was run against real Synthea. Coverage, limits
and what is *not* possible: [plan/08-coverage.md](../plan/08-coverage.md).

Targeting a cohort (all in the request, no config needed): `conditions`, `procedures`, `medications` (currently taking), joined
by `match: all|any`; `within: all` requires *every* listed condition (diabetes **and** hypertension).

Robustness: Synthea occasionally stalls on a seed. After `timeout_seconds` the run is retried once with a derived seed
(`retries_on_timeout`), and the job's provenance records `seed_used` / `retried_after_timeout`.

### Ready-made templates (`GET /api/v1/presets`, grouped by `category`)

85 templates ship in `configs/synthetic_data_connectors.yaml`; the UI groups them by category. Every one was run against real Synthea.

| Group | Templates |
|---|---|
| **Gastroenterology** | one patient with *all* their GI operations; one full record; one template per operation (colonoscopy, gallbladder removal, appendectomy, partial colon resection); acid-reflux journey; several patients' GI operations |
| **Orthopedics** (bones and joints) | one patient with all their joint operations; one full record; knee replacement; hip replacement; fracture care; osteoarthritis journey; osteoporosis journey |
| **Preventive health** | routine check-up visits; screening tests (depression, anxiety, substance use, fall risk, HIV/hepatitis, mammography, bone density); vaccinations; risk-factor checks (vitals, lifestyle, questionnaires); one patient's preventive profile |
| **20 more groups** | Cardiology, Pulmonology, Neurology, Mental health, Endocrinology, Nephrology, Oncology, Dermatology, ENT, Infectious disease, Ophthalmology, Rheumatology, Women's health, Hematology, Pediatrics, Geriatrics: one full record per specialty + condition journeys and operation stays |
| **General** | whole record, patients only, billing only, administration only, vitals, labs, past 2 / 5 years, ER visits, diabetes, cardiology, one appendectomy stay, instant demo |

*Preventive health* = care that happens before someone is ill. Add your own by copying one in the YAML (`title`, `category`, `description`, `cohort`, `shape`, `sink`). Rare conditions are slow: fracture care took ~3.5 min and a *colon cancer* template was dropped after 16+ min without finishing.

Don't know the code for "colonoscopy" or "reflux"? **Search for it**: `GET /api/v1/connectors/synthea/terms?q=colonoscopy`
returns codes with a ready-to-paste `reference` (about 3,400 conditions, procedures, medications and labs from the real
Synthea modules). `GET /api/v1/resource-groups` lists the named categories. `GET /api/v1/slicers` lists every slicer with
its parameters.

Per-request Synthea options (`connector_params`) cover what people vary: `reference_date`, `end_date`, and a safe subset of
properties, e.g. `{"properties": {"exporter.fhir.use_us_core_ig": true}}` for US Core profiles. Paths, images and JVM flags
stay config-only.

## Configuration

| File | Purpose |
|---|---|
| `configs/synthetic_data_connectors.yaml` | **Generator config**: connectors, slicer defaults, sinks, specialties, presets, limits |
| `configs/config.yaml`, `configs/cache.yaml` | App behavior: logging, CORS, rate limit, pagination, mounted routers |
| `.env` | Per-environment secrets/URLs (`DATABASE_URL`, `${VAR}`s referenced from the connectors file) |

Request precedence: **request body > preset > config defaults.** Synthea output is only reproducible
because `reference_date` is pinned in the connector options (otherwise it depends on today's date). Component options are plain
dicts from the YAML; each connector/slicer/sink validates its own.

## Layout

```
app/generator/     framework-free library: spec, config_loader, registry, runtime, codes (code/text matching),
                   connectors/ (synthea/, static_fixtures), slicers/, sinks/   <- add new ones here
app/routers/       generations.py (jobs), catalog.py (discovery + preset run)
app/services/      generation_service.py, catalog_service.py
app/workers/       job_runner.py (in-process, bounded concurrency)
fixtures/synthea_r4/   Synthea-shaped sample bundles for the static_fixtures connector
docker/synthea/        Dockerfile for the Synthea runtime image
```

### Add a slicer / sink / connector

Subclass the base in `app/generator/{slicers,sinks,connectors}/base.py`, decorate with
`@slicers.register("name")` (etc.), define a pydantic `Params`/`Options` model, and import the
module in the package `__init__`. Presets and specialties are YAML only.

## Notes

- `summary.patients` counts Patient resources, so episode-per-visit shapes report one per bundle.
- Every output resource is tagged `meta.tag` = v3-ActReason `HTEST` (test health data).
- Jobs left `queued`/`running` by a previous process are marked failed at startup.
- Generated files are deleted after `artifact_ttl_hours` (72 by default; checked every `cleanup_interval_minutes`). The metadata
  row (request, timings, counts, seed) stays with status `expired`, and downloading returns `410 ARTIFACT_EXPIRED`.
- Real Synthea runs take ~15 s+ (JVM start-up); a 1-patient inline request blocks that long. Use file sinks for cohorts.
- Redis is off by default (`redis.enabled: false`); nothing in v1 needs it.
