import { ArrowRight, Inbox, Send, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import type { OperatorJob, OperatorObservation } from "@/lib/operator-inventory";
import { latestOperatorObservations, observedJobState } from "@/lib/control-analytics";

const stateLabels = {
  active: "Observed active",
  paused: "Observed paused",
  pending: "Pending reconciliation",
  error: "Reconciliation error",
  mismatch: "Observed schedule mismatch",
  stale: "Stale observation",
  unknown: "Unknown",
} as const;

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
  jobs = [],
  observations = [],
  jobsUnavailable = false,
  observationsUnavailable = false,
  basePath = "/workspace",
  sampleMode = false,
}: {
  watcherId: string;
  jobs?: OperatorJob[];
  observations?: OperatorObservation[];
  jobsUnavailable?: boolean;
  observationsUnavailable?: boolean;
  basePath?: string;
  sampleMode?: boolean;
}) {
  const workflow = workflows[watcherId];
  if (!workflow) return null;
  const observationById = latestOperatorObservations(observations);
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
          <strong>{sampleMode ? "Sample job records" : "Shared jobs"}</strong>
          {jobsUnavailable ? (
            <span>Job records unavailable. Reload to check their status.</span>
          ) : jobs.length ? (
            <ul>
              {jobs.map((job) => {
                const observation = observationById.get(`job:${job.job_id}`);
                const state = observationsUnavailable
                  ? "Observation unavailable"
                  : sampleMode
                    ? "Example record, no live status"
                    : stateLabels[observedJobState(job, observation)];
                return (
                  <li key={job.job_id}>
                    <Link href={`${basePath}/jobs#job-${job.job_id}`}>{job.display_name}</Link>
                    <span>{state}</span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <span>No linked jobs</span>
          )}
        </div>
      </section>
    </>
  );
}
