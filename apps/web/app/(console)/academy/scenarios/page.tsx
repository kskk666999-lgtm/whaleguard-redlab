"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Search, ShieldCheck } from "lucide-react";
import { AcademyScenarioCard } from "@/components/academy/scenario-card";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { apiRequest, fetchPage } from "@/lib/api";
import type { AcademyScenarioListItem, Project } from "@/lib/types";

export default function AcademyScenariosPage() {
  const [projectId, setProjectId] = useState("");
  const [difficulty, setDifficulty] = useState("all");
  const [query, setQuery] = useState("");
  const projects = useQuery({ queryKey: ["projects", "academy-scenarios"], queryFn: () => fetchPage<Project>("/projects?page=1&page_size=100") });
  const activeProjects = useMemo(() => (projects.data?.items || []).filter((project) => project.status !== "archived"), [projects.data]);

  useEffect(() => {
    if (!activeProjects.some((project) => project.id === projectId)) setProjectId(activeProjects[0]?.id || "");
  }, [activeProjects, projectId]);

  const scenarios = useQuery({
    queryKey: ["academy-scenarios", projectId],
    queryFn: () => apiRequest<{ items: AcademyScenarioListItem[]; total: number; starter_path: string[] }>(`/academy/scenarios?project_id=${encodeURIComponent(projectId)}`),
    enabled: Boolean(projectId),
  });
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (scenarios.data?.items || []).filter((scenario) => {
      if (difficulty !== "all" && scenario.difficulty !== difficulty) return false;
      if (!needle) return true;
      return `${scenario.id} ${scenario.title} ${scenario.story} ${scenario.knowledge_tags.join(" ")}`.toLowerCase().includes(needle);
    });
  }, [difficulty, query, scenarios.data]);

  if (projects.isLoading) return <LoadingState label="正在读取 Academy 项目…" />;
  if (projects.error) return <ErrorState error={projects.error} onRetry={() => projects.refetch()} />;

  return (
    <div>
      <PageHeader eyebrow="17 EVENT-DRIVEN CHALLENGES" title="Academy 场景库" description="每关都具备 Vulnerable / Hardened 两套状态、确定性成功条件、Evidence 评分与同 payload Replay。" actions={<Button asChild variant="outline"><Link href="/academy"><ArrowLeft className="h-4 w-4" />返回 Academy</Link></Button>} />
      <Card className="mb-5 shadow-none"><CardContent className="grid gap-4 p-4 md:grid-cols-[1fr_220px_220px]"><div><Label htmlFor="scenario-search">搜索场景或知识标签</Label><div className="relative"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input id="scenario-search" value={query} onChange={(event) => setQuery(event.target.value)} className="pl-10" placeholder="例如：RAG、MCP、BOLA、Memory" /></div></div><div><Label htmlFor="scenario-level">难度</Label><Select id="scenario-level" value={difficulty} onChange={(event) => setDifficulty(event.target.value)}><option value="all">全部难度</option><option value="Beginner">Beginner</option><option value="Intermediate">Intermediate</option><option value="Advanced">Advanced</option></Select></div><div><Label htmlFor="scenario-project">项目</Label><Select id="scenario-project" value={projectId} onChange={(event) => setProjectId(event.target.value)}>{activeProjects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</Select></div></CardContent></Card>

      {!activeProjects.length ? <Card className="shadow-none"><CardContent className="p-8 text-center text-sm text-muted-foreground">请先创建项目。</CardContent></Card> : scenarios.isLoading ? <LoadingState label="正在加载 17 个场景…" /> : scenarios.error ? <ErrorState error={scenarios.error} onRetry={() => scenarios.refetch()} /> : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2"><Badge tone="info">{filtered.length} 个场景</Badge><Badge tone="success"><ShieldCheck className="mr-1 h-3 w-3" />local-only</Badge><span className="text-[11px] text-muted-foreground">Starter Path：B01 → B02 → B03 → B04 → B05</span></div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">{filtered.map((scenario) => <AcademyScenarioCard key={scenario.id} scenario={scenario} />)}</div>
          {!filtered.length ? <Card className="shadow-none"><CardContent className="p-10 text-center text-sm text-muted-foreground">没有匹配的场景。</CardContent></Card> : null}
        </>
      )}
    </div>
  );
}
