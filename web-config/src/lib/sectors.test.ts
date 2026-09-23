import { describe, expect, it, vi } from "vitest";

import { computePriceSignal, getDailyEvidence } from "@/lib/sectors";

describe("computePriceSignal", () => {
  it("sorts observations before calculating the daily move", () => {
    const signal = computePriceSignal([
      { symbol: "BBRI.JK", date: "2026-09-14", close: 104, volume: 1, market_cap: 1 },
      { symbol: "BBRI.JK", date: "2026-09-13", close: 100, volume: 1, market_cap: 1 },
    ]);

    expect(signal).toEqual({
      previousClose: 100,
      latestClose: 104,
      changePercent: 4,
      latestDate: "2026-09-14",
    });
  });

  it("rejects insufficient or invalid evidence", () => {
    expect(() => computePriceSignal([])).toThrow(/two daily observations/i);
    expect(() => computePriceSignal([
      { symbol: "BBRI.JK", date: "2026-09-13", close: 0, volume: 1, market_cap: 1 },
      { symbol: "BBRI.JK", date: "2026-09-14", close: 100, volume: 1, market_cap: 1 },
    ])).toThrow(/invalid closing price/i);
  });
});

describe("getDailyEvidence", () => {
  it("labels local fixture data as synthetic when no API key exists", async () => {
    const result = await getDailyEvidence("bbri.jk", { now: new Date("2026-09-14T08:30:00.000Z") });
    expect(result.symbol).toBe("BBRI");
    expect(result.origin).toBe("synthetic-demo");
    expect(result.endpoint).toBe("/v2/daily/BBRI/");
    expect(result.points).toHaveLength(5);
  });

  it("uses the official Sectors v2 authorization contract for live evidence", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify([
      { symbol: "BBRI.JK", date: "2026-09-13", close: 100, volume: 10, market_cap: 1000 },
      { symbol: "BBRI.JK", date: "2026-09-14", close: 102, volume: 12, market_cap: 1020 },
    ]), { status: 200, headers: { "content-type": "application/json" } }));

    const result = await getDailyEvidence("BBRI", {
      apiKey: "demo-key",
      baseUrl: "https://api.sectors.app/",
      fetchImpl,
      now: new Date("2026-09-14T08:31:00.000Z"),
    });

    expect(fetchImpl).toHaveBeenCalledWith(
      "https://api.sectors.app/v2/daily/BBRI/",
      expect.objectContaining({
        headers: { Authorization: "demo-key" },
        cache: "no-store",
      }),
    );
    expect(result.origin).toBe("sectors-live");
  });
});
