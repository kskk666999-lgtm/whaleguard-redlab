"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Check, Clipboard, Eye, Fingerprint, Hash } from "lucide-react";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { useApp } from "@/components/providers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { fetchPage } from "@/lib/api";
import type { ApiRecord } from "@/lib/types";
import { formatDate, shortId } from "@/lib/utils";

type Evidence = ApiRecord & { evidence_type?: string; type?: string; title?: string; request_id?: string; finding_id?: string; response_summary?: string; hash_value?: string; sha256?: string; content_hash?: string; source?: string; size?: number; captured_at?: string; content?: Record<string, unknown> };

function EvidencePageContent() {
  const params = useSearchParams();
  const router = useRouter();
  const findingId = params.get("finding_id");
  const { toast } = useApp();
  const [selected, setSelected] = useState<Evidence | null>(null);
  const query = useQuery({ queryKey: ["evidence", findingId], queryFn: () => fetchPage<Evidence>(`/evidence?page=1&page_size=200${findingId ? `&finding_id=${encodeURIComponent(findingId)}` : ""}`) });
  const copyHash = async (value: string) => { await navigator.clipboard.writeText(value); toast({ title: "哈希已复制", description: "可用于离线校验证据完整性。", tone: "success" }); };
  const columns: Column<Evidence>[] = [
    { key: "type", header: "证据类型", searchValue: (row) => row.evidence_type || row.type || "record", render: (row) => <div className="flex items-center gap-2"><div className="rounded-md bg-primary/10 p-1.5 text-primary"><Fingerprint className="h-3.5 w-3.5" /></div><Badge tone="info">{row.evidence_type || row.type || "record"}</Badge></div> },
    { key: "summary", header: "响应摘要", searchValue: (row) => row.response_summary || "", render: (row) => <p className="max-w-lg truncate text-xs">{row.response_summary || "结构化证据记录"}</p> },
    { key: "request", header: "请求 ID", searchValue: (row) => row.request_id || row.id, render: (row) => <span className="mono-value text-muted-foreground">{shortId(row.request_id || row.id)}</span> },
    { key: "hash", header: "SHA-256", searchValue: (row) => row.hash_value || row.sha256 || row.content_hash || "", render: (row) => { const hash = row.hash_value || row.sha256 || row.content_hash; return hash ? <button className="focus-ring flex items-center gap-1.5 rounded font-mono text-[10px] text-muted-foreground hover:text-primary" onClick={() => copyHash(hash)} title="复制完整哈希"><Hash className="h-3 w-3" />{shortId(hash)}</button> : <span className="text-xs text-muted-foreground">—</span>; } },
    { key: "timestamp", header: "时间戳", render: (row) => <span className="text-xs text-muted-foreground">{formatDate(row.created_at)}</span> },
    { key: "action", header: "操作", className: "text-right", render: (row) => <Button size="sm" variant="ghost" onClick={() => setSelected(row)}><Eye className="h-3.5 w-3.5" />查看</Button> },
  ];
  return (
    <div>
      <PageHeader eyebrow="CHAIN OF EVIDENCE" title="证据中心" description="统一保存原始输入、模型输出、Tool Call、Policy Decision、时间戳、请求 ID、附件元数据与 SHA-256 哈希。" actions={findingId ? <Button variant="outline" onClick={() => router.push("/evidence")}>清除 Finding 过滤</Button> : undefined} />
      {findingId ? <div className="mb-4 flex items-center gap-2 rounded-xl border border-sky-500/20 bg-sky-500/[.05] px-4 py-3 text-xs"><Check className="h-4 w-4 text-sky-400" />正在查看 Finding <span className="font-mono">{shortId(findingId)}</span> 的关联证据</div> : null}
      <Card className="overflow-hidden shadow-none">{query.isLoading ? <LoadingState label="正在校验证据索引…" /> : query.error ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : <DataTable data={query.data?.items || []} columns={columns} rowKey={(row) => row.id} searchPlaceholder="搜索摘要、请求 ID 或证据哈希…" filters={["input", "output", "tool_call", "policy_decision", "attachment"].map((type) => ({ label: type, value: type, matches: (row: Evidence) => (row.evidence_type || row.type || "").includes(type) }))} emptyTitle="暂无证据记录" emptyDescription="测试运行会自动保存经过脱敏的输入、输出、策略判定和完整性哈希。" />}</Card>
      <Dialog open={Boolean(selected)} onOpenChange={(value) => !value && setSelected(null)}><DialogContent className="max-w-3xl">{selected ? <><DialogHeader><DialogTitle>{selected.title || "证据记录"}</DialogTitle><DialogDescription>请求 {selected.request_id || selected.id} · {formatDate(selected.captured_at || selected.created_at)}</DialogDescription></DialogHeader><div className="grid gap-3 sm:grid-cols-2"><EvidenceBlock label="证据类型" value={selected.evidence_type || "record"} /><EvidenceBlock label="响应摘要" value={selected.response_summary || "—"} /><div className="sm:col-span-2"><EvidenceBlock label="结构化内容（脱敏）" value={selected.content || {}} code /></div><div className="sm:col-span-2"><EvidenceBlock label="SHA-256" value={selected.hash_value || selected.sha256 || selected.content_hash || "—"} code /></div></div><DialogFooter><Button variant="outline" onClick={() => setSelected(null)}>关闭</Button>{selected.hash_value || selected.sha256 || selected.content_hash ? <Button onClick={() => copyHash((selected.hash_value || selected.sha256 || selected.content_hash)!)}><Clipboard className="h-4 w-4" />复制哈希</Button> : <Button disabled title="此证据无可复制哈希"><Clipboard className="h-4 w-4" />无哈希</Button>}</DialogFooter></> : null}</DialogContent></Dialog>
    </div>
  );
}

export default function EvidencePage() {
  return (
    <Suspense fallback={<LoadingState label="正在准备证据索引…" />}>
      <EvidencePageContent />
    </Suspense>
  );
}

function EvidenceBlock({ label, value, code }: { label: string; value: unknown; code?: boolean }) {
  const text = typeof value === "string" ? value : value == null ? "—" : JSON.stringify(value, null, 2);
  return <div className="rounded-lg border bg-muted/25 p-3"><p className="data-label">{label}</p><pre className={`mt-2 max-h-36 overflow-auto whitespace-pre-wrap break-all text-[11px] leading-5 text-muted-foreground ${code ? "font-mono" : "font-sans"}`}>{text}</pre></div>;
}
