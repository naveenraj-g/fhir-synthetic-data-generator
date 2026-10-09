"use client";

import { XIcon } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

/** Free-text list: type a value, press Enter or comma. */
export function ChipInput({
  value,
  onChange,
  placeholder,
  suggestions,
  id,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  suggestions?: string[];
  id?: string;
}) {
  const [draft, setDraft] = useState("");
  const listId = suggestions ? `${id ?? "chips"}-suggestions` : undefined;

  const commit = (raw: string) => {
    const items = raw.split(",").map((s) => s.trim()).filter(Boolean);
    if (!items.length) return;
    onChange([...value, ...items.filter((i) => !value.includes(i))]);
    setDraft("");
  };

  return (
    <div className="flex flex-col gap-2">
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {value.map((v) => (
            <Badge key={v} variant="secondary" className="gap-1 pr-1">
              {v}
              <button
                type="button"
                aria-label={`Remove ${v}`}
                className="hover:bg-foreground/10 rounded-full p-0.5"
                onClick={() => onChange(value.filter((x) => x !== v))}
              >
                <XIcon className="size-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
      <Input
        id={id}
        value={draft}
        list={listId}
        placeholder={placeholder ?? "Type and press Enter"}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            commit(draft);
          } else if (e.key === "Backspace" && !draft && value.length) {
            onChange(value.slice(0, -1));
          }
        }}
        onBlur={() => commit(draft)}
      />
      {suggestions && (
        <datalist id={listId}>
          {suggestions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      )}
    </div>
  );
}

export interface Choice {
  value: string;
  label?: string;
  hint?: string;
}

/** Pick any number of options from a fixed list (rendered as toggle chips). */
export function ChoiceChips({
  options,
  value,
  onChange,
  single,
}: {
  options: Choice[];
  value: string[];
  onChange: (next: string[]) => void;
  /** When true, at most one can be selected. */
  single?: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-1.5" role="group">
      {options.map((o) => {
        const on = value.includes(o.value);
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={on}
            title={o.hint}
            onClick={() => {
              if (single) onChange(on ? [] : [o.value]);
              else onChange(on ? value.filter((v) => v !== o.value) : [...value, o.value]);
            }}
            className={cn(
              "rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
              "focus-visible:ring-ring/50 outline-none focus-visible:ring-3",
              on
                ? "border-primary bg-primary text-primary-foreground"
                : "bg-background hover:bg-muted text-foreground",
            )}
          >
            {o.label ?? o.value}
          </button>
        );
      })}
    </div>
  );
}

/** Label + optional hint above a control, with consistent spacing. */
export function Field({
  label,
  htmlFor,
  hint,
  required,
  children,
  className,
}: {
  label: string;
  htmlFor?: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={htmlFor} className="text-sm leading-none font-medium">
        {label}
        {required && <span className="text-destructive ml-0.5">*</span>}
      </label>
      {children}
      {hint && <p className="text-muted-foreground text-xs leading-snug">{hint}</p>}
    </div>
  );
}

export interface SelectOption {
  value: string;
  label: string;
}

/** shadcn Select with a flat options list; passes `items` so the trigger shows the label, not the raw value. */
export function SimpleSelect({
  value,
  onChange,
  options,
  placeholder,
  className,
  id,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  className?: string;
  id?: string;
  disabled?: boolean;
}) {
  return (
    <Select items={options} value={value} onValueChange={(v) => onChange(String(v ?? ""))} disabled={disabled}>
      <SelectTrigger id={id} className={cn("w-full", className)}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
