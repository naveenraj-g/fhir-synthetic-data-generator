"use client";

import { ChevronDownIcon, TriangleAlertIcon } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useConnectorHealth, useConnectors } from "@/lib/api/hooks";
import { Field, SimpleSelect } from "./inputs";
import type { SectionProps } from "./section";

export function AdvancedSection({ state, update }: SectionProps) {
  const { data: connectors } = useConnectors();
  const enabled = (connectors ?? []).filter((c) => c.enabled);
  const selected = enabled.find((c) => c.name === state.connector);
  // "Default connector" is decided by the backend config, so health is checked for what will actually run.
  const effective = state.connector || enabled.find((c) => c.type === "synthea")?.name || enabled[0]?.name;
  const health = useConnectorHealth(effective);
  const isSynthea = (selected ?? enabled.find((c) => c.name === effective))?.type === "synthea";

  return (
    <Collapsible className="rounded-xl border">
      <CollapsibleTrigger className="group hover:bg-muted/50 flex w-full items-center justify-between gap-2 rounded-xl p-4 text-left text-sm font-medium">
        <span>
          Advanced options
          <span className="text-muted-foreground ml-2 font-normal">connector, dates, US Core, reference check</span>
        </span>
        <ChevronDownIcon className="size-4 transition-transform group-aria-expanded:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="flex flex-col gap-5 border-t p-4">
        {health.data && !health.data.ok && (
          <Alert variant="destructive">
            <TriangleAlertIcon />
            <AlertTitle>The &quot;{effective}&quot; connector is not usable right now</AlertTitle>
            <AlertDescription>{health.data.detail}</AlertDescription>
          </Alert>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Connector" htmlFor="connector" hint="Where the data comes from. Synthea generates realistic records; static fixtures are instant samples that need no Docker.">
            <SimpleSelect
              id="connector"
              value={state.connector || "default"}
              onChange={(v) => update({ connector: v === "default" ? "" : v })}
              options={[
                { value: "default", label: "Default (from config)" },
                ...enabled.map((c) => ({ value: c.name, label: c.name.replace(/_/g, " ") })),
              ]}
            />
          </Field>
          {isSynthea && (
            <>
              <Field label="Reference date" htmlFor="ref-date" hint="Ages are computed as of this date. Blank = the server's pinned date.">
                <Input id="ref-date" type="date" value={state.referenceDate} onChange={(e) => update({ referenceDate: e.target.value })} />
              </Field>
              <Field label="End date" htmlFor="end-date" hint="Where the simulation stops. Blank = same as the reference date.">
                <Input id="end-date" type="date" value={state.endDate} onChange={(e) => update({ endDate: e.target.value })} />
              </Field>
            </>
          )}
        </div>
        {isSynthea && (
          <div className="flex items-start justify-between gap-3 rounded-lg border p-3">
            <div className="flex flex-col gap-1">
              <label htmlFor="us-core" className="text-sm leading-none font-medium">US Core profiles</label>
              <p className="text-muted-foreground text-xs">Mark resources with the US Core Implementation Guide profiles.</p>
            </div>
            <Switch id="us-core" checked={state.usCore} onCheckedChange={(usCore) => update({ usCore })} />
          </div>
        )}
        <div className="flex items-start justify-between gap-3 rounded-lg border p-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="check-refs" className="text-sm leading-none font-medium">Verify references</label>
            <p className="text-muted-foreground text-xs">Fail the job if any reference in the output points at something that is not in it.</p>
          </div>
          <Switch id="check-refs" checked={state.checkReferences} onCheckedChange={(checkReferences) => update({ checkReferences })} />
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
