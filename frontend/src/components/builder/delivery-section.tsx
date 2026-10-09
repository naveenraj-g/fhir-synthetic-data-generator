"use client";

import { ArchiveIcon, FileJsonIcon, FilesIcon, ZapIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useSinks } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";
import { Section, type SectionProps } from "./section";

const SINK_UI: Record<string, { title: string; icon: typeof ZapIcon; background: boolean; blurb: string }> = {
  json: { title: "View here + download", icon: FileJsonIcon, background: true, blurb: "Shown on the job page and kept 72 hours as one JSON file you can download. Safe for runs that take a while." },
  inline: { title: "Instant response (API only)", icon: FileJsonIcon, background: false, blurb: "Held in the HTTP response; lost if the connection drops." },
  zip: { title: "ZIP download", icon: ArchiveIcon, background: true, blurb: "One JSON file per FHIR bundle, compressed. Works for any size." },
  ndjson: { title: "NDJSON files", icon: FilesIcon, background: true, blurb: "One file per resource type, one resource per line (Bulk Data style)." },
};

export function DeliverySection({ state, update }: SectionProps) {
  const { data, isPending } = useSinks();
  return (
    <Section step={4} title="Delivery" description="How you receive the result. Downloads are kept for 72 hours, then deleted.">
      <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Delivery">
        {isPending && Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-lg" />)}
        {/* `inline` holds the HTTP request open while Synthea runs; it is for API callers, not for this form. */}
        {data?.filter((sink) => sink.name !== "inline").map((sink) => {
          const ui = SINK_UI[sink.name] ?? { title: sink.name, icon: ZapIcon, background: true, blurb: sink.description ?? "" };
          const Icon = ui.icon;
          const selected = state.sink === sink.name;
          return (
            <button
              key={sink.name}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => update({ sink: sink.name })}
              className={cn(
                "hover:bg-muted flex flex-col items-start gap-1.5 rounded-lg border p-3 text-left transition-colors",
                selected && "border-primary bg-primary/5",
              )}
            >
              <span className="flex w-full items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 text-sm font-medium">
                  <Icon className="size-4" /> {ui.title}
                </span>
                <Badge variant={ui.background ? "outline" : "secondary"}>{ui.background ? "background job" : "instant"}</Badge>
              </span>
              <span className="text-muted-foreground text-xs">{ui.blurb}</span>
            </button>
          );
        })}
      </div>
    </Section>
  );
}
