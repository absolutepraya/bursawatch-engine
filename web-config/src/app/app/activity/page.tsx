import { ArrowDown, CheckCircle2, DatabaseZap, ExternalLink, ShieldAlert } from "lucide-react";
import Link from "next/link";

import { PageHeading } from "@/components/page-heading";
import { StatusBadge } from "@/components/status-badge";
import { WorkflowNavigation } from "@/components/workflow-navigation";
import { getWorkspaceRecords } from "@/lib/sample-workspace";
import { formatWib } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function ActivityPage({
  searchParams,
}: {
  searchParams: Promise<{ run?: string }>;
}) {
  const { run: requestedRun } = await searchParams;
  const db = getWorkspaceRecords();
  const runs = db.listRuns(20);
  const selected = runs.find((run) => run.id === requestedRun) ?? runs[0];
  const events = selected ? db.listActivity(selected.id) : [];
  const evidence = selected ? db.listEvidence(selected.id) : [];

  return (
    <div className="page-wrap">
      <PageHeading
        title="Workflows"
        description="Review each run, its outcome, and the source evidence."
      />
      <WorkflowNavigation />
      {runs.length ? (
        <nav className="run-picker" aria-label="Workflow runs">
          {runs.map((run) => (
            <Link
              key={run.id}
              href={`/app/activity?run=${run.id}`}
              aria-current={run.id === selected?.id ? "true" : undefined}
            >
              <span>
                <strong>{run.automationName}</strong>
                <time dateTime={run.startedAt}>{formatWib(run.startedAt)}</time>
              </span>
              <span className="run-picker-trigger">{run.trigger}</span>
              <StatusBadge status={run.outcome} />
            </Link>
          ))}
        </nav>
      ) : null}
      {selected ? (
        <div className="activity-layout">
          <section className="timeline-panel" aria-labelledby="timeline-title">
            <div className="section-heading">
              <div>
                <h2 id="timeline-title">{selected.automationName}</h2>
                <p className="section-meta">
                  {formatWib(selected.startedAt, {
                    day: "2-digit",
                    month: "long",
                    year: "numeric",
                  })}
                </p>
              </div>
              <StatusBadge
                status={selected.outcome}
                label={selected.outcome === "prepared-preview" ? "Preview ready" : undefined}
              />
            </div>
            <div className="timeline">
              {events.map((event, index) => (
                <div className="timeline-event" key={event.id}>
                  <time dateTime={event.occurredAt}>
                    {formatWib(event.occurredAt, { hour: "2-digit", minute: "2-digit" })}
                  </time>
                  <span className={`timeline-marker marker-${event.status}`}>
                    <CheckCircle2 aria-hidden="true" size={15} />
                  </span>
                  <div>
                    <strong>{event.title}</strong>
                    <p>{event.detail}</p>
                    {event.evidenceRef ? <code>{event.evidenceRef}</code> : null}
                  </div>
                  {index < events.length - 1 ? (
                    <ArrowDown className="timeline-arrow" aria-hidden="true" size={14} />
                  ) : null}
                </div>
              ))}
            </div>
            {selected.outcome === "no-change" ? (
              <div className="no-op-banner">
                <CheckCircle2 aria-hidden="true" />
                <div>
                  <strong>No new change</strong>
                  <p>This check found no change to your alert condition.</p>
                </div>
              </div>
            ) : null}
          </section>

          <aside className="run-detail">
            <div className="section-heading">
              <div>
                <h2>Check details</h2>
              </div>
              <span className="mono-id">{selected.id.slice(0, 12)}</span>
            </div>
            <dl className="detail-list compact">
              <div>
                <dt>Trigger</dt>
                <dd>{selected.trigger}</dd>
              </div>
              <div>
                <dt>Configuration</dt>
                <dd>Version {selected.configVersion}</dd>
              </div>
              <div>
                <dt>Condition</dt>
                <dd>{selected.conditionResult}</dd>
              </div>
              <div>
                <dt>Data source</dt>
                <dd>
                  <StatusBadge
                    status={selected.evidenceMode === "sectors-live" ? "healthy" : "delayed"}
                    label={
                      selected.evidenceMode === "sectors-live" ? "Sectors live" : "Sample data"
                    }
                  />
                </dd>
              </div>
              <div>
                <dt>Completed</dt>
                <dd>{selected.completedAt ? formatWib(selected.completedAt) : "Running"}</dd>
              </div>
            </dl>
            <div className="run-summary">
              <ShieldAlert aria-hidden="true" size={18} />
              <p>{selected.summary}</p>
            </div>
            <div className="evidence-list">
              <div className="evidence-title">
                <DatabaseZap aria-hidden="true" size={18} />
                <h3>Source data</h3>
              </div>
              {evidence.length ? (
                evidence.map((item) => (
                  <article key={item.id}>
                    <div>
                      <strong>
                        {item.symbol} · {item.metric.replaceAll("_", " ")}
                      </strong>
                      <span>
                        {item.marketAsOf} · {item.origin.replaceAll("-", " ")}
                      </span>
                    </div>
                    <b>
                      {item.value}
                      {item.unit}
                    </b>
                    <a
                      href={`https://docs.sectors.app/api-references/v2/indonesia/transaction/daily`}
                      target="_blank"
                      rel="noreferrer"
                      aria-label={`View documentation for ${item.endpoint}`}
                    >
                      <ExternalLink aria-hidden="true" size={15} />
                    </a>
                  </article>
                ))
              ) : (
                <p className="empty-copy">No source data was saved for this check.</p>
              )}
            </div>
          </aside>
        </div>
      ) : (
        <div className="empty-state">
          <h2>No checks yet</h2>
          <p>Completed checks will appear here.</p>
        </div>
      )}
    </div>
  );
}
