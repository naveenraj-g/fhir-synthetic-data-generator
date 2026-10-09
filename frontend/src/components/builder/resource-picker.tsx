"use client";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { newStepId, OBSERVATION_CATEGORIES, type ShapeStepState } from "@/lib/builder-state";
import { cn } from "@/lib/utils";
import { ChoiceChips } from "./inputs";

/**
 * Every resource type Synthea emits, in plain-language sections. Picking here edits the `resource_types` step of the
 * shape (and a `resource_filter` step for the kinds of observation), so the step list below always shows exactly
 * what will run and either way of editing works.
 */
const CATALOG: { title: string; blurb: string; types: { type: string; hint: string }[] }[] = [
  { title: "Patients and visits", blurb: "Who they are and each time they were seen", types: [
    { type: "Patient", hint: "Demographics: name, birth date, gender, address" },
    { type: "Encounter", hint: "Visits: office, emergency, inpatient" },
  ] },
  { title: "Diagnoses", blurb: "Conditions and allergies", types: [
    { type: "Condition", hint: "Diagnoses, with onset and resolution dates" },
    { type: "AllergyIntolerance", hint: "Allergies and intolerances" },
  ] },
  { title: "Procedures and care plans", blurb: "Operations and the plan of care", types: [
    { type: "Procedure", hint: "Operations and other procedures" },
    { type: "CarePlan", hint: "Care plans, with their goals" },
    { type: "CareTeam", hint: "Who is on the care team" },
    { type: "Goal", hint: "Patient goals set in care plans" },
  ] },
  { title: "Orders", blurb: "Requests for tests and services", types: [
    { type: "ServiceRequest", hint: "Orders for tests, imaging, referrals and other services" },
  ] },
  { title: "Medications", blurb: "Prescriptions and doses given", types: [
    { type: "MedicationRequest", hint: "Prescriptions" },
    { type: "MedicationAdministration", hint: "Doses given in a visit" },
    { type: "Medication", hint: "The medication definitions referred to" },
  ] },
  { title: "Vaccines", blurb: "", types: [{ type: "Immunization", hint: "Vaccinations given" }] },
  { title: "Results", blurb: "Vitals, labs and reports", types: [
    { type: "Observation", hint: "Vital signs, lab values, surveys, social history" },
    { type: "DiagnosticReport", hint: "Lab and imaging reports (group several observations)" },
    { type: "ImagingStudy", hint: "Imaging studies (X-ray, CT, MRI)" },
    { type: "Media", hint: "Media attached to results, such as images" },
  ] },
  { title: "Notes and audit", blurb: "", types: [
    { type: "DocumentReference", hint: "Clinical notes" },
    { type: "Provenance", hint: "Audit trail: who produced the record" },
  ] },
  { title: "Devices and supplies", blurb: "", types: [
    { type: "Device", hint: "Implants and devices" },
    { type: "SupplyDelivery", hint: "Supplies delivered" },
  ] },
  { title: "Billing", blurb: "Claims and what the insurer paid", types: [
    { type: "Claim", hint: "Claims submitted" },
    { type: "ExplanationOfBenefit", hint: "What the insurer paid" },
    { type: "Coverage", hint: "The insurance plan behind the claims" },
  ] },
  { title: "Providers and places", blurb: "Added from Synthea's provider lists", types: [
    { type: "Practitioner", hint: "Doctors and other clinicians" },
    { type: "PractitionerRole", hint: "Each clinician's role at an organization" },
    { type: "Organization", hint: "Hospitals, clinics, payers" },
    { type: "Location", hint: "Facilities and their addresses" },
  ] },
];

const KIND_LABELS: Record<string, string> = {
  "vital-signs": "Vital signs",
  laboratory: "Lab results",
  survey: "Surveys",
  "social-history": "Social history",
  exam: "Exams",
  imaging: "Imaging",
  procedure: "Procedure results",
  therapy: "Therapy",
  activity: "Activity",
};

type Shape = ShapeStepState[];
const list = (v: unknown): string[] => (Array.isArray(v) ? (v as string[]) : []);
const typesIndex = (shape: Shape) => shape.findIndex((s) => s.slicer === "resource_types");

/** The types the shape keeps, or null when it has no type restriction (every type is returned). */
function selectedTypes(shape: Shape, groups: Record<string, string[]>): Set<string> | null {
  const step = shape[typesIndex(shape)];
  if (!step) return null;
  const p = step.params;
  const set = new Set([...list(p.types), ...list(p.groups).flatMap((g) => groups[g] ?? [])]);
  list(p.exclude_types).forEach((t) => set.delete(t));
  if (p.keep_patient !== false) set.add("Patient");
  return set;
}

