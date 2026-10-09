"use client";

import { CheckIcon, ChevronsUpDownIcon, Loader2Icon, XIcon } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { usePlaces } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";
import { useTermsConnector } from "./target-picker";

/**
 * Pick a state or a city from the list Synthea itself accepts (it matches names exactly and fails on anything else).
 * Pass `state` to list that state's cities instead of the states.
 */
export function PlacePicker({
  id,
  value,
  onChange,
  state,
  placeholder,
  connector: preferred,
  disabled,
}: {
  id?: string;
  value: string;
  onChange: (next: string) => void;
  state?: string;
  placeholder: string;
  connector?: string;
  disabled?: boolean;
}) {
  const connector = useTermsConnector(preferred);
  const [open, setOpen] = useState(false);
  const { data, isPending, error } = usePlaces(connector, state);
  const items = data?.items ?? [];

  return (
    <div className="flex gap-1.5">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger
          render={
            <Button
              id={id}
              type="button"
              variant="outline"
              role="combobox"
              aria-expanded={open}
              disabled={disabled || !connector}
              className="min-w-0 flex-1 justify-between font-normal"
            >
              <span className={cn("truncate", !value && "text-muted-foreground")}>{value || placeholder}</span>
              <ChevronsUpDownIcon className="text-muted-foreground size-4 shrink-0" />
            </Button>
          }
        />
        <PopoverContent align="start" className="w-64 max-w-[calc(100vw-2rem)] p-0">
          <Command>
            <CommandInput placeholder={state ? `Search cities in ${state}...` : "Search states..."} />
            <CommandList className="max-h-64">
              {isPending && (
                <div className="text-muted-foreground flex items-center gap-2 p-3 text-xs">
                  <Loader2Icon className="size-3.5 animate-spin" />
                  Loading (first time only)...
                </div>
              )}
              {error && <div className="text-destructive p-3 text-xs">{error.message}</div>}
              {data && <CommandEmpty>No match.</CommandEmpty>}
              <CommandGroup>
                {items.map((name) => (
                  <CommandItem
                    key={name}
                    value={name}
                    onSelect={() => {
                      onChange(name);
                      setOpen(false);
                    }}
                  >
                    {name}
                    {name === value && <CheckIcon className="ml-auto size-4" />}
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      {value && (
        <Button type="button" variant="ghost" size="icon" aria-label={`Clear ${placeholder.toLowerCase()}`} onClick={() => onChange("")}>
          <XIcon />
        </Button>
      )}
    </div>
  );
}
