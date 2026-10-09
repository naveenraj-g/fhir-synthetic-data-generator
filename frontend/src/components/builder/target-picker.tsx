"use client";

import { Loader2Icon, PlusIcon, XIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useConnectors, useTerms } from "@/lib/api/hooks";
import type { TermInfo } from "@/lib/api/client";

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** The connector whose term index we search: the first enabled Synthea one (the only connector that has one). */
export function useTermsConnector(preferred?: string) {
  const { data } = useConnectors();
  return useMemo(() => {
    const enabled = (data ?? []).filter((c) => c.enabled && c.type === "synthea");
    return enabled.find((c) => c.name === preferred)?.name ?? enabled[0]?.name;
  }, [data, preferred]);
}

const MANUAL_CODE = /^(?:[A-Za-z][A-Za-z0-9_-]*:[A-Za-z0-9][A-Za-z0-9.-]*|\d+)$/;
const codeOf = (reference: string) => reference.split(":").pop() ?? reference;

/** Human label for a code like "SNOMED-CT:44054006", looked up in the term index (cached). */
export function useTermLabel(connector: string | undefined, reference: string) {
  const code = codeOf(reference);
  const { data } = useTerms(connector, code, undefined, 10);
  return data?.items.find((t) => t.reference === reference || t.code === code)?.display;
}

/** A code shown with its human name; pass `onRemove` to make it removable. */
export function TargetChip({ connector, reference, onRemove }: { connector?: string; reference: string; onRemove?: () => void }) {
  const label = useTermLabel(connector, reference);
  return (
    <Badge variant="secondary" className="h-auto max-w-full gap-1 py-1 pr-1 whitespace-normal" title={reference}>
      <span className="min-w-0 text-left">
        {label ? label.replace(/\s*\((?:disorder|procedure|finding|situation)\)\s*$/, "") : reference}
        {label && <span className="text-muted-foreground ml-1 font-mono text-[10px]">{codeOf(reference)}</span>}
      </span>
      {onRemove && (
        <button
          type="button"
          aria-label={`Remove ${label ?? reference}`}
          className="hover:bg-foreground/10 shrink-0 rounded-full p-0.5"
          onClick={onRemove}
        >
          <XIcon className="size-3" />
        </button>
      )}
    </Badge>
  );
}

export function TargetPicker({
  value,
  onChange,
  kind,
  preferredConnector,
  addLabel,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  kind: "condition" | "procedure" | "medication";
  preferredConnector?: string;
  addLabel?: string;
}) {
  const connector = useTermsConnector(preferredConnector);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const debounced = useDebounced(q, 250);
  const { data, isFetching, error } = useTerms(connector, debounced, kind, 30);

  const add = (reference: string) => {
    if (!value.includes(reference)) onChange([...value, reference]);
    setQ("");
  };
  const manual = q.trim();
  const canAddManually = MANUAL_CODE.test(manual) && !value.includes(manual);

  return (
    <div className="flex flex-col gap-2">
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {value.map((ref) => (
            <TargetChip key={ref} connector={connector} reference={ref} onRemove={() => onChange(value.filter((v) => v !== ref))} />
          ))}
        </div>
      )}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger
          render={
            <Button type="button" variant="outline" size="sm" className="w-fit" disabled={!connector}>
              <PlusIcon />
              {addLabel ?? `Add ${kind}`}
            </Button>
          }
        />
        <PopoverContent align="start" className="w-[26rem] max-w-[calc(100vw-2rem)] p-0">
          <Command shouldFilter={false}>
            <CommandInput autoFocus placeholder={`Search ${kind}s: "reflux", "colonoscopy"...`} value={q} onValueChange={setQ} />
            <CommandList className="max-h-72">
              {isFetching && !data && (
                <div className="text-muted-foreground flex items-center gap-2 p-3 text-xs">
                  <Loader2Icon className="size-3.5 animate-spin" />
                  Building the code index (first time only, a few seconds)...
                </div>
              )}
              {error && <div className="text-destructive p-3 text-xs">{error.message}</div>}
              {data && data.items.length === 0 && !canAddManually && <CommandEmpty>No match. Try other words.</CommandEmpty>}
              {canAddManually && (
                <CommandGroup heading="Use this code">
                  <CommandItem value={`manual-${manual}`} onSelect={() => add(manual)}>
                    <span className="font-mono text-xs">{manual}</span>
                  </CommandItem>
                </CommandGroup>
              )}
              {data && data.items.length > 0 && (
                <CommandGroup heading={`${data.total.toLocaleString()} match${data.total === 1 ? "" : "es"}${data.total > data.returned ? ` (showing ${data.returned})` : ""}`}>
                  {data.items.map((t: TermInfo) => (
                    <CommandItem key={t.reference} value={t.reference} onSelect={() => add(t.reference)} data-checked={value.includes(t.reference)}>
                      <div className="flex min-w-0 flex-col">
                        <span className="truncate">{t.display}</span>
                        <span className="text-muted-foreground truncate font-mono text-[10px]">{t.reference}</span>
                      </div>
                    </CommandItem>
                  ))}
                </CommandGroup>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      {!connector && <p className="text-muted-foreground text-xs">Searching codes needs the Synthea connector to be enabled.</p>}
    </div>
  );
}
