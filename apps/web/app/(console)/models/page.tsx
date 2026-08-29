"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cable, KeyRound, Plus, RadioTower, ShieldCheck } from "lucide-react";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { useApp } from "@/components/providers";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Select } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { apiRequest, fetchPage } from "@/lib/api";
import { modelChannelInputSchema } from "@/lib/schemas";
import type { ApiRecord } from "@/lib/types";
import { formatDate, maskSecret } from "@/lib/utils";

type ModelChannel = ApiRecord & { name: string; provider: string; base_url: string; model: string; enabled?: boolean; api_key_masked?: string; status?: string; last_tested_at?: string; timeout?: number; max_tokens?: number; temperature?: number };

const initialForm = { name: "", provider: "openai-compatible" as "openai-compatible" | "deepseek-compatible" | "glm-compatible" | "qwen-compatible" | "ollama-compatible", base_url: "http://127.0.0.1:11434/v1", api_key: "", model: "", timeout: 60, max_tokens: 2048, temperature: 0, enabled: true };

export default function ModelsPage() {
  const { toast } = useApp();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(initialForm);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [testingId, setTestingId] = useState<string | null>(null);
  const query = useQuery({ queryKey: ["model-channels"], queryFn: () => fetchPage<ModelChannel>("/model-channels?page=1&page_size=100") });
  const create = useMutation({ mutationFn: (data: typeof initialForm) => apiRequest<ModelChannel>("/model-channels", { method: "POST", body: { ...data, api_key: data.api_key || undefined } }), onSuccess: () => { client.invalidateQueries({ queryKey: ["model-channels"] }); setOpen(false); setForm(initialForm); toast({ title: "模型渠道已添加", description: "密钥已交由后端加密保存，前端不会再次读取明文。", tone: "success" }); } });
  const test = useMutation({ mutationFn: (id: string) => apiRequest<{ success?: boolean; message?: string; latency_ms?: number }>(`/model-channels/${id}/test-connection`, { method: "POST", body: {} }), onMutate: (id) => setTestingId(id), onSuccess: (result) => { toast({ title: result.success === false ? "连接测试未通过" : "连接测试成功", description: result.message || (result.latency_ms ? `响应延迟 ${result.latency_ms} ms` : "渠道返回有效响应。"), tone: result.success === false ? "error" : "success" }); client.invalidateQueries({ queryKey: ["model-channels"] }); }, onError: (error) => toast({ title: "连接测试失败", description: error.message, tone: "error" }), onSettled: () => setTestingId(null) });
  const submit = (event: React.FormEvent) => { event.preventDefault(); const parsed = modelChannelInputSchema.safeParse(form); if (!parsed.success) { const next: Record<string, string> = {}; parsed.error.issues.forEach((issue) => { next[String(issue.path[0])] = issue.message; }); setErrors(next); return; } setErrors({}); create.mutate(parsed.data as typeof initialForm); };
  const columns: Column<ModelChannel>[] = [
    { key: "name", header: "渠道", searchValue: (row) => `${row.name} ${row.provider} ${row.model}`, render: (row) => <div><p className="font-medium">{row.name}</p><p className="mt-1 text-[10px] uppercase tracking-wide text-muted-foreground">{row.provider}</p></div> },
    { key: "model", header: "模型", searchValue: (row) => row.model, render: (row) => <span className="font-mono text-xs">{row.model}</span> },
    { key: "url", header: "Base URL", searchValue: (row) => row.base_url, render: (row) => <span className="block max-w-60 truncate font-mono text-[11px] text-muted-foreground">{row.base_url}</span> },
    { key: "key", header: "API Key", render: (row) => <span className="font-mono text-[11px] text-muted-foreground">{maskSecret(row.api_key_masked)}</span> },
    { key: "state", header: "状态", searchValue: (row) => row.status || (row.enabled ? "enabled" : "disabled"), render: (row) => <Badge tone={statusTone(row.status || (row.enabled ? "enabled" : "disabled"))}>{row.status || (row.enabled ? "enabled" : "disabled")}</Badge> },
    { key: "tested", header: "最近测试", render: (row) => <span className="text-xs text-muted-foreground">{formatDate(row.last_tested_at)}</span> },
    { key: "actions", header: "操作", className: "text-right", render: (row) => <Button size="sm" variant="outline" loading={testingId === row.id} disabled={!row.enabled || (testingId !== null && testingId !== row.id)} onClick={() => test.mutate(row.id)}><Cable className="h-3.5 w-3.5" />测试连接</Button> },
  ];
  return (
    <div>
      <PageHeader eyebrow="MODEL GATEWAY" title="模型渠道" description="统一管理 OpenAI-Compatible 模型端点。API Key 仅提交一次并加密保存，列表接口只返回掩码。" actions={<Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" />添加渠道</Button>} />
      <div className="mb-4 flex items-start gap-3 rounded-xl border border-teal-500/20 bg-teal-500/[.045] p-4 text-xs"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-teal-400" /><p className="leading-5 text-muted-foreground"><span className="font-medium text-foreground">凭据安全：</span>浏览器不会持久化模型密钥；后端日志与错误响应必须脱敏。Ollama 本地渠道可以不填写 API Key。</p></div>
      <Card className="overflow-hidden shadow-none">{query.isLoading ? <LoadingState /> : query.error ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : <DataTable data={query.data?.items || []} columns={columns} rowKey={(row) => row.id} searchPlaceholder="搜索渠道、模型或 Base URL…" filters={[{ label: "已启用", value: "enabled", matches: (row) => row.enabled !== false }, { label: "已禁用", value: "disabled", matches: (row) => row.enabled === false }]} emptyTitle="尚未配置模型渠道" emptyDescription="可以先使用 Docker 私有网络中的 Mock LLM 完成无外部依赖评估。" />}</Card>
      <Dialog open={open} onOpenChange={setOpen}><DialogContent className="max-w-2xl"><DialogHeader><DialogTitle>添加模型渠道</DialogTitle><DialogDescription>支持 OpenAI Compatible、DeepSeek、GLM、Qwen 与 Ollama 兼容接口。</DialogDescription></DialogHeader><form onSubmit={submit} className="space-y-4"><div className="grid gap-4 sm:grid-cols-2"><div><Label htmlFor="model-name">渠道名称</Label><Input id="model-name" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="本地 Ollama" /><FieldError>{errors.name}</FieldError></div><div><Label htmlFor="provider">Provider</Label><Select id="provider" value={form.provider} onChange={(event) => setForm({ ...form, provider: event.target.value as typeof form.provider })}><option value="openai-compatible">OpenAI Compatible</option><option value="deepseek-compatible">DeepSeek Compatible</option><option value="glm-compatible">GLM Compatible</option><option value="qwen-compatible">Qwen Compatible</option><option value="ollama-compatible">Ollama Compatible</option></Select></div></div><div><Label htmlFor="base-url">Base URL</Label><Input id="base-url" type="url" value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} /><FieldError>{errors.base_url}</FieldError></div><div className="grid gap-4 sm:grid-cols-2"><div><Label htmlFor="model-id">模型 ID</Label><Input id="model-id" value={form.model} onChange={(event) => setForm({ ...form, model: event.target.value })} placeholder="qwen3:8b / deepseek-chat" /><FieldError>{errors.model}</FieldError></div><div><Label htmlFor="api-key">API Key（可选）</Label><div className="relative"><KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input id="api-key" type="password" autoComplete="new-password" value={form.api_key} onChange={(event) => setForm({ ...form, api_key: event.target.value })} className="pl-10" placeholder="仅本次提交可见" /></div></div></div><div className="grid grid-cols-3 gap-3"><div><Label htmlFor="timeout">超时（秒）</Label><Input id="timeout" type="number" min={1} max={300} value={form.timeout} onChange={(event) => setForm({ ...form, timeout: Number(event.target.value) })} /></div><div><Label htmlFor="max-tokens">Max tokens</Label><Input id="max-tokens" type="number" min={1} max={32768} value={form.max_tokens} onChange={(event) => setForm({ ...form, max_tokens: Number(event.target.value) })} /></div><div><Label htmlFor="temperature">Temperature</Label><Input id="temperature" type="number" step="0.1" min={0} max={2} value={form.temperature} onChange={(event) => setForm({ ...form, temperature: Number(event.target.value) })} /></div></div><label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} className="h-4 w-4 accent-teal-500" />创建后立即启用</label>{create.error ? <p className="rounded-lg bg-red-500/10 p-3 text-xs text-red-400">{create.error.message}</p> : null}<DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>取消</Button><Button type="submit" loading={create.isPending}><RadioTower className="h-4 w-4" />保存渠道</Button></DialogFooter></form></DialogContent></Dialog>
    </div>
  );
}
