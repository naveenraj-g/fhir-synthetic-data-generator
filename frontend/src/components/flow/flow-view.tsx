"use client";

import "@xyflow/react/dist/style.css";

import { Background, ControlButton, Controls, MarkerType, MiniMap, ReactFlow, ReactFlowProvider, useReactFlow, useStore, type Edge, type NodeMouseHandler } from "@xyflow/react";
import { ArrowLeftIcon, Maximize2Icon, Minimize2Icon, ScanIcon, TriangleAlertIcon } from "lucide-react";
import Link from "next/link";
import { useTheme } from "next-themes";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SimpleSelect } from "@/components/builder/inputs";
import { jobTitle } from "@/components/jobs/jobs-list";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useBundle, useBundleIndex, useJob } from "@/lib/api/hooks";
import { buildGraph, countByType, DEFAULT_HIDDEN_TYPES, LARGE_RECORD, parseBundle, type ParsedBundle } from "@/lib/fhir-graph";
import { layoutGraph } from "@/lib/fhir-layout";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { PipelineStrip } from "./pipeline-strip";
import { NODE_HEIGHT, NODE_WIDTH, ResourceNode, type ResourceFlowNode } from "./resource-node";
import { ResourceDrawer } from "./resource-drawer";
import { typeColor } from "./type-style";

const nodeTypes = { resource: ResourceNode };

/** Below this zoom the cards are unreadable, so a big graph starts here instead of being squeezed to fit. */
const READABLE_ZOOM = 0.45;

