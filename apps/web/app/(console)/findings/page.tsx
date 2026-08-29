"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bug, CheckCircle2, Eye, FileCheck2, ShieldAlert, Target } from "lucide-react";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { useApp } from "@/components/providers";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label, Select } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { apiRequest, fetchPage } from "@/lib/api";
import type { Finding } from "@/lib/types";
import { formatDate } from "@/lib/utils";

const statuses = ["open", "confirmed", "false_positive", "accepted_risk", "fixed", "retest_required", "closed"];

export default function FindingsPage() {
  const { toast } = useApp();
  const client = useQueryClient();
  const [selected, setSelected] = useState<Finding | null>(null);
  const query = useQuery({ queryKey: ["findings"], queryFn: () => fetchPage<Finding>("/findings?page=1&page_size=200") });
  const update = useMutation({ mutationFn: ({ id, status }: { id: string; status: string }) => apiRequest<Finding>(`/findings/${id}`, { method: "PATCH", body: { status } }), onSuccess: (result) => { client.invalidateQueries({ queryKey: ["findings"] }); setSelected((current) => current?.id === result.id ? result : current); toast({ title: "Finding 状态已更新", description: `当前状态：${result.status}`, tone: "success" }); }, onError: (error) => toast({ title: "更新失败", description: error.message, tone: "error" }) });
  const items = query.data?.items || [];
  const columns: Column<Finding>[] = [
    { key: "finding", header: "Finding", searchValue: (row) => `${row.title} ${row.category} ${row.affected_target || ""}`, render: (row) => <div><p className="max-w-md font-medium">{row.title}</p><p className="mt-1 text-[10px] text-muted-foreground">{row.category} · {row.affected_target || "未指定目标"}</p></div> },
    { key: "severity", header: "严重性", searchValue: (row) => row.severity, render: (row) => <Badge tone={statusTone(row.severity)}>{row.severity}</Badge> },
    { key: "confidence", header: "置信度", render: (row) => <span className="font-mono text-xs">{typeof row.confidence === "number" ? `${Math.round(row.confidence * (row.confidence <= 1 ? 100 : 1))}%` : row.confidence || "—"}</span> },
    { key: "status", header: "状态", searchValue: (row) => row.status, render: (row) => <Badge tone={statusTone(row.status)}>{row.status}</Badge> },
    { key: "updated", header: "更新时间", render: (row) => <span className="text-xs text-muted-foreground">{formatDate(row.updated_at || row.created_at)}</span> },
    { key: "action", header: "操作", className: "text-right", render: (row) => <Button size="sm" variant="ghost" onClick={() => setSelected(row)}><Eye className="h-3.5 w-3.5" />处置</Button> },
  ];
  return (
    <div>
      <PageHeader eyebrow="RISK REGISTER" title="Findings" description="将规则与可选 Judge 结果转化为可处置风险，串联证据、影响、复现摘要、修复建议与复测状态。" actions={<Button asChild><Link href="/reports"><FileCheck2 className="h-4 w-4" />生成风险报告</Link></Button>} />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">{[
        { label: "严重", key: "critical", icon: ShieldAlert, tone: "text-red-400 bg-red-500/10" },
        { label: "高危", key: "high", icon: Bug, tone: "text-orange-400 bg-orange-500/10" },
        { label: "待复测", key: "retest_required", icon: Target, tone: "text-amber-400 bg-amber-500/10", status: true },
        { label: "已修复", key: "fixed", icon: CheckCircle2, tone: "text-emerald-400 bg-emerald-500/10", status: true },
      ].map((metric) => <Card key={metric.key} className="shadow-none"><CardContent className="flex items-center gap-3 p-4"><div className={`rounded-lg p-2.5 ${metric.tone}`}><metric.icon className="h-4 w-4" /></div><div><p className="font-mono text-xl font-semibold">{items.filter((item) => metric.status ? item.status === metric.key : item.severity.toLowerCase() === metric.key).length}</p><p className="text-[10px] text-muted-foreground">{metric.label}</p></div></CardContent></Card>)}</div>
      <Card className="overflow-hidden shadow-none">{query.isLoading ? <LoadingState label="正在汇总风险登记册…" /> : query.error ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : <DataTable data={items} columns={columns} rowKey={(row) => row.id} searchPlaceholder="搜索标题、类别或受影响目标…" filters={["critical", "high", "medium", "low"].map((severity) => ({ label: severity.toUpperCase(), value: severity, matches: (row: Finding) => row.severity.toLowerCase() === severity }))} emptyTitle="暂无 Findings" emptyDescription="完成 Mock Agent 安全测试后，违规结果会在这里形成 Finding。" />}</Card>
      <Dialog open={Boolean(selected)} onOpenChange={(value) => !value && setSelected(null)}><DialogContent className="max-w-3xl">{selected ? <><DialogHeader><DialogTitle className="pr-6">{selected.title}</DialogTitle><DialogDescription>{selected.category} · {selected.affected_target || "未指定目标"}</DialogDescription></DialogHeader><div className="flex flex-wrap gap-2"><Badge tone={statusTone(selected.severity)}>{selected.severity}</Badge><Badge tone={statusTone(selected.status)}>{selected.status}</Badge><Badge>{String(selected.confidence || "置信度未标注")}</Badge></div><div className="grid gap-3 sm:grid-cols-2"><DetailBlock title="描述" value={String(selected.description || "暂无描述")} /><DetailBlock title="影响" value={String(selected.impact || "暂无影响说明")} /><DetailBlock title="复现摘要" value={String(selected.reproduction_summary || "暂无复现摘要")} /><DetailBlock title="修复建议" value={String(selected.remediation || "暂无修复建议")} accent /></div><div><Label htmlFor="finding-status">处置状态</Label><Select id="finding-status" value={selected.status} disabled={update.isPending} onChange={(event) => update.mutate({ id: selected.id, status: event.target.value })}>{statuses.map((status) => <option key={status} value={status}>{status}</option>)}</Select></div><div className="flex gap-2"><Button asChild variant="outline" size="sm"><Link href={`/evidence?finding_id=${selected.id}`}>查看关联证据</Link></Button></div>{update.error ? <p className="rounded-lg bg-red-500/10 p-3 text-xs text-red-400">{update.error.message}</p> : null}<DialogFooter><Button variant="outline" onClick={() => setSelected(null)}>关闭</Button></DialogFooter></> : null}</DialogContent></Dialog>
    </div>
  );
}

function DetailBlock({ title, value, accent }: { title: string; value: string; accent?: boolean }) {
  return <div className={`rounded-lg border p-3 ${accent ? "border-teal-500/20 bg-teal-500/[.04]" : "bg-muted/25"}`}><p className="data-label">{title}</p><p className="mt-2 text-xs leading-5 text-muted-foreground">{value}</p></div>;
}
