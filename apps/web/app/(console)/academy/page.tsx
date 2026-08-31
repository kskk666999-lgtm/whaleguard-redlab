"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BookOpen, GraduationCap, Network, ShieldCheck, Sparkles } from "lucide-react";
import { AcademyLearningRoadmap } from "@/components/academy/learning-roadmap";
import { AcademyMicroCourses } from "@/components/academy/micro-courses";
import { AcademyScenarioCard } from "@/components/academy/scenario-card";
import { AcademySkillProgress } from "@/components/academy/skill-progress";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label, Select } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { apiRequest, fetchPage } from "@/lib/api";
import type {
  AcademyMicroCourseList,
  AcademyRoadmap,
  AcademyScenarioListItem,
  AcademySkillProgress as AcademySkillProgressData,
  AcademySummary,
  Project,
} from "@/lib/types";

export default function AcademyPage() {
  const [projectId, setProjectId] = useState("");
  const projects = useQuery({
    queryKey: ["projects", "academy"],
    queryFn: () => fetchPage<Project>("/projects?page=1&page_size=100"),
  });
  const activeProjects = useMemo(
    () => (projects.data?.items || []).filter((project) => project.status !== "archived"),
    [projects.data],
  );

  useEffect(() => {
    if (!activeProjects.some((project) => project.id === projectId)) {
      setProjectId(activeProjects[0]?.id || "");
    }
  }, [activeProjects, projectId]);

  const summary = useQuery({
    queryKey: ["academy-summary", projectId],
    queryFn: () => apiRequest<AcademySummary>(`/academy?project_id=${encodeURIComponent(projectId)}`),
    enabled: Boolean(projectId),
  });
  const scenarios = useQuery({
    queryKey: ["academy-scenarios", projectId],
    queryFn: () => apiRequest<{ items: AcademyScenarioListItem[]; total: number; starter_path: string[] }>(`/academy/scenarios?project_id=${encodeURIComponent(projectId)}`),
    enabled: Boolean(projectId),
  });
  const roadmap = useQuery({
    queryKey: ["academy-roadmap", projectId],
    queryFn: () => apiRequest<AcademyRoadmap>(`/academy/roadmap?project_id=${encodeURIComponent(projectId)}`),
    enabled: Boolean(projectId),
  });
  const skills = useQuery({
    queryKey: ["academy-skills", projectId],
    queryFn: () => apiRequest<AcademySkillProgressData>(`/academy/skills?project_id=${encodeURIComponent(projectId)}`),
    enabled: Boolean(projectId),
  });
  const microCourses = useQuery({
    queryKey: ["academy-micro-courses"],
    queryFn: () => apiRequest<AcademyMicroCourseList>("/academy/micro-courses"),
  });

  if (projects.isLoading) return <LoadingState label="正在准备安全学院…" />;
  if (projects.error) return <ErrorState error={projects.error} onRetry={() => projects.refetch()} />;

  const data = summary.data;
  const allScenarios = scenarios.data?.items || [];
  const roadmapData = roadmap.data?.total_count ? roadmap.data : undefined;
  const skillItems = Array.isArray(skills.data?.items) ? skills.data.items : [];
  const courseItems = Array.isArray(microCourses.data?.items) ? microCourses.data.items : [];
  const nextLesson = roadmapData?.next_lesson || data?.next_lesson;
  const fallbackId = data?.starter_path?.[0] || "B01";
  const fallbackScenario = allScenarios.find((item) => item.id === fallbackId);
  const nextId = nextLesson?.scenario_id || fallbackId;
  const nextTitle = nextLesson?.title || fallbackScenario?.title || "Prompt Breaker";
  const starter = (data?.starter_path || [])
    .map((id) => allScenarios.find((item) => item.id === id))
    .filter((item): item is AcademyScenarioListItem => Boolean(item));
  const loadingCore = summary.isLoading || scenarios.isLoading;
  const coreError = summary.error || scenarios.error;

  return (
    <div>
      <PageHeader
        eyebrow="LEARN AI SECURITY · LOCAL ONLY"
        title="WhaleGuard Academy Range"
        description="不需要 API Key，也不用先理解 Project、Scope 或容器。先学三分钟，再在本地靶场动手，最后亲眼比较漏洞版和修复版。"
        actions={(
          <Button asChild variant="outline">
            <Link href="/academy/scenarios">查看完整路线<ArrowRight className="h-4 w-4" /></Link>
          </Button>
        )}
      />

      <Card className="mb-5 border-primary/25 bg-primary/[.035] shadow-none" data-testid="academy-next-lesson">
        <CardContent className="grid gap-5 p-5 lg:grid-cols-[1fr_auto] lg:items-center">
          <div>
            <p className="flex items-center gap-2 text-xs font-semibold text-primary"><Sparkles className="h-4 w-4" />{nextLesson?.action === "continue" ? "继续上一课" : "从第一课开始"}</p>
            <h2 className="mt-2 text-xl font-semibold">{nextId} · {nextTitle}</h2>
            <p className="mt-2 text-xs leading-6 text-muted-foreground">
              {nextLesson?.reason || "这节课会带你完成一次完整的 学 → 猜 → 做 → 看 → 修 → 再测 → 总结。"}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge tone="success"><ShieldCheck className="mr-1 h-3 w-3" />本地安全靶场</Badge>
              <Badge tone="info"><Network className="mr-1 h-3 w-3" />不访问公网</Badge>
              <Badge><BookOpen className="mr-1 h-3 w-3" />零基础可学</Badge>
            </div>
          </div>
          <Button asChild size="lg" disabled={!projectId}>
            <Link href={`/academy/scenarios/${nextId}`}>
              {nextLesson?.action === "continue" ? "继续上一课" : "开始第一课"}<ArrowRight className="h-4 w-4" />
            </Link>
          </Button>
        </CardContent>
      </Card>

      <Card className="mb-5 shadow-none">
        <CardContent className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
          <div>
            <Label htmlFor="academy-project">学习记录保存到</Label>
            <Select id="academy-project" value={projectId} onChange={(event) => setProjectId(event.target.value)}>
              {activeProjects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
            </Select>
            <p className="mt-1 text-[11px] text-muted-foreground">系统自动使用现有项目保存进度、Finding 和 Evidence；新手不需要手动配置底层对象。</p>
          </div>
          <div className="flex items-center gap-3 rounded-xl border bg-muted/25 px-4 py-3">
            <GraduationCap className="h-5 w-5 text-primary" />
            <div><p className="font-mono text-sm font-semibold">{data?.completed_count || 0}/{data?.scenario_count || 17}</p><p className="text-[10px] text-muted-foreground">已完成课程</p></div>
          </div>
        </CardContent>
      </Card>

      {!activeProjects.length ? (
        <Card className="shadow-none"><CardContent className="p-8 text-center text-sm text-muted-foreground">请先创建一个项目，再开始 Academy 训练。</CardContent></Card>
      ) : loadingCore ? (
        <LoadingState label="正在读取你的学习路线…" />
      ) : coreError ? (
        <ErrorState error={coreError} onRetry={() => { summary.refetch(); scenarios.refetch(); roadmap.refetch(); skills.refetch(); }} />
      ) : (
        <div className="space-y-5">
          <AcademyMicroCourses courses={courseItems} />
          {roadmapData ? <AcademyLearningRoadmap roadmap={roadmapData} /> : (
            <Card className="shadow-none">
              <CardContent className="p-5">
                <h2 className="text-base font-semibold">推荐从这五关开始</h2>
                <p className="mt-1 text-xs text-muted-foreground">完整 Roadmap 暂时不可用，场景本身仍可正常运行。</p>
                <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">{starter.map((scenario) => <AcademyScenarioCard key={scenario.id} scenario={scenario} />)}</div>
              </CardContent>
            </Card>
          )}
          <AcademySkillProgress skills={skillItems} />
          <Card className="border-emerald-500/25 bg-emerald-500/[.04] shadow-none">
            <CardContent className="p-4">
              <p className="flex items-center gap-2 text-xs font-semibold text-emerald-500"><ShieldCheck className="h-4 w-4" />安全边界不会因为新手模式而放宽</p>
              <p className="mt-2 text-[11px] leading-5 text-muted-foreground">学院只运行本地确定性模拟，训练数据全部以 WHALE_LAB_FAKE_* 动态生成；无真实凭据、无公网目标、无 Shell、无真实外传。</p>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
