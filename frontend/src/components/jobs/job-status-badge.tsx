import { CheckCircle2Icon, ClockIcon, HourglassIcon, Loader2Icon, XCircleIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { JobStatus } from "@/lib/api/client";
import { cn } from "@/lib/utils";

const STATUS: Record<JobStatus, { label: string; icon: typeof ClockIcon; className: string; spin?: boolean }> = {
  queued: { label: "Queued", icon: ClockIcon, className: "bg-muted text-muted-foreground" },
  running: { label: "Running", icon: Loader2Icon, className: "bg-primary/15 text-primary", spin: true },
  succeeded: { label: "Succeeded", icon: CheckCircle2Icon, className: "bg-success/15 text-success" },
  failed: { label: "Failed", icon: XCircleIcon, className: "bg-destructive/15 text-destructive" },
  expired: { label: "Files expired", icon: HourglassIcon, className: "bg-warning/20 text-warning-foreground dark:text-warning" },
};

export function JobStatusBadge({ status, className }: { status: JobStatus; className?: string }) {
  const s = STATUS[status];
  const Icon = s.icon;
  return (
    <Badge variant="secondary" className={cn("gap-1 border-transparent", s.className, className)}>
      <Icon className={cn("size-3", s.spin && "animate-spin")} />
      {s.label}
    </Badge>
  );
}
