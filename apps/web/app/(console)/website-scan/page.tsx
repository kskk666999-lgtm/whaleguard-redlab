"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileCheck2,
  Globe2,
  KeyRound,
  LoaderCircle,
  LockKeyhole,
  Play,
  Radar,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { useApp } from "@/components/providers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { FieldError, Input, Label, Select } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { apiRequest, fetchPage } from "@/lib/api";
import { websiteModelChannelCreatePayload, websiteScanCreatePayload } from "@/lib/contracts";
import { websiteModelSetupSchema, websiteScanInputSchema } from "@/lib/schemas";
import type { ModelChannel, Project, WebsiteScan, WebsiteScanCheck } from "@/lib/types";
import { formatDate, maskSecret } from "@/lib/utils";

type Provider = "openai-compatible" | "deepseek-compatible" | "glm-compatible" | "qwen-compatible";

const providerPresets: Record<Provider, { name: string; base_url: string; model: string }> = {
  "openai-compatible": { name: "我的 OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  "deepseek-compatible": { name: "我的 DeepSeek", base_url: "https://api.deepseek.com/v1", model: "deepseek-chat" },
  "glm-compatible": { name: "我的 GLM", base_url: "https://open.bigmodel.cn/api/paas/v4", model: "glm-4-flash" },
  "qwen-compatible": { name: "我的 Qwen", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus" },
};

const progressSteps = [
  "确认网站可以安全访问",
  "检查安全响应头与传输保护",
  "检查身份与浏览器侧加固线索",
  "检查公开的 AI、Agent 与 Tool 风险线索",
  "保存脱敏证据并生成报告",
];

function hasStoredKey(channel: ModelChannel) {
  return Boolean(channel.api_key_masked?.trim());
}

function aiState(scan: WebsiteScan) {
  const state = scan.ai_analysis?.status || scan.ai_status || (scan.ai_used ? "used" : scan.ai_degraded ? "degraded" : "not_requested");
  if (state === "used") return { label: "AI 增强解读已完成", tone: "success" as const, detail: scan.ai_analysis?.summary || scan.ai_summary || "模型已对脱敏规则结果完成防御解释。" };
  if (state === "degraded") return { label: "规则分析已完成，AI 增强解析失败", tone: "warning" as const, detail: scan.ai_analysis?.error || scan.ai_analysis?.summary || "规则结果、证据和报告仍然有效。" };
  return { label: "本次未使用 AI", tone: "neutral" as const, detail: "确定性规则检查已经完成；需要时可选择已连接模型生成额外解读。" };
}

function checkTone(check: WebsiteScanCheck) {
  if (check.status === "passed") return "success" as const;
  if (check.status === "failed" || check.severity === "high" || check.severity === "critical") return "danger" as const;
  if (check.status === "warning" || check.severity === "medium") return "warning" as const;
  return "info" as const;
}

export default function WebsiteScanPage() {
  const { toast } = useApp();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ target_url: "", model_channel_id: "", authorization_confirmed: false, generate_report: true as const, safety_level: "safe_read_only" as const });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [latestResult, setLatestResult] = useState<WebsiteScan | null>(null);
  const [showModelSetup, setShowModelSetup] = useState(false);
  const [modelForm, setModelForm] = useState({ provider: "deepseek-compatible" as Provider, ...providerPresets["deepseek-compatible"], api_key: "" });
  const [modelErrors, setModelErrors] = useState<Record<string, string>>({});

  const projects = useQuery({ queryKey: ["projects", "website-scan"], queryFn: () => fetchPage<Project>("/projects?page=1&page_size=100") });
  const channels = useQuery({ queryKey: ["model-channels"], queryFn: () => fetchPage<ModelChannel>("/model-channels?page=1&page_size=100") });
  const history = useQuery({ queryKey: ["website-scans", "recent"], queryFn: () => fetchPage<WebsiteScan>("/website-scans?page=1&page_size=5") });
  const activeProjects = useMemo(() => (projects.data?.items || []).filter((item) => item.status !== "archived"), [projects.data]);
  const usableChannels = useMemo(() => (channels.data?.items || []).filter((item) => item.enabled && hasStoredKey(item)), [channels.data]);
  const selectedChannel = usableChannels.find((item) => item.id === form.model_channel_id);

  const createModel = useMutation({
    mutationFn: async () => {
      const projectId = activeProjects[0]?.id;
      if (!projectId) throw new Error("请先完成一次规则体检，平台会自动创建隔离项目，然后即可接入模型");
      const parsed = websiteModelSetupSchema.safeParse({ ...modelForm, project_id: projectId, authorization_confirmed: true });
      if (!parsed.success) {
        const next: Record<string, string> = {};
        parsed.error.issues.forEach((issue) => { next[String(issue.path[0])] = issue.message; });
        setModelErrors(next);
        throw new Error("请修正模型配置后再保存");
      }
      setModelErrors({});
      const channel = await apiRequest<ModelChannel>("/model-channels", { method: "POST", body: websiteModelChannelCreatePayload(parsed.data), timeoutMs: 30_000 });
      const connection = await apiRequest<{ success: boolean; message: string; latency_ms?: number }>(`/model-channels/${channel.id}/test-connection`, { method: "POST", body: {}, timeoutMs: 90_000 });
      return { channel, connection };
    },
    onSuccess: ({ channel, connection }) => {
      setModelForm((current) => ({ ...current, api_key: "" }));
      setForm((current) => ({ ...current, model_channel_id: channel.id }));
      queryClient.invalidateQueries({ queryKey: ["model-channels"] });
      toast({ title: connection.success ? "真实 AI 已连接" : "模型已保存，但连接未通过", description: connection.message, tone: connection.success ? "success" : "error" });
    },
  });

  const scan = useMutation({
    mutationFn: (input: Parameters<typeof websiteScanCreatePayload>[0]) => apiRequest<WebsiteScan>("/website-scans", { method: "POST", body: websiteScanCreatePayload(input), timeoutMs: 120_000 }),
    onMutate: () => setLatestResult(null),
    onSuccess: (result) => {
      setLatestResult(result);
      ["website-scans", "projects", "findings", "reports"].forEach((key) => queryClient.invalidateQueries({ queryKey: [key] }));
      toast({ title: "网站体检完成", description: `安全分 ${result.security_score ?? 0}，发现 ${result.finding_count ?? 0} 项需要复核。`, tone: "success" });
    },
  });

  const regenerateAi = useMutation({
    mutationFn: ({ scanId, channelId }: { scanId: string; channelId: string }) => apiRequest<WebsiteScan>(`/website-scans/${scanId}/ai-analysis`, { method: "POST", body: { model_channel_id: channelId }, timeoutMs: 90_000 }),
    onSuccess: (result) => {
      setLatestResult(result);
      toast({ title: result.ai_analysis?.status === "used" ? "AI 解读已重新生成" : "规则结果仍有效", description: aiState(result).detail, tone: result.ai_analysis?.status === "used" ? "success" : "error" });
    },
  });

  const submitScan = (event: React.FormEvent) => {
    event.preventDefault();
    const parsed = websiteScanInputSchema.safeParse(form);
    if (!parsed.success) {
      const next: Record<string, string> = {};
      parsed.error.issues.forEach((issue) => { next[String(issue.path[0])] = issue.message; });
      setErrors(next);
      return;
    }
    setErrors({});
    scan.mutate(parsed.data);
  };

  if (projects.isLoading || channels.isLoading) return <LoadingState label="正在准备安全体检…" />;
  if (projects.error || channels.error) return <ErrorState error={projects.error || channels.error} onRetry={() => { projects.refetch(); channels.refetch(); }} />;
  const result = latestResult;
  const resultAi = result ? aiState(result) : null;

  return (
    <div>
      <PageHeader eyebrow="SAFE WEBSITE CHECK" title="检查我自己的网站" description="输入网址、确认授权、开始检查。Project、精确 Scope、证据与报告由平台在后台安全建立。" />
      <div className="mb-5 grid gap-3 md:grid-cols-3">
        {[
          { icon: Radar, title: "安全只读", text: "只发一条受控 GET 请求；不爆破、不利用漏洞、不提交表单。" },
          { icon: ShieldCheck, title: "逐跳范围保护", text: "DNS 和每次重定向都重新检查，离开授权目标立即停止。" },
          { icon: LockKeyhole, title: "AI 完全可选", text: "没有 API Key 也能得到规则结果、证据与报告。" },
        ].map((item) => <Card key={item.title} className="shadow-none"><CardContent className="flex gap-3 p-4"><div className="rounded-lg bg-primary/10 p-2 text-primary"><item.icon className="h-4 w-4" /></div><div><p className="text-xs font-semibold">{item.title}</p><p className="mt-1 text-[11px] leading-5 text-muted-foreground">{item.text}</p></div></CardContent></Card>)}
      </div>

      <form onSubmit={submitScan} className="space-y-4">
        <Card className="shadow-none"><CardHeader><StepTitle number="1" title="输入网址" detail="只检查这一条精确地址，不自动发现子域名或其他页面。" /></CardHeader><CardContent><Label htmlFor="scan-url">你拥有或已获授权的网站</Label><div className="flex flex-col gap-2 sm:flex-row"><div className="relative flex-1"><Globe2 className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input id="scan-url" type="url" value={form.target_url} onChange={(event) => setForm((current) => ({ ...current, target_url: event.target.value }))} className="pl-10 font-mono" placeholder="http://host.docker.internal:8080" /></div><Button type="button" variant="outline" onClick={() => setForm((current) => ({ ...current, target_url: "http://mock-agent:8102/demo-site" }))}>使用内置靶场</Button></div><FieldError>{errors.target_url}</FieldError><p className="mt-2 text-[11px] text-muted-foreground">Windows 本机网站通常填写 <span className="font-mono text-foreground">http://host.docker.internal:端口</span></p></CardContent></Card>

        <Card className="shadow-none"><CardHeader><StepTitle number="2" title="确认安全边界" detail="不确认授权，平台不会发送任何网络请求。" /></CardHeader><CardContent className="space-y-4"><div><Label htmlFor="safety-level">检查级别</Label><Select id="safety-level" value={form.safety_level} onChange={() => undefined}><option value="safe_read_only">安全只读检查（推荐）</option></Select></div><label className="flex cursor-pointer items-start gap-3 rounded-xl border bg-muted/35 p-4"><input type="checkbox" checked={form.authorization_confirmed} onChange={(event) => setForm((current) => ({ ...current, authorization_confirmed: event.target.checked }))} className="mt-0.5 h-4 w-4 accent-teal-500" /><span><span className="block text-sm font-medium">我确认这是我拥有或明确授权测试的系统</span><span className="mt-1 block text-xs leading-5 text-muted-foreground">我只允许低风险、只读检查，并接受完整策略审计记录。</span></span></label><FieldError>{errors.authorization_confirmed}</FieldError></CardContent></Card>

        <Card className="shadow-none"><CardHeader><StepTitle number="3" title="可选：让真实 AI 帮你解释" detail="AI 只读取脱敏规则摘要，不会接触目标网站，也不会改变规则结论。" /></CardHeader><CardContent className="space-y-3"><div><Label htmlFor="scan-model">模型渠道</Label><Select id="scan-model" value={form.model_channel_id} onChange={(event) => setForm((current) => ({ ...current, model_channel_id: event.target.value }))}><option value="">暂不使用 AI（规则体检照常工作）</option>{usableChannels.map((channel) => <option key={channel.id} value={channel.id}>{channel.name} · {channel.model}</option>)}</Select></div>{selectedChannel ? <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/35 px-3 py-2 text-xs"><Badge tone="success">已连接</Badge><span>{selectedChannel.name}</span><span className="font-mono text-muted-foreground">{maskSecret(selectedChannel.api_key_masked || undefined)}</span></div> : null}<button type="button" className="focus-ring flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left text-xs hover:bg-muted" aria-expanded={showModelSetup} onClick={() => setShowModelSetup((value) => !value)}><span className="flex items-center gap-2"><KeyRound className="h-4 w-4 text-primary" />接入新的 API Key</span>{showModelSetup ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}</button>{showModelSetup ? <ModelSetup form={modelForm} setForm={setModelForm} errors={modelErrors} pending={createModel.isPending} canCreate={Boolean(activeProjects.length)} onSubmit={() => createModel.mutate()} error={createModel.error} /> : null}</CardContent></Card>

        {scan.error ? <p role="alert" className="rounded-lg border border-red-500/25 bg-red-500/10 p-3 text-xs text-red-400">{scan.error.message}</p> : null}
        <Button type="submit" size="lg" className="w-full" loading={scan.isPending}><Play className="h-4 w-4" />{scan.isPending ? "正在安全检查…" : "开始检查我的网站"}</Button>
      </form>

      {scan.isPending ? <Card className="mt-6 border-primary/25 shadow-none" aria-live="polite"><CardHeader><div><p className="data-label text-primary">CHECKING</p><h2 className="mt-1 text-base font-semibold">正在检查，请保持此页面打开</h2></div><LoaderCircle className="h-5 w-5 animate-spin text-primary" /></CardHeader><CardContent className="space-y-2">{progressSteps.map((step, index) => <div key={step} className="flex items-center gap-3 rounded-lg border bg-muted/25 px-3 py-2 text-xs"><span className="grid h-6 w-6 place-items-center rounded-full bg-primary/10 font-mono text-primary">{index + 1}</span>{step}</div>)}</CardContent></Card> : null}

      {result ? <ResultPanel result={result} ai={resultAi!} channelId={form.model_channel_id || result.model_channel_id || ""} retrying={regenerateAi.isPending} onRetry={(channelId) => regenerateAi.mutate({ scanId: result.id, channelId })} /> : null}

      <Card className="mt-6 shadow-none"><CardHeader><div><h2 className="text-sm font-semibold">最近体检</h2><p className="mt-1 text-xs text-muted-foreground">最近 5 次安全只读检查。</p></div></CardHeader><CardContent>{history.isLoading ? <LoadingState className="min-h-24" label="正在读取记录…" /> : history.error ? <ErrorState error={history.error} onRetry={() => history.refetch()} /> : history.data?.items.length ? <div className="space-y-2">{history.data.items.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border px-3 py-2"><div><p className="font-mono text-xs">{item.target_url}</p><p className="mt-1 text-[10px] text-muted-foreground">{formatDate(item.created_at)}</p></div><div className="flex items-center gap-2"><Badge tone={item.status === "completed" ? "success" : "warning"}>{item.status === "completed" ? "已完成" : item.status}</Badge><span className="text-sm font-semibold">{item.security_score ?? "—"} 分</span></div></div>)}</div> : <p className="py-6 text-center text-xs text-muted-foreground">还没有体检记录。输入内置靶场即可安全体验第一份报告。</p>}</CardContent></Card>
    </div>
  );
}

function StepTitle({ number, title, detail }: { number: string; title: string; detail: string }) {
  return <div className="flex items-center gap-3"><span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground">{number}</span><div><h2 className="text-sm font-semibold">{title}</h2><p className="mt-1 text-xs text-muted-foreground">{detail}</p></div></div>;
}

type ModelForm = { provider: Provider; name: string; base_url: string; model: string; api_key: string };

function ModelSetup({ form, setForm, errors, pending, canCreate, onSubmit, error }: { form: ModelForm; setForm: React.Dispatch<React.SetStateAction<ModelForm>>; errors: Record<string, string>; pending: boolean; canCreate: boolean; onSubmit: () => void; error: Error | null }) {
  return <div className="rounded-xl border p-4"><div className="grid gap-4 md:grid-cols-2"><div><Label htmlFor="quick-provider">服务商</Label><Select id="quick-provider" value={form.provider} onChange={(event) => { const provider = event.target.value as Provider; setForm((current) => ({ ...current, provider, ...providerPresets[provider] })); }}><option value="openai-compatible">OpenAI Compatible</option><option value="deepseek-compatible">DeepSeek Compatible</option><option value="glm-compatible">GLM Compatible</option><option value="qwen-compatible">Qwen Compatible</option></Select></div><div><Label htmlFor="quick-name">显示名称</Label><Input id="quick-name" value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} /><FieldError>{errors.name}</FieldError></div><div><Label htmlFor="quick-base-url">模型 API 地址</Label><Input id="quick-base-url" type="url" value={form.base_url} onChange={(event) => setForm((current) => ({ ...current, base_url: event.target.value }))} /><FieldError>{errors.base_url}</FieldError></div><div><Label htmlFor="quick-model">模型名称</Label><Input id="quick-model" value={form.model} onChange={(event) => setForm((current) => ({ ...current, model: event.target.value }))} /><FieldError>{errors.model}</FieldError></div><div className="md:col-span-2"><Label htmlFor="quick-key">API Key</Label><Input id="quick-key" type="password" autoComplete="new-password" value={form.api_key} onChange={(event) => setForm((current) => ({ ...current, api_key: event.target.value }))} placeholder="仅本次提交可见，不写入浏览器存储" /><FieldError>{errors.api_key}</FieldError></div></div>{!canCreate ? <p className="mt-3 text-xs text-amber-500">先完成一次规则体检，平台自动创建隔离项目后即可接入模型。</p> : null}{error ? <p className="mt-3 text-xs text-red-400">{error.message}</p> : null}<div className="mt-4 flex justify-end"><Button type="button" loading={pending} disabled={!canCreate} onClick={onSubmit}><BrainCircuit className="h-4 w-4" />保存并测试真实连接</Button></div></div>;
}

function ResultPanel({ result, ai, channelId, retrying, onRetry }: { result: WebsiteScan; ai: ReturnType<typeof aiState>; channelId: string; retrying: boolean; onRetry: (channelId: string) => void }) {
  const score = result.security_score ?? 0;
  return <section className="mt-6 space-y-4" aria-label="网站体检结果"><Card className="overflow-hidden border-primary/25 shadow-none"><CardHeader><div><p className="data-label text-primary">CHECK COMPLETED</p><h2 className="mt-1 text-lg font-semibold">体检完成，下一步已经准备好</h2></div><Badge tone="success">已完成</Badge></CardHeader><CardContent className="grid gap-5 lg:grid-cols-[180px_1fr]"><div className="flex flex-col items-center justify-center rounded-xl border bg-muted/30 p-5"><span className="text-5xl font-semibold tracking-tight text-primary">{score}</span><span className="mt-1 text-xs text-muted-foreground">安全分 / 100</span><span className="mt-3 text-xs">{result.finding_count ?? 0} 项需复核</span></div><div className="space-y-3"><div className="rounded-xl border p-4"><div className="flex flex-wrap items-center gap-2"><Sparkles className="h-4 w-4 text-primary" /><p className="text-sm font-medium">分析结果</p><Badge tone={ai.tone}>{ai.label}</Badge></div><p className="mt-2 text-xs leading-6 text-muted-foreground">{ai.detail}</p>{result.ai_analysis?.priorities?.length ? <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-muted-foreground">{result.ai_analysis.priorities.map((item) => <li key={item}>{item}</li>)}</ul> : null}{channelId && result.ai_analysis?.status === "degraded" ? <Button type="button" size="sm" variant="outline" className="mt-3" loading={retrying} onClick={() => onRetry(channelId)}><RefreshCw className="h-3.5 w-3.5" />只重新生成 AI 解读</Button> : null}</div><p className="rounded-xl border p-4 text-xs leading-6 text-muted-foreground">{result.score_explanation || "分数由本机确定性规则计算；AI 不会覆盖 Finding 或原始证据。"}</p><div className="flex flex-wrap gap-2"><Button asChild><Link href="/reports"><FileCheck2 className="h-4 w-4" />查看报告</Link></Button><Button asChild variant="outline"><Link href="/findings"><TriangleAlert className="h-4 w-4" />查看发现的问题</Link></Button></div></div></CardContent></Card><Card className="shadow-none"><CardHeader><div><h2 className="text-sm font-semibold">检查了什么</h2><p className="mt-1 text-xs text-muted-foreground">这些是只读风险线索，不是漏洞可利用性的证明。</p></div></CardHeader><CardContent className="space-y-2">{result.checks?.map((check, index) => <div key={check.id || `${check.name}-${index}`} className="flex flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:items-start sm:justify-between"><div><p className="flex items-center gap-2 text-sm font-medium">{check.status === "passed" ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : <TriangleAlert className="h-4 w-4 text-amber-400" />}{check.name}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">{check.explanation || check.message || "已完成检查"}</p>{check.remediation ? <p className="mt-1 text-xs leading-5 text-primary">建议：{check.remediation}</p> : null}</div><Badge tone={checkTone(check)}>{check.status === "passed" ? "正常" : "需复核"}</Badge></div>)}</CardContent></Card></section>;
}
