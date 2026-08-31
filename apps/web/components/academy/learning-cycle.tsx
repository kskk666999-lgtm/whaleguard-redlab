import { CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";

const steps = [
  ["learn", "学"],
  ["guess", "猜"],
  ["do", "做"],
  ["see", "看"],
  ["fix", "修"],
  ["retest", "再测"],
  ["summary", "总结"],
] as const;

export function AcademyLearningCycle({ completed }: { completed: string[] }) {
  const completedSet = new Set(completed);
  return (
    <nav aria-label="本课学习步骤" className="mb-5 overflow-x-auto rounded-xl border bg-background/65 p-2" data-testid="academy-learning-cycle">
      <ol className="flex min-w-max items-center gap-1">
        {steps.map(([id, label], index) => (
          <li key={id} className="flex items-center">
            <a href={`#academy-${id}`} className={cn("flex items-center gap-2 rounded-lg px-3 py-2 text-xs hover:bg-muted", completedSet.has(id) ? "text-emerald-500" : "text-muted-foreground")}>
              {completedSet.has(id) ? <CheckCircle2 className="h-3.5 w-3.5" /> : <span className="grid h-4 w-4 place-items-center rounded-full border font-mono text-[8px]">{index + 1}</span>}
              {label}
            </a>
            {index < steps.length - 1 ? <span className="text-muted-foreground/40">→</span> : null}
          </li>
        ))}
      </ol>
    </nav>
  );
}
