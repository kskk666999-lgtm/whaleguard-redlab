import { BrainCircuit } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { AcademySkillProgressItem } from "@/lib/types";

const tones = {
  not_started: "neutral",
  introduced: "info",
  practicing: "warning",
  foundation: "success",
} as const;

export function AcademySkillProgress({ skills }: { skills: AcademySkillProgressItem[] }) {
  return (
    <Card className="shadow-none" data-testid="academy-skill-progress">
      <CardHeader>
        <div>
          <p className="data-label">SKILL PROGRESS</p>
          <h2 className="mt-1 text-base font-semibold">你已经学会了什么</h2>
          <p className="mt-1 text-xs text-muted-foreground">关卡不是终点；这里按知识能力整理你的练习成果。</p>
        </div>
        <BrainCircuit className="h-5 w-5 text-primary" />
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        {skills.map((skill) => (
          <article key={skill.skill_id} className="rounded-xl border bg-background/55 p-4">
            <div className="flex items-start justify-between gap-2">
              <h3 className="text-xs font-semibold">{skill.name}</h3>
              <Badge tone={tones[skill.status]}>{skill.status_label}</Badge>
            </div>
            <p className="mt-2 min-h-10 text-[11px] leading-5 text-muted-foreground">{skill.description}</p>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-primary" style={{ width: `${skill.progress_percent}%` }} />
            </div>
            <p className="mt-2 font-mono text-[10px] text-muted-foreground">{skill.completed_count}/{skill.total_count} lessons</p>
          </article>
        ))}
        {!skills.length ? <p className="text-xs text-muted-foreground">完成第一课后，这里会出现你的技能地图。</p> : null}
      </CardContent>
    </Card>
  );
}
