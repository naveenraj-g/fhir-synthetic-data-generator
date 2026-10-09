# 5. Synthea Connector

> **Status: implemented and verified against Synthea v4.0.0 (Docker).** Everything below marked
> *verified* was observed by running the real jar, not taken from documentation.

## What Synthea is

Java application (`synthetichealth/synthea`) that simulates patient lifetimes through state-machine
"modules" and exports FHIR (R4 default), C-CDA, CSV, … It needs JDK 17+. It is not a Python library,
so the connector runs it as a **subprocess** — inside Docker by default.

## Runtime: Docker (default) or local JDK

| | `mode: docker` (default) | `mode: local` |
|---|---|---|
| Needs | Docker + the `fhir-gen-synthea` image | JDK 17+ and `vendor/synthea/synthea-with-dependencies.jar` |
| Setup | `just synthea-build` | download jar yourself |
| Isolation | JVM version pinned by the image; nothing installed on the host | uses host Java |

- `backend/docker/synthea/Dockerfile`: `eclipse-temurin:17-jre` + the **pinned release jar** (`v4.0.0`, not the
  rolling `master-branch-latest`). `ENTRYPOINT ["java"]`; the connector passes the whole JVM command line.
- Per job the connector creates a work dir, **bind-mounts it at `/work`**, and Synthea writes `/work/output`.
  A generated keep module (below) is written to `/work/keep.json`; a custom `modules_dir` mounts read-only at `/modules`.
- On timeout the connector `docker kill`s the named container — killing only the `docker` client would leave
  the container running.
- **Deployment note:** the API's own Docker image does not contain the Docker CLI. Run the API on the host
  (or mount the socket — not recommended), or use `mode: local` with a JRE added to the API image.
- `healthcheck()` (`GET /connectors/synthea/health`) reports a missing `docker`, a stopped daemon, or a missing
  image with the exact build command. Runs fail fast with `CONNECTOR_UNAVAILABLE` (503).

## Invocation (*verified*, `run_synthea -h`)

```
java -Xmx2g -jar synthea.jar -p <count> -s <seed> -cs <seed> -r <YYYYMMDD>
     [-g M|F] [-a min-max] [-k keep.json] [-d modules_dir]
     --exporter.baseDirectory=<work>/output --exporter.fhir.export=true
     --exporter.hospital.fhir.export=true --exporter.practitioner.fhir.export=true
     --exporter.years_of_history=N --generate.only_alive_patients=true
     [--<property>=<value> ...]  <State> [<City>]
```

Built by `flags.py` as an **argument list** (never a shell string). Properties are validated by name pattern and
the connector-managed ones (`exporter.baseDirectory`, `exporter.fhir.export`, …) cannot be overridden.

**Correction to the earlier plan:** v4.0.0 has **no `-m` module filter**. Specialty/condition targeting uses
`-k` (keep module) instead — see next section.

## Specialties and conditions: keep modules (*verified*)

`cohort.specialty` is expanded by the runtime to a list of condition codes (config: `specialties.<name>.conditions`).
For a non-empty `conditions` list the connector writes a Synthea **keep module** — the same shape as Synthea's own
`keep_modules/keep_diabetes.json`: `Initial → Keep` if the patient has ANY listed `Active Condition`, else
`Terminal`; reaching a state named `Keep` keeps the patient. Synthea regenerates until `-p` patients are kept.

Real runs: 4/4 patients had type 2 diabetes, exact count, ~16 s. This supersedes the earlier "over-generate and
post-filter" idea: filtering is native and exact, so no `oversample_factor` is needed.

**Limit found by testing:** Synthea gives up on a patient slot after `generate.max_attempts_to_keep_patient`
(default 1000), logs `Failed to produce a matching patient after 1000 attempts`, **and exits 0 with fewer
patients.** Mitigations:
1. The connector defaults that property to 10000 (override via `properties`). A rare-ish case (seed 5, diabetes,
   count 3) needed it: 100 s instead of failing.
2. If fewer than `count` patients come back the job fails with `UNSATISFIABLE_COHORT` (422) quoting Synthea's
   message — never a silently short result.

## Behaviors confirmed by running it

| Topic | Observation |
|---|---|
| Speed | ~12–16 s for 1–4 patients (JVM + module load dominate); batch, never one run per patient |
| Size | One patient bundle: 0.4 MB – 8.7 MB (long-lived patients). Inline sink has a 5 MB cap; use `zip`/`ndjson` |
| Determinism | Same seed + `-cs` + pinned `-r` **and `-e`** + same properties ⇒ **byte-identical** files (md5 compared). `-r` only fixes ages; Synthea simulates up to **today** unless `-e` is given (found in Phase 3: the metadata showed `endTime` = today, and a visit dated after `-r`). The connector therefore defaults `-e` to `reference_date`, and an e2e test asserts no encounter is later than it |
| Count semantics | `-p` = alive patients; deceased are extra. Connector passes `generate.only_alive_patients=true` unless `only_alive: false`, so `count` = exported |
| Exit code | **0 even on `OutOfMemoryError`** (zero patients written) and on the give-up case above ⇒ the connector validates the output, not just the exit code |
| Output | `output/fhir/<Name>_<uuid>.json` (transaction Bundle per patient), `hospitalInformation<ts>.json` + `practitionerInformation<ts>.json` (batch Bundles of Organization/Location/Practitioner), `output/metadata/*.json` |
| References | Patient-internal: `urn:uuid:…`. Providers: **conditional** (`Practitioner?identifier=…\|npi`, `Organization?identifier=…`, `Location?identifier=…`) resolved only via the infra bundles ⇒ `full_record` with `include_infrastructure: true` pulls in the matching infra resources. Claims use `#coverage`/`#referral` fragment refs to `contained` resources (valid, not dangling) |
| Version string | The `v4.0.0` release jar reports `v3.4.0-18-ga07a65555` in its metadata (git-describe baked into that build). Recorded verbatim in provenance next to the image tag |

