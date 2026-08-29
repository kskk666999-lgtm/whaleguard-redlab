import { expect, test, type Page, type Route } from "@playwright/test";

const projectId = "11111111-1111-4111-8111-111111111111";
const runId = "66666666-6666-4666-8666-666666666666";
const approvalId = "77777777-7777-4777-8777-777777777777";
const now = "2026-08-30T00:00:00Z";

function pageResult(items: unknown[]) {
  return { items, total: items.length, page: 1, page_size: 100, pages: 1 };
}

async function installApiMock(page: Page, writes: Array<{ path: string; body: unknown; headers: Record<string, string> }>) {
  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const method = request.method();
    if (method !== "GET") {
      writes.push({ path, body: request.postDataJSON(), headers: await request.allHeaders() });
    }
    if (path === "/auth/login" && method === "POST") {
      return route.fulfill({ json: { access_token: "e2e-access", token_type: "bearer", expires_in: 1800, csrf_token: "e2e-csrf", user: { id: "00000000-0000-4000-8000-000000000001", username: "admin", display_name: "安全管理员", role: "Admin" } } });
    }
    if (path === "/projects" && method === "POST") {
      return route.fulfill({ status: 201, json: { id: "22222222-2222-4222-8222-222222222222", name: "E2E 安全项目", description: "Playwright 创建", status: "active", created_at: now, updated_at: now } });
    }
    if (path === `/projects/${projectId}/scopes` && method === "POST") {
      return route.fulfill({ status: 201, json: { id: "33333333-3333-4333-8333-333333333333", project_id: projectId, name: "E2E 本地范围", target_type: "ip", target_value: "127.0.0.1", allowed_request_types: ["http", "https"], is_authorized: true, expires_at: "2030-01-01T00:00:00Z", created_at: now, updated_at: now } });
    }
    if (path === `/approvals/${approvalId}/decision` && method === "POST") {
      return route.fulfill({ json: { id: approvalId, project_id: projectId, run_id: runId, action_type: "request_sensitive_demo_data", risk_level: "high", reason: "模拟敏感数据请求必须人工确认", status: "approved", decision_reason: "已核验授权范围", created_at: now, updated_at: now } });
    }
    if (path === `/runs/${runId}` && method === "GET") {
      return route.fulfill({ json: { id: runId, project_id: projectId, suite_id: "44444444-4444-4444-8444-444444444444", name: "审批围栏测试", status: "queued", progress: 40, pause_requested: false, evaluation_mode: "rules", created_at: now, updated_at: now } });
    }
    if (path === "/projects") return route.fulfill({ json: pageResult([{ id: projectId, name: "WhaleGuard Demo Lab", description: "本地演示项目", status: "active", created_at: now, updated_at: now }]) });
    if (path === `/projects/${projectId}/scopes`) return route.fulfill({ json: pageResult([]) });
    if (path === "/test-suites") return route.fulfill({ json: pageResult([{ id: "44444444-4444-4444-8444-444444444444", project_id: projectId, name: "AgentArena 基础安全测试", created_at: now, updated_at: now }]) });
    if (path === "/agents") return route.fulfill({ json: pageResult([{ id: "55555555-5555-4555-8555-555555555555", project_id: projectId, name: "Mock Agent", agent_type: "mock-local", endpoint_url: "http://mock-agent:8102", enabled: true, created_at: now, updated_at: now }]) });
    if (path === "/runs") return route.fulfill({ json: pageResult([{ id: runId, project_id: projectId, suite_id: "44444444-4444-4444-8444-444444444444", name: "审批围栏测试", status: "waiting_approval", progress: 40, pause_requested: false, evaluation_mode: "rules", created_at: now, updated_at: now }]) });
    if (path === "/approvals") return route.fulfill({ json: pageResult([{ id: approvalId, project_id: projectId, run_id: runId, action_type: "request_sensitive_demo_data", risk_level: "high", reason: "模拟敏感数据请求必须人工确认", status: "pending", created_at: now, updated_at: now }]) });
    return route.fulfill({ json: pageResult([]) });
  });
}

