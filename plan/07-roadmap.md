# 7. Roadmap, Testing, Risks, Open Questions

## Phases

### Phase 0 — Foundation (≈ 0.5 day) — ✅ DONE
- Backend scaffold from `fastapi-starter-kit` (done: copied into `backend/`).
- Rename project in `pyproject.toml`; `uv sync`; confirm `just dev` and tests pass.
- Add `CONNECTORS_CONFIG_PATH` setting + `configs/synthetic_data_connectors.yaml` skeleton (exists) + loader with env interpolation.
- Make DB optional-friendly: SQLite default for local dev, Postgres via env (starter assumes Postgres). *(Redis also off by default; removed from docker-compose.)*
- Remove `items` example once `generations` exists.

> **Status (2026-10-09):** Phases 0-4 implemented. 85 unit/API tests + ~30 real-Synthea e2e tests pass.
> Deviations: `limit`/`redact_infra` slicers and `check_references` option came in early;
> `cancel` and `logs` endpoints are deferred to Phase 4 as planned; `static_fixtures` is the default
> connector until Phase 2 lands (`synthea` is configured but `enabled: false`).

### Phase 1 — Pipeline skeleton with no Java (≈ 2–3 days) — ✅ DONE
- `spec.py`, registries, `Connector`/`Slicer`/`Sink` interfaces.
- `static_fixtures` connector + 2–3 hand-trimmed Synthea-shaped fixture bundles in `tests/fixtures/`.
- Slicers: `full_record`, `resource_types`, `limit`, `redact_infra`.
- Sinks: `inline`, `zip`, `ndjson`.
- `GenerationService`, job model/repo, in-process job runner, `/generations` + discovery endpoints.
- Unit tests for slicers; API integration tests (SQLite).
- **Exit:** `POST /generations` with `full-patient` and `vitals-only` presets works end-to-end on fixtures.

### Phase 2 — Synthea connector (≈ 2–3 days) — ✅ DONE (Docker mode)
- Docker image with pinned Synthea (`just synthea-build`); flags/properties verified against v4.0.0 (doc 05 corrected: no `-m`, use keep modules).
- `flags.py`, `runner.py` (async subprocess, timeout, cancel), `output.py`.
- Reproducibility test (same seed twice ⇒ identical).
- Healthcheck endpoint. (Module listing dropped: specialties use condition codes.)
- Synthea runs in its own Docker image; the API image does not bundle Java/Docker (see doc 05 deployment note).
- **Exit:** real 10-patient generation through the API.

### Phase 3 — Advanced shapes (≈ 3–4 days) — ✅ DONE
- `reference_closure` helper; tested against a trimmed REAL Synthea bundle with an independent string-based cross-check (not property tests).
- `encounter` slicer with selectors; `date_window`; `condition_filter`; `condition_scoped`.
- Specialties config (with default age ranges); procedure-targeted cohorts; `UNSATISFIABLE_COHORT` handling. Oversampling dropped (keep modules are exact).
- Presets from doc 03.
- **Exit:** `single-surgery-episode`, `cardiology-cohort`, `er-visits` presets verified on real Synthea output.

### Phase 4 - Dynamic engine + cleanup - ✅ DONE (revised scope)
Decided with the user: **no FHIR-server sink** (the product is "generate, then download a zip"), metadata-only database, files
deleted after 72 h. Built instead: resource groups, `resource_filter`, administrative-only `infrastructure` slicer,
`match: any|all` for specialties (gastroenterology, cardiac-surgery), term search, per-request `connector_params` (US Core,
dates), `last_n_years`, expiry cleanup with `410`, and reference-pruning in every dropping slicer.

### Phase 4 (original plan, superseded) — Delivery & hardening (≈ 2 days)
- `fhir_server` sink (transaction POST, retries, concurrency) — test against the user's FHIR server starter.
- Optional R4 validation; `meta.tag SYNTHETIC` stamping; artifact TTL cleanup; cancel/logs endpoints.
- Orphan recovery, limits, rate-limit tuning, structured logging with job ids.
- README + usage cookbook.

