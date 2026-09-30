// @vitest-environment jsdom
import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ControlWatcherList } from "./control-dashboard";
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
