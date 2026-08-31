"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpenCheck,
  CheckCircle2,
  Clock3,
  FileSearch,
  Globe2,
  GraduationCap,
  ScanSearch,
  ShieldCheck,
} from "lucide-react";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { apiRequest, fetchPage, getSystemStatus } from "@/lib/api";
import type {
  AcademySummary,
  Finding,
  Project,
  SystemServiceStatus,
  TestRun,
} from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";

const primaryActions = [
  {
    title: "学习 AI 安全",
    description: "进入本地安全学院，用虚构数据完成攻击、取证、修复和复测。",
    href: "/academy",
    action: "开始学习",
    note: "不需要 API Key · 仅本地请求",
    icon: BookOpenCheck,
  },
  {
    title: "检查我的网站",
    description: "对你拥有或获得明确授权的网站执行低风险、只读的配置体检。",
    href: "/website-scan",
    action: "开始体检",
    note: "需要确认授权 · 受 Scope Guard 保护",
    icon: ScanSearch,
  },
  {
    title: "查看已有结果",
    description: "查看已经形成的 Findings、证据与修复建议，不会重新发起测试。",
    href: "/findings",
    action: "查看 Findings",
    note: "只读取本地平台数据",
    icon: FileSearch,
  },
];

function serviceTone(status: SystemServiceStatus["status"]) {
  if (status === "normal") return "success" as const;
  if (status === "abnormal") return "danger" as const;
  if (status === "optional") return "info" as const;
  return "warning" as const;
}

function serviceLabel(status: SystemServiceStatus["status"]) {
  if (status === "normal") return "正常";
  if (status === "abnormal") return "异常";
  if (status === "optional") return "可选";
  return "未启动";
}

