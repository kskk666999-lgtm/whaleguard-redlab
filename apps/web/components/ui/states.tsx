import { AlertTriangle, Inbox, LoaderCircle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function LoadingState({ label = "正在加载安全数据…", className }: { label?: string; className?: string }) {
  return (
    <div className={cn("flex min-h-48 flex-col items-center justify-center gap-3 text-muted-foreground", className)} role="status">
      <LoaderCircle className="h-6 w-6 animate-spin text-primary" />
      <span className="text-sm">{label}</span>
    </div>
  );
}

export function EmptyState({ title = "暂无数据", description = "完成首次配置后，数据会显示在这里。", action }: { title?: string; description?: string; action?: React.ReactNode }) {
  return (
    <div className="flex min-h-52 flex-col items-center justify-center px-6 text-center">
      <div className="mb-3 rounded-xl border bg-muted p-3"><Inbox className="h-5 w-5 text-muted-foreground" /></div>
      <h3 className="text-sm font-medium">{title}</h3>
      <p className="mt-1 max-w-sm text-xs leading-5 text-muted-foreground">{description}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : "未知错误";
  return (
    <div className="flex min-h-52 flex-col items-center justify-center px-6 text-center">
      <div className="mb-3 rounded-xl border border-red-500/25 bg-red-500/10 p-3"><AlertTriangle className="h-5 w-5 text-red-400" /></div>
      <h3 className="text-sm font-medium">无法加载数据</h3>
      <p className="mt-1 max-w-md text-xs leading-5 text-muted-foreground">{message}</p>
      {onRetry ? <Button className="mt-4" variant="outline" size="sm" onClick={onRetry}><RefreshCw className="h-3.5 w-3.5" />重试</Button> : null}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} />;
}
