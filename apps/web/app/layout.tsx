import type { Metadata, Viewport } from "next";
import "@/app/globals.css";
import "@xyflow/react/dist/style.css";
import { Providers } from "@/components/providers";

export const metadata: Metadata = {
  title: { default: "WhaleGuard AI RedLab", template: "%s · WhaleGuard" },
  description: "鲸盾 AI 安全红队实验平台 — 仅用于本地、自有与明确授权目标。",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "dark light",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#080d18" },
    { media: "(prefers-color-scheme: light)", color: "#f4f7fa" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" className="dark" data-scroll-behavior="smooth" suppressHydrationWarning>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
