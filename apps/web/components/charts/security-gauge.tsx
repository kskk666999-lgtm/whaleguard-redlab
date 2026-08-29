"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import type { EChartsOption } from "echarts";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

export function SecurityGauge({ score = 82 }: { score?: number }) {
  const option = useMemo<EChartsOption>(() => ({
    animationDuration: 700,
    series: [{
      type: "gauge",
      startAngle: 210,
      endAngle: -30,
      min: 0,
      max: 100,
      radius: "92%",
      center: ["50%", "55%"],
      splitNumber: 5,
      axisLine: { lineStyle: { width: 10, color: [[0.6, "#ef4444"], [0.8, "#f59e0b"], [1, "#2dd4bf"]] } },
      progress: { show: true, width: 10, itemStyle: { color: score >= 80 ? "#2dd4bf" : score >= 60 ? "#f59e0b" : "#ef4444" } },
      pointer: { show: false },
      axisTick: { show: false },
      splitLine: { distance: -15, length: 4, lineStyle: { width: 1, color: "rgba(148,163,184,.35)" } },
      axisLabel: { show: false },
      anchor: { show: false },
      title: { show: true, offsetCenter: [0, "43%"], color: "#94a3b8", fontSize: 11 },
      detail: { valueAnimation: true, width: 50, height: 30, borderRadius: 8, offsetCenter: [0, "2%"], formatter: "{value}", color: "#e2e8f0", fontSize: 35, fontFamily: "monospace", fontWeight: 700 },
      data: [{ value: Math.max(0, Math.min(100, score)), name: "SECURITY SCORE" }],
    }],
  }), [score]);
  return <ReactECharts option={option} style={{ height: 218, width: "100%" }} opts={{ renderer: "svg" }} />;
}
