import Link from "next/link";
import { BookOpenCheck, FileCheck2, Globe2, HelpCircle, ShieldCheck } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

const guides = [
  {
    title: "先在安全学院练习",
    description: "使用本地虚构数据和确定性事件规则，不需要 API Key，不会扫描公网。",
    href: "/academy",
    action: "进入安全学院",
    network: "仅本地请求",
    icon: BookOpenCheck,
  },
  {
    title: "检查我自己的网站",
    description: "只发出受 Scope Guard 约束的低风险只读请求；开始前必须确认所有权或授权。",
    href: "/website-scan",
    action: "进入网站体检",
    network: "会向已授权目标发请求",
    icon: Globe2,
  },
  {
    title: "查看结果和报告",
    description: "Findings 保存需要处理的问题，报告中心提供 HTML、Markdown 和 JSON 导出。",
    href: "/reports",
    action: "查看报告",
    network: "只读取本地平台数据",
    icon: FileCheck2,
  },
];

const glossary = [
  ["Prompt", "你发给 AI 的问题或指令。"],
  ["Token", "模型读取和生成文字时使用的小片段，也是常见的用量单位。"],
  ["RAG", "先从知识库找资料，再让模型结合资料回答。"],
  ["Embedding", "把文字转换成便于计算相似度的数字表示。"],
  ["Vector", "Embedding 形成的一串数字，用于查找意思相近的内容。"],
  ["Agent", "能够规划步骤并按规则调用工具完成任务的 AI 程序。"],
  ["Tool", "Agent 可以调用的一项受限能力，例如查询天气或读取演示文档。"],
  ["MCP", "让 AI 应用用统一方式发现和调用工具的协议。"],
  ["Scope", "明确允许测试的目标和范围；范围外的请求会被拒绝。"],
  ["Finding", "一次检查发现的、需要确认或修复的安全问题。"],
  ["Evidence", "证明安全问题确实发生过的请求、响应或系统事件。"],
  ["Payload", "为了验证某个安全行为而提交的测试内容；WhaleGuard 只使用安全样例。"],
  ["Request", "客户端发给网站或服务的一次请求。"],
  ["Response", "网站或服务对请求返回的结果。"],
  ["SSE", "服务器持续把运行进度推送到页面的一种方式。"],
  ["RBAC", "按角色分配权限，例如管理员、工程师、审核员和只读用户。"],
] as const;

export default function HelpPage() {
  return (
    <div>
      <PageHeader
        eyebrow="BEGINNER HELP"
        title="从这里开始"
        description="WhaleGuard 用于本地、自有系统和明确授权目标。下面每个入口都会说明是否会产生网络请求。"
        actions={<Button asChild variant="outline"><Link href="/onboarding"><HelpCircle className="h-4 w-4" />重新打开新手引导</Link></Button>}
      />
      <div className="grid gap-4 lg:grid-cols-3">
        {guides.map((guide) => (
          <Card key={guide.href} className="shadow-none">
            <CardHeader><guide.icon className="h-5 w-5 text-primary" /><Badge tone={guide.href === "/website-scan" ? "warning" : "success"}>{guide.network}</Badge></CardHeader>
            <CardContent>
              <h2 className="text-base font-semibold">{guide.title}</h2>
              <p className="mt-2 min-h-16 text-xs leading-6 text-muted-foreground">{guide.description}</p>
              <Button asChild className="mt-5 w-full" variant="outline"><Link href={guide.href}>{guide.action}</Link></Button>
            </CardContent>
          </Card>
        ))}
      </div>
      <Card className="mt-5 border-emerald-500/25 bg-emerald-500/[.04] shadow-none">
        <CardContent className="flex items-start gap-3 p-5">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-emerald-400" />
          <div><p className="text-sm font-semibold">安全边界不会因新手模式而改变</p><p className="mt-1 text-xs leading-6 text-muted-foreground">Scope Guard、授权确认、凭据加密、只读检查和审计日志始终生效。切换到高级模式只会显示更多入口，不会放宽权限。</p></div>
        </CardContent>
      </Card>
      <section className="mt-8" aria-labelledby="glossary-title">
        <p className="data-label text-primary">PLAIN LANGUAGE</p>
        <h2 id="glossary-title" className="mt-1 text-xl font-semibold">常见术语，用人话解释</h2>
        <p className="mt-1 text-xs text-muted-foreground">不需要先背下来；遇到陌生词时回这里看一眼就够了。</p>
        <dl className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {glossary.map(([term, explanation]) => (
            <div key={term} className="rounded-xl border bg-card/60 p-4">
              <dt className="text-sm font-semibold text-primary">{term}</dt>
              <dd className="mt-2 text-xs leading-5 text-muted-foreground">{explanation}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
