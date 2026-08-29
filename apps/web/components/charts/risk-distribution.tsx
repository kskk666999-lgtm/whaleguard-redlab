"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import type { EChartsOption } from "echarts";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

export function RiskDistribution({ values = [1, 3, 6, 9] }: { values?: number[] }) {
  const option = useMemo<EChartsOption>(() => ({
    animationDuration: 650,
    tooltip: { trigger: "item", backgroundColor: "#111827", borderColor: "#334155", textStyle: { color: "#e2e8f0", fontSize: 11 } },
    legend: { bottom: 0, left: "center", textStyle: { color: "#94a3b8", fontSize: 10 }, itemWidth: 8, itemHeight: 8 },
    series: [{ type: "pie", radius: ["53%", "75%"], center: ["50%", "43%"], avoidLabelOverlap: true, itemStyle: { borderColor: "rgba(15,23,42,.6)", borderWidth: 2, borderRadius: 4 }, label: { show: false }, data: [
      { value: values[0] ?? 0, name: "严重", itemStyle: { color: "#ef4444" } },
      { value: values[1] ?? 0, name: "高危", itemStyle: { color: "#f97316" } },
      { value: values[2] ?? 0, name: "中危", itemStyle: { color: "#f59e0b" } },
      { value: values[3] ?? 0, name: "低危", itemStyle: { color: "#38bdf8" } },
    ], emphasis: { scaleSize: 5 } }],
    graphic: [{ type: "text", left: "center", top: "34%", style: { text: String(values.reduce((sum, value) => sum + value, 0)), fill: "#e2e8f0", font: "600 26px monospace", textAlign: "center" } }, { type: "text", left: "center", top: "49%", style: { text: "FINDINGS", fill: "#64748b", font: "10px sans-serif", textAlign: "center" } }],
  }), [values]);
  return <ReactECharts option={option} style={{ height: 235, width: "100%" }} opts={{ renderer: "svg" }} />;
}
