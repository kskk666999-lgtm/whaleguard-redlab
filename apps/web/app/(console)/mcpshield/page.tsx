"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Braces, FileJson, Network, Plus, ScanSearch, ShieldAlert, Wrench } from "lucide-react";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { useApp } from "@/components/providers";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Select, Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { apiRequest, fetchPage, toPage } from "@/lib/api";
import { mcpImportPayload, mcpServerCreatePayload } from "@/lib/contracts";
import { mcpImportSchema } from "@/lib/schemas";
import type { ApiRecord, Project } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";

type MCPServer = ApiRecord & { project_id?: string; name: string; transport?: string; endpoint_url?: string; status?: string; risk_score?: number; risk_level?: string; tool_count?: number; last_analyzed_at?: string; findings?: unknown[]; recommendations?: string[] };
type MCPTool = ApiRecord & { name: string; description?: string; risk_level?: string; risk_score?: number; requires_approval?: boolean; permissions?: string[]; risk_flags?: string[]; input_schema?: unknown };
type MCPAnalysis = { server_id: string; risk_score: number; risk_level: string; findings: Array<Record<string, unknown>>; recommendations: string[]; tools: MCPTool[]; execution_performed: false };

const sampleConfig = `{
  "mcpServers": {
    "demo-safe-server": {
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "mock_mcp_server"]
    }
  }
}`;

