"use client";

import { useState } from "react";
import { Check, ShieldAlert, X } from "lucide-react";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label, Textarea } from "@/components/ui/input";
import type { ApiRecord } from "@/lib/types";

export type ApprovalRequest = ApiRecord & {
  project_id: string;
  run_id?: string | null;
  action_type: string;
  risk_level: string;
  reason: string;
  status: string;
};

type Props = {
  approval?: ApprovalRequest;
  loading: boolean;
  error?: Error | null;
  decisionError?: Error | null;
  busy: boolean;
  onRetry: () => void;
  onDecision: (status: "approved" | "rejected", reason: string) => void;
};

export function RunApprovalControls({ approval, loading, error, decisionError, busy, onRetry, onDecision }: Props) {
  const [reason, setReason] = useState("");
  const canDecide = Boolean(approval && reason.trim() && !busy);

  if (loading) return <div className="rounded-lg border border-amber-500/20 bg-amber-500/[.04] p-4 text-xs text-muted-foreground">正在读取待处理审批…</div>;
  if (error) return <div role="alert" className="rounded-lg border border-red-500/20 bg-red-500/[.05] p-4 text-xs text-red-500 dark:text-red-300"><p>审批请求读取失败：{error.message}</p><Button className="mt-3" size="sm" variant="outline" onClick={onRetry}>重新读取</Button></div>;
  if (!approval) return <div className="rounded-lg border border-amber-500/20 bg-amber-500/[.04] p-4 text-xs text-muted-foreground">任务正在等待审批，但尚未读取到对应的待处理请求。队列同步后可重新打开详情。</div>;

  return (
    <section aria-label="高风险操作审批" className="rounded-xl border border-amber-500/25 bg-amber-500/[.045] p-4">
      <div className="flex items-start gap-3">
        <div className="rounded-lg bg-amber-500/10 p-2 text-amber-500"><ShieldAlert className="h-4 w-4" /></div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2"><p className="text-sm font-medium">高风险操作需要人工审批</p><Badge tone={statusTone(approval.risk_level)}>{approval.risk_level}</Badge></div>
          <p className="mt-1 text-xs text-muted-foreground">{approval.action_type} · {approval.reason}</p>
        </div>
      </div>
      <div className="mt-4">
        <Label htmlFor="approval-decision-reason">审批理由</Label>
        <Textarea id="approval-decision-reason" value={reason} disabled={busy} maxLength={10000} onChange={(event) => setReason(event.target.value)} placeholder="记录授权核验、风险判断和决定依据（必填）" className="min-h-20" />
      </div>
      {decisionError ? <p role="alert" className="mt-2 text-xs text-red-500 dark:text-red-300">审批提交失败：{decisionError.message}</p> : null}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" loading={busy} disabled={!canDecide} title={reason.trim() ? "批准并重新入队" : "请先填写审批理由"} onClick={() => onDecision("approved", reason.trim())}><Check className="h-3.5 w-3.5" />批准并继续</Button>
        <Button size="sm" variant="destructive" disabled={!canDecide} title={reason.trim() ? "拒绝并取消任务" : "请先填写审批理由"} onClick={() => onDecision("rejected", reason.trim())}><X className="h-3.5 w-3.5" />拒绝并取消</Button>
      </div>
    </section>
  );
}
