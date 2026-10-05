// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { OperatorJobs } from "./operator-jobs";
import { ToastProvider } from "./toast-provider";
import type { OperatorComponent, OperatorJob, OperatorObservation } from "@/lib/operator-inventory";
import { watcherNames } from "@/lib/watcher-fields";

afterEach(cleanup);

const time = "2026-09-30T02:00:00+00:00";
const job: OperatorJob = {
  job_id: "shared-reader",
  can_edit: true,
  watcher_id: null,
  component_ids: ["telegram-adapter", "news-owner"],
  display_name: "Shared Telegram reader",
  runtime_job_key: "bursawatch-tg-source-ingest",
  schedule_kind: "interval",
  min_interval_seconds: 300,
  max_interval_seconds: 3600,
  schedule: {
    api_version: 1,
    job_id: "shared-reader",
    revision: 3,
    enabled: true,
    interval_seconds: 600,
    timezone: "Asia/Jakarta",
    schedule_sha256: "a".repeat(64),
    updated_at: time,
  },
  reconciliation: { status: "applied", applied_revision: 3, effective: true, has_error: false },
};
const components: OperatorComponent[] = [
  {
    inventory_version: 1,
    component_id: "telegram-adapter",
    kind: "source_adapter",
    display_name: "Telegram Source Inbox",
    capabilities: [],
    pipeline_ids: [],
    config_resource_ids: [],
    related_component_ids: [],
    job_ids: [job.job_id],
  },
  {
    inventory_version: 1,
    component_id: "news-owner",
    kind: "domain_owner",
    display_name: "Market News",
    capabilities: [],
    pipeline_ids: [],
    config_resource_ids: ["bursawatch-tg-market-news"],
    related_component_ids: ["telegram-adapter"],
    job_ids: [job.job_id],
  },
];
const mismatch: OperatorObservation = {
  api_version: 1,
  identity_kind: "job",
  identity_id: job.job_id,
  observer_id: "observer",
  observed_at: time,
  received_at: time,
  status: "enabled",
  freshness: "fresh",
  evidence: {
    runtime_job_key: job.runtime_job_key,
    enabled: true,
    schedule: { kind: "interval", minutes: 20 },
    last_execution: { at: time, status: "success" },
  },
  comparison: "mismatch",
  desired: job.schedule,
  reconciliation: { status: "applied", applied_revision: 3 },
};

function view(current: OperatorJob, relatedComponents = components) {
  return render(
    <ToastProvider>
      <OperatorJobs
        jobs={[current]}
        components={relatedComponents}
        observations={[mismatch]}
        request={vi.fn()}
        onDirtyChange={vi.fn()}
      />
    </ToastProvider>,
  );
}

it("names every affected component before the shared schedule control", () => {
  view(job);
  expect(
    screen.getByText(/changing this schedule affects Telegram Source Inbox, Market News/),
  ).toBeTruthy();
  expect(screen.getByRole("button", { name: "Save schedule" })).toBeTruthy();
  expect(document.getElementById("job-shared-reader")).toBeTruthy();
});

it("shows an observed mismatch and removes save controls for viewers", () => {
  view({ ...job, can_edit: false });
  expect(screen.getByText("Observed schedule mismatch")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Save schedule" })).toBeNull();
  expect(screen.getByText(/You have view access/)).toBeTruthy();
});

it.each(Object.keys(watcherNames))(
  "resolves the backend watcher resource for %s for viewers and admins",
  (watcherId) => {
    const owner = {
      ...components[1],
      config_resource_ids: ["source-catalog", `watcher:${watcherId}`],
    };
    for (const canEdit of [false, true]) {
      const rendered = view({ ...job, can_edit: canEdit }, [components[0], owner]);
      expect(screen.getByRole("link", { name: "Market News" }).getAttribute("href")).toBe(
        `/workspace/workflows?watcher=${watcherId}`,
      );
      expect(screen.getByRole("link", { name: "Telegram Source Inbox" }).getAttribute("href")).toBe(
        "/workspace/sources",
      );
      rendered.unmount();
    }
  },
);

it.each(
  [
    [],
    ["source-catalog"],
    ["watcher:"],
    ["watcher:unknown-workflow"],
    ["pipeline:bursawatch-tg-market-news"],
    ["watcher:watcher:bursawatch-tg-market-news"],
    ["watcher:bursawatch-tg-market-news", "watcher:bursawatch-stockbit-snips"],
  ].map((resources) => ({ resources })),
)(
  "keeps unresolved or ambiguous resources readable without a bogus workflow link: $resources",
  ({ resources }) => {
    view(job, [components[0], { ...components[1], config_resource_ids: resources }]);
    expect(screen.queryByRole("link", { name: "Market News" })).toBeNull();
    expect(screen.getAllByText("Market News").length).toBeGreaterThan(0);
  },
);

it("retains bare watcher compatibility and ignores duplicate references", () => {
  view(job, [
    components[0],
    {
      ...components[1],
      config_resource_ids: ["bursawatch-tg-market-news", "watcher:bursawatch-tg-market-news"],
    },
  ]);
  expect(screen.getByRole("link", { name: "Market News" }).getAttribute("href")).toBe(
    "/workspace/workflows?watcher=bursawatch-tg-market-news",
  );
});

it("does not link a delivery service even when a watcher resource is present", () => {
  view(job, [
    {
      ...components[1],
      kind: "delivery_service",
      config_resource_ids: ["watcher:bursawatch-tg-market-news"],
    },
  ]);
  expect(screen.queryByRole("link", { name: "Market News" })).toBeNull();
});
