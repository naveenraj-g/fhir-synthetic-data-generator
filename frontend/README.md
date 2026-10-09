# FHIR Synthetic Data Generator - frontend

Next.js 16 (App Router, Cache Components) + shadcn/ui (Base UI flavour) + Tailwind 4 + TanStack Query.
It is a thin, dynamic UI over the backend API: nothing about slicers, sinks, presets, specialties or
codes is hard-coded here, so adding one on the backend shows up in the UI without a frontend change.

## Run it

```bash
# terminal 1 - the API (see ../backend/README.md)
cd backend && uv run alembic upgrade head && just dev          # http://localhost:8000

# terminal 2 - this app
cd frontend && pnpm install && pnpm dev                        # http://localhost:3000
```

`BACKEND_URL` (default `http://localhost:8000`, see `.env.example`) says where the API lives. The browser never calls
it directly: it calls `/backend/*`, which `next.config.ts` rewrites to the API. One origin means no CORS setup and the
backend address stays out of the client bundle.

Open it as `http://localhost:3000` (or `http://127.0.0.1:3000`; both are allowed in dev).

## Pages

| Route | What it does |
|---|---|
| `/` | **Generate.** Start from a template (grouped: Gastroenterology, Orthopedics, Preventive health, General; or blank), then set *who* (cohort, targeting by specialty / disease / operation), *what data* (a chain of slicers, with one-click quick shapes), *delivery* (instant, ZIP, NDJSON) and advanced options. The request is validated against the real API as you type (`/generations/preview`) and the exact JSON that will be sent is shown. |
| `/jobs` | Every generation with status, duration, result size and when its files expire. Auto-refreshes while anything is running. |
| `/jobs/[id]` | Status, timings, what was asked, how to reproduce it (seed, Synthea version), a per-resource-type breakdown, downloads, and the instant result. **Edit & re-run** loads the job back into the builder. |
| `/explore` | Search every disease, operation, medication and lab the generator can produce, and copy its code or send it to the builder. |

## How it stays dynamic

* Slicer parameter forms are **rendered from each slicer's JSON schema** (`components/builder/schema-form.tsx`).
  Known parameters get purpose-built pickers (resource groups, encounter classes, searchable code pickers); anything
  else falls back to inputs derived from the schema's types.
* Templates, specialties, sinks, connectors and slicers all come from the discovery endpoints (`lib/api/hooks.ts`).
* API types are **generated from the backend's OpenAPI document**: after changing the API run `pnpm gen:api`
  (it exports the spec with `uv`, then runs `openapi-typescript` into `src/lib/api/schema.ts`).

## Layout

```
src/app/                 routes (thin: they render components)
src/components/builder/  the generate page: sections, schema-form, code picker, summary panel
src/components/jobs/     jobs list + job detail
src/components/explore/  code search
src/components/ui/       shadcn components
src/lib/api/             client.ts (fetch + typed errors), hooks.ts (TanStack Query), schema.ts (generated)
src/lib/builder-state.ts form state <-> API request, quick shapes, loading a preset / a past job
```

## Scripts

`pnpm dev` · `pnpm build` · `pnpm typecheck` (generates Next's route types first) · `pnpm lint` · `pnpm gen:api`

## Notes

* **Cache Components** is enabled (see `next.config.ts`), so runtime values must not be read during prerender:
  `usePathname()` sits behind `<Suspense>` (the header nav) and the clock for "3m ago" is `lib/use-now.ts`, which returns
  `null` until hydration. `next build` fails loudly if either rule is broken.
* The form never uses the `inline` sink: it keeps the HTTP request open for the whole run (the Next proxy drops it after its
  timeout, and the result is lost). "View here + download" is the `json` sink: a background job whose result is a stored
  file, loaded into the viewer on the job page (up to 15 MB; larger is download-only) and kept 72 hours.
  `lib/inline-store.ts` only holds results of API-style inline runs.
* The API has routes with trailing slashes (`POST /generations/`); `next.config.ts` keeps them intact through the proxy
  (`skipTrailingSlashRedirect` + an explicit rewrite). Without that the browser sees a cross-origin redirect and the
  request fails with "Failed to fetch".

## The flow view (`/jobs/<id>/flow`)

"View the flow" on a finished job draws the stored result as a graph: the Patient, each visit and every resource in it,
joined by the references inside the resources. Click a resource for a side panel with all its fields, its connections
(both directions, clickable) and the raw JSON. Above the graph, a strip shows request -> Synthea -> each step ->
delivery with what each stage kept.

* Data comes from `GET /generations/{id}/bundles` (an index) and `/bundles/{n}` (one whole bundle), which read the stored
  JSON, ZIP or NDJSON. Files expire after 72 h, so the view does too.
* `lib/fhir-graph.ts` builds the graph (no UI imports, so it can be tried on its own); `components/flow/*` draws it
  with React Flow and lays it out with dagre.
* Providers (Practitioner, Organization, Location) and Provenance are hidden at first because nearly everything points
  at them; the chips above the graph toggle any type. Many same-type resources in one visit fold into one node (open one
  in the panel and use "Draw these in the graph").
* **Big records.** Layout is the part that does not scale: dagre (used up to 350 nodes) took ~9 s at 2,000 nodes and
  minutes at 5,000, which froze the tab. Beyond 350 nodes `lib/fhir-layout.ts` uses a linear-time timeline layout (a
  column per step away from the Patient, a row band per visit), 17 ms for 10,000 resources. Records over 3,000
  resources also fold every type into one node per visit, and a folded group lists at most 300 members. The API reads
  at most 64 MB of JSON (128 MB unpacked for a ZIP) for the flow view; beyond that the download still works.
