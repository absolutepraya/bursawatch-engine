import { describe, expect, it, vi } from "vitest";
import type { ControlRun, ControlWatcher } from "@/server/control-plane";
import { controlBrowser, WorkspaceError } from "./control-browser";
import { xWatcherId } from "./x-delivery-status";
import {
  loadWorkspaceRecords,
  type WorkspaceProgress,
  type WorkspaceView,
} from "./workspace-loader";

const watchers: ControlWatcher[] = Array.from({ length: 5 }, (_, index) => ({
  watcher_id: `source-${index}`,
  display_name: `Source ${index}`,
  current_revision: 1,
  updated_at: "2026-09-21T00:00:00Z",
}));
type Requester = ReturnType<typeof controlBrowser>;
function operatorJobFor(componentId: string) {
  const jobId = `shared-job-${componentId}`;
  return {
    job_id: jobId,
    can_edit: false,
    watcher_id: null,
    component_ids: [componentId],
    display_name: `Shared ${componentId} job`,
    runtime_job_key: jobId,
    schedule_kind: "interval" as const,
    min_interval_seconds: 60,
    max_interval_seconds: 3600,
    schedule: {
      api_version: 1 as const,
      job_id: jobId,
      revision: 1,
      enabled: true,
      interval_seconds: 60,
      timezone: "Asia/Jakarta" as const,
      schedule_sha256: "a".repeat(64),
      updated_at: "2026-09-21T00:00:00Z",
    },
    reconciliation: {
      status: "applied" as const,
      applied_revision: 1,
      last_error: null,
      effective: true,
    },
  };
}
function requester(
  fn: (path: string, payload?: unknown, options?: { signal?: AbortSignal }) => Promise<unknown>,
): Requester {
  return fn as Requester;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (failure: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
async function flush() {
  for (let index = 0; index < 8; index++) await Promise.resolve();
}

describe("scoped workspace loading", () => {
  it.each([
    ["overview", null, 16, ["jobs", "runs"]],
    ["sources", null, 1, []],
    ["jobs", null, 3, []],
    ["workflows", null, 1, []],
    ["workflows", "source-2", 4, ["jobs", "jobs", "observations"]],
    ["workflows", xWatcherId, 5, ["jobs", "jobs", "observations", "runs"]],
    ["workflows", "unlisted", 1, []],
    ["history", null, 7, ["runs"]],
    ["settings", null, 0, []],
  ] as const)(
    "loads only needed records for %s with selection %s",
    async (view, watcherId, count, resources) => {
      const catalog = [...watchers, { ...watchers[0], watcher_id: xWatcherId }];
      const read = vi.fn(async (path: string) =>
        path === "watchers"
          ? catalog
          : path === "components"
            ? { inventory_version: 1, components: [] }
            : path.startsWith("jobs?component_id=")
              ? [operatorJobFor(decodeURIComponent(path.split("=")[1]))]
              : [],
      );
      const records = await loadWorkspaceRecords(requester(read), {
        view: view as WorkspaceView,
        watcherId,
      });
      expect(read).toHaveBeenCalledTimes(count);
      if (["overview", "workflows", "history"].includes(view))
        expect(read.mock.calls[0][0]).toBe("watchers");
      const globalPaths =
        view === "overview"
          ? ["components", "jobs", "observations"]
          : view === "sources"
            ? ["components"]
            : view === "jobs"
              ? ["components", "jobs", "observations"]
              : [];
      const scopedWorkflowPaths =
        view === "workflows" && watcherId
          ? [
              `jobs?component_id=${encodeURIComponent(watcherId)}`,
              `observations?job_id=shared-job-${encodeURIComponent(watcherId)}`,
            ]
          : [];
      expect(
        read.mock.calls
          .slice(1)
          .every(
            ([path]) =>
              globalPaths.includes(path) ||
              scopedWorkflowPaths.includes(path) ||
              resources.some((resource) => path.endsWith(`/${resource}`)),
          ),
      ).toBe(true);
      if (watcherId)
        expect(
          read.mock.calls
            .slice(1)
            .filter(([path]) => String(path).startsWith("watchers/"))
            .every(([path]) => path.startsWith(`watchers/${watcherId}/`)),
        ).toBe(true);
      expect(records.watchers).toEqual(
        ["overview", "workflows", "history"].includes(view) ? catalog : [],
      );
      expect(records.issues).toEqual([]);
    },
  );

  it("publishes the catalog before waiting for selected diagnostics", async () => {
    const details = deferred<never[]>();
    const onCatalog = vi.fn();
    const catalog = [{ ...watchers[0], watcher_id: xWatcherId }];
    const request = requester(async (path) =>
      path === "watchers"
        ? catalog
        : path === "components"
          ? { inventory_version: 1, components: [] }
          : details.promise,
    );
    const result = loadWorkspaceRecords(request, {
      view: "workflows",
      watcherId: xWatcherId,
      onCatalog,
    });
    await flush();
    expect(onCatalog).toHaveBeenCalledExactlyOnceWith(catalog);
    details.resolve([]);
    await result;
  });

  it.each([
    "bursawatch-ig-account-watch",
    "bursawatch-wa-channel-watch",
    "bursawatch-tg-market-news",
    "bursawatch-tg-kelas-investasi-gtw",
    "bursawatch-tg-phintraco-swing",
    "bursawatch-dc-swing-board",
  ])("loads schedules without unrelated run history for the %s editor", async (watcherId) => {
    const catalog = [{ ...watchers[0], watcher_id: watcherId }];
    const read = vi.fn(async (path: string) =>
      path === "watchers"
        ? catalog
        : path === "components"
          ? { inventory_version: 1, components: [] }
          : path.startsWith("jobs?component_id=")
            ? [operatorJobFor(watcherId)]
            : [],
    );
    const records = await loadWorkspaceRecords(requester(read), {
      view: "workflows",
      watcherId,
    });
    expect(read).toHaveBeenCalledTimes(4);
    expect(read.mock.calls[0]).toEqual(["watchers", undefined, expect.any(Object)]);
    expect(read.mock.calls[1]).toEqual([
      `watchers/${watcherId}/jobs`,
      undefined,
      expect.any(Object),
    ]);
    expect(read.mock.calls[2]).toEqual([
      `jobs?component_id=${encodeURIComponent(watcherId)}`,
      undefined,
      expect.any(Object),
    ]);
    expect(read.mock.calls[3]).toEqual([
      `observations?job_id=shared-job-${encodeURIComponent(watcherId)}`,
      undefined,
      expect.any(Object),
    ]);
    expect(records).toMatchObject({
      watchers: catalog,
      jobs: [],
      runs: [],
      components: [],
      operatorJobs: [operatorJobFor(watcherId)],
      observations: [],
      issues: [],
    });
  });

  it("does not scan the catalog or histories when opening a run timeline", async () => {
    const read = vi.fn(async () => {
      throw new Error("A timeline must read its events directly.");
    });
    const onCatalog = vi.fn();
    const onProgress = vi.fn();
    const records = await loadWorkspaceRecords(requester(read), {
      view: "history",
      runId: "fixture-direct-run",
      onCatalog,
      onProgress,
    });
    expect(read).not.toHaveBeenCalled();
    expect(onCatalog).not.toHaveBeenCalled();
    expect(onProgress).not.toHaveBeenCalled();
    expect(records).toMatchObject({ watchers: [], jobs: [], runs: [], issues: [] });
  });

  it("keeps at most six reads in flight and fills a free slot before a slow peer finishes", async () => {
    const pending = new Map<string, ReturnType<typeof deferred<never[]>>>();
    let active = 0;
    let maximum = 0;
    const progress: WorkspaceProgress[] = [];
    const request = requester(async (path) => {
      if (path === "watchers") return watchers;
      if (path === "components") return { inventory_version: 1, components: [] };
      if (path === "jobs" || path === "observations") return [];
      active++;
      maximum = Math.max(maximum, active);
      const task = deferred<never[]>();
      pending.set(path, task);
      try {
        return await task.promise;
      } finally {
        active--;
      }
    });
    const loading = loadWorkspaceRecords(request, {
      view: "overview",
      onProgress: (item) => progress.push(item),
    });
    await flush();
    expect(pending.size).toBe(6);
    const initial = progress.at(-1)!;
    pending.get("watchers/source-2/runs")!.resolve([]);
    await flush();
    expect(pending.has("watchers/source-3/jobs")).toBe(true);
    expect(pending.size).toBe(7);
    expect(active).toBe(6);
    expect(initial.entries.every((entry) => entry.status === "loading")).toBe(true);
    while (pending.size < 10) {
      for (const task of pending.values()) task.resolve([]);
      await flush();
    }
    for (const task of pending.values()) task.resolve([]);
    await loading;
    expect(maximum).toBe(6);
    expect(progress[0]).toEqual({ phase: "catalog", completed: 0, total: 0, entries: [] });
    expect(progress.at(-1)).toMatchObject({ phase: "details", completed: 10, total: 10 });
    expect(progress.at(-1)!.entries.every((entry) => entry.status === "ready")).toBe(true);
  });

  it("retains successful records, sorts runs, and reports only safe partial-failure reasons", async () => {
    const run = (id: string, started_at: string): ControlRun => ({
      run_id: id,
      watcher_id: "source-2",
      scheduler_job_id: null,
      trigger: "schedule",
      config_revision: 1,
      started_at,
      finished_at: started_at,
      status: "ok",
    });
    const request = requester(async (path) => {
      if (path === "watchers") return watchers;
      if (path === "components") return { inventory_version: 1, components: [] };
      if (path.endsWith("source-0/runs"))
        throw new WorkspaceError("rate-limit", "private source account");
      if (path.endsWith("source-1/runs")) throw new Error("private provider response");
      if (path.endsWith("source-2/runs"))
        return [run("old", "2026-09-20T00:00:00Z"), run("new", "2026-09-21T00:00:00Z")];
      return [];
    });
    const records = await loadWorkspaceRecords(request, { view: "history" });
    expect(records.runs.map((run) => run.run_id)).toEqual(["new", "old"]);
    expect(records.issues).toHaveLength(2);
    expect(records.issues[0].message).toContain("The service is busy");
    expect(JSON.stringify(records.issues)).not.toContain("private");
  });

  it("preserves viewer access failures as partial records without granting access", async () => {
    const request = requester(async (path) => {
      if (path === "watchers") return [watchers[0]];
      if (path === "components") return { inventory_version: 1, components: [] };
      throw new WorkspaceError("forbidden", "private raw denial");
    });
    const records = await loadWorkspaceRecords(request, {
      view: "workflows",
      watcherId: watchers[0].watcher_id,
    });
    expect(records.jobs).toEqual([]);
    expect(records.issues[0].message).toContain("does not have access");
  });

  it("makes lost authentication fatal and stops queued reads even when peers cancel first", async () => {
    const calls: string[] = [];
    const auth = deferred<never[]>();
    const request = requester(async (path, _payload, options) => {
      calls.push(path);
      if (path === "watchers") return watchers;
      if (path === "components") return { inventory_version: 1, components: [] };
      if (path.endsWith("source-0/jobs")) return auth.promise;
      return new Promise((_, reject) =>
        options?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("Cancelled", "AbortError")),
          { once: true },
        ),
      );
    });
    const loading = loadWorkspaceRecords(request, { view: "overview" });
    await flush();
    auth.reject(new WorkspaceError("auth", "private token error"));
    await expect(loading).rejects.toMatchObject({
      code: "auth",
      message: "Your session has expired. Sign in again.",
    });
    expect(calls).toHaveLength(7);
  });

  it("does not load details or publish a catalog after cancellation", async () => {
    const controller = new AbortController();
    const catalog = deferred<ControlWatcher[]>();
    const onCatalog = vi.fn();
    const read = vi.fn(async () => catalog.promise);
    const loading = loadWorkspaceRecords(requester(read), {
      view: "overview",
      signal: controller.signal,
      onCatalog,
    });
    controller.abort();
    catalog.resolve(watchers);
    await expect(loading).rejects.toMatchObject({ name: "AbortError" });
    expect(onCatalog).not.toHaveBeenCalled();
    expect(read).toHaveBeenCalledTimes(1);
  });

  it("rejects catalog permission failures without starting any detail reads", async () => {
    const read = vi.fn(async () => {
      throw new WorkspaceError("forbidden", "Access denied.");
    });
    await expect(loadWorkspaceRecords(requester(read), { view: "overview" })).rejects.toMatchObject(
      { code: "forbidden" },
    );
    expect(read).toHaveBeenCalledTimes(1);
  });
});
