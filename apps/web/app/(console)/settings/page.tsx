"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Moon, Pencil, Save, Settings2, ShieldCheck, Sun } from "lucide-react";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { useApp } from "@/components/providers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Label, Textarea } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { apiRequest, fetchPage } from "@/lib/api";
import type { ApiRecord } from "@/lib/types";
import { formatDate } from "@/lib/utils";

type SystemSetting = ApiRecord & { key: string; value: Record<string, unknown>; description?: string; is_secret?: boolean; updated_by_id?: string };

export default function SettingsPage() {
  const { theme, toggleTheme, toast } = useApp();
  const client = useQueryClient();
  const [selected, setSelected] = useState<SystemSetting | null>(null);
  const [json, setJson] = useState("{}");
  const [description, setDescription] = useState("");
  const [parseError, setParseError] = useState("");
  const query = useQuery({ queryKey: ["settings"], queryFn: () => fetchPage<SystemSetting>("/settings?page=1&page_size=100") });
  useEffect(() => { if (selected) { setJson(JSON.stringify(selected.value, null, 2)); setDescription(selected.description || ""); setParseError(""); } }, [selected]);
  const update = useMutation({ mutationFn: ({ setting, value }: { setting: SystemSetting; value: Record<string, unknown> }) => apiRequest<SystemSetting>(`/settings/${encodeURIComponent(setting.key)}`, { method: "PUT", body: { value, description, is_secret: setting.is_secret || false } }), onSuccess: () => { client.invalidateQueries({ queryKey: ["settings"] }); setSelected(null); toast({ title: "系统设置已保存", description: "变更已写入审计日志。", tone: "success" }); } });
  const save = (event: React.FormEvent) => { event.preventDefault(); if (!selected) return; try { const value = JSON.parse(json) as unknown; if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("设置值必须是 JSON 对象"); setParseError(""); update.mutate({ setting: selected, value: value as Record<string, unknown> }); } catch (error) { setParseError(error instanceof Error ? error.message : "JSON 格式无效"); } };
  const columns: Column<SystemSetting>[] = [
    { key: "key", header: "设置键", searchValue: (row) => `${row.key} ${row.description || ""}`, render: (row) => <div className="flex items-center gap-3"><div className="rounded-lg bg-muted p-2"><Settings2 className="h-4 w-4 text-primary" /></div><div><p className="font-mono text-xs font-semibold">{row.key}</p><p className="mt-1 max-w-md truncate text-[10px] text-muted-foreground">{row.description || "无说明"}</p></div></div> },
    { key: "value", header: "值摘要", render: (row) => row.is_secret ? <Badge tone="warning"><KeyRound className="mr-1 h-3 w-3" />已加密</Badge> : <span className="block max-w-72 truncate font-mono text-[10px] text-muted-foreground">{JSON.stringify(row.value)}</span> },
    { key: "scope", header: "类型", searchValue: (row) => row.is_secret ? "secret" : "standard", render: (row) => <Badge tone={row.is_secret ? "warning" : "neutral"}>{row.is_secret ? "secret" : "standard"}</Badge> },
    { key: "updated", header: "更新时间", render: (row) => <span className="text-xs text-muted-foreground">{formatDate(row.updated_at)}</span> },
    { key: "action", header: "操作", className: "text-right", render: (row) => <Button size="sm" variant="ghost" onClick={() => setSelected(row)}><Pencil className="h-3.5 w-3.5" />编辑</Button> },
  ];
  return (
    <div>
      <PageHeader eyebrow="PLATFORM GOVERNANCE" title="系统设置" description="管理平台级安全策略与运行参数。敏感设置加密保存，修改操作仅对具备 settings.write 权限的角色开放并全程审计。" />
      <div className="mb-4 grid gap-4 lg:grid-cols-2">
        <Card className="shadow-none"><CardHeader><div><p className="data-label">APPEARANCE</p><h2 className="mt-1 text-sm font-semibold">界面主题</h2></div></CardHeader><CardContent className="flex items-center gap-4"><div className="grid h-10 w-10 place-items-center rounded-lg bg-muted">{theme === "dark" ? <Moon className="h-4 w-4 text-primary" /> : <Sun className="h-4 w-4 text-amber-500" />}</div><div className="flex-1"><p className="text-xs font-medium">当前：{theme === "dark" ? "专业暗色" : "清晰亮色"}</p><p className="mt-1 text-[10px] text-muted-foreground">主题偏好只保存在本机浏览器</p></div><Button variant="outline" onClick={toggleTheme}>切换主题</Button></CardContent></Card>
        <Card className="border-teal-500/20 bg-teal-500/[.035] shadow-none"><CardHeader><div><p className="data-label">SECURITY BASELINE</p><h2 className="mt-1 text-sm font-semibold">默认安全边界</h2></div><Badge tone="success">enforced</Badge></CardHeader><CardContent className="grid grid-cols-2 gap-2">{["严格 CORS", "JWT 过期", "Scope Guard", "日志脱敏"].map((item) => <div key={item} className="flex items-center gap-2 rounded-lg border bg-background/35 px-3 py-2 text-xs"><ShieldCheck className="h-3.5 w-3.5 text-primary" />{item}</div>)}</CardContent></Card>
      </div>
      <Card className="overflow-hidden shadow-none">{query.isLoading ? <LoadingState label="正在读取系统配置…" /> : query.error ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : <DataTable data={query.data?.items || []} columns={columns} rowKey={(row) => row.id} searchPlaceholder="搜索设置键或说明…" filters={[{ label: "敏感设置", value: "secret", matches: (row) => row.is_secret === true }, { label: "标准设置", value: "standard", matches: (row) => !row.is_secret }]} emptyTitle="暂无系统设置" emptyDescription="平台可使用内置安全默认值；管理员写入的设置会显示在这里。" />}</Card>
      <Dialog open={Boolean(selected)} onOpenChange={(value) => !value && setSelected(null)}><DialogContent>{selected ? <><DialogHeader><DialogTitle>编辑 {selected.key}</DialogTitle><DialogDescription>{selected.is_secret ? "此设置为敏感值；服务端返回的是掩码，保存会覆盖原值。" : "设置值必须是 JSON 对象，保存后会生成审计日志。"}</DialogDescription></DialogHeader><form className="space-y-4" onSubmit={save}><div><Label htmlFor="setting-value">JSON 值</Label><Textarea id="setting-value" className="min-h-48 font-mono text-xs" value={json} onChange={(event) => setJson(event.target.value)} spellCheck={false} /><FieldError>{parseError}</FieldError></div><div><Label htmlFor="setting-description">说明</Label><Textarea id="setting-description" value={description} onChange={(event) => setDescription(event.target.value)} /></div>{update.error ? <p className="rounded-lg bg-red-500/10 p-3 text-xs text-red-400">{update.error.message}</p> : null}<DialogFooter><Button type="button" variant="outline" onClick={() => setSelected(null)}>取消</Button><Button type="submit" loading={update.isPending}><Save className="h-4 w-4" />保存设置</Button></DialogFooter></form></> : null}</DialogContent></Dialog>
    </div>
  );
}
