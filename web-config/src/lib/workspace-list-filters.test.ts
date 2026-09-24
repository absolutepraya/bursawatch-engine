import { describe, expect, it } from "vitest";
import type { ControlRun, ControlWatcher } from "@/server/control-plane";
import { filterWorkspaceRuns, filterWorkspaceWatchers } from "@/lib/workspace-list-filters";

const watchers: ControlWatcher[] = [
  {
    watcher_id: "bursawatch-tg-market-news",
    display_name: "Market news",
    current_revision: 3,
    updated_at: "2026-09-24T04:00:00Z",
  },
  {
    watcher_id: "bursawatch-x-account-watch",
    display_name: "X account watch",
    current_revision: null,
    updated_at: "2026-09-24T04:00:00Z",
  },
];

const runs: ControlRun[] = [
  {
    run_id: "market-source-poll",
    watcher_id: watchers[0].watcher_id,
    scheduler_job_id: "market-hourly",
    trigger: "schedule",
    config_revision: 3,
    started_at: "2026-09-24T04:00:00Z",
    finished_at: "2026-09-24T04:01:00Z",
    status: "ok",
  },
  {
    run_id: "x-queue-drain",
    watcher_id: watchers[1].watcher_id,
    scheduler_job_id: null,
    trigger: "queue",
    config_revision: 1,
    started_at: "2026-09-24T03:00:00Z",
    finished_at: "2026-09-24T03:01:00Z",
    status: "failed",
  },
];

describe("workspace list filters", () => {
  it("matches workflow names and IDs, then applies the saved configuration filter", () => {
    expect(filterWorkspaceWatchers(watchers, " MARKET  news ", "configured")).toEqual([
      watchers[0],
    ]);
    expect(filterWorkspaceWatchers(watchers, "account watch", "needs-setup")).toEqual([
      watchers[1],
    ]);
    expect(filterWorkspaceWatchers(watchers, "bursawatch-x", "configured")).toEqual([]);
  });

  it("combines run search, workflow and outcome without changing returned order", () => {
    expect(filterWorkspaceRuns(runs, watchers, "", "all", "all")).toEqual(runs);
    expect(filterWorkspaceRuns(runs, watchers, "x queue", "all", "failed")).toEqual([runs[1]]);
    expect(
      filterWorkspaceRuns(runs, watchers, "source poll", watchers[0].watcher_id, "ok"),
    ).toEqual([runs[0]]);
    expect(filterWorkspaceRuns(runs, watchers, "queue", watchers[0].watcher_id, "all")).toEqual([]);
  });
});
