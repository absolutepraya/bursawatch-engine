import { ArrowRight, Plus, Clock3 } from "lucide-react";
import Link from "next/link";
import { PageHeading } from "@/components/page-heading";
import { StatusBadge } from "@/components/status-badge";
import { BrowserWatches } from "@/components/browser-watches";
import { getWorkspaceRecords } from "@/lib/sample-workspace";
import { hostedDemo } from "@/lib/demo-mode";
import { formatWib } from "@/lib/format";

export const dynamic = "force-dynamic";

export default function OverviewPage() {
  const db = getWorkspaceRecords();
  const automations = db.listAutomations();
  const runs = db.listRuns(5);
  const active = automations.filter((item) => item.status === "active");
  const symbols = Array.from(new Set(automations.flatMap((item) => item.symbols)));
  const next = active.sort((a, b) => a.nextRunAt.localeCompare(b.nextRunAt))[0];
  return (
    <div className="page-wrap">
      <PageHeading
        title="Overview"
        description="Your stocks, scheduled checks, and latest results."
        action={
          <Link className="button primary" href="/app/automations/new">
            <Plus size={18} aria-hidden="true" /> New watch
          </Link>
        }
      />
      <BrowserWatches />
      <section
        className="desk-summary"
        aria-label={hostedDemo ? "Example workspace summary" : "Workspace summary"}
      >
        <div>
          <span>Stocks in view</span>
          <strong>{symbols.length}</strong>
          <p>{symbols.join(" · ") || "Add your first stock"}</p>
        </div>
        <div>
          <span>Active watches</span>
          <strong>{active.length}</strong>
          <p>Scheduled for daily checks</p>
        </div>
        <div>
          <span>Next check</span>
          <strong>
            {hostedDemo
              ? "15:30"
              : next
                ? formatWib(next.nextRunAt, { hour: "2-digit", minute: "2-digit" })
                : "—"}
          </strong>
          <p>
            {hostedDemo
              ? "WIB · Weekday schedule"
              : next
                ? formatWib(next.nextRunAt)
                : "No active schedule"}
          </p>
        </div>
      </section>
      <div className="desk-grid">
        <section className="desk-activity">
          <div className="section-heading">
            <h2>Recent checks</h2>
            <Link className="text-link" href="/app/activity">
              All activity <ArrowRight size={16} aria-hidden="true" />
            </Link>
          </div>
          <div className="check-listing">
            {runs.map((run) => (
              <Link className="check-entry" key={run.id} href={`/app/activity?run=${run.id}`}>
                <span className="check-entry-icon">
                  <Clock3 size={18} aria-hidden="true" />
                </span>
                <div>
                  <strong>{run.automationName}</strong>
                  <p>
                    {run.outcome === "no-change"
                      ? "No new change. Watch continues."
                      : run.outcome === "prepared-preview"
                        ? "Condition changed. A brief is ready to preview."
                        : run.summary}
                  </p>
                  <time dateTime={run.startedAt}>{formatWib(run.startedAt)}</time>
                </div>
                <StatusBadge
                  status={run.outcome}
                  label={
                    run.outcome === "prepared-preview"
                      ? "Brief ready"
                      : run.outcome === "no-change"
                        ? "No change"
                        : undefined
                  }
                />
                <ArrowRight size={16} aria-hidden="true" />
              </Link>
            ))}
          </div>
          {!runs.length ? (
            <p className="empty-state">Your first completed check will appear here.</p>
          ) : null}
        </section>
        <aside className="desk-watchlist">
          <div className="section-heading">
            <h2>On your radar</h2>
            <Link href="/app/watchlist" className="text-link" aria-label="Open watchlist">
              <ArrowRight size={18} aria-hidden="true" />
            </Link>
          </div>
          {symbols.map((symbol) => (
            <Link href="/app/watchlist" className="radar-row" key={symbol}>
              <span className="ticker-monogram">{symbol.slice(0, 2)}</span>
              <div>
                <strong>{symbol}</strong>
                <p>
                  {symbol === "BBRI"
                    ? "Bank Rakyat Indonesia"
                    : symbol === "TLKM"
                      ? "Telkom Indonesia"
                      : "IDX stock"}
                </p>
              </div>
              <span>Daily</span>
            </Link>
          ))}
          <div className="radar-note">
            <h3>Daily, not intraday.</h3>
            <p>
              Price conditions use daily data. Each result includes the check time and its source.
            </p>
            <Link href="/app/automations/new" className="text-link">
              Set up a watch <ArrowRight size={16} aria-hidden="true" />
            </Link>
          </div>
        </aside>
      </div>
    </div>
  );
}
