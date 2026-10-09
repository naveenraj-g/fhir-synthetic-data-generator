/**
 * Turns a FHIR Bundle into a graph: every resource is a node, every `reference` inside a resource is a link.
 * Pure TypeScript with no UI imports, so it can be tested on its own.
 *
 * Vocabulary: a link goes FROM the resource that holds the reference TO the resource it points at (an Observation
 * points at its Encounter). The flow reads the other way (Patient -> Encounter -> Observation), so the UI lays the
 * "referent" on the left and marks which end the arrow points at.
 */

export type Resource = { resourceType: string; id?: string } & Record<string, unknown>;
type Json = Record<string, unknown>;

export interface Link {
  from: string; // id of the resource that holds the reference
  to: string; // id of the resource it points at
  field: string; // where it sits, e.g. "encounter", "participant.individual"
}
export interface Unresolved {
  field: string;
  reference: string;
}
export interface ParsedBundle {
  resources: Map<string, Resource>; // by node id ("Condition/abc")
  order: string[]; // bundle order
  links: Link[];
  unresolved: Map<string, Unresolved[]>; // references that point outside the bundle
  patientId: string | undefined;
  /** The node id a reference string points at, if it points inside this bundle. */
  resolve: (reference: string) => string | undefined;
}

export interface FlowNode {
  id: string; // a resource id, or "group:<context>:<type>" for a collapsed group
  type: string;
  title: string;
  subtitle: string;
  date: string; // YYYY-MM-DD or ""
  members?: string[]; // group nodes: the resources they stand for
}
export interface FlowEdge {
  id: string;
  from: string; // referrer
  to: string; // referent
  fields: string[];
  implied: boolean; // not a real reference: keeps the graph connected to the Patient
}
export interface GraphOptions {
  collapse: boolean; // fold many same-type siblings of one visit into one node
  hiddenTypes: ReadonlySet<string>;
  patientLinks: boolean; // draw every resource's link to the Patient (a hairball), not just the visits'
  expanded: ReadonlySet<string>; // group keys the user opened up: their members are drawn one by one
  groupMin?: number; // fold a type with more than this many in one visit (default GROUP_MIN)
}

/** Providers and places are referenced by almost everything, so they are hidden until asked for. */
export const PROVIDER_TYPES = ["Practitioner", "PractitionerRole", "Organization", "Location"] as const;
export const DEFAULT_HIDDEN_TYPES = ["Provenance", ...PROVIDER_TYPES] as const;

/** More than this many same-type resources in one visit fold into a group node when collapsing. */
export const GROUP_MIN = 4;
const NEVER_GROUP = new Set(["Patient", "Encounter"]);

const isObject = (v: unknown): v is Json => typeof v === "object" && v !== null && !Array.isArray(v);
const asArray = (v: unknown): unknown[] => (Array.isArray(v) ? v : v === undefined || v === null ? [] : [v]);
const str = (v: unknown): string => (typeof v === "string" ? v : typeof v === "number" ? String(v) : "");

// ── parsing ────────────────────────────────────────────────────────────────

const REFERENCE_FORM = /(?:^|\/)([A-Z][A-Za-z]+)\/([A-Za-z0-9\-.]{1,64})(?:\/_history\/[^/]+)?$/;
const CONDITIONAL_FORM = /^([A-Z][A-Za-z]+)\?identifier=(.+)$/;

