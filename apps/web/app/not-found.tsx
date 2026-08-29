import Link from "next/link";
import { ArrowLeft, ShieldQuestion } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Brand } from "@/components/layout/brand";

export default function NotFound() {
  return (
    <main className="security-grid grid min-h-screen place-items-center px-6">
      <div className="w-full max-w-lg text-center">
        <Brand className="mb-10 justify-center" />
        <div className="mx-auto grid h-16 w-16 place-items-center rounded-2xl border bg-muted"><ShieldQuestion className="h-7 w-7 text-primary" /></div>
        <p className="data-label mt-6 text-primary">404 / ROUTE NOT FOUND</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">安全工作区中没有此页面</h1>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">链接可能已失效，或当前版本尚未提供该路由。</p>
        <Button asChild className="mt-7"><Link href="/dashboard"><ArrowLeft className="h-4 w-4" />返回系统总览</Link></Button>
      </div>
    </main>
  );
}
