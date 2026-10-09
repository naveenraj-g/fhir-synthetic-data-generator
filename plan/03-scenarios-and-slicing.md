# 3. Scenarios and Slicing

This is the heart of "how do we cover all the combinations". Every request is described
on **three independent axes**; any combination is valid.

```
   COHORT (who)          ×      SHAPE (what slice)        ×     DELIVERY (where)
 ─────────────────            ─────────────────────            ─────────────────
 count, seed                  full_record                      inline response
 gender, age range            resource_types [..]              zip / ndjson / files
 state / city                 encounter (+closure)             FHIR server POST
 specialty / conditions       date_window                      (later: S3, Kafka…)
 modules (keep/include)       condition_scoped
 years_of_history             sampled / limited
```

## Axis 1 — Cohort (who gets generated)

Handled by the **connector** natively where it can; otherwise the planner warns (and a slicer can enforce it).

| Field | Meaning | Synthea mapping |
|---|---|---|
| `count` | number of patients | `-p` |
| `seed` | reproducibility | `-s` (+ `-cs` clinician seed, `-r` reference date) |
| `gender` | M / F / any | `-g` |
| `age_range` | e.g. `[30, 65]` | `-a 30-65` |
| `state`, `city` | geography | positional args |
| `specialty` | named set of condition and/or procedure codes (see below) | expanded to `conditions` / `procedures` / `match` |
| `conditions` | must have ANY of these (SNOMED codes) | `-k` keep module (generated) |
| `years_of_history` | how much history | `exporter.years_of_history` |
| `only_alive` | exclude deceased | `generate.only_alive_patients` |

### Specialty / "best treatment" data

Synthea has no "specialty" switch, but it is **module-driven**: each disease/care pathway
is a module (e.g. diabetes, cardiovascular disease, asthma, breast-cancer, …), and
modules encode guideline-style treatment pathways (screening → diagnosis → medication →
procedures → follow-up).

Implemented (see doc 05). A specialty is **diseases and/or operations**:
1. In config, a **specialty** is a named set of condition and procedure codes; `match: any` means "has the
   disease OR had one of the operations" (default `all` = both):
   ```yaml
   specialties:
     cardiology:
       conditions: ["22298006", "49436004", "88805009"]   # MI, atrial fibrillation, heart failure
   ```
2. The runtime expands `cohort.specialty` into `cohort.conditions` (explicit conditions are added to it).
3. The Synthea connector turns `conditions` into a **keep module** (`-k`): Synthea itself discards patients
   without ANY of the conditions and keeps generating until `count` match. Filtering is native and exact,
   so there is no over-generation; a connector that cannot filter natively gets a warning instead.
4. If Synthea cannot find enough matches (rare condition / narrow age range) the job fails with
   `UNSATISFIABLE_COHORT` rather than returning a short result.
5. A `condition_filter` slicer remains useful as a verification step / for non-Synthea connectors (Phase 3).

"Best treatment" = whatever pathway the Synthea module encodes. We document that these
are *simulated* guideline-like pathways, not clinical advice. Custom modules (a team's own
pathway) can be dropped into a `modules_dir` and referenced by name.

## Axis 2 — Shape (what slice of the record)

Synthea emits one **transaction Bundle per patient** (all their resources, with
`urn:uuid:` references), plus shared `hospitalInformation*` and `practitionerInformation*`
Bundles. Slicers operate on these.

| Slicer | Params | Output |
|---|---|---|
| `full_record` | `include_infrastructure` | Per-patient Bundle as emitted; optionally self-contained (practitioners/organizations/locations attached) |
| `resource_types` | `types`, `groups`, `exclude_types`, `keep_patient` | Only those types and/or named groups (`demographics`, `clinical`, `financial`, `administrative`, ...; see `GET /resource-groups`). Administrative types are pulled from the infrastructure bundles automatically |
| `resource_filter` | `resource_type`, `categories`, `codes`, `status`, `exclude` | Fine filter on one type: vitals vs labs, one code, only final results... |
| `infrastructure` | `types` | **Administrative data only**: providers/organizations/locations, no patients |
| `encounter` | `selector` (first/latest/random/all), `per_patient`, `encounter_class`, `with_procedure`, `with_condition`, `related_conditions`, `include_infrastructure`, `random_seed` | **One bundle per selected encounter**: the encounter + everything belonging to it |
| `date_window` | `from_date`, `to_date` **or** `last_n_days` | Encounters starting in the window + their members; shared resources by their own date |
| `condition_scoped` | `conditions`, `include_infrastructure` | One bundle per patient: every encounter the condition touches (+ members) |
| `condition_filter` | `conditions`, `active_only` | Whole patients that have the condition (verification / non-native connectors) |
| `limit` | `max_bundles`, `max_resources_per_bundle` | Truncation for tiny fixtures |
| `redact_infra` | `drop_types` | Drops Claim / ClaimResponse / ExplanationOfBenefit by default |

