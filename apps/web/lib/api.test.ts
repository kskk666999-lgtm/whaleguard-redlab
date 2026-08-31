import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  apiRequest,
  getSystemStatus,
  getUserPreferences,
  login,
  patchUserPreferences,
} from "@/lib/api";
import { saveSession } from "@/lib/auth";

describe("API client", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => vi.unstubAllGlobals());

  it("写请求自动携带 Bearer、CSRF 与 JSON headers", async () => {
    saveSession("access-token", "csrf-token", { username: "admin" });
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "1" }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/projects", { method: "POST", body: { name: "Demo" } });
    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(options.headers);
    expect(headers.get("Authorization")).toBe("Bearer access-token");
    expect(headers.get("X-CSRF-Token")).toBe("csrf-token");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(options.body).toBe(JSON.stringify({ name: "Demo" }));
  });

  it("登录请求不发送已有认证头并使用 Zod 校验响应", async () => {
    saveSession("stale-token", "stale-csrf", { username: "old" });
    const payload = { access_token: "new-token", token_type: "bearer", csrf_token: "new-csrf", expires_in: 1800, user: { username: "admin", role: "Admin" } };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(login("admin", "a-secure-password")).resolves.toMatchObject({ access_token: "new-token" });
    const headers = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers);
    expect(headers.has("Authorization")).toBe(false);
    expect(headers.has("X-CSRF-Token")).toBe(false);
  });

  it("403 返回明确的 RBAC 权限提示", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "permission denied" }), { status: 403, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiRequest("/settings", { method: "PUT", body: {} })).rejects.toEqual(expect.objectContaining({ status: 403, message: "当前角色没有执行此操作的权限" }));
  });

  it("通过真实偏好和系统状态端点读取并保存新手体验", async () => {
    saveSession("access-token", "csrf-token", { username: "admin" });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ experience_mode: "beginner", onboarding_complete: false, onboarding_goal: null }), { status: 200, headers: { "content-type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ experience_mode: "advanced", onboarding_complete: true, onboarding_goal: "both" }), { status: 200, headers: { "content-type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ overall: "ready", checked_at: "2026-09-01T00:00:00Z", services: { api: { status: "normal", label: "API", detail: "本地服务正常", optional: false } }, model_provider_name: null }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getUserPreferences()).resolves.toMatchObject({ experience_mode: "beginner" });
    await expect(patchUserPreferences({ experience_mode: "advanced", onboarding_complete: true, onboarding_goal: "both" })).resolves.toMatchObject({ experience_mode: "advanced", onboarding_goal: "both" });
    await expect(getSystemStatus()).resolves.toMatchObject({ overall: "ready", services: { api: { status: "normal" } } });

    expect(fetchMock.mock.calls[0][0]).toContain("/auth/preferences");
    const patchOptions = fetchMock.mock.calls[1][1] as RequestInit;
    expect(patchOptions.method).toBe("PATCH");
    expect(new Headers(patchOptions.headers).get("X-CSRF-Token")).toBe("csrf-token");
    expect(patchOptions.body).toBe(JSON.stringify({ experience_mode: "advanced", onboarding_complete: true, onboarding_goal: "both" }));
    expect(fetchMock.mock.calls[2][0]).toContain("/system/status");
  });

  it("401 清除本地会话并返回重新登录提示", async () => {
    saveSession("expired-token", "expired-csrf", { username: "admin" });
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "expired" }), { status: 401, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    const navigationNoise = vi.spyOn(console, "error").mockImplementation(() => undefined);
    await expect(apiRequest("/auth/me")).rejects.toEqual(expect.objectContaining({ status: 401, message: "登录已失效，请重新登录" }));
    expect(localStorage.getItem("whaleguard.access_token")).toBeNull();
    expect(localStorage.getItem("whaleguard.csrf_token")).toBeNull();
    navigationNoise.mockRestore();
  });
});
