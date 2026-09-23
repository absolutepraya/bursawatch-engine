import { ArrowRight, Eye, LineChart } from "lucide-react";
import Link from "next/link";

import { PageHeading } from "@/components/page-heading";
import { StatusBadge } from "@/components/status-badge";
import { getWorkspaceRecords } from "@/lib/sample-workspace";
import { BrowserWatches } from "@/components/browser-watches";
import { formatWib } from "@/lib/format";

export const dynamic = "force-dynamic";

export default function WatchlistPage() {
  const db = getWorkspaceRecords();
  const automations = db.listAutomations();
  const runs = db.listRuns(20);
  const symbols = Array.from(new Set(automations.flatMap((automation) => automation.symbols)));

  return (
    <div className="page-wrap">
      <PageHeading
        title="Watchlist"
        description="The stocks you follow and the changes you’re watching for."
        action={
          <Link className="button primary" href="/app/automations/new">
            Add stocks <ArrowRight aria-hidden="true" size={18} />
          </Link>
        }
      />
      <BrowserWatches />
      <section className="watchlist-table" aria-label="Watched IDX stocks">
        <div className="watchlist-head">
          <span>Stock</span>
          <span>Horizon</span>
          <span>Condition</span>
          <span>Latest cycle</span>
          <span>Status</span>
          <span aria-hidden="true" />
        </div>
        {symbols.map((symbol) => {
          const automation = automations.find((item) => item.symbols.includes(symbol))!;
          const run = runs.find((item) => item.automationId === automation.id);
          return (
            <article className="watchlist-row" key={symbol}>
              <div className="stock-name">
                <span className="stock-monogram">
                  <LineChart aria-hidden="true" size={18} />
                </span>
                <div>
                  <strong>{symbol}</strong>
                  <span>
                    {symbol === "BBRI"
                      ? "Bank Rakyat Indonesia"
                      : symbol === "TLKM"
                        ? "Telkom Indonesia"
                        : "IDX listed company"}
                  </span>
                </div>
              </div>
              <span>
                {automation.horizon === "days-to-weeks" ? "Days to weeks" : "Months to years"}
              </span>
              <span>
                {automation.triggers.priceMove
                  ? `Daily move ≥ ${automation.triggers.priceMoveThreshold}%`
                  : "Daily check"}
              </span>
              <time dateTime={run?.startedAt}>
                {run ? formatWib(run.startedAt) : "Awaiting run"}
              </time>
              <StatusBadge
                status={automation.conditionState === "stale" ? "degraded" : automation.status}
                label={
                  automation.conditionState === "true"
                    ? "Condition met"
                    : automation.conditionState === "false"
                      ? "Watching"
                      : automation.conditionState
                }
              />
              <Link
                className="icon-button"
                href="/app/activity"
                aria-label={`View ${symbol} evidence activity`}
              >
                <Eye aria-hidden="true" size={18} />
              </Link>
            </article>
          );
        })}
      </section>
      <p className="table-footnote">
        Prices are checked daily. Intraday monitoring is not available.
      </p>
    </div>
  );
}
