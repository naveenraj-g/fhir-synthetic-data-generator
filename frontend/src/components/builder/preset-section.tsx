"use client";

import { CheckIcon, FileIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { PresetInfo } from "@/lib/api/client";
import { usePresets } from "@/lib/api/hooks";
import { fromPreset, INITIAL_STATE, type BuilderState } from "@/lib/builder-state";
import { cn } from "@/lib/utils";
import { Section } from "./section";

const prettyName = (name: string) => name.replace(/-/g, " ").replace(/^./, (c) => c.toUpperCase());

/** A short plain-language explanation of each template group (shown when it is the one in view). */
const CATEGORY_INFO: Record<string, string> = {
  Gastroenterology: "The digestive system: reflux, gallbladder, appendix, colon. Operation templates give one patient and the stay in which the operation happened.",
  Orthopedics: "Bones and joints: fractures, arthritis, osteoporosis, knee and hip replacements.",
  "Preventive health": "Care that happens before someone is ill: routine check-ups, screening tests, vaccines, and checks of risk factors such as blood pressure and smoking.",
  General: "Building blocks for any use: whole records, only patients, only billing, vitals, labs, time windows.",
  Cardiology: "Heart and circulation: heart attack, atrial fibrillation, heart failure, bypass surgery.",
  Pulmonology: "Lungs and breathing: asthma, COPD, sleep apnea.",
  Neurology: "Brain and nerves: epilepsy, stroke, migraine, Alzheimer's disease.",
  "Mental health": "Mental health and substance use: ADHD, depression, drug and alcohol dependence.",
  Endocrinology: "Hormones and metabolism: prediabetes, thyroid disease, obesity (diabetes is under General).",
  Nephrology: "Kidneys: chronic kidney disease and dialysis.",
  Oncology: "Cancer: breast and lung cancer journeys.",
  Dermatology: "Skin: atopic and contact dermatitis.",
  "ENT (ear, nose, throat)": "Ear, nose and throat: ear infections, sinusitis, hay fever.",
  "Infectious disease": "Infections: urinary tract infections, HIV.",
  Ophthalmology: "Eyes: diabetic eye disease and retinal exams.",
  Rheumatology: "Autoimmune and joint-inflammation disease: rheumatoid arthritis, gout, lupus, fibromyalgia.",
  "Women's health (OB/GYN)": "Pregnancy and childbirth: prenatal care, caesarean section.",
  Hematology: "Blood: anemia and transfusions.",
  Pediatrics: "Children and teenagers (0-17): full records, vaccinations, well-child check-ups.",
  Geriatrics: "Older adults (65 and over): full records and recent history.",
};
const UNCATEGORIZED = "Other";

function groupByCategory(presets: PresetInfo[]): [string, PresetInfo[]][] {
  const groups = new Map<string, PresetInfo[]>();
  for (const p of presets) {
    const key = p.category ?? UNCATEGORIZED;
    groups.set(key, [...(groups.get(key) ?? []), p]);
  }
  // Specialty groups first (in config order); the generic building blocks last.
  const generic = new Set(["General", UNCATEGORIZED]);
  return [...groups.entries()].sort(([a], [b]) => Number(generic.has(a)) - Number(generic.has(b)));
}

function TemplateCard({ preset, selected, onPick }: { preset: PresetInfo; selected: boolean; onPick: () => void }) {
  const count = (preset.cohort as { count?: number } | undefined)?.count;
  const sink = (preset.sink as { name?: string } | null | undefined)?.name;
  return (
    <button
      type="button"
      onClick={onPick}
      aria-pressed={selected}
      className={cn(
        "hover:bg-muted flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-colors",
        selected && "border-primary bg-primary/5",
      )}
    >
      <span className="flex w-full items-center justify-between gap-2 text-sm font-medium">
        {preset.title ?? prettyName(preset.name)}
        {selected && <CheckIcon className="text-primary size-4 shrink-0" />}
      </span>
      <span className="text-muted-foreground line-clamp-3 text-xs">{preset.description}</span>
      <span className="mt-1 flex gap-1">
        {count !== undefined && <Badge variant="outline">{count} patient{count === 1 ? "" : "s"}</Badge>}
        {sink && <Badge variant="outline">{sink}</Badge>}
      </span>
    </button>
  );
}

export function PresetSection({ state, onPick }: { state: BuilderState; onPick: (next: BuilderState) => void }) {
  const { data, isPending, error } = usePresets();
  const [category, setCategory] = useState("all");
  const groups = useMemo(() => groupByCategory(data ?? []), [data]);
  const visible = category === "all" ? groups : groups.filter(([name]) => name === category);

  return (
    <Section
      step={1}
      title="Start from a template"
      description="Pick a ready-made scenario, then change anything below, or start blank and build your own."
    >
      {error && <p className="text-destructive text-sm">{error.message}</p>}

      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Template category">
        {[["all", "All", data?.length ?? 0] as const, ...groups.map(([name, items]) => [name, name, items.length] as const)].map(([value, label, n]) => (
          <button
            key={value}
            type="button"
            aria-pressed={category === value}
            onClick={() => setCategory(value)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
              category === value ? "border-primary bg-primary text-primary-foreground" : "bg-background hover:bg-muted",
            )}
          >
            {label} <span className="opacity-70">{n}</span>
          </button>
        ))}
      </div>
      {category !== "all" && CATEGORY_INFO[category] && <p className="text-muted-foreground -mt-2 text-sm">{CATEGORY_INFO[category]}</p>}

      <button
        type="button"
        onClick={() => onPick({ ...INITIAL_STATE })}
        aria-pressed={state.preset === null}
        className={cn(
          "hover:bg-muted flex w-full items-center gap-3 rounded-lg border border-dashed p-3 text-left transition-colors sm:w-fit sm:pr-8",
          state.preset === null && "border-primary bg-primary/5",
        )}
      >
        <FileIcon className="size-4 shrink-0" />
        <span className="flex flex-col">
          <span className="text-sm font-medium">Blank</span>
          <span className="text-muted-foreground text-xs">Build it yourself from the sections below.</span>
        </span>
      </button>

      {isPending && (
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[92px] rounded-lg" />)}
        </div>
      )}

      {visible.map(([name, items]) => (
        <div key={name} className="flex flex-col gap-2.5">
          {category === "all" && (
            <div>
              <h3 className="text-sm font-semibold">{name}</h3>
              {CATEGORY_INFO[name] && <p className="text-muted-foreground text-xs">{CATEGORY_INFO[name]}</p>}
            </div>
          )}
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {items.map((p) => (
              <TemplateCard key={p.name} preset={p} selected={state.preset === p.name} onPick={() => onPick(fromPreset(p))} />
            ))}
          </div>
        </div>
      ))}
    </Section>
  );
}
