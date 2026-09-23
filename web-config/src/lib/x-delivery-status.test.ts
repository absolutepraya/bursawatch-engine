import { describe, expect, it } from "vitest";
import type { ControlJob, ControlRun } from "@/server/control-plane";
import { xDeliveryStatus, xSourceJobId, xWatcherId } from "./x-delivery-status";
const run = (overrides: Partial<ControlRun> = {}): ControlRun => ({ run_id: "synthetic-run", watcher_id: xWatcherId, scheduler_job_id: xSourceJobId, trigger: "scheduled", config_revision: 3, started_at: "2026-09-22T00:00:00Z", finished_at: "2026-09-22T00:00:01Z", status: "ok", ...overrides });
const job = (enabled = true): ControlJob => ({ job_id: xSourceJobId, watcher_id: xWatcherId, display_name: "Source poller", schedule_kind: "interval", min_interval_seconds: 600, max_interval_seconds: 86400, schedule: { api_version: 1, job_id: xSourceJobId, revision: 1, enabled, interval_seconds: 600, timezone: "Asia/Jakarta", schedule_sha256: "a".repeat(64), updated_at: "2026-09-22T00:00:00Z" }, reconciliation: { effective: true, status: "applied", applied_revision: 1 } });
describe("X delivery evidence", () => {
  it("recognizes the source wrapper's runtime job key but not agent submissions", () => {
    expect(xDeliveryStatus(3, [], [run({ scheduler_job_id: "x-post-source" })]).revisionObserved).toBe(true);
    expect(xDeliveryStatus(3, [], [run({ scheduler_job_id: "x-post-source", trigger: "agent_submission" })]).latestSourceRun).toBeNull();
  });
  it("does not count queue runs as source checks", () => {
    expect(xDeliveryStatus(3, [], [run({ trigger: "queue", scheduler_job_id: "bursawatch-x-account-watch-queue-worker" })]).latestSourceRun).toBeNull();
  });
  it("does not claim a saved revision was consumed by an older run", () => {
    expect(xDeliveryStatus(4, [], [run()]).revisionObserved).toBe(false);
    expect(xDeliveryStatus(3, [], [run()]).revisionObserved).toBe(true);
  });
  it("requires matching schedule reconciliation", () => {
    const value = job(); value.reconciliation.applied_revision = 2;
    expect(xDeliveryStatus(3, [value], []).schedule).toBe("unverified");
    expect(xDeliveryStatus(3, [job()], []).schedule).toBe("active");
    expect(xDeliveryStatus(3, [job(false)], []).schedule).toBe("paused");
  });
  it("keeps the latest failed source check visible", () => {
    expect(xDeliveryStatus(3, [], [run(), run({ run_id: "new", status: "failed", started_at: "2026-09-22T01:00:00Z" })]).latestSourceRun?.status).toBe("failed");
  });
});
