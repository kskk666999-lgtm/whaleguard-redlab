import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

type FirstRunCredentials = { username: string; password: string };
type RunSnapshot = { status: string; security_score: number | null };
type PendingApproval = { id: string; run_id?: string | null };

const webBaseUrl = process.env.WG_E2E_WEB_BASE_URL || "http://127.0.0.1:3000";
const apiBaseUrl = process.env.WG_E2E_API_BASE_URL || "http://127.0.0.1:8000/api/v1";

function requireLoopbackUrl(raw: string, label: string): URL {
  const value = new URL(raw);
  if (value.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(value.hostname)) {
    throw new Error(`${label} must be an explicit loopback HTTP URL`);
  }
  return value;
}

function readCredentials(): FirstRunCredentials {
  const configuredPath = process.env.WG_E2E_CREDENTIALS_FILE;
  if (!configuredPath) {
    throw new Error("WG_E2E_CREDENTIALS_FILE is required for the real-stack Playwright lane");
  }
  const values = new Map<string, string>();
  for (const line of readFileSync(resolve(configuredPath), "utf8").split(/\r?\n/)) {
    const separator = line.indexOf("=");
    if (separator > 0) values.set(line.slice(0, separator).trim().toLowerCase(), line.slice(separator + 1));
  }
  const username = values.get("username");
  const password = values.get("password");
  if (!username || !password) throw new Error("first-run credential file is incomplete");
  return { username, password };
}

