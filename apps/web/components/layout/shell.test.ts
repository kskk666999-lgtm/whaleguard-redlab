import { describe, expect, it } from "vitest";
import { beginnerNavigation, navigation } from "@/components/layout/shell";

describe("console navigation modes", () => {
  it("新手模式只显示六个明确入口", () => {
    expect(beginnerNavigation.map((item) => item.label)).toEqual([
      "首页",
      "安全学院",
      "网站体检",
      "Findings",
      "报告",
      "帮助",
    ]);
    expect(beginnerNavigation.map((item) => item.href)).toEqual([
      "/dashboard",
      "/academy",
      "/website-scan",
      "/findings",
      "/reports",
      "/help",
    ]);
  });

  it("高级模式保留完整控制台入口", () => {
    const paths = navigation.map((item) => item.href);
    expect(paths).toContain("/projects");
    expect(paths).toContain("/scopes");
    expect(paths).toContain("/runs");
    expect(paths).toContain("/mcpshield");
    expect(paths).toContain("/settings");
    expect(paths.length).toBeGreaterThan(beginnerNavigation.length);
  });
});
