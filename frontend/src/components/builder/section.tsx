import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** A numbered step of the builder: "1 Start from", "2 Who", ... */
export function Section({
  step,
  title,
  description,
  action,
  children,
}: {
  step: number;
  title: string;
  description?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="bg-primary/10 text-primary grid size-7 shrink-0 place-items-center rounded-full text-sm font-semibold">
              {step}
            </span>
            <div className="flex flex-col gap-1">
              <CardTitle className="text-base">{title}</CardTitle>
              {description && <CardDescription>{description}</CardDescription>}
            </div>
          </div>
          {action}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">{children}</CardContent>
    </Card>
  );
}

export type SectionProps = {
  state: import("@/lib/builder-state").BuilderState;
  update: (patch: Partial<import("@/lib/builder-state").BuilderState>) => void;
};
