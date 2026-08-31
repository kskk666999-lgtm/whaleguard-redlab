"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, Eye, EyeOff, KeyRound, LockKeyhole, ShieldCheck, Waves } from "lucide-react";
import { Brand } from "@/components/layout/brand";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { login } from "@/lib/api";
import { saveSession } from "@/lib/auth";
import { loginInputSchema } from "@/lib/schemas";
import { safeInternalPath } from "@/lib/navigation";
import { useApp } from "@/components/providers";

function LoginPageContent() {
  const router = useRouter();
  const params = useSearchParams();
  const { syncPreferences, toast } = useApp();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const mutation = useMutation({
    mutationFn: () => login(username, password),
    onSuccess: async (result) => {
      saveSession(result.access_token, result.csrf_token, {
        id: result.user.id,
        username: result.user.username,
        display_name: result.user.display_name,
        role: result.user.role,
      });
      let onboardingComplete = false;
      try {
        const preferences = await syncPreferences();
        onboardingComplete = Boolean(preferences?.onboarding_complete);
      } catch {
        toast({
          title: "登录成功，但体验设置暂未同步",
          description: "请在引导页重试；不会影响本地安全数据。",
          tone: "info",
        });
        router.replace("/onboarding");
        return;
      }
      toast({ title: "登录成功", description: "已建立受保护的本地会话。", tone: "success" });
      const next = params.get("next");
      const safeNext = safeInternalPath(next);
      router.replace(onboardingComplete ? safeNext : "/onboarding");
    },
  });

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const parsed = loginInputSchema.safeParse({ username, password });
    if (!parsed.success) {
      const nextErrors: Record<string, string> = {};
      parsed.error.issues.forEach((issue) => { nextErrors[String(issue.path[0])] = issue.message; });
      setErrors(nextErrors);
      return;
    }
    setErrors({});
    mutation.mutate();
  };

  return (
    <main className="security-grid relative grid min-h-screen overflow-hidden lg:grid-cols-[1.08fr_.92fr]">
      <section className="relative hidden border-r bg-slate-950 px-12 py-10 text-slate-100 lg:flex lg:flex-col">
        <div className="absolute inset-0 opacity-80 [background:radial-gradient(circle_at_24%_18%,rgba(20,184,166,.16),transparent_32%),radial-gradient(circle_at_80%_78%,rgba(14,165,233,.10),transparent_34%)]" />
        <Brand className="relative" />
        <div className="relative my-auto max-w-2xl">
          <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-teal-400/20 bg-teal-400/5 px-3 py-1.5 text-[11px] uppercase tracking-[.14em] text-teal-300"><span className="status-dot" />Local-first Security Workspace</div>
          <h1 className="max-w-xl text-5xl font-semibold leading-[1.08] tracking-[-.045em]">让每一次 AI 安全判断，都有边界、有证据、可复核。</h1>
          <p className="mt-6 max-w-xl text-base leading-8 text-slate-400">面向本地实验、自有系统和明确授权目标的 AI 红队工作台。模型、Agent、MCP 工具与策略证据统一留痕。</p>
          <div className="mt-10 grid max-w-2xl grid-cols-3 gap-3">
            {[{ icon: ShieldCheck, value: "Scope", label: "强制范围守卫" }, { icon: Waves, value: "Trace", label: "全链路证据" }, { icon: CheckCircle2, value: "Policy", label: "审批式高风险动作" }].map((item) => <div key={item.value} className="rounded-xl border border-white/10 bg-white/[.035] p-4"><item.icon className="mb-4 h-5 w-5 text-teal-300" /><p className="font-mono text-sm font-semibold text-slate-100">{item.value}</p><p className="mt-1 text-[11px] text-slate-500">{item.label}</p></div>)}
          </div>
        </div>
        <p className="relative text-[11px] text-slate-600">WhaleGuard AI RedLab · 仅限合法授权安全评估</p>
      </section>
      <section className="flex min-h-screen items-center justify-center px-5 py-12 sm:px-10">
        <div className="w-full max-w-md animate-fade-up">
          <Brand className="mb-12 lg:hidden" />
          <div className="mb-8">
            <p className="data-label mb-3 text-primary">SECURE ACCESS / 安全访问</p>
            <h2 className="text-3xl font-semibold tracking-[-.04em]">登录鲸盾工作区</h2>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">初始管理员密码随机生成，请从后端首次运行凭据文件获取；不会使用固定弱口令。</p>
          </div>
          <form onSubmit={submit} className="space-y-5" noValidate>
            <div><Label htmlFor="username">用户名</Label><div className="relative"><KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input id="username" name="username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} className="h-11 pl-10" aria-invalid={Boolean(errors.username)} /></div>{errors.username ? <p className="mt-1.5 text-xs text-red-400">{errors.username}</p> : null}</div>
            <div><Label htmlFor="password">密码</Label><div className="relative"><LockKeyhole className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input id="password" name="password" type={showPassword ? "text" : "password"} autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="输入首次运行凭据中的随机密码" className="h-11 px-10" aria-invalid={Boolean(errors.password)} /><button type="button" className="focus-ring absolute right-3 top-1/2 -translate-y-1/2 rounded text-muted-foreground hover:text-foreground" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "隐藏密码" : "显示密码"}>{showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</button></div>{errors.password ? <p className="mt-1.5 text-xs text-red-400">{errors.password}</p> : null}</div>
            {mutation.error ? <div role="alert" className="rounded-lg border border-red-500/25 bg-red-500/10 px-3 py-2.5 text-xs leading-5 text-red-500 dark:text-red-300">{mutation.error.message}</div> : null}
            <Button type="submit" size="lg" loading={mutation.isPending} className="w-full">进入安全工作区<ArrowRight className="h-4 w-4" /></Button>
          </form>
          <div className="mt-8 flex items-start gap-3 rounded-xl border bg-muted/45 p-4"><LockKeyhole className="mt-0.5 h-4 w-4 shrink-0 text-primary" /><p className="text-xs leading-5 text-muted-foreground">API 默认仅绑定 <span className="font-mono text-foreground">127.0.0.1</span>。请勿将登录凭据或 API Key 写入仓库。</p></div>
        </div>
      </section>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<main className="security-grid min-h-screen" aria-label="正在加载登录页面" />}>
      <LoginPageContent />
    </Suspense>
  );
}
