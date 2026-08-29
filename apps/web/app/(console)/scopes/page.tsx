"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, FileWarning, Plus, Radar, ShieldCheck } from "lucide-react";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { useApp } from "@/components/providers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Select } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { apiRequest, fetchPage } from "@/lib/api";
import { scopeCreatePayload } from "@/lib/contracts";
import { scopeInputSchema } from "@/lib/schemas";
import type { AuthorizationScope, Project } from "@/lib/types";
import { formatDate, shortId } from "@/lib/utils";

const defaultExpiry = () => {
  const date = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000);
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 16);
};

export default function ScopesPage() {
  const { toast } = useApp();
  const client = useQueryClient();
  const [projectId, setProjectId] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [selected, setSelected] = useState<AuthorizationScope | null>(null);
  const [form, setForm] = useState({ name: "本地实验范围", target_value: "127.0.0.1", target_type: "ip" as "domain" | "ip" | "cidr", expires_at: defaultExpiry(), is_authorized: false });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const projects = useQuery({ queryKey: ["projects", "scope-selector"], queryFn: () => fetchPage<Project>("/projects?page=1&page_size=100") });
  useEffect(() => { if (!projectId && projects.data?.items[0]) setProjectId(projects.data.items[0].id); }, [projectId, projects.data]);
  const scopes = useQuery({ queryKey: ["scopes", projectId], queryFn: () => fetchPage<AuthorizationScope>(`/projects/${projectId}/scopes?page=1&page_size=100`), enabled: Boolean(projectId) });
  const create = useMutation({
    mutationFn: (data: typeof form) => apiRequest<AuthorizationScope>(`/projects/${projectId}/scopes`, { method: "POST", body: scopeCreatePayload(data) }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["scopes", projectId] });
      setCreateOpen(false);
      setForm({ name: "本地实验范围", target_value: "127.0.0.1", target_type: "ip", expires_at: defaultExpiry(), is_authorized: false });
      toast({ title: "授权范围已保存", description: "运行时仍将执行 DNS、重定向与到期时间复检。", tone: "success" });
    },
  });
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const parsed = scopeInputSchema.safeParse({ project_id: projectId, ...form });
    if (!parsed.success) {
      const next: Record<string, string> = {};
      parsed.error.issues.forEach((issue) => { next[String(issue.path[0])] = issue.message; });
      setErrors(next);
      return;
    }
    setErrors({});
    create.mutate(form);
  };
  const columns: Column<AuthorizationScope>[] = [
    { key: "target", header: "目标", searchValue: (row) => `${row.name} ${row.target_value}`, render: (row) => <div><p className="font-mono text-xs font-medium">{row.target_value}</p><p className="mt-1 text-[10px] text-muted-foreground">{row.name} · {row.target_type}</p></div> },
    { key: "authorization", header: "授权", searchValue: (row) => String(row.is_authorized), render: (row) => <Badge tone={row.is_authorized ? "success" : "danger"}>{row.is_authorized ? "authorized" : "blocked"}</Badge> },
    { key: "expires", header: "到期时间", render: (row) => <div className="flex items-center gap-1.5 text-xs text-muted-foreground"><CalendarClock className="h-3.5 w-3.5" />{formatDate(row.expires_at)}</div> },
    { key: "id", header: "策略 ID", searchValue: (row) => row.id, render: (row) => <span className="mono-value text-muted-foreground">{shortId(row.id)}</span> },
    { key: "action", header: "操作", className: "text-right", render: (row) => <Button size="sm" variant="ghost" onClick={() => setSelected(row)}><Radar className="h-3.5 w-3.5" />判定说明</Button> },
  ];
  return (
    <div>
      <PageHeader eyebrow="SCOPE GUARD" title="授权与测试范围" description="外部请求执行前校验目标、授权状态、到期时间、请求类型和工具风险。域名解析与每次重定向后都会重新检查 IP。" actions={<Button disabled={!projectId} onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" />添加授权范围</Button>} />
      <div className="mb-4 grid gap-3 md:grid-cols-3">
        <Card className="shadow-none md:col-span-2"><CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center"><div className="grid h-9 w-9 place-items-center rounded-lg bg-primary/10 text-primary"><ShieldCheck className="h-4 w-4" /></div><div className="min-w-0 flex-1"><p className="text-xs font-medium">选择项目范围</p><p className="mt-1 text-[10px] text-muted-foreground">每个项目独立维护授权边界</p></div><Select aria-label="选择项目" value={projectId} onChange={(event) => setProjectId(event.target.value)} className="sm:w-72"><option value="">请选择项目</option>{projects.data?.items.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</Select></CardContent></Card>
        <Card className="border-amber-500/20 bg-amber-500/[.035] shadow-none"><CardContent className="flex items-start gap-3 p-4"><FileWarning className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" /><div><p className="text-xs font-medium">默认阻止公网目标</p><p className="mt-1 text-[10px] leading-4 text-muted-foreground">仅明确添加并确认授权后可测试。</p></div></CardContent></Card>
      </div>
      <Card className="overflow-hidden shadow-none">{projects.isLoading || (projectId && scopes.isLoading) ? <LoadingState label="正在读取授权策略…" /> : projects.error ? <ErrorState error={projects.error} onRetry={() => projects.refetch()} /> : !projectId ? <EmptyState title="请先创建项目" description="授权范围必须归属于具体项目。" /> : scopes.error ? <ErrorState error={scopes.error} onRetry={() => scopes.refetch()} /> : <DataTable data={scopes.data?.items || []} columns={columns} rowKey={(row) => row.id} searchPlaceholder="搜索域名、IP、CIDR 或策略 ID…" filters={[{ label: "已授权", value: "authorized", matches: (row) => row.status === "authorized" || row.authorized !== false }, { label: "已阻止", value: "blocked", matches: (row) => row.status === "blocked" || row.authorized === false }]} emptyTitle="此项目尚无授权范围" emptyDescription="添加范围并确认已获得目标所有者的明确授权。" />}</Card>
      <Dialog open={createOpen} onOpenChange={setCreateOpen}><DialogContent><DialogHeader><DialogTitle>添加授权范围</DialogTitle><DialogDescription>这是一项安全边界变更。请准确填写目标并确认具有测试授权。</DialogDescription></DialogHeader><form onSubmit={submit} className="space-y-4"><div><Label htmlFor="scope-name">范围名称</Label><Input id="scope-name" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="本地实验范围" /><FieldError>{errors.name}</FieldError></div><div className="grid gap-4 sm:grid-cols-[.36fr_.64fr]"><div><Label htmlFor="scope-type">类型</Label><Select id="scope-type" value={form.target_type} onChange={(event) => setForm({ ...form, target_type: event.target.value as typeof form.target_type })}><option value="ip">IP</option><option value="cidr">CIDR</option><option value="domain">域名</option></Select></div><div><Label htmlFor="scope-target">目标</Label><Input id="scope-target" value={form.target_value} onChange={(event) => setForm({ ...form, target_value: event.target.value.trim() })} placeholder="127.0.0.1 / 10.0.0.0/8 / lab.example" /><FieldError>{errors.target_value}</FieldError></div></div><div><Label htmlFor="scope-expiry">授权到期时间</Label><Input id="scope-expiry" type="datetime-local" value={form.expires_at} onChange={(event) => setForm({ ...form, expires_at: event.target.value })} /><FieldError>{errors.expires_at}</FieldError></div><label className="flex cursor-pointer items-start gap-3 rounded-lg border border-amber-500/25 bg-amber-500/[.06] p-3"><input type="checkbox" className="mt-0.5 h-4 w-4 accent-teal-500" checked={form.is_authorized} onChange={(event) => setForm({ ...form, is_authorized: event.target.checked })} /><span className="text-xs leading-5">我确认已获得目标所有者明确授权，并理解范围外请求将被阻止。<FieldError>{errors.is_authorized}</FieldError></span></label>{create.error ? <p className="rounded-lg bg-red-500/10 p-3 text-xs text-red-400">{create.error.message}</p> : null}<DialogFooter><Button type="button" variant="outline" onClick={() => setCreateOpen(false)}>取消</Button><Button type="submit" loading={create.isPending}><ShieldCheck className="h-4 w-4" />确认并保存</Button></DialogFooter></form></DialogContent></Dialog>
      <Dialog open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}><DialogContent>{selected ? <><DialogHeader><DialogTitle>Scope Guard 判定说明</DialogTitle><DialogDescription className="font-mono">{selected.target_value}</DialogDescription></DialogHeader><div className="space-y-2">{["仅允许 HTTP / HTTPS 协议", "解析域名后重新检查所有 A / AAAA 地址", "阻止 IPv4-mapped IPv6 与 DNS Rebinding 绕过", "逐次检查重定向目标与授权到期时间", "保留请求 ID 和完整策略判定日志"].map((item) => <div key={item} className="flex items-center gap-2 rounded-lg border bg-muted/30 px-3 py-2.5 text-xs"><ShieldCheck className="h-3.5 w-3.5 text-primary" />{item}</div>)}</div><DialogFooter><Button variant="outline" onClick={() => setSelected(null)}>关闭</Button></DialogFooter></> : null}</DialogContent></Dialog>
    </div>
  );
}
