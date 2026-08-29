import { ShieldCheck, Waves } from "lucide-react";
import { cn } from "@/lib/utils";

export function Brand({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <div className="relative grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-xl border border-teal-400/25 bg-slate-950 text-teal-300 shadow-glow">
        <Waves className="absolute -bottom-1 -right-1 h-7 w-7 opacity-25" />
        <ShieldCheck className="relative h-5 w-5" />
      </div>
      {!compact ? (
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold tracking-wide">WhaleGuard</p>
          <p className="truncate text-[10px] uppercase tracking-[0.2em] text-muted-foreground">AI RedLab</p>
        </div>
      ) : null}
    </div>
  );
}
