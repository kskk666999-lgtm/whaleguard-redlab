"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Eye, Plus, Shield } from "lucide-react";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { useApp } from "@/components/providers";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { apiRequest, fetchPage } from "@/lib/api";
import { agentCreatePayload } from "@/lib/contracts";
import type { ApiRecord, Project } from "@/lib/types";
import { formatDate } from "@/lib/utils";

type AgentTarget = ApiRecord & { name: string; description?: string; endpoint_url?: string; agent_type?: string; status?: string; enabled?: boolean; project_name?: string; risk_level?: string };

export default function AgentsPage() {
  const client = useQueryClient();
  const { toast } = useApp();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<AgentTarget | null>(null);
  const [form, setForm] = useState({ project_id: "", name: "", description: "", agent_type: "mock-local", endpoint_url: "http://mock-agent:8102", enabled: true, risk_level: "medium" });
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => fetchPage<AgentTarget>("/agents?page=1&page_size=100") });
  const projects = useQuery({ queryKey: ["projects", "agent-selector"], queryFn: () => fetchPage<Project>("/projects?page=1&page_size=100") });
  useEffect(() => { if (!form.project_id && projects.data?.items[0]) setForm((value) => ({ ...value, project_id: projects.data!.items[0].id })); }, [form.project_id, projects.data]);
  const create = useMutation({ mutationFn: () => apiRequest<AgentTarget>("/agents", { method: "POST", body: agentCreatePayload(form) }), onSuccess: () => { client.invalidateQueries({ queryKey: ["agents"] }); setOpen(false); setForm((value) => ({ ...value, name: "", description: "" })); toast({ title: "Agent 目标已添加", description: "创建目标不会自动调用端点。", tone: "success" }); } });
  const columns: Column<AgentTarget>[] = [
    { key: "name", header: "Agent", searchValue: (row) => `${row.name} ${row.description || ""}`, render: (row) => <div><p className="font-medium">{row.name}</p><p className="mt-1 max-w-xs truncate text-[11px] text-muted-foreground">{row.description || row.project_name || "—"}</p></div> },
    { key: "type", header: "类型", searchValue: (row) => row.agent_type || "agent", render: (row) => <Badge tone={row.agent_type === "mock-local" ? "info" : "neutral"}>{row.agent_type || "agent"}</Badge> },
    { key: "endpoint", header: "端点", searchValue: (row) => row.endpoint_url || "", render: (row) => <span className="block max-w-64 truncate font-mono text-[11px] text-muted-foreground">{row.endpoint_url || "未配置"}</span> },
    { key: "risk", header: "工具风险", render: (row) => <Badge tone={statusTone(row.risk_level || "low")}>{row.risk_level || "low"}</Badge> },
    { key: "status", header: "状态", searchValue: (row) => row.status || (row.enabled ? "enabled" : "disabled"), render: (row) => <Badge tone={statusTone(row.status || (row.enabled === false ? "disabled" : "enabled"))}>{row.status || (row.enabled === false ? "disabled" : "enabled")}</Badge> },
    { key: "updated", header: "更新时间", render: (row) => <span className="text-xs text-muted-foreground">{formatDate(row.updated_at || row.created_at)}</span> },
    { key: "action", header: "操作", className: "text-right", render: (row) => <Button size="sm" variant="ghost" onClick={() => setSelected(row)}><Eye className="h-3.5 w-3.5" />查看</Button> },
  ];
  return (
    <div>
      <PageHeader eyebrow="AGENT TARGETS" title="Agent 管理" description="登记获授权的 Agent 测试目标、能力边界和调用入口。目标创建后不会自动执行工具或发起任务。" actions={<Button onClick={() => setOpen(true)} disabled={!projects.data?.items.length}><Plus className="h-4 w-4" />添加 Agent</Button>} />
      <Card className="overflow-hidden shadow-none">{agents.isLoading ? <LoadingState /> : agents.error ? <ErrorState error={agents.error} onRetry={() => agents.refetch()} /> : <DataTable data={agents.data?.items || []} columns={columns} rowKey={(row) => row.id} searchPlaceholder="搜索 Agent、项目或端点…" filters={[{ label: "Mock Agent", value: "mock", matches: (row) => row.agent_type === "mock-local" }, { label: "已启用", value: "enabled", matches: (row) => row.enabled !== false }]} emptyTitle="尚未添加 Agent" emptyDescription="建议先添加 Docker 私有网络中的 Mock Agent 完成本地安全基线。" />}</Card>
      <Dialog open={open} onOpenChange={setOpen}><DialogContent><DialogHeader><DialogTitle>添加 Agent 测试目标</DialogTitle><DialogDescription>仅登记目标。真正运行测试前会再次校验项目 Scope 和工具风险。</DialogDescription></DialogHeader><form onSubmit={(event) => { event.preventDefault(); create.mutate(); }} className="space-y-4"><div><Label htmlFor="agent-project">所属项目</Label><Select id="agent-project" required value={form.project_id} onChange={(event) => setForm({ ...form, project_id: event.target.value })}>{projects.data?.items.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</Select></div><div><Label htmlFor="agent-name">Agent 名称</Label><Input id="agent-name" required minLength={2} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="本地客服 Agent" /></div><div><Label htmlFor="agent-description">说明</Label><Textarea id="agent-description" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="Agent 能力、数据边界和测试用途" /></div><div className="grid gap-4 sm:grid-cols-2"><div><Label htmlFor="agent-type">目标类型</Label><Select id="agent-type" value={form.agent_type} onChange={(event) => setForm({ ...form, agent_type: event.target.value })}><option value="mock-local">Mock Agent</option><option value="openai-compatible">OpenAI Compatible Agent</option><option value="custom-http">授权 HTTP Agent</option></Select></div><div><Label htmlFor="agent-risk">风险等级</Label><Select id="agent-risk" value={form.risk_level} onChange={(event) => setForm({ ...form, risk_level: event.target.value })}><option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="critical">critical</option></Select></div></div><div><Label htmlFor="agent-endpoint">端点</Label><Input id="agent-endpoint" type="url" required value={form.endpoint_url} onChange={(event) => setForm({ ...form, endpoint_url: event.target.value })} /></div><label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} className="accent-teal-500" />创建后启用</label>{create.error ? <p className="rounded-lg bg-red-500/10 p-3 text-xs text-red-400">{create.error.message}</p> : null}<DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>取消</Button><Button type="submit" loading={create.isPending}><Bot className="h-4 w-4" />保存 Agent</Button></DialogFooter></form></DialogContent></Dialog>
      <Dialog open={Boolean(selected)} onOpenChange={(value) => !value && setSelected(null)}><DialogContent>{selected ? <><DialogHeader><DialogTitle>{selected.name}</DialogTitle><DialogDescription>{selected.description || "暂无说明"}</DialogDescription></DialogHeader><div className="rounded-lg border bg-muted/35 p-4"><p className="data-label">ENDPOINT</p><p className="mt-2 break-all font-mono text-xs">{selected.endpoint_url || "未配置"}</p></div><div className="flex items-start gap-3 rounded-lg border border-teal-500/20 bg-teal-500/5 p-3"><Shield className="mt-0.5 h-4 w-4 text-primary" /><p className="text-xs leading-5 text-muted-foreground">Agent 调用工具前需经过 Tool Policy；高风险动作必须获得人工审批。</p></div><DialogFooter><Button variant="outline" onClick={() => setSelected(null)}>关闭</Button></DialogFooter></> : null}</DialogContent></Dialog>
    </div>
  );
}
