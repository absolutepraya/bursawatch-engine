"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  Clock3,
  RefreshCw,
  ShieldAlert,
  TriangleAlert,
  XCircle,
} from "lucide-react";
import type { ControlJob, ControlRun, ControlWatcher } from "@/server/control-plane";
import type {
  OperatorComponent,
  OperatorComponentActivity,
  OperatorJob,
  OperatorObservation,
} from "@/lib/operator-inventory";
import {
  controlRunDuration,
  controlStatusLabels,
  controlStatuses,
  latestControlRuns,
  ownerConfigEvidence,
  summarizeControlRuns,
  summarizeControlSchedules,
  currentObservedFailures,
  latestOperatorObservations,
  observedJobState,
  observedJobSummary,
  type ControlCoverageIssue,
  type ControlRange,
} from "@/lib/control-analytics";
import "@/app/control-dashboard.css";

const number = new Intl.NumberFormat("en-GB");
const dayFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Jakarta",
  day: "numeric",
  month: "short",
});
const timeFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Jakarta",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const fullFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Jakarta",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function formatTime(value: string, kind: "day" | "time" | "full" = "full") {
  const date = new Date(value);
  if (!Number.isFinite(date.valueOf())) return "Time unavailable";
  const format = kind === "day" ? dayFormat : kind === "time" ? timeFormat : fullFormat;
  return format.format(date);
}

const statusIcons = {
  ok: CheckCircle2,
  degraded: TriangleAlert,
  failed: XCircle,
  blocked: ShieldAlert,
  running: Activity,
};

export function ControlRunStatus({
  status,
  sampleMode = false,
}: {
  status: ControlRun["status"];
  sampleMode?: boolean;
}) {
  const Icon = statusIcons[status];
  return (
    <span className={`control-status control-status-${status}`}>
      <Icon size={14} aria-hidden="true" />
      {sampleMode
        ? `Example ${controlStatusLabels[status].toLowerCase()}`
        : controlStatusLabels[status]}
    </span>
  );
}

export type ControlDashboardProps = {
  watchers: ControlWatcher[];
  jobs: ControlJob[];
  runs: ControlRun[];
  updatedAt: string;
  refreshing: boolean;
  onRefresh: () => void;
  onSelectWatcher: (watcherId: string) => void;
  onSelectRun: (runId: string) => void;
  issues?: ControlCoverageIssue[];
  components?: OperatorComponent[];
  componentActivity?: OperatorComponentActivity[];
  operatorJobs?: OperatorJob[];
  observations?: OperatorObservation[];
  operatorIssues?: { resource: string; message: string }[];
  basePath?: string;
  sampleMode?: boolean;
};

