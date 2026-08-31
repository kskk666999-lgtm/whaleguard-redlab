import { describe, expect, it } from "vitest";
import { websiteModelSetupSchema, websiteScanInputSchema } from "./schemas";

const scanBase = {
  authorization_confirmed: true as const,
  generate_report: true as const,
  safety_level: "safe_read_only" as const,
};

describe("website scan URL boundaries", () => {
  it("accepts a plain authorized HTTP target", () => {
    expect(
      websiteScanInputSchema.safeParse({
        ...scanBase,
        target_url: "http://host.docker.internal:8080/",
      }).success,
    ).toBe(true);
  });

  it.each([
    "https://owned.example/?token=must-not-send",
    "https://owned.example/#private-fragment",
    "https://owned.example/%2e%2e/admin",
    "https://owned.example/%2525252e%2525252e/admin",
    "https://owned.example/a%5cb",
  ])("rejects ambiguous or sensitive target URL %s", (target_url) => {
    expect(websiteScanInputSchema.safeParse({ ...scanBase, target_url }).success).toBe(false);
  });

  it("rejects model API URLs containing query parameters", () => {
    expect(
      websiteModelSetupSchema.safeParse({
        project_id: "11111111-1111-4111-8111-111111111111",
        name: "我的模型",
        provider: "openai-compatible",
        base_url: "https://model.example/v1?token=must-not-persist",
        api_key: "not-a-real-key-placeholder",
        model: "example-model",
        authorization_confirmed: true,
      }).success,
    ).toBe(false);
  });
});
