import type { ControlJob, ControlRun, ControlWatcher } from "@/server/control-plane";
import type { OperatorJob, OperatorObservation, OperatorComponentActivity } from "@/lib/operator-inventory";

export type ControlRange = "24h" | "7d";
export type ControlCoverageIssue = {
  watcherId: string;
  resource: "jobs" | "runs";
  message: string;
};

export const controlStatusLabels: Record<ControlRun["status"], string> = {
  ok: "Completed",
  degraded: "Degraded",
  failed: "Failed",
  blocked: "Blocked",
  running: "Running",
};

export const controlStatuses = ["ok", "degraded", "failed", "blocked", "running"] as const;
const HOUR = 3_600_000;
const DAY = HOUR * 24;
const WIB = HOUR * 7;

function emptyCounts(): Record<ControlRun["status"], number> {
  return { ok: 0, degraded: 0, failed: 0, blocked: 0, running: 0 };
}

function reportingTime(asOf: string) {
  const time = Date.parse(asOf);
  if (!Number.isFinite(time)) throw new Error("A valid reporting time is required.");
  return time;
}

/** Only returned records are counted. Empty buckets do not establish uptime. */
export function summarizeControlRuns(records: ControlRun[], range: ControlRange, asOf: string) {
  const end = reportingTime(asOf);
  const today = Math.floor((end + WIB) / DAY) * DAY - WIB;
  const start = range === "7d" ? today - DAY * 6 : end - DAY;
  const interval = range === "7d" ? DAY : HOUR;
  const bucketCount = range === "7d" ? 7 : 24;
  const buckets = Array.from({ length: bucketCount }, (_, index) => ({
    start: new Date(start + index * interval).toISOString(),
    end: new Date(Math.min(start + (index + 1) * interval, end)).toISOString(),
    count: 0,
    statuses: emptyCounts(),
  }));
  const seen = new Set<string>();
  const runs = records
    .filter((run) => {
      const time = Date.parse(run.started_at);
      if (!Number.isFinite(time) || time < start || time > end || seen.has(run.run_id))
        return false;
      seen.add(run.run_id);
      return true;
    })
    .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at));
  const statuses = emptyCounts();
  for (const run of runs) {
    const index = Math.min(
      bucketCount - 1,
      Math.floor((Date.parse(run.started_at) - start) / interval),
    );
    buckets[index].count += 1;
    buckets[index].statuses[run.status] += 1;
    statuses[run.status] += 1;
  }
  const maxCount = Math.max(0, ...buckets.map((bucket) => bucket.count));
  return {
    runs,
    buckets,
    statuses,
    total: runs.length,
    attention: statuses.degraded + statuses.failed + statuses.blocked,
    start: new Date(start).toISOString(),
    end: new Date(end).toISOString(),
    maxCount,
    // Keep the midpoint on a whole run; rounding only its label distorts the scale.
    chartCeiling: Math.max(2, Math.ceil(maxCount / 2) * 2),
  };
}

export function summarizeControlSchedules(jobs: ControlJob[]) {
  const result = { active: 0, paused: 0, pending: 0, error: 0, unverified: 0, total: jobs.length };
  for (const job of jobs) {
    const { schedule, reconciliation } = job;
    const applied = Boolean(
      schedule &&
      reconciliation.effective &&
      reconciliation.status === "applied" &&
      reconciliation.applied_revision === schedule.revision,
    );
    if (applied) {
      if (schedule?.enabled) result.active++;
      else result.paused++;
    } else if (reconciliation.status === "pending") result.pending++;
    else if (reconciliation.status === "error") result.error++;
    else result.unverified++;
  }
  return result;
}

