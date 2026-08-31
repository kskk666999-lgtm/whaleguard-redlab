"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  ArrowLeft,
  BookOpenCheck,
  CheckCircle2,
  ClipboardCheck,
  DatabaseZap,
  Eraser,
  FileCheck2,
  FileSearch,
  FlaskConical,
  Lightbulb,
  LockKeyhole,
  MessageSquareText,
  Network,
  Play,
  RefreshCcw,
  RotateCcw,
  ShieldCheck,
  ShieldOff,
  Target,
  Trophy,
  Wrench,
} from "lucide-react";
import { AcademyAttackStoryTimeline } from "@/components/academy/attack-story-timeline";
import { AcademyAttackTrace } from "@/components/academy/attack-trace";
import { AcademyKnowledgeReview } from "@/components/academy/knowledge-review";
import { AcademyLearningCycle } from "@/components/academy/learning-cycle";
import { AcademyScenarioComparison } from "@/components/academy/scenario-comparison";
import { AcademyWhaleTutor } from "@/components/academy/whale-tutor";
import { PageHeader } from "@/components/page-header";
import { useApp } from "@/components/providers";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Label, Select, Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { apiRequest, fetchPage } from "@/lib/api";
import type {
  AcademyAttackStory,
  AcademyComparison,
  AcademyEvent,
  AcademyRoadmap,
  AcademyScenario,
  AcademySession,
  Project,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type AcademyMode = "vulnerable" | "hardened";

type EvidenceResponse = {
  correct: boolean;
  matched_event_types: string[];
  missing_event_types: string[];
  score: number;
  evidence_complete: boolean;
};

type MitigationResponse = {
  correct: boolean;
  selected_choice_id: string;
  score: number;
  mitigation_complete: boolean;
};

type HintResponse = {
  level: number;
  kind: "idea" | "location" | "near_solution" | "solution";
  text?: string | null;
  walkthrough?: AcademyScenario["walkthrough"] | null;
  hints_used: number[];
  score: number;
};

const traceGroupOrder = ["Input / Agent", "RAG / Vector", "Memory", "MCP / Tool", "Identity / Auth", "Output / Guard"];

function traceGroup(eventType: string) {
  if (eventType.includes(".rag.") || eventType.includes(".vector.") || eventType.includes(".context.")) return "RAG / Vector";
  if (eventType.includes(".memory.")) return "Memory";
  if (eventType.includes(".mcp.") || eventType.includes(".tool.") || eventType.includes(".supply_chain.")) return "MCP / Tool";
  if (eventType.includes(".identity.") || eventType.includes(".authz.") || eventType.includes(".human.")) return "Identity / Auth";
  if (eventType.includes(".output.") || eventType.includes(".secret.") || eventType.includes(".egress.") || eventType.includes(".guard.") || eventType.includes(".resource.")) return "Output / Guard";
  return "Input / Agent";
}

function resultLabel(session?: AcademySession) {
  if (!session) return "尚未执行";
  if (session.mode === "vulnerable") return session.exploit_success ? "漏洞已复现" : "未触发漏洞";
  return session.defense_success ? "防护已验证" : "防护未通过";
}

function resultTone(session?: AcademySession) {
  if (!session) return "neutral" as const;
  if (session.mode === "vulnerable") return session.exploit_success ? "danger" as const : "warning" as const;
  return session.defense_success ? "success" as const : "danger" as const;
}

function SessionSummary({ title, session }: { title: string; session?: AcademySession }) {
  return (
    <div className={cn(
      "rounded-xl border p-4",
      session?.mode === "vulnerable" && session.exploit_success && "border-red-500/30 bg-red-500/[.06]",
      session?.mode === "hardened" && session.defense_success && "border-emerald-500/30 bg-emerald-500/[.06]",
    )}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold">{title}</p>
        <Badge tone={resultTone(session)}>{resultLabel(session)}</Badge>
      </div>
      {session ? (
        <dl className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
          <div><dt className="text-muted-foreground">判定方式</dt><dd className="mt-0.5 font-mono">event rules</dd></div>
          <div><dt className="text-muted-foreground">事件数</dt><dd className="mt-0.5 font-mono">{session.events.length}</dd></div>
          <div><dt className="text-muted-foreground">攻击识别</dt><dd className="mt-0.5 font-mono">{session.attack_detected ? "YES" : "NO"}</dd></div>
          <div><dt className="text-muted-foreground">本次得分</dt><dd className="mt-0.5 font-mono">+{session.score_awarded}</dd></div>
        </dl>
      ) : <p className="mt-3 text-[11px] leading-5 text-muted-foreground">等待同一 payload 的执行结果。</p>}
    </div>
  );
}

function EventDetails({ event, checked, onToggle }: { event: AcademyEvent; checked: boolean; onToggle: () => void }) {
  const selectable = event.status === "violation" || event.risk === "high" || event.risk === "critical";
  return (
    <label className={cn("block rounded-lg border bg-background/45 p-3", checked && "border-primary/45 bg-primary/[.05]")}>
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          className="mt-0.5 h-4 w-4 accent-teal-500"
          aria-label={"选择事件 " + event.event_type}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[10px] text-primary">#{event.sequence}</span>
            <span className="break-all font-mono text-[10px]">{event.event_type}</span>
            <Badge tone={statusTone(event.status)}>{event.status}</Badge>
            {selectable ? <Badge tone="danger">evidence candidate</Badge> : null}
          </div>
          <p className="mt-1.5 text-xs leading-5">{event.summary}</p>
          <p className="mt-1 text-[10px] text-muted-foreground">{event.source} → {event.target}</p>
          {Object.keys(event.details).length ? (
            <details className="mt-2">
              <summary className="cursor-pointer text-[10px] text-muted-foreground hover:text-foreground">查看事件字段</summary>
              <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-slate-950 p-2 text-[10px] leading-4 text-slate-200">{JSON.stringify(event.details, null, 2)}</pre>
            </details>
          ) : null}
        </div>
      </div>
    </label>
  );
}

export function ScenarioWorkbench({ scenarioId }: { scenarioId: string }) {
  const { toast } = useApp();
  const queryClient = useQueryClient();
  const [projectId, setProjectId] = useState("");
  const [mode, setMode] = useState<AcademyMode>("vulnerable");
  const [payload, setPayload] = useState("");
  const [payloadSeedKey, setPayloadSeedKey] = useState("");
  const [vulnerableSession, setVulnerableSession] = useState<AcademySession>();
  const [hardenedSession, setHardenedSession] = useState<AcademySession>();
  const [hydratedSessionId, setHydratedSessionId] = useState("");
  const [selectedEventIds, setSelectedEventIds] = useState<string[]>([]);
  const [mitigationChoice, setMitigationChoice] = useState("");
  const [guess, setGuess] = useState("");

  const projects = useQuery({
    queryKey: ["projects", "academy-workbench"],
    queryFn: () => fetchPage<Project>("/projects?page=1&page_size=100"),
  });
  const activeProjects = useMemo(
    () => (projects.data?.items || []).filter((project) => project.status !== "archived"),
    [projects.data],
  );

  useEffect(() => {
    if (!activeProjects.some((project) => project.id === projectId)) setProjectId(activeProjects[0]?.id || "");
  }, [activeProjects, projectId]);

  const scenario = useQuery({
    queryKey: ["academy-scenario", scenarioId, projectId],
    queryFn: () => apiRequest<AcademyScenario>("/academy/scenarios/" + scenarioId + "?project_id=" + encodeURIComponent(projectId)),
    enabled: Boolean(projectId),
  });
  const lastSessionId = scenario.data?.progress.last_session_id || "";
  const lastSession = useQuery({
    queryKey: ["academy-session", lastSessionId],
    queryFn: () => apiRequest<AcademySession>("/academy/sessions/" + lastSessionId),
    enabled: Boolean(lastSessionId),
  });
  const activeSessionId = (mode === "vulnerable" ? vulnerableSession?.id : hardenedSession?.id) || "";
  const comparisonSessionId = hardenedSession?.id || vulnerableSession?.id || "";
  const attackStory = useQuery({
    queryKey: ["academy-attack-story", activeSessionId],
    queryFn: () => apiRequest<AcademyAttackStory>(`/academy/sessions/${activeSessionId}/attack-story`),
    enabled: Boolean(activeSessionId),
  });
  const comparison = useQuery({
    queryKey: ["academy-comparison", comparisonSessionId],
    queryFn: () => apiRequest<AcademyComparison>(`/academy/sessions/${comparisonSessionId}/comparison`),
    enabled: Boolean(comparisonSessionId),
  });
  const roadmap = useQuery({
    queryKey: ["academy-roadmap", projectId],
    queryFn: () => apiRequest<AcademyRoadmap>(`/academy/roadmap?project_id=${encodeURIComponent(projectId)}`),
    enabled: Boolean(projectId),
  });

  useEffect(() => {
    const key = projectId + ":" + scenarioId;
    if (scenario.data && payloadSeedKey !== key) {
      setPayload(scenario.data.start_state.starter_prompt);
      setPayloadSeedKey(key);
      setVulnerableSession(undefined);
      setHardenedSession(undefined);
      setHydratedSessionId("");
      setSelectedEventIds([]);
      setMitigationChoice("");
      setGuess("");
    }
  }, [payloadSeedKey, projectId, scenario.data, scenarioId]);

  useEffect(() => {
    if (lastSession.data && hydratedSessionId !== lastSession.data.id) {
      if (lastSession.data.mode === "vulnerable") setVulnerableSession(lastSession.data);
      else setHardenedSession(lastSession.data);
      setHydratedSessionId(lastSession.data.id);
    }
  }, [hydratedSessionId, lastSession.data]);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["academy-scenario", scenarioId, projectId] });
    queryClient.invalidateQueries({ queryKey: ["academy-scenarios", projectId] });
    queryClient.invalidateQueries({ queryKey: ["academy-summary", projectId] });
    queryClient.invalidateQueries({ queryKey: ["academy-state", projectId] });
    queryClient.invalidateQueries({ queryKey: ["academy-roadmap", projectId] });
    queryClient.invalidateQueries({ queryKey: ["academy-skills", projectId] });
    queryClient.invalidateQueries({ queryKey: ["academy-attack-story"] });
    queryClient.invalidateQueries({ queryKey: ["academy-comparison"] });
  };

  const execute = useMutation({
    mutationFn: ({ runMode, runPayload }: { runMode: AcademyMode; runPayload: string }) => apiRequest<AcademySession>(
      "/academy/scenarios/" + scenarioId + "/execute",
      { method: "POST", body: { project_id: projectId, mode: runMode, payload: runPayload } },
    ),
    onSuccess: (session) => {
      if (session.mode === "vulnerable") {
        setVulnerableSession(session);
        setSelectedEventIds([]);
      } else {
        setHardenedSession(session);
      }
      refresh();
      toast({
        title: resultLabel(session),
        description: session.mode === "vulnerable"
          ? "结果由 Trace 中的真实事件组合判定，成功时已自动归档 Finding / Evidence。"
          : "已使用 Hardened 配置执行，检查阻断事件而非模型回答。",
        tone: session.exploit_success || session.defense_success ? "success" : "info",
      });
    },
  });

  const replay = useMutation({
    mutationFn: () => {
      if (!vulnerableSession) throw new Error("请先在 Vulnerable 模式完成一次执行");
      return apiRequest<AcademySession>("/academy/sessions/" + vulnerableSession.id + "/replay", {
        method: "POST",
        body: { mode: "hardened" },
      });
    },
    onSuccess: (session) => {
      setHardenedSession(session);
      setMode("hardened");
      refresh();
      toast({
        title: session.defense_success ? "相同 payload 已被阻断" : "Hardened 回放仍需检查",
        description: "服务器使用原执行记录中的 payload 原样回放，哈希可用于核对。",
        tone: session.defense_success ? "success" : "info",
      });
    },
  });

  const evidence = useMutation({
    mutationFn: () => {
      if (!vulnerableSession) throw new Error("请先完成 Vulnerable 利用");
      return apiRequest<EvidenceResponse>("/academy/sessions/" + vulnerableSession.id + "/evidence", {
        method: "POST",
        body: { event_ids: selectedEventIds },
      });
    },
    onSuccess: (result) => {
      refresh();
      toast({
        title: result.correct ? "证据链选择正确" : "证据链仍不完整",
        description: result.correct ? "已证明 Source → Unsafe Decision → Sink。" : "缺少事件：" + result.missing_event_types.join("、"),
        tone: result.correct ? "success" : "info",
      });
    },
  });

  const mitigation = useMutation({
    mutationFn: () => apiRequest<MitigationResponse>("/academy/scenarios/" + scenarioId + "/mitigation", {
      method: "POST",
      body: { project_id: projectId, choice_id: mitigationChoice },
    }),
    onSuccess: (result) => {
      refresh();
      toast({
        title: result.correct ? "修复策略选择正确" : "这项修复不足以切断攻击链",
        description: result.correct ? "下一步用相同 payload 回放 Hardened 模式。" : "结合 Trace 中的危险边界重新判断。",
        tone: result.correct ? "success" : "info",
      });
    },
  });

  const hint = useMutation({
    mutationFn: (action: 1 | 2 | 3 | "solution") => {
      const path = action === "solution"
        ? `/academy/scenarios/${scenarioId}/solution`
        : `/academy/scenarios/${scenarioId}/hints/${action}`;
      return apiRequest<HintResponse>(path, {
        method: "POST",
        body: { project_id: projectId },
      });
    },
    onSuccess: (result) => {
      refresh();
      toast({
        title: result.kind === "solution" ? "完整解法已显示" : `第 ${result.level} 级提示已显示`,
        description: "提示成本已计入本关得分，当前分数 " + result.score + "。",
        tone: "info",
      });
    },
  });

  const maintenance = useMutation({
    mutationFn: (action: "seed" | "memory" | "reset") => {
      const path = action === "seed"
        ? "/academy/fake-data/seed"
        : action === "memory"
          ? "/academy/memory/clear"
          : "/academy/scenarios/" + scenarioId + "/reset";
      return apiRequest<Record<string, unknown>>(path, { method: "POST", body: { project_id: projectId } });
    },
    onSuccess: (_result, action) => {
      if (action === "reset") {
        setVulnerableSession(undefined);
        setHardenedSession(undefined);
        setSelectedEventIds([]);
        setMitigationChoice("");
        setPayload(scenario.data?.start_state.starter_prompt || "");
        setMode("vulnerable");
        setHydratedSessionId(lastSessionId);
      }
      refresh();
      toast({
        title: action === "seed" ? "虚构数据已重新生成" : action === "memory" ? "跨会话记忆已清空" : "本关已重置",
        description: action === "reset"
          ? "只清理本关易失实验状态；历史进度、Finding、Evidence、报告和项目均会保留。"
          : "操作只影响当前项目中的本地 Academy 数据。",
        tone: "success",
      });
    },
  });

  if (projects.isLoading) return <LoadingState label="正在准备 Academy 场景…" />;
  if (projects.error) return <ErrorState error={projects.error} onRetry={() => projects.refetch()} />;
  if (!activeProjects.length) {
    return <EmptyState title="需要一个学习项目" description="请先在项目中心创建项目，Academy 进度、Finding 与 Evidence 将按项目隔离。" action={<Button asChild><Link href="/projects">前往项目中心</Link></Button>} />;
  }
  if (scenario.isLoading) return <LoadingState label={"正在加载 " + scenarioId + "…"} />;
  if (scenario.error || !scenario.data) return <ErrorState error={scenario.error || new Error("场景不存在")} onRetry={() => scenario.refetch()} />;

  const data = scenario.data;
  const currentSession = mode === "vulnerable" ? vulnerableSession : hardenedSession;
  const groupedEvents = traceGroupOrder.map((group) => ({
    group,
    events: currentSession?.events.filter((event) => traceGroup(event.event_type) === group) || [],
  })).filter((item) => item.events.length);
  const usedHints = new Set(data.progress.hints_used);
  const nextHint = ([1, 2, 3] as const).find((level) => !usedHints.has(level));
  const storyData = attackStory.data && Array.isArray(attackStory.data.timeline)
    ? attackStory.data
    : undefined;
  const comparisonData = comparison.data && typeof comparison.data.ready === "boolean"
    ? comparison.data
    : undefined;
  const nextLesson = roadmap.data?.next_lesson;
  const nextRoadmapItem = roadmap.data?.items.find((item) => (
    item.scenario_id !== scenarioId
    && (item.status === "available" || item.status === "in_progress")
  ));
  const nextTarget = nextLesson && nextLesson.scenario_id !== scenarioId
    ? { scenarioId: nextLesson.scenario_id, title: nextLesson.title, action: nextLesson.action }
    : nextRoadmapItem
      ? { scenarioId: nextRoadmapItem.scenario_id, title: nextRoadmapItem.title, action: "start" as const }
      : undefined;
  const lesson = data.lesson || {
    goal: data.learning_objectives[0] || "理解本关风险",
    why_it_matters: data.story,
    real_world_example: "类似问题可能出现在连接数据与工具的 AI 应用中。",
    learning_cycle: ["learn", "guess", "do", "see", "fix", "retest", "summary"],
  };
  const completedSteps = [
    "learn",
    ...(guess.trim() ? ["guess"] : []),
    ...(vulnerableSession ? ["do"] : []),
    ...(storyData ? ["see"] : []),
    ...(data.progress.mitigation_complete ? ["fix"] : []),
    ...(hardenedSession?.defense_success ? ["retest"] : []),
    ...(data.progress.completed ? ["summary"] : []),
  ];

  const restartChallenge = () => {
    setMode("vulnerable");
    setPayload(data.start_state.starter_prompt);
    setVulnerableSession(undefined);
    setHardenedSession(undefined);
    setSelectedEventIds([]);
    setMitigationChoice("");
    setGuess("");
    setHydratedSessionId(lastSessionId);
    toast({
      title: "已准备重新挑战",
      description: "历史记录和总进度没有改变；下一次提交会创建一条新的执行记录。",
      tone: "info",
    });
  };

  return (
    <div>
      <PageHeader
        eyebrow={data.difficulty.toUpperCase() + " · " + data.id}
        title={data.title}
        description={data.story}
        actions={
          <>
            <Button asChild variant="outline"><Link href="/academy/scenarios"><ArrowLeft className="h-4 w-4" />返回场景库</Link></Button>
            <Button variant="outline" onClick={restartChallenge}><RefreshCcw className="h-4 w-4" />重新挑战</Button>
            <Button
              variant="outline"
              disabled={maintenance.isPending}
              onClick={() => {
                if (window.confirm("确认重置本关的易失实验状态？历史进度、Finding、Evidence、报告和项目都会保留。")) maintenance.mutate("reset");
              }}
            ><RotateCcw className="h-4 w-4" />重置本关</Button>
          </>
        }
      />

      <AcademyLearningCycle completed={completedSteps} />

      <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Card className="shadow-none"><CardContent className="p-4"><p className="data-label">DIFFICULTY</p><p className="mt-2 text-sm font-semibold">{data.difficulty} · {"★".repeat(data.difficulty_stars)}</p><p className="mt-1 text-[11px] text-muted-foreground">预计 {data.estimated_time} 分钟</p></CardContent></Card>
        <Card className="shadow-none"><CardContent className="p-4"><p className="data-label">SCORE</p><p className="mt-2 font-mono text-xl font-semibold">{data.progress.score}/{data.progress.max_score}</p><p className="mt-1 text-[11px] text-muted-foreground">利用 60 · 证据 20 · 修复 20 · 回放 25</p></CardContent></Card>
        <Card className="shadow-none"><CardContent className="p-4"><p className="data-label">SUCCESS EVALUATOR</p><p className="mt-2 text-sm font-semibold">Deterministic Events</p><p className="mt-1 text-[11px] text-muted-foreground">不接受静态 Flag 或模型自评</p></CardContent></Card>
        <Card className="shadow-none"><CardContent className="p-4"><p className="data-label">NETWORK</p><p className="mt-2 flex items-center gap-2 text-sm font-semibold text-emerald-500"><Network className="h-4 w-4" />Public Egress OFF</p><p className="mt-1 text-[11px] text-muted-foreground">{data.scope.network_requests}</p></CardContent></Card>
      </div>

      <Card className="mb-5 shadow-none">
        <CardContent className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
          <div><Label htmlFor="academy-workbench-project">学习项目</Label><Select id="academy-workbench-project" value={projectId} onChange={(event) => setProjectId(event.target.value)}>{activeProjects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</Select></div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" disabled={maintenance.isPending} onClick={() => maintenance.mutate("seed")}><DatabaseZap className="h-3.5 w-3.5" />Seed Fake Data</Button>
            <Button variant="outline" size="sm" disabled={maintenance.isPending} onClick={() => maintenance.mutate("memory")}><Eraser className="h-3.5 w-3.5" />Clear Memory</Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-5 xl:grid-cols-[1.1fr_.9fr]">
        <Card id="academy-learn" className="scroll-mt-24 shadow-none">
          <CardHeader><div><p className="data-label">1 · LEARN</p><h2 className="mt-1 text-sm font-semibold">学：先用人话看懂</h2></div><Target className="h-4 w-4 text-primary" /></CardHeader>
          <CardContent className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-lg border bg-muted/25 p-3"><p className="text-[11px] font-semibold text-primary">今天学什么</p><p className="mt-2 text-[11px] leading-5 text-muted-foreground">{lesson.goal}</p></div>
              <div className="rounded-lg border bg-muted/25 p-3"><p className="text-[11px] font-semibold text-primary">为什么危险</p><p className="mt-2 text-[11px] leading-5 text-muted-foreground">{lesson.why_it_matters}</p></div>
              <div className="rounded-lg border bg-muted/25 p-3"><p className="text-[11px] font-semibold text-primary">现实中在哪里</p><p className="mt-2 text-[11px] leading-5 text-muted-foreground">{lesson.real_world_example}</p></div>
            </div>
            <div><p className="text-xs font-semibold">目标</p><ul className="mt-2 space-y-1.5 text-xs leading-5 text-muted-foreground">{data.learning_objectives.map((objective) => <li key={objective} className="flex gap-2"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />{objective}</li>)}</ul></div>
            <div><p className="text-xs font-semibold">攻击面</p><div className="mt-2 flex flex-wrap gap-1.5">{data.attack_surface.map((surface) => <Badge key={surface}>{surface}</Badge>)}</div></div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/[.05] p-3"><p className="text-[11px] font-semibold text-emerald-500">允许</p><ul className="mt-2 space-y-1 text-[11px] leading-4 text-muted-foreground">{data.scope.allowed.map((item) => <li key={item}>• {item}</li>)}</ul></div>
              <div className="rounded-lg border border-red-500/20 bg-red-500/[.05] p-3"><p className="text-[11px] font-semibold text-red-500">禁止</p><ul className="mt-2 space-y-1 text-[11px] leading-4 text-muted-foreground">{data.scope.forbidden.map((item) => <li key={item}>• {item}</li>)}</ul></div>
            </div>
          </CardContent>
        </Card>

        <Card className="shadow-none">
          <CardHeader><div><p className="data-label">MAP & STANDARDS</p><h2 className="mt-1 text-sm font-semibold">漏洞发生在哪一层</h2></div><FlaskConical className="h-4 w-4 text-primary" /></CardHeader>
          <CardContent>
            <div className="flex flex-wrap items-center gap-2">
              {data.architecture.nodes.map((node, index) => (
                <div key={node} className="contents">
                  <span className="rounded-lg border bg-muted/35 px-2.5 py-2 text-[11px] font-medium">{node}</span>
                  {index < data.architecture.nodes.length - 1 ? <span className="text-muted-foreground">→</span> : null}
                </div>
              ))}
            </div>
            <div className="mt-5">
              <p className="text-xs font-semibold">映射</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {data.owasp_llm.map((item) => <Badge key={item} tone="info">{item}</Badge>)}
                {data.owasp_agentic.map((item) => <Badge key={item} tone="purple">{item}</Badge>)}
                {data.mitre_atlas.map((item) => <Badge key={item}>{item}</Badge>)}
                {data.cwe.map((item) => <Badge key={item} tone="warning">{item}</Badge>)}
              </div>
            </div>
            {data.mcp_spec.concepts.length ? <p className="mt-4 text-[11px] leading-5 text-muted-foreground">MCP {data.mcp_spec.version}：{data.mcp_spec.concepts.join(" · ")}</p> : null}
          </CardContent>
        </Card>
      </div>

      <Card id="academy-guess" className="mt-5 scroll-mt-24 shadow-none">
        <CardHeader><div><p className="data-label">2 · GUESS</p><h2 className="mt-1 text-sm font-semibold">猜：你觉得哪里会出问题？</h2><p className="mt-1 text-xs text-muted-foreground">先写下判断，再动手。答案只保存在当前页面，不计分，也不会影响通关。</p></div><MessageSquareText className="h-4 w-4 text-primary" /></CardHeader>
        <CardContent>
          <Label htmlFor="academy-guess-input">我的判断</Label>
          <Textarea id="academy-guess-input" rows={3} value={guess} onChange={(event) => setGuess(event.target.value)} placeholder="例如：外部内容可能被当成了可信指令……" maxLength={1000} />
          <p className="mt-2 text-right text-[10px] text-muted-foreground">{guess.length}/1000</p>
        </CardContent>
      </Card>

      <Card id="academy-do" className="mt-5 scroll-mt-24 shadow-none">
        <CardHeader><div><p className="data-label">3 · DO</p><h2 className="mt-1 text-sm font-semibold">做：在本地靶场试一次</h2><p className="mt-1 text-xs text-muted-foreground">不需要找端口、容器或内部 URL；系统会在本地确定性运行时中自动准备。</p></div><Play className="h-4 w-4 text-primary" /></CardHeader>
        <CardContent>
          <div className="mb-4 grid grid-cols-2 gap-2 rounded-xl border bg-muted/20 p-1 sm:max-w-md">
            <button type="button" className={cn("rounded-lg px-3 py-2 text-xs font-medium", mode === "vulnerable" ? "bg-red-500/12 text-red-500 shadow-sm" : "text-muted-foreground")} onClick={() => setMode("vulnerable")}><ShieldOff className="mr-2 inline h-3.5 w-3.5" />Vulnerable</button>
            <button type="button" className={cn("rounded-lg px-3 py-2 text-xs font-medium", mode === "hardened" ? "bg-emerald-500/12 text-emerald-500 shadow-sm" : "text-muted-foreground")} onClick={() => setMode("hardened")}><ShieldCheck className="mr-2 inline h-3.5 w-3.5" />Hardened</button>
          </div>
          <Label htmlFor="academy-payload">你的测试输入</Label>
          <Textarea id="academy-payload" rows={6} value={payload} onChange={(event) => setPayload(event.target.value)} className="font-mono text-xs leading-5" maxLength={8000} />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button aria-label={mode === "vulnerable" ? "执行 Vulnerable" : "执行 Hardened"} loading={execute.isPending} disabled={!payload.trim()} onClick={() => execute.mutate({ runMode: mode, runPayload: payload.trim() })}><Play className="h-4 w-4" />{mode === "vulnerable" ? "运行漏洞版" : "运行修复版"}</Button>
            <Button aria-label="相同 Payload 回放 Hardened" variant="outline" disabled={!vulnerableSession || replay.isPending} loading={replay.isPending} onClick={() => replay.mutate()}><RefreshCcw className="h-4 w-4" />用相同输入验证修复版</Button>
            <span className="ml-auto text-[10px] text-muted-foreground">{payload.length}/8000 · 仅本地确定性运行时 · 禁止粘贴真实凭证或个人数据</span>
          </div>
          {execute.error || replay.error ? <p className="mt-3 rounded-lg bg-red-500/10 p-3 text-xs text-red-500">{(execute.error || replay.error)?.message}</p> : null}
        </CardContent>
      </Card>

      <div className="mt-5 grid gap-5 xl:grid-cols-[1.35fr_.65fr]">
        <Card id="academy-see" className="scroll-mt-24 shadow-none">
          <CardHeader><div><p className="data-label">4 · SEE</p><h2 className="mt-1 text-sm font-semibold">看：为什么会成功或被阻断</h2><p className="mt-1 text-xs text-muted-foreground">Attack Story 来自服务器保存的真实事件，不依赖模型自评。</p></div>{currentSession ? <Badge tone={resultTone(currentSession)}>{resultLabel(currentSession)}</Badge> : null}</CardHeader>
          <CardContent>
            {currentSession ? (
              <>
                <AcademyAttackTrace events={currentSession.events} />
                <div className="mt-5">
                  {storyData ? <AcademyAttackStoryTimeline story={storyData} /> : attackStory.isLoading ? <LoadingState label="正在整理攻击故事…" /> : <p className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">Attack Story 暂时不可用，下面仍保留完整事件链。</p>}
                </div>
                <details className="mt-5 rounded-xl border p-4" open={!storyData}>
                  <summary className="cursor-pointer text-xs font-semibold">查看并选择原始 Evidence 事件</summary>
                  <div className="mt-4 space-y-4">
                    {groupedEvents.map((group) => (
                      <section key={group.group}>
                        <div className="mb-2 flex items-center justify-between"><h3 className="text-xs font-semibold">{group.group}</h3><span className="font-mono text-[10px] text-muted-foreground">{group.events.length} events</span></div>
                        <div className="space-y-2">{group.events.map((event) => <EventDetails key={event.id} event={event} checked={selectedEventIds.includes(event.id)} onToggle={() => setSelectedEventIds((current) => current.includes(event.id) ? current.filter((id) => id !== event.id) : [...current, event.id])} />)}</div>
                      </section>
                    ))}
                  </div>
                </details>
              </>
            ) : <EmptyState title="等待执行" description="选择模式并提交 payload 后，这里会显示 User → LLM → RAG → Agent → Tool → Data → Output 的真实事件链。" />}
          </CardContent>
        </Card>

        <div className="space-y-5">
          <Card className="shadow-none">
            <CardHeader><div><p className="data-label">A / B VALIDATION</p><h2 className="mt-1 text-sm font-semibold">同一 Payload 攻防对照</h2></div><ShieldCheck className="h-4 w-4 text-primary" /></CardHeader>
            <CardContent className="space-y-3">
              <SessionSummary title="A · Vulnerable" session={vulnerableSession} />
              <SessionSummary title="B · Hardened" session={hardenedSession} />
              {vulnerableSession && hardenedSession ? (
                <div className="rounded-lg bg-muted/40 p-3 text-[11px] leading-5 text-muted-foreground">
                  Payload SHA-256：<span className="break-all font-mono text-foreground">{vulnerableSession.payload_sha256}</span>
                  <p className="mt-1">{hardenedSession.replay_of_id === vulnerableSession.id ? "✓ 该 Hardened 记录由 Vulnerable 原始 payload 回放生成。" : "两次独立执行；如需严格 A/B，请点击“相同 Payload 回放”。"}</p>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card className="shadow-none">
            <CardHeader><div><p className="data-label">PROGRESS</p><h2 className="mt-1 text-sm font-semibold">红蓝闭环</h2></div><Trophy className="h-4 w-4 text-primary" /></CardHeader>
            <CardContent className="space-y-2">
              {[
                ["复现漏洞", data.progress.exploit_complete, "60"],
                ["提交证据链", data.progress.evidence_complete, "20"],
                ["选择正确修复", data.progress.mitigation_complete, "20"],
                ["Hardened 回放", data.progress.hardened_complete, "25"],
              ].map(([label, complete, points]) => <div key={String(label)} className="flex items-center gap-3 rounded-lg border p-3 text-xs"><CheckCircle2 className={cn("h-4 w-4", complete ? "text-emerald-500" : "text-muted-foreground/35")} /><span>{label}</span><span className="ml-auto font-mono text-muted-foreground">+{points}</span></div>)}
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <Card className="shadow-none">
          <CardHeader><div><p className="data-label">EVIDENCE</p><h2 className="mt-1 text-sm font-semibold">证明攻击链</h2></div><ClipboardCheck className="h-4 w-4 text-primary" /></CardHeader>
          <CardContent>
            <p className="text-xs leading-5 text-muted-foreground">{data.expected_evidence.rubric}</p>
            <p className="mt-2 text-[11px] text-muted-foreground">期望事件：{data.expected_evidence.event_types.join(" · ")}</p>
            <Button className="mt-4" loading={evidence.isPending} disabled={!vulnerableSession?.exploit_success || !selectedEventIds.length} onClick={() => evidence.mutate()}><FileSearch className="h-4 w-4" />提交已勾选事件</Button>
            {evidence.error ? <p className="mt-3 text-xs text-red-500">{evidence.error.message}</p> : null}
            {vulnerableSession?.finding_id || vulnerableSession?.evidence_id ? <div className="mt-4 flex flex-wrap gap-2"><Button asChild variant="outline" size="sm"><Link href="/findings">查看 Finding</Link></Button><Button asChild variant="outline" size="sm"><Link href="/evidence">查看 Evidence</Link></Button><Button asChild variant="outline" size="sm"><Link href="/reports"><FileCheck2 className="h-3.5 w-3.5" />生成报告</Link></Button></div> : null}
          </CardContent>
        </Card>

        <Card id="academy-fix" className="scroll-mt-24 shadow-none">
          <CardHeader><div><p className="data-label">5 · FIX</p><h2 className="mt-1 text-sm font-semibold">修：选择能切断攻击链的控制</h2></div><Wrench className="h-4 w-4 text-primary" /></CardHeader>
          <CardContent>
            <div className="space-y-2">
              {data.mitigations.map((item) => (
                <label key={item.id} className={cn("flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-xs leading-5", mitigationChoice === item.id && "border-primary/45 bg-primary/[.05]")}>
                  <input type="radio" name="academy-mitigation" value={item.id} checked={mitigationChoice === item.id} onChange={() => setMitigationChoice(item.id)} className="mt-0.5 h-4 w-4 accent-teal-500" />
                  <span>{item.label}</span>
                </label>
              ))}
            </div>
            <Button className="mt-4" loading={mitigation.isPending} disabled={!mitigationChoice} onClick={() => mitigation.mutate()}><ShieldCheck className="h-4 w-4" />验证修复选择</Button>
            {mitigation.error ? <p className="mt-3 text-xs text-red-500">{mitigation.error.message}</p> : null}
            <div className="mt-4 rounded-lg bg-muted/40 p-3"><p className="text-[11px] font-semibold">检测要点</p><ul className="mt-2 space-y-1 text-[11px] leading-4 text-muted-foreground">{data.detection_notes.map((note) => <li key={note}>• {note}</li>)}</ul></div>
          </CardContent>
        </Card>
      </div>

      <Card id="academy-retest" className="mt-5 scroll-mt-24 shadow-none">
        <CardHeader><div><p className="data-label">6 · RETEST</p><h2 className="mt-1 text-sm font-semibold">再测：漏洞版 VS 修复版</h2><p className="mt-1 text-xs text-muted-foreground">服务器按相同 Payload 关联两次执行，并高亮真正改变的安全控制。</p></div><ShieldCheck className="h-4 w-4 text-primary" /></CardHeader>
        <CardContent>
          {comparisonData ? <AcademyScenarioComparison comparison={comparisonData} /> : currentSession ? (
            <div className="space-y-3">
              <p className="rounded-xl border border-dashed p-5 text-center text-xs text-muted-foreground">正在读取真实攻防对照；原始执行记录仍保留在上方。</p>
              {vulnerableSession && !hardenedSession ? <Button aria-label="在对照区验证修复版" loading={replay.isPending} onClick={() => replay.mutate()}><RefreshCcw className="h-4 w-4" />用相同输入验证修复版</Button> : null}
            </div>
          ) : <EmptyState title="先完成漏洞版" description="触发漏洞后，用相同输入回放 Hardened，系统会生成真实左右对照。" />}
        </CardContent>
      </Card>

      <Card className="mt-5 shadow-none">
        <CardHeader><div><p className="data-label">HELP WITHOUT SHAME</p><h2 className="mt-1 text-sm font-semibold">卡住了吗？按需要查看三级提示</h2><p className="mt-1 text-xs text-muted-foreground">提示按顺序逐渐具体；完整解法必须单独主动点击。</p></div><Lightbulb className="h-4 w-4 text-primary" /></CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-3">
            {([1, 2, 3] as const).map((level) => {
              const unlocked = usedHints.has(level);
              const hintItem = data.hints.find((item) => item.level === level);
              const cost = hintItem?.cost || 0;
              const canUnlock = nextHint === level;
              const labels = ["思路提示", "位置提示", "接近答案"];
              return (
                <div key={level} className={cn("rounded-xl border p-4", unlocked && "border-amber-500/30 bg-amber-500/[.05]")}>
                  <div className="flex items-center justify-between"><p className="text-xs font-semibold">Hint {level} · {labels[level - 1]}</p><Badge tone={unlocked ? "warning" : "neutral"}>-{cost}</Badge></div>
                  {unlocked ? <p className="mt-3 text-[11px] leading-5 text-muted-foreground">{hintItem?.text}</p> : <p className="mt-3 flex items-center gap-2 text-[11px] text-muted-foreground"><LockKeyhole className="h-3.5 w-3.5" />按顺序解锁</p>}
                  {!unlocked ? <Button className="mt-3 w-full" size="sm" variant="outline" disabled={!canUnlock || hint.isPending} onClick={() => hint.mutate(level)}>解锁</Button> : null}
                </div>
              );
            })}
          </div>
          <div className="mt-4 flex flex-col gap-3 rounded-xl border border-amber-500/25 bg-amber-500/[.04] p-4 sm:flex-row sm:items-center sm:justify-between">
            <div><p className="text-xs font-semibold">完整解法</p><p className="mt-1 text-[11px] leading-5 text-muted-foreground">会显示本地训练 Payload、完整步骤和修复后复测方法。查看不会清空进度。</p></div>
            {usedHints.has(4) ? <Badge tone="success">已主动查看</Badge> : <Button variant="outline" disabled={!([1, 2, 3].every((level) => usedHints.has(level))) || hint.isPending} loading={hint.isPending} onClick={() => hint.mutate("solution")}><BookOpenCheck className="h-4 w-4" />查看完整解法</Button>}
          </div>
          {!data.walkthrough.locked ? (
            <div className="mt-5 rounded-xl border border-amber-500/25 bg-amber-500/[.05] p-5">
              <div className="flex items-center gap-2 text-sm font-semibold"><BookOpenCheck className="h-4 w-4 text-amber-500" />完整解法</div>
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <div><p className="text-xs font-semibold">Payload</p><div className="mt-2 space-y-2">{(data.walkthrough.payloads || []).map((item) => <pre key={item} className="whitespace-pre-wrap rounded-lg bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">{item}</pre>)}</div></div>
                <div><p className="text-xs font-semibold">步骤</p><ol className="mt-2 space-y-2 text-[11px] leading-5 text-muted-foreground">{(data.walkthrough.steps || []).map((step, index) => <li key={step} className="flex gap-2"><span className="grid h-5 w-5 shrink-0 place-items-center rounded-full border font-mono text-[9px]">{index + 1}</span>{step}</li>)}</ol><p className="mt-3 rounded-lg bg-background/50 p-3 text-[11px] leading-5">{data.walkthrough.retest}</p></div>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card className="mt-5 shadow-none">
        <CardHeader><div><p className="data-label">DEFENSIVE TUTOR</p><h2 className="mt-1 text-sm font-semibold">不懂就问：只讲本关与防御</h2></div><MessageSquareText className="h-4 w-4 text-cyan-500" /></CardHeader>
        <CardContent>
          <AcademyWhaleTutor scenario={data} story={storyData} comparison={comparisonData} projectId={projectId} sessionId={currentSession?.id} />
        </CardContent>
      </Card>

      <Card id="academy-summary" className={cn("mt-5 scroll-mt-24 shadow-none", data.progress.completed && "border-emerald-500/30 bg-emerald-500/[.035]")}>
        <CardHeader>
          <div>
            <p className="data-label">7 · SUMMARY</p>
            <h2 className="mt-1 text-sm font-semibold">总结：说清楚攻击链，再继续下一关</h2>
            <p className="mt-1 text-xs text-muted-foreground">完成不是只看到成功提示，而是能解释“为什么成功、在哪里阻断、用什么证据证明”。</p>
          </div>
          <Trophy className={cn("h-4 w-4", data.progress.completed ? "text-emerald-500" : "text-muted-foreground")} />
        </CardHeader>
        <CardContent>
          {data.progress.completed ? (
            <div className="space-y-5">
              <div className="grid gap-3 lg:grid-cols-3">
                <div className="rounded-xl border bg-background/65 p-4"><p className="text-[11px] font-semibold text-red-500">漏洞是什么</p><p className="mt-2 text-xs leading-5 text-muted-foreground">{data.risk_family}：{lesson.why_it_matters}</p></div>
                <div className="rounded-xl border bg-background/65 p-4"><p className="text-[11px] font-semibold text-amber-500">为什么会成功</p><p className="mt-2 text-xs leading-5 text-muted-foreground">{storyData?.explanation || "事件链显示不可信输入跨过了应有的信任边界，并影响了 Agent、工具或输出决策。"}</p></div>
                <div className="rounded-xl border bg-background/65 p-4"><p className="text-[11px] font-semibold text-emerald-500">为什么能修好</p><p className="mt-2 text-xs leading-5 text-muted-foreground">{comparisonData?.conclusion || "Hardened 在产生副作用前执行隔离、最小权限或人工审批，并保留阻断事件。"}</p></div>
              </div>

              <div className="rounded-xl border bg-background/65 p-4">
                <p className="text-xs font-semibold">本关练到的技能</p>
                <div className="mt-2 flex flex-wrap gap-2">{data.skills.map((skill) => <Badge key={skill} tone="info">{skill}</Badge>)}</div>
              </div>

              <AcademyKnowledgeReview scenario={data} />

              <div className="grid gap-4 rounded-xl border border-primary/25 bg-primary/[.05] p-5 lg:grid-cols-[1fr_auto] lg:items-center" data-testid="academy-completion-next">
                <div>
                  <p className="flex items-center gap-2 text-xs font-semibold text-emerald-500"><CheckCircle2 className="h-4 w-4" />本关已完成 · {data.progress.score}/{data.progress.max_score}</p>
                  <h3 className="mt-2 text-lg font-semibold">{nextTarget ? `下一关：${nextTarget.scenarioId} · ${nextTarget.title}` : "全部课程已完成"}</h3>
                  <p className="mt-1 text-xs text-muted-foreground">{nextTarget ? "进度、Finding、Evidence 与报告都会保留，可以直接沿路线继续。" : "回到路线图查看技能进度，或重新挑战任意关卡巩固。"}</p>
                </div>
                <Button asChild size="lg">
                  <Link href={nextTarget ? `/academy/scenarios/${nextTarget.scenarioId}` : "/academy"}>
                    {nextTarget ? "一键继续学习" : "查看完整路线"}<ArrowRight className="h-4 w-4" />
                  </Link>
                </Button>
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-dashed p-6 text-center">
              <p className="text-sm font-semibold">还差一点就能总结</p>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">依次完成漏洞复现、证据提交、修复选择和 Hardened 回放。完成后这里会出现知识回顾与最明显的“下一关”。</p>
              <Button asChild className="mt-4" variant="outline"><a href="#academy-do"><Play className="h-4 w-4" />继续本关</a></Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
