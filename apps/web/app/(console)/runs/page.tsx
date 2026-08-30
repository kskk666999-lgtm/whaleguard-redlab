"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Pause, Play, RotateCcw, ScrollText, Square, TestTube2 } from "lucide-react";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { useApp } from "@/components/providers";
import { RunApprovalControls, type ApprovalRequest } from "@/components/run-approval-controls";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Select } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { API_BASE, apiRequest, fetchPage } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { runCreatePayload } from "@/lib/contracts";
import { runInputSchema } from "@/lib/schemas";
import type { ApiRecord, Project, TestRun } from "@/lib/types";
import { cn, formatDate, shortId } from "@/lib/utils";

type TestSuite = ApiRecord & { name: string; project_id?: string };
type AgentTarget = ApiRecord & { project_id?: string; name: string; enabled?: boolean; agent_type?: string };
type ModelChannel = ApiRecord & { project_id?: string; name: string; enabled?: boolean; model?: string };

function useRunEvents(runId: string | null) {
  const [events, setEvents] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!runId) { setEvents([]); setConnected(false); setError(null); return; }
    const controller = new AbortController();
    const connect = async () => {
      try {
        const response = await fetch(`${API_BASE}/runs/${runId}/events`, { headers: { Accept: "text/event-stream", ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}) }, signal: controller.signal });
        if (!response.ok || !response.body) throw new Error(`事件流连接失败（HTTP ${response.status}）`);
        setConnected(true);
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const chunks = buffer.split("\n\n");
          buffer = chunks.pop() || "";
          for (const chunk of chunks) {
            const data = chunk.split("\n").filter((line) => line.startsWith("data:")) .map((line) => line.slice(5).trim()).join(" ");
            if (data) setEvents((current) => [...current.slice(-199), data]);
          }
        }
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "事件流异常");
      } finally {
        if (!controller.signal.aborted) setConnected(false);
      }
    };
    connect();
    return () => controller.abort();
  }, [runId]);
  return { events, connected, error };
}