export function ControlDashboard({
  watchers,
  jobs,
  runs,
  updatedAt,
  onRefresh,
  refreshing,
  onSelectWatcher,
  onSelectRun,
  issues = [],
  components = [],
  componentActivity = [],
  operatorJobs = [],
  observations = [],
  operatorIssues = [],
  basePath = "/workspace",
  sampleMode = false,
}: ControlDashboardProps) {
  const [range, setRange] = useState<ControlRange>("7d");
  const report = useMemo(
    () => summarizeControlRuns(runs, range, updatedAt),
    [runs, range, updatedAt],
  );
  const schedules = useMemo(() => summarizeControlSchedules(jobs), [jobs]);
  const observedJobs = useMemo(
    () => observedJobSummary(operatorJobs, observations),
    [operatorJobs, observations],
  );
  const observationById = useMemo(() => latestOperatorObservations(observations), [observations]);
  const currentFailures = useMemo(
    () => currentObservedFailures(operatorJobs, observations),
    [operatorJobs, observations],
  );
  const operatorJobsUnavailable = operatorIssues.some(
    (issue) => issue.resource === "operator-jobs" || issue.resource === "observations",
  );
  const scheduleSegments = [
    { label: "Active", count: schedules.active, tone: "ok" },
    { label: "Paused", count: schedules.paused, tone: "muted" },
    { label: "Pending", count: schedules.pending, tone: "degraded" },
    { label: "Needs attention", count: schedules.error, tone: "failed" },
    { label: "Unverified", count: schedules.unverified, tone: "unverified" },
  ];

  return (
    <div className="control-overview">
      <header className="control-overview-heading">
        <div>
          <h1>Overview</h1>
          <p>
            {sampleMode
              ? "Sample watchers, schedules and example activity."
              : "Your watchers, schedules and latest activity."}
          </p>
        </div>
        <div className="control-refresh">
          <span>
            {sampleMode ? (
              "Synthetic examples"
            ) : (
              <>
                Updated <time dateTime={updatedAt}>{formatTime(updatedAt)} WIB</time>
              </>
            )}
          </span>
          <button
            className="button secondary"
            onClick={onRefresh}
            disabled={refreshing}
            aria-busy={refreshing}
          >
            <RefreshCw size={16} aria-hidden="true" />
            {refreshing ? "Refreshing…" : sampleMode ? "Reload examples" : "Refresh"}
          </button>
        </div>
      </header>

      {issues.length > 0 && (
        <div className="control-coverage-notice" role="status">
          <TriangleAlert size={18} aria-hidden="true" />
          <div>
            <strong>Some records could not be loaded.</strong>
            <p>Totals reflect the available records. Refresh to try again.</p>
          </div>
        </div>
      )}

      <section className="control-metrics" aria-label="Workspace summary">
        <div className="control-metric">
          <span>Watchers</span>
          <strong>{number.format(watchers.length)}</strong>
          <small>
            {number.format(watchers.filter((watcher) => watcher.current_revision !== null).length)}{" "}
            {sampleMode ? "with example configuration" : "with saved configuration"}
          </small>
        </div>
        <div className="control-metric">
          <span>{sampleMode ? "Sample run records" : "Recorded runs"}</span>
          <strong>{number.format(report.total)}</strong>
          <small>{range === "7d" ? "Last 7 calendar days" : "Last 24 hours"} · WIB</small>
        </div>
        <div className={`control-metric${report.attention ? " control-metric-attention" : ""}`}>
          <span>
            {sampleMode ? "Sample runs needing attention" : "Historical runs needing attention"}
          </span>
          <strong>{number.format(report.attention)}</strong>
          <small>
            {range === "7d" ? "Last 7 calendar days" : "Last 24 hours"}, not a current incident
            count
          </small>
        </div>
        <div className="control-metric">
          <span>{sampleMode ? "Sample job records" : "Observed active jobs"}</span>
          <strong>
            {sampleMode
              ? number.format(operatorJobs.length)
              : operatorJobsUnavailable
                ? "Unavailable"
                : number.format(observedJobs.active)}
            {!sampleMode && !operatorJobsUnavailable ? (
              <span> / {number.format(observedJobs.total)}</span>
            ) : null}
          </strong>
          <small>
            {sampleMode
              ? "Example records only, with no live job status"
              : `${number.format(observedJobs.stale)} stale · ${number.format(observedJobs.unknown)} unknown · ${number.format(currentFailures.length)} fresh failed executions`}
          </small>
        </div>
      </section>

      <OperatorEvidencePanel
        components={components}
        activity={componentActivity}
        jobs={operatorJobs}
        observations={observationById}
        issues={operatorIssues}
        sampleMode={sampleMode}
      />

      <div className="control-chart-grid">
        <section
          className="control-panel control-activity-panel"
          aria-labelledby="control-activity-title"
        >
          <div className="control-section-heading">
            <div>
              <h2 id="control-activity-title">
                {sampleMode ? "Sample run activity" : "Run activity"}
              </h2>
              <p>{sampleMode ? "Example records over time" : "Recorded outcomes over time"}</p>
            </div>
            <fieldset className="control-range">
              <legend className="sr-only">Activity date range</legend>
              {(["24h", "7d"] as const).map((value) => (
                <label key={value}>
                  <input
                    type="radio"
                    name="control-activity-range"
                    value={value}
                    checked={range === value}
                    onChange={() => setRange(value)}
                  />
                  <span>{value === "24h" ? "24 hours" : "7 days"}</span>
                </label>
              ))}
            </fieldset>
          </div>
          <div className="control-chart-summary">
            <strong>{number.format(report.total)}</strong>
            <span>
              {sampleMode ? "sample run records" : "recorded runs"}
              <span className="control-chart-period">
                {formatTime(report.start)} – {formatTime(report.end)} WIB
              </span>
            </span>
          </div>
          <p className="control-chart-coverage">
            {sampleMode
              ? "Synthetic example records only. This view does not check real runs."
              : "Up to 50 latest runs per watcher. This range may be incomplete."}
          </p>

          {report.total === 0 ? (
            <div className="control-chart-empty">
              <Activity size={25} strokeWidth={1.5} aria-hidden="true" />
              <strong>No runs recorded in this range</strong>
              <span>
                {issues.some((issue) => issue.resource === "runs")
                  ? "Some run history is unavailable. Try refreshing."
                  : "Returned run history has no records for these dates."}
              </span>
            </div>
          ) : (
            <div
              className={`control-chart control-chart-${range}`}
              role="img"
              aria-label={`${sampleMode ? `${report.total} sample run records` : `${report.total} recorded runs`}. ${controlStatuses.map((status) => `${report.statuses[status]} ${controlStatusLabels[status].toLowerCase()}`).join(", ")}. Full values are available in the activity table below.`}
            >
              <div className="control-chart-axis" aria-hidden="true">
                <span>{number.format(report.chartCeiling)}</span>
                <span>{number.format(report.chartCeiling / 2)}</span>
                <span>0</span>
              </div>
              <div className="control-chart-body" aria-hidden="true">
                <div className="control-chart-guide" />
                <div className="control-chart-guide control-chart-guide-middle" />
                <div className="control-chart-columns">
                  {report.buckets.map((bucket) => (
                    <div
                      className="control-chart-column"
                      key={bucket.start}
                      title={`${formatTime(bucket.start)} – ${formatTime(bucket.end)} WIB: ${bucket.count} ${sampleMode ? "sample run records" : "recorded runs"}`}
                    >
                      {bucket.count > 0 ? (
                        <div
                          className="control-chart-stack"
                          style={{ height: `${(bucket.count / report.chartCeiling) * 100}%` }}
                        >
                          {controlStatuses.map(
                            (status) =>
                              bucket.statuses[status] > 0 && (
                                <span
                                  className={`control-chart-segment control-fill-${status}`}
                                  key={status}
                                  style={{ flexGrow: bucket.statuses[status] }}
                                />
                              ),
                          )}
                        </div>
                      ) : (
                        <span className="control-chart-zero" />
                      )}
                    </div>
                  ))}
                </div>
              </div>
              <div className="control-chart-labels" aria-hidden="true">
                {range === "7d" ? (
                  report.buckets.map((bucket) => (
                    <span key={bucket.start}>{formatTime(bucket.start, "day")}</span>
                  ))
                ) : (
                  <>
                    <span>{formatTime(report.start, "time")}</span>
                    <span>{formatTime(report.buckets[12].start, "time")}</span>
                    <span>{formatTime(report.end, "time")}</span>
                  </>
                )}
              </div>
            </div>
          )}

          <ul className="control-chart-legend" aria-label="Run outcomes">
            {controlStatuses.map((status) => (
              <li key={status}>
                <span className={`control-legend-mark control-fill-${status}`} aria-hidden="true" />
                <span>{controlStatusLabels[status]}</span>
                <strong>{number.format(report.statuses[status])}</strong>
              </li>
            ))}
          </ul>
          <details className="control-chart-table">
            <summary>
              View activity table
              <ChevronRight size={14} aria-hidden="true" />
            </summary>
            <table>
              <caption>
                {sampleMode
                  ? "Synthetic sample records by start time, in WIB. They do not represent real runs."
                  : `Returned runs by start time, in WIB. ${range === "7d" ? "Today is a partial day. " : ""}Empty intervals do not establish that a check ran.`}
              </caption>
              <thead>
                <tr>
                  <th scope="col">{range === "7d" ? "Day" : "Hour starting"}</th>
                  <th scope="col">Runs</th>
                  <th scope="col">Outcomes</th>
                </tr>
              </thead>
              <tbody>
                {report.buckets.map((bucket) => (
                  <tr key={bucket.start}>
                    <th scope="row">
                      <time dateTime={bucket.start}>
                        {formatTime(bucket.start, range === "7d" ? "day" : "full")}
                      </time>
                    </th>
                    <td>{bucket.count}</td>
                    <td>
                      {bucket.count
                        ? controlStatuses
                            .filter((status) => bucket.statuses[status] > 0)
                            .map(
                              (status) =>
                                `${bucket.statuses[status]} ${controlStatusLabels[status].toLowerCase()}`,
                            )
                            .join(", ")
                        : "No records"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </section>

        <section
          className="control-panel control-schedule-panel"
          aria-labelledby="control-schedules-title"
        >
          <div className="control-section-heading">
            <div>
              <h2 id="control-schedules-title">
                {sampleMode ? "Sample schedule records" : "Schedule status"}
              </h2>
              <p>
                {sampleMode
                  ? "Example records only, with no current scheduler status."
                  : "Legacy watcher schedule reconciliation, not live registry proof"}
              </p>
            </div>
            <Clock3 size={19} aria-hidden="true" />
          </div>
          {sampleMode ? (
            <div className="control-schedule-total">
              <strong>{number.format(operatorJobs.length)}</strong>
              <span>example job records</span>
            </div>
          ) : (
            <>
              <div className="control-schedule-total">
                <strong>{number.format(schedules.active)}</strong>
                <span>active {schedules.active === 1 ? "schedule" : "schedules"}</span>
              </div>
              <div className="control-schedule-bar" aria-hidden="true">
                {scheduleSegments
                  .filter((segment) => segment.count > 0)
                  .map((segment) => (
                    <span
                      className={`control-fill-${segment.tone}`}
                      style={{ flexGrow: segment.count }}
                      key={segment.label}
                    />
                  ))}
              </div>
              <dl className="control-schedule-breakdown">
                {scheduleSegments.map((segment) => (
                  <div key={segment.label}>
                    <dt>
                      <span
                        className={`control-legend-mark control-fill-${segment.tone}`}
                        aria-hidden="true"
                      />
                      {segment.label}
                    </dt>
                    <dd>{number.format(segment.count)}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
          <p className="control-panel-note">
            {sampleMode
              ? "These records do not represent live jobs or scheduler state."
              : schedules.pending > 0
                ? "Saved changes stay pending until the scheduler confirms them."
                : schedules.total === 0
                  ? "No schedule records are available yet."
                  : "Active means the enabled schedule matches its applied revision."}
          </p>
        </section>
      </div>

      <section
        className="control-panel control-watchers-panel"
        aria-labelledby="control-watchers-title"
      >
        <div className="control-section-heading">
          <div>
            <h2 id="control-watchers-title">
              {sampleMode ? "Sample workflows" : "Watcher status"}
            </h2>
            <p>
              {sampleMode
                ? "Example configuration and history records."
                : "Latest recorded run for each watcher"}
            </p>
          </div>
          <span className="control-section-count">
            {number.format(watchers.length)} {watchers.length === 1 ? "watcher" : "watchers"}
          </span>
        </div>
        <ControlWatcherList
          watchers={watchers}
          runs={runs}
          jobs={jobs}
          updatedAt={updatedAt}
          onSelectWatcher={onSelectWatcher}
          issues={issues}
          components={components}
          operatorJobs={operatorJobs}
          observations={observations}
          operatorIssues={operatorIssues}
          basePath={basePath}
          sampleMode={sampleMode}
        />
      </section>

      <section
        className="control-panel control-recent-panel"
        aria-labelledby="control-recent-title"
      >
        <div className="control-section-heading">
          <div>
            <h2 id="control-recent-title">{sampleMode ? "Sample activity" : "Recent activity"}</h2>
            <p>
              {sampleMode
                ? "Open an example record to inspect its synthetic events."
                : "Open a run to inspect its recorded events"}
            </p>
          </div>
          <Activity size={19} aria-hidden="true" />
        </div>
        <ControlRunList
          runs={report.runs}
          watchers={watchers}
          onSelectRun={onSelectRun}
          limit={6}
          emptyMessage="No run records in the selected range."
          sampleMode={sampleMode}
        />
      </section>
      <p className="control-data-note">
        {sampleMode
          ? "These synthetic examples do not represent a real run, message delivery or current system state."
          : "A completed run does not confirm message delivery. Run samples are bounded history; gaps do not establish uptime."}
      </p>
    </div>
  );
}

function OperatorEvidencePanel({
  components,
  activity,
  jobs,
  observations,
  issues,
  sampleMode = false,
}: {
  components: OperatorComponent[];
  activity: OperatorComponentActivity[];
  jobs: OperatorJob[];
  observations: Map<string, OperatorObservation>;
  issues: { resource: string; message: string }[];
  sampleMode?: boolean;
}) {
  const activityById = new Map(activity.map((row) => [row.component_id, row]));
  const states: Record<string, string> = {
    active: "Observed active",
    paused: "Observed paused",
    pending: "Pending application",
    error: "Reconciliation error",
    mismatch: "Schedule mismatch",
    stale: "Stale observation",
    unknown: "Unknown",
  };
  return (
    <section
      className="control-panel control-operator-evidence"
      aria-labelledby="control-operator-evidence-title"
    >
      <div className="control-section-heading">
        <div>
          <h2 id="control-operator-evidence-title">
            {sampleMode ? "Sample workflow relationships" : "Current engine evidence"}
          </h2>
          <p>
            {sampleMode
              ? "Synthetic records only. Live intake, pipeline work, jobs and deliveries are not checked."
              : "Source Inbox intake, pipeline work and job observations are separate from run history."}
          </p>
        </div>
      </div>
      {issues.length ? (
        <p className="control-evidence-warning" role="status">
          Some operator evidence is unavailable. Its missing row does not mean no activity occurred.
        </p>
      ) : null}
      {!components.length && !jobs.length ? (
        <p className="control-muted">Component and job inventory is unavailable.</p>
      ) : null}
      <div className="control-evidence-grid">
        <section aria-labelledby="control-component-evidence-title">
          <h3 id="control-component-evidence-title">
            {sampleMode ? "Sample components" : "Components"}
          </h3>
          {components.map((component) => {
            const row = activityById.get(component.component_id);
            const accepted =
              row?.endpoints
                .map((endpoint) => endpoint.accepted_at)
                .filter((value): value is string => value !== null) ?? [];
            const lastAccepted = accepted.sort((a, b) => Date.parse(b) - Date.parse(a))[0] ?? null;
            const pipelineTime =
              row?.pipelines
                .map((pipeline) => pipeline.work_created_at)
                .filter((value): value is string => value !== null)
                .sort((a, b) => Date.parse(b) - Date.parse(a))[0] ?? null;
            return (
              <article key={component.component_id}>
                <strong>{component.display_name}</strong>
                <span>
                  {sampleMode ? (
                    "Sample input status is not represented."
                  ) : (
                    <>
                      Last accepted input:{" "}
                      {lastAccepted ? (
                        <time dateTime={lastAccepted}>{formatTime(lastAccepted)} WIB</time>
                      ) : row ? (
                        "No accepted input recorded"
                      ) : (
                        "Unavailable"
                      )}
                    </>
                  )}
                </span>
                <span>
                  {sampleMode ? (
                    "Sample pipeline work is not represented."
                  ) : (
                    <>
                      Last pipeline work:{" "}
                      {row?.pipelines.length ? (
                        pipelineTime ? (
                          <time dateTime={pipelineTime}>{formatTime(pipelineTime)} WIB</time>
                        ) : (
                          "Not recorded"
                        )
                      ) : component.pipeline_ids.length ? (
                        "Unknown"
                      ) : (
                        "Not applicable"
                      )}
                    </>
                  )}
                </span>
                <span>
                  {sampleMode
                    ? "Delivery: not represented"
                    : `Delivery: ${row?.delivery_status ?? "Not instrumented"}`}
                </span>
              </article>
            );
          })}
        </section>
        <section aria-labelledby="control-job-evidence-title">
          <h3 id="control-job-evidence-title">{sampleMode ? "Sample jobs" : "Jobs"}</h3>
          {jobs.map((job) => {
            const observation = observations.get(`job:${job.job_id}`);
            const state = observedJobState(job, observation);
            const last = observation?.evidence.last_execution;
            return (
              <article key={job.job_id}>
                <strong>{job.display_name}</strong>
                {sampleMode ? (
                  <span>
                    Example job record only. No live job status or execution is represented.
                  </span>
                ) : (
                  <>
                    <span>
                      {states[state]} · {job.job_id}
                    </span>
                    <span>
                      Observed:{" "}
                      {observation
                        ? `${formatTime(observation.observed_at)} WIB`
                        : "No observation"}
                    </span>
                    <span>
                      Last execution:{" "}
                      {last?.at
                        ? `${last.status ?? "Status unavailable"}, ${formatTime(last.at)} WIB`
                        : "Not reported"}
                    </span>
                  </>
                )}
              </article>
            );
          })}
        </section>
      </div>
      <p className="control-panel-note">
        {sampleMode
          ? "The sample shows workflow relationships only, with no live input, processing, job or delivery evidence."
          : "Input means accepted into Source Inbox. Pipeline work does not confirm Discord delivery."}
      </p>
    </section>
  );
}

export function ControlWatcherList({
  watchers,
  runs,
  jobs,
  updatedAt,
  onSelectWatcher,
  issues = [],
  limit,
  statusLoaded = true,
  components = [],
  operatorJobs = [],
  observations = [],
  operatorIssues = [],
  basePath = "/workspace",
  sampleMode = false,
}: {
  watchers: ControlWatcher[];
  runs: ControlRun[];
  jobs: ControlJob[];
  updatedAt: string;
  onSelectWatcher: (watcherId: string) => void;
  issues?: ControlCoverageIssue[];
  limit?: number;
  statusLoaded?: boolean;
  components?: OperatorComponent[];
  operatorJobs?: OperatorJob[];
  observations?: OperatorObservation[];
  operatorIssues?: { resource: string; message: string }[];
  basePath?: string;
  sampleMode?: boolean;
}) {
  const latest = useMemo(
    () => latestControlRuns(watchers, runs, updatedAt),
    [watchers, runs, updatedAt],
  );
  const observationById = useMemo(() => latestOperatorObservations(observations), [observations]);
  const relationshipsUnavailable = operatorIssues.some(
    (issue) => issue.resource === "components" || issue.resource === "operator-jobs",
  );
  const observationsUnavailable = operatorIssues.some((issue) => issue.resource === "observations");
  if (watchers.length === 0)
    return (
      <div className="control-list-empty">
        <CircleDashed size={24} aria-hidden="true" />
        <strong>No watchers available</strong>
        <p>Watchers will appear here when your workspace has access to them.</p>
      </div>
    );
  return (
    <ul className="control-watcher-list">
      {watchers.slice(0, limit).map((watcher) => {
        const lastRun = latest.get(watcher.watcher_id);
        const runUnavailable = issues.some(
          (issue) => issue.watcherId === watcher.watcher_id && issue.resource === "runs",
        );
        const jobsUnavailable = issues.some(
          (issue) => issue.watcherId === watcher.watcher_id && issue.resource === "jobs",
        );
        const configEvidence = ownerConfigEvidence(
          watcher.current_revision,
          runs.filter((run) => run.watcher_id === watcher.watcher_id),
        );
        const schedules = summarizeControlSchedules(
          jobs.filter((job) => job.watcher_id === watcher.watcher_id),
        );
        const ownerComponents = components.filter(
          (component) =>
            component.kind === "domain_owner" &&
            (component.component_id === watcher.watcher_id ||
              component.config_resource_ids.includes(watcher.watcher_id) ||
              component.config_resource_ids.includes(`watcher:${watcher.watcher_id}`)),
        );
        const ownerJobIds = new Set(ownerComponents.flatMap((component) => component.job_ids));
        const ownerJobs = operatorJobs.filter((job) => ownerJobIds.has(job.job_id));
        return (
          <li key={watcher.watcher_id}>
            <button
              className="control-watcher-row"
              onClick={() => onSelectWatcher(watcher.watcher_id)}
            >
              <span className="sr-only">Open watcher details: </span>
              <span className="control-watcher-monogram" aria-hidden="true">
                {watcher.display_name.trim().slice(0, 2).toUpperCase()}
              </span>
              <span className="control-watcher-identity">
                <strong>{watcher.display_name}</strong>
                <span>
                  {sampleMode
                    ? `Sample configuration v${watcher.current_revision ?? "unknown"}`
                    : watcher.current_revision === null
                      ? "Configuration not saved"
                      : `Configuration v${watcher.current_revision}`}
                  {!statusLoaded
                    ? sampleMode
                      ? " · Open to review sample settings"
                      : " · Open to review settings"
                    : sampleMode
                      ? " · Example history only"
                      : jobsUnavailable
                        ? " · Schedules unavailable"
                        : ` · ${schedules.active} active ${schedules.active === 1 ? "schedule" : "schedules"}`}
                </span>
              </span>
              <span className="control-watcher-outcome">
                {!statusLoaded ? (
                  <span className="control-muted">Configure</span>
                ) : runUnavailable ? (
                  <span className="control-status control-status-degraded">
                    <TriangleAlert size={14} aria-hidden="true" />
                    History unavailable
                  </span>
                ) : lastRun ? (
                  <ControlRunStatus status={lastRun.status} sampleMode={sampleMode} />
                ) : (
                  <span className="control-status control-status-muted">
                    <CircleDashed size={14} aria-hidden="true" />
                    {sampleMode ? "No sample run" : "No recorded run"}
                  </span>
                )}
                {statusLoaded && lastRun && !runUnavailable && !sampleMode && (
                  <time dateTime={lastRun.started_at}>{formatTime(lastRun.started_at)} WIB</time>
                )}
              </span>
              <ArrowUpRight size={18} className="control-row-arrow" aria-hidden="true" />
            </button>
            {statusLoaded && (
              <div className="control-watcher-operator-evidence">
                <span>
                  {sampleMode
                    ? "Sample configuration record"
                    : runUnavailable
                      ? "Configuration use unavailable"
                      : configEvidence.label}
                </span>
                {relationshipsUnavailable ? (
                  <span>Shared job relationship unavailable</span>
                ) : ownerJobs.length ? (
                  <span>
                    Shared jobs:{" "}
                    {ownerJobs.map((job, index) => {
                      const state = observedJobState(job, observationById.get(`job:${job.job_id}`));
                      return (
                        <span key={job.job_id}>
                          {index ? ", " : ""}
                          {job.display_name} (
                          {sampleMode
                            ? "sample record"
                            : observationsUnavailable
                              ? "status unavailable"
                              : formatObservedJobState(state)}
                          )
                        </span>
                      );
                    })}{" "}
                    <Link href={`${basePath}/jobs`}>View Jobs</Link>
                  </span>
                ) : (
                  <span>Shared job relationship unavailable</span>
                )}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function formatObservedJobState(state: ReturnType<typeof observedJobState>) {
  const labels: Record<ReturnType<typeof observedJobState>, string> = {
    active: "active",
    paused: "paused",
    pending: "pending",
    error: "reconciliation error",
    mismatch: "mismatch",
    stale: "stale",
    unknown: "unknown",
  };
  return labels[state];
}

export function ControlRunList({
  runs,
  watchers,
  onSelectRun,
  limit,
  emptyMessage = "No run records are available yet.",
  sampleMode = false,
}: {
  runs: ControlRun[];
  watchers: ControlWatcher[];
  onSelectRun: (runId: string) => void;
  limit?: number;
  emptyMessage?: string;
  sampleMode?: boolean;
}) {
  const names = new Map(watchers.map((watcher) => [watcher.watcher_id, watcher.display_name]));
  const recent = [...runs]
    .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at))
    .slice(0, limit);
  if (!recent.length)
    return (
      <div className="control-list-empty">
        <Activity size={24} aria-hidden="true" />
        <strong>No activity to show</strong>
        <p>{emptyMessage}</p>
      </div>
    );
  return (
    <div className="control-run-list">
      <div className="control-run-columns" aria-hidden="true">
        <span>{sampleMode ? "Sample workflow record" : "Watcher / trigger"}</span>
        <span>{sampleMode ? "Example outcome" : "Outcome"}</span>
        <span>{sampleMode ? "Example time" : "Started · WIB"}</span>
        <span>{sampleMode ? "Example duration" : "Duration"}</span>
        <span />
      </div>
      <ul>
        {recent.map((run) => (
          <li key={run.run_id}>
            <button className="control-run-row" onClick={() => onSelectRun(run.run_id)}>
              <span className="sr-only">View run details: </span>
              <span className="control-run-identity">
                <strong>{names.get(run.watcher_id) ?? run.watcher_id}</strong>
                <span>
                  {sampleMode
                    ? "Sample record · Sample configuration"
                    : `${run.trigger.replaceAll("_", " ")} · Configuration v${run.config_revision}`}
                </span>
              </span>
              <ControlRunStatus status={run.status} sampleMode={sampleMode} />
              <time dateTime={run.started_at}>
                <span className="sr-only">{sampleMode ? "Example time " : "Started "}</span>
                {formatTime(run.started_at)}
                <span className="sr-only"> WIB</span>
              </time>
              <span className="control-run-duration">
                <span className="control-duration-label">Duration: </span>
                {controlRunDuration(run)}
              </span>
              <ChevronRight className="control-row-arrow" size={17} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
