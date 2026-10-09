# FHIR Synthetic Data Generator — Plan

A configurable service that produces **synthetic FHIR data** on demand, in whatever
*shape* and *slice* the caller needs. Synthea is the first data source; the design
makes it one pluggable **connector** among several.

## Documents

| # | File | What it answers |
|---|------|-----------------|
| 1 | [01-vision-and-scope.md](01-vision-and-scope.md) | Why, who uses it, goals / non-goals |
| 2 | [02-architecture.md](02-architecture.md) | The pipeline, layers, folder layout, how it sits on the FastAPI starter |
| 3 | [03-scenarios-and-slicing.md](03-scenarios-and-slicing.md) | How we cover "full patient record", "one encounter / operation", "specialty data", etc. |
| 4 | [04-configuration.md](04-configuration.md) | `backend/configs/synthetic_data_connectors.yaml` design, connectors, presets, Python-dict handling |
| 5 | [05-synthea-connector.md](05-synthea-connector.md) | Running Synthea, flags, Java, output handling |
| 6 | [06-api-design.md](06-api-design.md) | FastAPI endpoints, async jobs, request/response shapes |
| 7 | [07-roadmap.md](07-roadmap.md) | Phased delivery, testing, risks, open questions |

## The one-paragraph design

A request (`GenerationSpec`) says **what cohort** (how many patients, demographics,
conditions/specialty, seed), **what shape** (full record, selected resource types,
single encounter + its dependencies, a date window…) and **where it goes**
(response, file/zip, NDJSON, POST to a FHIR server). The service resolves a
*connector* (Synthea today) to produce raw FHIR, runs it through a chain of
*slicers* (pure functions over FHIR Bundles) to cut the exact shape, then hands the
result to a *sink*. Because "shape" is separated from "generation", every scenario
the user listed is a slicer + a preset, not a new generator.

## Decisions already made (from the kickoff)

- Python project managed with **uv**.
- Synthea (`github.com/synthetichealth/synthea`) is the initial connector.
- Everything configurable through `backend/configs/synthetic_data_connectors.yaml`; multiple connectors supported.
- Config is loaded into **plain Python dicts** at the connector boundary.
- `backend/` is built on **`fastapi-starter-kit`** (layered Router → Service → Repository,
  DI, structured logging, error envelope). The FHIR-specific code in `fhir-server-starter`
  is deliberately **not** used.
- A frontend may come later → the API must be self-describing (OpenAPI) and CORS-ready.