export function parseBundle(bundle: { entry?: { fullUrl?: string; resource?: Resource }[] }): ParsedBundle {
  const resources = new Map<string, Resource>();
  const order: string[] = [];
  const byFullUrl = new Map<string, string>();
  const byIdentifier = new Map<string, string>(); // "Type|system|value" -> node id

  (bundle.entry ?? []).forEach((entry, i) => {
    const res = entry.resource;
    if (!res || typeof res.resourceType !== "string") return;
    const id = res.id ? `${res.resourceType}/${res.id}` : `${res.resourceType}#${i}`;
    if (resources.has(id)) return;
    resources.set(id, res);
    order.push(id);
    if (entry.fullUrl) byFullUrl.set(entry.fullUrl, id);
    for (const ident of asArray(res.identifier)) {
      if (isObject(ident) && ident.system && ident.value) byIdentifier.set(`${res.resourceType}|${str(ident.system)}|${str(ident.value)}`, id);
    }
  });

  const resolve = (ref: string): string | undefined => {
    if (ref.startsWith("urn:")) return byFullUrl.get(ref);
    const conditional = CONDITIONAL_FORM.exec(ref);
    if (conditional) {
      const [system, ...value] = decodeURIComponent(conditional[2]).split("|");
      return byIdentifier.get(`${conditional[1]}|${system}|${value.join("|")}`);
    }
    const direct = REFERENCE_FORM.exec(ref);
    if (direct) {
      const key = `${direct[1]}/${direct[2]}`;
      return resources.has(key) ? key : byFullUrl.get(ref);
    }
    return byFullUrl.get(ref);
  };

  const links: Link[] = [];
  const unresolved = new Map<string, Unresolved[]>();
  const seen = new Set<string>();

  for (const [from, res] of resources) {
    const walk = (node: unknown, path: string[]) => {
      if (Array.isArray(node)) return node.forEach((n) => walk(n, path));
      if (!isObject(node)) return;
      for (const [key, value] of Object.entries(node)) {
        if (key === "reference" && typeof value === "string") {
          if (value.startsWith("#")) continue; // points at a resource contained inside this one
          const field = path.join(".") || "reference";
          const to = resolve(value);
          if (to === undefined) {
            unresolved.set(from, [...(unresolved.get(from) ?? []), { field, reference: value }]);
          } else if (to !== from && !seen.has(`${from}|${to}|${field}`)) {
            seen.add(`${from}|${to}|${field}`);
            links.push({ from, to, field });
          }
        } else if (key !== "contained") {
          walk(value, [...path, key]);
        }
      }
    };
    walk(res, []);
  }

  const patientId = order.find((id) => resources.get(id)?.resourceType === "Patient");
  return { resources, order, links, unresolved, patientId, resolve };
}

// ── describing a resource in a line or two ──────────────────────────────────

/** SNOMED names end in a semantic tag, "Appendectomy (procedure)": noise on a card. */
const SEMANTIC_TAG = /\s*\((?:procedure|finding|disorder|situation|regime\/therapy|environment|observable entity|morphologic abnormality|qualifier value|person|product|substance|event|social concept|body structure|physical object|record artifact|attribute|occupation|medicinal product|clinical drug)\)\s*$/;
const conceptText = (cc: unknown): string => {
  if (!isObject(cc)) return "";
  const coding = asArray(cc.coding).find(isObject);
  return (str(cc.text) || (coding ? str(coding.display) || str(coding.code) : "")).replace(SEMANTIC_TAG, "");
};
const firstConcept = (v: unknown): string => asArray(v).map(conceptText).find(Boolean) ?? "";
const humanName = (v: unknown): string => {
  if (typeof v === "string") return v;
  const n = asArray(v).find(isObject);
  if (!n) return "";
  const parts = [...asArray(n.prefix), ...asArray(n.given), n.family].map(str).filter(Boolean);
  return parts.join(" ") || str(n.text);
};
const quantity = (q: unknown): string => {
  if (!isObject(q) || q.value === undefined) return "";
  const v = typeof q.value === "number" ? Math.round(q.value * 100) / 100 : q.value;
  return `${v}${q.unit ? ` ${str(q.unit)}` : ""}`;
};

const DATE_FIELDS: Record<string, string[][]> = {
  Encounter: [["period", "start"]],
  Observation: [["effectiveDateTime"], ["effectivePeriod", "start"], ["issued"]],
  Condition: [["onsetDateTime"], ["recordedDate"]],
  Procedure: [["performedDateTime"], ["performedPeriod", "start"]],
  MedicationRequest: [["authoredOn"]],
  MedicationAdministration: [["effectiveDateTime"], ["effectivePeriod", "start"]],
  DiagnosticReport: [["effectiveDateTime"], ["issued"]],
  Immunization: [["occurrenceDateTime"]],
  CarePlan: [["period", "start"]],
  CareTeam: [["period", "start"]],
  Goal: [["startDate"]],
  DocumentReference: [["date"]],
  Claim: [["created"], ["billablePeriod", "start"]],
  ExplanationOfBenefit: [["created"], ["billablePeriod", "start"]],
  ImagingStudy: [["started"]],
  AllergyIntolerance: [["onsetDateTime"], ["recordedDate"]],
  SupplyDelivery: [["occurrenceDateTime"]],
  ServiceRequest: [["authoredOn"], ["occurrenceDateTime"]],
  Media: [["createdDateTime"], ["issued"]],
  Provenance: [["recorded"]],
  Coverage: [["period", "start"]],
  Device: [],
  Patient: [["birthDate"]],
};

