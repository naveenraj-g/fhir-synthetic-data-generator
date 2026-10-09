"use client";

import { ChevronLeftIcon, ChevronRightIcon, SparklesIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { JobResponse } from "@/lib/api/client";
import { matchQuickShape } from "@/lib/builder-state";
import { useJobs } from "@/lib/api/hooks";
import { formatBytes, formatDuration, formatNumber, parseApiDate, shortId, timeAgo, timeUntil } from "@/lib/format";
import { useNow } from "@/lib/use-now";
import { JobStatusBadge } from "./job-status-badge";

const PAGE = 15;
const FILTERS = [
  { value: "all", label: "All" },
  { value: "running", label: "Running" },
  { value: "succeeded", label: "Succeeded" },
  { value: "failed", label: "Failed" },
  { value: "expired", label: "Expired" },
];

const capitalize = (s: string) => s.replace(/[-_]/g, " ").replace(/^./, (c) => c.toUpperCase());

/** A plain-language name: the template's name, or what was asked ("Vital signs · gastroenterology"). */
export function jobTitle(job: JobResponse): string {
  if (job.preset) return capitalize(job.preset);
  const spec = job.resolved_spec as {
    cohort?: { specialty?: string; conditions?: string[]; procedures?: string[] };
    shape?: { slicer: string; params?: Record<string, unknown> }[];
  };
  const c = spec.cohort;
  const scope = matchQuickShape(spec.shape ?? [])?.label ?? ((spec.shape ?? []).length ? (spec.shape ?? []).map((s) => capitalize(s.slicer)).join(" + ") : "Everything");
  const target = c?.specialty
    ? capitalize(c.specialty)
    : c?.procedures?.length
      ? "operation cohort"
      : c?.conditions?.length
        ? "disease cohort"
        : "";
  return target ? `${scope} · ${target}` : scope;
}

function patients(job: JobResponse): number | undefined {
  return (job.resolved_spec as { cohort?: { count?: number } }).cohort?.count;
}

export function JobsList() {
  const [filter, setFilter] = useState("all");
  const [page, setPage] = useState(0);
  const { data, isPending, error } = useJobs(filter === "all" ? undefined : filter, PAGE, page * PAGE);
  const now = useNow();

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Jobs</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Every generation, with how long it took. Only this metadata is stored; generated files are deleted after 72 hours.
          </p>
        </div>
        <Link href="/" className={buttonVariants()}>
          <SparklesIcon /> New generation
        </Link>
      </div>

      <Tabs value={filter} onValueChange={(v) => { setFilter(String(v)); setPage(0); }}>
        <TabsList>
          {FILTERS.map((f) => <TabsTrigger key={f.value} value={f.value}>{f.label}</TabsTrigger>)}
        </TabsList>
      </Tabs>

      {error && (
        <Alert variant="destructive">
          <AlertTitle>Could not load jobs</AlertTitle>
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      )}

      <Card className="overflow-hidden p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Status</TableHead>
              <TableHead>Request</TableHead>
              <TableHead className="hidden md:table-cell">Started</TableHead>
              <TableHead className="hidden sm:table-cell">Took</TableHead>
              <TableHead className="hidden lg:table-cell">Result</TableHead>
              <TableHead className="hidden lg:table-cell">Files</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isPending && Array.from({ length: 5 }).map((_, i) => (
              <TableRow key={i}><TableCell colSpan={6}><Skeleton className="h-6 w-full" /></TableCell></TableRow>
            ))}
            {data?.data.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-muted-foreground py-10 text-center">
                  Nothing here yet. <Link href="/" className="text-primary underline underline-offset-4">Generate some data</Link>.
                </TableCell>
              </TableRow>
            )}
            {data?.data.map((job) => {
              const started = parseApiDate(job.started_at ?? job.created_at);
              const took = (job.provenance as { elapsed_seconds?: number } | null)?.elapsed_seconds;
              const files = job.artifacts.reduce((n, a) => n + a.size, 0);
              const summary = job.summary as { patients?: number; total_resources?: number } | null;
              return (
                <TableRow key={job.id} className="relative">
                  <TableCell><JobStatusBadge status={job.status} /></TableCell>
                  <TableCell>
                    <Link href={`/jobs/${job.id}`} className="font-medium after:absolute after:inset-0 hover:underline">
                      {jobTitle(job)}
                    </Link>
                    <div className="text-muted-foreground text-xs">
                      {patients(job)} patient{patients(job) === 1 ? "" : "s"} · {job.connector} · {(job.resolved_spec as { sink?: { name?: string } }).sink?.name} · <span className="font-mono">{shortId(job.id)}</span>
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground hidden md:table-cell">{timeAgo(started, now)}</TableCell>
                  <TableCell className="hidden sm:table-cell">{formatDuration(took)}</TableCell>
                  <TableCell className="hidden lg:table-cell">
                    {summary ? `${formatNumber(summary.total_resources)} resources` : job.status === "failed" ? <span className="text-destructive text-xs">{(job.error as { code?: string } | null)?.code}</span> : "-"}
                  </TableCell>
                  <TableCell className="hidden lg:table-cell">
                    {job.artifacts.length ? (
                      <span>{formatBytes(files)} <span className="text-muted-foreground text-xs">· deleted {timeUntil(parseApiDate(job.expires_at), now)}</span></span>
                    ) : "-"}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Card>

      {data && data.total > PAGE && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">
            {page * PAGE + 1}-{Math.min((page + 1) * PAGE, data.total)} of {data.total}
          </span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}><ChevronLeftIcon /> Previous</Button>
            <Button variant="outline" size="sm" disabled={(page + 1) * PAGE >= data.total} onClick={() => setPage((p) => p + 1)}>Next <ChevronRightIcon /></Button>
          </div>
        </div>
      )}
    </div>
  );
}
