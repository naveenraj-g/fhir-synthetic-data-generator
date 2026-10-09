"use client";

import { useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { ENCOUNTER_CLASSES, OBSERVATION_CATEGORIES, type StepParams } from "@/lib/builder-state";
import { ChipInput, ChoiceChips, Field, SimpleSelect } from "./inputs";
import { TargetPicker } from "./target-picker";

/** The subset of JSON Schema (as emitted by pydantic) that slicer/sink parameters use. */
interface Prop {
  type?: string;
  enum?: unknown[];
  items?: Prop;
  format?: string;
  default?: unknown;
  description?: string;
  title?: string;
  minimum?: number;
  maximum?: number;
  anyOf?: Prop[];
}
export interface ObjectSchema {
  properties?: Record<string, Prop>;
  required?: string[];
}

/** `X | None` arrives as anyOf [X, {type: null}]: unwrap to X, keeping the outer description/default. */
function unwrap(p: Prop): Prop {
  if (!p.anyOf) return p;
  const inner = p.anyOf.find((b) => b.type !== "null") ?? {};
  return { ...inner, description: p.description ?? inner.description, default: p.default, title: p.title };
}

export interface FormContext {
  /** Resource groups from the API (name -> resource types). */
  groups: Record<string, string[]>;
  connector?: string;
}

function JsonField({ value, onChange, id }: { value: unknown; onChange: (v: unknown) => void; id: string }) {
  const [text, setText] = useState(value === undefined ? "" : JSON.stringify(value, null, 2));
  const [bad, setBad] = useState(false);
  return (
    <Textarea
      id={id}
      value={text}
      aria-invalid={bad}
      className="font-mono text-xs"
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        if (!text.trim()) return onChange(undefined);
        try {
          onChange(JSON.parse(text));
          setBad(false);
        } catch {
          setBad(true);
        }
      }}
    />
  );
}

function Control({
  name,
  prop,
  value,
  onChange,
  ctx,
  id,
}: {
  name: string;
  prop: Prop;
  value: unknown;
  onChange: (v: unknown) => void;
  ctx: FormContext;
  id: string;
}) {
  const allTypes = useMemo(() => [...new Set(Object.values(ctx.groups).flat())].sort(), [ctx.groups]);
  const list = Array.isArray(value) ? (value as string[]) : [];

  // Known parameters get purpose-built pickers; everything else is derived from the schema.
  switch (name) {
    case "groups":
      return (
        <ChoiceChips
          value={list}
          onChange={onChange}
          options={Object.entries(ctx.groups).map(([g, types]) => ({ value: g, hint: types.join(", ") }))}
        />
      );
    case "encounter_class":
      return <ChoiceChips value={list} onChange={onChange} options={ENCOUNTER_CLASSES} />;
    case "types":
    case "exclude_types":
    case "drop_types":
      return <ChipInput id={id} value={list} onChange={onChange} suggestions={allTypes} placeholder="Resource type, e.g. Observation" />;
    case "categories":
      return <ChipInput id={id} value={list} onChange={onChange} suggestions={OBSERVATION_CATEGORIES} placeholder="e.g. vital-signs" />;
    case "with_procedure":
      return <TargetPicker kind="procedure" value={list} onChange={onChange} preferredConnector={ctx.connector} addLabel="Add operation" />;
    case "with_condition":
    case "conditions":
      return <TargetPicker kind="condition" value={list} onChange={onChange} preferredConnector={ctx.connector} addLabel="Add condition" />;
    case "resource_type":
      return (
        <SimpleSelect
          id={id}
          value={String(value ?? "")}
          onChange={(v) => onChange(v || undefined)}
          options={allTypes.map((t) => ({ value: t, label: t }))}
          placeholder="Choose a resource type"
        />
      );
  }

  if (prop.enum) {
    return (
      <SimpleSelect
        id={id}
        value={String(value ?? prop.default ?? "")}
        onChange={onChange}
        options={prop.enum.map((v) => ({ value: String(v), label: String(v) }))}
      />
    );
  }
  switch (prop.type) {
    case "boolean":
      return (
        <Switch
          id={id}
          checked={Boolean(value ?? prop.default ?? false)}
          onCheckedChange={(c) => onChange(c)}
        />
      );
    case "integer":
    case "number":
      return (
        <Input
          id={id}
          type="number"
          min={prop.minimum}
          max={prop.maximum}
          value={value === undefined || value === null ? "" : String(value)}
          placeholder={prop.default !== undefined && prop.default !== null ? `default ${prop.default}` : undefined}
          onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
        />
      );
    case "string":
      return (
        <Input
          id={id}
          type={prop.format === "date" ? "date" : "text"}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value)}
        />
      );
    case "array":
      if (!prop.items || prop.items.type === "string") {
        return <ChipInput id={id} value={list} onChange={onChange} />;
      }
  }
  return <JsonField id={id} value={value} onChange={onChange} />;
}

/** Renders a form for any `{properties, required}` JSON schema; booleans sit inline, the rest stack. */
export function SchemaForm({
  schema,
  value,
  onChange,
  ctx,
  idPrefix,
}: {
  schema: ObjectSchema | null | undefined;
  value: StepParams;
  onChange: (next: StepParams) => void;
  ctx: FormContext;
  idPrefix: string;
}) {
  const entries = Object.entries(schema?.properties ?? {});
  if (entries.length === 0) {
    return <p className="text-muted-foreground text-sm">This step has no options.</p>;
  }
  const set = (name: string, v: unknown) => {
    const next = { ...value };
    if (v === undefined || v === "") delete next[name];
    else next[name] = v;
    onChange(next);
  };

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {entries.map(([name, raw]) => {
        const prop = unwrap(raw);
        const id = `${idPrefix}-${name}`;
        const wide = prop.type === "array" || name === "with_procedure" || name === "with_condition" || name === "groups";
        const isBool = prop.type === "boolean" && !prop.enum;
        const label = (raw.title ?? name).replace(/_/g, " ");
        const control = <Control name={name} prop={prop} value={value[name]} onChange={(v) => set(name, v)} ctx={ctx} id={id} />;

        if (isBool) {
          return (
            <div key={name} className="flex items-start justify-between gap-3 rounded-lg border p-3 sm:col-span-2">
              <div className="flex flex-col gap-1">
                <label htmlFor={id} className="text-sm leading-none font-medium capitalize">
                  {label}
                </label>
                {prop.description && <p className="text-muted-foreground text-xs leading-snug">{prop.description}</p>}
              </div>
              {control}
            </div>
          );
        }
        return (
          <Field
            key={name}
            label={label.charAt(0).toUpperCase() + label.slice(1)}
            htmlFor={id}
            hint={prop.description}
            required={schema?.required?.includes(name)}
            className={wide ? "sm:col-span-2" : undefined}
          >
            {control}
          </Field>
        );
      })}
    </div>
  );
}
