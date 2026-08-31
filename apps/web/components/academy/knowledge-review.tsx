"use client";

import { useMemo, useState } from "react";
import { Brain, CheckCircle2, RotateCcw, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { AcademyScenario } from "@/lib/types";
import { cn } from "@/lib/utils";

type ReviewQuestion = {
  prompt: string;
  choices: string[];
  answerIndex: number;
  explanation: string;
};

export function AcademyKnowledgeReview({ scenario }: { scenario: AcademyScenario }) {
  const questions = useMemo<ReviewQuestion[]>(() => [
    {
      prompt: "哪一种证据最能证明这关的攻击链真的发生了？",
      choices: ["模型说‘我被攻击了’", "服务器保存的连续事件链", "页面上出现一个静态 Flag"],
      answerIndex: 1,
      explanation: `正确。WhaleGuard 会按 ${scenario.expected_evidence.event_types.join("、")} 等事件进行确定性判定。`,
    },
    {
      prompt: "Hardened 版本的正确目标是什么？",
      choices: ["隐藏日志", "让输出看起来更礼貌", "在危险动作产生副作用前阻断并留下证据"],
      answerIndex: 2,
      explanation: "正确。防护既要切断攻击链，也要保留可审计的 policy/guard 事件。",
    },
    {
      prompt: "Academy 练习允许把什么数据放进测试输入？",
      choices: ["本地虚构数据", "真实 API Key", "他人的个人信息"],
      answerIndex: 0,
      explanation: "正确。课程只使用本地虚构数据；真实凭证、个人信息和未授权目标都不应进入靶场。",
    },
  ], [scenario.expected_evidence.event_types]);
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const answeredCount = Object.keys(answers).length;
  const score = questions.reduce((total, question, index) => total + (answers[index] === question.answerIndex ? 1 : 0), 0);

  return (
    <section data-testid="academy-knowledge-review" className="rounded-xl border bg-muted/20 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2"><Brain className="h-4 w-4 text-primary" /><h3 className="text-sm font-semibold">3 题知识回顾</h3></div>
        <Badge tone={answeredCount === questions.length && score === questions.length ? "success" : "neutral"}>{score}/{questions.length}</Badge>
      </div>
      <p className="mt-1 text-[11px] text-muted-foreground">不计入关卡得分，用来确认你理解了“为什么”。</p>

      <div className="mt-4 space-y-4">
        {questions.map((question, questionIndex) => {
          const selected = answers[questionIndex];
          const answered = selected !== undefined;
          const correct = selected === question.answerIndex;
          return (
            <fieldset key={question.prompt} className="rounded-lg border bg-background/60 p-4">
              <legend className="px-1 text-xs font-semibold">{questionIndex + 1}. {question.prompt}</legend>
              <div className="mt-2 grid gap-2 sm:grid-cols-3">
                {question.choices.map((choice, choiceIndex) => (
                  <button
                    key={choice}
                    type="button"
                    disabled={answered}
                    onClick={() => setAnswers((current) => ({ ...current, [questionIndex]: choiceIndex }))}
                    className={cn(
                      "rounded-lg border px-3 py-2 text-left text-[11px] leading-5 transition-colors disabled:cursor-default",
                      !answered && "hover:border-primary/40 hover:bg-primary/[.04]",
                      answered && choiceIndex === question.answerIndex && "border-emerald-500/35 bg-emerald-500/[.07]",
                      answered && choiceIndex === selected && !correct && "border-red-500/35 bg-red-500/[.07]",
                    )}
                  >{choice}</button>
                ))}
              </div>
              {answered ? (
                <p aria-live="polite" className={cn("mt-3 flex gap-2 text-[11px] leading-5", correct ? "text-emerald-500" : "text-amber-500")}>
                  {correct ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
                  {correct ? question.explanation : `还差一点。${question.explanation}`}
                </p>
              ) : null}
            </fieldset>
          );
        })}
      </div>

      {answeredCount === questions.length ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-primary/20 bg-primary/[.04] p-3">
          <p className="text-xs font-medium">{score === questions.length ? "全部答对，可以继续下一关。" : `答对 ${score} 题；可以重做一次再继续。`}</p>
          <Button type="button" size="sm" variant="outline" onClick={() => setAnswers({})}><RotateCcw className="h-3.5 w-3.5" />重新回顾</Button>
        </div>
      ) : null}
    </section>
  );
}