export default function MCPShieldPage() {
  const { toast } = useApp();
  const client = useQueryClient();
  const [manualOpen, setManualOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [projectId, setProjectId] = useState("");
  const [selected, setSelected] = useState<MCPServer | null>(null);
  const [analyzingId, setAnalyzingId] = useState<string | null>(null);
  const [manual, setManual] = useState({ name: "", transport: "stdio", command: "", url: "", enabled: true });
  const [configText, setConfigText] = useState(sampleConfig);
  const [configError, setConfigError] = useState("");
  const servers = useQuery({ queryKey: ["mcp-servers"], queryFn: () => fetchPage<MCPServer>("/mcp/servers?page=1&page_size=100") });
  const projects = useQuery({ queryKey: ["projects", "mcp-selector"], queryFn: () => fetchPage<Project>("/projects?page=1&page_size=100") });
  useEffect(() => { if (!projectId && projects.data?.items[0]) setProjectId(projects.data.items[0].id); }, [projectId, projects.data]);
  const tools = useQuery({ queryKey: ["mcp-tools", selected?.id], queryFn: async () => toPage<MCPTool>(await apiRequest<unknown>(`/mcp/servers/${selected!.id}/tools?page=1&page_size=100`)), enabled: Boolean(selected) });
  const create = useMutation({ mutationFn: () => apiRequest<MCPServer>("/mcp/servers", { method: "POST", body: mcpServerCreatePayload(projectId, manual) }), onSuccess: () => { client.invalidateQueries({ queryKey: ["mcp-servers"] }); setManualOpen(false); setManual({ name: "", transport: "stdio", command: "", url: "", enabled: true }); toast({ title: "MCP Server 已登记", description: "尚未执行任何 Tool。可以开始静态元数据分析。", tone: "success" }); } });
  const importConfig = useMutation({ mutationFn: (config: unknown) => apiRequest<unknown>("/mcp/servers/import", { method: "POST", body: mcpImportPayload(projectId, config) }), onSuccess: () => { client.invalidateQueries({ queryKey: ["mcp-servers"] }); setImportOpen(false); toast({ title: "MCP 配置已导入", description: "仅解析配置与元数据，不会启动或执行未知 Tool。", tone: "success" }); } });
  const analyze = useMutation({ mutationFn: (id: string) => apiRequest<MCPAnalysis>(`/mcp/servers/${id}/analyze`, { method: "POST", body: {} }), onMutate: (id) => setAnalyzingId(id), onSuccess: (result) => { client.invalidateQueries({ queryKey: ["mcp-servers"] }); if (selected?.id === result.server_id) setSelected((current) => current ? { ...current, risk_score: result.risk_score, risk_level: result.risk_level, findings: result.findings, recommendations: result.recommendations } : current); toast({ title: "MCP 静态分析完成", description: `风险分数 ${result.risk_score}，未执行任何 Tool。`, tone: "success" }); }, onError: (error) => toast({ title: "分析失败", description: error.message, tone: "error" }), onSettled: () => setAnalyzingId(null) });
  const submitImport = (event: React.FormEvent) => { event.preventDefault(); const parsed = mcpImportSchema.safeParse({ config: configText }); if (!parsed.success) { setConfigError(parsed.error.issues[0]?.message || "配置无效"); return; } setConfigError(""); importConfig.mutate(parsed.data.config); };
  const columns: Column<MCPServer>[] = [
    { key: "server", header: "MCP Server", searchValue: (row) => `${row.name} ${row.endpoint_url || ""}`, render: (row) => <div><p className="font-medium">{row.name}</p><p className="mt-1 max-w-64 truncate font-mono text-[10px] text-muted-foreground">{row.endpoint_url || "配置元数据"}</p></div> },
    { key: "transport", header: "传输", searchValue: (row) => row.transport || "stdio", render: (row) => <Badge>{row.transport || "stdio"}</Badge> },
    { key: "tools", header: "Tools", render: (row) => <span className="font-mono text-xs">{row.tool_count ?? 0}</span> },
    { key: "score", header: "风险分数", render: (row) => <div className="flex items-center gap-2"><span className={cn("font-mono text-sm font-semibold", (row.risk_score ?? 0) >= 70 ? "text-red-400" : (row.risk_score ?? 0) >= 40 ? "text-amber-400" : "text-emerald-400")}>{row.risk_score ?? "—"}</span><Badge tone={statusTone(row.risk_level || "unknown")}>{row.risk_level || "未分析"}</Badge></div> },
    { key: "analyzed", header: "最近分析", render: (row) => <span className="text-xs text-muted-foreground">{formatDate(row.last_analyzed_at)}</span> },
    { key: "actions", header: "操作", className: "text-right", render: (row) => <div className="flex justify-end gap-1"><Button size="sm" variant="ghost" onClick={() => setSelected(row)}><Wrench className="h-3.5 w-3.5" />Tools</Button><Button size="sm" variant="outline" loading={analyzingId === row.id} disabled={analyzingId !== null && analyzingId !== row.id} onClick={() => analyze.mutate(row.id)}><ScanSearch className="h-3.5 w-3.5" />分析</Button></div> },
  ];
  return (
    <div>
      <PageHeader eyebrow="STATIC MCP RISK ANALYSIS" title="MCPShield" description="第一版仅分析 MCP 配置、Tool 描述、参数 Schema 与权限元数据；永不自动执行未知 MCP Tool。" actions={<><Button variant="outline" disabled={!projectId} onClick={() => setManualOpen(true)}><Plus className="h-4 w-4" />手工添加</Button><Button disabled={!projectId} onClick={() => setImportOpen(true)}><FileJson className="h-4 w-4" />导入 JSON 配置</Button></>} />
      <div className="mb-4 grid gap-3 md:grid-cols-3">
        {[{ label: "分析模式", value: "Metadata Only", icon: ScanSearch }, { label: "未知 Tool 执行", value: "始终禁止", icon: ShieldAlert }, { label: "检查维度", value: "8 类风险", icon: Braces }].map((item) => <Card key={item.label} className="shadow-none"><CardContent className="flex items-center gap-3 p-4"><div className="rounded-lg bg-primary/10 p-2 text-primary"><item.icon className="h-4 w-4" /></div><div><p className="text-[10px] text-muted-foreground">{item.label}</p><p className="mt-1 text-xs font-semibold">{item.value}</p></div></CardContent></Card>)}
      </div>
      <Card className="overflow-hidden shadow-none">{servers.isLoading ? <LoadingState label="正在读取 MCP 资产…" /> : servers.error ? <ErrorState error={servers.error} onRetry={() => servers.refetch()} /> : <DataTable data={servers.data?.items || []} columns={columns} rowKey={(row) => row.id} searchPlaceholder="搜索 MCP Server、命令或 URL…" filters={[{ label: "高风险", value: "high", matches: (row) => (row.risk_score ?? 0) >= 70 }, { label: "需复核", value: "review", matches: (row) => (row.risk_score ?? 0) >= 40 && (row.risk_score ?? 0) < 70 }, { label: "低风险", value: "low", matches: (row) => (row.risk_score ?? 0) < 40 }]} emptyTitle="尚未登记 MCP Server" emptyDescription="可以手工添加或导入 JSON 配置；导入不会启动外部进程。" />}</Card>
      <Dialog open={manualOpen} onOpenChange={setManualOpen}><DialogContent><DialogHeader><DialogTitle>手工添加 MCP Server</DialogTitle><DialogDescription>仅保存配置元数据，不会连接或启动 Server。</DialogDescription></DialogHeader><form className="space-y-4" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}><div><Label htmlFor="mcp-project">所属项目</Label><Select id="mcp-project" required value={projectId} onChange={(event) => setProjectId(event.target.value)}>{projects.data?.items.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</Select></div><div><Label htmlFor="mcp-name">名称</Label><Input id="mcp-name" required minLength={2} value={manual.name} onChange={(event) => setManual({ ...manual, name: event.target.value })} placeholder="demo-safe-server" /></div><div><Label htmlFor="mcp-transport">Transport</Label><Select id="mcp-transport" value={manual.transport} onChange={(event) => setManual({ ...manual, transport: event.target.value })}><option value="stdio">stdio</option><option value="sse">SSE</option><option value="streamable-http">Streamable HTTP</option></Select></div>{manual.transport === "stdio" ? <div><Label htmlFor="mcp-command">命令元数据</Label><Input id="mcp-command" required value={manual.command} onChange={(event) => setManual({ ...manual, command: event.target.value })} placeholder="python -m mock_mcp_server" /></div> : <div><Label htmlFor="mcp-url">授权 URL</Label><Input id="mcp-url" required type="url" value={manual.url} onChange={(event) => setManual({ ...manual, url: event.target.value })} placeholder="http://mock-mcp-server:8103/mcp" /></div>}<div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs leading-5 text-muted-foreground">命令或 URL 只作为待分析元数据保存；本操作不会执行它。</div>{create.error ? <p className="rounded-lg bg-red-500/10 p-3 text-xs text-red-400">{create.error.message}</p> : null}<DialogFooter><Button type="button" variant="outline" onClick={() => setManualOpen(false)}>取消</Button><Button type="submit" loading={create.isPending}><Network className="h-4 w-4" />保存元数据</Button></DialogFooter></form></DialogContent></Dialog>
      <Dialog open={importOpen} onOpenChange={setImportOpen}><DialogContent className="max-w-2xl"><DialogHeader><DialogTitle>导入 MCP JSON 配置</DialogTitle><DialogDescription>服务端会清理敏感字段并进行结构验证；不会执行配置中的 command。</DialogDescription></DialogHeader><form className="space-y-4" onSubmit={submitImport}><div><Label htmlFor="mcp-import-project">所属项目</Label><Select id="mcp-import-project" required value={projectId} onChange={(event) => setProjectId(event.target.value)}>{projects.data?.items.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</Select></div><div><Label htmlFor="mcp-json">JSON 配置</Label><Textarea id="mcp-json" className="min-h-72 font-mono text-xs" value={configText} onChange={(event) => setConfigText(event.target.value)} spellCheck={false} /><FieldError>{configError}</FieldError></div>{importConfig.error ? <p className="rounded-lg bg-red-500/10 p-3 text-xs text-red-400">{importConfig.error.message}</p> : null}<DialogFooter><Button type="button" variant="outline" onClick={() => setImportOpen(false)}>取消</Button><Button type="submit" loading={importConfig.isPending}><FileJson className="h-4 w-4" />安全导入</Button></DialogFooter></form></DialogContent></Dialog>
      <Dialog open={Boolean(selected)} onOpenChange={(value) => !value && setSelected(null)}><DialogContent className="max-w-3xl"><DialogHeader><DialogTitle>{selected?.name} · Tool 元数据</DialogTitle><DialogDescription>显示静态分析结果与修复建议，不提供执行按钮。</DialogDescription></DialogHeader>{selected ? <>{tools.isLoading ? <LoadingState className="min-h-40" /> : tools.error ? <ErrorState error={tools.error} onRetry={() => tools.refetch()} /> : tools.data?.items.length ? <div className="max-h-80 space-y-2 overflow-y-auto">{tools.data.items.map((tool) => <div key={tool.id} className="rounded-lg border bg-muted/25 p-3"><div className="flex items-start gap-3"><div className="rounded-md bg-muted p-2"><Wrench className="h-3.5 w-3.5" /></div><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className="font-mono text-xs font-semibold">{tool.name}</p><Badge tone={statusTone(tool.risk_level || "low")}>{tool.risk_level || "low"}</Badge>{tool.requires_approval ? <Badge tone="warning">需人工审批</Badge> : null}</div><p className="mt-1.5 text-[11px] leading-5 text-muted-foreground">{tool.description || "无描述"}</p><div className="mt-2 flex flex-wrap gap-1">{[...(tool.permissions || []), ...(tool.risk_flags || [])].map((flag) => <Badge key={flag}>{flag}</Badge>)}</div></div></div></div>)}</div> : <EmptyState title="未发现 Tool 元数据" description="该 Server 尚未提供可分析的 Tools。" />}{selected.recommendations?.length ? <div className="rounded-lg border border-teal-500/20 bg-teal-500/5 p-3"><p className="text-xs font-medium">修复建议</p><ul className="mt-2 space-y-1 text-[11px] leading-5 text-muted-foreground">{selected.recommendations.map((item) => <li key={item}>• {item}</li>)}</ul></div> : null}<DialogFooter><Button variant="outline" onClick={() => setSelected(null)}>关闭</Button><Button loading={analyzingId === selected.id} onClick={() => analyze.mutate(selected.id)}><ScanSearch className="h-4 w-4" />重新分析</Button></DialogFooter></> : null}</DialogContent></Dialog>
    </div>
  );
}
