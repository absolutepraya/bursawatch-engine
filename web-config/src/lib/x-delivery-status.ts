import type { ControlJob, ControlRun } from "@/server/control-plane";

export const xWatcherId = "bursawatch-x-account-watch";
export const xSourceJobId = "bursawatch-x-account-watch-source";

/** A source run and a queue run are different evidence. Neither confirms an
 * individual profile was fetched or a Discord message was delivered. */
export function xDeliveryStatus(revision: number, jobs: ControlJob[], runs: ControlRun[]) {
  const job = jobs.find((row) => row.watcher_id === xWatcherId && row.job_id === xSourceJobId);
  const verifiedSchedule = Boolean(job?.schedule && job.reconciliation.effective &&
    job.reconciliation.status === "applied" && job.reconciliation.applied_revision === job.schedule.revision);
  const sourceRuns = runs.filter((row) => row.watcher_id === xWatcherId &&
    row.trigger === "scheduled" && [xSourceJobId, "x-post-source"].includes(row.scheduler_job_id ?? ""))
    .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at));
  const latestSourceRun = sourceRuns[0] ?? null;
  return {
    job,
    schedule: !verifiedSchedule ? "unverified" as const : job?.schedule?.enabled ? "active" as const : "paused" as const,
    latestSourceRun,
    revisionObserved: Boolean(latestSourceRun && latestSourceRun.config_revision === revision),
  };
}
