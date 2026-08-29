import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "success" | "warning" | "danger" | "info" | "purple";

const tones: Record<Tone, string> = {
  neutral: "border-border bg-muted text-muted-foreground",
  success: "border-emerald-500/25 bg-emerald-500/10 text-emerald-500 dark:text-emerald-300",
  warning: "border-amber-500/25 bg-amber-500/10 text-amber-600 dark:text-amber-300",
  danger: "border-red-500/25 bg-red-500/10 text-red-600 dark:text-red-300",
  info: "border-sky-500/25 bg-sky-500/10 text-sky-600 dark:text-sky-300",
  purple: "border-violet-500/25 bg-violet-500/10 text-violet-600 dark:text-violet-300",
};

export function Badge({ tone = "neutral", className, ...props }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return <span className={cn("inline-flex items-center whitespace-nowrap rounded-md border px-2 py-0.5 text-[11px] font-medium", tones[tone], className)} {...props} />;
}

export function statusTone(value?: string): Tone {
  const normalized = value?.toLowerCase() || "";
  if (["active", "enabled", "completed", "fixed", "confirmed", "healthy", "authorized", "passed", "closed"].includes(normalized)) return "success";
  if (["failed", "critical", "high", "blocked", "expired", "cancelled", "open"].includes(normalized)) return "danger";
  if (["warning", "medium", "waiting_approval", "retest_required", "queued", "pending"].includes(normalized)) return "warning";
  if (["running", "info", "low"].includes(normalized)) return "info";
  if (["accepted_risk", "false_positive", "paused"].includes(normalized)) return "purple";
  return "neutral";
}
