import Link from "next/link";
import { CheckCircle2, Clock3, LockKeyhole, PlayCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { AcademyRoadmap, AcademyRoadmapLesson } from "@/lib/types";
import { cn } from "@/lib/utils";

const statusCopy = {
  available: { label: "可以开始", tone: "info" as const, icon: PlayCircle },
  in_progress: { label: "正在学习", tone: "warning" as const, icon: PlayCircle },
  completed: { label: "已完成", tone: "success" as const, icon: CheckCircle2 },
  recommended_later: { label: "建议稍后", tone: "neutral" as const, icon: LockKeyhole },
};

function RoadmapLesson({ lesson }: { lesson: AcademyRoadmapLesson }) {
  const status = statusCopy[lesson.status];
  const StatusIcon = status.icon;
  const primaryOwasp = lesson.standards.owasp_llm[0] || lesson.standards.owasp_agentic[0];
  return (
    <li
      className={cn(
        "relative rounded-xl border bg-background/55 p-4",
        lesson.status === "in_progress" && "border-amber-500/40 bg-amber-500/[.05]",
        lesson.status === "completed" && "border-emerald-500/30 bg-emerald-500/[.04]",
      )}
      data-testid={`roadmap-lesson-${lesson.scenario_id}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border bg-muted font-mono text-xs font-bold text-primary">
            {lesson.scenario_id}
          </span>
          <div>
            <h3 className="text-sm font-semibold">{lesson.title}</h3>
            <p className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
              <Clock3 className="h-3 w-3" />预计 {lesson.estimated_time} 分钟
            </p>
          </div>
        </div>
        <Badge tone={status.tone}>
          <StatusIcon className="mr-1 h-3 w-3" />{status.label}
        </Badge>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {lesson.skills.slice(0, 3).map((skill) => <Badge key={skill}>{skill}</Badge>)}
      </div>
      {primaryOwasp ? <p className="mt-3 text-[11px] leading-5 text-muted-foreground">对应：{primaryOwasp}</p> : null}
      <p className="mt-1 text-[11px] leading-5 text-muted-foreground">
        前置：{lesson.prerequisites.length ? lesson.prerequisites.join("、") : "无，适合第一课"}
      </p>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary"
          style={{ width: `${Math.min(100, lesson.progress.score / lesson.progress.max_score * 100)}%` }}
        />
      </div>
      <Button asChild variant="outline" size="sm" className="mt-3 w-full">
        <Link href={`/academy/scenarios/${lesson.scenario_id}`}>
          {lesson.status === "completed" ? "复习本课" : lesson.status === "in_progress" ? "继续本课" : "进入本课"}
        </Link>
      </Button>
    </li>
  );
}

export function AcademyLearningRoadmap({ roadmap }: { roadmap: AcademyRoadmap }) {
  return (
    <Card className="shadow-none" data-testid="academy-roadmap">
      <CardHeader>
        <div>
          <p className="data-label">LEARNING ROADMAP</p>
          <h2 className="mt-1 text-base font-semibold">你的 AI 安全学习路线</h2>
          <p className="mt-1 text-xs text-muted-foreground">推荐顺序不会强制锁课；前置课程用于告诉你先学什么会更容易。</p>
        </div>
        <Badge tone="info">{roadmap.completed_count}/{roadmap.total_count}</Badge>
      </CardHeader>
      <CardContent className="space-y-6">
        {(["Beginner", "Intermediate", "Advanced"] as const).map((level) => {
          const lessons = roadmap.items.filter((item) => item.difficulty === level);
          const levelProgress = roadmap.levels[level];
          return (
            <section key={level} aria-labelledby={`roadmap-${level}`}>
              <div className="mb-3 flex items-center justify-between">
                <h3 id={`roadmap-${level}`} className="text-sm font-semibold">{level}</h3>
                <span className="font-mono text-[11px] text-muted-foreground">
                  {levelProgress?.completed || 0}/{levelProgress?.total || lessons.length}
                </span>
              </div>
              <ol className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {lessons.map((lesson) => <RoadmapLesson key={lesson.scenario_id} lesson={lesson} />)}
              </ol>
            </section>
          );
        })}
      </CardContent>
    </Card>
  );
}
