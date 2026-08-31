import { ArrowRight, ShieldCheck, ShieldOff } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { AcademyComparison, AcademyComparisonSide } from "@/lib/types";

const rows: Array<[keyof Pick<AcademyComparisonSide, "model_decision" | "tool_call" | "policy_decision" | "output">, string]> = [
  ["model_decision", "模型 / Agent 决定"],
  ["tool_call", "Tool Call"],
  ["policy_decision", "Policy Decision"],
  ["output", "Output"],
];

function Side({ side, hardened }: { side: AcademyComparisonSide; hardened: boolean }) {
  const Icon = hardened ? ShieldCheck : ShieldOff;
  return (
    <article className={hardened ? "rounded-xl border border-emerald-500/30 bg-emerald-500/[.04] p-4" : "rounded-xl border border-red-500/30 bg-red-500/[.04] p-4"}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold"><Icon className={hardened ? "h-4 w-4 text-emerald-500" : "h-4 w-4 text-red-500"} />{hardened ? "Hardened 修复版" : "Vulnerable 漏洞版"}</h3>
        <Badge tone={hardened ? "success" : "danger"}>{side.result}</Badge>
      </div>
      <dl className="mt-4 space-y-3 text-[11px]">
        <div><dt className="font-semibold">Input</dt><dd className="mt-1 whitespace-pre-wrap rounded-lg bg-background/55 p-2 text-muted-foreground">{side.input.payload}</dd></div>
        {rows.map(([key, label]) => (
          <div key={key}>
            <dt className="font-semibold">{label}</dt>
            <dd className="mt-1 space-y-1 text-muted-foreground">
              {side[key].length ? side[key].map((item) => <p key={item}>• {item}</p>) : <p>未发生</p>}
            </dd>
          </div>
        ))}
        <div><dt className="font-semibold">Evidence / Finding</dt><dd className="mt-1 text-muted-foreground">Evidence：{side.evidence.created ? "已保存" : "未生成"} · Finding：{side.finding.created ? "已生成" : "未生成"}</dd></div>
      </dl>
    </article>
  );
}

export function AcademyScenarioComparison({ comparison }: { comparison: AcademyComparison }) {
  if (!comparison.ready || !comparison.vulnerable || !comparison.hardened) {
    return (
      <div className="rounded-xl border border-dashed p-6 text-center text-xs leading-5 text-muted-foreground" data-testid="academy-comparison-pending">
        还缺少 {comparison.missing_mode === "vulnerable" ? "Vulnerable 漏洞版" : "Hardened 修复版"}结果。完成同一 Payload 回放后，这里会自动生成真实左右对照。
      </div>
    );
  }
  return (
    <section data-testid="academy-vulnerable-hardened-comparison" aria-labelledby="comparison-heading">
      <h3 id="comparison-heading" className="sr-only">Vulnerable 与 Hardened 对照</h3>
      <div className="grid gap-3 lg:grid-cols-[1fr_auto_1fr] lg:items-start">
        <Side side={comparison.vulnerable} hardened={false} />
        <ArrowRight className="mx-auto h-5 w-5 rotate-90 text-primary lg:mt-8 lg:rotate-0" />
        <Side side={comparison.hardened} hardened />
      </div>
      <div className="mt-4 rounded-xl border bg-muted/25 p-4">
        <p className="text-xs font-semibold">真正发生变化的安全控制</p>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {comparison.control_changes.map((change) => (
            <div key={change.control} className="rounded-lg border bg-background/60 p-3 text-[11px] leading-5">
              <p className="font-mono font-semibold text-primary">{change.control}</p>
              <p className="mt-1 text-muted-foreground">{String(change.vulnerable)} → {String(change.hardened)}</p>
              <p className="mt-1 text-muted-foreground">{change.explanation}</p>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs font-semibold text-emerald-500">{comparison.conclusion}</p>
      </div>
    </section>
  );
}
