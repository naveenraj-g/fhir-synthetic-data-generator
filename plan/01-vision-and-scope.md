# 1. Vision and Scope

## Problem

Teams building on FHIR need realistic test data, but "realistic" means different
things per use case:

- a QA engineer wants **1,000 complete patient records** to load-test a FHIR server;
- a developer wants **just Observations** (vitals/labs) to test a chart widget;
- a UI dev wants **one encounter with everything hanging off it** (a surgery visit:
  Encounter + Procedure + Conditions + Medications + Practitioner + Location);
- a clinical-analytics team wants **cardiology patients with realistic treatment
  history**, not random people;
- a demo needs **the same data every time** (seeded, reproducible).

Synthea can produce rich records, but it is a Java CLI with a large flag surface and
emits one big Bundle per patient. Nothing in it gives you "just the procedures" or
"one encounter". That gap is this project.

## Users

1. Developers/QA calling the REST API (primary).
2. Data engineers using presets from a script/CI job.
3. Later: non-technical users through a frontend that builds the same spec visually.

## Goals

- G1. One spec format that expresses cohort + shape + destination.
- G2. Connector abstraction — Synthea first, others (Faker-based, template/fixture,
  LLM-assisted, third-party generators) added without touching core code.
- G3. Slicing layer that turns patient-level Bundles into any useful shape.
- G4. Named **presets** in config so common scenarios are one call.
- G5. Reproducibility (seed + pinned Synthea version recorded in job metadata).
- G6. Async jobs for big cohorts; instant response for tiny ones.
- G7. Easy local run (`uv sync && just dev`) and Docker image that bundles Java + Synthea.

## Non-goals (for now)

- Not a FHIR server (we may *push to* one, the user's own server being the obvious target).
- No real PHI ever enters the system; no de-identification of real data.
- No authoring of new clinical modules in v1 (we can point Synthea at custom module
  dirs, but a module-builder UI is out of scope).
- No frontend in v1 (backend first, as agreed).
- No multi-tenant auth in v1 (starter's optional JWT/RBAC stays available).

## Success criteria

- `POST /api/v1/generations` with a preset name returns a downloadable artifact.
- The same spec + seed yields byte-identical FHIR twice.
- Adding a second connector requires: one class, one registry line, one config block.
- Every slicer is unit-tested against fixture bundles with no Java installed.
