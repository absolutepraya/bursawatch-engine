import { ArrowRight, Inbox, Send, SlidersHorizontal } from "lucide-react";

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
};

export function ConnectedWorkflowSummary({ watcherId }: { watcherId: string }) {
  const workflow = workflows[watcherId];
  if (!workflow) return null;
  return (
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
  );
}
