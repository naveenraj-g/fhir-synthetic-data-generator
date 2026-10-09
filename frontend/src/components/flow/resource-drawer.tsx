"use client";

import { CopyIcon, XIcon } from "lucide-react";
import { useMemo } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { describe, neighbours, type ParsedBundle, type Resource } from "@/lib/fhir-graph";
import { typeColor } from "./type-style";

type Json = Record<string, unknown>;
const isObject = (v: unknown): v is Json => typeof v === "object" && v !== null && !Array.isArray(v);
const isPrimitive = (v: unknown) => v === null || ["string", "number", "boolean"].includes(typeof v);

interface Ctx {
  parsed: ParsedBundle;
  open: (id: string) => void;
}

/** A name for a resource id, for link labels. */
function label(parsed: ParsedBundle, id: string): string {
  const res = parsed.resources.get(id);
  return res ? `${res.resourceType}: ${describe(res).title}` : id;
}

function LinkButton({ id, ctx, children }: { id: string; ctx: Ctx; children?: React.ReactNode }) {
  return (
    <button type="button" className="text-primary text-left underline-offset-2 hover:underline" onClick={() => ctx.open(id)}>
      {children ?? label(ctx.parsed, id)}
    </button>
  );
}

/** A folded group of thousands is listed in part: that many rows would freeze the page. */
const GROUP_LIST_LIMIT = 300;

const isSimple = (v: unknown) => isPrimitive(v) || (Array.isArray(v) && v.every(isPrimitive));

/** Every field of the resource, nested as the FHIR JSON is, with references turned into links. */
function Fields({ value, ctx, depth = 0 }: { value: Json; ctx: Ctx; depth?: number }) {
  return (
    <dl className="flex flex-col gap-1.5 text-xs">
      {Object.entries(value).map(([key, v]) =>
        // Short values sit beside their name; nested ones go below it, so deep levels never get squeezed into a sliver.
        isSimple(v) ? (
          <div key={key} className={depth === 0 ? "grid grid-cols-[7.5rem_minmax(0,1fr)] gap-2" : "flex flex-wrap gap-x-2"}>
            <dt className="text-muted-foreground break-words">{key}</dt>
            <dd className="min-w-0 break-words">
              <Value k={key} v={v} ctx={ctx} depth={depth} />
            </dd>
          </div>
        ) : (
          <div key={key} className="flex flex-col gap-1">
            <dt className="text-muted-foreground">{key}</dt>
            <dd className="min-w-0">
              <Value k={key} v={v} ctx={ctx} depth={depth} />
            </dd>
          </div>
        ),
      )}
    </dl>
  );
}

function Value({ k, v, ctx, depth }: { k: string; v: unknown; ctx: Ctx; depth: number }) {
  if (typeof v === "string" && k === "reference") {
    const target = ctx.parsed.resolve(v);
    return target ? (
      <LinkButton id={target} ctx={ctx} />
    ) : (
      <span className="font-mono break-all">
        {v} <span className="text-muted-foreground">(not in this bundle)</span>
      </span>
    );
  }
  if (isPrimitive(v)) return <span className="break-words">{String(v)}</span>;
  if (Array.isArray(v)) {
    if (v.length === 0) return <span className="text-muted-foreground">empty</span>;
    if (v.every(isPrimitive)) return <span className="break-words">{v.map(String).join(", ")}</span>;
    return (
      <ol className="flex flex-col gap-2">
        {v.map((item, i) => (
          <li key={i} className="border-l-2 pl-2">
            {isObject(item) ? <Fields value={item} ctx={ctx} depth={depth + 1} /> : <Value k={k} v={item} ctx={ctx} depth={depth + 1} />}
          </li>
        ))}
      </ol>
    );
  }
  return isObject(v) ? (
    <div className="border-l-2 pl-2">
      <Fields value={v} ctx={ctx} depth={depth + 1} />
    </div>
  ) : null;
}

