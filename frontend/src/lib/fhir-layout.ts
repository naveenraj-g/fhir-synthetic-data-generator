import { graphlib, layout } from "@dagrejs/dagre";
import type { FlowEdge, FlowNode } from "./fhir-graph.ts";

export const NODE_WIDTH = 232;
export const NODE_HEIGHT = 68;

export type Positions = Map<string, { x: number; y: number }>;

/** Up to this many nodes dagre lays the graph out (nicely, but its time grows far faster than linearly: ~9 s at 2,000
 *  nodes, minutes at 5,000). Beyond it the visit-band layout below is used: same reading order, linear time. */
export const DAGRE_MAX_NODES = 350;

/** Left-to-right layout with the referenced resource first, so the graph reads Patient -> visit -> what happened in it. */
export function layoutWithDagre(nodes: FlowNode[], edges: FlowEdge[], ranker: "network-simplex" | "longest-path" = "network-simplex"): Positions {
  const g = new graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 14, ranksep: 120, marginx: 24, marginy: 24, ranker });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT }));
  edges.forEach((e) => g.setEdge(e.to, e.from));
  layout(g);
  return new Map(nodes.map((n) => {
    const p = g.node(n.id);
    return [n.id, { x: p.x - NODE_WIDTH / 2, y: p.y - NODE_HEIGHT / 2 }];
  }));
}

const GAP_X = 120;
const GAP_Y = 14;
const BAND_GAP = 44;

function push<K, V>(map: Map<K, V[]>, key: K, value: V) {
  const list = map.get(key);
  if (list) list.push(value);
  else map.set(key, [value]);
}

/**
 * Linear-time layout for big graphs. Column = how far a resource is from the Patient along its references (Patient,
 * visits, what happened in a visit, what refers to that...). Row band = the visit it belongs to, in date order, so
 * the picture reads as a timeline from the top down. Resources not tied to any visit sit in the first band, under
 * the Patient. Nothing here searches or iterates to convergence, so 20,000 nodes lay out in milliseconds.
 */
export function layoutBands(nodes: FlowNode[], edges: FlowEdge[]): Positions {
  const referents = new Map<string, string[]>(); // node -> the nodes it points at
  const referrers = new Map<string, string[]>(); // node -> the nodes that point at it
  for (const e of edges) {
    push(referents, e.from, e.to);
    push(referrers, e.to, e.from);
  }

  // Column: longest path from a node with no referents, in topological order (Kahn). Cycles leave some nodes
  // unvisited; they take the column after their deepest visited referent.
  const waiting = new Map<string, number>();
  const column = new Map<string, number>();
  const queue: string[] = [];
  for (const n of nodes) {
    const count = referents.get(n.id)?.length ?? 0;
    waiting.set(n.id, count);
    if (count === 0) {
      column.set(n.id, 0);
      queue.push(n.id);
    }
  }
  const order: string[] = [];
  for (let head = 0; head < queue.length; head++) {
    const id = queue[head];
    order.push(id);
    for (const r of referrers.get(id) ?? []) {
      column.set(r, Math.max(column.get(r) ?? 0, (column.get(id) ?? 0) + 1));
      const left = (waiting.get(r) ?? 1) - 1;
      waiting.set(r, left);
      if (left === 0) queue.push(r);
    }
  }
  const visited = new Set(order);
  for (const n of nodes) {
    if (visited.has(n.id)) continue;
    let deepest = -1;
    for (const ref of referents.get(n.id) ?? []) deepest = Math.max(deepest, column.get(ref) ?? 0);
    column.set(n.id, deepest + 1);
    order.push(n.id);
  }

  // Band: the visit a node belongs to (itself, if it is one; else the visit of the first node it points at).
  const type = new Map(nodes.map((n) => [n.id, n.type]));
  const band = new Map<string, string>();
  for (const id of order) {
    if (type.get(id) === "Encounter") {
      band.set(id, id);
      continue;
    }
    for (const ref of referents.get(id) ?? []) {
      const b = band.get(ref);
      if (b !== undefined) {
        band.set(id, b);
        break;
      }
    }
  }

  // Bands in the nodes' own order (the Patient, then visits by date); the un-visited resources form the first band.
  const NONE = "";
  const bandOrder: string[] = [NONE];
  const cells = new Map<string, Map<number, string[]>>(); // band -> column -> node ids, top to bottom
  const place = (b: string, col: number, id: string) => {
    let columns = cells.get(b);
    if (!columns) cells.set(b, (columns = new Map()));
    push(columns, col, id);
  };
  for (const n of nodes) {
    const b = band.get(n.id) ?? NONE;
    if (b === n.id && b !== NONE) bandOrder.push(b);
    place(b, column.get(n.id) ?? 0, n.id);
  }

  const positions: Positions = new Map();
  let y = 0;
  for (const b of bandOrder) {
    const columns = cells.get(b);
    if (!columns) continue;
    let rows = 1;
    for (const [col, ids] of columns) {
      rows = Math.max(rows, ids.length);
      ids.forEach((id, i) => positions.set(id, { x: col * (NODE_WIDTH + GAP_X), y: y + i * (NODE_HEIGHT + GAP_Y) }));
    }
    y += rows * (NODE_HEIGHT + GAP_Y) + BAND_GAP;
  }
  return positions;
}

export function layoutGraph(nodes: FlowNode[], edges: FlowEdge[]): Positions {
  return nodes.length <= DAGRE_MAX_NODES ? layoutWithDagre(nodes, edges) : layoutBands(nodes, edges);
}
