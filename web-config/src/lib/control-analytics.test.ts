import { describe, expect, it } from "vitest";
import {
  controlRunDuration,
  latestControlRuns,
  summarizeControlRuns,
  summarizeControlSchedules,
} from "@/lib/control-analytics";
import type { ControlJob, ControlRun, ControlWatcher } from "@/server/control-plane";

const asOf = "2026-09-20T09:15:00Z";
function run(started_at: string, overrides: Partial<ControlRun> = {}): ControlRun {
  return {
    run_id: started_at,
    watcher_id: "news",
    scheduler_job_id: "news-hourly",
    trigger: "schedule",
    config_revision: 2,
    started_at,
    finished_at: started_at,
    status: "ok",
    ...overrides,
  };
}
function job(overrides: Partial<ControlJob> = {}): ControlJob {
  return {
    job_id: "news-hourly",
    watcher_id: "news",
    display_name: "News check",
    schedule_kind: "interval",
    min_interval_seconds: 60,
    max_interval_seconds: 86400,
    schedule: {
      api_version: 1,
      job_id: "news-hourly",
      revision: 2,
      enabled: true,
      interval_seconds: 3600,
      timezone: "Asia/Jakarta",
      schedule_sha256: "a".repeat(64),
      updated_at: asOf,
    },
    reconciliation: { status: "applied", applied_revision: 2, effective: true },
    ...overrides,
  };
}

describe("operations run activity", () => {
  it("uses seven WIB calendar days and excludes future and malformed times", () => {
    const result = summarizeControlRuns(
      [
        run("2026-09-13T16:59:59Z"),
        run("2026-09-13T17:00:00Z"),
        run(asOf),
        run("2026-09-20T09:15:01Z"),
        run("invalid"),
      ],
      "7d",
      asOf,
    );
    expect(result.total).toBe(2);
    expect(result.start).toBe("2026-09-13T17:00:00.000Z");
    expect(result.buckets).toHaveLength(7);
    expect(result.buckets[0].count).toBe(1);
    expect(result.buckets[6].count).toBe(1);
    expect(result.runs[0].started_at).toBe(asOf);
  });

  it("buckets by start time across WIB midnight, irrespective of completion", () => {
    const result = summarizeControlRuns(
      [run("2026-09-19T16:59:59Z", { finished_at: asOf }), run("2026-09-19T17:00:00Z")],
      "7d",
      asOf,
    );
    expect(result.buckets[5].count).toBe(1);
    expect(result.buckets[6].count).toBe(1);
  });

  it("uses the trailing 24 hours and includes the snapshot endpoint exactly once", () => {
    const result = summarizeControlRuns(
      [
        run("2026-09-19T09:14:59Z"),
        run("2026-09-19T09:15:00Z"),
        run("2026-09-19T10:15:00Z"),
        run(asOf),
        run(asOf),
      ],
      "24h",
      asOf,
    );
    expect(result.total).toBe(3);
    expect(result.buckets).toHaveLength(24);
    expect(result.buckets[0].count).toBe(1);
    expect(result.buckets[1].count).toBe(1);
    expect(result.buckets[23].count).toBe(1);
  });

  it("counts each actual outcome and leaves absent activity unrecorded", () => {
    const statuses = ["ok", "degraded", "failed", "blocked", "running"] as const;
    const records = statuses.map((status) => run(asOf, { status, run_id: status }));
    const result = summarizeControlRuns(records, "7d", asOf);
    expect(result.statuses).toEqual({ ok: 1, degraded: 1, failed: 1, blocked: 1, running: 1 });
    expect(result.attention).toBe(3);
    expect(result.buckets.slice(0, 6).every((bucket) => bucket.count === 0)).toBe(true);
    expect(records[0].run_id).toBe("ok");
    expect(summarizeControlRuns([], "24h", asOf).total).toBe(0);
    expect(() => summarizeControlRuns([], "7d", "invalid")).toThrow("valid reporting time");
  });

  it("keeps chart ticks on an accurate whole-run scale for odd bucket totals", () => {
    const result = summarizeControlRuns(
      Array.from({ length: 5 }, (_, index) => run(asOf, { run_id: `run-${index}` })),
      "7d",
      asOf,
    );
    expect(result.maxCount).toBe(5);
    expect(result.chartCeiling).toBe(6);
    expect(result.chartCeiling / 2).toBe(3);
    expect(summarizeControlRuns([], "7d", asOf).maxCount).toBe(0);
    expect(summarizeControlRuns([], "7d", asOf).chartCeiling).toBe(2);
  });

  it("bounds every bucket at the snapshot even at WIB midnight and a year boundary", () => {
    const midnight = "2026-12-31T17:00:00Z";
    const result = summarizeControlRuns(
      [run("2026-12-25T17:00:00Z"), run("2026-12-31T16:59:59Z"), run(midnight)],
      "7d",
      midnight,
    );
    expect(result.start).toBe("2026-12-25T17:00:00.000Z");
    expect(result.buckets.map((bucket) => bucket.count)).toEqual([1, 0, 0, 0, 0, 1, 1]);
    expect(result.buckets.at(-1)?.start).toBe(result.end);
    expect(result.buckets.at(-1)?.end).toBe(result.end);
    expect(result.buckets.every((bucket) => Date.parse(bucket.end) <= Date.parse(midnight))).toBe(
      true,
    );
  });
});

