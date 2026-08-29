export const RUN_STATUSES = [
  "pending",
  "queued",
  "running",
  "waiting_approval",
  "completed",
  "failed",
  "cancelled",
] as const;

export type RunStatus = (typeof RUN_STATUSES)[number];

export const FINDING_STATUSES = [
  "open",
  "confirmed",
  "false_positive",
  "accepted_risk",
  "fixed",
  "retest_required",
  "closed",
] as const;

export type FindingStatus = (typeof FINDING_STATUSES)[number];
export type Severity = "info" | "low" | "medium" | "high" | "critical";

export interface RunEvent {
  id: string;
  run_id: string;
  type: "status" | "progress" | "policy" | "result" | "error";
  timestamp: string;
  message: string;
  data: Record<string, unknown>;
}
