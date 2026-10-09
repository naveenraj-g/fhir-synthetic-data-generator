import type { GenerationRequest, PresetInfo, ResolvedSpec, SpecialtyDef } from "@/lib/api/client";

/**
 * The form's state. It mirrors the API's GenerationRequest but uses strings for number inputs (so a half-typed
 * "4" or an empty box is representable) and carries an `id` per shape step (stable React keys while reordering).
 */
export type StepParams = Record<string, unknown>;
export interface ShapeStepState {
  id: string;
  slicer: string;
  params: StepParams;
}

export interface BuilderState {
  /** Template this form was started from; informational only, the full spec is always sent. */
  preset: string | null;
  connector: string;
  count: string;
  seed: string;
  gender: "any" | "M" | "F";
  ageMin: string;
  ageMax: string;
  state: string;
  city: string;
  yearsOfHistory: string;
  onlyAlive: "default" | "yes" | "no";
  specialty: string;
  conditions: string[];
  procedures: string[];
  /** RxNorm codes of medications the patient is currently taking. */
  medications: string[];
  match: "default" | "all" | "any";
  /** How several diseases (or several operations) combine: at least one, or every one. */
  within: "any" | "all";
  shape: ShapeStepState[];
  sink: string;
  referenceDate: string; // yyyy-mm-dd
  endDate: string; // yyyy-mm-dd
  usCore: boolean;
  checkReferences: boolean;
}

let nextId = 0;
export const newStepId = () => `step-${++nextId}`;

/** `inline` keeps the HTTP request open for the whole run (and loses the result if it drops); the form uses `json` instead. */
const uiSink = (name: string) => (name === "inline" ? "json" : name);

export const INITIAL_STATE: BuilderState = {
  preset: null,
  connector: "",
  count: "5",
  seed: "",
  gender: "any",
  ageMin: "",
  ageMax: "",
  state: "",
  city: "",
  yearsOfHistory: "",
  onlyAlive: "default",
  specialty: "",
  conditions: [],
  procedures: [],
  medications: [],
  match: "default",
  within: "any",
  shape: [],
  sink: "zip",
  referenceDate: "",
  endDate: "",
  usCore: false,
  checkReferences: false,
};