export function BeginnerDashboard() {
  const projects = useQuery({
    queryKey: ["projects", "beginner-dashboard"],
    queryFn: () => fetchPage<Project>("/projects?page=1&page_size=100"),
  });
  const findings = useQuery({
    queryKey: ["findings", "beginner-dashboard"],
    queryFn: () => fetchPage<Finding>("/findings?page=1&page_size=20"),
  });
  const runs = useQuery({
    queryKey: ["runs", "beginner-dashboard"],
    queryFn: () => fetchPage<TestRun>("/runs?page=1&page_size=20"),
  });
  const systemStatus = useQuery({
    queryKey: ["system-status", "beginner-dashboard"],
    queryFn: getSystemStatus,
  });
  const activeProject = (projects.data?.items || []).find((project) => project.status !== "archived");
  const academy = useQuery({
    queryKey: ["academy-summary", "beginner-dashboard", activeProject?.id],
    queryFn: () => apiRequest<AcademySummary>(`/academy?project_id=${encodeURIComponent(activeProject!.id)}`),
    enabled: Boolean(activeProject?.id),
  });

  const recentResults = useMemo(() => {
    const findingRows = (findings.data?.items || []).map((item) => ({
      id: `finding-${item.id}`,
      title: item.title,
      meta: `Finding · ${item.severity}`,
      status: item.status,
      createdAt: item.created_at,
      href: "/findings",
    }));
    const runRows = (runs.data?.items || []).map((item) => ({
      id: `run-${item.id}`,
      title: item.name || `测试运行 ${item.id.slice(0, 8)}`,
      meta: "测试运行",
      status: item.status,
      createdAt: item.created_at,
      href: "/runs",
    }));
    return [...findingRows, ...runRows]
      .sort((left, right) => new Date(right.createdAt || 0).getTime() - new Date(left.createdAt || 0).getTime())
      .slice(0, 6);
  }, [findings.data, runs.data]);

  const progress = academy.data?.scenario_count
    ? Math.round((academy.data.completed_count / academy.data.scenario_count) * 100)
    : 0;
  const loading = projects.isLoading || findings.isLoading || runs.isLoading || systemStatus.isLoading;
  const firstError = projects.error || findings.error || runs.error;

  return (
    <div>
      <section className="rounded-2xl border bg-card/65 p-5 shadow-sm sm:p-7">
        <p className="data-label text-primary">BEGINNER HOME / 新手首页</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-[-.04em]">你今天想做什么？</h1>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">选择一个真实入口即可开始。WhaleGuard 不会替你扫描其他网站，任何网络检查都需要明确授权并经过 Scope Guard。</p>
        <div className="mt-6 grid gap-3 lg:grid-cols-3">
          {primaryActions.map((item) => (
            <Card key={item.href} className="group shadow-none transition-colors hover:border-primary/35">
              <CardContent className="flex h-full flex-col p-5">
                <div className="grid h-10 w-10 place-items-center rounded-xl bg-primary/10 text-primary"><item.icon className="h-5 w-5" /></div>
                <h2 className="mt-5 text-base font-semibold">{item.title}</h2>
                <p className="mt-2 flex-1 text-xs leading-6 text-muted-foreground">{item.description}</p>
                <p className="mt-4 text-[11px] text-muted-foreground">{item.note}</p>
                <Button asChild className="mt-4 w-full" variant="outline"><Link href={item.href}>{item.action}<ArrowRight className="h-4 w-4" /></Link></Button>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section className="mt-8" aria-labelledby="beginner-progress-title">
        <div className="mb-4"><p className="data-label text-primary">YOUR WORKSPACE</p><h2 id="beginner-progress-title" className="mt-1 text-xl font-semibold">你的进度和最近结果</h2><p className="mt-1 text-xs text-muted-foreground">以下数字全部来自当前账号的真实数据。</p></div>
        {firstError ? <div className="mb-4 rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-xs text-amber-600 dark:text-amber-200">部分数据暂时无法读取：{firstError.message}</div> : null}
        {loading ? <Card><LoadingState label="正在读取你的真实进度…" /></Card> : (
          <div className="grid gap-4 xl:grid-cols-[.85fr_1.3fr]">
            <div className="space-y-4">
              <Card className="shadow-none">
                <CardHeader><div><p className="data-label">ACADEMY</p><h3 className="mt-1 text-sm font-semibold">安全学院进度</h3></div><GraduationCap className="h-4 w-4 text-primary" /></CardHeader>
                <CardContent>
                  {!activeProject ? <EmptyState title="还没有可用项目" description="创建项目后，学院进度会按项目保存。" action={<Button asChild size="sm" variant="outline"><Link href="/projects">创建项目</Link></Button>} /> : academy.isLoading ? <LoadingState label="正在读取学院进度…" /> : academy.error ? <ErrorState error={academy.error} onRetry={() => void academy.refetch()} /> : academy.data ? (
                    <>
                      <div className="flex items-end justify-between gap-3"><div><p className="text-3xl font-semibold">{academy.data.completed_count}<span className="text-base text-muted-foreground"> / {academy.data.scenario_count}</span></p><p className="mt-1 text-xs text-muted-foreground">已完成场景</p></div><Badge tone={progress === 100 ? "success" : "info"}>{progress}%</Badge></div>
                      <div className="mt-4 h-2 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${progress}%` }} /></div>
                      <Button asChild className="mt-5 w-full" variant="outline"><Link href="/academy">继续学习<ArrowRight className="h-4 w-4" /></Link></Button>
                    </>
                  ) : null}
                </CardContent>
              </Card>
              <Card className="shadow-none">
                <CardHeader><div><p className="data-label">COUNTS</p><h3 className="mt-1 text-sm font-semibold">当前数据</h3></div></CardHeader>
                <CardContent className="grid grid-cols-3 gap-2 text-center">
                  <div className="rounded-lg bg-muted/35 p-3"><p className="font-mono text-lg font-semibold">{projects.data?.total || 0}</p><p className="mt-1 text-[10px] text-muted-foreground">项目</p></div>
                  <div className="rounded-lg bg-muted/35 p-3"><p className="font-mono text-lg font-semibold">{runs.data?.total || 0}</p><p className="mt-1 text-[10px] text-muted-foreground">测试运行</p></div>
                  <div className="rounded-lg bg-muted/35 p-3"><p className="font-mono text-lg font-semibold">{findings.data?.total || 0}</p><p className="mt-1 text-[10px] text-muted-foreground">Findings</p></div>
                </CardContent>
              </Card>
            </div>

            <Card className="overflow-hidden shadow-none">
              <CardHeader><div><p className="data-label">RECENT RESULTS</p><h3 className="mt-1 text-sm font-semibold">最近结果</h3></div><Button asChild size="sm" variant="ghost"><Link href="/findings">查看全部<ArrowRight className="h-3.5 w-3.5" /></Link></Button></CardHeader>
              {recentResults.length ? <div className="divide-y">{recentResults.map((item) => (
                <Link key={item.id} href={item.href} className="flex items-center gap-3 px-5 py-4 transition-colors hover:bg-muted/35">
                  <div className="grid h-8 w-8 place-items-center rounded-lg bg-muted"><CheckCircle2 className="h-4 w-4 text-primary" /></div>
                  <div className="min-w-0 flex-1"><p className="truncate text-xs font-medium">{item.title}</p><p className="mt-1 text-[10px] text-muted-foreground">{item.meta} · {formatDate(item.createdAt)}</p></div>
                  <Badge tone={statusTone(item.status)}>{item.status}</Badge>
                </Link>
              ))}</div> : <EmptyState title="还没有检查结果" description="完成一次安全学院练习或网站体检后，结果会显示在这里。" action={<Button asChild size="sm"><Link href="/academy">从安全学院开始</Link></Button>} />}
            </Card>
          </div>
        )}
      </section>

      <section className="mt-8" aria-labelledby="beginner-system-title">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3"><div><p className="data-label text-primary">SYSTEM STATUS</p><h2 id="beginner-system-title" className="mt-1 text-xl font-semibold">本地系统状态</h2></div><Button variant="outline" size="sm" loading={systemStatus.isFetching} onClick={() => void systemStatus.refetch()}><Clock3 className="h-3.5 w-3.5" />重新检测</Button></div>
        {systemStatus.error ? <Card><ErrorState error={systemStatus.error} onRetry={() => void systemStatus.refetch()} /></Card> : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {Object.entries(systemStatus.data?.services || {}).map(([key, service]) => (
              <Card key={key} className="shadow-none"><CardContent className="flex items-start gap-3 p-4"><ShieldCheck className={cn("mt-0.5 h-4 w-4", service.status === "normal" ? "text-emerald-400" : "text-amber-400")} /><div className="min-w-0 flex-1"><p className="text-xs font-semibold">{service.label}</p><p className="mt-1 text-[11px] leading-5 text-muted-foreground">{service.detail}</p></div><Badge tone={serviceTone(service.status)}>{serviceLabel(service.status)}</Badge></CardContent></Card>
            ))}
          </div>
        )}
      </section>
      <div className="mt-5 flex items-center gap-2 rounded-xl border bg-muted/25 px-4 py-3 text-xs text-muted-foreground"><Globe2 className="h-4 w-4 text-primary" />只有网站体检会向你明确授权的目标发送受限请求；学习和查看结果只使用本地服务。</div>
    </div>
  );
}