export default function RunsPage() {
  const { toast } = useApp();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<TestRun | null>(null);
  const [form, setForm] = useState({ project_id: "", suite_id: "", target_type: "agent" as "agent" | "model", agent_target_id: "", model_channel_id: "", evaluation_mode: "rules" as "rules" | "rules_with_llm_judge", judge_model_channel_id: "", max_concurrency: 2 });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => fetchPage<TestRun>("/runs?page=1&page_size=100"), refetchInterval: (query) => query.state.data?.items.some((item) => ["pending", "queued", "running", "waiting_approval"].includes(item.status)) ? 3000 : false });
  const projects = useQuery({ queryKey: ["projects", "run-selector"], queryFn: () => fetchPage<Project>("/projects?page=1&page_size=100") });
  const suites = useQuery({ queryKey: ["test-suites", "run-selector"], queryFn: () => fetchPage<TestSuite>("/test-suites?page=1&page_size=100") });
  const agents = useQuery({ queryKey: ["agents", "run-selector"], queryFn: () => fetchPage<AgentTarget>("/agents?page=1&page_size=100") });
  const models = useQuery({ queryKey: ["model-channels", "run-selector"], queryFn: () => fetchPage<ModelChannel>("/model-channels?page=1&page_size=100") });
  useEffect(() => { if (!form.project_id && projects.data?.items[0]) setForm((value) => ({ ...value, project_id: projects.data!.items[0].id })); }, [form.project_id, projects.data]);
  useEffect(() => { const candidate = suites.data?.items.find((item) => !item.project_id || item.project_id === form.project_id); if (!form.suite_id && candidate) setForm((value) => ({ ...value, suite_id: candidate.id })); }, [form.project_id, form.suite_id, suites.data]);
  useEffect(() => {
    if (form.target_type !== "agent") return;
    const candidate = agents.data?.items.find((item) => item.enabled !== false && (!item.project_id || item.project_id === form.project_id));
    if (candidate && !form.agent_target_id) setForm((value) => ({ ...value, agent_target_id: candidate.id }));
  }, [agents.data, form.agent_target_id, form.project_id, form.target_type]);
  useEffect(() => {
    if (form.target_type !== "model") return;
    const candidate = models.data?.items.find((item) => item.enabled !== false && (!item.project_id || item.project_id === form.project_id));
    if (candidate && !form.model_channel_id) setForm((value) => ({ ...value, model_channel_id: candidate.id }));
  }, [form.model_channel_id, form.project_id, form.target_type, models.data]);
  useEffect(() => {
    const fresh = runs.data?.items.find((item) => item.id === selected?.id);
    if (fresh) setSelected(fresh);
  }, [runs.data, selected?.id]);
  const needsApproval = selected?.status === "waiting_approval" && !selected.pause_requested;
  const approvals = useQuery({
    queryKey: ["approvals", selected?.project_id, selected?.id],
    queryFn: () => fetchPage<ApprovalRequest>(`/approvals?status_filter=pending&project_id=${encodeURIComponent(selected!.project_id)}&page=1&page_size=100`),
    enabled: Boolean(needsApproval && selected?.project_id),
  });
  const pendingApproval = approvals.data?.items.find((item) => item.run_id === selected?.id);
  const create = useMutation({ mutationFn: (data: unknown) => apiRequest<TestRun>("/runs", { method: "POST", body: data }), onSuccess: (result) => { client.invalidateQueries({ queryKey: ["runs"] }); setOpen(false); setSelected(result); toast({ title: "测试任务已入队", description: "Scope Guard 将在每个外部请求前执行判定。", tone: "success" }); } });
  const control = useMutation({ mutationFn: ({ id, action }: { id: string; action: "pause" | "resume" | "cancel" | "retry" }) => apiRequest<TestRun>(`/runs/${id}/${action}`, { method: "POST", body: {} }), onSuccess: (result, variables) => { client.invalidateQueries({ queryKey: ["runs"] }); setSelected((current) => current?.id === result.id ? { ...current, ...result } : current); toast({ title: `任务操作已提交：${variables.action}`, tone: "success" }); }, onError: (error) => toast({ title: "任务操作失败", description: error.message, tone: "error" }) });
  const decide = useMutation({
    mutationFn: ({ approvalId, status, reason }: { approvalId: string; status: "approved" | "rejected"; reason: string }) => apiRequest<ApprovalRequest>(`/approvals/${approvalId}/decision`, { method: "POST", body: { status, decision_reason: reason } }),
    onSuccess: async (_, variables) => {
      client.invalidateQueries({ queryKey: ["approvals"] });
      client.invalidateQueries({ queryKey: ["runs"] });
      if (selected) {
        try { setSelected(await apiRequest<TestRun>(`/runs/${selected.id}`)); } catch { /* polling will reconcile the run */ }
      }
      toast({ title: variables.status === "approved" ? "审批已通过，任务重新入队" : "审批已拒绝，任务已取消", tone: variables.status === "approved" ? "success" : "info" });
    },
    onError: (error) => toast({ title: "审批提交失败", description: error.message, tone: "error" }),
  });
  const stream = useRunEvents(selected?.id || null);
  const submit = (event: React.FormEvent) => { event.preventDefault(); const parsed = runInputSchema.safeParse(form); if (!parsed.success) { const next: Record<string, string> = {}; parsed.error.issues.forEach((issue) => { next[String(issue.path[0])] = issue.message; }); setErrors(next); return; } setErrors({}); create.mutate(runCreatePayload(parsed.data)); };
  const columns: Column<TestRun>[] = useMemo(() => [
    { key: "run", header: "运行", searchValue: (row) => `${row.name || ""} ${row.id} ${row.project_name || ""}`, render: (row) => <div><p className="font-medium">{row.name || `安全评估 ${shortId(row.id)}`}</p><p className="mt-1 text-[10px] text-muted-foreground">{row.project_name || "授权项目"} · {formatDate(row.created_at)}</p></div> },
    { key: "status", header: "状态", searchValue: (row) => row.status, render: (row) => <Badge tone={statusTone(row.status)}>{row.status === "waiting_approval" ? (row.pause_requested ? "等待恢复" : "等待审批") : row.status}</Badge> },
    { key: "progress", header: "进度", render: (row) => <div className="w-32"><div className="mb-1 flex justify-between font-mono text-[9px] text-muted-foreground"><span>{row.progress ?? (row.status === "completed" ? 100 : 0)}%</span><span>{row.status === "running" ? "LIVE" : ""}</span></div><div className="h-1.5 overflow-hidden rounded-full bg-muted"><div className={cn("h-full rounded-full bg-primary transition-all", row.status === "failed" && "bg-red-500")} style={{ width: `${Math.max(0, Math.min(100, row.progress ?? (row.status === "completed" ? 100 : 0)))}%` }} /></div></div> },
    { key: "score", header: "安全得分", render: (row) => <span className="font-mono text-sm font-semibold">{row.security_score ?? "—"}</span> },
    { key: "id", header: "请求 ID", searchValue: (row) => row.id, render: (row) => <span className="mono-value text-muted-foreground">{shortId(row.id)}</span> },
    { key: "actions", header: "操作", className: "text-right", render: (row) => <div className="flex justify-end gap-1"><Button size="sm" variant="ghost" onClick={() => setSelected(row)}><ScrollText className="h-3.5 w-3.5" />详情</Button>{row.status === "running" ? <Button aria-label="暂停任务" size="icon" variant="ghost" className="h-8 w-8" disabled={control.isPending} onClick={() => control.mutate({ id: row.id, action: "pause" })}><Pause className="h-3.5 w-3.5" /></Button> : null}{row.status === "waiting_approval" && row.pause_requested ? <Button aria-label="继续任务" size="icon" variant="ghost" className="h-8 w-8" disabled={control.isPending} onClick={() => control.mutate({ id: row.id, action: "resume" })}><Play className="h-3.5 w-3.5" /></Button> : null}{row.status === "failed" ? <Button aria-label="重试任务" size="icon" variant="ghost" className="h-8 w-8" disabled={control.isPending} onClick={() => control.mutate({ id: row.id, action: "retry" })}><RotateCcw className="h-3.5 w-3.5" /></Button> : null}</div> },
  ], [control]);
  const runAvailable = Boolean(projects.data?.items.length && suites.data?.items.length && (agents.data?.items.length || models.data?.items.length));
  return (
    <div>
      <PageHeader eyebrow="EXECUTION ENGINE" title="测试运行中心" description="异步批量执行安全测试，支持并发控制、暂停、取消、失败重试、超时与实时事件流。" actions={<Button onClick={() => setOpen(true)} disabled={!runAvailable}><Play className="h-4 w-4" />运行测试套件</Button>} />
      {!runAvailable && !projects.isLoading && !suites.isLoading && !agents.isLoading && !models.isLoading ? <div className="mb-4 rounded-xl border border-amber-500/25 bg-amber-500/10 p-4 text-xs text-amber-600 dark:text-amber-200">运行前至少需要一个项目、一个测试套件，以及一个已启用的 Agent 或模型渠道。</div> : null}
      <Card className="overflow-hidden shadow-none">{runs.isLoading ? <LoadingState label="正在读取任务队列…" /> : runs.error ? <ErrorState error={runs.error} onRetry={() => runs.refetch()} /> : <DataTable data={runs.data?.items || []} columns={columns} rowKey={(row) => row.id} searchPlaceholder="搜索运行、项目或请求 ID…" filters={["running", "waiting_approval", "completed", "failed", "cancelled"].map((status) => ({ label: status, value: status, matches: (row: TestRun) => row.status === status }))} emptyTitle="暂无测试运行" emptyDescription="选择项目、测试套件与 Mock Agent 发起首个安全评估。" />}</Card>
      <Dialog open={open} onOpenChange={setOpen}><DialogContent><DialogHeader><DialogTitle>运行安全测试套件</DialogTitle><DialogDescription>任务将进入轻量队列。所有网络与工具动作都必须通过策略校验。</DialogDescription></DialogHeader><form onSubmit={submit} className="space-y-4"><div><Label htmlFor="run-project">项目</Label><Select id="run-project" value={form.project_id} onChange={(event) => setForm({ ...form, project_id: event.target.value, suite_id: "", agent_target_id: "", model_channel_id: "" })}>{projects.data?.items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Select><FieldError>{errors.project_id}</FieldError></div><div><Label htmlFor="run-suite">测试套件</Label><Select id="run-suite" value={form.suite_id} onChange={(event) => setForm({ ...form, suite_id: event.target.value })}>{suites.data?.items.filter((item) => !item.project_id || item.project_id === form.project_id).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Select><FieldError>{errors.suite_id}</FieldError></div><div className="grid grid-cols-2 gap-4"><div><Label htmlFor="run-target">目标类型</Label><Select id="run-target" value={form.target_type} onChange={(event) => { const target_type = event.target.value as typeof form.target_type; setForm({ ...form, target_type, agent_target_id: target_type === "agent" ? form.agent_target_id : "", model_channel_id: target_type === "model" ? form.model_channel_id : "" }); }}><option value="agent">Agent（含本地 Mock）</option><option value="model">模型渠道</option></Select></div><div><Label htmlFor="run-concurrency">最大并发</Label><Input id="run-concurrency" type="number" min={1} max={8} value={form.max_concurrency} onChange={(event) => setForm({ ...form, max_concurrency: Number(event.target.value) })} /><FieldError>{errors.max_concurrency}</FieldError></div></div>{form.target_type === "agent" ? <div><Label htmlFor="run-agent">Agent 目标</Label><Select id="run-agent" value={form.agent_target_id} onChange={(event) => setForm({ ...form, agent_target_id: event.target.value })}><option value="">请选择 Agent</option>{agents.data?.items.filter((item) => item.enabled !== false && (!item.project_id || item.project_id === form.project_id)).map((item) => <option key={item.id} value={item.id}>{item.name}{item.agent_type === "mock-local" ? "（本地 Mock）" : ""}</option>)}</Select><FieldError>{errors.agent_target_id}</FieldError></div> : <div><Label htmlFor="run-model">模型渠道</Label><Select id="run-model" value={form.model_channel_id} onChange={(event) => setForm({ ...form, model_channel_id: event.target.value })}><option value="">请选择模型渠道</option>{models.data?.items.filter((item) => item.enabled !== false && (!item.project_id || item.project_id === form.project_id)).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.model}</option>)}</Select><FieldError>{errors.model_channel_id}</FieldError></div>}<div><Label htmlFor="run-evaluation">评分模式</Label><Select id="run-evaluation" value={form.evaluation_mode} onChange={(event) => setForm({ ...form, evaluation_mode: event.target.value as typeof form.evaluation_mode, judge_model_channel_id: event.target.value === "rules" ? "" : form.judge_model_channel_id })}><option value="rules">规则评分（推荐，零额外 Token）</option><option value="rules_with_llm_judge">规则 + LLM Judge</option></Select></div>{form.evaluation_mode === "rules_with_llm_judge" ? <div><Label htmlFor="run-judge-model">Judge 模型渠道</Label><Select id="run-judge-model" value={form.judge_model_channel_id} onChange={(event) => setForm({ ...form, judge_model_channel_id: event.target.value })}><option value="">请选择 Judge 渠道</option>{models.data?.items.filter((item) => item.enabled !== false).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.model}</option>)}</Select><FieldError>{errors.judge_model_channel_id}</FieldError></div> : null}<div className="rounded-lg border border-teal-500/20 bg-teal-500/[.05] p-3 text-xs leading-5 text-muted-foreground"><span className="font-medium text-foreground">安全默认：</span>规则评估优先、并发上限 8、敏感模拟工具进入审批、不执行未知 MCP Tool。</div>{create.error ? <p className="rounded-lg bg-red-500/10 p-3 text-xs text-red-400">{create.error.message}</p> : null}<DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>取消</Button><Button type="submit" loading={create.isPending}><TestTube2 className="h-4 w-4" />确认运行</Button></DialogFooter></form></DialogContent></Dialog>
      <Dialog open={Boolean(selected)} onOpenChange={(value) => !value && setSelected(null)}>
        <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
          <DialogHeader><DialogTitle>{selected?.name || `测试运行 ${shortId(selected?.id)}`}</DialogTitle><DialogDescription>实时事件流仅展示经过服务端脱敏的日志。</DialogDescription></DialogHeader>
          {selected ? <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4"><div className="rounded-lg border bg-muted/35 p-3"><p className="data-label">STATUS</p><div className="mt-2"><Badge tone={statusTone(selected.status)}>{selected.status === "waiting_approval" ? (selected.pause_requested ? "等待恢复" : "等待审批") : selected.status}</Badge></div></div><div className="rounded-lg border bg-muted/35 p-3"><p className="data-label">PROGRESS</p><p className="mt-2 font-mono text-sm">{selected.progress ?? 0}%</p></div><div className="rounded-lg border bg-muted/35 p-3"><p className="data-label">SCORE</p><p className="mt-2 font-mono text-sm">{selected.security_score ?? "—"}</p></div><div className="rounded-lg border bg-muted/35 p-3"><p className="data-label">STREAM</p><p className={cn("mt-2 text-xs", stream.connected ? "text-emerald-400" : "text-muted-foreground")}>{stream.connected ? "已连接" : "未连接"}</p></div></div>
            <div className="h-64 overflow-y-auto rounded-lg border bg-slate-950 p-3 font-mono text-[11px] leading-5 text-slate-300">{stream.events.length ? stream.events.map((event, index) => <div key={`${index}-${event.slice(0, 8)}`}><span className="mr-2 text-slate-600">{String(index + 1).padStart(3, "0")}</span>{event}</div>) : <div className="grid h-full place-items-center text-slate-600">{stream.error || (stream.connected ? "等待事件…" : "正在连接事件流…")}</div>}</div>
            {needsApproval ? <RunApprovalControls approval={pendingApproval} loading={approvals.isLoading} error={approvals.error} decisionError={decide.error} busy={decide.isPending} onRetry={() => approvals.refetch()} onDecision={(status, reason) => pendingApproval && decide.mutate({ approvalId: pendingApproval.id, status, reason })} /> : null}
            <div className="flex flex-wrap gap-2">
              {selected.status === "running" ? <Button size="sm" variant="outline" loading={control.isPending} onClick={() => control.mutate({ id: selected.id, action: "pause" })}><Pause className="h-3.5 w-3.5" />暂停</Button> : null}
              {selected.status === "waiting_approval" && selected.pause_requested ? <Button size="sm" variant="outline" loading={control.isPending} onClick={() => control.mutate({ id: selected.id, action: "resume" })}><Play className="h-3.5 w-3.5" />继续</Button> : null}
              {["pending", "queued", "running", "waiting_approval"].includes(selected.status) ? <Button size="sm" variant="destructive" disabled={control.isPending || decide.isPending} onClick={() => control.mutate({ id: selected.id, action: "cancel" })}><Square className="h-3.5 w-3.5" />取消任务</Button> : null}
              {selected.status === "failed" ? <Button size="sm" loading={control.isPending} onClick={() => control.mutate({ id: selected.id, action: "retry" })}><RotateCcw className="h-3.5 w-3.5" />失败重试</Button> : null}
              {["completed", "cancelled"].includes(selected.status) ? <Button size="sm" variant="outline" disabled title="终态任务无需控制"><Ban className="h-3.5 w-3.5" />任务已结束</Button> : null}
            </div>
          </> : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