## Procedure-targeted cohorts (*verified*)

`cohort.procedures` (and a specialty's `procedures`) add to the keep module: `(any condition) AND (any procedure)`. Synthea
records performed procedures in the same "present" map as conditions and never removes them, so `Active Condition` on a
procedure code works (this is how Synthea's own `must_have_cabg.json` does it).

**Found by testing:** the keep module judges the patient's *whole life*, but only the last `years_of_history` years are
*exported*. A patient kept for an appendectomy performed in 1999 had no appendectomy in a 20-year export. So for
procedure cohorts the connector exports full history (`years_of_history=0`) unless the request sets it. Condition cohorts
keep the configured window (chronic conditions were present in every tested record, but an old-onset condition outside
the window is not proven to appear).

Specialties may carry a default `age_range`: unbounded searches for diabetes burned 10000 attempts on a slot and
failed (`UNSATISFIABLE_COHORT`); with `[40, 90]` the same request took ~19 s.

## Term index and per-request options (Phase 4)

* **Term search** (`GET /connectors/synthea/terms`): the jar's 536 module files are parsed once per image (extracted with
  `docker create` + `docker cp`) into ~3,400 searchable terms - conditions, procedures, medications, observations,
  allergies, ... - each with a paste-ready `reference` (`SNOMED-CT:73761001`, `ICD10:C25.0`). Cached under `data/cache/`
  keyed by the image id. Found while building it: search is by display text, so "appendectomy" does not find the procedure
  Synthea calls "Excision of appendix" - which is exactly why users need the search.
* **`match: any|all`** between conditions and procedures (keep module `Or` / `And`). Gastroenterology uses `any`.
* **`connector_params`** (per request): `reference_date`, `end_date`, and `properties` limited to the prefixes
  `exporter.fhir.` and `generate.` minus connector-managed ones and `exporter.fhir.bulk_data` (it changes the output
  layout). Anything else - image, JVM flags, modules dir, other exporters - is rejected. Verified: `use_us_core_ig` yields
  US Core profiles on real output.
* Codes: a bare code must be numeric (SNOMED-CT); alphanumeric codes need a system (`ICD10:C25.0`).

## Process handling

`runner.py` uses `subprocess.Popen` in a worker thread (not asyncio subprocesses): asyncio subprocess support
depends on the event-loop implementation (Windows selector loops raise `NotImplementedError`) and uvicorn's loop
choice varies. Stdout/stderr tail (60 lines) is captured and attached to errors. Known gap: a *running* job cannot
yet be cancelled (the worker thread blocks until Synthea ends or times out) — tracked for Phase 4.

## Output handling

`output.py` lists patient bundles sorted by file name (deterministic: names embed seeded UUIDs), yields them lazily,
and reads infra bundles + metadata. Provenance recorded per job: mode, image, jar-reported version, Java version,
seed, reference date, state, keep conditions, records produced.

## Capabilities declared

`count, seed, gender, age_range, state, city, years_of_history, only_alive, specialty, conditions` — all native.
The planner warns (preview and job) for any cohort field a connector does not honour (e.g. `static_fixtures`
ignores `gender`).

## Verified specialty codes (SNOMED-CT, found in Synthea v4.0.0 modules)

| Specialty | Codes |
|---|---|
| diabetes | 44054006 Diabetes mellitus type 2 |
| cardiology | 22298006 Myocardial infarction · 49436004 Atrial fibrillation · 88805009 Chronic congestive heart failure |
| oncology | 254837009 Malignant neoplasm of breast · 363406005 Malignant neoplasm of colon |
| respiratory | 195967001 Asthma |

(Coronary heart disease 53741008 and COPD/CKD codes I guessed were *not* found in the modules and were left out.)

## Other connectors this design does not block

`static_fixtures` (built — instant, no Docker), a Faker-based generator, an LLM enrichment step (as a slicer), a remote
generator service. Synthea licence is Apache-2.0; every output resource is tagged `meta.tag` = v3-ActReason `HTEST`.

## Still open (later phases)

- Per-job cancel of a running container (Phase 4).
- `GET /connectors/synthea/modules` (module list): dropped for now — specialties use condition codes, not module names.
  The v4.0.0 jar has 87 top-level modules if wanted later.
- Procedure-based targeting ("must have CABG") via the same keep-module trick with `Active Condition` on a procedure code
  (Synthea's `must_have_cabg.json` does exactly this) — needed for the `single-surgery-episode` preset in Phase 3.
