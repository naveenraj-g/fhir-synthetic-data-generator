"use client";

import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { LayersIcon } from "lucide-react";
import { memo } from "react";
import { cn } from "@/lib/utils";
import { typeColor } from "./type-style";

import { NODE_HEIGHT, NODE_WIDTH } from "@/lib/fhir-layout";

export { NODE_HEIGHT, NODE_WIDTH };

export type ResourceNodeData = {
  type: string;
  title: string;
  subtitle: string;
  count?: number; // set on a group node
  selected: boolean;
  dimmed: boolean;
};
export type ResourceFlowNode = Node<ResourceNodeData, "resource">;

/** One resource (or one folded group of them) in the flow. */
function ResourceNodeView({ data }: NodeProps<ResourceFlowNode>) {
  const color = typeColor(data.type);
  const group = data.count !== undefined;
  return (
    <div
      className={cn(
        "bg-card text-card-foreground relative flex flex-col justify-center gap-0.5 rounded-lg border px-3 py-1.5 text-left shadow-xs transition-opacity",
        group && "border-dashed",
        data.selected && "ring-primary ring-2",
        data.dimmed && "opacity-30",
      )}
      style={{ width: NODE_WIDTH, height: NODE_HEIGHT, borderLeft: `4px ${group ? "dashed" : "solid"} ${color}` }}
    >
      <Handle type="source" position={Position.Right} className="!size-1.5 !border-0 !bg-transparent" isConnectable={false} />
      <Handle type="target" position={Position.Left} className="!size-1.5 !border-0 !bg-transparent" isConnectable={false} />
      <span className="flex items-center gap-1 text-[10px] font-semibold tracking-wide uppercase" style={{ color }}>
        {group && <LayersIcon className="size-3" />}
        {data.type}
      </span>
      <span className="line-clamp-2 text-xs leading-tight font-medium break-words">{data.title}</span>
      {data.subtitle && <span className="text-muted-foreground truncate text-[10px]">{data.subtitle}</span>}
    </div>
  );
}

export const ResourceNode = memo(ResourceNodeView);