const dig = (res: Json, path: string[]): string => {
  let node: unknown = res;
  for (const key of path) node = isObject(node) ? node[key] : undefined;
  return str(node);
};
export const dateOf = (res: Resource): string => {
  for (const path of DATE_FIELDS[res.resourceType] ?? []) {
    const d = dig(res, path);
    if (d) return d.slice(0, 10);
  }
  return "";
};

/** A short title and subtitle for the node card; a readable line, never the raw data (that is in the panel). */
export function describe(res: Resource): { title: string; subtitle: string } {
  const date = dateOf(res);
  const join = (...parts: string[]) => parts.filter(Boolean).join(" · ");
  switch (res.resourceType) {
    case "Patient":
      return { title: humanName(res.name) || "Patient", subtitle: join(str(res.gender), res.birthDate ? `born ${str(res.birthDate)}` : "") };
    case "Encounter": {
      const cls = isObject(res.class) ? str(res.class.code) : "";
      return { title: firstConcept(res.type) || firstConcept(res.serviceType) || "Encounter", subtitle: join(date, cls) };
    }
    case "Observation": {
      const components = asArray(res.component).filter(isObject);
      const value =
        quantity(res.valueQuantity) ||
        conceptText(res.valueCodeableConcept) ||
        str(res.valueString) ||
        (components.length ? components.map((c) => quantity(c.valueQuantity)).filter(Boolean).join(" / ") : "");
      return { title: conceptText(res.code) || "Observation", subtitle: join(value, date) };
    }
    case "Claim":
    case "ExplanationOfBenefit": {
      const total = asArray(res.total).find(isObject);
      const amount = quantity(isObject(total) ? total.amount : undefined) || (isObject(res.total) ? quantity(res.total) : "");
      return { title: join(res.resourceType === "Claim" ? "Claim" : "Insurer payment", conceptText(res.type)), subtitle: join(amount, date) };
    }
    case "MedicationRequest":
    case "MedicationAdministration":
      return { title: conceptText(res.medicationCodeableConcept) || "Medication", subtitle: join(str(res.status), date) };
    case "Immunization":
      return { title: conceptText(res.vaccineCode) || "Immunization", subtitle: date };
    case "CarePlan":
      return { title: firstConcept(res.category) || str(res.title) || "Care plan", subtitle: join(str(res.status), date) };
    case "CareTeam":
      return { title: str(res.name) || "Care team", subtitle: date };
    case "Goal":
      return { title: conceptText(res.description) || "Goal", subtitle: join(str(res.lifecycleStatus), date) };
    case "DocumentReference":
      return { title: conceptText(res.type) || "Document", subtitle: date };
    case "Device":
      return { title: firstConcept(res.type) || str((asArray(res.deviceName).find(isObject) as Json | undefined)?.name) || "Device", subtitle: "" };
    case "SupplyDelivery":
      return { title: (isObject(res.suppliedItem) ? conceptText(res.suppliedItem.itemCodeableConcept) : "") || "Supply delivery", subtitle: date };
    case "ImagingStudy":
      return { title: str(res.description) || "Imaging study", subtitle: date };
    case "Coverage":
      return { title: conceptText(res.type) || "Coverage", subtitle: str(res.status) };
    case "Practitioner":
      return { title: humanName(res.name) || "Practitioner", subtitle: "" };
    case "PractitionerRole":
      return { title: firstConcept(res.specialty) || firstConcept(res.code) || "Practitioner role", subtitle: "" };
    case "Organization":
    case "Location":
      return { title: str(res.name) || res.resourceType, subtitle: "" };
    case "Provenance":
      return { title: "Provenance", subtitle: date };
    default:
      return {
        title: conceptText(res.code) || firstConcept(res.type) || firstConcept(res.category) || res.resourceType,
        subtitle: join(str(res.status), date),
      };
  }
}

// ── the graph to draw ──────────────────────────────────────────────────────

const sortKey = (n: FlowNode) => n.date || "9999";

