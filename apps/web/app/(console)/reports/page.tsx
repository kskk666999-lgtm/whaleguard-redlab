"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileCode2, FileJson2, FileText, Plus, RefreshCw } from "lucide-react";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { useApp } from "@/components/providers";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Select } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { API_BASE, apiRequest, fetchPage } from "@/lib/api";
import { reportCreatePayload } from "@/lib/contracts";
import { getToken } from "@/lib/auth";
import { reportInputSchema } from "@/lib/schemas";
import type { Project, Report } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export default function ReportsPage() {
  const { toast } = useApp();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [form, setForm] = useState({ project_id: "", name: `WhaleGuard 安全评估报告`, format: "html" as "html" | "markdown" | "json" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const reports = useQuery({ queryKey: ["reports"], queryFn: () => fetchPage<Report>("/reports?page=1&page_size=100") });
  const projects = useQuery({ queryKey: ["projects", "report-selector"], queryFn: () => fetchPage<Project>("/projects?page=1&page_size=100") });
  useEffect(() => { if (!form.project_id && projects.data?.items[0]) setForm((value) => ({ ...value, project_id: projects.data!.items[0].id })); }, [form.project_id, projects.data]);
  const create = useMutation({ mutationFn: async (data: typeof form) => { const report = await apiRequest<Report>("/reports", { method: "POST", body: reportCreatePayload(data) }); return apiRequest<Report>(`/reports/${report.id}/generate`, { method: "POST" }); }, onSuccess: () => { client.invalidateQueries({ queryKey: ["reports"] }); setOpen(false); toast({ title: "报告已生成", description: "已汇总 Findings、证据摘要、评分解释与修复建议。", tone: "success" }); } });
  const generate = useMutation({ mutationFn: (report: Report) => apiRequest<Report>(`/reports/${report.id}/generate`, { method: "POST" }), onMutate: (report) => setBusyId(report.id), onSuccess: () => { client.invalidateQueries({ queryKey: ["reports"] }); toast({ title: "报告已重新生成", tone: "success" }); }, onError: (error) => toast({ title: "生成失败", description: error.message, tone: "error" }), onSettled: () => setBusyId(null) });
  const submit = (event: React.FormEvent) => { event.preventDefault(); const parsed = reportInputSchema.safeParse(form); if (!parsed.success) { const next: Record<string, string> = {}; parsed.error.issues.forEach((issue) => { next[String(issue.path[0])] = issue.message; }); setErrors(next); return; } setErrors({}); create.mutate(parsed.data); };
  const download = async (report: Report) => {
    setBusyId(report.id);
    try {
      const format = report.formats?.[0] || "html";
      const response = await fetch(`${API_BASE}/reports/${report.id}/download?format=${encodeURIComponent(format)}`, { headers: { ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}) } });
      if (!response.ok) throw new Error(`下载失败（HTTP ${response.status}）`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${report.name.replace(/[^\w\u4e00-\u9fa5-]+/g, "-")}.${format === "markdown" ? "md" : format}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      toast({ title: "报告下载已开始", tone: "success" });
    } catch (error) {
      toast({ title: "下载失败", description: error instanceof Error ? error.message : "未知错误", tone: "error" });
    } finally { setBusyId(null); }
  };
  const columns: Column<Report>[] = [
    { key: "report", header: "报告", searchValue: (row) => `${row.name} ${row.project_name || ""}`, render: (row) => { const format = row.formats?.[0] || "html"; return <div className="flex items-center gap-3"><div className="rounded-lg bg-primary/10 p-2 text-primary">{format === "json" ? <FileJson2 className="h-4 w-4" /> : format === "markdown" ? <FileText className="h-4 w-4" /> : <FileCode2 className="h-4 w-4" />}</div><div><p className="font-medium">{row.name}</p><p className="mt-1 text-[10px] text-muted-foreground">{row.project_name || "授权项目"}</p></div></div>; } },
    { key: "format", header: "格式", searchValue: (row) => (row.formats || ["html"]).join(" "), render: (row) => <div className="flex gap-1">{(row.formats || ["html"]).map((format) => <Badge key={format} tone="info">{format.toUpperCase()}</Badge>)}</div> },
    { key: "status", header: "状态", searchValue: (row) => row.status || "completed", render: (row) => <Badge tone={statusTone(row.status || "completed")}>{row.status || "completed"}</Badge> },
    { key: "generated", header: "生成时间", render: (row) => <span className="text-xs text-muted-foreground">{formatDate(row.generated_at || row.updated_at || row.created_at)}</span> },
    { key: "actions", header: "操作", className: "text-right", render: (row) => <div className="flex justify-end gap-1"><Button aria-label="重新生成报告" size="icon" variant="ghost" className="h-8 w-8" loading={busyId === row.id && generate.isPending} disabled={busyId !== null && busyId !== row.id} onClick={() => generate.mutate(row)}><RefreshCw className="h-3.5 w-3.5" /></Button><Button size="sm" variant="outline" loading={busyId === row.id && !generate.isPending} disabled={(row.status && !["completed", "generated", "ready"].includes(row.status)) || (busyId !== null && busyId !== row.id)} onClick={() => download(row)}><Download className="h-3.5 w-3.5" />下载</Button></div> },
  ];
  return (
    <div>
      <PageHeader eyebrow="EVIDENCE-BACKED OUTPUT" title="报告中心" description="从结构化 Findings 与证据生成 HTML、Markdown 和 JSON 报告，包含评分解释、复现摘要、影响与修复建议。" actions={<Button onClick={() => setOpen(true)} disabled={!projects.data?.items.length}><Plus className="h-4 w-4" />生成报告</Button>} />
      <div className="mb-4 grid gap-3 md:grid-cols-3">{[{ icon: FileCode2, label: "HTML", note: "离线自包含，适合浏览与归档" }, { icon: FileText, label: "Markdown", note: "适合 GitHub 与代码评审" }, { icon: FileJson2, label: "JSON", note: "机器可读，便于二次集成" }].map((format) => <Card key={format.label} className="shadow-none"><CardContent className="flex items-center gap-3 p-4"><div className="rounded-lg bg-muted p-2"><format.icon className="h-4 w-4 text-primary" /></div><div><p className="text-xs font-semibold">{format.label}</p><p className="mt-1 text-[10px] text-muted-foreground">{format.note}</p></div></CardContent></Card>)}</div>
      <Card className="overflow-hidden shadow-none">{reports.isLoading ? <LoadingState label="正在读取报告索引…" /> : reports.error ? <ErrorState error={reports.error} onRetry={() => reports.refetch()} /> : <DataTable data={reports.data?.items || []} columns={columns} rowKey={(row) => row.id} searchPlaceholder="搜索报告或项目…" filters={["html", "markdown", "json"].map((format) => ({ label: format.toUpperCase(), value: format, matches: (row: Report) => (row.formats || ["html"]).includes(format) }))} emptyTitle="暂无报告" emptyDescription="完成安全测试并产生 Finding 后，可以生成第一份证据化报告。" />}</Card>
      <Dialog open={open} onOpenChange={setOpen}><DialogContent><DialogHeader><DialogTitle>生成安全评估报告</DialogTitle><DialogDescription>报告将引用当前项目的 Findings 与证据摘要，不包含 API Key 或完整敏感内容。</DialogDescription></DialogHeader><form className="space-y-4" onSubmit={submit}><div><Label htmlFor="report-project">项目</Label><Select id="report-project" value={form.project_id} onChange={(event) => setForm({ ...form, project_id: event.target.value })}>{projects.data?.items.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</Select><FieldError>{errors.project_id}</FieldError></div><div><Label htmlFor="report-name">报告名称</Label><Input id="report-name" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /><FieldError>{errors.name}</FieldError></div><div><Label htmlFor="report-format">输出格式</Label><Select id="report-format" value={form.format} onChange={(event) => setForm({ ...form, format: event.target.value as typeof form.format })}><option value="html">HTML（推荐）</option><option value="markdown">Markdown</option><option value="json">JSON</option></Select></div>{create.error ? <p className="rounded-lg bg-red-500/10 p-3 text-xs text-red-400">{create.error.message}</p> : null}<DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>取消</Button><Button type="submit" loading={create.isPending}><FileCode2 className="h-4 w-4" />创建并生成</Button></DialogFooter></form></DialogContent></Dialog>
    </div>
  );
}
