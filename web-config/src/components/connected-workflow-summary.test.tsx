// @vitest-environment jsdom
import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ConnectedWorkflowSummary } from "./connected-workflow-summary";
import type { OperatorComponent, OperatorJob } from "@/lib/operator-inventory";

afterEach(cleanup);

const job: OperatorJob = {
  job_id: "shared-reader",
  can_edit: true,
  watcher_id: null,
  component_ids: ["bursawatch-tg-source-ingest", "bursawatch-tg-market-news"],
  display_name: "Shared Telegram reader",
  runtime_job_key: "bursawatch-tg-source-ingest",
  schedule_kind: "interval",
  min_interval_seconds: 300,
  max_interval_seconds: 3600,
  schedule: null,
  reconciliation: {
    status: "pending",
    applied_revision: null,
    effective: false,
    has_error: false,
  },
};

const components: OperatorComponent[] = [
  {
    inventory_version: 1,
    component_id: "bursawatch-tg-market-news",
    kind: "domain_owner",
    display_name: "Market News",
    capabilities: [],
    pipeline_ids: [],
    config_resource_ids: ["bursawatch-tg-market-news"],
    related_component_ids: ["bursawatch-tg-source-ingest"],
    job_ids: [job.job_id],
  },
  {
    inventory_version: 1,
    component_id: "bursawatch-tg-source-ingest",
    kind: "source_adapter",
    display_name: "Telegram Source Inbox",
    capabilities: [],
    pipeline_ids: [],
    config_resource_ids: [],
    related_component_ids: [],
    job_ids: [job.job_id],
  },
];

it("links a workflow's shared job to its single Jobs entry", () => {
  render(
    <ConnectedWorkflowSummary
      watcherId="bursawatch-tg-market-news"
      components={components}
      jobs={[job]}
    />,
  );

  expect(screen.getByRole("link", { name: "Shared Telegram reader" }).getAttribute("href")).toBe(
    "/workspace/jobs#job-shared-reader",
  );
  expect(screen.getByText("Telegram Source Inbox")).toBeTruthy();
});