export function latestControlRuns(watchers: ControlWatcher[], records: ControlRun[], asOf: string) {
  const end = reportingTime(asOf);
  const latest = new Map<string, ControlRun>();
  const known = new Set(watchers.map((watcher) => watcher.watcher_id));
  for (const run of records) {
    const time = Date.parse(run.started_at);
    if (!known.has(run.watcher_id) || !Number.isFinite(time) || time > end) continue;
    const previous = latest.get(run.watcher_id);
    if (!previous || time > Date.parse(previous.started_at)) latest.set(run.watcher_id, run);
  }
  return latest;
}

export function controlRunDuration(run: ControlRun): string {
  if (run.status === "running") return "In progress";
  if (!run.finished_at) return "Not recorded";
  const elapsed = Date.parse(run.finished_at) - Date.parse(run.started_at);
  if (!Number.isFinite(elapsed) || elapsed < 0) return "Not recorded";
  if (elapsed < 1000) return "<1s";
  const seconds = Math.floor(elapsed / 1000);
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

export type ObservedJobState = "active" | "paused" | "pending" | "error" | "mismatch" | "stale" | "unknown";

export function latestOperatorObservations(rows: OperatorObservation[]) {
  return new Map(rows.map((row) => [`${row.identity_kind}:${row.identity_id}`, row]));
}

export function observedJobState(job: OperatorJob, observation?: OperatorObservation): ObservedJobState {
  if (!observation) return job.reconciliation.status === "error" ? "error" : job.reconciliation.status === "pending" ? "pending" : "unknown";
  if (observation.freshness === "stale" || observation.status === "stale") return "stale";
  if (observation.comparison === "mismatch") return "mismatch";
  if (observation.status === "disabled") return "paused";
  if (observation.comparison === "match" && job.schedule && job.reconciliation.status === "applied"
    && job.reconciliation.applied_revision === job.schedule.revision) return "active";
  if (job.schedule_kind === "fixed" && observation.status === "enabled") return "active";
  return "unknown";
}

export function observedJobSummary(jobs: OperatorJob[], observations: OperatorObservation[]) {
  const byJob = latestOperatorObservations(observations);
  const counts: Record<ObservedJobState, number> = { active: 0, paused: 0, pending: 0, error: 0, mismatch: 0, stale: 0, unknown: 0 };
  for (const job of jobs) counts[observedJobState(job, byJob.get(`job:${job.job_id}`))]++;
  return { ...counts, total: jobs.length };
}

/** Current issues require a fresh enabled-job observation, never a historical run row. */
export function currentObservedFailures(jobs: OperatorJob[], observations: OperatorObservation[]) {
  const byJob = latestOperatorObservations(observations);
  return jobs.filter((job) => {
    const row = byJob.get(`job:${job.job_id}`);
    return row && observedJobState(job, row) === "active" && row.evidence.last_execution.status === "failed";
  });
}

export function latestActivityTimestamp(activity: OperatorComponentActivity[]) {
  const values = activity.flatMap((row) => [
    ...row.endpoints.map((endpoint) => endpoint.accepted_at),
    ...row.pipelines.map((pipeline) => pipeline.work_created_at),
  ]).filter((value): value is string => value !== null && Number.isFinite(Date.parse(value)));
  return values.sort((a, b) => Date.parse(b) - Date.parse(a))[0] ?? null;
}

export function ownerConfigEvidence(savedRevision: number | null, runs: ControlRun[]) {
  if (savedRevision === null) return { label: "No saved configuration", loadedRevision: null as number | null };
  const latest = [...runs].sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at))[0];
  if (!latest) return { label: "Saved, use unverified", loadedRevision: null as number | null };
  if (latest.config_revision === savedRevision) return { label: `Last run used saved v${savedRevision}`, loadedRevision: latest.config_revision };
  return { label: `Saved v${savedRevision}, use unverified; last run used v${latest.config_revision}`, loadedRevision: latest.config_revision };
}

export function isEffectiveSubscription(subscription: { enabled: boolean; verification_status: "verified" | "pending" }) {
  return subscription.enabled && subscription.verification_status === "verified";
}