export function buildGraph(parsed: ParsedBundle, opts: GraphOptions): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const { resources, links, patientId } = parsed;
  const visible = parsed.order.filter((id) => !opts.hiddenTypes.has(resources.get(id)!.resourceType));
  const visibleSet = new Set(visible);
  const typeOf = (id: string) => resources.get(id)!.resourceType;

  // Which visit does each resource belong to? (its reference to an Encounter)
  const visitOf = new Map<string, string>();
  for (const l of links) if (!visitOf.has(l.from) && typeOf(l.to) === "Encounter") visitOf.set(l.from, l.to);

  // Many results of one type in one visit fold into a single node.
  const groupOf = new Map<string, string>();
  const groups = new Map<string, string[]>();
  if (opts.collapse) {
    const buckets = new Map<string, string[]>();
    for (const id of visible) {
      if (NEVER_GROUP.has(typeOf(id))) continue;
      const key = `group:${visitOf.get(id) ?? "patient"}:${typeOf(id)}`;
      const bucket = buckets.get(key);
      if (bucket) bucket.push(id);
      else buckets.set(key, [id]);
    }
    for (const [key, members] of buckets) {
      if (members.length <= (opts.groupMin ?? GROUP_MIN) || opts.expanded.has(key)) continue;
      groups.set(key, members);
      members.forEach((m) => groupOf.set(m, key));
    }
  }
  const nodeId = (id: string) => groupOf.get(id) ?? id;

  const nodes: FlowNode[] = [];
  for (const id of visible) {
    if (groupOf.has(id)) continue;
    const res = resources.get(id)!;
    nodes.push({ id, type: res.resourceType, date: dateOf(res), ...describe(res) });
  }
  for (const [key, members] of groups) {
    const dates = members.map((m) => dateOf(resources.get(m)!)).filter(Boolean).sort();
    const type = typeOf(members[0]);
    nodes.push({
      id: key,
      type,
      title: `${members.length} × ${type}`,
      subtitle: dates.length ? (dates[0] === dates[dates.length - 1] ? dates[0] : `${dates[0]} to ${dates[dates.length - 1]}`) : "",
      date: dates[0] ?? "",
      members,
    });
  }
  // Patient first, then the visits in time order: the graph then reads top to bottom as a timeline.
  nodes.sort((a, b) => (a.id === patientId ? -1 : b.id === patientId ? 1 : (a.type === "Encounter" ? 0 : 1) - (b.type === "Encounter" ? 0 : 1) || sortKey(a).localeCompare(sortKey(b))));

  const edgeMap = new Map<string, FlowEdge>();
  const degree = new Map<string, number>();
  const addEdge = (from: string, to: string, field: string, implied: boolean) => {
    if (from === to) return;
    const key = `${from}|${to}`;
    const existing = edgeMap.get(key);
    if (existing) {
      if (!existing.fields.includes(field)) existing.fields.push(field);
      return;
    }
    edgeMap.set(key, { id: key, from, to, fields: [field], implied });
    degree.set(from, (degree.get(from) ?? 0) + 1);
    degree.set(to, (degree.get(to) ?? 0) + 1);
  };

  for (const l of links) {
    if (!visibleSet.has(l.from) || !visibleSet.has(l.to)) continue;
    const toPatient = l.to === patientId;
    // Every resource points at the Patient; drawing all of those buries the picture. Visits keep theirs (the spine).
    if (toPatient && !opts.patientLinks && typeOf(l.from) !== "Encounter") continue;
    addEdge(nodeId(l.from), nodeId(l.to), l.field, false);
  }
  // Anything left with no connection at all hangs off the Patient so it still appears in the flow.
  if (patientId && visibleSet.has(patientId)) {
    for (const n of nodes) if (n.id !== patientId && !degree.get(n.id)) addEdge(n.id, patientId, "patient", true);
  }
  return { nodes, edges: [...edgeMap.values()] };
}

/** Resources a selected id points at, and the ones pointing at it (all of them, whatever is on screen). */
export function neighbours(parsed: ParsedBundle, id: string) {
  return {
    outgoing: parsed.links.filter((l) => l.from === id),
    incoming: parsed.links.filter((l) => l.to === id),
    unresolved: parsed.unresolved.get(id) ?? [],
  };
}

export function countByType(parsed: ParsedBundle): [string, number][] {
  const counts = new Map<string, number>();
  for (const res of parsed.resources.values()) counts.set(res.resourceType, (counts.get(res.resourceType) ?? 0) + 1);
  return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

/** A record this big is drawn coarser by default: one node per type per visit, so the page stays quick. */
export const LARGE_RECORD = 3000;
