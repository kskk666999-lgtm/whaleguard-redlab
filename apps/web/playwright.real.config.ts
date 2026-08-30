import { defineConfig, devices } from "@playwright/test";

const webBaseUrl = process.env.WG_E2E_WEB_BASE_URL || "http://127.0.0.1:3000";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/real-stack.spec.ts",
  timeout: 240_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["html", { outputFolder: "playwright-report-real", open: "never" }]],
  outputDir: "test-results-real",
  use: {
    baseURL: webBaseUrl,
    // Real-stack login uses an ephemeral random password. Network traces and
    // videos are disabled so credentials cannot enter uploaded diagnostics.
    trace: "off",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [{ name: "chromium-real-stack", use: { ...devices["Desktop Chrome"] } }],
});
