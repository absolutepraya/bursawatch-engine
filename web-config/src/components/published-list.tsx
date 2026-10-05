"use client";

import type { Publication, PublicationCoverage } from "@/lib/publications";
import { publicationOwnerLabels, publicationTypeLabels } from "@/lib/publications";
import "@/app/published.css";

export type PublishedFilter = {
  group: "all" | "news" | "swing";
  type: Publication["type"] | "all";
  ticker: string;
  source: string;
};

export function PublishedList({
  items,
  coverage,
  cursor,
  filter,
  loading,
  error,
  onFilter,
  onMore,
  onSelect,
}: {
  items: Publication[];
  coverage: PublicationCoverage | null;
  cursor: string | null;
  filter: PublishedFilter;
  loading: boolean;
  error: string;
  onFilter: (next: PublishedFilter) => void;
  onMore: () => void;
  onSelect: (publicationId: string) => void;
}) {
  const boundary = coverage?.cutover?.boundary;
  const coverageProblem = coverage === null || coverage.overall_status !== "complete";
  const shown = items.filter((item) => {
    if (filter.group === "news" && isSwing(item.type)) return false;
    if (filter.group === "swing" && !isSwing(item.type)) return false;
    return true;
  });
  return (
    <section className="published-feed" aria-label="Published records">
      <div className="published-coverage" role="status">
        <strong>
          {boundary ? `Published since ${dateTime(boundary)}` : "Publication feed not started"}
        </strong>
        <p>
          {coverageProblem
            ? "Coverage is incomplete or unverified. A missing item does not prove nothing was published."
            : "All required publishers reported a current comparison. Coverage ends at each publisher's last check."}
        </p>
        <p>
          {"A confirmed record documents delivery at that time. "}
          {"Check Discord to see whether it is still visible."}
        </p>
        {coverage?.owners.length ? (
          <details>
            <summary>Publisher coverage</summary>
            <ul>
              {coverage.owners.map((owner) => (
                <li key={owner.owner_id}>
                  <span>{publicationOwnerLabels[owner.owner_id]}</span>
                  <strong>{owner.status}</strong>
                  {owner.checkpoint ? (
                    <time dateTime={owner.checkpoint.compared_at}>
                      {dateTime(owner.checkpoint.compared_at)}
                    </time>
                  ) : null}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>
      <div className="published-filters">
        <div role="group" aria-label="Publication group" className="published-group">
          {(["all", "news", "swing"] as const).map((group) => (
            <button
              key={group}
              type="button"
              aria-pressed={filter.group === group}
              onClick={() => onFilter({ ...filter, group })}
            >
              {group === "all" ? "All" : group === "news" ? "News" : "Swing"}
            </button>
          ))}
        </div>
        <label>
          Ticker
          <input
            value={filter.ticker}
            maxLength={20}
            placeholder="Optional"
            onChange={(event) => onFilter({ ...filter, ticker: event.target.value.toUpperCase() })}
          />
        </label>
        <label>
          Source
          <input
            value={filter.source}
            maxLength={200}
            placeholder="Publisher name"
            onChange={(event) => onFilter({ ...filter, source: event.target.value })}
          />
        </label>
      </div>
      {error ? (
        <p className="control-alert" role="alert">
          {error}
        </p>
      ) : null}
      {shown.length === 0 && !loading ? (
        <div className="control-empty">
          <p>
            {boundary
              ? "No confirmed publications in this view since the cutover."
              : "The forward-only feed has not been activated."}
          </p>
          {coverageProblem ? (
            <p>Check publisher coverage before treating this as a complete result.</p>
          ) : null}
        </div>
      ) : (
        <ol className="published-rows">
          {shown.map((item) => (
            <li key={item.publication_id}>
              <button type="button" onClick={() => onSelect(item.publication_id)}>
                <span className="published-row-top">
                  <strong>{item.title}</strong>
                  <span>{publicationTypeLabels[item.type]}</span>
                </span>
                <span className="published-row-meta">
                  {publicationOwnerLabels[item.owner_id]} · {item.ticker ?? item.source_name} ·
                  Delivered {dateTime(item.delivery_confirmed_at)}
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
      {cursor ? (
        <button type="button" className="button secondary" disabled={loading} onClick={onMore}>
          {loading ? "Loading…" : "Load more"}
        </button>
      ) : null}
      {loading && shown.length === 0 ? <p role="status">Loading confirmed publications…</p> : null}
    </section>
  );
}

export function isSwing(type: Publication["type"]): boolean {
  return [
    "broker_swing_plan",
    "broker_swing_update",
    "swing_context",
    "swing_bundle",
    "swing_board_update",
  ].includes(type);
}

function dateTime(value: string): string {
  return (
    new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Jakarta",
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(value)) + " WIB"
  );
}