async function authenticatedJson<T>(page: Page, path: string): Promise<T> {
  return page.evaluate(
    async ({ base, resource }) => {
      const token = localStorage.getItem("whaleguard.access_token");
      if (!token) throw new Error("browser session has no access token");
      const response = await fetch(`${base}${resource}`, {
        headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error(`authenticated API read failed with HTTP ${response.status}`);
      return response.json();
    },
    { base: apiBaseUrl, resource: path },
  );
}

test.beforeAll(() => {
  requireLoopbackUrl(webBaseUrl, "WG_E2E_WEB_BASE_URL");
  const apiUrl = requireLoopbackUrl(apiBaseUrl, "WG_E2E_API_BASE_URL");
  if (!apiUrl.pathname.replace(/\/$/, "").endsWith("/api/v1")) {
    throw new Error("WG_E2E_API_BASE_URL must end with /api/v1");
  }
});

test("真实 Docker 栈完成登录、授权、Agent 运行、审批和 RQ 回执", async ({ page, request }) => {
  const credentials = readCredentials();
  const readiness = await request.get(`${apiBaseUrl.replace(/\/api\/v1\/?$/, "")}/ready`);
  expect(readiness.ok()).toBe(true);
  await expect(readiness.json()).resolves.toMatchObject({ status: "ok", database: "ok" });

  await page.goto("/login");
  await page.getByLabel("用户名", { exact: true }).fill(credentials.username);
  await page.getByLabel("密码", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: /进入安全工作区/ }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "系统总览" })).toBeVisible();

  const suffix = `${Date.now()}-${test.info().workerIndex}`;
  const projectName = `Playwright 真实栈 ${suffix}`;
  const scopeName = `Playwright 回环授权 ${suffix}`;

  await page.goto("/projects");
  await page.getByRole("button", { name: "新建项目" }).click();
  await page.getByLabel("项目名称", { exact: true }).fill(projectName);
  await page.getByLabel("项目说明", { exact: true }).fill("真实 Docker 集成验收；仅限回环地址。");
  await page.getByRole("button", { name: "创建项目", exact: true }).click();
  await expect(page.getByText("项目已创建")).toBeVisible();
  await expect(page.getByText(projectName, { exact: true })).toBeVisible();

  await page.goto("/scopes");
  await page.getByLabel("选择项目").selectOption({ label: projectName });
  await page.getByRole("button", { name: "添加授权范围" }).click();
  await page.getByLabel("范围名称").fill(scopeName);
  await page.getByLabel("目标", { exact: true }).fill("127.0.0.1");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "确认并保存" }).click();
  await expect(page.getByText("授权范围已保存")).toBeVisible();
  await expect(page.getByText("127.0.0.1", { exact: true })).toBeVisible();
  await expect(page.getByText("authorized", { exact: true })).toBeVisible();

  await page.goto("/runs");
  await page.getByRole("button", { name: "运行测试套件" }).click();
  await page.getByLabel("项目", { exact: true }).selectOption({ label: "WhaleGuard Demo Lab" });
  await expect(page.getByLabel("测试套件", { exact: true })).toHaveValue(/.+/);
  await expect(page.getByLabel("Agent 目标", { exact: true })).toHaveValue(/.+/);
  const runResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.request().method() === "POST" && url.pathname === "/api/v1/runs";
  });
  await page.getByRole("button", { name: "确认运行" }).click();
  const runResponse = await runResponsePromise;
  expect(runResponse.status()).toBe(202);
  const run = (await runResponse.json()) as { id: string; project_id: string };
  expect(run.id).toMatch(/^[0-9a-f-]{36}$/i);
  await expect(page.getByText("测试任务已入队")).toBeVisible();

  const runDialog = page.getByRole("dialog");
  const approvedIds = new Set<string>();
  for (let attempt = 0; attempt < 15; attempt += 1) {
    await expect
      .poll(
        async () => {
          const snapshot = await authenticatedJson<RunSnapshot>(page, `/runs/${run.id}`);
          if (["completed", "failed", "cancelled"].includes(snapshot.status)) return snapshot.status;
          if (snapshot.status !== "waiting_approval") return snapshot.status;
          const approvals = await authenticatedJson<{ items: PendingApproval[] }>(
            page,
            `/approvals?project_id=${encodeURIComponent(run.project_id)}&status_filter=pending&page=1&page_size=100`,
          );
          return approvals.items.some((item) => item.run_id === run.id && !approvedIds.has(item.id))
            ? "new_approval"
            : "waiting_approval";
        },
        { timeout: 120_000, intervals: [500, 1_000, 2_000] },
      )
      .toMatch(/^(new_approval|completed|failed|cancelled)$/);

    const snapshot = await authenticatedJson<RunSnapshot>(page, `/runs/${run.id}`);
    if (snapshot.status === "completed") break;
    expect(snapshot.status).toBe("waiting_approval");
    const approvals = await authenticatedJson<{ items: PendingApproval[] }>(
      page,
      `/approvals?project_id=${encodeURIComponent(run.project_id)}&status_filter=pending&page=1&page_size=100`,
    );
    const approval = approvals.items.find((item) => item.run_id === run.id && !approvedIds.has(item.id));
    expect(approval).toBeDefined();
    approvedIds.add(approval!.id);

    const approvalRegion = runDialog.getByRole("region", { name: "高风险操作审批" });
    if (!(await approvalRegion.isVisible())) {
      await page.reload();
      const currentRunRow = page.getByRole("row").filter({ hasText: run.id.slice(0, 8) });
      await expect(currentRunRow).toBeVisible();
      await currentRunRow.getByRole("button", { name: "详情" }).click();
    }
    await expect(runDialog.getByText("等待审批", { exact: true })).toBeVisible({ timeout: 15_000 });
    await expect(approvalRegion).toBeVisible();
    await runDialog.getByLabel("审批理由").fill("真实集成验收：仅批准虚构敏感数据模拟。");
    const decisionResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return response.request().method() === "POST" && url.pathname === `/api/v1/approvals/${approval!.id}/decision`;
    });
    await runDialog.getByRole("button", { name: /批准并继续/ }).click();
    expect((await decisionResponsePromise).status()).toBe(200);
    await expect(page.getByText("审批已通过，任务重新入队")).toBeVisible();
  }

  await expect
    .poll(async () => (await authenticatedJson<RunSnapshot>(page, `/runs/${run.id}`)).status, {
      timeout: 120_000,
      intervals: [500, 1_000, 2_000],
    })
    .toBe("completed");
  expect(approvedIds.size).toBeGreaterThan(0);
  const completedRun = await authenticatedJson<RunSnapshot>(page, `/runs/${run.id}`);
  expect(completedRun.security_score).toEqual(expect.any(Number));

  await expect
    .poll(
      async () =>
        (
          await authenticatedJson<{ total: number }>(
            page,
            `/runs/${run.id}/delivery-receipts?page=1&page_size=100`,
          )
        ).total,
      { timeout: 120_000, intervals: [1_000, 2_000, 3_000] },
    )
    .toBe(15);

  await expect(runDialog.getByText("completed", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(runDialog.getByRole("button", { name: "任务已结束" })).toBeDisabled();
});
