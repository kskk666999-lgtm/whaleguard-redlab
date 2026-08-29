import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest, login } from "@/lib/api";
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
