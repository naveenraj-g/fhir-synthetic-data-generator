# 8. Coverage: what is configurable, what is covered, what is not

*Assessed 2026-10-09 against the running system. "Verified" means it was run against real Synthea v4.0.0 in Docker, not
just unit-tested.*

**Short answer.** Nearly every setting the API accepts can be set in the UI (two exceptions: free-form Synthea properties,
of which the UI exposes only US Core, and saving a template), and every kind of data Synthea can produce can be requested,
sliced and delivered in any combination. It is **not** true that "everything" is covered:
Synthea has limits, and a few targeting options are not built. Both are listed here so nobody finds out in production.

## 1. What can be configured, and where

| Choice | Request / UI | Config only |
|---|---|---|
| How many patients, seed, gender, age, state, city, years of history, deceased | yes | |
| Target by disease / operation / **medication**; combine them with **AND / OR**; require **any or all** of several diseases (comorbidity) | yes | |
| Target by a named **specialty** (20 shipped) | yes (pick, or send your own codes) | define a new specialty |
| Find the right codes (3,400 diseases, operations, drugs, labs) | yes (Find codes page, `GET /terms`) | |
| State and city, picked from the 51 states / ~43,000 cities Synthea knows (`GET /connectors/synthea/places`); wrong capitalisation is corrected, an unknown name fails at once with suggestions | yes | |
| Pick any of the 28 resource types Synthea's R4 exporter can write (read from its code, not yet confirmed one by one in real output), one by one or by section (step 3), choose which observations (vitals, labs, surveys, social history...), and 19 one-click quick shapes | yes | |
| See the result as a graph: Patient, visits and every resource they hold, linked by their references; click one for all its data (fields, connections, raw JSON); what each pipeline step kept (job page > View the flow; `GET /generations/{id}/bundles`) | yes | |
| Slice the record: groups, resource types, vitals vs labs, one visit, a date window, a condition's story, administration only | yes (any chain, in any order) | |
| Reference date, end date, US Core profiles | yes (`connector_params`) | |
| Verify references; instant / ZIP / NDJSON delivery | yes | |
| Other Synthea properties, custom Synthea modules, image, memory, timeouts, limits | | yes (security: callers cannot reach paths or JVM flags) |
| Templates (85) and specialties | pick and edit in the form | add / change in `synthetic_data_connectors.yaml` |

The UI cannot **save the form as a new template**, and exposes only one of the free-form Synthea properties (US Core); the
API accepts more (`exporter.fhir.*`, `generate.*`).

## 2. Specialties (all verified against real Synthea, 1 patient, 13-60 s)

| Specialty | A patient matches if they have... |
|---|---|
| Cardiology | heart attack, atrial fibrillation or heart failure |
| Pulmonology | asthma, COPD, emphysema, sleep apnea, or had lung surgery / bronchoscopy |
| Neurology | epilepsy, stroke, Alzheimer's, migraine, brain injury, or an EEG |
| Mental health | depression, PTSD, anxiety, ADHD, alcohol or drug dependence, or CBT |
| Endocrinology | diabetes, prediabetes, hypothyroidism, obesity |
| Nephrology | chronic kidney disease, kidney failure, or dialysis |
| Oncology | breast, colon or lung cancer, or chemotherapy / radiation |
| Dermatology | atopic or contact dermatitis |
| ENT | ear infection, sinusitis, hay fever, sore throat, or sinus endoscopy |
| Infectious disease | urinary tract infection (incl. recurrent), HIV |
| Ophthalmology | diabetic retinopathy / macular edema, retinal exam or laser |
| Rheumatology | rheumatoid arthritis, lupus, gout, fibromyalgia |
| Women's health (OB/GYN) | pregnancy, high-risk pregnancy, miscarriage, caesarean (women 16-45) |
| Hematology | anemia, leukemia, or a transfusion |
| Pediatrics / Geriatrics | any condition, age 0-17 / 65+ |
| Gastroenterology, Orthopedics, Diabetes, Cardiac surgery | see doc 03 |

85 templates: one full-record template per specialty, plus journeys (a condition's story) and operation stays.

## 3. Known limits (honest list)

**Synthea's own limits**
* It only knows the ~87 disease modules it ships. Anything outside them (most of dentistry, many rare diseases, sports
  medicine, transplant follow-up...) cannot be generated, whatever the request says.
* *Active* conditions only. A condition that resolves (heart attack, stroke, anemia, pregnancy, a fracture once healed) is
  invisible to condition targeting once it has ended, so those cannot be targeted by condition. Target a **procedure** the
  episode always contains instead (that is how "Prenatal care" and "Caesarean section" work).
* Rare things are slow or impossible on demand: colon cancer (16+ min, template removed), lupus, stroke, hypothyroidism,
  heart attack (each >5 min, templates removed). The UI warns in the template text; `UNSATISFIABLE_COHORT` is returned
  instead of a short result.
* **Stalls.** Synthea occasionally hangs on one seed (seen with pulmonology, seed 11). The connector times out
  (900 s default), retries once with a derived seed, and records `seed_used` and `retried_after_timeout` in the job.
* Gender matters for speed: a women-only condition without `gender: F` wastes half of Synthea's attempts (breast cancer went
  from >5 min to 24 s).
* Medication targeting means "**currently taking at the end of the period**" and matches one formulation code
  (e.g. "metformin 24h ER 500 mg"), not the drug in general.
* Palliative/hospice patients are deceased and excluded by default (`only_alive: false` includes them; hospice targeting
  was not tested). Dental codes (CDT) were not tested with keep modules.

**Not built**
* Targeting by lab value ("HbA1c > 8"), race/ethnicity, insurer/payer, county, or a named provider. The request model does
  not expose these. (Synthea's module language has conditions for some of them; that was neither built nor verified.)
* Output formats other than FHIR R4 JSON (zip/NDJSON). No CSV, C-CDA, STU3/DSTU2, or Bulk-Data manifest.
* Saving a form as a template from the UI; editing specialties from the UI.
* Cancelling a running job (it finishes or times out). Jobs run in-process on one machine (2 at a time): a restart marks
  in-flight jobs failed. No queue, no multi-node.
* Authentication: none enabled. Put it behind your network or an auth proxy before exposing it.
* Scale: tested with up to ~20 patients per job (records are 0.4-9 MB each). The 5,000-patient limit exists in config but
  was never load-tested.
* The UI's mobile layout is built responsively but was not checked on a phone-sized screen; accessibility was not audited.

## 3b. Delivery pitfall found in use (fixed)

The first UI "Show it here" option used the `inline` sink, which holds the browser's request open while Synthea runs. Next's
proxy drops a request after 30 s ("socket hang up"), which cancelled the run and lost the result. Now: the UI delivers as
`json` (background job, stored 72 h, viewable and downloadable), a cancelled request marks its job `failed:
REQUEST_CANCELLED` instead of leaving it `running`, and the proxy timeout is 10 min. `inline` remains for API callers.

## 4. Deployment

* Development: run the API on the host; Synthea runs in its own Docker image (`just synthea-build`).
* Deployed: `backend/Dockerfile` bundles Java and the pinned Synthea jar and sets `SYNTHEA_MODE=local`, so the container
  needs no Docker socket. **Verified:** built (1.1 GB), started, ran its migration, reported "java ok", and generated a real
  patient to a ZIP.