describe("schedule reconciliation summary", () => {
  it("requires a matching applied revision before calling a schedule active or paused", () => {
    const enabled = job();
    expect(
      summarizeControlSchedules([
        enabled,
        job({ schedule: { ...enabled.schedule!, enabled: false } }),
        job({ reconciliation: { status: "applied", applied_revision: 1, effective: true } }),
        job({ reconciliation: { status: "pending", applied_revision: 1, effective: false } }),
        job({ reconciliation: { status: "error", applied_revision: null, effective: false } }),
        job({
          schedule: null,
          reconciliation: { status: "not_connected", applied_revision: null, effective: false },
        }),
      ]),
    ).toEqual({ active: 1, paused: 1, pending: 1, error: 1, unverified: 2, total: 6 });
  });
});

describe("latest watcher run", () => {
  const watchers: ControlWatcher[] = [
    { watcher_id: "news", display_name: "News", current_revision: 2, updated_at: asOf },
  ];
  it("ignores unknown sources, malformed and future runs, and keeps latest evidence", () => {
    const newest = run(asOf, { status: "failed" });
    const result = latestControlRuns(
      watchers,
      [
        newest,
        run("2026-09-19T09:00:00Z"),
        run("invalid"),
        run("2026-09-21T09:00:00Z"),
        run(asOf, { watcher_id: "unknown" }),
      ],
      asOf,
    );
    expect([...result.keys()]).toEqual(["news"]);
    expect(result.get("news")).toBe(newest);
    expect(latestControlRuns(watchers, [], asOf).size).toBe(0);
    expect(() => latestControlRuns(watchers, [newest], "invalid")).toThrow("valid reporting time");
  });

  it("does not invent duration for running, missing or invalid completion times", () => {
    expect(controlRunDuration(run(asOf, { status: "running", finished_at: null }))).toBe(
      "In progress",
    );
    expect(controlRunDuration(run(asOf, { finished_at: null }))).toBe("Not recorded");
    expect(controlRunDuration(run(asOf, { finished_at: "2026-09-20T09:14:00Z" }))).toBe(
      "Not recorded",
    );
    expect(controlRunDuration(run(asOf, { finished_at: "2026-09-20T09:16:12Z" }))).toBe("1m 12s");
    expect(controlRunDuration(run(asOf, { finished_at: "2026-09-20T10:30:00Z" }))).toBe("1h 15m");
  });
});
