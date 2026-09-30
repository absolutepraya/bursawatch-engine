import { ArrowRight, Inbox, Send, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import type { OperatorComponent, OperatorJob, OperatorObservation } from "@/lib/operator-inventory";
import { observedJobState } from "@/lib/control-analytics";

const workflows: Record<string, { input: string; processing: string; output: string }> = {
  "bursawatch-x-account-watch": {
    input: "X accounts",
    processing: "Post filters, threads and summaries",
    output: "Discord channels",
  },
  "bursawatch-ig-account-watch": {
    input: "Instagram accounts",
    processing: "Posts, reels and image text",
    output: "Discord channels",
  },
  "bursawatch-wa-channel-watch": {
    input: "WhatsApp Channels",
    processing: "Relevance, summaries and routing",
    output: "Discord channels",
  },
  "bursawatch-tg-market-news": {
    input: "Telegram news sources",
    processing: "Company, industry and macro news",
    output: "Discord channels",
  },
  "bursawatch-tg-phintraco-swing": {
    input: "Telegram swing calls",
    processing: "Original source calls and updates",
    output: "Discord alerts",
  },
  "bursawatch-tg-kelas-investasi-gtw": {
    input: "Telegram research bundles",
    processing: "Completed bundles and summaries",
    output: "Discord alerts",
  },
  "bursawatch-dc-swing-board": {
    input: "Source-backed plans",
    processing: "Closing-price checks and plan status",
    output: "Discord swing board",
  },
  "bursawatch-stockbit-snips": {
    input: "Four Stockbit Snips feeds",
    processing: "Article analysis and source summaries",
    output: "Two Discord news routes",
  },
};

export function ConnectedWorkflowSummary({
  watcherId,
  components = [],
  jobs = [],
  observations = [],
}: {
  watcherId: string;
  components?: OperatorComponent[];
  jobs?: OperatorJob[];
  observations?: OperatorObservation[];
}) {
  const workflow = workflows[watcherId];
  if (!workflow) return null;
  const owner = components.find((item) => item.component_id === watcherId);
  const componentById = new Map(components.map((item) => [item.component_id, item]));
  const jobById = new Map(jobs.map((item) => [item.job_id, item]));
  const observationById = new Map(observations.map((item) => [item.identity_id, item]));
  const inputs =
    owner?.related_component_ids
      .map((id) => componentById.get(id))
      .filter((item) => item?.kind === "source_adapter") ?? [];
  return (
    <>
      <section className="control-workflow-flow" aria-label="Workflow capabilities">
        <div>
          <Inbox size={20} aria-hidden="true" />
          <span>
            <small>Input</small>
            <strong>{workflow.input}</strong>
          </span>
        </div>
        <ArrowRight className="control-flow-arrow" size={16} aria-hidden="true" />
        <div>
          <SlidersHorizontal size={20} aria-hidden="true" />
          <span>
            <small>Processing</small>
            <strong>{workflow.processing}</strong>
          </span>
        </div>
        <ArrowRight className="control-flow-arrow" size={16} aria-hidden="true" />
        <div>
          <Send size={20} aria-hidden="true" />
          <span>
            <small>Output</small>
            <strong>{workflow.output}</strong>
          </span>
        </div>
      </section>
      <section className="control-workflow-runtime" aria-label="Runtime relationships">
        <div>
          <strong>Input owners</strong>
          <span>
            {inputs.length
              ? inputs.map((item) => item!.display_name).join(", ")
              : "Input relationship unavailable"}
          </span>
        </div>
        <div>
          <strong>Shared jobs</strong>
          {owner?.job_ids.length ? (
            <ul>
              {owner.job_ids.map((jobId) => {
                const job = jobById.get(jobId);
                const observation = observationById.get(jobId);
                const state = job
                  ? observedJobState(job, observation)
                  : observation
                    ? observation.freshness === "stale"
                      ? "stale"
                      : observation.status
                    : "unknown";
                return (
                  <li key={jobId}>
                    <Link href={`/workspace/jobs?job=${encodeURIComponent(jobId)}`}>
                      {job?.display_name ?? jobId}
                    </Link>
                    <span>{state}</span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <span>No declared jobs</span>
          )}
        </div>
      </section>
    </>
  );
}
