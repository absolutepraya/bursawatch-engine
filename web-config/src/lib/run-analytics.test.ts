import { describe, expect, it } from "vitest";
import { latestStockMoves, summarizeRuns } from "@/lib/run-analytics";
import type { EvidenceRecord, RunRecord } from "@/lib/types";

function run(startedAt: string, overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id: startedAt,
    automationId: "watch",
    automationName: "Banking watch",
    configVersion: 1,
    trigger: "schedule",
    startedAt,
    completedAt: startedAt,
    outcome: "no-change",
    evidenceMode: "sectors-live",
    conditionResult: "false",
    summary: "No change",
    ...overrides,
  };
}

describe("run insights", () => {
  const asOf = "2026-09-17T08:00:00.000Z";
  it("includes seven WIB calendar days through the snapshot, not future records", () => {
    const report = summarizeRuns(
      [
        run("2026-09-10T16:59:59.999Z"),
        run("2026-09-10T17:00:00.000Z"),
        run(asOf),
        run("2026-09-17T08:00:00.001Z"),
        run("invalid"),
      ],
      7,
      asOf,
    );
    expect(report.checks).toBe(2);
    expect(report.start).toBe("2026-09-10T17:00:00.000Z");
    expect(report.days[0]).toMatchObject({ date: "2026-09-11", count: 1 });
    expect(report.days[6]).toMatchObject({ date: "2026-09-17", count: 1 });
    expect(report.runs.map((r) => r.startedAt)).toEqual([asOf, "2026-09-10T17:00:00.000Z"]);
  });

  it("groups checks around WIB midnight by start time, not completion time", () => {
    const report = summarizeRuns(
      [
        run("2026-09-16T16:59:59Z", { completedAt: "2026-09-16T17:01:00Z" }),
        run("2026-09-16T17:00:00Z"),
      ],
      7,
      asOf,
    );
    expect(report.days[5]).toMatchObject({ date: "2026-09-16", count: 1 });
    expect(report.days[6]).toMatchObject({ date: "2026-09-17", count: 1 });
  });

  it("counts every outcome once and separates prepared briefs, issues and sample evidence", () => {
    const records = [
      run(asOf, { outcome: "prepared-preview", evidenceMode: "synthetic-demo" }),
      run(asOf),
      run(asOf, { outcome: "degraded" }),
      run(asOf, { outcome: "failed" }),
      run(asOf, { outcome: "running", completedAt: null }),
    ];
    const report = summarizeRuns(records, 7, asOf);
    expect(report).toMatchObject({
      checks: 5,
      prepared: 1,
      issues: 2,
      sampleCount: 1,
      liveCount: 4,
      recordedDays: 1,
    });
    expect(report.outcomes).toEqual({
      "prepared-preview": 1,
      "no-change": 1,
      degraded: 1,
      failed: 1,
      running: 1,
    });
    expect(report.days.reduce((sum, day) => sum + day.count, 0)).toBe(report.checks);
    expect(records[0].outcome).toBe("prepared-preview");
  });

  it("expands to thirty calendar days across a month boundary", () => {
    const records = [run("2026-08-18T17:00:00Z"), run("2026-08-18T16:59:59Z")];
    expect(summarizeRuns(records, 7, asOf).checks).toBe(0);
    const report = summarizeRuns(records, 30, asOf);
    expect(report.days).toHaveLength(30);
    expect(report.days[0]).toMatchObject({ date: "2026-08-19", count: 1 });
    expect(report.checks).toBe(1);
  });

  it("leaves missing days unrecorded without inventing successful no-change checks", () => {
    const report = summarizeRuns([], 7, asOf);
    expect(report).toMatchObject({
      checks: 0,
      prepared: 0,
      issues: 0,
      recordedDays: 0,
      sampleCount: 0,
    });
    expect(report.days.every((day) => day.count === 0 && day.outcomes["no-change"] === 0)).toBe(
      true,
    );
  });

  it("rejects an invalid reporting clock", () => {
    expect(() => summarizeRuns([], 7, "invalid")).toThrow("valid reporting time");
  });
});

describe("stock evidence insights", () => {
  const item: EvidenceRecord = {
    id: "evidence-1",
    runId: "included",
    symbol: "BBRI",
    endpoint: "/v2/daily/BBRI/",
    metric: "daily_close_change",
    value: "3.60",
    unit: "%",
    marketAsOf: "2026-09-16",
    retrievedAt: "2026-09-17T08:00:00Z",
    origin: "synthetic-demo",
  };

  it("uses the latest market date per stock and ties each observation to included run evidence", () => {
    const records = [run("2026-09-17T08:00:00Z", { id: "included" })];
    const result = latestStockMoves(records, [
      { runId: "excluded", items: [{ ...item, marketAsOf: "2026-09-17", value: "99" }] },
      {
        runId: "included",
        items: [
          item,
          { ...item, id: "older", marketAsOf: "2026-09-15", value: "-2" },
          { ...item, id: "other", symbol: "TLKM", value: "-1.25" },
        ],
      },
    ]);
    expect(result.map((entry) => [entry.evidence.symbol, entry.change])).toEqual([
      ["BBRI", 3.6],
      ["TLKM", -1.25],
    ]);
    expect(result[0]).toMatchObject({
      runId: "included",
      evidence: { origin: "synthetic-demo", marketAsOf: "2026-09-16" },
    });
  });

  it("uses the latest retrieval for a repeated market date without inventing a return series", () => {
    const records = [run("2026-09-17T08:00:00Z", { id: "included" })];
    const result = latestStockMoves(records, [
      {
        runId: "included",
        items: [item, { ...item, retrievedAt: "2026-09-17T09:00:00Z", value: "3.5" }],
      },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0].change).toBe(3.5);
  });

  it("omits absent, malformed and unrelated metrics instead of treating them as flat prices", () => {
    const records = [run("2026-09-17T08:00:00Z", { id: "included" })];
    const malformed = [
      { ...item, value: "" },
      { ...item, value: "NaN" },
      { ...item, value: "Infinity" },
      { ...item, metric: "volume" },
      { ...item, unit: "IDR" },
      { ...item, marketAsOf: "unknown" },
    ];
    expect(latestStockMoves(records, [{ runId: "included", items: malformed }])).toEqual([]);
    expect(latestStockMoves([], [{ runId: "included", items: [item] }])).toEqual([]);
  });
});
