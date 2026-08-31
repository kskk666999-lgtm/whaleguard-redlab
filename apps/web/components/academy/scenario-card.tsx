import Link from "next/link";
import { ArrowRight, CheckCircle2, Clock3, ShieldAlert, Star } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { AcademyScenarioListItem } from "@/lib/types";

function difficultyTone(difficulty: AcademyScenarioListItem["difficulty"]) {
  if (difficulty === "Advanced") return "danger" as const;
  if (difficulty === "Intermediate") return "warning" as const;
  return "success" as const;
}

export function AcademyScenarioCard({ scenario }: { scenario: AcademyScenarioListItem }) {
  const progress = scenario.progress;
  return (
    <Card className="group h-full overflow-hidden shadow-none transition-colors hover:border-primary/35">
      <CardContent className="flex h-full flex-col p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="rounded-md border bg-muted px-2 py-1 font-mono text-xs font-bold text-primary">{scenario.id}</span>
            <Badge tone={difficultyTone(scenario.difficulty)}>{scenario.difficulty}</Badge>
          </div>
          {progress.completed ? <CheckCircle2 className="h-5 w-5 text-emerald-400" aria-label="已完成" /> : <ShieldAlert className="h-5 w-5 text-muted-foreground/50" />}
        </div>
        <h2 className="mt-4 text-base font-semibold">{scenario.title}</h2>
        <p className="mt-2 line-clamp-3 text-xs leading-5 text-muted-foreground">{scenario.story}</p>
        <div className="mt-4 flex flex-wrap gap-1.5">
          {scenario.knowledge_tags.slice(0, 4).map((tag) => <Badge key={tag}>{tag}</Badge>)}
        </div>
        <div className="mt-auto pt-5">
          <div className="mb-2 flex items-center justify-between text-[11px] text-muted-foreground">
            <span className="flex items-center gap-1"><Clock3 className="h-3.5 w-3.5" />{scenario.estimated_time} 分钟</span>
            <span className="flex items-center gap-1"><Star className="h-3.5 w-3.5" />{"★".repeat(scenario.difficulty_stars)}</span>
            <span className="font-mono text-foreground">{progress.score}/{progress.max_score}</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${Math.min(100, (progress.score / progress.max_score) * 100)}%` }} />
          </div>
          <Button asChild variant="outline" size="sm" className="mt-4 w-full group-hover:border-primary/40">
            <Link href={`/academy/scenarios/${scenario.id}`}>{progress.exploit_complete ? "继续训练" : "进入场景"}<ArrowRight className="h-3.5 w-3.5" /></Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
