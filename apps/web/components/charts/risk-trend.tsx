"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import type { EChartsOption } from "echarts";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

export function RiskTrend() {
  const option = useMemo<EChartsOption>(() => ({
    animationDuration: 650,
    grid: { top: 18, right: 12, bottom: 28, left: 34 },
    tooltip: { trigger: "axis", backgroundColor: "#111827", borderColor: "#334155", textStyle: { color: "#e2e8f0", fontSize: 11 } },
    legend: { data: ["安全得分", "策略拦截"], right: 0, top: 0, textStyle: { color: "#94a3b8", fontSize: 10 } },
    xAxis: { type: "category", boundaryGap: false, data: ["08-24", "08-25", "08-26", "08-27", "08-28", "08-29", "08-30"], axisLine: { lineStyle: { color: "rgba(100,116,139,.25)" } }, axisTick: { show: false }, axisLabel: { color: "#64748b", fontSize: 10 } },
    yAxis: [{ type: "value", min: 0, max: 100, splitLine: { lineStyle: { color: "rgba(100,116,139,.12)" } }, axisLabel: { color: "#64748b", fontSize: 10 } }, { type: "value", min: 0, max: 16, show: false }],
    series: [
      { name: "安全得分", type: "line", smooth: true, symbol: "circle", symbolSize: 5, data: [71, 74, 73, 77, 81, 80, 84], lineStyle: { width: 2, color: "#2dd4bf" }, itemStyle: { color: "#2dd4bf" }, areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "rgba(45,212,191,.20)" }, { offset: 1, color: "rgba(45,212,191,0)" }] } } },
      { name: "策略拦截", type: "bar", yAxisIndex: 1, barWidth: 7, data: [3, 6, 5, 9, 7, 12, 8], itemStyle: { color: "rgba(56,189,248,.45)", borderRadius: [3, 3, 0, 0] } },
    ],
  }), []);
  return <ReactECharts option={option} style={{ height: 250, width: "100%" }} opts={{ renderer: "svg" }} />;
}
