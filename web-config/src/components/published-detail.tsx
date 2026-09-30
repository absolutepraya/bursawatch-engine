"use client";

import type { PublicationDetail as PublicationDetailData } from "@/lib/publications";
import { publicationOwnerLabels, publicationTypeLabels } from "@/lib/publications";
import "@/app/published.css";

export function PublishedDetail({
  detail,
  onBack,
  onSelect,
}: {
  detail: PublicationDetailData;
  onBack: () => void;
  onSelect: (publicationId: string) => void;
}) {
  const current = detail.versions.at(-1);
  if (!current) return null;
  return (
    <article className="published-detail">
      <button type="button" className="control-back" onClick={onBack}>
        Back to Published
      </button>
      <div className="published-detail-heading">
        <div>
          <p className="published-kind">
            {publicationTypeLabels[current.type]} · {publicationOwnerLabels[current.owner_id]}
          </p>
          <h1>{current.title}</h1>
          <p className="control-muted">
            {current.source_name}
            {current.ticker ? ` · ${current.ticker}` : ""}
          </p>
        </div>
        <span>Version {current.version}</span>
      </div>
      <dl className="published-metadata">
        <div>
          <dt>Delivered</dt>
          <dd>
            <time dateTime={current.delivery_confirmed_at}>
              {dateTime(current.delivery_confirmed_at)}
            </time>
          </dd>
        </div>
        <div>
          <dt>Source published</dt>
          <dd>
            {current.source_published_at ? (
              <time dateTime={current.source_published_at}>
                {dateTime(current.source_published_at)}
              </time>
            ) : (
              "Not provided"
            )}
          </dd>
        </div>
        <div>
          <dt>Market data as of</dt>
          <dd>
            {current.market_data_as_of ? (
              <time dateTime={current.market_data_as_of}>
                {dateTime(current.market_data_as_of)}
              </time>
            ) : (
              "Not provided"
            )}
          </dd>
        </div>
        {current.source_url ? (
          <div>
            <dt>Source</dt>
            <dd>
              <a href={current.source_url} target="_blank" rel="noopener noreferrer">
                Open source
              </a>
            </dd>
          </div>
        ) : null}
      </dl>
      {current.broker_levels ? (
        <section className="published-plan" aria-label="Broker plan levels">
          <h2>Broker plan levels</h2>
          <dl>
            <div>
              <dt>Entry</dt>
              <dd>{current.broker_levels.entry}</dd>
            </div>
            <div>
              <dt>Stop</dt>
              <dd>{current.broker_levels.stop}</dd>
            </div>
            <div>
              <dt>Targets</dt>
              <dd>{current.broker_levels.targets.join(", ")}</dd>
            </div>
            <div>
              <dt>Units</dt>
              <dd>{current.broker_levels.units}</dd>
            </div>
            <div>
              <dt>Attribution</dt>
              <dd>{current.broker_levels.attribution}</dd>
            </div>
          </dl>
        </section>
      ) : null}
      <section aria-label="Confirmed deliveries">
        <h2>Confirmed deliveries</h2>
        <p className="control-muted">
          These are the exact rendered output legs accepted from the publisher&apos;s confirmed delivery
          receipts.
        </p>
        <ol className="published-legs">
          {current.legs.map((leg) => (
            <li key={leg.operation_key}>
              <div>
                <strong>Destination {leg.destination}</strong>
                <span>Confirmed</span>
              </div>
              {leg.text ? <pre>{leg.text}</pre> : null}
              {leg.attachments.length ? (
                <ul>
                  {leg.attachments.map((file) => (
                    <li key={`${file.filename}:${file.discord_url ?? "none"}`}>
                      {file.discord_url ? (
                        <a href={file.discord_url} target="_blank" rel="noopener noreferrer">
                          {file.filename}
                        </a>
                      ) : (
                        file.filename
                      )}
                    </li>
                  ))}
                </ul>
              ) : null}
              {leg.message_url ? (
                <a href={leg.message_url} target="_blank" rel="noopener noreferrer">
                  Open confirmed Discord message
                </a>
              ) : null}
            </li>
          ))}
        </ol>
      </section>
      {current.parent_publication_id || detail.linked.length ? (
        <section aria-label="Related publications" className="published-related">
          <h2>Related publications</h2>
          {current.parent_publication_id ? (
            <button type="button" onClick={() => onSelect(current.parent_publication_id!)}>
              Open parent publication
            </button>
          ) : null}
          {detail.linked.map((linked) => (
            <button
              type="button"
              key={linked.publication_id}
              onClick={() => onSelect(linked.publication_id)}
            >
              {publicationTypeLabels[linked.type]} · {dateTime(linked.delivery_confirmed_at)}
            </button>
          ))}
        </section>
      ) : null}
      {detail.versions.length > 1 ? (
        <details className="published-versions">
          <summary>Earlier confirmed versions</summary>
          <ol>
            {detail.versions.slice(0, -1).map((version) => (
              <li key={version.version}>
                Version {version.version}: delivered {dateTime(version.delivery_confirmed_at)}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </article>
  );
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
