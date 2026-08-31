"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  BookOpenCheck,
  CheckCircle2,
  Globe2,
  RefreshCw,
  ScanSearch,
  Settings2,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { Brand } from "@/components/layout/brand";
import { useApp } from "@/components/providers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { getSystemStatus } from "@/lib/api";
import { getToken } from "@/lib/auth";
import type { OnboardingGoal, SystemServiceStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const steps = ["选择目标", "检查系统", "选择模型", "开始使用"];

const goals: Array<{
  id: OnboardingGoal;
  title: string;
  description: string;
  icon: typeof BookOpenCheck;
}> = [
  {
    id: "learn",
    title: "我想学习 AI 安全",
    description: "从本地安全学院开始，不需要 API Key，也不会访问公网。",
    icon: BookOpenCheck,
  },
  {
    id: "scan",
    title: "我想检查自己的网站",
    description: "进入只读网站体检，目标必须归你所有或已明确授权。",
    icon: ScanSearch,
  },
  {
    id: "both",
    title: "两种都想体验",
    description: "先回到新手首页，再按自己的节奏选择学习或体检。",
    icon: Sparkles,
  },
];

function serviceTone(status: SystemServiceStatus["status"]) {
  if (status === "normal") return "success" as const;
  if (status === "abnormal") return "danger" as const;
  if (status === "optional") return "info" as const;
  return "warning" as const;
}

function goalDestination(goal: OnboardingGoal) {
  if (goal === "learn") return "/academy";
  if (goal === "scan") return "/website-scan";
  return "/dashboard";
}

export default function OnboardingPage() {
  const router = useRouter();
  const {
    preferences,
    preferencesError,
    preferencesReady,
    syncPreferences,
    toast,
    updatePreferences,
  } = useApp();
  const [authenticated, setAuthenticated] = useState(false);
  const [step, setStep] = useState(0);
  const [goal, setGoal] = useState<OnboardingGoal | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login?next=%2Fonboarding");
      return;
    }
    setAuthenticated(true);
  }, [router]);

  useEffect(() => {
    if (preferences?.onboarding_goal) setGoal(preferences.onboarding_goal);
  }, [preferences]);

  const systemStatus = useQuery({
    queryKey: ["system-status", "onboarding"],
    queryFn: getSystemStatus,
    enabled: authenticated,
    retry: 1,
  });

  if (!authenticated || !preferencesReady) {
    return <LoadingState className="min-h-screen" label="正在准备新手引导…" />;
  }
  if (preferencesError && !preferences) {
    return (
      <main className="grid min-h-screen place-items-center px-5">
        <Card className="w-full max-w-xl">
          <ErrorState error={new Error(preferencesError)} onRetry={() => void syncPreferences()} />
        </Card>
      </main>
    );
  }

  const finish = async () => {
    if (!goal) return;
    setSaving(true);
    try {
      await updatePreferences({
        experience_mode: "beginner",
        onboarding_complete: true,
        onboarding_goal: goal,
      });
      toast({
        title: "新手设置已保存",
        description: "以后可以在右上角随时切换新手模式和高级模式。",
        tone: "success",
      });
      router.replace(goalDestination(goal));
    } catch (error) {
      toast({
        title: "暂时无法保存设置",
        description: error instanceof Error ? error.message : "请稍后重试",
        tone: "error",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="security-grid min-h-screen px-4 py-6 sm:px-8 lg:py-10">
      <div className="mx-auto w-full max-w-5xl">
        <div className="mb-8 flex items-center justify-between gap-4">
          <Brand />
          <Badge tone="info">新手引导 · {step + 1}/{steps.length}</Badge>
        </div>

        <ol className="mb-6 grid grid-cols-4 gap-2" aria-label="新手引导进度">
          {steps.map((label, index) => (
            <li key={label}>
              <div className={cn("h-1.5 rounded-full", index <= step ? "bg-primary" : "bg-muted")} />
              <p className={cn("mt-2 text-[11px]", index <= step ? "text-foreground" : "text-muted-foreground")}>{label}</p>
            </li>
          ))}
        </ol>

        <Card className="overflow-hidden shadow-panel">
          {step === 0 ? (
            <>
              <CardHeader>
                <div>
                  <p className="data-label text-primary">STEP 1 / 你的目标</p>
                  <h1 className="mt-2 text-2xl font-semibold">你今天最想先完成什么？</h1>
                  <p className="mt-2 text-sm text-muted-foreground">这只影响首页和导航的简洁程度，不会删除任何高级功能。</p>
                </div>
              </CardHeader>
              <CardContent className="grid gap-3 md:grid-cols-3">
                {goals.map((item) => {
                  const Icon = item.icon;
                  const selected = goal === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      className={cn(
                        "focus-ring rounded-xl border p-5 text-left transition-colors hover:bg-muted/55",
                        selected && "border-primary bg-primary/5",
                      )}
                      onClick={() => setGoal(item.id)}
                      aria-pressed={selected}
                    >
                      <Icon className="h-6 w-6 text-primary" />
                      <p className="mt-5 text-sm font-semibold">{item.title}</p>
                      <p className="mt-2 text-xs leading-5 text-muted-foreground">{item.description}</p>
                      {selected ? <p className="mt-4 flex items-center gap-1.5 text-xs text-primary"><CheckCircle2 className="h-4 w-4" />已选择</p> : null}
                    </button>
                  );
                })}
              </CardContent>
            </>
          ) : null}

          {step === 1 ? (
            <>
              <CardHeader>
                <div>
                  <p className="data-label text-primary">STEP 2 / 系统检查</p>
                  <h1 className="mt-2 text-2xl font-semibold">确认本地服务是否准备好</h1>
                  <p className="mt-2 text-sm text-muted-foreground">以下内容来自真实的系统状态接口，不是演示数据。</p>
                </div>
                <Button variant="outline" size="sm" loading={systemStatus.isFetching} onClick={() => void systemStatus.refetch()}><RefreshCw className="h-3.5 w-3.5" />重新检测</Button>
              </CardHeader>
              <CardContent>
                {systemStatus.isLoading ? <LoadingState label="正在检测 API、数据库和本地靶场…" /> : systemStatus.error ? <ErrorState error={systemStatus.error} onRetry={() => void systemStatus.refetch()} /> : (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {Object.entries(systemStatus.data?.services || {}).map(([key, service]) => (
                      <div key={key} className="flex items-start gap-3 rounded-xl border bg-muted/25 p-4">
                        <ShieldCheck className={cn("mt-0.5 h-4 w-4", service.status === "normal" ? "text-emerald-400" : "text-amber-400")} />
                        <div className="min-w-0 flex-1"><p className="text-sm font-medium">{service.label}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">{service.detail}</p></div>
                        <Badge tone={serviceTone(service.status)}>{service.status === "normal" ? "正常" : service.status === "optional" ? "可选" : service.status === "not_started" ? "未启动" : "异常"}</Badge>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </>
          ) : null}

          {step === 2 ? (
            <>
              <CardHeader>
                <div>
                  <p className="data-label text-primary">STEP 3 / AI 模型</p>
                  <h1 className="mt-2 text-2xl font-semibold">API Key 是可选的</h1>
                  <p className="mt-2 text-sm text-muted-foreground">安全学院和本地规则检查不依赖外部模型；只有需要 AI 解读时才会使用你的模型渠道。</p>
                </div>
              </CardHeader>
              <CardContent>
                <div className="rounded-xl border bg-muted/25 p-5">
                  <div className="flex flex-wrap items-center gap-3">
                    <Globe2 className="h-5 w-5 text-primary" />
                    <p className="text-sm font-semibold">当前模型状态</p>
                    {systemStatus.data?.services.model_provider ? <Badge tone={serviceTone(systemStatus.data.services.model_provider.status)}>{systemStatus.data.services.model_provider.status === "normal" ? "已连接" : "可稍后配置"}</Badge> : null}
                  </div>
                  <p className="mt-3 text-xs leading-6 text-muted-foreground">{systemStatus.data?.services.model_provider?.detail || "尚未取得模型状态；你仍然可以跳过并继续。"}</p>
                  <div className="mt-5 flex flex-wrap gap-2">
                    <Button asChild variant="outline"><Link href="/models"><Settings2 className="h-4 w-4" />去配置模型</Link></Button>
                    <Button onClick={() => setStep(3)}>暂时跳过，继续<ArrowRight className="h-4 w-4" /></Button>
                  </div>
                </div>
              </CardContent>
            </>
          ) : null}

          {step === 3 ? (
            <>
              <CardHeader>
                <div>
                  <p className="data-label text-primary">STEP 4 / 完成</p>
                  <h1 className="mt-2 text-2xl font-semibold">设置完成，可以开始了</h1>
                  <p className="mt-2 text-sm text-muted-foreground">我们会保存你的选择，并把你带到对应的真实功能页面。</p>
                </div>
              </CardHeader>
              <CardContent>
                <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/[.05] p-5">
                  <p className="flex items-center gap-2 text-sm font-semibold"><CheckCircle2 className="h-5 w-5 text-emerald-400" />你的起点</p>
                  <p className="mt-3 text-sm text-muted-foreground">{goals.find((item) => item.id === goal)?.title}</p>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">模式和引导状态会通过账号偏好接口真实保存。</p>
                </div>
              </CardContent>
            </>
          ) : null}

          <div className="flex items-center justify-between border-t px-5 py-4">
            <Button variant="ghost" disabled={step === 0 || saving} onClick={() => setStep((current) => Math.max(0, current - 1))}><ArrowLeft className="h-4 w-4" />上一步</Button>
            {step < 2 ? <Button disabled={step === 0 && !goal} onClick={() => setStep((current) => Math.min(3, current + 1))}>下一步<ArrowRight className="h-4 w-4" /></Button> : null}
            {step === 2 ? <span className="text-xs text-muted-foreground">模型可跳过</span> : null}
            {step === 3 ? <Button loading={saving} disabled={!goal} onClick={() => void finish()}>进入 WhaleGuard<ArrowRight className="h-4 w-4" /></Button> : null}
          </div>
        </Card>
      </div>
    </main>
  );
}
