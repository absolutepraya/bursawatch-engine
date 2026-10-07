import Link from "next/link";
import { ArrowUpRight, Info } from "lucide-react";
import type { ControlConfigSnapshot, ControlJob, ControlRun } from "@/server/control-plane";
import { xDeliveryStatus } from "@/lib/x-delivery-status";
import { controlStatusLabels } from "@/lib/control-analytics";

export function XDeliveryStatus({
  snapshot,
  jobs,
  runs,
  loading,
  unavailable,
  basePath = "/workspace",
  sampleMode = false,
}: {
  snapshot: ControlConfigSnapshot;
  jobs: ControlJob[];
  runs: ControlRun[];
  loading: boolean;
  unavailable: boolean;
  basePath?: string;
  sampleMode?: boolean;
}) {
  if (sampleMode)
    return (
      <section className="x-delivery-check" aria-labelledby="x-delivery-title">
        <div className="x-delivery-heading">
          <Info size={18} aria-hidden="true" />
          <h2 id="x-delivery-title">X to Discord checks</h2>
        </div>
        <p>
          This is a sample X profile configuration. It does not poll X, run a watcher, or deliver to
          Discord.
        </p>
        <Link href={`${basePath}/jobs`}>Review sample Jobs</Link>
      </section>
    );
  const state = xDeliveryStatus(snapshot.revision, jobs, runs);
  const latest = state.latestSourceRun;
  return (
    <section className="x-delivery-check" aria-labelledby="x-delivery-title">
      <div className="x-delivery-heading">
        <Info size={18} aria-hidden="true" />
        <h2 id="x-delivery-title">X → Discord checks</h2>
      </div>
      <dl>
        <div>
          <dt>Saved settings</dt>
          <dd>Revision {snapshot.revision}</dd>
        </div>
        <div>
          <dt>Source polling</dt>
          <dd>
            {loading
              ? "Checking…"
              : unavailable
                ? "Status unavailable"
                : state.schedule === "active"
                  ? `Every ${Math.round((state.job?.schedule?.interval_seconds ?? 0) / 60)} minutes`
                  : state.schedule === "paused"
                    ? "Paused"
                    : "Not confirmed by scheduler"}
          </dd>
        </div>
        <div>
          <dt>Latest source run</dt>
          <dd>
            {loading
              ? "Checking…"
              : unavailable
                ? "History unavailable"
                : latest
                  ? `${controlStatusLabels[latest.status]} · revision ${latest.config_revision}`
                  : "Not in returned history"}
          </dd>
        </div>
      </dl>
      {!loading && !unavailable && !state.revisionObserved ? (
        <p>
          No source-poll run using revision {snapshot.revision} is visible yet. A saved revision or
          a queue-worker run does not mean X has been checked.
        </p>
      ) : null}
      <details>
        <summary>A post has not arrived?</summary>
        <ol>
          <li>
            Open the account below. Enable “Watch this source”, choose eligible post types, and save
            its Discord destination.
          </li>
          <li>
            A new account’s first successful nonempty poll establishes a starting point. Tweets
            already present at that poll are not forwarded.
          </li>
          <li>
            After initialization, only new eligible posts enter the queue. Relevance filtering can
            skip personal or test posts; thread handling can add the configured wait.
          </li>
          <li>
            Inspect the source run for fetch failures, then the queue run for processing or delivery
            failures. Your workspace owner can check RSSHub, X rate limits and Discord permissions.
          </li>
        </ol>
        <p>
          These checks do not confirm that a particular account was fetched or a message was
          delivered. The web cannot reset cursors, replay a tweet or verify Discord permissions.
        </p>
      </details>
      <div className="x-delivery-links">
        <Link href={`${basePath}/jobs`}>
          Review Jobs <ArrowUpRight size={15} aria-hidden="true" />
        </Link>
        {latest ? (
          <Link href={`${basePath}/history?run=${encodeURIComponent(latest.run_id)}`}>
            Inspect source run <ArrowUpRight size={15} aria-hidden="true" />
          </Link>
        ) : (
          <Link href={`${basePath}/history`}>
            Open run history <ArrowUpRight size={15} aria-hidden="true" />
          </Link>
        )}
      </div>
    </section>
  );
}
