"use client";

import { useMemo, useState } from "react";
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
import {
  controlRunDuration,
  controlStatusLabels,
  controlStatuses,
  latestControlRuns,
  summarizeControlRuns,
  summarizeControlSchedules,
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

export function ControlRunStatus({ status }: { status: ControlRun["status"] }) {
  const Icon = statusIcons[status];
  return (
    <span className={`control-status control-status-${status}`}>
      <Icon size={14} aria-hidden="true" />
      {controlStatusLabels[status]}
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
}: ControlDashboardProps) {
  const [range, setRange] = useState<ControlRange>("7d");
  const report = useMemo(
    () => summarizeControlRuns(runs, range, updatedAt),
    [runs, range, updatedAt],
  );
  const schedules = useMemo(() => summarizeControlSchedules(jobs), [jobs]);
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
          <p>Your watchers, schedules and latest activity.</p>
        </div>
        <div className="control-refresh">
          <span>
            Updated <time dateTime={updatedAt}>{formatTime(updatedAt)} WIB</time>
          </span>
          <button
            className="button secondary"
            onClick={onRefresh}
            disabled={refreshing}
            aria-busy={refreshing}
          >
            <RefreshCw size={16} aria-hidden="true" />
            {refreshing ? "Refreshing…" : "Refresh"}
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
            with saved configuration
          </small>
        </div>
        <div className="control-metric">
          <span>Recorded runs</span>
          <strong>{number.format(report.total)}</strong>
          <small>{range === "7d" ? "Last 7 calendar days" : "Last 24 hours"} · WIB</small>
        </div>
        <div className={`control-metric${report.attention ? " control-metric-attention" : ""}`}>
          <span>Runs needing attention</span>
          <strong>{number.format(report.attention)}</strong>
          <small>Degraded, failed or blocked</small>
        </div>
        <div className="control-metric">
          <span>Active schedules</span>
          <strong>
            {number.format(schedules.active)}
            <span> / {number.format(schedules.total)}</span>
          </strong>
          <small>Enabled and applied by the scheduler</small>
        </div>
      </section>

      <div className="control-chart-grid">
        <section
          className="control-panel control-activity-panel"
          aria-labelledby="control-activity-title"
        >
          <div className="control-section-heading">
            <div>
              <h2 id="control-activity-title">Run activity</h2>
              <p>Recorded outcomes over time</p>
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
              recorded runs
              <span className="control-chart-period">
                {formatTime(report.start)} – {formatTime(report.end)} WIB
              </span>
            </span>
          </div>
          <p className="control-chart-coverage">
            Up to 50 latest runs per watcher. This range may be incomplete.
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
              aria-label={`${report.total} recorded runs. ${controlStatuses.map((status) => `${report.statuses[status]} ${controlStatusLabels[status].toLowerCase()}`).join(", ")}. Full values are available in the activity table below.`}
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
                      title={`${formatTime(bucket.start)} – ${formatTime(bucket.end)} WIB: ${bucket.count} recorded runs`}
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
                Returned runs by start time, in WIB.{" "}
                {range === "7d" ? "Today is a partial day. " : ""}
                Empty intervals do not establish that a check ran.
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
              <h2 id="control-schedules-title">Schedule status</h2>
              <p>Saved and applied schedules</p>
            </div>
            <Clock3 size={19} aria-hidden="true" />
          </div>
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
          <p className="control-panel-note">
            {schedules.pending > 0
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
            <h2 id="control-watchers-title">Watcher status</h2>
            <p>Latest recorded run for each watcher</p>
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
        />
      </section>

      <section
        className="control-panel control-recent-panel"
        aria-labelledby="control-recent-title"
      >
        <div className="control-section-heading">
          <div>
            <h2 id="control-recent-title">Recent activity</h2>
            <p>Open a run to inspect its recorded events</p>
          </div>
          <Activity size={19} aria-hidden="true" />
        </div>
        <ControlRunList
          runs={report.runs}
          watchers={watchers}
          onSelectRun={onSelectRun}
          limit={6}
          emptyMessage="No run records in the selected range."
        />
      </section>
      <p className="control-data-note">
        A completed run does not confirm message delivery. Gaps in returned history do not establish
        uptime.
      </p>
    </div>
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
}: {
  watchers: ControlWatcher[];
  runs: ControlRun[];
  jobs: ControlJob[];
  updatedAt: string;
  onSelectWatcher: (watcherId: string) => void;
  issues?: ControlCoverageIssue[];
  limit?: number;
  statusLoaded?: boolean;
}) {
  const latest = useMemo(
    () => latestControlRuns(watchers, runs, updatedAt),
    [watchers, runs, updatedAt],
  );
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
        const schedules = summarizeControlSchedules(
          jobs.filter((job) => job.watcher_id === watcher.watcher_id),
        );
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
                  {watcher.current_revision === null
                    ? "Configuration not saved"
                    : `Configuration v${watcher.current_revision}`}
                  {!statusLoaded
                    ? " · Open to review settings"
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
                  <ControlRunStatus status={lastRun.status} />
                ) : (
                  <span className="control-status control-status-muted">
                    <CircleDashed size={14} aria-hidden="true" />
                    No recorded run
                  </span>
                )}
                {lastRun && !runUnavailable && (
                  <time dateTime={lastRun.started_at}>{formatTime(lastRun.started_at)} WIB</time>
                )}
              </span>
              <ArrowUpRight size={18} className="control-row-arrow" aria-hidden="true" />
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export function ControlRunList({
  runs,
  watchers,
  onSelectRun,
  limit,
  emptyMessage = "No run records are available yet.",
}: {
  runs: ControlRun[];
  watchers: ControlWatcher[];
  onSelectRun: (runId: string) => void;
  limit?: number;
  emptyMessage?: string;
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
        <span>Watcher / trigger</span>
        <span>Outcome</span>
        <span>Started · WIB</span>
        <span>Duration</span>
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
                  {run.trigger.replaceAll("_", " ")} · Configuration v{run.config_revision}
                </span>
              </span>
              <ControlRunStatus status={run.status} />
              <time dateTime={run.started_at}>
                <span className="sr-only">Started </span>
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
