"use client";

import { useState } from "react";
import { BookOpen, CheckCircle2, Clock3, Lightbulb, Network } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { AcademyMicroCourse } from "@/lib/types";
import { cn } from "@/lib/utils";

function MicroCourse({ course }: { course: AcademyMicroCourse }) {
  const [answer, setAnswer] = useState<number>();
  const answered = answer !== undefined;
  const correct = answer === course.interactive_example.answer_index;
  return (
    <details className="group rounded-xl border bg-background/55 p-4" data-testid={`micro-course-${course.id}`}>
      <summary className="flex cursor-pointer list-none items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary/10 font-mono text-[11px] font-bold text-primary">
            {course.id}
          </span>
          <div>
            <h3 className="text-sm font-semibold">{course.title}</h3>
            <p className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
              <Clock3 className="h-3 w-3" />{course.minutes} 分钟 · 不计分，可随时复习
            </p>
          </div>
        </div>
        <Badge tone="info">展开</Badge>
      </summary>
      <div className="mt-4 space-y-4 border-t pt-4">
        <p className="text-xs leading-6">{course.plain_explanation}</p>
        <div className="rounded-lg border border-sky-500/20 bg-sky-500/[.05] p-3">
          <p className="flex items-center gap-2 text-[11px] font-semibold text-sky-500"><Lightbulb className="h-3.5 w-3.5" />生活类比</p>
          <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{course.analogy}</p>
        </div>
        <div aria-label={`${course.title} 简图`} className="flex flex-wrap items-center gap-2 rounded-lg bg-muted/35 p-3">
          {course.diagram.nodes.map((node, index) => (
            <div key={`${node}-${index}`} className="contents">
              <span className="rounded-md border bg-background px-2 py-1.5 text-[11px]">{node}</span>
              {index < course.diagram.nodes.length - 1 ? <span className="text-primary">→</span> : null}
            </div>
          ))}
        </div>
        <div>
          <p className="text-xs font-semibold">试一试：{course.interactive_example.prompt}</p>
          <div className="mt-2 grid gap-2">
            {course.interactive_example.choices.map((choice, index) => (
              <Button
                key={choice}
                type="button"
                size="sm"
                variant="outline"
                className={cn("h-auto justify-start whitespace-normal py-2 text-left", answer === index && "border-primary bg-primary/[.06]")}
                onClick={() => setAnswer(index)}
              >
                {choice}
              </Button>
            ))}
          </div>
          {answered ? (
            <p className={cn("mt-3 rounded-lg p-3 text-[11px] leading-5", correct ? "bg-emerald-500/10 text-emerald-500" : "bg-amber-500/10 text-amber-500")} role="status">
              {correct ? "答对了。" : "再想一下。"} {course.interactive_example.explanation}
            </p>
          ) : null}
        </div>
      </div>
    </details>
  );
}

export function AcademyMicroCourses({ courses }: { courses: AcademyMicroCourse[] }) {
  return (
    <Card className="shadow-none" data-testid="academy-micro-courses">
      <CardHeader>
        <div>
          <p className="data-label">0 · BEFORE YOU START</p>
          <h2 className="mt-1 text-base font-semibold">开始之前：零基础微课程</h2>
          <p className="mt-1 text-xs text-muted-foreground">每节 3～5 分钟，用人话、类比和一个小问题讲清关键概念。</p>
        </div>
        <BookOpen className="h-5 w-5 text-primary" />
      </CardHeader>
      <CardContent>
        {courses.length ? <div className="grid gap-3 lg:grid-cols-2">{courses.map((course) => <MicroCourse key={course.id} course={course} />)}</div> : (
          <div className="rounded-xl border border-dashed p-6 text-center text-xs text-muted-foreground">
            <Network className="mx-auto mb-2 h-5 w-5" />微课程暂时无法读取；17 个本地实验仍可正常使用。
          </div>
        )}
        <p className="mt-4 flex items-center gap-2 text-[11px] text-muted-foreground"><CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />这些内容完全本地展示，不需要 API Key。</p>
      </CardContent>
    </Card>
  );
}
