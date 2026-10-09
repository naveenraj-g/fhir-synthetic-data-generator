"use client";

import { ArrowLeftIcon, CopyIcon, DownloadIcon, Loader2Icon, NetworkIcon, PencilIcon, Trash2Icon, TriangleAlertIcon } from "lucide-react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, downloadUrl, type JobResponse, type ResolvedSpec } from "@/lib/api/client";
import { useDeleteJob, useJob, useSpecialties } from "@/lib/api/hooks";
import { fromResolved } from "@/lib/builder-state";
import { formatBytes, formatDuration, formatNumber, parseApiDate, timeUntil } from "@/lib/format";
import { getInline } from "@/lib/inline-store";
import { setPrefill } from "@/lib/prefill";
import { useNow } from "@/lib/use-now";
import { jobTitle } from "./jobs-list";
import { JobStatusBadge } from "./job-status-badge";

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-muted-foreground text-xs">{label}</span>
      <span className="text-lg leading-tight font-semibold">{value}</span>
      {hint && <span className="text-muted-foreground text-xs">{hint}</span>}
    </div>
  );
}

function ResourceBars({ counts }: { counts: Record<string, number> }) {
  const rows = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...rows.map(([, n]) => n));
  return (
    <ul className="flex flex-col gap-1.5">
      {rows.map(([type, n]) => (
        <li key={type} className="grid grid-cols-[9.5rem_1fr_4.5rem] items-center gap-3 text-sm">
          <span className="truncate">{type}</span>
          <span className="bg-muted h-2 overflow-hidden rounded-full" aria-hidden>
            <span className="bg-primary block h-full rounded-full" style={{ width: `${Math.max(2, (n / max) * 100)}%` }} />
          </span>
          <span className="text-right tabular-nums">{formatNumber(n)}</span>
        </li>
      ))}
    </ul>
  );
}

const MAX_SHOWN = 200_000; // characters of JSON rendered at once; the file itself is always fully downloadable
const MAX_VIEW_BYTES = 15 * 1024 * 1024; // larger stored results are download-only (the browser would struggle to render them)

/** A stored JSON result (the "View here + download" delivery) is fetched from the API once and cached. */
function useStoredResult(url: string | undefined) {
  return useQuery({
    queryKey: ["stored-result", url],
    queryFn: async () => {
      const res = await fetch(downloadUrl(url!));
      if (!res.ok) throw new ApiError(res.status === 410 ? "The file expired and was deleted." : `Could not load the result (${res.status})`, res.status, "HTTP_ERROR");
      return (await res.json()) as Record<string, unknown>[];
    },
    enabled: !!url,
    staleTime: Infinity,
    retry: false,
  });
}

/**
 * Shows FHIR bundles with copy + download. `stored` means the result is a file on the server (kept 72 h, so it
 * survives reloads); otherwise it is an in-memory instant result that only exists in this browser session.
 */
