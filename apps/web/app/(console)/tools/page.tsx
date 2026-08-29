"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Network, ShieldAlert, Wrench } from "lucide-react";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { fetchPage } from "@/lib/api";
import type { ApiRecord } from "@/lib/types";

type MCPServer = ApiRecord & { name: string };
type Tool = ApiRecord & { name: string; description?: string; risk_level?: string; risk_score?: number; requires_approval?: boolean; permissions?: string[]; risk_flags?: string[]; server_id?: string; server_name?: string };

export default function ToolsPage() {
  const query = useQuery({
    queryKey: ["all-mcp-tools"],
    queryFn: async () => {
      const servers = await fetchPage<MCPServer>("/mcp/servers?page=1&page_size=100");
      const groups = await Promise.all(servers.items.map(async (server) => {
        const tools = await fetchPage<Tool>(`/mcp/servers/${server.id}/tools?page=1&page_size=100`);
        return tools.items.map((tool) => ({ ...tool, server_id: server.id, server_name: server.name }));
      }));
      return groups.flat();
    },
  });
  const columns: Column<Tool>[] = [
    { key: "tool", header: "Tool", searchValue: (row) => `${row.name} ${row.description || ""}`, render: (row) => <div className="flex items-start gap-3"><div className="rounded-md bg-muted p-2"><Wrench className="h-3.5 w-3.5 text-primary" /></div><div><p className="font-mono text-xs font-semibold">{row.name}</p><p className="mt-1 max-w-lg truncate text-[11px] text-muted-foreground">{row.description || "无描述"}</p></div></div> },
    { key: "server", header: "MCP Server", searchValue: (row) => row.server_name || "", render: (row) => <div className="flex items-center gap-1.5 text-xs"><Network className="h-3.5 w-3.5 text-muted-foreground" />{row.server_name || "—"}</div> },
    { key: "risk", header: "风险", searchValue: (row) => row.risk_level || "low", render: (row) => <div className="flex items-center gap-2"><Badge tone={statusTone(row.risk_level || "low")}>{row.risk_level || "low"}</Badge><span className="font-mono text-[10px] text-muted-foreground">{row.risk_score ?? "—"}</span></div> },
    { key: "capabilities", header: "能力", render: (row) => <div className="flex max-w-56 flex-wrap gap-1">{[...(row.permissions || []), ...(row.risk_flags || [])].slice(0, 3).map((capability) => <Badge key={capability}>{capability}</Badge>)}</div> },
    { key: "approval", header: "人工审批", render: (row) => row.requires_approval ? <Badge tone="warning"><ShieldAlert className="mr-1 h-3 w-3" />required</Badge> : <Badge tone="neutral">not required</Badge> },
  ];
  return (
    <div>
      <PageHeader eyebrow="TOOL INVENTORY" title="工具与 MCP" description="跨 Server 浏览 MCP Tool 元数据、风险能力和审批要求。此页面只读，不提供 Tool 执行入口。" actions={<Button asChild><Link href="/mcpshield"><ExternalLink className="h-4 w-4" />进入 MCPShield</Link></Button>} />
      <Card className="overflow-hidden shadow-none">{query.isLoading ? <LoadingState label="正在聚合 Tool 元数据…" /> : query.error ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : <DataTable data={query.data || []} columns={columns} rowKey={(row) => `${row.server_id}-${row.id}`} searchPlaceholder="搜索 Tool 名称、描述、Server 或能力…" filters={[{ label: "需人工审批", value: "approval", matches: (row) => row.requires_approval === true }, { label: "高风险", value: "high", matches: (row) => ["critical", "high"].includes(row.risk_level || "") }, { label: "网络能力", value: "network", matches: (row) => [...(row.permissions || []), ...(row.risk_flags || [])].some((item) => item.includes("network")) }]} emptyTitle="暂无 Tool 元数据" emptyDescription="先在 MCPShield 中导入或添加 MCP Server 并执行静态分析。" />}</Card>
    </div>
  );
}