test("登录、创建项目并创建授权 Scope", async ({ page }) => {
  const writes: Array<{ path: string; body: unknown; headers: Record<string, string> }> = [];
  await installApiMock(page, writes);

  await page.goto("/login");
  await page.getByLabel("密码", { exact: true }).fill("safe-e2e-password");
  await page.getByRole("button", { name: /进入安全工作区/ }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "系统总览" })).toBeVisible();

  await page.goto("/projects");
  await page.getByRole("button", { name: "新建项目" }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("E2E 安全项目");
  await page.getByLabel("项目说明", { exact: true }).fill("Playwright 创建");
  await page.getByRole("button", { name: "创建项目", exact: true }).click();
  await expect(page.getByText("项目已创建")).toBeVisible();

  const projectWrite = writes.find((item) => item.path === "/projects");
  expect(projectWrite?.body).toEqual({ name: "E2E 安全项目", description: "Playwright 创建" });
  expect(projectWrite?.headers.authorization).toBe("Bearer e2e-access");
  expect(projectWrite?.headers["x-csrf-token"]).toBe("e2e-csrf");

  await page.goto("/scopes");
  await page.getByRole("button", { name: "添加授权范围" }).click();
  await page.getByLabel("范围名称").fill("E2E 本地范围");
  await page.getByLabel("目标", { exact: true }).fill("127.0.0.1");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "确认并保存" }).click();
  await expect(page.getByText("授权范围已保存")).toBeVisible();

  const scopeWrite = writes.find((item) => item.path === `/projects/${projectId}/scopes`);
  expect(scopeWrite?.body).toEqual(expect.objectContaining({ name: "E2E 本地范围", target_type: "ip", target_value: "127.0.0.1", is_authorized: true, allowed_request_types: ["http", "https"] }));
  expect(scopeWrite?.headers["x-csrf-token"]).toBe("e2e-csrf");
});

test("全部 16 个控制台路由可访问", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("whaleguard.access_token", "e2e-access");
    localStorage.setItem("whaleguard.csrf_token", "e2e-csrf");
    localStorage.setItem("whaleguard.user", JSON.stringify({ username: "admin", role: "Admin" }));
  });
  await installApiMock(page, []);
  const routes = [
    ["/dashboard", "系统总览"], ["/projects", "项目中心"], ["/scopes", "授权与测试范围"], ["/models", "模型渠道"], ["/agents", "Agent 管理"], ["/test-cases", "AI 红队测试用例"], ["/runs", "测试运行中心"], ["/mcpshield", "MCPShield"], ["/arena", "AgentArena"], ["/findings", "Findings"], ["/evidence", "证据中心"], ["/reports", "报告中心"], ["/knowledge", "知识库"], ["/tools", "工具与 MCP"], ["/audit", "审计日志"], ["/settings", "系统设置"],
  ] as const;
  for (const [path, title] of routes) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
  }
});

test("待审批运行可提交带 CSRF 的人工决定", async ({ page }) => {
  const writes: Array<{ path: string; body: unknown; headers: Record<string, string> }> = [];
  await page.addInitScript(() => {
    localStorage.setItem("whaleguard.access_token", "e2e-access");
    localStorage.setItem("whaleguard.csrf_token", "e2e-csrf");
    localStorage.setItem("whaleguard.user", JSON.stringify({ username: "admin", role: "Admin" }));
  });
  await installApiMock(page, writes);
  await page.goto("/runs");
  await page.getByRole("button", { name: "详情" }).click();
  await expect(page.getByRole("region", { name: "高风险操作审批" })).toBeVisible();
  const approve = page.getByRole("button", { name: /批准并继续/ });
  await expect(approve).toBeDisabled();
  await page.getByLabel("审批理由").fill("已核验授权范围");
  await approve.click();
  await expect(page.getByText("审批已通过，任务重新入队")).toBeVisible();

  const decision = writes.find((item) => item.path === `/approvals/${approvalId}/decision`);
  expect(decision?.body).toEqual({ status: "approved", decision_reason: "已核验授权范围" });
  expect(decision?.headers.authorization).toBe("Bearer e2e-access");
  expect(decision?.headers["x-csrf-token"]).toBe("e2e-csrf");
});
