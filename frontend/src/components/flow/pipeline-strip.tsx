"use client";

import { ChevronRightIcon } from "lucide-react";
import { Fragment } from "react";
import { Card, CardContent } from "@/components/ui/card";
import type { JobResponse } from "@/lib/api/client";
import { formatBytes, formatDuration, formatNumber } from "@/lib/format";

interface Stage {
  stage: string;
  bundles: number;
  resources: number;
  by_type: Record<string, number>;
}
type Json = Record<string, unknown>;

const pretty = (name: string) => name.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
const list = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : []);

/** One line per non-empty parameter of a slicer step, e.g. "types: Observation, Condition". */
function paramLines(params: unknown): string[] {
  return Object.entries((params ?? {}) as Json)
    .filter(([, v]) => v !== undefined && v !== null && v !== "" && !(Array.isArray(v) && v.length === 0) && v !== false)
    .map(([k, v]) => `${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(", ") : String(v)}`);
}

function Box({ title, tone, lines, footer }: { title: string; tone: string; lines: string[]; footer?: string }) {
  return (
    <Card size="sm" className="w-56 shrink-0">
      <CardContent className="flex flex-col gap-1">
        <span className="text-[10px] font-semibold tracking-wide uppercase" style={{ color: tone }}>
          {title}
        </span>
        {lines.map((l, i) => (
          <span key={i} className="text-muted-foreground text-xs break-words">
            {l}
          </span>
        ))}
        {footer && <span className="mt-1 border-t pt-1 text-xs font-medium">{footer}</span>}
      </CardContent>
    </Card>
  );
}

function Arrow({ label }: { label?: string }) {
  return (
    <div className="text-muted-foreground flex w-16 shrink-0 flex-col items-center justify-center text-[10px] leading-tight">
      <ChevronRightIcon className="size-4" />
      {label && <span className="text-center">{label}</span>}
    </div>
  );
}

/** Request -> connector -> each step -> delivery, with what each stage let through (counts recorded by the run). */
export function PipelineStrip({ job }: { job: JobResponse }) {
  const spec = job.resolved_spec as unknown as { cohort: Json; shape: { slicer: string; params?: unknown }[]; sink: { name: string } };
  const prov = (job.provenance ?? {}) as Json;
  const stages = (Array.isArray(prov.stages) ? prov.stages : []) as Stage[];
  const cohort = spec.cohort;
  const age = cohort.age_range as [number, number] | undefined;

  const request = [
    `${cohort.count ?? 1} patient${cohort.count === 1 ? "" : "s"}${cohort.gender ? `, ${cohort.gender === "F" ? "female" : "male"}` : ""}${age ? `, age ${age[0]}-${age[1]}` : ""}`,
    [cohort.city, cohort.state].filter(Boolean).join(", "),
    cohort.specialty ? `specialty: ${cohort.specialty}` : "",
    ...(["conditions", "procedures", "medications"] as const).map((k) => (list(cohort[k]).length ? `${list(cohort[k]).length} ${k} targeted` : "")),
    cohort.years_of_history !== undefined && cohort.years_of_history !== null ? `${cohort.years_of_history} years of history` : "",
  ].filter(Boolean);

  const connectorLines = [
    prov.synthea_version ? `Synthea ${prov.synthea_version}` : "",
    prov.mode ? `run in ${prov.mode}` : "",
    prov.seed_used !== undefined && prov.seed_used !== null ? `seed ${prov.seed_used}${prov.retried_after_timeout ? " (retried after a stall)" : ""}` : "",
    prov.reference_date ? `dates as of ${prov.reference_date}` : "",
    typeof prov.elapsed_seconds === "number" ? `whole run took ${formatDuration(prov.elapsed_seconds)}` : "",
  ].filter(Boolean);

  const count = (s?: Stage) => (s ? `${formatNumber(s.bundles)} bundle${s.bundles === 1 ? "" : "s"}, ${formatNumber(s.resources)} resources` : undefined);
  const flow = (s?: Stage) => (s ? `${formatNumber(s.resources)} resources` : undefined);
  const files = job.artifacts;

  return (
    <div className="flex items-stretch overflow-x-auto pb-2" aria-label="How this data was made">
      <Box title="1 · Your request" tone="oklch(0.62 0.17 255)" lines={request} />
      <Arrow />
      <Box title={`2 · ${pretty(String(prov.connector_name ?? job.connector))}`} tone="oklch(0.66 0.15 150)" lines={connectorLines} footer={count(stages[0])} />
      {spec.shape.map((step, i) => {
        const before = stages[i];
        const after = stages[i + 1];
        const removed = before && after ? before.resources - after.resources : undefined;
        return (
          <Fragment key={i}>
            <Arrow label={flow(before)} />
            <Box
              title={`${i + 3} · ${pretty(step.slicer)}`}
              tone="oklch(0.7 0.16 70)"
              lines={paramLines(step.params).length ? paramLines(step.params) : ["no settings"]}
              footer={after ? `${count(after)}${removed ? ` (${removed > 0 ? "-" : "+"}${formatNumber(Math.abs(removed))})` : ""}` : undefined}
            />
          </Fragment>
        );
      })}
      <Arrow label={flow(stages[stages.length - 1])} />
      <Box
        title={`${spec.shape.length + 3} · Delivery: ${spec.sink.name}`}
        tone="oklch(0.62 0.18 295)"
        lines={files.length ? files.slice(0, 5).map((f) => `${f.filename} (${formatBytes(f.size)})`).concat(files.length > 5 ? [`and ${files.length - 5} more`] : []) : ["no files (expired or not stored)"]}
      />
    </div>
  );
}
