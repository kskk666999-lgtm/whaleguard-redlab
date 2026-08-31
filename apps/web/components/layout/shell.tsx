"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  Archive,
  Bell,
  Blocks,
  Bot,
  BrainCircuit,
  Bug,
  ChevronDown,
  CircleHelp,
  FileCheck2,
  FileSearch,
  FlaskConical,
  FolderKanban,
  Gauge,
  Globe2,
  GraduationCap,
  Home,
  Library,
  LogOut,
  Menu,
  Moon,
  Network,
  PlayCircle,
  Search,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sun,
  TerminalSquare,
  UserCircle2,
  X,
} from "lucide-react";
import { Brand } from "@/components/layout/brand";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { clearSession, getStoredUser, getToken, type SessionUser } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { useApp } from "@/components/providers";

type NavGroup = "开始" | "工作台" | "评估" | "资产" | "治理";
type NavItem = { href: string; label: string; icon: typeof Gauge; group: NavGroup };

export const navigation: NavItem[] = [
  { href: "/website-scan", label: "网站一键体检", icon: Globe2, group: "工作台" },
  { href: "/dashboard", label: "系统总览", icon: Gauge, group: "工作台" },
  { href: "/projects", label: "项目中心", icon: FolderKanban, group: "工作台" },
  { href: "/scopes", label: "授权与测试范围", icon: ShieldCheck, group: "工作台" },
  { href: "/runs", label: "测试运行中心", icon: PlayCircle, group: "工作台" },
  { href: "/test-cases", label: "AI 红队测试用例", icon: FlaskConical, group: "评估" },
  { href: "/academy", label: "Academy Range", icon: GraduationCap, group: "评估" },
  { href: "/mcpshield", label: "MCPShield", icon: Network, group: "评估" },
  { href: "/arena", label: "AgentArena", icon: Blocks, group: "评估" },
  { href: "/findings", label: "Findings", icon: Bug, group: "评估" },
  { href: "/evidence", label: "证据中心", icon: Archive, group: "评估" },
  { href: "/reports", label: "报告中心", icon: FileCheck2, group: "评估" },
  { href: "/models", label: "模型渠道", icon: BrainCircuit, group: "资产" },
  { href: "/agents", label: "Agent 管理", icon: Bot, group: "资产" },
  { href: "/tools", label: "工具与 MCP", icon: TerminalSquare, group: "资产" },
  { href: "/knowledge", label: "知识库", icon: Library, group: "资产" },
  { href: "/audit", label: "审计日志", icon: FileSearch, group: "治理" },
  { href: "/settings", label: "系统设置", icon: Settings, group: "治理" },
];

export const beginnerNavigation: NavItem[] = [
  { href: "/dashboard", label: "首页", icon: Home, group: "开始" },
  { href: "/academy", label: "安全学院", icon: GraduationCap, group: "开始" },
  { href: "/website-scan", label: "网站体检", icon: Globe2, group: "开始" },
  { href: "/findings", label: "Findings", icon: Bug, group: "开始" },
  { href: "/reports", label: "报告", icon: FileCheck2, group: "开始" },
  { href: "/help", label: "帮助", icon: CircleHelp, group: "开始" },
];