/** Write a chosen set back as an explicit `types` list (groups are expanded, so what you see is what runs). */
function withTypes(shape: Shape, next: Set<string>): Shape {
  const i = typesIndex(shape);
  if (next.size === 0) return i < 0 ? shape : shape.filter((_, k) => k !== i);
  const params = { ...(i >= 0 ? shape[i].params : {}), types: [...next].sort(), groups: [], exclude_types: [] } as Record<string, unknown>;
  if (next.has("Patient")) delete params.keep_patient;
  else params.keep_patient = false;
  if (i >= 0) return shape.map((s, k) => (k === i ? { ...s, params } : s));
  // "Everything" is a full_record step: replace it, keeping its choice about providers.
  const full = shape.findIndex((s) => s.slicer === "full_record");
  if (full >= 0 && shape[full].params.include_infrastructure) params.include_infrastructure = true;
  const step = { id: newStepId(), slicer: "resource_types", params };
  return full >= 0 ? shape.map((s, k) => (k === full ? step : s)) : [step, ...shape];
}

const isKindFilter = (s: ShapeStepState) =>
  s.slicer === "resource_filter" && s.params.resource_type === "Observation" && !s.params.exclude && !list(s.params.codes).length && !list(s.params.status).length;

function withKinds(shape: Shape, kinds: string[]): Shape {
  const i = shape.findIndex(isKindFilter);
  if (kinds.length === 0) return i < 0 ? shape : shape.filter((_, k) => k !== i);
  if (i >= 0) return shape.map((s, k) => (k === i ? { ...s, params: { ...s.params, categories: kinds } } : s));
  const step = { id: newStepId(), slicer: "resource_filter", params: { resource_type: "Observation", categories: kinds } };
  const at = typesIndex(shape) + 1; // right after the type selection (0 when there is none)
  return [...shape.slice(0, at), step, ...shape.slice(at)];
}

export function ResourcePicker({
  shape,
  groups,
  onChange,
}: {
  shape: Shape;
  groups: Record<string, string[]>;
  onChange: (shape: Shape) => void;
}) {
  const selected = selectedTypes(shape, groups);
  const all = CATALOG.flatMap((s) => s.types.map((t) => t.type));
  const current = selected ?? new Set<string>();
  const kindStep = shape.find(isKindFilter);
  const typesStep = shape[typesIndex(shape)];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">Resource types</span>
        <span className="text-muted-foreground text-xs">
          {selected ? `${selected.size} selected` : "None picked: every type is returned."}
        </span>
        <div className="ml-auto flex gap-1">
          <Button type="button" variant="ghost" size="xs" onClick={() => onChange(withTypes(shape, new Set(all)))}>
            Select all
          </Button>
          <Button type="button" variant="ghost" size="xs" disabled={!selected} onClick={() => onChange(withTypes(shape, new Set()))}>
            Clear
          </Button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {CATALOG.map((section) => {
          const types = section.types.map((t) => t.type);
          const chosen = types.filter((t) => current.has(t));
          const setSection = (next: string[]) => {
            const merged = new Set([...current].filter((t) => !types.includes(t)));
            next.forEach((t) => merged.add(t));
            onChange(withTypes(shape, merged));
          };
          return (
            <div
              key={section.title}
              className={cn("flex flex-col overflow-hidden rounded-lg border", chosen.length > 0 && "border-primary/40")}
            >
              <div className="bg-muted/50 flex items-center gap-2 border-b px-3 py-2">
                <div className="flex min-w-0 flex-col">
                  <span className="text-sm font-semibold">{section.title}</span>
                  {section.blurb && <span className="text-muted-foreground truncate text-xs">{section.blurb}</span>}
                </div>
                <span className="text-muted-foreground ml-auto shrink-0 text-xs tabular-nums">
                  {chosen.length}/{types.length}
                </span>
                <button
                  type="button"
                  className="text-muted-foreground hover:text-foreground shrink-0 text-xs underline-offset-2 hover:underline"
                  onClick={() => setSection(chosen.length === types.length ? [] : types)}
                >
                  {chosen.length === types.length ? "none" : "all"}
                </button>
              </div>
              <div className="p-3">
                <ChoiceChips
                  value={chosen}
                  onChange={setSection}
                  options={section.types.map((t) => ({ value: t.type, hint: t.hint }))}
                />
              </div>
            </div>
          );
        })}
      </div>

      {current.has("Observation") && (
        <div className="flex flex-col gap-1.5 rounded-lg border p-3">
          <span className="text-sm font-medium">Which observations?</span>
          <ChoiceChips
            value={list(kindStep?.params.categories)}
            onChange={(kinds) => onChange(withKinds(shape, kinds))}
            options={OBSERVATION_CATEGORIES.map((c) => ({ value: c, label: KIND_LABELS[c] ?? c }))}
          />
          <p className="text-muted-foreground text-xs">None picked = all kinds. Pick Vital signs for blood pressure, heart rate and weight; Lab results for blood tests.</p>
        </div>
      )}

      {typesStep && (
        <label className="flex items-start gap-2 text-sm">
          <Switch
            checked={typesStep.params.include_infrastructure === true}
            onCheckedChange={(on) =>
              onChange(shape.map((s) => (s === typesStep ? { ...s, params: { ...s.params, include_infrastructure: on } } : s)))
            }
          />
          <span>
            Include the doctors and organizations the records point to
            <span className="text-muted-foreground block text-xs">So each bundle is self-contained (references resolve). Off keeps the bundles smaller.</span>
          </span>
        </label>
      )}
    </div>
  );
}
