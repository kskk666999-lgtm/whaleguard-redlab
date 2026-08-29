"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, FolderPlus, Plus, ShieldCheck } from "lucide-react";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { useApp } from "@/components/providers";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Textarea } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { apiRequest, fetchPage } from "@/lib/api";
import { projectInputSchema } from "@/lib/schemas";
import type { Project } from "@/lib/types";
import { formatDate, shortId } from "@/lib/utils";

export default function ProjectsPage() {
  const { toast } = useApp();
  const client = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [selected, setSelected] = useState<Project | null>(null);
  const [form, setForm] = useState({ name: "", description: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const query = useQuery({ queryKey: ["projects"], queryFn: () => fetchPage<Project>("/projects?page=1&page_size=100") });
  const mutation = useMutation({
    mutationFn: (data: typeof form) => apiRequest<Project>("/projects", { method: "POST", body: data }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["projects"] });
      setCreateOpen(false);
      setForm({ name: "", description: "" });
      toast({ title: "项目已创建", description: "现在可以配置授权范围与测试目标。", tone: "success" });
    },
  });
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const parsed = projectInputSchema.safeParse(form);
    if (!parsed.success) {
      const next: Record<string, string> = {};
      parsed.error.issues.forEach((issue) => { next[String(issue.path[0])] = issue.message; });
      setErrors(next);
      return;
    }
    setErrors({});
    mutation.mutate(parsed.data);
  };
  const columns: Column<Project>[] = [
    { key: "name", header: "项目", searchValue: (row) => `${row.name} ${row.description || ""}`, render: (row) => <div><p className="font-medium">{row.name}</p><p className="mt-1 max-w-md truncate text-[11px] text-muted-foreground">{row.description || "暂无描述"}</p></div> },
    { key: "id", header: "项目 ID", searchValue: (row) => row.id, render: (row) => <span className="mono-value text-muted-foreground">{shortId(row.id)}</span> },
    { key: "status", header: "状态", searchValue: (row) => row.status || "active", render: (row) => <Badge tone={statusTone(row.status || "active")}>{row.status || "active"}</Badge> },
    { key: "score", header: "安全得分", render: (row) => <span className="font-mono text-sm font-semibold">{typeof row.security_score === "number" ? row.security_score : "—"}</span> },
    { key: "findings", header: "Findings", render: (row) => <span className="font-mono text-xs">{row.finding_count ?? 0}</span> },
    { key: "updated", header: "更新时间", render: (row) => <span className="text-xs text-muted-foreground">{formatDate(row.updated_at || row.created_at)}</span> },
    { key: "action", header: "操作", className: "text-right", render: (row) => <Button size="sm" variant="ghost" onClick={() => setSelected(row)}><Eye className="h-3.5 w-3.5" />详情</Button> },
  ];
  return (
    <div>
      <PageHeader eyebrow="WORKSPACES" title="项目中心" description="隔离管理目标、授权范围、模型渠道、测试资产与风险证据。创建项目不会自动发起任何网络请求。" actions={<Button onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" />新建项目</Button>} />
      <Card className="overflow-hidden shadow-none">{query.isLoading ? <LoadingState /> : query.error ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : <DataTable data={query.data?.items || []} columns={columns} rowKey={(row) => row.id} searchPlaceholder="搜索项目名称、描述或 ID…" filters={[{ label: "活跃", value: "active", matches: (row) => (row.status || "active") === "active" }, { label: "已归档", value: "archived", matches: (row) => row.status === "archived" }]} emptyTitle="尚未创建项目" emptyDescription="项目是授权范围、测试运行与 Findings 的隔离边界。" />}</Card>
      <Dialog open={createOpen} onOpenChange={setCreateOpen}><DialogContent><DialogHeader><DialogTitle>创建安全评估项目</DialogTitle><DialogDescription>仅填写项目元数据。创建后仍需单独配置并确认授权范围。</DialogDescription></DialogHeader><form onSubmit={submit} className="space-y-4"><div><Label htmlFor="project-name">项目名称</Label><Input id="project-name" autoFocus value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：本地 Agent 安全基线" /><FieldError>{errors.name}</FieldError></div><div><Label htmlFor="project-description">项目说明</Label><Textarea id="project-description" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="描述授权背景、测试目标和责任人（不要填写凭据）" /><FieldError>{errors.description}</FieldError></div>{mutation.error ? <p className="rounded-lg bg-red-500/10 p-3 text-xs text-red-400">{mutation.error.message}</p> : null}<DialogFooter><Button type="button" variant="outline" onClick={() => setCreateOpen(false)}>取消</Button><Button type="submit" loading={mutation.isPending}><FolderPlus className="h-4 w-4" />创建项目</Button></DialogFooter></form></DialogContent></Dialog>
      <Dialog open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}><DialogContent>{selected ? <><DialogHeader><DialogTitle>{selected.name}</DialogTitle><DialogDescription>{selected.description || "暂无项目描述"}</DialogDescription></DialogHeader><div className="grid grid-cols-2 gap-3"><div className="rounded-lg border bg-muted/35 p-3"><p className="data-label">PROJECT ID</p><p className="mono-value mt-2 break-all">{selected.id}</p></div><div className="rounded-lg border bg-muted/35 p-3"><p className="data-label">STATUS</p><div className="mt-2"><Badge tone={statusTone(selected.status || "active")}>{selected.status || "active"}</Badge></div></div></div><div className="flex items-start gap-3 rounded-lg border border-teal-500/20 bg-teal-500/5 p-3"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-teal-400" /><p className="text-xs leading-5 text-muted-foreground">项目存在不代表目标已获授权。测试运行前仍会执行 Scope Guard 判定。</p></div><DialogFooter><Button variant="outline" onClick={() => setSelected(null)}>关闭</Button></DialogFooter></> : null}</DialogContent></Dialog>
    </div>
  );
}
