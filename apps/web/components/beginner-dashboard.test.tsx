import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  fetchPage: vi.fn(),
  getSystemStatus: vi.fn(),
}));

vi.mock("@/lib/api", () => apiMocks);

import { BeginnerDashboard } from "@/components/beginner-dashboard";

describe("beginner dashboard", () => {
  beforeEach(() => {
    apiMocks.fetchPage.mockReset().mockImplementation((path: string) => {
      if (path.startsWith("/projects")) return Promise.resolve({ items: [{ id: "project-1", name: "演示项目", status: "active", created_at: "2026-09-01T00:00:00Z" }], total: 1, page: 1, page_size: 100, pages: 1 });
      if (path.startsWith("/findings")) return Promise.resolve({ items: [{ id: "finding-1", title: "缺少安全响应头", severity: "low", status: "open", category: "headers", created_at: "2026-09-01T02:00:00Z" }], total: 1, page: 1, page_size: 20, pages: 1 });
      return Promise.resolve({ items: [{ id: "run-1", name: "本地测试", status: "completed", project_id: "project-1", created_at: "2026-09-01T01:00:00Z" }], total: 1, page: 1, page_size: 20, pages: 1 });
    });
    apiMocks.apiRequest.mockReset().mockResolvedValue({ scenario_count: 17, completed_count: 3, total_score: 300, max_score: 1700 });
    apiMocks.getSystemStatus.mockReset().mockResolvedValue({
      overall: "ready",
      checked_at: "2026-09-01T00:00:00Z",
      services: { api: { status: "normal", label: "API", detail: "本地服务正常", optional: false } },
      model_provider_name: null,
    });
  });

  it("展示三个真实入口、真实进度、最近结果和系统状态", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><BeginnerDashboard /></QueryClientProvider>);

    expect(screen.getByRole("heading", { name: "你今天想做什么？" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /开始学习/ })).toHaveAttribute("href", "/academy");
    expect(screen.getByRole("link", { name: /开始体检/ })).toHaveAttribute("href", "/website-scan");
    expect(screen.getByRole("link", { name: /查看 Findings/ })).toHaveAttribute("href", "/findings");
    expect(
      await screen.findByText((_, element) => element?.textContent === "3 / 17"),
    ).toBeInTheDocument();
    expect(await screen.findByText("缺少安全响应头")).toBeInTheDocument();
    expect(await screen.findByText("本地服务正常")).toBeInTheDocument();
  });
});
