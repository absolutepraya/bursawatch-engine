"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { PageHeading } from "@/components/page-heading";
import {
  insightsRunLimit,
  latestStockMoves,
  outcomeLabels,
  summarizeRuns,
  type RunEvidence,
} from "@/lib/run-analytics";
import type { RunOutcome, RunRecord } from "@/lib/types";

function dayLabel(date: string) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(new Date(`${date}T12:00:00Z`));
}

function runTime(date: string) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: "Asia/Jakarta",
  }).format(new Date(date));
}

export function WorkflowInsights({
  runs,
  evidence,
  asOf,
}: {
  runs: RunRecord[];
  evidence: RunEvidence[];
  asOf: string;
}) {
  const [range, setRange] = useState<7 | 30>(7);
  const [showTable, setShowTable] = useState(false);
  const report = summarizeRuns(runs, range, asOf);
  const stockMoves = latestStockMoves(report.runs, evidence);
  const maxCount = Math.max(1, ...report.days.map((day) => day.count));
  const firstDate = dayLabel(report.days[0].date);
  const lastDate = dayLabel(report.days.at(-1)!.date);
  const sourceLabel =
    report.sampleCount === report.checks && report.checks
      ? "Sample run records"
      : report.sampleCount
        ? "Sample and Sectors-live run records"
        : report.checks
          ? "Sectors-live run records"
          : "Available run records";

  return (
    <div className="page-wrap insights-page">
      <PageHeading
        title="Insights"
        description="Understand what your recorded workflow checks produced."
        action={
          <Link className="button secondary" href="/app/activity">
            Run history <ArrowRight size={17} aria-hidden="true" />
          </Link>
        }
      />
      <div className="insights-toolbar">
        <div className="insights-range" role="group" aria-label="Reporting period">
          {([7, 30] as const).map((days) => (
            <button
              type="button"
              key={days}
              aria-pressed={range === days}
              onClick={() => setRange(days)}
            >
              Last {days} days
            </button>
          ))}
        </div>
        <p>
          {firstDate}–{lastDate} · WIB (UTC+7)
        </p>
      </div>
      <div className="insights-report-context" aria-live="polite">
        <p>
          <strong>{sourceLabel}.</strong> {report.checks} {report.checks === 1 ? "check" : "checks"}{" "}
          across {report.recordedDays} recorded {report.recordedDays === 1 ? "day" : "days"} in this
          period.
        </p>
        <p>
          Uses up to the latest {insightsRunLimit} runs available to Run history, through{" "}
          {runTime(asOf)} WIB. This is a snapshot, not a complete execution history.
        </p>
      </div>
      {report.checks ? (
        <>
          <dl className="insights-totals">
            <div>
              <dt>Recorded checks</dt>
              <dd>{report.checks}</dd>
              <dd className="insights-total-note">Includes checks still in progress.</dd>
            </div>
            <div>
              <dt>Briefs prepared</dt>
              <dd>{report.prepared}</dd>
              <dd className="insights-total-note">Prepared previews, not delivery receipts.</dd>
            </div>
            <div>
              <dt>Checks with issues</dt>
              <dd>{report.issues}</dd>
              <dd className="insights-total-note">Degraded or failed outcomes.</dd>
            </div>
          </dl>
          <section className="insights-stocks" aria-labelledby="insights-stocks-title">
            <div className="insights-section-heading">
              <div>
                <h2 id="insights-stocks-title">Stock moves in your checks</h2>
                <p>
                  Latest saved daily closing-price change for each stock checked in this period.
                </p>
              </div>
              <Link className="text-link" href="/app/watchlist">
                Stock watchlist <ArrowRight size={17} aria-hidden="true" />
              </Link>
            </div>
            {stockMoves.length ? (
              <>
                <p className="insights-stock-summary">
                  {stockMoves.filter((item) => item.change > 0).length} up ·{" "}
                  {stockMoves.filter((item) => item.change < 0).length} down ·{" "}
                  {stockMoves.filter((item) => item.change === 0).length} unchanged. These are saved
                  observations on the dates shown, not current quotes or portfolio returns.
                </p>
                <ul className="insights-stock-list">
                  {stockMoves.map(({ evidence: item, change, runId }) => (
                    <li key={item.symbol}>
                      <Link href={`/app/activity?run=${encodeURIComponent(runId)}`}>
                        <span className="insights-stock-identity">
                          <strong>{item.symbol}</strong>
                          <span>
                            {item.origin === "synthetic-demo" ? "Sample data" : "Sectors live"}
                          </span>
                        </span>
                        <span
                          className={`insights-stock-change ${change > 0 ? "positive" : change < 0 ? "negative" : ""}`}
                        >
                          {change > 0 ? "+" : ""}
                          {change.toFixed(2)}%
                          <span>
                            {change > 0 ? "Up" : change < 0 ? "Down" : "Unchanged"} on{" "}
                            {dayLabel(item.marketAsOf)}
                          </span>
                        </span>
                        <span className="insights-stock-evidence">
                          View evidence <ArrowRight size={16} aria-hidden="true" />
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="insights-stock-summary">
                No daily price-change evidence was saved with these checks. Open a recorded check
                below to inspect the source data that is available.
              </p>
            )}
          </section>
          <section className="insights-outcomes" aria-labelledby="insights-outcomes-title">
            <div className="insights-section-heading">
              <div>
                <h2 id="insights-outcomes-title">Daily outcomes</h2>
                <p>Each bar counts recorded checks by their start date in WIB.</p>
              </div>
              <button
                type="button"
                className="button secondary"
                aria-expanded={showTable}
                aria-controls="insights-data-table"
                onClick={() => setShowTable((current) => !current)}
              >
                {showTable ? "Hide data table" : "Show data table"}
              </button>
            </div>
            <figure className="insights-chart">
              <div
                className="insights-bars"
                role="img"
                aria-label={`${firstDate} to ${lastDate}, WIB: ${report.checks} recorded checks, ${report.prepared} briefs prepared, ${report.outcomes["no-change"]} with no change, ${report.issues} with issues, ${report.outcomes.running} in progress. Full daily counts are available in the data table.`}
              >
                {report.days.map((day) => (
                  <div className="insights-day" key={day.date} aria-hidden="true">
                    <div className="insights-day-stack">
                      {[
                        ["prepared", day.outcomes["prepared-preview"]],
                        ["unchanged", day.outcomes["no-change"]],
                        ["issues", day.outcomes.degraded + day.outcomes.failed],
                        ["running", day.outcomes.running],
                      ].map(([kind, count]) =>
                        count ? (
                          <span
                            key={kind}
                            className={`insights-segment insights-${kind}`}
                            style={{ height: `${(Number(count) / maxCount) * 100}%` }}
                          />
                        ) : null,
                      )}
                      {!day.count ? <span className="insights-unrecorded" /> : null}
                    </div>
                    {range === 7 ? (
                      <span className="insights-day-number">{day.date.slice(-2)}</span>
                    ) : null}
                  </div>
                ))}
              </div>
              <div className="insights-chart-axis" aria-hidden="true">
                <span>{firstDate}</span>
                <span>
                  Peak: {maxCount} {maxCount === 1 ? "check" : "checks"}/day
                </span>
                <span>{lastDate}</span>
              </div>
              <ul className="insights-legend" aria-label="Chart legend">
                <li>
                  <span className="insights-prepared" />
                  Brief prepared
                </li>
                <li>
                  <span className="insights-unchanged" />
                  No change
                </li>
                <li>
                  <span className="insights-issues" />
                  Issue
                </li>
                <li>
                  <span className="insights-running" />
                  In progress
                </li>
              </ul>
              <figcaption>
                Gaps mean no records in this snapshot. They do not confirm that a check ran or that
                the scheduler was healthy.
              </figcaption>
            </figure>
            <div id="insights-data-table" hidden={!showTable}>
              <table className="insights-table">
                <caption>
                  Daily recorded checks · {firstDate}–{lastDate}, WIB
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Date</th>
                    <th scope="col">Checks</th>
                    <th scope="col">Outcomes</th>
                  </tr>
                </thead>
                <tbody>
                  {report.days.map((day) => (
                    <tr key={day.date}>
                      <th scope="row">{dayLabel(day.date)}</th>
                      <td>{day.count || "—"}</td>
                      <td>
                        {day.count
                          ? (Object.entries(day.outcomes) as [RunOutcome, number][])
                              .filter(([, count]) => count > 0)
                              .map(
                                ([outcome, count]) =>
                                  `${count} ${outcomeLabels[outcome].toLowerCase()}`,
                              )
                              .join(" · ")
                          : "No recorded checks"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <section className="insights-records" aria-labelledby="insights-records-title">
            <div className="insights-section-heading">
              <div>
                <h2 id="insights-records-title">Behind the numbers</h2>
                <p>The five most recent checks in this period.</p>
              </div>
              <Link className="text-link" href="/app/activity">
                All run history <ArrowRight size={16} aria-hidden="true" />
              </Link>
            </div>
            <ul>
              {report.runs.slice(0, 5).map((run) => (
                <li key={run.id}>
                  <Link href={`/app/activity?run=${encodeURIComponent(run.id)}`}>
                    <span className="insights-record-name">
                      <strong>{run.automationName}</strong>
                      <span>
                        <time dateTime={run.startedAt}>{runTime(run.startedAt)} WIB</time> ·{" "}
                        {run.evidenceMode === "synthetic-demo" ? "Sample data" : "Sectors live"}
                      </span>
                    </span>
                    <span className="insights-record-outcome">{outcomeLabels[run.outcome]}</span>
                    <ArrowRight size={17} aria-hidden="true" />
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        </>
      ) : (
        <section className="insights-empty" aria-labelledby="insights-empty-title">
          <h2 id="insights-empty-title">No recorded checks in this period</h2>
          <p>
            {range === 7 && runs.length
              ? "Try the 30-day view, or open Run history to inspect the available records."
              : "Recorded checks will supply these totals once they are available. Open Workflows to review what you have configured."}
          </p>
          <Link className="button secondary" href="/app/automations">
            View workflows <ArrowRight size={17} aria-hidden="true" />
          </Link>
        </section>
      )}
    </div>
  );
}