function LinkList({ title, empty, items, ctx }: { title: string; empty: string; items: { field: string; id: string }[]; ctx: Ctx }) {
  return (
    <section className="flex flex-col gap-1.5">
      <h3 className="text-sm font-medium">
        {title} <span className="text-muted-foreground font-normal">({items.length})</span>
      </h3>
      {items.length === 0 && <p className="text-muted-foreground text-xs">{empty}</p>}
      <ul className="flex flex-col gap-1 text-xs">
        {items.map((item, i) => (
          <li key={`${item.id}-${item.field}-${i}`} className="flex gap-2">
            <span className="text-muted-foreground w-40 shrink-0 break-words">{item.field}</span>
            <LinkButton id={item.id} ctx={ctx} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function Header({ type, title, subtitle, id, onClose }: { type: string; title: string; subtitle: string; id?: string; onClose: () => void }) {
  return (
    <div className="flex items-start gap-2 border-b p-4">
      <span className="mt-1 h-10 w-1 shrink-0 rounded-full" style={{ background: typeColor(type) }} />
      <div className="min-w-0 flex-1">
        <div className="text-[10px] font-semibold tracking-wide uppercase" style={{ color: typeColor(type) }}>
          {type}
        </div>
        <h2 className="text-sm leading-snug font-semibold break-words">{title}</h2>
        {subtitle && <p className="text-muted-foreground text-xs">{subtitle}</p>}
        {id && <p className="text-muted-foreground mt-1 font-mono text-[10px] break-all">{id}</p>}
      </div>
      <Button type="button" variant="ghost" size="icon-sm" aria-label="Close the panel" onClick={onClose}>
        <XIcon />
      </Button>
    </div>
  );
}

/** The panel on the right: everything about the clicked resource (its fields, how it connects, the raw JSON). */
export function ResourceDrawer({
  parsed,
  selectedId,
  members,
  onSelect,
  onExpand,
  onClose,
}: {
  parsed: ParsedBundle;
  selectedId: string;
  /** Set when a folded group is selected: the resources it stands for. */
  members?: string[];
  onSelect: (id: string) => void;
  /** Draw this folded group's members one by one in the graph. */
  onExpand?: () => void;
  onClose: () => void;
}) {
  const ctx: Ctx = useMemo(() => ({ parsed, open: onSelect }), [parsed, onSelect]);
  const resource: Resource | undefined = parsed.resources.get(selectedId);
  const json = useMemo(() => (resource ? JSON.stringify(resource, null, 2) : ""), [resource]);
  const links = useMemo(() => (resource ? neighbours(parsed, selectedId) : null), [parsed, selectedId, resource]);

  if (members) {
    const type = parsed.resources.get(members[0])?.resourceType ?? "Resources";
    return (
      <div className="flex h-full flex-col">
        <Header type={type} title={`${members.length} × ${type}`} subtitle="Folded into one node. Click one to open it." onClose={onClose} />
        {onExpand && (
          <div className="border-b p-3">
            <Button type="button" size="sm" variant="outline" onClick={onExpand}>
              Draw these {members.length} in the graph
            </Button>
          </div>
        )}
        <ul className="flex-1 divide-y overflow-auto text-xs">
          {members.slice(0, GROUP_LIST_LIMIT).map((m) => {
            const res = parsed.resources.get(m)!;
            const d = describe(res);
            return (
              <li key={m}>
                <button type="button" className="hover:bg-muted w-full px-4 py-2 text-left" onClick={() => onSelect(m)}>
                  <span className="block font-medium break-words">{d.title}</span>
                  {d.subtitle && <span className="text-muted-foreground block">{d.subtitle}</span>}
                </button>
              </li>
            );
          })}
          {members.length > GROUP_LIST_LIMIT && (
            <li className="text-muted-foreground px-4 py-2">
              and {members.length - GROUP_LIST_LIMIT} more. Use &quot;Draw these in the graph&quot; to reach all of them.
            </li>
          )}
        </ul>
      </div>
    );
  }
  if (!resource || !links) return null;
  const d = describe(resource);

  return (
    <div className="flex h-full flex-col">
      <Header type={resource.resourceType} title={d.title} subtitle={d.subtitle} id={selectedId} onClose={onClose} />
      <Tabs defaultValue="details" className="min-h-0 flex-1 gap-0">
        <TabsList className="mx-4 mt-3">
          <TabsTrigger value="details">Details</TabsTrigger>
          <TabsTrigger value="links">Connections</TabsTrigger>
          <TabsTrigger value="json">JSON</TabsTrigger>
        </TabsList>
        <TabsContent value="details" className="overflow-auto p-4">
          <Fields value={Object.fromEntries(Object.entries(resource).filter(([k]) => k !== "resourceType"))} ctx={ctx} />
        </TabsContent>
        <TabsContent value="links" className="flex flex-col gap-5 overflow-auto p-4">
          <LinkList
            title="Points at"
            empty="Holds no references to other resources."
            items={links.outgoing.map((l) => ({ field: l.field, id: l.to }))}
            ctx={ctx}
          />
          <LinkList
            title="Referenced by"
            empty="No other resource in this bundle points at it."
            items={links.incoming.map((l) => ({ field: `${l.field} of`, id: l.from }))}
            ctx={ctx}
          />
          {links.unresolved.length > 0 && (
            <section className="flex flex-col gap-1.5">
              <h3 className="text-sm font-medium">
                Points outside this bundle <span className="text-muted-foreground font-normal">({links.unresolved.length})</span>
              </h3>
              <ul className="flex flex-col gap-1 text-xs">
                {links.unresolved.map((u, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-muted-foreground w-40 shrink-0 break-words">{u.field}</span>
                    <span className="font-mono break-all">{u.reference}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </TabsContent>
        <TabsContent value="json" className="flex min-h-0 flex-col gap-2 p-4">
          <Button type="button" size="sm" variant="outline" className="w-fit" onClick={() => navigator.clipboard.writeText(json).then(() => toast.success("Copied"))}>
            <CopyIcon /> Copy JSON
          </Button>
          <pre className="bg-muted min-h-0 flex-1 overflow-auto rounded-lg p-3 font-mono text-[11px] leading-relaxed">{json}</pre>
        </TabsContent>
      </Tabs>
    </div>
  );
}
