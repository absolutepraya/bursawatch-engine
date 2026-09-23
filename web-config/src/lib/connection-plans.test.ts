import { describe, expect, it } from "vitest";
import { changeConnectionPlans, connectionLabel, connectionProviders, decodeConnectionPlans, emptyConnectionPlans, connectionDraftKey, encodeConnectionDraft, restoreConnectionDraft } from "./connection-plans";

describe("connection plans", () => {
  it("recovers incomplete names across unrelated saves but protects a changed field", () => {
    const raw = encodeConnectionDraft("Saved name", "ab");
    expect(restoreConnectionDraft(raw, "Saved name")).toBe("ab");
    expect(restoreConnectionDraft(raw, "Newer name")).toBe("Newer name");
    expect(restoreConnectionDraft("malformed", "Saved name")).toBe("Saved name");
    expect(connectionDraftKey("input:telegram")).not.toBe(connectionDraftKey("output:telegram"));
  });
  it("does not persist obvious credentials or URLs in recoverable drafts", () => {
    for (const label of ["https://example.test/secret", "token=secret", "bearer secret", "secret=value"]) {
      expect(encodeConnectionDraft("", label)).toBeNull();
    }
  });
  it("starts with an independent empty workspace", () => {
    const first = decodeConnectionPlans(null)!;
    first.workspaceName = "Changed workspace";
    expect(decodeConnectionPlans(null)).toEqual(emptyConnectionPlans);
  });
  it("keeps inputs separate from outputs and marks adapters accurately", () => {
    expect(connectionProviders.filter(p => p.direction === "input")).toHaveLength(4);
    expect(connectionProviders.filter(p => p.direction === "output" && p.supported).map(p => p.id)).toEqual(["output:discord"]);
  });
  it("saves and removes one direction without altering the other", () => {
    const input = changeConnectionPlans(emptyConnectionPlans, 0, { type: "save", id: "input:telegram", label: "Research intake" });
    const output = changeConnectionPlans(input, 1, { type: "save", id: "output:telegram", label: "My brief" });
    const removed = changeConnectionPlans(output, 2, { type: "remove", id: "output:telegram" });
    expect(removed.connections["input:telegram"]?.label).toBe("Research intake");
    expect(removed.connections["output:telegram"]).toBeUndefined();
    expect(input.connections["output:telegram"]).toBeUndefined();
    expect(emptyConnectionPlans.revision).toBe(0);
  });
  it("renames without altering prepared connections", () => {
    const next = changeConnectionPlans(emptyConnectionPlans, 0, { type: "rename", label: "  My research desk  " });
    expect(next.workspaceName).toBe("My research desk");
    expect(next.revision).toBe(1);
    expect(next.connections).toEqual({});
  });
  it("rejects stale editors", () => {
    const current = changeConnectionPlans(emptyConnectionPlans, 0, { type: "rename", label: "Research desk" });
    expect(() => changeConnectionPlans(current, 0, { type: "rename", label: "Old edit" })).toThrow("another tab");
  });
  it.each(["", "{", '{"version":2}', JSON.stringify({ ...emptyConnectionPlans, connections: { "output:unknown": {} } }), JSON.stringify({ ...emptyConnectionPlans, connected: true })])("preserves unreadable or unsupported storage: %s", raw => {
    expect(decodeConnectionPlans(raw)).toBeNull();
  });
  it.each(["ab", "a".repeat(61), "https://example.test/hook", "token=secret", "bearer secret", "line\nbreak"])("rejects invalid labels: %s", label => {
    expect(connectionLabel.safeParse(label).success).toBe(false);
  });
  it("round-trips a plan without claiming connection or delivery", () => {
    const next = changeConnectionPlans(emptyConnectionPlans, 0, { type: "save", id: "output:discord", label: "Research channel" }, "2026-09-18T08:00:00.000Z");
    expect(decodeConnectionPlans(JSON.stringify(next))).toEqual(next);
    expect(Object.keys(next.connections["output:discord"]!)).toEqual(["label", "updatedAt"]);
  });
});
