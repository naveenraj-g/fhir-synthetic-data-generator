"use client";

import { CopyIcon, Loader2Icon, SearchIcon, SparklesIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { ChoiceChips } from "@/components/builder/inputs";
import { useDebounced, useTermsConnector } from "@/components/builder/target-picker";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useTerms } from "@/lib/api/hooks";
import { INITIAL_STATE } from "@/lib/builder-state";
import { setPrefill } from "@/lib/prefill";

const KINDS = [
  { value: "condition", label: "Diseases" },
  { value: "procedure", label: "Operations" },
  { value: "medication", label: "Medications" },
  { value: "observation", label: "Observations" },
  { value: "allergy", label: "Allergies" },
  { value: "immunization", label: "Immunizations" },
  { value: "diagnostic_report", label: "Reports" },
];

export function Explorer() {
  const router = useRouter();
  const connector = useTermsConnector();
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<string[]>([]);
  const debounced = useDebounced(q, 250);
  const { data, isFetching, error } = useTerms(connector, debounced, kind[0], 50);

  const openInGenerator = (reference: string, kindOfTerm: string) => {
    setPrefill({ ...INITIAL_STATE, [kindOfTerm === "procedure" ? "procedures" : "conditions"]: [reference] });
    router.push("/");
  };

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Find codes</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Everything the generator knows how to produce, searchable by words. Use a disease or operation to target patients.
        </p>
      </div>

      <div className="flex flex-col gap-3">
        <div className="relative max-w-xl">
          <SearchIcon className="text-muted-foreground absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
          <Input
            autoFocus
            className="pl-8"
            placeholder='Try "colonoscopy", "reflux", "diabetes", "appendix"...'
            value={q}
            onChange={(e) => setQ(e.target.value)}
            aria-label="Search terms"
          />
        </div>
        <ChoiceChips single options={KINDS} value={kind} onChange={setKind} />
      </div>

      {!connector && (
        <Alert>
          <AlertTitle>No searchable connector</AlertTitle>
          <AlertDescription>The Synthea connector is not enabled in the backend configuration.</AlertDescription>
        </Alert>
      )}
      {error && (
        <Alert variant="destructive">
          <AlertTitle>Search failed</AlertTitle>
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      )}

      <div className="text-muted-foreground flex items-center gap-2 text-sm" aria-live="polite">
        {isFetching && <Loader2Icon className="size-3.5 animate-spin" />}
        {data
          ? `${data.total.toLocaleString()} match${data.total === 1 ? "" : "es"}${data.total > data.returned ? `, showing the first ${data.returned}` : ""}`
          : isFetching
            ? "Building the code index (first time only, a few seconds)..."
            : ""}
      </div>

      <Card className="overflow-hidden p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead className="hidden sm:table-cell">Kind</TableHead>
              <TableHead>Code</TableHead>
              <TableHead className="hidden lg:table-cell">Appears in</TableHead>
              <TableHead className="w-24"><span className="sr-only">Actions</span></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.items.length === 0 && (
              <TableRow><TableCell colSpan={5} className="text-muted-foreground py-10 text-center">No match. Try different words.</TableCell></TableRow>
            )}
            {data?.items.map((t) => (
              <TableRow key={`${t.kind}-${t.reference}`}>
                <TableCell className="max-w-md font-medium whitespace-normal">{t.display}</TableCell>
                <TableCell className="hidden sm:table-cell"><Badge variant="outline">{t.kind.replace(/_/g, " ")}</Badge></TableCell>
                <TableCell className="font-mono text-xs">{t.reference}</TableCell>
                <TableCell className="text-muted-foreground hidden max-w-xs truncate text-xs lg:table-cell" title={t.modules.join(", ")}>
                  {t.modules.slice(0, 2).join(", ")}{t.modules.length > 2 ? ` +${t.modules.length - 2}` : ""}
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-1">
                    <Button variant="ghost" size="icon-sm" aria-label={`Copy ${t.reference}`} onClick={() => navigator.clipboard.writeText(t.reference).then(() => toast.success("Copied"))}>
                      <CopyIcon />
                    </Button>
                    {(t.kind === "condition" || t.kind === "procedure") && (
                      <Button variant="ghost" size="icon-sm" aria-label="Use in the generator" title="Use in the generator" onClick={() => openInGenerator(t.reference, t.kind)}>
                        <SparklesIcon />
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