function ResultViewer({
  id,
  bundles,
  stored,
}: {
  id: string;
  bundles: Record<string, unknown>[];
  stored?: { href: string; filename: string; expires: string };
}) {
  const [index, setIndex] = useState(0);
  const [all, setAll] = useState(false);
  const json = JSON.stringify(bundles[index], null, 2);
  const shown = all || json.length <= MAX_SHOWN ? json : json.slice(0, MAX_SHOWN);

  const downloadFromMemory = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(bundles, null, 2)], { type: "application/json" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `generation-${id.slice(0, 8)}.json` });
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Result</CardTitle>
        <CardDescription>
          {stored
            ? `${bundles.length} bundle${bundles.length === 1 ? "" : "s"}. This is the stored file: download it any time until it is deleted ${stored.expires}.`
            : "Shown here because you used the instant response. It is not stored on the server, so download it now: a page reload clears it."}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {bundles.length > 1 && (
            <div className="flex max-h-24 flex-wrap gap-1 overflow-auto">
              {bundles.map((_, i) => (
                <Button key={i} size="xs" variant={i === index ? "secondary" : "ghost"} onClick={() => { setIndex(i); setAll(false); }}>
                  Bundle {i + 1}
                </Button>
              ))}
            </div>
          )}
          <div className="ml-auto flex gap-2">
            <Button size="sm" variant="outline" onClick={() => navigator.clipboard.writeText(json).then(() => toast.success("Copied"))}>
              <CopyIcon /> Copy bundle
            </Button>
            {stored ? (
              <a href={stored.href} download={stored.filename} className={buttonVariants({ size: "sm" })}>
                <DownloadIcon /> Download all ({stored.filename})
              </a>
            ) : (
              <Button size="sm" onClick={downloadFromMemory}>
                <DownloadIcon /> Download JSON
              </Button>
            )}
          </div>
        </div>
        <pre className="bg-muted max-h-[32rem] overflow-auto rounded-lg p-3 font-mono text-[11px] leading-relaxed">{shown}</pre>
        {!all && json.length > MAX_SHOWN && (
          <Button variant="link" className="w-fit" onClick={() => setAll(true)}>
            Showing the first {formatBytes(MAX_SHOWN)} of {formatBytes(json.length)} - show all
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function Detail({ job }: { job: JobResponse }) {
  const router = useRouter();
  const now = useNow();
  const { data: specialties } = useSpecialties();
  const del = useDeleteJob();
  const spec = job.resolved_spec as unknown as ResolvedSpec;
  const summary = job.summary as { patients?: number; bundles?: number; total_resources?: number; resources?: Record<string, number> } | null;
  const prov = (job.provenance ?? {}) as Record<string, unknown>;
  const inline = getInline(job.id);
  // The "View here + download" delivery stores one JSON file; show it (if it is a sensible size) next to the download.
  const jsonArtifact = job.status === "succeeded" ? job.artifacts.find((x) => x.filename.endsWith(".json") && x.size <= MAX_VIEW_BYTES) : undefined;
  const stored = useStoredResult(jsonArtifact?.download_url);
  const started = parseApiDate(job.started_at);
  const finished = parseApiDate(job.finished_at);
  const took = (prov.elapsed_seconds as number | undefined) ?? (started && finished ? (finished.getTime() - started.getTime()) / 1000 : undefined);
  const error = job.error as { code?: string; message?: string; details?: unknown[] } | null;
  const files = job.artifacts.reduce((n, a) => n + a.size, 0);

  const editAndRerun = () => {
    setPrefill(fromResolved(spec, specialties ?? {}));
    router.push("/");
  };

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link href="/jobs" className="text-muted-foreground hover:text-foreground mb-3 inline-flex items-center gap-1 text-sm">
          <ArrowLeftIcon className="size-3.5" /> All jobs
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-semibold tracking-tight">{jobTitle(job)}</h1>
              <JobStatusBadge status={job.status} />
            </div>
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1.5 font-mono text-xs"
              onClick={() => navigator.clipboard.writeText(job.id).then(() => toast.success("Job id copied"))}
            >
              {job.id} <CopyIcon className="size-3" />
            </button>
          </div>
          <div className="flex gap-2">
            {job.status === "succeeded" && job.artifacts.length > 0 && (
              <Link href={`/jobs/${job.id}/flow`} className={buttonVariants()}>
                <NetworkIcon /> View the flow
              </Link>
            )}
            <Button variant="outline" onClick={editAndRerun}><PencilIcon /> Edit &amp; re-run</Button>
            <Dialog>
              <DialogTrigger render={<Button variant="outline" aria-label="Delete this job"><Trash2Icon /></Button>} />
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Delete this job?</DialogTitle>
                  <DialogDescription>Its record and any downloadable files are removed. This cannot be undone.</DialogDescription>
                </DialogHeader>
                <DialogFooter>
                  <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                  <Button
                    variant="destructive"
                    disabled={del.isPending}
                    onClick={() => del.mutate(job.id, { onSuccess: () => { toast.success("Deleted"); router.push("/jobs"); }, onError: (e) => toast.error(e.message) })}
                  >
                    {del.isPending && <Loader2Icon className="animate-spin" />} Delete
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        </div>
      </div>

      {(job.status === "queued" || job.status === "running") && (
        <Alert>
          <Loader2Icon className="animate-spin" />
          <AlertTitle>{job.status === "queued" ? "Waiting for a free slot..." : "Generating..."}</AlertTitle>
          <AlertDescription>Real Synthea runs take 15 seconds or more; larger or rarer cohorts take minutes. This page updates by itself.</AlertDescription>
        </Alert>
      )}

      {job.status === "failed" && error && (
        <Alert variant="destructive">
          <TriangleAlertIcon />
          <AlertTitle>{error.message ?? "Generation failed"} <span className="font-mono text-xs font-normal">({error.code})</span></AlertTitle>
          {!!error.details?.length && (
            <AlertDescription>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 font-mono text-xs break-words">
                {error.details.slice(0, 10).map((d, i) => <li key={i}>{typeof d === "string" ? d : JSON.stringify(d)}</li>)}
              </ul>
            </AlertDescription>
          )}
        </Alert>
      )}

      {job.status === "expired" && (
        <Alert>
          <TriangleAlertIcon />
          <AlertTitle>The files were deleted after 72 hours</AlertTitle>
          <AlertDescription>The record below is kept. Use &quot;Edit &amp; re-run&quot; to generate the same data again (the seed is saved).</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardContent className="grid grid-cols-2 gap-5 sm:grid-cols-4">
          <Stat label="Took" value={formatDuration(took)} hint={finished ? `finished ${finished.toLocaleTimeString()}` : undefined} />
          <Stat label="Patients" value={formatNumber(summary?.patients ?? spec.cohort.count)} hint={summary ? `${summary.bundles} bundle${summary.bundles === 1 ? "" : "s"}` : "requested"} />
          <Stat label="Resources" value={formatNumber(summary?.total_resources)} />
          <Stat label="Files" value={job.artifacts.length ? formatBytes(files) : "-"} hint={job.artifacts.length ? `deleted ${timeUntil(parseApiDate(job.expires_at), now)}` : undefined} />
        </CardContent>
      </Card>

      {job.artifacts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Download</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {job.artifacts.map((a) => (
              <div key={a.id} className="flex items-center justify-between gap-3 rounded-lg border p-3">
                <div className="flex min-w-0 flex-col">
                  <span className="truncate font-medium">{a.filename}</span>
                  <span className="text-muted-foreground text-xs">{formatBytes(a.size)}</span>
                </div>
                <a href={downloadUrl(a.download_url)} download={a.filename} className={buttonVariants({ size: "sm" })}>
                  <DownloadIcon /> Download
                </a>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {inline && <ResultViewer id={job.id} bundles={inline} />}
      {!inline && jsonArtifact && stored.isPending && <Skeleton className="h-64" />}
      {!inline && jsonArtifact && stored.error && (
        <Alert variant="destructive">
          <TriangleAlertIcon />
          <AlertTitle>Could not show the result here</AlertTitle>
          <AlertDescription>{stored.error.message} You can still use the Download button above.</AlertDescription>
        </Alert>
      )}
      {!inline && jsonArtifact && stored.data && (
        <ResultViewer
          id={job.id}
          bundles={stored.data}
          stored={{ href: downloadUrl(jsonArtifact.download_url), filename: jsonArtifact.filename, expires: timeUntil(parseApiDate(job.expires_at), now) }}
        />
      )}
      {job.status === "succeeded" && !job.artifacts.length && !inline && (
        <Alert>
          <AlertTitle>This result was not stored</AlertTitle>
          <AlertDescription>
            It used the old instant response, which is shown once and never kept (a reload or a dropped connection loses it). Use
            &quot;Edit &amp; re-run&quot;: the form now delivers as &quot;View here + download&quot;, which is stored for 72 hours.
          </AlertDescription>
        </Alert>
      )}

      {summary?.resources && (
        <Card>
          <CardHeader><CardTitle className="text-base">What is in it</CardTitle></CardHeader>
          <CardContent><ResourceBars counts={summary.resources} /></CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-base">What was asked</CardTitle></CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[7rem_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Connector</dt><dd>{spec.connector}</dd>
              <dt className="text-muted-foreground">Patients</dt><dd>{spec.cohort.count}</dd>
              {spec.cohort.specialty && (<><dt className="text-muted-foreground">Specialty</dt><dd>{spec.cohort.specialty}</dd></>)}
              {!!spec.cohort.conditions?.length && (<><dt className="text-muted-foreground">Diseases</dt><dd className="font-mono text-xs break-all">{spec.cohort.conditions.join(", ")}</dd></>)}
              {!!spec.cohort.procedures?.length && (<><dt className="text-muted-foreground">Operations</dt><dd className="font-mono text-xs break-all">{spec.cohort.procedures.join(", ")}</dd></>)}
              {spec.cohort.age_range && (<><dt className="text-muted-foreground">Age</dt><dd>{spec.cohort.age_range[0]}-{spec.cohort.age_range[1]}</dd></>)}
              {spec.cohort.gender && (<><dt className="text-muted-foreground">Gender</dt><dd>{spec.cohort.gender}</dd></>)}
              <dt className="text-muted-foreground">Steps</dt>
              <dd>{spec.shape.map((s) => s.slicer.replace(/_/g, " ")).join(" → ") || "full record"}</dd>
              <dt className="text-muted-foreground">Delivery</dt><dd>{spec.sink.name}</dd>
            </dl>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-base">How it was made</CardTitle><CardDescription>Everything needed to reproduce it.</CardDescription></CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Seed</dt><dd className="font-mono">{String(prov.seed ?? spec.cohort.seed ?? "-")}</dd>
              {prov.retried_after_timeout === true && (
                <>
                  <dt className="text-muted-foreground">Retried</dt>
                  <dd className="text-xs">
                    Synthea stalled on that seed, so it was re-run with seed <span className="font-mono">{String(prov.seed_used)}</span> (the
                    same request always does this, so it stays reproducible).
                  </dd>
                </>
              )}
              {!!prov.synthea_version && (<><dt className="text-muted-foreground">Synthea</dt><dd className="font-mono text-xs break-all">{String(prov.synthea_version)}</dd></>)}
              {!!prov.image && (<><dt className="text-muted-foreground">Docker image</dt><dd className="font-mono text-xs">{String(prov.image)}</dd></>)}
              {!!prov.reference_date && (<><dt className="text-muted-foreground">Reference date</dt><dd className="font-mono">{String(prov.reference_date)}</dd></>)}
              {!!prov.end_date && (<><dt className="text-muted-foreground">End date</dt><dd className="font-mono">{String(prov.end_date)}</dd></>)}
              <dt className="text-muted-foreground">FHIR</dt><dd>{String(prov.fhir_version ?? "R4")}</dd>
            </dl>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export function JobDetail({ id }: { id: string }) {
  const { data, error, isPending } = useJob(id);
  if (isPending) return <div className="flex flex-col gap-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-28" /><Skeleton className="h-48" /></div>;
  if (error) {
    const notFound = error instanceof ApiError && error.status === 404;
    return (
      <Alert variant="destructive">
        <TriangleAlertIcon />
        <AlertTitle>{notFound ? "No such job" : "Could not load the job"}</AlertTitle>
        <AlertDescription>
          {notFound ? "It may have been deleted. " : `${error.message} `}
          <Link href="/jobs" className="underline underline-offset-4">Back to all jobs</Link>
        </AlertDescription>
      </Alert>
    );
  }
  return <Detail job={data} />;
}
