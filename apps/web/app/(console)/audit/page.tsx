"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Eye, FileClock, RefreshCw, ShieldCheck, UserRound } from "lucide-react";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { fetchPage } from "@/lib/api";
import type { ApiRecord } from "@/lib/types";
import { formatDate, shortId } from "@/lib/utils";

type AuditLog = ApiRecord & { actor_id?: string; action: string; resource_type: string; resource_id?: string; outcome: string; ip_address?: string; user_agent?: string; request_id?: string; details?: Record<string, unknown> };

export default function AuditPage() {
  const [selected, setSelected] = useState<AuditLog | null>(null);
  const query = useQuery({ queryKey: ["audit-logs"], queryFn: () => fetchPage<AuditLog>("/audit-logs?page=1&page_size=100") });
  const columns: Column<AuditLog>[] = [
    { key: "action", header: "操作", searchValue: (row) => `${row.action} ${row.resource_type}`, render: (row) => <div className="flex items-center gap-3"><div className="rounded-lg bg-muted p-2"><FileClock className="h-4 w-4 text-primary" /></div><div><p className="font-mono text-xs font-semibold">{row.action}</p><p className="mt-1 text-[10px] text-muted-foreground">{row.resource_type} · {shortId(row.resource_id)}</p></div></div> },
    { key: "actor", header: "操作者", searchValue: (row) => row.actor_id || "system", render: (row) => <div className="flex items-center gap-1.5 text-xs"><UserRound className="h-3.5 w-3.5 text-muted-foreground" />{shortId(row.actor_id) || "system"}</div> },
    { key: "outcome", header: "结果", searchValue: (row) => row.outcome, render: (row) => <Badge tone={statusTone(row.outcome)}>{row.outcome}</Badge> },
    { key: "request", header: "请求 ID", searchValue: (row) => row.request_id || "", render: (row) => <span className="mono-value text-muted-foreground">{shortId(row.request_id)}</span> },
    { key: "ip", header: "来源 IP", searchValue: (row) => row.ip_address || "", render: (row) => <span className="font-mono text-[11px] text-muted-foreground">{row.ip_address || "—"}</span> },
    { key: "time", header: "时间", render: (row) => <span className="text-xs text-muted-foreground">{formatDate(row.created_at)}</span> },
    { key: "detail", header: "详情", className: "text-right", render: (row) => <Button size="sm" variant="ghost" onClick={() => setSelected(row)}><Eye className="h-3.5 w-3.5" />查看</Button> },
  ];
  return (
    <div>
      <PageHeader eyebrow="IMMUTABLE ACTIVITY TRAIL" title="审计日志" description="记录登录、项目与 Scope 变更、模型配置、测试执行、审批、数据删除、报告导出与系统设置修改。普通用户不可修改。" actions={<Button variant="outline" loading={query.isFetching} onClick={() => query.refetch()}><RefreshCw className="h-4 w-4" />刷新日志</Button>} />
      <div className="mb-4 flex items-start gap-3 rounded-xl border border-teal-500/20 bg-teal-500/[.045] p-4"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" /><p className="text-xs leading-5 text-muted-foreground"><span className="font-medium text-foreground">只读审计视图：</span>前端没有编辑或删除入口；日志详情中的敏感字段由后端脱敏。</p></div>
      <Card className="overflow-hidden shadow-none">{query.isLoading ? <LoadingState label="正在读取不可变审计轨迹…" /> : query.error ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : <DataTable data={query.data?.items || []} columns={columns} rowKey={(row) => row.id} searchPlaceholder="搜索操作、资源、请求 ID 或来源 IP…" filters={[{ label: "成功", value: "success", matches: (row) => row.outcome === "success" }, { label: "拒绝", value: "denied", matches: (row) => ["denied", "blocked", "failed"].includes(row.outcome) }, { label: "Scope 变更", value: "scope", matches: (row) => row.action.includes("scope") }]} emptyTitle="暂无审计日志" emptyDescription="受审计操作发生后会自动记录到这里。" />}</Card>
      <Dialog open={Boolean(selected)} onOpenChange={(value) => !value && setSelected(null)}><DialogContent className="max-w-2xl">{selected ? <><DialogHeader><DialogTitle>{selected.action}</DialogTitle><DialogDescription>请求 {selected.request_id || "—"} · {formatDate(selected.created_at)}</DialogDescription></DialogHeader><div className="grid gap-3 sm:grid-cols-2"><AuditField label="资源" value={`${selected.resource_type} / ${selected.resource_id || "—"}`} /><AuditField label="结果" value={selected.outcome} /><AuditField label="操作者" value={selected.actor_id || "system"} /><AuditField label="来源" value={`${selected.ip_address || "—"} · ${selected.user_agent || "unknown client"}`} /></div><div className="rounded-lg border bg-slate-950 p-3"><p className="data-label text-slate-500">DETAILS</p><pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-5 text-slate-300">{JSON.stringify(selected.details || {}, null, 2)}</pre></div><DialogFooter><Button variant="outline" onClick={() => setSelected(null)}>关闭</Button></DialogFooter></> : null}</DialogContent></Dialog>
    </div>
  );
}

function AuditField({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border bg-muted/25 p-3"><p className="data-label">{label}</p><p className="mt-2 break-all text-xs text-muted-foreground">{value}</p></div>;
}