function Canvas({ parsed }: { parsed: ParsedBundle }) {
  const { resolvedTheme } = useTheme();
  const { fitView, setViewport } = useReactFlow();
  const typeCounts = useMemo(() => countByType(parsed), [parsed]);
  const large = parsed.resources.size > LARGE_RECORD;
  const [hidden, setHidden] = useState<ReadonlySet<string>>(() => new Set(DEFAULT_HIDDEN_TYPES));
  const [collapse, setCollapse] = useState(true);
  const [patientLinks, setPatientLinks] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Full screen: the graph and its side panel go full screen together (React Flow's own bottom-left button only refits
  // the zoom). If the browser refuses the Fullscreen API, the graph fills the whole window instead. Esc leaves either;
  // the canvas reframes itself because its size changes.
  const boxRef = useRef<HTMLDivElement>(null);
  const [fullscreen, setFullscreen] = useState(false); // the browser's full screen
  const [filled, setFilled] = useState(false); // the fallback: fixed over the whole window
  useEffect(() => {
    const sync = () => setFullscreen(document.fullscreenElement === boxRef.current);
    document.addEventListener("fullscreenchange", sync);
    return () => document.removeEventListener("fullscreenchange", sync);
  }, []);
  const big = fullscreen || filled;
  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else if (filled) setFilled(false);
    else if (boxRef.current?.requestFullscreen) boxRef.current.requestFullscreen().catch(() => setFilled(true));
    else setFilled(true);
  };
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set());

  const graph = useMemo(() => buildGraph(parsed, { collapse, hiddenTypes: hidden, patientLinks, expanded, groupMin: large ? 1 : undefined }), [parsed, collapse, hidden, patientLinks, expanded, large]);
  const positions = useMemo(() => layoutGraph(graph.nodes, graph.edges), [graph]);
  const nodeById = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph]);

  // The node standing for the selection: the resource itself, or the group it is folded into.
  const selectedNodeId = useMemo(() => {
    if (!selectedId) return null;
    if (nodeById.has(selectedId)) return selectedId;
    return graph.nodes.find((n) => n.members?.includes(selectedId))?.id ?? null;
  }, [selectedId, nodeById, graph.nodes]);
  const group = selectedId ? nodeById.get(selectedId)?.members : undefined;
  const openGroup = useCallback((key: string) => {
    setExpanded((prev) => new Set(prev).add(key));
    setSelectedId(null);
  }, []);

  const near = useMemo(() => {
    if (!selectedNodeId) return null;
    const set = new Set([selectedNodeId]);
    for (const e of graph.edges) if (e.from === selectedNodeId || e.to === selectedNodeId) set.add(e.from).add(e.to);
    return set;
  }, [graph.edges, selectedNodeId]);

  const nodes = useMemo<ResourceFlowNode[]>(
    () =>
      graph.nodes.map((n) => ({
        id: n.id,
        type: "resource",
        position: positions.get(n.id) ?? { x: 0, y: 0 },
        data: { type: n.type, title: n.title, subtitle: n.subtitle, count: n.members?.length, selected: n.id === selectedNodeId, dimmed: near !== null && !near.has(n.id) },
        // Fixed size, known up front: the minimap draws only nodes it can size, and with only the visible nodes
        // rendered the others are never measured.
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        draggable: false,
        connectable: false,
      })),
    [graph.nodes, positions, selectedNodeId, near],
  );

  const edges = useMemo<Edge[]>(
    () =>
      graph.edges.map((e) => {
        const active = selectedNodeId !== null && (e.from === selectedNodeId || e.to === selectedNodeId);
        return {
          id: e.id,
          source: e.to, // the resource being pointed at sits on the left...
          target: e.from, // ...and the one holding the reference on the right
          markerStart: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
          label: active ? e.fields.join(", ") : undefined,
          labelStyle: { fontSize: 10 },
          style: { strokeDasharray: e.implied ? "4 4" : undefined, strokeWidth: active ? 2 : 1, opacity: selectedNodeId !== null && !active ? 0.12 : 0.7 },
          selectable: false,
          focusable: false,
        };
      }),
    [graph.edges, selectedNodeId],
  );

  // Frame the drawing whenever it changes shape (new bundle, filters, folding). Small enough: fit all of it. Too big to
  // read at once (a long record): start at the patient, on the left, at a readable zoom; pan or zoom out from there.
  const width = useStore((s) => s.width);
  const height = useStore((s) => s.height);
  useEffect(() => {
    if (!width || !height || positions.size === 0) return;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const p of positions.values()) {
      if (p.x < minX) minX = p.x;
      if (p.x > maxX) maxX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.y > maxY) maxY = p.y;
    }
    maxX += NODE_WIDTH;
    maxY += NODE_HEIGHT;
    const fit = Math.min((width - 60) / (maxX - minX), (height - 60) / (maxY - minY));
    // Start on the patient: vertically centred in the view, but never showing empty space above the first row.
    const patient = parsed.patientId ? positions.get(parsed.patientId) : undefined;
    const centre = Math.max((patient?.y ?? (minY + maxY) / 2) + NODE_HEIGHT / 2, minY - 40 + height / (2 * READABLE_ZOOM));
    const t = window.setTimeout(() => {
      if (fit >= READABLE_ZOOM) fitView({ padding: 0.12, duration: 250 });
      else setViewport({ x: 30 - minX * READABLE_ZOOM, y: height / 2 - centre * READABLE_ZOOM, zoom: READABLE_ZOOM }, { duration: 250 });
    }, 50);
    return () => window.clearTimeout(t);
  }, [positions, parsed.patientId, width, height, fitView, setViewport]);

  const select = useCallback(
    (id: string | null, pan = false) => {
      setSelectedId(id);
      if (id && pan) {
        const target = nodeById.has(id) ? id : graph.nodes.find((n) => n.members?.includes(id))?.id;
        if (target) fitView({ nodes: [{ id: target }], duration: 350, maxZoom: 1, padding: 0.8 });
      }
    },
    [fitView, graph.nodes, nodeById],
  );
  const onNodeClick = useCallback<NodeMouseHandler>((_, node) => select(node.id), [select]);

  // Esc closes the side panel first; with nothing open it leaves the filled-window mode.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (selectedId !== null) setSelectedId(null);
      else if (filled) setFilled(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId, filled]);

  const toggleType = (type: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (!next.delete(type)) next.add(type);
      return next;
    });
  const hiddenPresent = typeCounts.filter(([t]) => hidden.has(t));

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={collapse} onCheckedChange={(on) => { setCollapse(on); setExpanded(new Set()); }} />
          Fold many similar results in one visit
        </label>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={patientLinks} onCheckedChange={setPatientLinks} />
          Draw every link to the patient
        </label>
        <span className="text-muted-foreground ml-auto text-xs tabular-nums">
          {formatNumber(parsed.resources.size)} resources · {formatNumber(parsed.links.length)} links · showing {formatNumber(graph.nodes.length)} nodes
        </span>
      </div>

      {large && (
        <Alert>
          <TriangleAlertIcon />
          <AlertTitle>A large record: {formatNumber(parsed.resources.size)} resources</AlertTitle>
          <AlertDescription>
            To keep the page fast it is drawn as a timeline (one row band per visit) with each type folded into one node per visit. Click a folded node to
            list its resources, open any of them, or use &quot;Draw these in the graph&quot;. Hiding types you do not need makes it lighter still.
          </AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Show or hide resource types">
        {typeCounts.map(([type, n]) => {
          const off = hidden.has(type);
          return (
            <button
              key={type}
              type="button"
              aria-pressed={!off}
              onClick={() => toggleType(type)}
              className={cn("flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors", off ? "text-muted-foreground bg-transparent line-through opacity-60" : "bg-background hover:bg-muted")}
            >
              <span className="size-2 rounded-full" style={{ background: typeColor(type) }} />
              {type}
              <span className="text-muted-foreground tabular-nums no-underline">{n}</span>
            </button>
          );
        })}
      </div>
      {hiddenPresent.length > 0 && (
        <p className="text-muted-foreground text-xs">
          Hidden to keep the picture readable: {hiddenPresent.map(([t]) => t).join(", ")}.{" "}
          <button type="button" className="text-primary underline-offset-2 hover:underline" onClick={() => setHidden(new Set())}>
            Show everything
          </button>
        </p>
      )}

      <div ref={boxRef} className={cn("bg-background relative flex overflow-hidden rounded-lg border", filled ? "fixed inset-0 z-50 h-screen rounded-none border-0" : fullscreen ? "h-screen rounded-none border-0" : "h-[75svh] min-h-[34rem]")}>
        <div className="min-w-0 flex-1">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodeClick={onNodeClick}
            onPaneClick={() => select(null)}
            colorMode={resolvedTheme === "dark" ? "dark" : "light"}
            nodesDraggable={false}
            nodesConnectable={false}
            minZoom={0.04}
            maxZoom={1.6}
            onlyRenderVisibleElements
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={20} />
            <Controls showInteractive={false} showFitView={false}>
              <ControlButton onClick={() => fitView({ padding: 0.1, duration: 300, minZoom: 0.02 })} title="Fit everything in view" aria-label="Fit everything in view">
                <ScanIcon />
              </ControlButton>
              <ControlButton onClick={toggleFullscreen} title={big ? "Leave full screen" : "Full screen"} aria-label={big ? "Leave full screen" : "Full screen"}>
                {big ? <Minimize2Icon /> : <Maximize2Icon />}
              </ControlButton>
            </Controls>
            <MiniMap pannable zoomable nodeColor={(n) => typeColor(String((n.data as { type?: string }).type))} nodeStrokeWidth={0} nodeBorderRadius={4} className="!hidden md:!block" />
          </ReactFlow>
          {graph.nodes.length === 0 && (
            <p className="text-muted-foreground absolute inset-0 grid place-items-center text-sm">Nothing to show: every type is hidden.</p>
          )}
        </div>
        {selectedId && (parsed.resources.has(selectedId) || group) && (
          <aside className="bg-background absolute inset-y-0 right-0 z-10 w-[26rem] max-w-[90%] border-l shadow-lg lg:static lg:shadow-none" aria-label="Resource details">
            <ResourceDrawer parsed={parsed} selectedId={selectedId} members={group} onExpand={selectedId && group ? () => openGroup(selectedId) : undefined} onSelect={(id) => select(id, true)} onClose={() => select(null)} />
          </aside>
        )}
      </div>
      <p className="text-muted-foreground text-xs">
        Click a resource to see all of its data. Each line joins a resource to one it references; the arrowhead is on the referenced resource. Dashed lines only keep unconnected resources attached to the patient.
      </p>
    </div>
  );
}

