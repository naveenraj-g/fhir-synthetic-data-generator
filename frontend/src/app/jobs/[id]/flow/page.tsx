import type { Metadata } from "next";
import { Suspense } from "react";
import { FlowView } from "@/components/flow/flow-view";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Flow of the data" };

export default function FlowPage({ params }: PageProps<"/jobs/[id]/flow">) {
  // params is a runtime value, so it is read inside a Suspense boundary (the page shell stays static).
  return (
    <Suspense fallback={<Skeleton className="h-64" />}>
      {params.then(({ id }) => (
        <FlowView id={id} />
      ))}
    </Suspense>
  );
}
