"use client";

import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { MessageCircleQuestion, ShieldCheck, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiRequest } from "@/lib/api";
import type {
  AcademyAttackStory,
  AcademyComparison,
  AcademyScenario,
  AcademyTutorIntent,
  AcademyTutorResponse,
} from "@/lib/types";

type TutorQuestion = {
  id: AcademyTutorIntent;
  label: string;
  answer: string;
};

export function AcademyWhaleTutor({
  scenario,
  story,
  comparison,
  projectId,
  sessionId,
}: {
  scenario: AcademyScenario;
  story?: AcademyAttackStory;
  comparison?: AcademyComparison;
  projectId: string;
  sessionId?: string;
}) {
  const questions = useMemo<TutorQuestion[]>(() => {
    const lesson = scenario.lesson || {
      goal: scenario.learning_objectives?.[0] || `理解 ${scenario.title} 的安全风险`,
      why_it_matters: scenario.story || "不可信输入可能跨过安全边界。",
    };
    const controlSummary = comparison?.control_changes
      .map((item) => item.explanation)
      .filter(Boolean)
      .slice(0, 2)
      .join("；");
    const hardenedKeys = Object.keys(scenario.hardened_config || {}).slice(0, 3).join("、");
    const evidenceTypes = scenario.expected_evidence?.event_types || [];

    return [
      {
        id: "meaning",
        label: "这关到底在学什么？",
        answer: `${lesson.goal}。${lesson.why_it_matters}`,
      },
      {
        id: "why_vulnerable",
        label: "为什么漏洞版会成功？",
        answer: story?.explanation || `本关关注“${scenario.risk_family || scenario.title}”。不要只看模型说了什么，要沿事件链确认不可信输入在哪一步改变了 Agent、工具或输出。`,
      },
      {
        id: "why_hardened",
        label: "为什么修复版能拦住？",
        answer: comparison?.conclusion || controlSummary || `修复版会在关键决策点启用 ${hardenedKeys || "最小权限、输入隔离和策略审批"}，让危险动作在产生副作用前被拒绝。`,
      },
      {
        id: "evidence",
        label: "Evidence 应该怎么看？",
        answer: `${scenario.expected_evidence?.rubric || "选择能证明输入、危险决定和结果的连续事件"}。优先找这些真实事件：${evidenceTypes.join("、") || "输入、策略与输出事件"}。模型自述和静态 Flag 都不能单独证明通关。`,
      },
      {
        id: "simplify",
        label: "再简单一点",
        answer: `一句话：先看 ${scenario.title} 的事件链哪里越界，再用修复版证明危险动作已经被拦住。`,
      },
    ];
  }, [comparison, scenario, story]);
  const [selectedId, setSelectedId] = useState(questions[0].id);
  const [response, setResponse] = useState<AcademyTutorResponse>();
  const selected = questions.find((item) => item.id === selectedId) || questions[0];
  const askTutor = useMutation({
    mutationFn: (intent: AcademyTutorIntent) => apiRequest<AcademyTutorResponse>(`/academy/scenarios/${scenario.id}/tutor`, {
      method: "POST",
      body: {
        project_id: projectId,
        intent,
        ...(sessionId ? { session_id: sessionId } : {}),
      },
    }),
    onSuccess: (result) => setResponse(result),
    onError: () => setResponse(undefined),
  });

  const selectQuestion = (intent: AcademyTutorIntent) => {
    setSelectedId(intent);
    setResponse(undefined);
    askTutor.mutate(intent);
  };

  return (
    <section data-testid="academy-whale-tutor" className="rounded-xl border border-cyan-500/20 bg-cyan-500/[.04] p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <MessageCircleQuestion className="h-4 w-4 text-cyan-500" />
            <h3 className="text-sm font-semibold">问鲸鱼导师</h3>
          </div>
          <p className="mt-1 text-[11px] leading-5 text-muted-foreground">只解释当前课程、脱敏证据和防御；已连接模型可提供增强，失败时自动回到本地解释，绝不生成攻击载荷。</p>
        </div>
        <Badge tone="info"><ShieldCheck className="mr-1 h-3 w-3" />课程边界内</Badge>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {questions.map((item) => (
          <Button
            key={item.id}
            type="button"
            size="sm"
            variant={selectedId === item.id ? "default" : "outline"}
            aria-pressed={selectedId === item.id}
            disabled={askTutor.isPending}
            onClick={() => selectQuestion(item.id)}
          >
            {item.label}
          </Button>
        ))}
      </div>

      <div aria-live="polite" className="mt-4 rounded-lg border bg-background/70 p-4">
        <p className="flex items-center gap-2 text-xs font-semibold"><Sparkles className="h-3.5 w-3.5 text-cyan-500" />{selected.label}</p>
        <p className="mt-2 text-xs leading-6 text-muted-foreground">
          {askTutor.isPending ? "正在结合当前课程与执行记录整理解释…" : response?.answer || selected.answer}
        </p>
        {response?.key_points.length ? <ul className="mt-3 space-y-1 text-[11px] leading-5 text-muted-foreground">{response.key_points.map((point) => <li key={point}>• {point}</li>)}</ul> : null}
        {response?.suggested_next_step ? <p className="mt-3 rounded-md bg-primary/[.05] px-3 py-2 text-[11px] leading-5"><span className="font-semibold text-primary">建议下一步：</span>{response.suggested_next_step}</p> : null}
        {response ? <p className="mt-3 text-[10px] text-muted-foreground">{response.used_ai ? "已使用受限模型解释" : `确定性解释${response.fallback_reason ? ` · ${response.fallback_reason}` : ""}`} · {response.session_context_used ? "已结合本次执行" : "仅使用课程内容"}</p> : null}
        {askTutor.error ? <p className="mt-3 text-[10px] text-amber-500">导师接口暂时不可用，已显示本地课程内的确定性解释。</p> : null}
      </div>
    </section>
  );
}
