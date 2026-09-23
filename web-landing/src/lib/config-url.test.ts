import { describe, expect, it } from "vitest";
import { configOrigin, workspaceUrl, type WorkspacePath } from "./config-url";

describe("workspace origin", () => {
  it("defaults only development to the config app port", () => {
    expect(configOrigin(undefined)).toBe("http://localhost:3100");
    expect(() => configOrigin(undefined, true)).toThrow("BURSAWATCH_CONFIG_URL");
    expect(() => configOrigin("  ", true)).toThrow();
  });
  it("normalizes HTTPS origins and development loopback", () => {
    expect(configOrigin(" https://workspace.example.com/ ", true)).toBe(
      "https://workspace.example.com",
    );
    expect(configOrigin("http://127.0.0.1:3100")).toBe("http://127.0.0.1:3100");
    expect(configOrigin("http://[::1]:3100")).toBe("http://[::1]:3100");
  });
  it.each([
    "javascript:alert(1)",
    "//workspace.example.com",
    "/app",
    "invalid",
    "https://user:secret@workspace.example.com",
    "https://workspace.example.com/app",
    "https://workspace.example.com/?token=private",
    "https://workspace.example.com/#app",
    "http://workspace.example.com",
    "ftp://workspace.example.com",
  ])("rejects unsafe or ambiguous navigation origin %s", (value) => {
    expect(() => configOrigin(value)).toThrow();
  });
  it.each(["http://localhost:3100", "https://localhost", "https://127.0.0.1"])(
    "rejects loopback in production %s",
    (value) => {
      expect(() => configOrigin(value, true)).toThrow();
    },
  );
});

describe("workspace routes", () => {
  it.each([
    "/workspace",
    "/app",
    "/app/insights",
    "/app/discover",
    "/app/automations/new",
  ] as const)("links %s to the separate application", (path) => {
    expect(workspaceUrl("https://workspace.example.com", path)).toBe(
      `https://workspace.example.com${path}`,
    );
  });
  it("rejects unexpected destinations at runtime", () => {
    expect(() =>
      workspaceUrl("https://workspace.example.com", "//other.example" as WorkspacePath),
    ).toThrow();
  });
});