Every slicer that drops resources also removes the references pointing at them (`filter_entries`), so chained shapes stay
consistent. (Found in Phase 4: `vitals-only` used to leave `Observation.encounter` dangling.)

Slicers are **composable**: `shape: [date_window, redact_infra]` applies in order. `GET /slicers` returns each one's
JSON schema.

### "One operation / one encounter" - how it works (implemented)

Observed in real Synthea output (not assumed): clinical resources point at their Encounter through `encounter`,
`context.encounter[]` (DocumentReference) or `item[].encounter[]` (Claim, ExplanationOfBenefit); Patient, Device and
SupplyDelivery point at no encounter; and **one patient-wide `Provenance` points at every encounter**.

`slicers/reference_closure.py::extract` therefore uses these rules:

1. **Belongs to the episode** = every encounter the resource references is in the chosen set. A resource that
   references several encounters (the Provenance) only belongs to a set containing all of them, so it never leaks
   into a single-visit extract.
2. **Shared resources** (no encounter link): the Patient is always kept; others only when an included resource
   references them (e.g. `Procedure.focalDevice` → Device), followed transitively.
3. **Related conditions** (`related_conditions`, default on): a Condition referenced by an included resource - typically
   `MedicationRequest.reasonReference` - is pulled in even when it was recorded at another visit. One hop, no recursion.
4. **No dangling references**: any local reference left pointing at something that was cut is removed (empty containers
   too). Synthea's conditional references (`Practitioner?identifier=...`) and http URLs were never local, so they are
   left alone and resolved by `attach_infrastructure` from the hospital/practitioner bundles.
5. Inputs are never mutated; the result is a new transaction Bundle in the original entry order.

Selectors: `with_procedure` / `with_condition` take a numeric code (optionally `SNOMED-CT:` prefixed) **or** free text
matched case-insensitively against display/text (`"appendectomy"`). `encounter_class` is `AMB` / `IMP` / `EMER`.
`selector: random` is deterministic per patient and `random_seed`.

"Operation" is interpreted as a clinical episode; an `$everything`-style export is simply `full_record`.

Empty results are errors: if the shape yields no bundles at all (no encounter matched) the job fails with
`UNSATISFIABLE_COHORT` instead of reporting an empty success.

Caveats: `summary.patients` counts Patient resources, so an episode-per-encounter shape (e.g. `er-visits`) reports one
"patient" per bundle even when several bundles come from the same person.

## Axis 3 — Delivery (where it goes)

| Sink | Notes |
|---|---|
| `inline` | JSON in the HTTP response; capped by size |
| `zip` | One file per patient/bundle; downloadable artifact |
| `ndjson` | One resource per line grouped by type — the FHIR Bulk Data layout |
| `files` | Write to a server-side directory |
| `fhir_server` | POST each Bundle (transaction) or resource to a target base URL with auth; retries, concurrency limit, per-bundle result report. Natural target: the user's own FHIR server |

## Preset catalogue (shipped in config)

| Preset | Cohort | Shape | Delivery |
|---|---|---|---|
| `full-patient` | 1 patient | `full_record` | inline |
| `full-patients-100` | 100 | `full_record` | zip |
| `vitals-only` | 50 | `resource_types: [Observation]` (+ category=vital-signs) | ndjson |
| `labs-only` | 50 | `resource_types: [Observation, DiagnosticReport]` | ndjson |
| `single-surgery-episode` | 1, `procedures: [80146002]` | `encounter(with_procedure=80146002)` | inline |
| `cardiology-cohort` | 25, specialty=cardiology | `full_record` + `condition_filter` | zip |
| `diabetes-journey` | 5, specialty=diabetes | `condition_scoped` | zip |
| `er-visits` | 20 | `encounter(encounter_class=[EMER], selector=all)` | zip |
| `recent-history` | 10 | `date_window(last_n_days=730)` | zip |
| `load-test-1k` | 1000 | `full_record` | `fhir_server` |

Users can pass `preset` plus overrides (`{"preset": "full-patient", "cohort": {"count": 3}}`),
or a fully custom spec.

## Cross-cutting concerns

- **Reference integrity check** after every slicer (a test-mode assertion, optional at runtime):
  every `reference` resolves inside the output unless `allow_dangling: true`.
- **US Core**: Synthea can emit US Core-profiled FHIR; expose as a connector option
  (`fhir_profile: us-core`), default plain R4.
- **FHIR version**: R4 as default; Synthea also supports STU3/DSTU2 exporters — expose
  `fhir_version` in connector config but only test R4 in v1.
- **Size guard**: refuse/redirect to async when the estimate exceeds `inline_max_bytes`.
