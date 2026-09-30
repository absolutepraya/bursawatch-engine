// @vitest-environment jsdom
import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ConnectedWorkflowSummary } from "./connected-workflow-summary";
import type { OperatorJob, OperatorObservation } from "@/lib/operator-inventory";

afterEach(cleanup);

const observedAt = "2026-09-30T04:00:00Z";
const job: OperatorJob = {
  job_id: "shared-reader",
  can_edit: true,
  watcher_id: null,
  component_ids: ["bursawatch-tg-source-ingest", "bursawatch-tg-market-news"],
  display_name: "Shared Telegram reader",
  runtime_job_key: "bursawatch-tg-source-ingest",
  schedule_kind: "interval",
  min_interval_seconds: 60,
  max_interval_seconds: 3600,
  schedule: {
    api_version: 1,
    job_id: "shared-reader",
    revision: 1,
    enabled: true,
    interval_seconds: 60,
    timezone: "Asia/Jakarta",
    schedule_sha256: "a".repeat(64),
    updated_at: observedAt,
  },
  reconciliation: { status: "applied", applied_revision: 1, effective: true, has_error: false },
};
const observation: OperatorObservation = {
  api_version: 1,
  identity_kind: "job",
  identity_id: job.job_id,
  observer_id: "vps-hermes-observer",
  observed_at: observedAt,
  received_at: observedAt,
  status: "enabled",
  freshness: "fresh",
  evidence: {
    runtime_job_key: job.runtime_job_key,
    enabled: true,
    schedule: { kind: "interval", minutes: 1 },
    last_execution: { at: observedAt, status: "success" },
  },
  comparison: "match",
  desired: job.schedule,
  reconciliation: { status: "applied", applied_revision: 1 },
};

it("links the component-scoped shared job and shows its observed state", () => {
  render(
    <ConnectedWorkflowSummary
      watcherId="bursawatch-tg-market-news"
      jobs={[job]}
      observations={[observation]}
    />,
  );

  expect(screen.getByRole("link", { name: "Shared Telegram reader" }).getAttribute("href")).toBe(
    "/workspace/jobs#job-shared-reader",
  );
  expect(screen.getByText("Observed active")).toBeTruthy();
});

it("does not present a failed job read as an empty relationship", () => {
  render(<ConnectedWorkflowSummary watcherId="bursawatch-tg-market-news" jobsUnavailable />);

  expect(screen.getByText("Job records unavailable. Reload to check their status.")).toBeTruthy();
  expect(screen.queryByText("No linked jobs")).toBeNull();
});

it("labels observation read failures separately from reconciled schedule state", () => {
  render(
    <ConnectedWorkflowSummary
      watcherId="bursawatch-tg-market-news"
      jobs={[job]}
      observationsUnavailable
    />,
  );

  expect(screen.getByText("Observation unavailable")).toBeTruthy();
});
