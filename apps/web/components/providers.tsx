"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { CheckCircle2, CircleAlert, Info, X } from "lucide-react";
import { cn } from "@/lib/utils";

type Theme = "dark" | "light";
type Toast = { id: number; title: string; description?: string; tone?: "success" | "error" | "info" };
type AppContextValue = {
  theme: Theme;
  toggleTheme: () => void;
  toast: (value: Omit<Toast, "id">) => void;
};

const AppContext = createContext<AppContextValue | null>(null);

export function useApp() {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp must be used inside Providers");
  return value;
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: {
      queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false },
      mutations: { retry: 0 },
    },
  }));
  const [theme, setTheme] = useState<Theme>("dark");
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    const saved = localStorage.getItem("whaleguard.theme") as Theme | null;
    const next = saved === "light" ? "light" : "dark";
    setTheme(next);
    document.documentElement.classList.toggle("dark", next === "dark");
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((current) => {
      const next = current === "dark" ? "light" : "dark";
      localStorage.setItem("whaleguard.theme", next);
      document.documentElement.classList.toggle("dark", next === "dark");
      return next;
    });
  }, []);

  const toast = useCallback((value: Omit<Toast, "id">) => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((current) => [...current.slice(-3), { ...value, id }]);
    window.setTimeout(() => setToasts((current) => current.filter((item) => item.id !== id)), 4200);
  }, []);

  const context = useMemo(() => ({ theme, toggleTheme, toast }), [theme, toggleTheme, toast]);

  return (
    <QueryClientProvider client={client}>
      <AppContext.Provider value={context}>
        {children}
        <div className="fixed right-4 top-4 z-[100] flex w-[min(92vw,380px)] flex-col gap-2" aria-live="polite">
          {toasts.map((item) => {
            const Icon = item.tone === "error" ? CircleAlert : item.tone === "success" ? CheckCircle2 : Info;
            return (
              <div key={item.id} className={cn("animate-fade-up rounded-xl border bg-card/95 p-4 shadow-panel backdrop-blur-xl", item.tone === "error" && "border-red-500/35", item.tone === "success" && "border-emerald-500/35")}>
                <div className="flex items-start gap-3">
                  <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", item.tone === "error" ? "text-red-400" : item.tone === "success" ? "text-emerald-400" : "text-sky-400")} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{item.title}</p>
                    {item.description ? <p className="mt-1 text-xs leading-5 text-muted-foreground">{item.description}</p> : null}
                  </div>
                  <button className="focus-ring rounded p-0.5 text-muted-foreground hover:text-foreground" onClick={() => setToasts((current) => current.filter((toastItem) => toastItem.id !== item.id))} aria-label="关闭通知">
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </AppContext.Provider>
    </QueryClientProvider>
  );
}
