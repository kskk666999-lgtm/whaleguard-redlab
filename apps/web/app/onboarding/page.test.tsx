import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  syncPreferences: vi.fn(),
  toast: vi.fn(),
  updatePreferences: vi.fn(),
  getSystemStatus: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace }),
}));

vi.mock("@/components/providers", () => ({
  useApp: () => ({
    preferences: null,
    preferencesError: null,
    preferencesReady: true,
    syncPreferences: mocks.syncPreferences,
    toast: mocks.toast,
    updatePreferences: mocks.updatePreferences,
  }),
}));

vi.mock("@/lib/api", () => ({
  getSystemStatus: mocks.getSystemStatus,
}));

import OnboardingPage from "@/app/onboarding/page";

describe("onboarding flow", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("whaleguard.access_token", "test-token");
    mocks.replace.mockReset();
    mocks.syncPreferences.mockReset();
    mocks.toast.mockReset();
    mocks.updatePreferences.mockReset().mockResolvedValue({ experience_mode: "beginner", onboarding_complete: true, onboarding_goal: "learn" });
    mocks.getSystemStatus.mockReset().mockResolvedValue({
      overall: "ready",
      checked_at: "2026-09-01T00:00:00Z",
      services: {
        api: { status: "normal", label: "API", detail: "本地服务正常", optional: false },
        model_provider: { status: "optional", label: "AI 模型", detail: "未配置也可以完整学习 Academy", optional: true },
      },
      model_provider_name: null,
    });
  });

  afterEach(() => vi.clearAllMocks());

  it("四步内完成目标、真实状态、可选模型和偏好保存", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><OnboardingPage /></QueryClientProvider>);

    await userEvent.click(screen.getByRole("button", { name: /我想学习 AI 安全/ }));
    await userEvent.click(screen.getByRole("button", { name: /下一步/ }));
    expect(await screen.findByText("确认本地服务是否准备好")).toBeInTheDocument();
    expect(await screen.findByText("本地服务正常")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /下一步/ }));
    expect(screen.getByText("API Key 是可选的")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /暂时跳过/ }));
    expect(screen.getByText("设置完成，可以开始了")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /进入 WhaleGuard/ }));
    await waitFor(() => expect(mocks.updatePreferences).toHaveBeenCalledWith({
      experience_mode: "beginner",
      onboarding_complete: true,
      onboarding_goal: "learn",
    }));
    expect(mocks.replace).toHaveBeenCalledWith("/academy");
  });
});