function Sidebar({ pathname, items, onNavigate }: { pathname: string; items: NavItem[]; onNavigate?: () => void }) {
  const groups = Array.from(new Set(items.map((item) => item.group)));
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-20 items-center border-b px-5"><Brand /></div>
      <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-4" aria-label="主导航">
        {groups.map((group) => (
          <div key={group}>
            <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground/70">{group}</p>
            <div className="space-y-0.5">
              {items.filter((item) => item.group === group).map((item) => {
                const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
                const Icon = item.icon;
                return (
                  <Link key={item.href} href={item.href} onClick={onNavigate} className={cn("focus-ring group flex h-9 items-center gap-3 rounded-lg px-3 text-[13px] transition-colors", active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted/75 hover:text-foreground")}>
                    <Icon className={cn("h-4 w-4 shrink-0", active && "text-primary")} />
                    <span className="truncate">{item.label}</span>
                    {active ? <span className="ml-auto h-1.5 w-1.5 rounded-full bg-primary shadow-[0_0_8px_rgba(45,212,191,.7)]" /> : null}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
      <div className="border-t p-4">
        <div className="rounded-lg border bg-muted/35 p-3">
          <div className="flex items-center gap-2 text-xs font-medium"><span className="status-dot" />Scope Guard 已启用</div>
          <p className="mt-1.5 text-[10px] leading-4 text-muted-foreground">默认阻止公网目标与未授权跳转</p>
        </div>
      </div>
    </div>
  );
}

function CommandPalette({ open, items, onOpenChange }: { open: boolean; items: NavItem[]; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const matches = items.filter((item) => item.label.toLowerCase().includes(query.toLowerCase()));
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="top-[24%] max-w-lg p-0">
        <DialogHeader className="sr-only"><DialogTitle>快速导航</DialogTitle></DialogHeader>
        <div className="flex items-center gap-3 border-b px-4"><Search className="h-4 w-4 text-muted-foreground" /><Input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索页面或功能…" className="h-14 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0" /></div>
        <div className="max-h-80 overflow-y-auto p-2">
          {matches.length ? matches.map((item) => {
            const Icon = item.icon;
            return <button key={item.href} className="focus-ring flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm hover:bg-muted" onClick={() => { router.push(item.href); onOpenChange(false); setQuery(""); }}><Icon className="h-4 w-4 text-primary" /><span>{item.label}</span><span className="ml-auto text-[10px] text-muted-foreground">{item.group}</span></button>;
          }) : <p className="px-3 py-8 text-center text-sm text-muted-foreground">没有匹配页面</p>}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function ConsoleShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const {
    experienceMode,
    preferencesLoading,
    preferencesReady,
    theme,
    toast,
    toggleTheme,
    updatePreferences,
  } = useApp();
  const [ready, setReady] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const [alertsOpen, setAlertsOpen] = useState(false);
  const [modeSaving, setModeSaving] = useState(false);
  const [user, setUser] = useState<SessionUser | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    setUser(getStoredUser());
    setReady(true);
  }, [pathname, router]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const activeNavigation = experienceMode === "beginner" ? beginnerNavigation : navigation;
  const title = useMemo(
    () => [...beginnerNavigation, ...navigation].find((item) => pathname === item.href || pathname.startsWith(item.href + "/"))?.label || "WhaleGuard",
    [pathname],
  );

  if (!ready || !preferencesReady) {
    return <div className="grid min-h-screen place-items-center bg-background"><div className="flex items-center gap-3 text-sm text-muted-foreground"><Activity className="h-4 w-4 animate-pulse text-primary" />正在建立安全会话…</div></div>;
  }

  const logout = () => { clearSession(); router.replace("/login"); };
  const switchExperienceMode = async () => {
    const nextMode = experienceMode === "beginner" ? "advanced" : "beginner";
    setModeSaving(true);
    try {
      await updatePreferences({ experience_mode: nextMode });
      toast({
        title: nextMode === "beginner" ? "已切换到新手模式" : "已切换到高级模式",
        description: nextMode === "beginner" ? "导航和首页已简化，所有高级功能仍然保留。" : "已恢复完整控制台导航。",
        tone: "success",
      });
      if (pathname === "/dashboard") router.refresh();
    } catch (error) {
      toast({ title: "模式切换失败", description: error instanceof Error ? error.message : "请稍后重试", tone: "error" });
    } finally {
      setModeSaving(false);
    }
  };

  return (
    <div className="min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 border-r bg-card/85 backdrop-blur-xl lg:block"><Sidebar pathname={pathname} items={activeNavigation} /></aside>
      {mobileOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button className="absolute inset-0 bg-slate-950/70 backdrop-blur-sm" aria-label="关闭导航" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-[min(86vw,290px)] border-r bg-card shadow-panel"><button className="focus-ring absolute right-3 top-3 rounded-md p-2 text-muted-foreground" onClick={() => setMobileOpen(false)} aria-label="关闭导航"><X className="h-4 w-4" /></button><Sidebar pathname={pathname} items={activeNavigation} onNavigate={() => setMobileOpen(false)} /></aside>
        </div>
      ) : null}
      <div className="lg:pl-64">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b bg-background/82 px-4 backdrop-blur-xl sm:px-6">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setMobileOpen(true)} aria-label="打开导航"><Menu className="h-5 w-5" /></Button>
          <div className="min-w-0"><p className="truncate text-sm font-semibold">{title}</p><p className="hidden text-[10px] text-muted-foreground sm:block">授权安全评估工作区</p></div>
          <button className="focus-ring ml-auto hidden h-9 w-64 items-center gap-2 rounded-lg border bg-muted/40 px-3 text-xs text-muted-foreground hover:bg-muted md:flex" onClick={() => setCommandOpen(true)}><Search className="h-3.5 w-3.5" />快速导航<span className="ml-auto rounded border bg-background px-1.5 py-0.5 font-mono text-[9px]">Ctrl K</span></button>
          <Button variant="outline" size="sm" loading={modeSaving || preferencesLoading} onClick={() => void switchExperienceMode()} aria-label={`切换到${experienceMode === "beginner" ? "高级" : "新手"}模式`}><SlidersHorizontal className="h-3.5 w-3.5" /><span className="hidden sm:inline">{experienceMode === "beginner" ? "新手模式" : "高级模式"}</span></Button>
          <Button variant="ghost" size="icon" onClick={toggleTheme} aria-label={theme === "dark" ? "切换亮色模式" : "切换暗色模式"}>{theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</Button>
          <DropdownMenu.Root open={alertsOpen} onOpenChange={setAlertsOpen}>
            <DropdownMenu.Trigger asChild><Button variant="ghost" size="icon" aria-label="查看通知" className="relative"><Bell className="h-4 w-4" /><span className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-amber-400" /></Button></DropdownMenu.Trigger>
            <DropdownMenu.Portal><DropdownMenu.Content align="end" sideOffset={8} className="z-50 w-80 rounded-xl border bg-card p-2 shadow-panel">
              <p className="px-2 py-2 text-xs font-semibold">安全通知</p>
              <div className="rounded-lg bg-muted/55 p-3"><p className="text-xs font-medium">Scope Guard 处于强制模式</p><p className="mt-1 text-[11px] leading-4 text-muted-foreground">所有外部请求将在解析域名及重定向后再次校验。</p></div>
              <p className="px-2 py-3 text-center text-[11px] text-muted-foreground">暂无待处理告警</p>
            </DropdownMenu.Content></DropdownMenu.Portal>
          </DropdownMenu.Root>
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild><button className="focus-ring flex items-center gap-2 rounded-lg p-1.5 hover:bg-muted"><div className="grid h-7 w-7 place-items-center rounded-md bg-primary/15 text-primary"><UserCircle2 className="h-4 w-4" /></div><span className="hidden max-w-24 truncate text-xs font-medium sm:block">{user?.display_name || user?.username || "用户"}</span><ChevronDown className="hidden h-3 w-3 text-muted-foreground sm:block" /></button></DropdownMenu.Trigger>
            <DropdownMenu.Portal><DropdownMenu.Content align="end" sideOffset={8} className="z-50 min-w-52 rounded-xl border bg-card p-1.5 shadow-panel">
              <div className="border-b px-2 py-2"><p className="text-xs font-medium">{user?.username}</p><p className="mt-0.5 text-[10px] text-muted-foreground">{user?.role || "已认证用户"}</p></div>
              <DropdownMenu.Item className="focus-ring mt-1 flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-xs outline-none hover:bg-muted" onSelect={() => router.push("/settings")}><SlidersHorizontal className="h-3.5 w-3.5" />个人设置</DropdownMenu.Item>
              <DropdownMenu.Item className="focus-ring flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-xs text-red-500 outline-none hover:bg-red-500/10" onSelect={logout}><LogOut className="h-3.5 w-3.5" />安全退出</DropdownMenu.Item>
            </DropdownMenu.Content></DropdownMenu.Portal>
          </DropdownMenu.Root>
        </header>
        <main className="mx-auto w-full max-w-[1680px] px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </div>
      <CommandPalette open={commandOpen} items={activeNavigation} onOpenChange={setCommandOpen} />
    </div>
  );
}
