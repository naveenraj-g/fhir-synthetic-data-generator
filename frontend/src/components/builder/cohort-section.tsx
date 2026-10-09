"use client";

import { DicesIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { useSpecialties } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";
import { Field, SimpleSelect } from "./inputs";
import { PlacePicker } from "./place-picker";
import { Section, type SectionProps } from "./section";
import { TargetChip, TargetPicker, useTermsConnector } from "./target-picker";

function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="bg-muted inline-flex rounded-lg p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded-md px-3 py-1 text-sm transition-colors",
            value === o.value ? "bg-background font-medium shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function CohortSection({ state, update }: SectionProps) {
  const { data: specialties } = useSpecialties();
  const connector = useTermsConnector(state.connector || undefined);
  const specialty = state.specialty ? specialties?.[state.specialty] : undefined;

  const hasConditions = state.conditions.length > 0 || (specialty?.conditions?.length ?? 0) > 0;
  const hasProcedures = state.procedures.length > 0 || (specialty?.procedures?.length ?? 0) > 0;
  const hasMedications = state.medications.length > 0 || (specialty?.medications?.length ?? 0) > 0;
  const groupsChosen = [hasConditions, hasProcedures, hasMedications].filter(Boolean).length;
  const specialtyOptions = [
    { value: "none", label: "None" },
    ...Object.entries(specialties ?? {}).map(([name, def]) => ({
      value: name,
      label: `${name.replace(/-/g, " ").replace(/^./, (c) => c.toUpperCase())}${def.description ? ` - ${def.description}` : ""}`,
    })),
  ];

  return (
    <Section
      step={2}
      title="Who"
      description="How many patients, and what they must be like. Leave anything blank to not restrict it."
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Patients" htmlFor="count" required>
          <Input id="count" type="number" min={1} value={state.count} onChange={(e) => update({ count: e.target.value })} />
        </Field>
        <Field label="Seed" htmlFor="seed" hint="Same seed = same data.">
          <div className="flex gap-1.5">
            <Input id="seed" type="number" min={0} placeholder="random" value={state.seed} onChange={(e) => update({ seed: e.target.value })} />
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label="Pick a random seed"
              onClick={() => update({ seed: String(Math.floor(Math.random() * 1_000_000)) })}
            >
              <DicesIcon />
            </Button>
          </div>
        </Field>
        <Field label="Age" hint="Years, e.g. 40 to 65.">
          <div className="flex items-center gap-1.5">
            <Input aria-label="Minimum age" type="number" min={0} placeholder="min" value={state.ageMin} onChange={(e) => update({ ageMin: e.target.value })} />
            <span className="text-muted-foreground">-</span>
            <Input aria-label="Maximum age" type="number" min={0} placeholder="max" value={state.ageMax} onChange={(e) => update({ ageMax: e.target.value })} />
          </div>
        </Field>
        <Field label="Gender">
          <Segmented
            label="Gender"
            value={state.gender}
            onChange={(gender) => update({ gender })}
            options={[
              { value: "any", label: "Any" },
              { value: "F", label: "Female" },
              { value: "M", label: "Male" },
            ]}
          />
        </Field>
        <Field label="State" htmlFor="state" hint="Blank = the connector's default state.">
          <PlacePicker
            id="state"
            placeholder="Default state"
            connector={state.connector || undefined}
            value={state.state}
            onChange={(next) => update({ state: next, city: "" })} // a city belongs to one state
          />
        </Field>
        <Field label="City" htmlFor="city" hint={state.state ? undefined : "Pick a state first."}>
          <PlacePicker
            id="city"
            placeholder="Any city"
            connector={state.connector || undefined}
            state={state.state || undefined}
            value={state.city}
            onChange={(city) => update({ city })}
            disabled={!state.state}
          />
        </Field>
        <Field label="Years of history" htmlFor="years" hint="0 = the whole life.">
          <Input id="years" type="number" min={0} placeholder="connector default" value={state.yearsOfHistory} onChange={(e) => update({ yearsOfHistory: e.target.value })} />
        </Field>
        <Field label="Deceased patients">
          <SimpleSelect
            value={state.onlyAlive}
            onChange={(v) => update({ onlyAlive: v as typeof state.onlyAlive })}
            options={[
              { value: "default", label: "Exclude (default)" },
              { value: "yes", label: "Alive only" },
              { value: "no", label: "Include" },
            ]}
          />
        </Field>
      </div>

      <Separator />

      <div className="flex flex-col gap-4">
        <div>
          <h3 className="text-sm font-medium">Target a disease, specialty or operation</h3>
          <p className="text-muted-foreground text-xs">
            Only patients matching these are generated. Search by words, e.g. &quot;reflux&quot; or &quot;colonoscopy&quot;.
          </p>
        </div>

        <Field label="Specialty" htmlFor="specialty" hint="A named group of diseases and/or operations, defined in the backend config.">
          <SimpleSelect
            id="specialty"
            value={state.specialty || "none"}
            onChange={(v) => update({ specialty: v === "none" ? "" : v })}
            options={specialtyOptions}
          />
        </Field>

        {specialty && (
          <div className="bg-muted/50 flex flex-col gap-2 rounded-lg p-3 text-sm">
            <p className="text-muted-foreground text-xs">
              This specialty matches patients who {specialty.match === "any" ? "have any of these diseases OR had any of these operations" : "match all of its criteria"}
              {specialty.age_range ? `, aged ${specialty.age_range[0]}-${specialty.age_range[1]} unless you set an age above` : ""}:
            </p>
            {!!specialty.conditions?.length && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-xs font-medium">Diseases</span>
                {specialty.conditions.map((c) => <TargetChip key={c} connector={connector} reference={c} />)}
              </div>
            )}
            {!!specialty.procedures?.length && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-xs font-medium">Operations</span>
                {specialty.procedures.map((c) => <TargetChip key={c} connector={connector} reference={c} />)}
              </div>
            )}
          </div>
        )}

        <div className="grid gap-4 lg:grid-cols-2">
          <Field label={specialty ? "Plus these diseases" : "Diseases"} hint="Patients must have any of them.">
            <TargetPicker kind="condition" value={state.conditions} onChange={(conditions) => update({ conditions })} preferredConnector={state.connector || undefined} addLabel="Add disease" />
          </Field>
          <Field label={specialty ? "Plus these operations" : "Operations"} hint="Patients must have had any of them. Full history is exported so the operation is in the record.">
            <TargetPicker kind="procedure" value={state.procedures} onChange={(procedures) => update({ procedures })} preferredConnector={state.connector || undefined} addLabel="Add operation" />
          </Field>
        </div>

        {/* Not offered with a specialty: "all" would then also demand every code in the specialty's own list. */}
        {!state.specialty && (state.conditions.length > 1 || state.procedures.length > 1 || state.medications.length > 1) && (
          <Field
            label="When you pick several diseases (or several operations)"
            hint='"All of them" finds patients with every one, e.g. diabetes AND hypertension (a comorbidity).'
          >
            <Segmented
              label="Combine several picks"
              value={state.within}
              onChange={(within) => update({ within })}
              options={[
                { value: "any", label: "Any of them" },
                { value: "all", label: "All of them" },
              ]}
            />
          </Field>
        )}

        <Field
          label="Medications (currently taking)"
          hint="Patients who are on any of these medications at the end of the period, e.g. metformin. Search by drug name."
        >
          <TargetPicker kind="medication" value={state.medications} onChange={(medications) => update({ medications })} preferredConnector={state.connector || undefined} addLabel="Add medication" />
        </Field>

        {groupsChosen > 1 && (
          <Field label="When you chose more than one of the above (diseases, operations, medications)">
            <Segmented
              label="Match mode"
              value={state.match === "default" ? (specialty?.match ?? "all") : state.match}
              onChange={(match) => update({ match })}
              options={[
                { value: "all", label: "All of them (AND)" },
                { value: "any", label: "Any one of them (OR)" },
              ]}
            />
          </Field>
        )}
      </div>
    </Section>
  );
}
