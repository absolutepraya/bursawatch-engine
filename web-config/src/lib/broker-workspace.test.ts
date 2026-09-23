import { afterEach, describe, expect, it, vi } from "vitest";
import {
  clearBrokerDraft,
  readBrokerDraft,
  saveBrokerDraft,
  changeWorkspace,
  decodeWorkspace,
  defaultPreferences,
  emptyWorkspace,
  preferencesSchema,
  updateWorkspace,
  workspaceKey,
} from "@/lib/broker-workspace";
import type { BrokerId } from "@/lib/brokers";

const now = "2026-09-17T08:00:00.000Z";
const both = () =>
  changeWorkspace(emptyWorkspace, { type: "add", ids: ["bri-danareksa", "phintraco"] }, now);
afterEach(() => vi.unstubAllGlobals());
describe("brokerage configuration contract", () => {
  it("recovers a per-tab draft without changing saved configuration", () => {
    const values = new Map<string, string>();
    vi.stubGlobal("sessionStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    });
    expect(
      saveBrokerDraft("phintraco", defaultPreferences, { ...defaultPreferences, goal: "invest" }),
    ).toBe(true);
    expect(readBrokerDraft("phintraco", defaultPreferences)?.goal).toBe("invest");
    expect(readBrokerDraft("bri-danareksa", defaultPreferences)).toBeNull();
    clearBrokerDraft("phintraco");
    expect(readBrokerDraft("phintraco", defaultPreferences)).toBeNull();
  });
  it("does not recover a draft over a newer saved configuration", () => {
    let value: string | null = null;
    vi.stubGlobal("sessionStorage", {
      getItem: () => value,
      setItem: (_key: string, raw: string) => {
        value = raw;
      },
    });
    saveBrokerDraft("phintraco", defaultPreferences, { ...defaultPreferences, goal: "invest" });
    expect(readBrokerDraft("phintraco", { ...defaultPreferences, language: "en" })).toBeNull();
  });
  it("handles unavailable draft storage without claiming recovery", () => {
    vi.stubGlobal("sessionStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
      removeItem: () => {
        throw new Error("blocked");
      },
    });
    expect(saveBrokerDraft("phintraco", defaultPreferences, defaultPreferences)).toBe(false);
    expect(readBrokerDraft("phintraco", defaultPreferences)).toBeNull();
    expect(() => clearBrokerDraft("phintraco")).not.toThrow();
  });
  it("adds selected firms together without duplicate watches or log entries", () => {
    const state = changeWorkspace(both(), { type: "add", ids: ["phintraco", "phintraco"] }, now);
    expect(state.watches).toHaveLength(2);
    expect(state.events).toHaveLength(2);
    expect(emptyWorkspace.watches).toHaveLength(0);
  });
  it("stores independent per-firm preferences through a JSON round trip", () => {
    const changed = changeWorkspace(
      both(),
      {
        type: "configure",
        id: "phintraco",
        preferences: {
          ...defaultPreferences,
          goal: "invest",
          priceSummary: false,
          instructions: "  Explain terms simply.  ",
        },
      },
      now,
    );
    const loaded = decodeWorkspace(JSON.stringify(changed))!;
    expect(loaded.watches[1].preferences).toMatchObject({
      goal: "invest",
      priceSummary: false,
      instructions: "Explain terms simply.",
    });
    expect(loaded.watches[0].preferences).toEqual(defaultPreferences);
    expect(loaded.events[0]).toMatchObject({ action: "configured", brokerId: "phintraco" });
  });
  it("pauses, resumes and removes only the specified firm", () => {
    let state = changeWorkspace(both(), { type: "toggle", id: "phintraco" }, now);
    expect(state.watches[1].paused).toBe(true);
    state = changeWorkspace(state, { type: "toggle", id: "phintraco" }, now);
    expect(state.watches[1].paused).toBe(false);
    state = changeWorkspace(state, { type: "remove", id: "phintraco" }, now);
    expect(state.watches.map((x) => x.brokerId)).toEqual(["bri-danareksa"]);
    expect(state.events[0].action).toBe("removed");
    expect(() =>
      changeWorkspace(state, {
        type: "configure",
        id: "phintraco",
        preferences: defaultPreferences,
      }),
    ).toThrow("no longer");
  });
  it("fails closed for corrupt data, unknown firms and unsupported values", () => {
    expect(decodeWorkspace("not JSON")).toBeNull();
    expect(decodeWorkspace('{"version":2}')).toBeNull();
    expect(() =>
      changeWorkspace(emptyWorkspace, { type: "add", ids: ["unknown" as BrokerId] }),
    ).toThrow();
    expect(
      preferencesSchema.safeParse({ ...defaultPreferences, goal: "guaranteed-profit" }).success,
    ).toBe(false);
    expect(
      preferencesSchema.safeParse({ ...defaultPreferences, instructions: "x".repeat(601) }).success,
    ).toBe(false);
  });
  it("bounds local history without losing current configuration", () => {
    let state = both();
    for (let i = 0; i < 55; i++)
      state = changeWorkspace(state, { type: "toggle", id: "phintraco" }, now);
    expect(state.events).toHaveLength(50);
    expect(state.watches).toHaveLength(2);
    expect(state.watches[1].paused).toBe(true);
  });
  it("reports write failure and never signals a successful save", () => {
    const dispatchEvent = vi.fn();
    vi.stubGlobal("window", { dispatchEvent });
    vi.stubGlobal("localStorage", {
      getItem: () => null,
      setItem: () => {
        throw new Error("quota");
      },
    });
    expect(() => updateWorkspace({ type: "add", ids: ["phintraco"] })).toThrow("Could not save");
    expect(dispatchEvent).not.toHaveBeenCalled();
  });
  it("does not overwrite unreadable browser data", () => {
    const setItem = vi.fn();
    vi.stubGlobal("localStorage", { getItem: () => "corrupt", setItem });
    expect(() => updateWorkspace({ type: "add", ids: ["phintraco"] })).toThrow("not been changed");
    expect(setItem).not.toHaveBeenCalled();
  });
  it("persists preferences only in its own namespaced key", () => {
    const values = new Map([["unrelated-user-data", "keep"]]);
    const dispatchEvent = vi.fn();
    vi.stubGlobal("window", { dispatchEvent });
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    });
    updateWorkspace({ type: "add", ids: ["phintraco"] });
    updateWorkspace({
      type: "configure",
      id: "phintraco",
      preferences: { ...defaultPreferences, language: "en" },
    });
    expect(decodeWorkspace(values.get(workspaceKey)!)?.watches[0].preferences.language).toBe("en");
    expect(values.get("unrelated-user-data")).toBe("keep");
    expect(dispatchEvent).toHaveBeenCalledTimes(2);
  });
});