const toInt = (s: string): number | undefined => {
  if (s.trim() === "") return undefined;
  const n = Number(s);
  return Number.isInteger(n) ? n : undefined;
};
const yyyymmdd = (iso: string) => iso.replaceAll("-", "");
const isoFromCompact = (s: string) => (s.length === 8 ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6)}` : "");

/** Drop empty params so the request stays minimal and the server's defaults apply. */
const cleanParams = (p: StepParams): StepParams =>
  Object.fromEntries(
    Object.entries(p).filter(([, v]) => v !== undefined && v !== "" && !(Array.isArray(v) && v.length === 0)),
  );

/** Form state -> API request. Returns only what the user actually set. */
export function toRequest(s: BuilderState): GenerationRequest {
  const cohort: NonNullable<GenerationRequest["cohort"]> = {};
  const count = toInt(s.count);
  if (count !== undefined) cohort.count = count;
  const seed = toInt(s.seed);
  if (seed !== undefined) cohort.seed = seed;
  if (s.gender !== "any") cohort.gender = s.gender;
  const lo = toInt(s.ageMin);
  const hi = toInt(s.ageMax);
  if (lo !== undefined || hi !== undefined) cohort.age_range = [lo ?? 0, hi ?? 140];
  if (s.state.trim()) cohort.state = s.state.trim();
  if (s.city.trim()) cohort.city = s.city.trim();
  const years = toInt(s.yearsOfHistory);
  if (years !== undefined) cohort.years_of_history = years;
  if (s.onlyAlive !== "default") cohort.only_alive = s.onlyAlive === "yes";
  if (s.specialty) cohort.specialty = s.specialty;
  if (s.conditions.length) cohort.conditions = s.conditions;
  if (s.procedures.length) cohort.procedures = s.procedures;
  if (s.medications.length) cohort.medications = s.medications;
  if (s.match !== "default") cohort.match = s.match;
  if (s.within === "all") cohort.within = "all";

  const request: GenerationRequest = { cohort, sink: { name: s.sink } };
  if (s.connector) request.connector = s.connector;
  if (s.shape.length) {
    request.shape = s.shape.map((st) => ({ slicer: st.slicer, params: cleanParams(st.params) }));
  }
  const properties: Record<string, unknown> = {};
  if (s.usCore) properties["exporter.fhir.use_us_core_ig"] = true;
  const connectorParams: Record<string, unknown> = {};
  if (s.referenceDate) connectorParams.reference_date = yyyymmdd(s.referenceDate);
  if (s.endDate) connectorParams.end_date = yyyymmdd(s.endDate);
  if (Object.keys(properties).length) connectorParams.properties = properties;
  if (Object.keys(connectorParams).length) request.connector_params = connectorParams;
  if (s.checkReferences) request.options = { check_references: true };
  return request;
}

type CohortLike = Record<string, unknown>;

function cohortFields(c: CohortLike): Partial<BuilderState> {
  const age = c.age_range as [number, number] | undefined;
  return {
    count: c.count != null ? String(c.count) : INITIAL_STATE.count,
    seed: c.seed != null ? String(c.seed) : "",
    gender: (c.gender as "M" | "F" | undefined) ?? "any",
    ageMin: age ? String(age[0]) : "",
    ageMax: age ? String(age[1]) : "",
    state: (c.state as string) ?? "",
    city: (c.city as string) ?? "",
    yearsOfHistory: c.years_of_history != null ? String(c.years_of_history) : "",
    onlyAlive: c.only_alive == null ? "default" : c.only_alive ? "yes" : "no",
    specialty: (c.specialty as string) ?? "",
    conditions: (c.conditions as string[]) ?? [],
    procedures: (c.procedures as string[]) ?? [],
    medications: (c.medications as string[]) ?? [],
    match: (c.match as "all" | "any" | undefined) ?? "default",
    within: (c.within as "any" | "all" | undefined) ?? "any",
  };
}

const stepsFrom = (shape: { slicer: string; params?: Record<string, unknown> }[] | null | undefined) =>
  (shape ?? []).map((st) => ({ id: newStepId(), slicer: st.slicer, params: { ...(st.params ?? {}) } }));

/** A preset becomes an editable starting point (the user sees and can change everything it implies). */
export function fromPreset(preset: PresetInfo): BuilderState {
  return {
    ...INITIAL_STATE,
    ...cohortFields(preset.cohort ?? {}),
    preset: preset.name,
    connector: preset.connector ?? "",
    shape: stepsFrom(preset.shape as never),
    sink: uiSink((preset.sink as { name?: string } | null | undefined)?.name ?? INITIAL_STATE.sink),
  };
}

/**
 * Rebuild the form from what actually ran (a job's resolved spec), so "Edit & re-run" starts from exactly that.
 * A specialty's own codes are not copied into the conditions/procedures lists: the specialty re-expands them.
 */
export function fromResolved(spec: ResolvedSpec, specialties: Record<string, SpecialtyDef> = {}): BuilderState {
  const cohort = { ...(spec.cohort as CohortLike) };
  const sp = typeof cohort.specialty === "string" ? specialties[cohort.specialty] : undefined;
  if (sp) {
    cohort.conditions = ((cohort.conditions as string[]) ?? []).filter((c) => !(sp.conditions ?? []).includes(c));
    cohort.procedures = ((cohort.procedures as string[]) ?? []).filter((c) => !(sp.procedures ?? []).includes(c));
    cohort.medications = ((cohort.medications as string[]) ?? []).filter((c) => !(sp.medications ?? []).includes(c));
    // These come from the specialty itself; re-sending them as explicit overrides would pin them.
    if (sp.match && cohort.match === sp.match) delete cohort.match;
    if (sp.age_range && JSON.stringify(cohort.age_range) === JSON.stringify(sp.age_range)) delete cohort.age_range;
  }
  const cp = (spec.connector_params ?? {}) as { reference_date?: string; end_date?: string; properties?: Record<string, unknown> };
  return {
    ...INITIAL_STATE,
    ...cohortFields(cohort),
    preset: spec.preset ?? null,
    connector: spec.connector,
    shape: stepsFrom(spec.shape as never),
    sink: uiSink(spec.sink.name),
    referenceDate: cp.reference_date ? isoFromCompact(cp.reference_date) : "",
    endDate: cp.end_date ? isoFromCompact(cp.end_date) : "",
    usCore: cp.properties?.["exporter.fhir.use_us_core_ig"] === true,
    checkReferences: spec.options?.check_references === true,
  };
}

/**
 * One-click shapes for the common asks. Each is just a slicer chain, so after clicking one the user can
 * still see and edit the steps below it.
 */
export interface QuickShape {
  id: string;
  label: string;
  hint: string;
  steps: { slicer: string; params?: StepParams }[];
}

export const QUICK_SHAPES: QuickShape[] = [
  { id: "full", label: "Everything", hint: "The whole record of each patient", steps: [{ slicer: "full_record", params: { include_infrastructure: true } }] },
  { id: "demographics", label: "Patients only", hint: "Who they are, no clinical history", steps: [{ slicer: "resource_types", params: { groups: ["demographics"] } }] },
  { id: "clinical", label: "Clinical only", hint: "Encounters, conditions, medications, results... no billing", steps: [{ slicer: "resource_types", params: { groups: ["clinical"] } }] },
  { id: "financial", label: "Billing only", hint: "Claims and insurance payments", steps: [{ slicer: "resource_types", params: { groups: ["financial"] } }] },
  { id: "encounters", label: "Visits", hint: "The encounters (visits) and the patient", steps: [{ slicer: "resource_types", params: { groups: ["encounters"] } }] },
  { id: "conditions", label: "Diagnoses & allergies", hint: "Conditions and allergies", steps: [{ slicer: "resource_types", params: { groups: ["conditions"] } }] },
  { id: "procedures", label: "Procedures", hint: "Operations and other procedures", steps: [{ slicer: "resource_types", params: { groups: ["procedures"] } }] },
  { id: "medications", label: "Medications", hint: "Prescriptions and doses given", steps: [{ slicer: "resource_types", params: { groups: ["medications"] } }] },
  { id: "immunizations", label: "Vaccines", hint: "Immunizations", steps: [{ slicer: "resource_types", params: { groups: ["immunizations"] } }] },
  { id: "results", label: "Results & reports", hint: "Observations, diagnostic reports and imaging", steps: [{ slicer: "resource_types", params: { groups: ["diagnostics"] } }] },
  { id: "orders", label: "Orders", hint: "Service requests: ordered tests, imaging, referrals", steps: [{ slicer: "resource_types", params: { groups: ["orders"] } }] },
  { id: "careplans", label: "Care plans", hint: "Care plans, care teams and goals", steps: [{ slicer: "resource_types", params: { groups: ["care_plans"] } }] },
  { id: "social", label: "Social history", hint: "Smoking, alcohol, education, employment and similar survey answers", steps: [{ slicer: "resource_types", params: { types: ["Observation"] } }, { slicer: "resource_filter", params: { resource_type: "Observation", categories: ["social-history", "survey"] } }] },
  { id: "notes", label: "Clinical notes", hint: "Document references (notes)", steps: [{ slicer: "resource_types", params: { types: ["DocumentReference"] } }] },
  { id: "admin", label: "Administration only", hint: "Providers, organizations, locations - no patients", steps: [{ slicer: "infrastructure" }] },
  { id: "vitals", label: "Vital signs", hint: "Blood pressure, heart rate, weight...", steps: [{ slicer: "resource_types", params: { types: ["Observation"] } }, { slicer: "resource_filter", params: { resource_type: "Observation", categories: ["vital-signs"] } }] },
  { id: "labs", label: "Lab results", hint: "Laboratory observations", steps: [{ slicer: "resource_types", params: { types: ["Observation", "DiagnosticReport"] } }, { slicer: "resource_filter", params: { resource_type: "Observation", categories: ["laboratory"] } }] },
  { id: "5y", label: "Past 5 years", hint: "Only the most recent five years of each record", steps: [{ slicer: "date_window", params: { last_n_years: 5 } }] },
  { id: "er", label: "ER visits", hint: "One bundle per emergency visit", steps: [{ slicer: "encounter", params: { encounter_class: ["EMER"], selector: "all" } }] },
];

/** The quick shape whose steps exactly match `steps`, if any (used to name things in plain words). */
export function matchQuickShape(steps: { slicer: string; params?: unknown }[]): QuickShape | undefined {
  return QUICK_SHAPES.find(
    (q) =>
      q.steps.length === steps.length &&
      q.steps.every((st, i) => st.slicer === steps[i].slicer && JSON.stringify(st.params ?? {}) === JSON.stringify(steps[i].params ?? {})),
  );
}

export const stepsFromQuick = (q: QuickShape): ShapeStepState[] =>
  q.steps.map((st) => ({ id: newStepId(), slicer: st.slicer, params: { ...(st.params ?? {}) } }));

/** Resource-type names used for pickers (the union of all groups the API reports is passed in by callers). */
export const ENCOUNTER_CLASSES = [
  { value: "AMB", label: "Outpatient (AMB)" },
  { value: "IMP", label: "Inpatient (IMP)" },
  { value: "EMER", label: "Emergency (EMER)" },
];
export const OBSERVATION_CATEGORIES = [
  "vital-signs",
  "laboratory",
  "survey",
  "social-history",
  "exam",
  "imaging",
  "procedure",
  "therapy",
  "activity",
];
