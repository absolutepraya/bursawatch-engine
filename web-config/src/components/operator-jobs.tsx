"use client";

import { useEffect, useMemo, useState } from "react";
import { ScheduleEditor } from "@/components/schedule-editor";
import Link from "next/link";
import { observedJobState, latestOperatorObservations } from "@/lib/control-analytics";
import type { OperatorComponent, OperatorJob, OperatorObservation } from "@/lib/operator-inventory";
import type { ControlJob, ScheduleInput } from "@/server/control-plane";

type Requester = <T>(
  path: string,
  payload?: unknown,
  options?: { signal?: AbortSignal; method?: "POST" },
) => Promise<T>;

const stateLabel: Record<ReturnType<typeof observedJobState>, string> = {
  active: "Observed active",
  paused: "Observed paused",
  pending: "Pending reconciliation",
  error: "Reconciliation error",
  mismatch: "Observed schedule mismatch",
  stale: "Stale observation",
  unknown: "Unknown",
};

export function OperatorJobs({
  jobs: initialJobs,
  components,
  observations,
  request,
  onDirtyChange,
  unavailable = false,
}: {
  jobs: OperatorJob[];
  components: OperatorComponent[];
  observations: OperatorObservation[];
  request: Requester;
  onDirtyChange: (dirty: boolean) => void;
  unavailable?: boolean;
}) {
  const [jobs, setJobs] = useState(initialJobs);
  const [dirtyRows, setDirtyRows] = useState<string[]>([]);
  const byComponent = useMemo(
    () => new Map(components.map((item) => [item.component_id, item])),
    [components],
  );
  const byObservation = useMemo(() => latestOperatorObservations(observations), [observations]);
  const controlJobs = useMemo(
    () => new Map(jobs.map((item) => [item.job_id, toControlJob(item)])),
    [jobs],
  );
  useEffect(() => onDirtyChange(dirtyRows.length > 0), [dirtyRows, onDirtyChange]);

  const updateDirty = (jobId: string, dirty: boolean) => {
    setDirtyRows((previous) => {
      if (dirty) return previous.includes(jobId) ? previous : [...previous, jobId];
      return previous.includes(jobId) ? previous.filter((item) => item !== jobId) : previous;
    });
  };
  const replaceSchedule = (jobId: string, result: ControlJob) => {
    setJobs((current) =>
      current.map((item) =>
        item.job_id === jobId
          ? {
              ...item,
              schedule: result.schedule,
              reconciliation: { ...item.reconciliation, ...result.reconciliation },
            }
          : item,
      ),
    );
    setDirtyRows((previous) => previous.filter((item) => item !== jobId));
    return result;
  };

  return (
    <>
      <div className="control-page-heading">
        <h1>Jobs</h1>
        <p>Declared jobs, schedule intent and current Hermes observations.</p>
      </div>
      {jobs.length ? (
        <ol className="operator-job-list">
          {jobs.map((job) => {
            const observation = byObservation.get(`job:${job.job_id}`);
            const state = observedJobState(job, observation);
            const related = job.component_ids
              .map((id) => byComponent.get(id))
              .filter((value): value is OperatorComponent => Boolean(value));
            const affected = related.filter(
              (item) => item.kind === "source_adapter" || item.kind === "domain_owner",
            );
            const lastExecution = observation?.evidence.last_execution;
            return (
              <li key={job.job_id} className="operator-job-card">
                <section aria-labelledby={`operator-job-${slug(job.job_id)}`}>
                  <div className="operator-job-heading">
                    <div>
                      <h2 id={`operator-job-${slug(job.job_id)}`}>{job.display_name}</h2>
                      <p>{job.runtime_job_key}</p>
                    </div>
                    <span className={`operator-job-state operator-job-state-${state}`}>
                      {stateLabel[state]}
                    </span>
                  </div>
                  <dl className="operator-job-evidence">
                    <div>
                      <dt>Desired</dt>
                      <dd>
                        {job.schedule
                          ? `${job.schedule.enabled ? "Enabled" : "Paused"} · every ${job.schedule.interval_seconds / 60} minutes · revision ${job.schedule.revision}`
                          : "No desired interval"}
                      </dd>
                    </div>
                    <div>
                      <dt>Applied</dt>
                      <dd>{appliedScheduleLabel(job)}</dd>
                    </div>
                    <div>
                      <dt>Observed</dt>
                      <dd>
                        {observation
                          ? `${observation.evidence.enabled ? "Enabled" : "Paused"} · ${formatObservedSchedule(observation)} · ${formatTime(observation.observed_at)} WIB`
                          : "No observation"}
                      </dd>
                    </div>
                    <div>
                      <dt>Last execution</dt>
                      <dd>
                        {lastExecution?.at
                          ? `${lastExecution.status ?? "Status unavailable"} · ${formatTime(lastExecution.at)} WIB`
                          : "Not reported"}
                      </dd>
                    </div>
                    <div>
                      <dt>Components</dt>
                      <dd>
                        {related.length ? (
                          <ul className="operator-job-components">
                            {related.map((item) => {
                              const href =
                                item.kind === "source_adapter"
                                  ? "/workspace/sources"
                                  : item.kind === "domain_owner" && item.config_resource_ids[0]
                                    ? `/workspace/workflows?watcher=${encodeURIComponent(item.config_resource_ids[0])}`
                                    : null;
                              return (
                                <li key={item.component_id}>
                                  {href ? (
                                    <Link href={href}>{item.display_name}</Link>
                                  ) : (
                                    item.display_name
                                  )}
                                </li>
                              );
                            })}
                          </ul>
                        ) : (
                          "No component relationship reported"
                        )}
                      </dd>
                    </div>
                  </dl>
                  {job.schedule_kind === "fixed" ? (
                    <p className="operator-job-readonly">
                      Fixed system schedule. It can be reviewed here but not changed.
                    </p>
                  ) : null}
                  {job.schedule_kind === "interval" && job.can_edit && job.schedule ? (
                    <>
                      {affected.length > 1 ? (
                        <p className="operator-job-impact">
                          <strong>Shared job impact:</strong> changing this schedule affects{" "}
                          {affected.map((item) => item.display_name).join(", ")}.
                        </p>
                      ) : null}
                      <ScheduleEditor
                        job={controlJobs.get(job.job_id)!}
                        onDirtyChange={(dirty) => updateDirty(job.job_id, dirty)}
                        onSave={async (input: ScheduleInput) =>
                          replaceSchedule(
                            job.job_id,
                            await request<ControlJob>(
                              `jobs/${encodeURIComponent(job.job_id)}/schedule`,
                              { ...input, expectedRevision: job.schedule?.revision },
                            ),
                          )
                        }
                        onRefresh={async () =>
                          replaceSchedule(
                            job.job_id,
                            await request<ControlJob>(
                              `jobs/${encodeURIComponent(job.job_id)}/schedule`,
                            ),
                          )
                        }
                      />
                    </>
                  ) : null}
                  {job.schedule_kind === "interval" && !job.can_edit ? (
                    <p className="operator-job-readonly">
                      You have view access. An administrator can change this schedule.
                    </p>
                  ) : null}
                  {job.schedule_kind === "interval" && job.can_edit && !job.schedule ? (
                    <p className="operator-job-readonly">
                      No desired schedule is configured, so controls are unavailable.
                    </p>
                  ) : null}
                </section>
              </li>
            );
          })}
        </ol>
      ) : (
        <div className="control-empty">
          {unavailable
            ? "Job inventory could not be loaded. Refresh the workspace to try again."
            : "No declared jobs were returned."}
        </div>
      )}
    </>
  );
}