export function FlowView({ id }: { id: string }) {
  const job = useJob(id);
  const index = useBundleIndex(id);
  const [which, setWhich] = useState(0);
  const bundle = useBundle(id, which);
  const parsed = useMemo(() => (bundle.data ? parseBundle(bundle.data) : null), [bundle.data]);

  const failure = index.error ?? bundle.error;
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <Link href={`/jobs/${id}`} className={buttonVariants({ variant: "outline", size: "sm" })}>
          <ArrowLeftIcon /> Back to the job
        </Link>
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight">Flow of the data</h1>
          {job.data && <p className="text-muted-foreground truncate text-sm">{jobTitle(job.data)}</p>}
        </div>
        {index.data && index.data.count > 1 && (
          <div className="ml-auto w-64">
            <SimpleSelect
              value={String(which)}
              onChange={(v) => setWhich(Number(v))}
              options={index.data.items.map((b) => ({ value: String(b.index), label: `${b.label} (${formatNumber(b.resources)})` }))}
            />
          </div>
        )}
      </div>

      {job.data && job.data.status === "succeeded" && <PipelineStrip job={job.data} />}

      {failure && (
        <Alert variant="destructive">
          <TriangleAlertIcon />
          <AlertTitle>Cannot draw this result</AlertTitle>
          <AlertDescription>{failure.message}</AlertDescription>
        </Alert>
      )}
      {!failure && (index.isPending || bundle.isPending) && <Skeleton className="h-[28rem] rounded-lg" />}
      {parsed && (
        <ReactFlowProvider key={`${id}-${which}`}>
          <Canvas parsed={parsed} />
        </ReactFlowProvider>
      )}
    </div>
  );
}
