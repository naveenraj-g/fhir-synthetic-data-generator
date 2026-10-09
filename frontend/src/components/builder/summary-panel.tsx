"use client";

import { CheckCircle2Icon, ChevronDownIcon, CopyIcon, Loader2Icon, SparklesIcon, TriangleAlertIcon } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ApiError, type GenerationRequest, type PreviewResponse } from "@/lib/api/client";

function detailText(d: unknown): string {
  if (typeof d === "string") return d;
  if (d && typeof d === "object") {
    const o = d as { field?: string; message?: string };
    if (o.message) return o.field ? `${o.field}: ${o.message}` : o.message;
  }
  return JSON.stringify(d);
}

export function SummaryPanel({
  request,
  preview,
  previewError,
  previewLoading,
  generating,
  onGenerate,
}: {
  request: GenerationRequest;
  preview: PreviewResponse | undefined;
  previewError: Error | null;
  previewLoading: boolean;
  generating: boolean;
  onGenerate: () => void;
}) {
  const spec = preview?.resolved_spec;
  const json = JSON.stringify(request, null, 2);
  const invalid = previewError instanceof ApiError && previewError.status >= 400 && previewError.status < 500;
  const cohort = spec?.cohort as { count?: number; conditions?: string[]; procedures?: string[]; medications?: string[]; match?: string; age_range?: number[] | null } | undefined;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Your request</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {invalid && (
          <Alert variant="destructive">
            <TriangleAlertIcon />
            <AlertTitle>{previewError.message}</AlertTitle>
            {(previewError as ApiError).details.length > 0 && (
              <AlertDescription>
                <ul className="list-disc pl-4">
                  {(previewError as ApiError).details.slice(0, 6).map((d, i) => <li key={i}>{detailText(d)}</li>)}
                </ul>
              </AlertDescription>
            )}
          </Alert>
        )}
        {previewError && !invalid && (
          <Alert variant="destructive">
            <TriangleAlertIcon />
            <AlertTitle>Cannot check the request</AlertTitle>
            <AlertDescription>{previewError.message}</AlertDescription>
          </Alert>
        )}

        {!previewError && (
          <div className="flex items-center gap-2 text-sm" aria-live="polite">
            {previewLoading || !preview ? (
              <>
                <Loader2Icon className="text-muted-foreground size-4 animate-spin" />
                <span className="text-muted-foreground">Checking...</span>
              </>
            ) : (
              <>
                <CheckCircle2Icon className="text-success size-4" />
                <span>
                  Ready - {preview.mode === "sync" ? "returns instantly" : "runs in the background, then you download it"}
                </span>
              </>
            )}
          </div>
        )}

        {preview?.warnings.map((w) => (
          <Alert key={w}>
            <TriangleAlertIcon />
            <AlertDescription>{w}</AlertDescription>
          </Alert>
        ))}

        {spec && cohort && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
            <dt className="text-muted-foreground">Connector</dt>
            <dd className="font-medium">{spec.connector}</dd>
            <dt className="text-muted-foreground">Patients</dt>
            <dd className="font-medium">{cohort.count}</dd>
            {!!(cohort.conditions?.length || cohort.procedures?.length || cohort.medications?.length) && (
              <>
                <dt className="text-muted-foreground">Targeting</dt>
                <dd className="font-medium">
                  {[
                    cohort.conditions?.length ? `${cohort.conditions.length} disease${cohort.conditions.length === 1 ? "" : "s"}` : "",
                    cohort.procedures?.length ? `${cohort.procedures.length} operation${cohort.procedures.length === 1 ? "" : "s"}` : "",
                    cohort.medications?.length ? `${cohort.medications.length} medication${cohort.medications.length === 1 ? "" : "s"}` : "",
                  ]
                    .filter(Boolean)
                    .join(", ")}
                  {[cohort.conditions, cohort.procedures, cohort.medications].filter((l) => l?.length).length > 1 ? ` (${cohort.match === "any" ? "any one" : "all"})` : ""}
                </dd>
              </>
            )}
            {cohort.age_range && (
              <>
                <dt className="text-muted-foreground">Age</dt>
                <dd className="font-medium">{cohort.age_range[0]}-{cohort.age_range[1]}</dd>
              </>
            )}
            <dt className="text-muted-foreground">Steps</dt>
            <dd className="font-medium">{spec.shape.map((s) => s.slicer.replace(/_/g, " ")).join(" → ") || "full record"}</dd>
            <dt className="text-muted-foreground">Delivery</dt>
            <dd className="font-medium">{spec.sink.name}</dd>
          </dl>
        )}

        <Button size="lg" className="w-full" disabled={generating || invalid || !!previewError || !preview} onClick={onGenerate}>
          {generating ? <Loader2Icon className="animate-spin" /> : <SparklesIcon />}
          {generating ? (preview?.mode === "sync" ? "Generating (can take a few seconds)..." : "Submitting...") : "Generate"}
        </Button>

        <Collapsible>
          <CollapsibleTrigger className="group text-muted-foreground hover:text-foreground flex w-full items-center justify-between text-xs">
            <span>Request JSON (what is sent to the API)</span>
            <ChevronDownIcon className="size-3.5 transition-transform group-aria-expanded:rotate-180" />
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-2">
            <div className="relative">
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                className="absolute top-1.5 right-1.5"
                aria-label="Copy request JSON"
                onClick={() => navigator.clipboard.writeText(json).then(() => toast.success("Copied"))}
              >
                <CopyIcon />
              </Button>
              <pre className="bg-muted max-h-72 overflow-auto rounded-lg p-3 font-mono text-[11px] leading-relaxed">{json}</pre>
            </div>
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  );
}
