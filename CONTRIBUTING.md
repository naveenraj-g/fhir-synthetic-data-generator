# Contributing

Thanks for helping. Bug reports, ideas and pull requests are all welcome.

## Set up

You need [uv](https://docs.astral.sh/uv/) (Python 3.12+), Node 24 with pnpm (`npm i -g pnpm@12.4.2`) and, to run real
Synthea, Docker (or a JDK 17+ with the Synthea jar: see `backend/README.md`).

```bash
# API
cd backend
uv sync
uv run alembic upgrade head
just synthea-build        # once: the Synthea Docker image (or set SYNTHEA_MODE=local)
just dev                  # http://localhost:8000/docs

# UI (another terminal)
cd frontend
pnpm install
pnpm dev                  # http://localhost:3000
```

No Docker or Java? The **Demo fixture patient** template (the `static_fixtures` connector) works without Synthea.

## Before you open a pull request

```bash
cd backend  && uv run pytest tests -q            # fast tests, no Synthea needed
cd frontend && pnpm lint && pnpm typecheck
```

* The slow end-to-end tests run real Synthea: `just test-e2e` (needs the Synthea image).
* If you change an API route or schema, regenerate the typed client: `cd frontend && pnpm gen:api` and commit
  `src/lib/api/schema.ts`.
* Add a test with a behaviour change. The backend has unit tests for slicers, the connector and sinks, and integration
  tests for the API; follow the nearest existing one.
* Keep changes focused. Say what changed and why in the pull request.

## Where things are

| | |
|---|---|
| `backend/app/generator/` | The framework-free library: connectors, slicers, sinks. Start here for new data sources or slicers |
| `backend/configs/synthetic_data_connectors.yaml` | Templates, specialties, limits |
| `frontend/src/components/builder/` | The generate form; `components/flow/` the graph view |
| `plan/` | Design notes and what is and is not covered (`08-coverage.md`) |

## Adding a template or specialty

Edit `backend/configs/synthetic_data_connectors.yaml`. Check a new targeted template against real Synthea first: rare
conditions can take many minutes to find (see the known limits in `plan/08-coverage.md`).

## Licence

By contributing you agree that your contribution is licensed under the Apache License 2.0 (see `LICENSE`).
