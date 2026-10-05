// @vitest-environment jsdom
import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ControlDashboard, ControlWatcherList } from "./control-dashboard";
import { SearchableWorkflowList } from "./workspace-list-filters";
import type { OperatorComponent, OperatorJob, OperatorObservation } from "@/lib/operator-inventory";
import type { ControlRun, ControlWatcher } from "@/server/control-plane";

afterEach(cleanup);

const watchers: ControlWatcher[] = [
  {
    watcher_id: "market-news",
    display_name: "Market News",
    current_revision: 3,
    updated_at: "2026-09-30T09:00:00+07:00",
  },
  {
    watcher_id: "swing-watch",
    display_name: "Swing Watch",
    current_revision: 4,
    updated_at: "2026-09-30T09:00:00+07:00",
  },
];

const runs: ControlRun[] = [
  {
    run_id: "news-latest",
    watcher_id: "market-news",
    scheduler_job_id: null,
    trigger: "queue",
    config_revision: 3,
    started_at: "2026-09-30T10:00:00+07:00",
    finished_at: "2026-09-30T10:00:03+07:00",
    status: "ok",
  },
  {
    run_id: "swing-latest",
    watcher_id: "swing-watch",
    scheduler_job_id: null,
    trigger: "queue",
    config_revision: 2,
    started_at: "2026-09-30T10:00:00+07:00",
    finished_at: "2026-09-30T10:00:03+07:00",
    status: "ok",
  },
];

it("shows the saved revision used by the latest run and flags an older loaded revision", () => {
  render(
    <ControlWatcherList
      watchers={watchers}
      runs={runs}
      jobs={[]}
      updatedAt="2026-09-30T10:05:00+07:00"
      onSelectWatcher={() => {}}
    />,
  );

  expect(screen.getByText("Last run used saved v3")).toBeTruthy();
  expect(screen.getByText("Saved v4, use unverified; last run used v2")).toBeTruthy();
});

const time = "2026-09-30T10:05:00+07:00";
const sharedJob: OperatorJob = {
  job_id: "shared-reader",
  can_edit: false,
  watcher_id: null,
  component_ids: ["news-owner"],
  display_name: "Shared Telegram reader",
  runtime_job_key: "synthetic-reader",
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
    updated_at: time,
  },
  reconciliation: { status: "applied", applied_revision: 1, effective: true, has_error: false },
};
const owner: OperatorComponent = {
  inventory_version: 1,
  component_id: "news-owner",
  kind: "domain_owner",
  display_name: "News owner",
  capabilities: [],
  pipeline_ids: [],
  config_resource_ids: ["watcher:market-news"],
  related_component_ids: [],
  job_ids: [sharedJob.job_id],
};
const observed: OperatorObservation = {
  api_version: 1,
  identity_kind: "job",
  identity_id: sharedJob.job_id,
  observer_id: "synthetic-observer",
  observed_at: time,
  received_at: time,
  status: "enabled",
  freshness: "fresh",
  comparison: "match",
  evidence: {
    runtime_job_key: sharedJob.runtime_job_key,
    enabled: true,
    schedule: { kind: "interval", minutes: 1 },
    last_execution: { at: time, status: "success" },
  },
};
it("keeps catalog rows free of runtime claims even with prior records", () => {
  render(
    <SearchableWorkflowList
      watchers={watchers}
      jobs={[]}
      runs={runs}
      updatedAt={time}
      components={[owner]}
      operatorJobs={[sharedJob]}
      observations={[observed]}
      onSelectWatcher={() => {}}
    />,
  );
  expect(screen.getByText("Configuration v3 · Open to review settings")).toBeTruthy();
  expect(screen.getAllByText("Configure")).toHaveLength(2);
  expect(document.querySelector(".control-watcher-operator-evidence")).toBeNull();
  expect(document.querySelector("time")).toBeNull();
  expect(
    screen.queryByText(/active schedules|No recorded run|unavailable|use unverified/),
  ).toBeNull();
});
function overview(overrides: Partial<Parameters<typeof ControlDashboard>[0]> = {}) {
  render(
    <ControlDashboard
      watchers={[watchers[0]]}
      jobs={[]}
      runs={runs}
      updatedAt={time}
      refreshing={false}
      onRefresh={() => {}}
      onSelectWatcher={() => {}}
      onSelectRun={() => {}}
      components={[owner]}
      operatorJobs={[sharedJob]}
      observations={[observed]}
      {...overrides}
    />,
  );
  return document.querySelector(".control-watcher-operator-evidence")!;
}
it("passes loaded shared-job evidence through Overview to its watcher rows", () => {
  const evidence = overview();
  expect(evidence.textContent).toContain("Shared Telegram reader (active)");
  expect(evidence.querySelector("a")?.getAttribute("href")).toBe("/workspace/jobs");
  expect(evidence.textContent).not.toContain("unavailable");
});
it.each([
  ["paused", { ...observed, status: "disabled" as const }],
  ["stale", { ...observed, freshness: "stale" as const }],
  ["mismatch", { ...observed, comparison: "mismatch" as const }],
  ["unknown", undefined],
])("preserves %s observed states in Overview rows", (label, observation) => {
  const evidence = overview({ observations: observation ? [observation] : [] });
  expect(evidence.textContent).toContain(`Shared Telegram reader (${label})`);
});
it.each(["components", "operator-jobs"])(
  "distinguishes a failed %s read from an empty relationship",
  (resource) => {
    const evidence = overview({ operatorIssues: [{ resource, message: "Safe failure" }] });
    expect(evidence.textContent).toContain("Shared job relationship unavailable");
    expect(evidence.textContent).not.toContain("(active)");
  },
);
it("retains job identity while marking failed observations unavailable", () => {
  const evidence = overview({
    observations: [],
    operatorIssues: [{ resource: "observations", message: "Safe failure" }],
  });
  expect(evidence.textContent).toContain("Shared Telegram reader (status unavailable)");
});
it("does not describe configuration use as unverified after a failed history read", () => {
  const evidence = overview({
    runs: [],
    issues: [{ watcherId: "market-news", resource: "runs", message: "Safe failure" }],
  });
  expect(evidence.textContent).toContain("Configuration use unavailable");
  expect(evidence.textContent).not.toContain("Saved, use unverified");
});
