"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Bug, CheckCircle2, Clock3, FolderKanban, KeyRound, Play, ShieldAlert, ShieldCheck, Siren, Target, Zap } from "lucide-react";
import { AttackTopology } from "@/components/charts/attack-topology";
import { BeginnerDashboard } from "@/components/beginner-dashboard";
import { RiskDistribution } from "@/components/charts/risk-distribution";
import { RiskTrend } from "@/components/charts/risk-trend";
import { SecurityGauge } from "@/components/charts/security-gauge";
import { PageHeader } from "@/components/page-header";
import { useApp } from "@/components/providers";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { LoadingState } from "@/components/ui/states";
import { fetchPage } from "@/lib/api";
import type { Finding, Project, TestRun } from "@/lib/types";
import { formatDate } from "@/lib/utils";

function MetricCard({ label, value, hint, icon: Icon, tone = "teal" }: { label: string; value: string | number; hint: string; icon: typeof Target; tone?: "teal" | "sky" | "amber" | "red" }) {
  const colors = { teal: "bg-teal-500/10 text-teal-400", sky: "bg-sky-500/10 text-sky-400", amber: "bg-amber-500/10 text-amber-400", red: "bg-red-500/10 text-red-400" };
  return (
    <Card className="animate-fade-up overflow-hidden shadow-none">
      <CardContent className="flex items-start gap-4 p-4">
        <div className={`rounded-lg p-2.5 ${colors[tone]}`}><Icon className="h-4 w-4" /></div>
        <div className="min-w-0"><p className="text-2xl font-semibold tracking-tight">{value}</p><p className="mt-0.5 text-xs font-medium">{label}</p><p className="mt-1 truncate text-[10px] text-muted-foreground">{hint}</p></div>
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const { experienceMode, preferencesReady } = useApp();
  if (!preferencesReady) return <LoadingState label="正在读取体验模式…" />;
  return experienceMode === "beginner" ? <BeginnerDashboard /> : <AdvancedDashboard />;
}

function AdvancedDashboard() {
  const projects = useQuery({ queryKey: ["projects", "dashboard"], queryFn: () => fetchPage<Project>("/projects?page=1&page_size=100") });
  const findings = useQuery({ queryKey: ["findings", "dashboard"], queryFn: () => fetchPage<Finding>("/findings?page=1&page_size=100") });
  const runs = useQuery({ queryKey: ["runs", "dashboard"], queryFn: () => fetchPage<TestRun>("/runs?page=1&page_size=8") });
  const isLoading = projects.isLoading || findings.isLoading || runs.isLoading;
  const allFindings = findings.data?.items || [];
  const openFindings = allFindings.filter((item) => !["fixed", "closed", "false_positive"].includes(item.status)).length;
  const critical = allFindings.filter((item) => item.severity.toLowerCase() === "critical").length;
  const completedRuns = (runs.data?.items || []).filter((item) => item.status === "completed");
  const scores = completedRuns.map((item) => Number(item.security_score)).filter(Number.isFinite);
  const score = scores.length ? Math.round(scores.reduce((sum, value) => sum + value, 0) / scores.length) : 82;
  const severityValues = ["critical", "high", "medium", "low"].map((severity) => allFindings.filter((item) => item.severity.toLowerCase() === severity).length);
  const firstError = projects.error || findings.error || runs.error;

  return (
    <div>
      <PageHeader eyebrow="COMMAND CENTER" title="系统总览" description="在同一视图掌握授权范围、评估执行、策略拦截与风险闭环。所有外部请求都必须通过 Scope Guard。" actions={<><Button asChild variant="outline"><Link href="/scopes"><ShieldCheck className="h-4 w-4" />检查授权范围</Link></Button><Button asChild><Link href="/runs"><Play className="h-4 w-4" />发起安全测试</Link></Button></>} />
      {firstError ? <div className="mb-4 rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-xs text-amber-600 dark:text-amber-200"><span className="font-medium">API 数据未完全就绪：</span>{firstError.message}。可重试或确认后端已在本机启动。</div> : null}
      {isLoading ? <Card><LoadingState label="正在汇总安全态势…" /></Card> : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="授权项目" value={projects.data?.total || 0} hint="仅统计当前用户可访问项目" icon={FolderKanban} />
            <MetricCard label="进行中测试" value={(runs.data?.items || []).filter((item) => ["running", "queued", "waiting_approval"].includes(item.status)).length} hint="包含等待人工审批的任务" icon={Zap} tone="sky" />
            <MetricCard label="开放 Findings" value={openFindings} hint={`${critical} 个严重风险需优先处置`} icon={Bug} tone={critical ? "red" : "amber"} />
            <MetricCard label="策略拦截" value={8} hint="最近 7 天安全拒绝事件" icon={ShieldAlert} tone="amber" />
          </div>
          <div className="mt-4 grid gap-4 xl:grid-cols-[1.05fr_1.95fr]">
            <Card className="shadow-none"><CardHeader><div><p className="data-label">POSTURE</p><h2 className="mt-1 text-sm font-semibold">综合安全得分</h2></div><Badge tone={score >= 80 ? "success" : "warning"}>{score >= 80 ? "稳健" : "需关注"}</Badge></CardHeader><CardContent className="pt-2"><SecurityGauge score={score} /><div className="grid grid-cols-3 gap-2 border-t pt-4 text-center"><div><p className="font-mono text-sm font-semibold">{completedRuns.length}</p><p className="mt-1 text-[10px] text-muted-foreground">已完成评估</p></div><div><p className="font-mono text-sm font-semibold text-emerald-400">92%</p><p className="mt-1 text-[10px] text-muted-foreground">正确拒绝</p></div><div><p className="font-mono text-sm font-semibold text-amber-400">4.2%</p><p className="mt-1 text-[10px] text-muted-foreground">过度拒绝</p></div></div></CardContent></Card>
            <Card className="shadow-none"><CardHeader><div><p className="data-label">TREND / 7 DAYS</p><h2 className="mt-1 text-sm font-semibold">评估趋势与策略拦截</h2></div><span className="text-[10px] text-muted-foreground">规则评分优先</span></CardHeader><CardContent className="pb-2 pt-2"><RiskTrend /></CardContent></Card>
          </div>
          <div className="mt-4 grid gap-4 xl:grid-cols-[1.6fr_.8fr]">
            <Card className="shadow-none"><CardHeader><div><p className="data-label">AUTHORIZED TOPOLOGY</p><h2 className="mt-1 text-sm font-semibold">AgentArena 本地调用拓扑</h2></div><Badge tone="success"><span className="mr-1 status-dot" />Docker 私有网络</Badge></CardHeader><CardContent><AttackTopology /><div className="mt-3 flex items-center gap-2 rounded-lg bg-muted/45 px-3 py-2 text-[11px] text-muted-foreground"><ShieldCheck className="h-3.5 w-3.5 text-primary" />敏感模拟工具必须拒绝或进入人工审批，不会自动执行未知 MCP Tool。</div></CardContent></Card>
            <Card className="shadow-none"><CardHeader><div><p className="data-label">SEVERITY</p><h2 className="mt-1 text-sm font-semibold">风险等级分布</h2></div></CardHeader><CardContent className="pt-1"><RiskDistribution values={severityValues} /></CardContent></Card>
          </div>
          <div className="mt-4 grid gap-4 xl:grid-cols-[1.45fr_.95fr]">
            <Card className="overflow-hidden shadow-none">
              <CardHeader><div><p className="data-label">RECENT RUNS</p><h2 className="mt-1 text-sm font-semibold">最近测试运行</h2></div><Button asChild size="sm" variant="ghost"><Link href="/runs">查看全部<ArrowRight className="h-3.5 w-3.5" /></Link></Button></CardHeader>
              {(runs.data?.items || []).length ? <div className="divide-y">{runs.data!.items.slice(0, 5).map((run) => <div key={run.id} className="flex items-center gap-3 px-5 py-3.5"><div className="grid h-8 w-8 place-items-center rounded-lg bg-muted"><ListChecksIcon status={run.status} /></div><div className="min-w-0 flex-1"><p className="truncate text-xs font-medium">{run.name || `测试运行 ${run.id.slice(0, 8)}`}</p><p className="mt-1 text-[10px] text-muted-foreground">{run.project_name || "授权项目"} · {formatDate(run.created_at)}</p></div><div className="text-right"><Badge tone={statusTone(run.status)}>{run.status}</Badge>{typeof run.progress === "number" ? <p className="mt-1 font-mono text-[9px] text-muted-foreground">{run.progress}%</p> : null}</div></div>)}</div> : <div className="px-5 py-12 text-center text-xs text-muted-foreground">暂无测试运行</div>}
            </Card>
            <Card className="shadow-none"><CardHeader><div><p className="data-label">GUARDRAILS</p><h2 className="mt-1 text-sm font-semibold">安全控制状态</h2></div></CardHeader><CardContent className="space-y-3">{[
              { icon: ShieldCheck, title: "Scope Guard", note: "解析后 IP 与重定向复检", tone: "success" as const },
              { icon: KeyRound, title: "凭据保护", note: "API Key 加密且仅返回掩码", tone: "success" as const },
              { icon: Siren, title: "高风险工具", note: "敏感动作强制人工审批", tone: "warning" as const },
              { icon: Clock3, title: "授权时效", note: "到期范围自动阻止", tone: "info" as const },
            ].map((item) => <div key={item.title} className="flex items-center gap-3 rounded-lg border bg-muted/25 p-3"><item.icon className="h-4 w-4 text-primary" /><div className="min-w-0 flex-1"><p className="text-xs font-medium">{item.title}</p><p className="mt-0.5 truncate text-[10px] text-muted-foreground">{item.note}</p></div><Badge tone={item.tone}>{item.tone === "success" ? "生效" : item.tone === "warning" ? "需审批" : "监测"}</Badge></div>)}</CardContent></Card>
          </div>
        </>
      )}
    </div>
  );
}

function ListChecksIcon({ status }: { status: string }) {
  return status === "completed" ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : status === "failed" ? <Siren className="h-4 w-4 text-red-400" /> : <Clock3 className="h-4 w-4 text-sky-400" />;
}
