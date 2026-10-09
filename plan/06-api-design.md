# 6. API Design

Base path `/api/v1`, following the starter's conventions (router per resource, error
envelope `{"error": {"code","message","details"}}`, pagination via `limit/offset`, OpenAPI
with explicit `operation_id`s so a future frontend/SDK can be generated).

## Endpoints

### Discovery (cheap, drives the future UI)

| Method & path | Purpose |
|---|---|
| `GET /connectors` | Configured connectors, enabled state, capabilities |
| `GET /connectors/{name}/health` | Java/jar present? version? |
| `GET /connectors/{name}/terms?q=&kind=&limit=` | Search the conditions/procedures/... a connector can target; hits carry a `reference` to paste into `cohort` |
| `GET /resource-groups` | Named categories of resource types for the `resource_types` slicer |
| `GET /slicers` | Slicer names + JSON-schema of their params |
| `GET /sinks` | Sink names + param schemas |
| `GET /specialties` | Configured specialties |
| `GET /presets` / `GET /presets/{name}` | Preset catalogue and the resolved spec of one |

### Generation

| Method & path | Purpose |
|---|---|
| `POST /generations` | Submit a spec. Small + inline sink ⇒ `200` with data; else `202` with a job |
| `POST /generations/preview` | Validate + resolve spec (preset merge, push-down vs. post-filter plan, estimated size) **without running** |
| `GET /generations` | List jobs (filter by status), paginated |
| `GET /generations/{id}` | Status, progress, provenance (versions, seeds), errors |
| `GET /generations/{id}/artifacts` | Files produced |
| `GET /generations/{id}/artifacts/{artifact_id}` | Download |
| `GET /generations/{id}/logs` | Tail of connector stdout/stderr |
| `POST /generations/{id}/cancel` | Kill a running job |
| `DELETE /generations/{id}` | Remove job + artifacts |

Convenience, thin wrappers over `POST /generations` with a preset:

- `POST /presets/{name}/run` body: optional overrides.

## Request shape

```jsonc
{
  "preset": "cardiology-cohort",            // optional; or give everything explicitly
  "connector": "synthea",                   // default from config
  "cohort": {
    "count": 25,
    "seed": 42,
    "gender": "F",
    "age_range": [40, 80],
    "state": "Massachusetts",
    "specialty": "cardiology",
    "conditions": [],
    "years_of_history": 5
  },
  "shape": [
    { "slicer": "date_window", "params": { "last_n_days": 730 } },
    { "slicer": "redact_infra" }
  ],
  "sink": { "name": "zip" },
  "connector_params": { "reference_date": "20250101", "properties": { "exporter.fhir.use_us_core_ig": true } },
  "options": { "check_references": true }
}
```

Unknown fields → `422` (`extra="forbid"`, as the starter does for create schemas).

## Job lifecycle

`queued → running → succeeded | failed`, and `succeeded → expired` once the files pass `artifact_ttl_hours`
(metadata kept; downloads return `410 ARTIFACT_EXPIRED`). `cancelled` is still planned.

Job record: id, status, spec (as submitted), **resolved spec** (after merges), provenance
(connector version, seeds, reference date), counts (patients, resources by type), timings,
error (code/message/stdout tail), artifact list, created/expires timestamps.

Orphan recovery at boot: `running` jobs from a previous process ⇒ `failed(code=server_restart)`.

## Response for sync inline

```jsonc
{ "id": "…", "status": "succeeded",
  "summary": { "patients": 1, "resources": {"Patient":1,"Encounter":42,"...": 0} },
  "data": [ { "resourceType": "Bundle", "...": "..." } ] }   // always a list of bundles
```

## Errors (extends starter hierarchy)

| Code | HTTP | When |
|---|---|---|
| `invalid_spec` | 422 | Unknown preset/slicer/sink, bad params, conflicting options |
| `connector_unavailable` | 503 | Java/jar missing, connector disabled |
| `limit_exceeded` | 413/422 | count above `max_patients_per_job`, inline too large |
| `generation_failed` | 500 | Non-zero Synthea exit; details include stdout tail |
| `unsatisfiable_cohort` | 422 | Connector produced fewer than `count` matching patients (details quote the reason) |
| `not_found` | 404 | job / artifact |

## Security & safety

- No arbitrary shell/paths from clients (see config override rules).
- Resource limits: max patients, max concurrent jobs, per-job timeout, artifact TTL, rate limit.
- Auth stays optional per starter; if enabled, permissions `generation:create|read|delete`.
- `fhir_server` sink targets come only from config (no client-supplied URLs → no SSRF).

## Frontend readiness (later)

OpenAPI + `GET /slicers|sinks|presets` schema endpoints are sufficient to render a spec
builder form dynamically. CORS configured through the starter's `cors` block.
