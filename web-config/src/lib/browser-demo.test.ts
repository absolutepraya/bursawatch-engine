import { afterEach, describe, expect, it, vi } from "vitest";
import { readBrowserWatches, saveBrowserWatch, toggleBrowserWatch } from "@/lib/browser-demo";
import type { CreateAutomationInput } from "@/lib/types";

const input: CreateAutomationInput = { name: "My banking watch", sourceIds: ["sectors"], symbols: ["BBRI"], horizon: "days-to-weeks", triggers: { sourceMention: false, postClose: true, priceMove: true, priceMoveThreshold: 3, filingOrFlow: false }, scheduleTime: "15:30", destination: "+6281255551847", language: "id", tone: "concise" };
function storage() {
  const values = new Map<string,string>();
  vi.stubGlobal("localStorage", { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value) });
  vi.stubGlobal("window", { dispatchEvent: vi.fn() });
  return values;
}
afterEach(() => vi.unstubAllGlobals());
describe("private browser demo watches", () => {
  it("persists settings with a masked destination and supports pausing", () => {
    const values = storage();
    saveBrowserWatch(input);
    const [watch] = readBrowserWatches();
    expect(watch.name).toBe(input.name);
    expect(watch.symbols).toEqual(["BBRI"]);
    expect(JSON.stringify([...values.values()])).not.toContain(input.destination);
    toggleBrowserWatch(watch.id);
    expect(readBrowserWatches()[0].paused).toBe(true);
  });
  it("rejects unsupported triggers before saving", () => {
    storage();
    expect(() => saveBrowserWatch({ ...input, triggers: { ...input.triggers, sourceMention: true } })).toThrow();
    expect(readBrowserWatches()).toEqual([]);
  });
  it("handles corrupt or unavailable browser storage", () => {
    const values = storage();
    values.set("bursawatch-demo-watches-v1", "broken JSON");
    expect(readBrowserWatches()).toEqual([]);
    vi.stubGlobal("localStorage", { getItem: () => { throw new Error("Disabled"); } });
    expect(readBrowserWatches()).toEqual([]);
  });
});
