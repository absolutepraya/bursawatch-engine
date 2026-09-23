import { describe, expect, it } from "vitest";
import {
  backendContractUrl,
  filterWorkflows,
  reviewedBackend,
  supportingCapabilities,
  workflowCatalog,
} from "./workflow-catalog";
import { parseSourceFilters } from "./source-filters";

describe("backend-aligned workflow discovery", () => {
  it("covers the seven scheduled packages with unique identities", () => {
    expect(new Set(workflowCatalog.map((item) => item.id)).size).toBe(7);
    expect(workflowCatalog.map((item) => item.module).sort()).toEqual([
      "cron-dc-swing-board",
      "cron-ig-account-watch",
      "cron-tg-kelas-investasi-gtw",
      "cron-tg-market-news",
      "cron-tg-phintraco-swing",
      "cron-wa-channel-watch",
      "cron-x-account-watch",
    ]);
  });
  it("searches across source, output and description without losing category scope", () => {
    expect(filterWorkflows("  TELEGRAM  ", "all")).toHaveLength(3);
    expect(filterWorkflows("reels", "sources").map((item) => item.id)).toEqual([
      "instagram-accounts",
    ]);
    expect(filterWorkflows("target", "tracking").map((item) => item.id)).toEqual(["swing-board"]);
    expect(filterWorkflows("Telegram", "sources")).toEqual([]);
    expect(filterWorkflows("", "all")).toHaveLength(7);
    expect(filterWorkflows("not a workflow", "all")).toEqual([]);
  });
  it("links to immutable reviewed contracts, not live configuration or credentials", () => {
    for (const item of workflowCatalog) {
      const url = new URL(backendContractUrl(item));
      expect(url.hostname).toBe("github.com");
      expect(url.pathname).toContain(`/blob/${reviewedBackend}/${item.module}/`);
      expect(url.search).toBe("");
    }
  });
  it("sends social source tasks to their own platform, not a brokerage", () => {
    for (const [id, platform] of [
      ["x-accounts", "x"],
      ["instagram-accounts", "instagram"],
      ["whatsapp-channels", "whatsapp"],
    ]) {
      const action = workflowCatalog.find((item) => item.id === id)!.action!;
      const url = new URL(action.href, "https://example.test");
      expect(url.pathname).toBe("/app/following");
      expect(parseSourceFilters(Object.fromEntries(url.searchParams))).toEqual({
        platform,
        type: "all",
      });
    }
  });
  it("normalizes conflicting or unsupported deep-link filters", () => {
    expect(parseSourceFilters({ platform: "x", type: "firms" })).toEqual({
      platform: "x",
      type: "all",
    });
    expect(parseSourceFilters({ platform: "unknown", type: "firms" })).toEqual({
      platform: "all",
      type: "firms",
    });
    expect(parseSourceFilters({ platform: ["x", "telegram"], type: "__proto__" })).toEqual({
      platform: "all",
      type: "all",
    });
    expect(parseSourceFilters({ platform: "constructor" })).toEqual({
      platform: "all",
      type: "all",
    });
  });
  it("keeps supporting infrastructure and unscheduled research out of the workflow list", () => {
    expect(supportingCapabilities).toHaveLength(6);
    expect(supportingCapabilities.every((item) => !item.module.startsWith("cron-"))).toBe(true);
    expect(workflowCatalog.find((item) => item.id === "swing-board")!.action).toBeUndefined();
    expect(
      workflowCatalog.filter((item) => item.group === "research").every((item) => !item.action),
    ).toBe(true);
  });
});
