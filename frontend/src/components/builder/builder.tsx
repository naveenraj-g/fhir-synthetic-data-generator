"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { toast } from "sonner";
import { useCreateGeneration, usePreview } from "@/lib/api/hooks";
import type { GenerationRequest } from "@/lib/api/client";
import { INITIAL_STATE, toRequest, type BuilderState } from "@/lib/builder-state";
import { saveInline } from "@/lib/inline-store";
import { clearPrefill, peekPrefill, prefillVersion, subscribePrefill } from "@/lib/prefill";
import { AdvancedSection } from "./advanced-section";
import { CohortSection } from "./cohort-section";
import { DeliverySection } from "./delivery-section";
import { PresetSection } from "./preset-section";
import { ShapeSection } from "./shape-section";
import { SummaryPanel } from "./summary-panel";
import { useDebounced } from "./target-picker";

/** A new "Edit & re-run" / "Use in generator" hand-off remounts the form, even if this page was kept alive. */
export function Builder() {
  const version = useSyncExternalStore(subscribePrefill, prefillVersion, () => 0);
  return <BuilderForm key={version} version={version} />;
}

function BuilderForm({ version }: { version: number }) {
  const router = useRouter();
  // Started from "Edit & re-run" / "Use in generator" when one of them set a prefill, otherwise blank.
  const [state, setState] = useState<BuilderState>(() => peekPrefill() ?? INITIAL_STATE);
  const update = useCallback((patch: Partial<BuilderState>) => setState((s) => ({ ...s, ...patch })), []);

  // Only the form that consumed this hand-off clears it: a kept-alive older form must not clear a newer one first.
  useEffect(() => {
    if (prefillVersion() === version) clearPrefill();
  }, [version]);

  const request = useMemo(() => toRequest(state), [state]);
  // Validate against the real API as the form changes (debounced), so errors appear next to the cause.
  const requestKey = useDebounced(JSON.stringify(request), 500);
  const debouncedRequest = useMemo(() => JSON.parse(requestKey) as GenerationRequest, [requestKey]);
  const preview = usePreview(debouncedRequest);
  const create = useCreateGeneration();

  const generate = () =>
    create.mutate(request, {
      onSuccess: (res) => {
        if (res.data) saveInline(res.id, res.data);
        toast.success(res.status === "succeeded" ? "Generated" : "Job submitted");
        router.push(`/jobs/${res.id}`);
      },
      onError: (e) => toast.error(e.message),
    });

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="flex min-w-0 flex-col gap-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Generate synthetic FHIR data</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Choose who, what slice of their record, and how you want it delivered. Every combination works.
          </p>
        </div>
        <PresetSection state={state} onPick={setState} />
        <CohortSection state={state} update={update} />
        <ShapeSection state={state} update={update} />
        <DeliverySection state={state} update={update} />
        <AdvancedSection state={state} update={update} />
      </div>
      <aside className="lg:sticky lg:top-20">
        <SummaryPanel
          request={request}
          preview={preview.data}
          previewError={preview.error}
          previewLoading={preview.isFetching || requestKey !== JSON.stringify(request)}
          generating={create.isPending}
          onGenerate={generate}
        />
      </aside>
    </div>
  );
}
