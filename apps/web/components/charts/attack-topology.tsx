"use client";

import { Background, Controls, MarkerType, ReactFlow, type Edge, type Node } from "@xyflow/react";

const nodes: Node[] = [
  { id: "user", position: { x: 0, y: 74 }, data: { label: "授权用户" }, style: { width: 112, background: "#0f172a", color: "#cbd5e1", border: "1px solid #334155", borderRadius: 8, fontSize: 11 } },
  { id: "agent", position: { x: 180, y: 74 }, data: { label: "Mock Agent" }, style: { width: 118, background: "#10231f", color: "#99f6e4", border: "1px solid #0f766e", borderRadius: 8, fontSize: 11 } },
  { id: "kb", position: { x: 374, y: 14 }, data: { label: "Demo Knowledge" }, style: { width: 130, background: "#111827", color: "#cbd5e1", border: "1px solid #334155", borderRadius: 8, fontSize: 11 } },
  { id: "mcp", position: { x: 374, y: 122 }, data: { label: "Mock MCP" }, style: { width: 130, background: "#111827", color: "#cbd5e1", border: "1px solid #334155", borderRadius: 8, fontSize: 11 } },
  { id: "approval", position: { x: 570, y: 122 }, data: { label: "人工审批" }, style: { width: 110, background: "#2a1d0c", color: "#fde68a", border: "1px solid #b45309", borderRadius: 8, fontSize: 11 } },
];

const edges: Edge[] = [
  { id: "e1", source: "user", target: "agent", animated: true, style: { stroke: "#2dd4bf" }, markerEnd: { type: MarkerType.ArrowClosed, color: "#2dd4bf" } },
  { id: "e2", source: "agent", target: "kb", style: { stroke: "#64748b" }, markerEnd: { type: MarkerType.ArrowClosed, color: "#64748b" } },
  { id: "e3", source: "agent", target: "mcp", style: { stroke: "#64748b" }, markerEnd: { type: MarkerType.ArrowClosed, color: "#64748b" } },
  { id: "e4", source: "mcp", target: "approval", label: "sensitive", labelStyle: { fill: "#f59e0b", fontSize: 9 }, style: { stroke: "#f59e0b", strokeDasharray: "5 4" }, markerEnd: { type: MarkerType.ArrowClosed, color: "#f59e0b" } },
];

export function AttackTopology() {
  return (
    <div className="h-[245px] w-full overflow-hidden rounded-lg border bg-slate-950/80">
      <ReactFlow nodes={nodes} edges={edges} fitView minZoom={0.6} maxZoom={1.5} nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} proOptions={{ hideAttribution: true }}>
        <Background color="#334155" gap={18} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
