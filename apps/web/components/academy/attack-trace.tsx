import { ArrowDown, ArrowRight, Bot, BrainCircuit, Database, FileSearch, Network, ShieldAlert, UserRound, Wrench } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AcademyEvent } from "@/lib/types";

const nodes = [
  { id: "user", label: "User", icon: UserRound, terms: ["user"] },
  { id: "llm", label: "LLM", icon: BrainCircuit, terms: ["llm"] },
  { id: "rag", label: "RAG", icon: FileSearch, terms: ["rag", "vector"] },
  { id: "planner", label: "Planner", icon: ShieldAlert, terms: ["planner"] },
  { id: "agent", label: "Agent", icon: Bot, terms: ["agent"] },
  { id: "tool", label: "MCP / Tool", icon: Wrench, terms: ["mcp", "tool"] },
  { id: "data", label: "Data", icon: Database, terms: ["data", "secret", "enterprise", "memory", "identity"] },
  { id: "output", label: "Output", icon: Network, terms: ["output", "renderer", "collector", "human"] },
] as const;

function nodeState(node: (typeof nodes)[number], events: AcademyEvent[]) {
  const matching = events.filter((event) => {
    const route = `${event.source} ${event.target}`.toLowerCase();
    return node.terms.some((term) => route.includes(term));
  });
  if (matching.some((event) => event.status === "violation" || ["high", "critical"].includes(event.risk))) return "danger";
  if (matching.some((event) => event.status === "blocked")) return "blocked";
  if (matching.length) return "active";
  return "idle";
}

export function AcademyAttackTrace({ events }: { events: AcademyEvent[] }) {
  return (
    <div aria-label="Academy 攻击链" className="grid gap-2 md:grid-cols-[repeat(15,minmax(0,1fr))] md:items-center">
      {nodes.map((node, index) => {
        const state = nodeState(node, events);
        const Icon = node.icon;
        return (
          <div key={node.id} className="contents">
            <div className={cn(
              "relative flex min-h-20 flex-col items-center justify-center rounded-xl border bg-muted/25 px-2 py-3 text-center transition-all md:col-span-1",
              state === "danger" && "border-red-500/50 bg-red-500/10 text-red-500 shadow-[0_0_24px_rgba(239,68,68,.12)]",
              state === "blocked" && "border-emerald-500/45 bg-emerald-500/10 text-emerald-500",
              state === "active" && "border-sky-500/35 bg-sky-500/[.07] text-sky-500",
            )}>
              <Icon className="h-4 w-4" />
              <span className="mt-2 text-[10px] font-semibold">{node.label}</span>
              {state !== "idle" ? <span className={cn("absolute right-2 top-2 h-1.5 w-1.5 rounded-full", state === "danger" ? "bg-red-400" : state === "blocked" ? "bg-emerald-400" : "bg-sky-400")} /> : null}
            </div>
            {index < nodes.length - 1 ? <div className="grid place-items-center text-muted-foreground md:col-span-1"><ArrowDown className="h-4 w-4 md:hidden" /><ArrowRight className="hidden h-4 w-4 md:block" /></div> : null}
          </div>
        );
      })}
    </div>
  );
}
