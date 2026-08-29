"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Eye, FilePlus2, Plus } from "lucide-react";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { useApp } from "@/components/providers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { apiRequest, fetchPage } from "@/lib/api";
import type { ApiRecord, Project } from "@/lib/types";
import { formatDate } from "@/lib/utils";

type KnowledgeDocument = ApiRecord & { title: string; content?: string; source_type?: string; source?: string; tags?: string[]; project_name?: string; chunk_count?: number; sha256?: string };

export default function KnowledgePage() {
  const { toast } = useApp();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<KnowledgeDocument | null>(null);
  const [form, setForm] = useState({ project_id: "", title: "", source_type: "manual", content: "", tags: "" });
  const documents = useQuery({ queryKey: ["knowledge"], queryFn: () => fetchPage<KnowledgeDocument>("/knowledge?page=1&page_size=100") });
  const projects = useQuery({ queryKey: ["projects", "knowledge-selector"], queryFn: () => fetchPage<Project>("/projects?page=1&page_size=100") });
  useEffect(() => { if (!form.project_id && projects.data?.items[0]) setForm((value) => ({ ...value, project_id: projects.data!.items[0].id })); }, [form.project_id, projects.data]);
  const create = useMutation({ mutationFn: () => apiRequest<KnowledgeDocument>("/knowledge", { method: "POST", body: { ...form, tags: form.tags.split(",").map((item) => item.trim()).filter(Boolean) } }), onSuccess: () => { client.invalidateQueries({ queryKey: ["knowledge"] }); setOpen(false); setForm((value) => ({ ...value, title: "", content: "", tags: "" })); toast({ title: "知识文档已添加", description: "仅用于授权实验项目的模拟检索上下文。", tone: "success" }); } });
  const columns: Column<KnowledgeDocument>[] = [
    { key: "title", header: "文档", searchValue: (row) => `${row.title} ${row.content || ""}`, render: (row) => <div className="flex items-center gap-3"><div className="rounded-lg bg-primary/10 p-2 text-primary"><BookOpen className="h-4 w-4" /></div><div><p className="font-medium">{row.title}</p><p className="mt-1 max-w-md truncate text-[10px] text-muted-foreground">{row.source || row.project_name || "本地知识库"}</p></div></div> },
    { key: "type", header: "类型", searchValue: (row) => row.source_type || "manual", render: (row) => <Badge tone="info">{row.source_type || "manual"}</Badge> },
    { key: "chunks", header: "分块", render: (row) => <span className="font-mono text-xs">{row.chunk_count ?? "—"}</span> },
    { key: "tags", header: "标签", render: (row) => <div className="flex max-w-52 flex-wrap gap-1">{row.tags?.slice(0, 3).map((tag) => <Badge key={tag}>{tag}</Badge>) || "—"}</div> },
    { key: "updated", header: "更新时间", render: (row) => <span className="text-xs text-muted-foreground">{formatDate(row.updated_at || row.created_at)}</span> },
    { key: "action", header: "操作", className: "text-right", render: (row) => <Button size="sm" variant="ghost" onClick={() => setSelected(row)}><Eye className="h-3.5 w-3.5" />预览</Button> },
  ];
  return (
    <div>
      <PageHeader eyebrow="AUTHORIZED CONTEXT" title="知识库" description="保存用于本地 Agent 与 RAG 投毒模拟的虚构、非敏感上下文。不要上传真实凭据、生产数据或受限个人信息。" actions={<Button onClick={() => setOpen(true)} disabled={!projects.data?.items.length}><Plus className="h-4 w-4" />添加文档</Button>} />
      <Card className="overflow-hidden shadow-none">{documents.isLoading ? <LoadingState label="正在读取知识文档…" /> : documents.error ? <ErrorState error={documents.error} onRetry={() => documents.refetch()} /> : <DataTable data={documents.data?.items || []} columns={columns} rowKey={(row) => row.id} searchPlaceholder="搜索标题、内容或标签…" filters={["manual", "demo", "reference"].map((type) => ({ label: type, value: type, matches: (row: KnowledgeDocument) => (row.source_type || "").includes(type) }))} emptyTitle="暂无知识文档" emptyDescription="添加虚构知识文档，为 Mock Agent 的 RAG 安全测试提供上下文。" />}</Card>
      <Dialog open={open} onOpenChange={setOpen}><DialogContent><DialogHeader><DialogTitle>添加知识文档</DialogTitle><DialogDescription>仅允许纯文本模拟资料；内容会经过大小与类型限制。</DialogDescription></DialogHeader><form className="space-y-4" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}><div><Label htmlFor="knowledge-project">项目</Label><Select id="knowledge-project" value={form.project_id} onChange={(event) => setForm({ ...form, project_id: event.target.value })}>{projects.data?.items.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</Select></div><div className="grid gap-4 sm:grid-cols-2"><div><Label htmlFor="knowledge-title">标题</Label><Input id="knowledge-title" required minLength={2} value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></div><div><Label htmlFor="knowledge-type">来源类型</Label><Select id="knowledge-type" value={form.source_type} onChange={(event) => setForm({ ...form, source_type: event.target.value })}><option value="manual">manual</option><option value="demo">demo</option><option value="reference">reference</option></Select></div></div><div><Label htmlFor="knowledge-content">纯文本内容</Label><Textarea id="knowledge-content" required maxLength={20000} className="min-h-48" value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} placeholder="输入虚构、非敏感的演示知识内容…" /><p className="mt-1 text-right text-[10px] text-muted-foreground">{form.content.length} / 20,000</p></div><div><Label htmlFor="knowledge-tags">标签（逗号分隔）</Label><Input id="knowledge-tags" value={form.tags} onChange={(event) => setForm({ ...form, tags: event.target.value })} placeholder="demo, safe-rag" /></div>{create.error ? <p className="rounded-lg bg-red-500/10 p-3 text-xs text-red-400">{create.error.message}</p> : null}<DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>取消</Button><Button type="submit" loading={create.isPending}><FilePlus2 className="h-4 w-4" />保存文档</Button></DialogFooter></form></DialogContent></Dialog>
      <Dialog open={Boolean(selected)} onOpenChange={(value) => !value && setSelected(null)}><DialogContent>{selected ? <><DialogHeader><DialogTitle>{selected.title}</DialogTitle><DialogDescription>{selected.source_type || "manual"} · {formatDate(selected.created_at)}</DialogDescription></DialogHeader><pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg border bg-muted/25 p-4 font-sans text-xs leading-6 text-muted-foreground">{selected.content || "API 未返回正文预览。"}</pre><DialogFooter><Button variant="outline" onClick={() => setSelected(null)}>关闭</Button></DialogFooter></> : null}</DialogContent></Dialog>
    </div>
  );
}
