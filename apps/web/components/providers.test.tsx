import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Providers, useApp } from "@/components/providers";
import { saveSession } from "@/lib/auth";

function PreferencesProbe() {
  const { experienceMode, preferencesReady, updatePreferences } = useApp();
  return (
    <div>
      <p>{preferencesReady ? `mode:${experienceMode}` : "loading"}</p>
      <button type="button" onClick={() => void updatePreferences({ experience_mode: "advanced" })}>切换高级模式</button>
    </div>
  );
}

describe("experience preferences provider", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => vi.unstubAllGlobals());

  it("登录会话后 GET 偏好，并通过 PATCH 持久化模式切换", async () => {
    saveSession("access-token", "csrf-token", { username: "admin" });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ experience_mode: "beginner", onboarding_complete: true, onboarding_goal: "learn" }), { status: 200, headers: { "content-type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ experience_mode: "advanced", onboarding_complete: true, onboarding_goal: "learn" }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    render(<Providers><PreferencesProbe /></Providers>);
    expect(await screen.findByText("mode:beginner")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "切换高级模式" }));
    expect(await screen.findByText("mode:advanced")).toBeInTheDocument();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[0][0]).toContain("/auth/preferences");
    const options = fetchMock.mock.calls[1][1] as RequestInit;
    expect(options.method).toBe("PATCH");
    expect(options.body).toBe(JSON.stringify({ experience_mode: "advanced" }));
  });
});
