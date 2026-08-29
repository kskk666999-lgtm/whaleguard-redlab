"use client";

import Link from "next/link";
import { Bot, BrainCircuit, Container, LockKeyhole, Network, Play, ShieldCheck, Wrench } from "lucide-react";
import { AttackTopology } from "@/components/charts/attack-topology";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

const services = [
  { name: "mock-llm", port: "8081 / private", icon: BrainCircuit, note: "确定性安全响应与可复现评分", capabilities: ["OpenAI Compatible", "canary-safe"] },
  { name: "mock-agent", port: "8102 / private", icon: Bot, note: "任务、知识库、工具调用与执行轨迹", capabilities: ["trace", "policy-aware"] },
  { name: "mock-mcp-server", port: "8103 / private", icon: Network, note: "5 个无破坏性模拟工具", capabilities: ["metadata", "approval"] },
];

export default function AgentArenaPage() {
  return (
    <div>
      <PageHeader eyebrow="LOCAL ATTACK / DEFENSE LAB" title="AgentArena" description="三个隔离在 Docker 私有网络中的确定性模拟服务，用于验证 Agent 目标偏离、Tool Policy 和人工审批围栏。" actions={<><Button asChild variant="outline"><Link href="/mcpshield"><Wrench className="h-4 w-4" />查看 Tool 风险</Link></Button><Button asChild><Link href="/runs"><Play className="h-4 w-4" />运行 Mock Agent 测试</Link></Button></>} />
      <div className="grid gap-4 lg:grid-cols-3">
        {services.map((service) => <Card key={service.name} className="shadow-none"><CardContent className="p-5"><div className="flex items-start justify-between"><div className="rounded-xl bg-primary/10 p-3 text-primary"><service.icon className="h-5 w-5" /></div><Badge tone="success"><span className="mr-1 status-dot" />private only</Badge></div><p className="mt-5 font-mono text-sm font-semibold">{service.name}</p><p className="mt-2 text-xs leading-5 text-muted-foreground">{service.note}</p><div className="mt-4 flex flex-wrap gap-1">{service.capabilities.map((item) => <Badge key={item}>{item}</Badge>)}</div><p className="mt-4 border-t pt-3 font-mono text-[10px] text-muted-foreground">{service.port}</p></CardContent></Card>)}
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-[1.55fr_.85fr]">
        <Card className="shadow-none"><CardHeader><div><p className="data-label">EXECUTION GRAPH</p><h2 className="mt-1 text-sm font-semibold">模拟调用与审批拓扑</h2></div><Badge tone="info"><Container className="mr-1 h-3 w-3" />internal network</Badge></CardHeader><CardContent><AttackTopology /></CardContent></Card>
        <Card className="shadow-none"><CardHeader><div><p className="data-label">MANDATORY POLICY</p><h2 className="mt-1 text-sm font-semibold">权限围栏</h2></div></CardHeader><CardContent className="space-y-3"><div className="rounded-lg border border-amber-500/25 bg-amber-500/[.06] p-4"><div className="flex items-center gap-2"><LockKeyhole className="h-4 w-4 text-amber-400" /><p className="font-mono text-xs font-semibold">request_sensitive_demo_data</p></div><p className="mt-2 text-[11px] leading-5 text-muted-foreground">默认必须拒绝或进入人工审批。模拟数据不含任何真实凭据。</p><Badge tone="warning" className="mt-3">approval_required</Badge></div>{["禁止 privileged 容器", "不映射公网监听端口", "工具仅访问内置虚构数据", "执行轨迹与策略判定可审计"].map((rule) => <div key={rule} className="flex items-center gap-2 rounded-lg border bg-muted/25 px-3 py-2.5 text-xs"><ShieldCheck className="h-3.5 w-3.5 text-primary" />{rule}</div>)}</CardContent></Card>
      </div>
      <Card className="mt-4 shadow-none"><CardHeader><div><p className="data-label">SAFE TOOL CATALOG</p><h2 className="mt-1 text-sm font-semibold">Mock MCP 工具</h2></div></CardHeader><CardContent><div className="grid gap-2 md:grid-cols-2 xl:grid-cols-5">{[
        ["read_demo_document", "读取虚构文档", "low"], ["search_demo_knowledge", "检索模拟知识库", "low"], ["create_demo_note", "创建临时演示笔记", "medium"], ["get_demo_weather", "读取固定演示天气", "low"], ["request_sensitive_demo_data", "验证审批围栏", "high"],
      ].map(([name, note, risk]) => <div key={name} className="rounded-lg border bg-muted/20 p-3"><p className="break-all font-mono text-[11px] font-semibold">{name}</p><p className="mt-2 text-[10px] leading-4 text-muted-foreground">{note}</p><Badge tone={risk === "high" ? "warning" : risk === "medium" ? "info" : "success"} className="mt-3">{risk}</Badge></div>)}</div></CardContent></Card>
    </div>
  );
}
