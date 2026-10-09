# FHIR Synthetic Data Generator

[![CI](https://github.com/naveenraj-g/fhir-synthetic-data-generator/actions/workflows/ci.yml/badge.svg)](https://github.com/naveenraj-g/fhir-synthetic-data-generator/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Generate realistic **synthetic FHIR R4 data** on demand: choose **who** (how many patients, a disease, a specialty, an operation),
**what slice of their record** (everything, only patients, only vitals, one surgical stay, the past five years...), and **how
to receive it** (viewed on the job page, or as a JSON / ZIP / NDJSON download). Powered by
[Synthea](https://github.com/synthetichealth/synthea), run inside the Docker image or in Docker beside your API. A web UI
shows each result as a graph of the patient's resources and how they connect.

> **The data is synthetic**, not real patient data (every resource is tagged `HTEST`). It is for testing, demos and
> development. This project is not affiliated with MITRE or the Synthea team.

| | |
|---|---|
| `backend/` | FastAPI service: connectors, slicers, sinks, jobs. See [backend/README.md](backend/README.md) |
| `frontend/` | Next.js UI over the API. See [frontend/README.md](frontend/README.md) |
| `plan/` | Design documents and roadmap |

## Quick start

```bash
# 1. Synthea's Docker image (once)
cd backend && just synthea-build

# 2. API
uv sync && uv run alembic upgrade head && just dev        # http://localhost:8000/docs

# 3. UI (another terminal)
cd frontend && pnpm install && pnpm dev                   # http://localhost:3000
```

No Docker? Pick the **Demo fixture patient** template (or the `static_fixtures` connector): instant sample data, no Synthea.

## Run it with Docker (everything in one image)

One image holds the web UI, the API and Synthea (with Java), so nothing else needs installing:

```bash
docker run -p 3000:3000 -v fhir-data:/app/backend/data ghcr.io/naveenraj-g/fhir-synthetic-data:latest   # http://localhost:3000
# or build it yourself:  docker compose up --build
```

* **Memory:** give Docker at least **3 GB** (Synthea's JVM uses up to 2 GB). Docker Desktop's default can be too low.
* **Data:** `-v fhir-data:/app/backend/data` keeps the job history and generated files (72 h) across restarts. Without it
  they vanish with the container.
* **First start** takes about a minute (the database is created, then the servers start). `docker ps` shows `healthy` when
  it is ready.
* **The API alone** (docs at `/docs`, for scripts): add `-p 8000:8000`.
* **No login.** Anyone who can reach the port can generate data and see every job. Keep it on a trusted network, or put
  an authenticating proxy in front, before sharing it more widely.

**Sharing the image** (so others do not build it): push it to a registry, then they only need `docker run`.

```bash
docker build -t <registry>/<you>/fhir-synthetic-data:1.0 .
docker push <registry>/<you>/fhir-synthetic-data:1.0                 # e.g. Docker Hub, or ghcr.io
docker run -p 3000:3000 -v fhir-data:/app/backend/data <registry>/<you>/fhir-synthetic-data:1.0
# Intel/AMD and Apple-silicon machines both: docker buildx build --platform linux/amd64,linux/arm64 --push -t ... .
# No registry: docker save fhir-synthetic-data | gzip > fhir-synthetic-data.tar.gz     then on the other machine:
#              docker load < fhir-synthetic-data.tar.gz
```

Settings are the files in `backend/configs/` (templates, specialties, limits); to change them without rebuilding, mount
your own copy: `-v ./my-connectors.yaml:/app/backend/configs/synthetic_data_connectors.yaml:ro`.

## What is stored

Only metadata: the request, timings, counts and the seed. Generated files are kept for 72 hours so you can download them,
then deleted. (Only the API's `inline` option, which returns the data in the response, stores nothing.)

## Contributing, security, licence

* [CONTRIBUTING.md](CONTRIBUTING.md): set up, tests, where things are.
* [SECURITY.md](SECURITY.md): how to report a vulnerability, and what the app does not protect (it has no login).
* Licensed under the [Apache License 2.0](LICENSE). [NOTICE](NOTICE) lists the third-party software it builds on, notably
  [Synthea](https://github.com/synthetichealth/synthea) (Apache-2.0).
