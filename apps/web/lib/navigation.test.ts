import { describe, expect, it } from "vitest";

import { safeInternalPath } from "./navigation";

describe("safeInternalPath", () => {
  it.each([
    ["/dashboard", "/dashboard"],
    ["/runs?state=failed#latest", "/runs?state=failed#latest"],
    ["/academy?lesson=B01", "/academy?lesson=B01"],
  ])("keeps a same-origin application path", (value, expected) => {
    expect(safeInternalPath(value)).toBe(expected);
  });

  it.each([
    "https://evil.example/",
    "//evil.example/",
    "/\\evil.example/",
    "/%5cevil.example/",
    "/%255cevil.example/",
    "/%2525255cevil.example/",
    "%2f%2fevil.example/",
    "/%00dashboard",
    "/%2500dashboard",
  ])("rejects an unsafe redirect target: %s", (value) => {
    expect(safeInternalPath(value)).toBe("/dashboard");
  });

  it("uses the caller's fallback for malformed input", () => {
    expect(safeInternalPath("/%E0%A4%A", "/onboarding")).toBe("/onboarding");
    expect(safeInternalPath(`/dashboard?value=${"a".repeat(2048)}`, "/onboarding")).toBe(
      "/onboarding",
    );
  });
});