function toControlJob(job: OperatorJob): ControlJob {
  return {
    job_id: job.job_id,
    watcher_id: job.watcher_id ?? "global-job",
    display_name: job.display_name,
    schedule_kind: job.schedule_kind,
    min_interval_seconds: job.min_interval_seconds,
    max_interval_seconds: job.max_interval_seconds,
    schedule: job.schedule,
    reconciliation: {
      status: job.reconciliation.status,
      applied_revision: job.reconciliation.applied_revision,
      effective: job.reconciliation.effective,
    },
  };
}

function formatObservedSchedule(observation: OperatorObservation): string {
  const schedule = observation.evidence.schedule;
  return schedule.kind === "interval"
    ? `every ${schedule.minutes} minutes`
    : `cron ${schedule.expr}`;
}

function appliedScheduleLabel(job: OperatorJob): string {
  if (job.schedule_kind === "fixed") return "Fixed system schedule";
  const matches = Boolean(
    job.schedule &&
    job.reconciliation.effective &&
    job.reconciliation.applied_revision === job.schedule.revision,
  );
  if (!matches)
    return `No matching applied revision · ${job.reconciliation.status.replaceAll("_", " ")}`;
  return `${job.schedule!.enabled ? "Enabled" : "Paused"} · every ${job.schedule!.interval_seconds / 60} minutes · revision ${job.schedule!.revision}`;
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Jakarta",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function slug(value: string) {
  return value.replace(/[^a-z0-9_-]/gi, "-");
}
