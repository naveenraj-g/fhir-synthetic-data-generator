import type { Metadata } from "next";
import { Suspense } from "react";
import { JobDetail } from "@/components/jobs/job-detail";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Job" };

export default function JobPage({ params }: PageProps<"/jobs/[id]">) {
  // params is a runtime value, so it is read inside a Suspense boundary (the page shell stays static).
  return (
    <Suspense fallback={<Skeleton className="h-64" />}>
      {params.then(({ id }) => (
        <JobDetail id={id} />
      ))}
    </Suspense>
  );
}
