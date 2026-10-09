# 4. Configuration

## Two config layers (kept separate on purpose)

| File | Owner | Contains |
|---|---|---|
| `backend/configs/config.yaml` (+ `.env`) | Starter kit, `pydantic-settings` | App behavior & secrets: logging, CORS, rate limit, DB URL, Redis |
| **`backend/configs/synthetic_data_connectors.yaml`** | **This project** | Generator: connectors, slicers defaults, sinks, specialties, presets, limits |

It lives inside `backend/` because it is tightly coupled to it (it configures the Synthea
runner the backend executes). The starter's settings gain one new field,
`CONNECTORS_CONFIG_PATH` (default `configs/synthetic_data_connectors.yaml`, resolved
relative to the backend package, not the CWD). Secrets (e.g. the FHIR-server token)
never live in the YAML — they're referenced as `${ENV_VAR}` and expanded at load time.

## "Config as Python dict"

The loader returns **plain `dict`s** and the connector/sink/slicer receive their own
sub-dict. The core does *not* define a rigid schema for connector options:

```
connectors yaml ──yaml.safe_load──► dict ──env-interpolate──► dict ──┐
                                                                  ├─► Connector(options: dict)
                                                  connector validates its own dict
                                                  with its own small pydantic model
```

Why: adding a connector must not require editing a central schema. Each connector owns
`class Options(BaseModel)` and validates in `__init__`. Only the **envelope**
(`type`, `enabled`, `options`) is validated centrally.

## Draft `configs/synthetic_data_connectors.yaml`

```yaml
version: 1

defaults:
  connector: synthea
  fhir_version: R4
  limits:
    sync_max_patients: 5          # <= this runs inline, else async job
    max_patients_per_job: 5000
    inline_max_bytes: 5_000_000
    max_concurrent_jobs: 2
    artifact_ttl_hours: 72

connectors:
  synthea:
    type: synthea
    enabled: true
    options:
      jar_path: vendor/synthea/synthea-with-dependencies.jar
      java_bin: java                 # or absolute path / ${JAVA_HOME}/bin/java
      synthea_version: "3.x"         # pinned; recorded on every job
      jvm_args: ["-Xmx2g"]
      timeout_seconds: 1800
      modules_dir: null              # custom module folder (-d)
      properties:                    # forwarded as --key=value overrides
        exporter.fhir.export: true
        exporter.fhir.use_us_core_ig: false
        exporter.hospital.fhir.export: true
        exporter.practitioner.fhir.export: true
        exporter.years_of_history: 10
        generate.only_alive_patients: false
      default_state: Massachusetts
  # Future connectors — same envelope, different options:
  # faker:
  #   type: faker_fhir
  #   enabled: false
  #   options: { locale: en_US }
  # fixtures:
  #   type: static_fixtures
  #   options: { directory: fixtures/ }

slicers:                           # defaults per slicer, overridable per request
  redact_infra:
    drop_types: [Claim, ClaimResponse, ExplanationOfBenefit]
  encounter:
    closure: true

sinks:
  zip:      { type: zip }
  ndjson:   { type: ndjson }
  inline:   { type: inline }
  my_fhir_server:
    type: fhir_server
    enabled: false
    options:
      base_url: ${FHIR_TARGET_URL}
      auth: { type: bearer, token: ${FHIR_TARGET_TOKEN} }
      mode: transaction              # transaction | per_resource
      concurrency: 4
      retries: 3

specialties:
  cardiology:
    modules: [cardiovascular_disease, congestive_heart_failure, atrial_fibrillation]
    require_any_condition: []        # filled/verified against pinned Synthea
    oversample_factor: 4
  diabetes:
    modules: [metabolic_syndrome_disease, metabolic_syndrome_care]
    oversample_factor: 3

presets:
  full-patient:
    description: One complete patient record
    cohort: { count: 1 }
    shape: [ { slicer: full_record } ]
    sink: { name: inline }
  vitals-only:
    cohort: { count: 50 }
    shape: [ { slicer: resource_types, params: { types: [Observation] } } ]
    sink: { name: ndjson }
  single-surgery-episode:
    cohort: { count: 1, oversample_factor: 5 }
    shape:
      - { slicer: encounter, params: { selector: { with_procedure: surgical }, closure: true } }
    sink: { name: inline }
```

> The draft above is the original design sketch. The shipped file is
> `backend/configs/synthetic_data_connectors.yaml` — the Synthea options there are `mode`, `docker_image`,
> `reference_date`, `properties`, …, and specialties are lists of verified SNOMED condition codes (doc 05).

## Loader behavior

1. Read YAML (UTF-8 explicitly — Windows default encoding bites otherwise).
2. Expand `${VAR}` / `${VAR:-default}` from the environment; missing required var → error
   naming the exact key path.
3. Validate the **envelope** with pydantic (types known? presets reference existing
   slicers/sinks/connectors/specialties?). Fail fast at startup with a readable list of all problems.
4. Freeze into an immutable `GeneratorConfig` object holding the dicts; expose
   `config.connector_options("synthea") -> dict`.
5. Optional hot-reload endpoint (`POST /admin/config/reload`) — post-v1.

## Request-time overrides

Precedence (highest first): **request body > preset > specialty > config defaults > connector defaults.**
Overrides are deep-merged dicts; lists replace, not append. A request may *not* override
connector `jar_path`, `java_bin`, or `modules_dir` (path-injection guard) — those are
config-only. `properties` overrides are checked against an allow-list pattern.

## Adding things

| To add… | Do |
|---|---|
| A connector | subclass `Connector`, `@register_connector("name")`, add block under `connectors:` |
| A slicer | implement `Slicer`, `@register_slicer("name")` |
| A preset / specialty | YAML only |
| A sink | subclass `Sink`, `@register_sink("name")`, block under `sinks:` |