### Frontend - ✅ DONE (Next.js 16 + shadcn/ui)
`frontend/`: Generate (template -> who -> what data -> delivery -> advanced, validated live against `/generations/preview`),
Jobs, Job detail (downloads, reproducibility info, Edit & re-run), Find codes. Slicer forms are rendered from the API's JSON
schemas, so new slicers appear without frontend work; API types are generated from OpenAPI (`pnpm gen:api`). Verified in a
real browser against the live API and real Synthea, which found two integration bugs (trailing-slash redirects through the
proxy; the code picker not taking focus) - see frontend/README.md.

### Templates for specialties - ✅ DONE
Gastroenterology (8), Orthopedics (7), Preventive health (5) added as presets with `title` + `category`, an `orthopedics`
specialty, an `encounter_type` filter on the encounter slicer (wellness visits) and `include_infrastructure` on
`resource_types` (self-contained subsets). All run against real Synthea; findings: a colon-cancer template is impractical
(16+ min, removed), fracture care takes ~3.5 min, and filtered subsets need provider resources attached to be self-contained.

### Specialty coverage - ✅ DONE
20 specialties and 85 templates, each run against real Synthea; new targeting (medications, `within: all` comorbidity);
Synthea stall retry; API Docker image with bundled Java. Findings and the honest list of what is NOT covered:
[08-coverage.md](08-coverage.md).

### Phase 5 — Extensions (backlog)
- Second real connector (Faker-based or remote).
- LLM enrichment step for clinical notes.
- CLI (`fhirgen`) reusing `app/generator`.
- Queue-based runner (arq/Celery) behind the `JobRunner` interface; S3 artifact store.
- Bulk Data (`$export`)-style async manifest.

## Testing strategy

| Layer | Approach |
|---|---|
| Config loader | Table-driven: interpolation, missing vars, bad envelope, preset→unknown slicer |
| Slicers | Fixture bundles; assertions on content **and** reference integrity; property tests (Hypothesis) on closure |
| Connector (Synthea) | Unit: flag building from specs (pure). e2e: real jar, `@pytest.mark.slow`, auto-skip without Java |
| Service/API | Starter's SQLite-swap pattern + `static_fixtures` connector |
| Reproducibility | Same spec twice ⇒ equal hash of outputs |
| Docker smoke | Build image, hit `/health/ready` and one preset |

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Synthea gives up on rare conditions and exits 0 with fewer patients | Higher attempt limit by default; connector fails with `UNSATISFIABLE_COHORT` on any shortfall (found + fixed in Phase 2) |
| Large cohorts blow memory | Stream bundles lazily; limits; JVM `-Xmx` configurable |
| Synthea CLI/properties change between releases | Pin version, verify in Phase 2, connector tests build args and assert against `--help` output when Java available |
| Reference closure misses edge types (e.g. Claim items) | Closure driven by a generic reference walker, not per-type lists; fixtures cover Claim/EOB |
| Windows path/encoding quirks | Short workdirs, explicit UTF-8, arg lists not shell strings; CI on both OSes if possible |
| Starter assumes Postgres/Redis | Phase 0 makes both optional for local dev |
| "Synthetic" data mistaken for real | `meta.tag` stamping, docs, artifact metadata |

## Open questions (need your call; defaults noted so work isn't blocked)

1. **"One operation"** — surgical procedure, or FHIR operation like `$everything`?
   *Default:* encounter-centered episode (+ `full_record` covers `$everything`).
2. ~~Config location~~ — decided: inside `backend/configs/synthetic_data_connectors.yaml`.
3. **Database** — Postgres (starter default) or SQLite for jobs in v1?
   *Default:* SQLite locally, Postgres in Docker; same code.
4. **Is your `fhir-server-starter` the intended `fhir_server` sink target?**
   *Default:* yes, generic FHIR REST, tested against it in Phase 4.
5. **FHIR flavor** — plain R4 or US Core profiled by default?
   *Default:* plain R4, US Core as an option.
6. **Java availability** — OK to install a JDK locally, or Docker-only for Synthea?
   *Default:* install JDK locally for dev; Docker for deployment.
7. **Auth** needed in v1? *Default:* off (starter's optional JWT stays dormant).
