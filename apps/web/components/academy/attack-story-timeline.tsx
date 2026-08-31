import { ArrowDown, CheckCircle2, ShieldAlert } from "lucide-react";
import { Badge, statusTone } from "@/components/ui/badge";
import type { AcademyAttackStory } from "@/lib/types";

export function AcademyAttackStoryTimeline({ story }: { story: AcademyAttackStory }) {
  const blocked = story.outcome === "blocked";
  return (
    <section data-testid="academy-attack-story" aria-labelledby="attack-story-heading">
      <div className={blocked ? "rounded-xl border border-emerald-500/30 bg-emerald-500/[.05] p-4" : "rounded-xl border border-red-500/25 bg-red-500/[.04] p-4"}>
        <div className="flex items-start gap-3">
          {blocked ? <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" /> : <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />}
          <div>
            <h3 id="attack-story-heading" className="text-sm font-semibold">{story.headline}</h3>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">{story.explanation}</p>
          </div>
        </div>
      </div>
      <ol className="mt-4 space-y-2">
        {story.timeline.map((step, index) => (
          <li key={step.event_id} className="relative rounded-xl border bg-background/55 p-4">
            <div className="flex flex-wrap items-start gap-3">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary/10 font-mono text-[10px] text-primary">{step.sequence}</span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={statusTone(step.status)}>{step.component}</Badge>
                  <span className="font-mono text-[10px] text-muted-foreground">{step.source} → {step.target}</span>
                </div>
                <p className="mt-2 text-xs font-semibold">{step.title}</p>
                <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{step.explanation}</p>
              </div>
            </div>
            {index < story.timeline.length - 1 ? <ArrowDown className="absolute -bottom-3 left-6 z-10 h-4 w-4 rounded-full bg-background text-muted-foreground" /> : null}
          </li>
        ))}
      </ol>
      {story.control_point ? (
        <div className="mt-4 rounded-xl border border-primary/25 bg-primary/[.04] p-4 text-xs leading-5">
          <span className="font-semibold">关键控制点：</span>{story.control_point.component} · {story.control_point.explanation}
        </div>
      ) : null}
      <details className="mt-4 rounded-xl border p-4">
        <summary className="cursor-pointer text-xs font-semibold">查看技术细节（原始事件 JSON）</summary>
        <pre className="mt-3 max-h-80 overflow-auto rounded-lg bg-slate-950 p-3 text-[10px] leading-4 text-slate-200">{JSON.stringify(story.technical_details, null, 2)}</pre>
      </details>
    </section>
  );
}
