"use client";

import { ArrowDownIcon, ArrowUpIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { useResourceGroups, useSlicers } from "@/lib/api/hooks";
import { matchQuickShape, newStepId, QUICK_SHAPES, stepsFromQuick, type ShapeStepState } from "@/lib/builder-state";
import { cn } from "@/lib/utils";
import { SimpleSelect } from "./inputs";
import { ResourcePicker } from "./resource-picker";
import { SchemaForm, type ObjectSchema } from "./schema-form";
import { Section, type SectionProps } from "./section";

const prettySlicer = (name: string) => name.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

export function ShapeSection({ state, update }: SectionProps) {
  const { data: slicers, isPending } = useSlicers();
  const { data: groups } = useResourceGroups();
  const ctx = { groups: groups ?? {}, connector: state.connector || undefined };
  const bySlicer = new Map((slicers ?? []).map((s) => [s.name, s]));

  const setShape = (shape: ShapeStepState[]) => update({ shape });
  const patchStep = (id: string, patch: Partial<ShapeStepState>) =>
    setShape(state.shape.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  const move = (i: number, dir: -1 | 1) => {
    const next = [...state.shape];
    const j = i + dir;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    setShape(next);
  };

  const activeQuick = matchQuickShape(state.shape);

  return (
    <Section
      step={3}
      title="What data"
      description="Cut exactly the slice you need from each patient's record. Steps run in order; each one works on the previous one's output."
    >
      <div className="flex flex-col gap-2">
        <span className="text-sm font-medium">Quick shapes</span>
        <div className="flex flex-wrap gap-1.5">
          {QUICK_SHAPES.map((q) => (
            <button
              key={q.id}
              type="button"
              title={q.hint}
              aria-pressed={activeQuick?.id === q.id}
              onClick={() => setShape(stepsFromQuick(q))}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                activeQuick?.id === q.id ? "border-primary bg-primary text-primary-foreground" : "bg-background hover:bg-muted",
              )}
            >
              {q.label}
            </button>
          ))}
        </div>
        <p className="text-muted-foreground text-xs">
          {activeQuick?.hint ?? (state.shape.length ? "Custom steps below." : "No steps: each patient's full record is returned.")}
        </p>
      </div>

      <ResourcePicker shape={state.shape} groups={groups ?? {}} onChange={setShape} />

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-0.5">
          <span className="text-sm font-medium">Steps</span>
          <span className="text-muted-foreground text-xs">
            What the choices above (and the quick shapes) turn into. Edit or add steps here for finer control: one visit, a date window, a condition&apos;s story, a limit.
          </span>
        </div>
        {isPending && <Skeleton className="h-24 rounded-lg" />}
        {state.shape.map((step, i) => {
          const def = bySlicer.get(step.slicer);
          return (
            <Card key={step.id} size="sm" className="bg-muted/30">
              <CardContent className="flex flex-col gap-3">
                <div className="flex items-center gap-2">
                  <span className="bg-background text-muted-foreground grid size-6 shrink-0 place-items-center rounded-full border text-xs font-semibold">
                    {i + 1}
                  </span>
                  <SimpleSelect
                    className="max-w-xs"
                    value={step.slicer}
                    onChange={(slicer) => patchStep(step.id, { slicer, params: {} })}
                    options={(slicers ?? []).map((s) => ({ value: s.name, label: prettySlicer(s.name) }))}
                  />
                  <div className="ml-auto flex items-center">
                    <Button type="button" variant="ghost" size="icon-sm" aria-label="Move step up" disabled={i === 0} onClick={() => move(i, -1)}>
                      <ArrowUpIcon />
                    </Button>
                    <Button type="button" variant="ghost" size="icon-sm" aria-label="Move step down" disabled={i === state.shape.length - 1} onClick={() => move(i, 1)}>
                      <ArrowDownIcon />
                    </Button>
                    <Button type="button" variant="ghost" size="icon-sm" aria-label="Remove step" onClick={() => setShape(state.shape.filter((s) => s.id !== step.id))}>
                      <Trash2Icon />
                    </Button>
                  </div>
                </div>
                {def?.description && <p className="text-muted-foreground text-xs">{def.description}</p>}
                <SchemaForm
                  idPrefix={step.id}
                  schema={def?.params_schema as ObjectSchema | null | undefined}
                  value={step.params}
                  onChange={(params) => patchStep(step.id, { params })}
                  ctx={ctx}
                />
              </CardContent>
            </Card>
          );
        })}

        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button type="button" variant="outline" className="w-fit">
                <PlusIcon /> Add a step
              </Button>
            }
          />
          <DropdownMenuContent align="start" className="w-80">
            {(slicers ?? []).map((s) => (
              <DropdownMenuItem
                key={s.name}
                className="flex-col items-start gap-0.5"
                onClick={() => setShape([...state.shape, { id: newStepId(), slicer: s.name, params: {} }])}
              >
                <span className="font-medium">{prettySlicer(s.name)}</span>
                <span className="text-muted-foreground line-clamp-2 text-xs">{s.description}</span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </Section>
  );
}
