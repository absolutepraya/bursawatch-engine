import { controlBrowser, WorkspaceError } from "./control-browser";
import { xWatcherId } from "./x-delivery-status";
import type { ControlJob, ControlRun, ControlWatcher } from "@/server/control-plane";

export type WorkspaceView = "overview" | "workflows" | "history" | "schedules" | "settings";
export type WorkspaceIssue = {
  watcherId: string;
  resource: "jobs" | "runs";
  message: string;
};
export type WorkspaceRecords = {
  watchers: ControlWatcher[];
  jobs: ControlJob[];
  runs: ControlRun[];
  updatedAt: string;
  issues: WorkspaceIssue[];
};
export type WorkspaceProgressEntry = {
  watcherId: string;
  resource: "jobs" | "runs";
  status: "loading" | "ready" | "error";
  message?: string;
};
export type WorkspaceProgress = {
  phase: "catalog" | "details";
  completed: number;
  total: number;
  entries: WorkspaceProgressEntry[];
};
export type WorkspaceLoadOptions = {
  view: WorkspaceView;
  watcherId?: string | null;
  runId?: string | null;
  onCatalog?: (watchers: ControlWatcher[]) => void;
  onProgress?: (progress: WorkspaceProgress) => void;
  signal?: AbortSignal;
};

function issueMessage(resource: "jobs" | "runs", failure: unknown) {
  const label = resource === "jobs" ? "Schedule status" : "Run history";
  const code = failure instanceof WorkspaceError ? failure.code : "unavailable";
  const reasons: Record<string, string> = {
    timeout: "The request timed out. Try again.",
    "rate-limit": "The service is busy. Wait a moment, then try again.",
    forbidden: "Your account does not have access to these records.",
    missing: "These records are no longer available. Refresh the workspace.",
    setup: "The workspace owner needs to finish connecting the service.",
    "invalid-response": "The response could not be verified. Try again.",
  };
  return `${label} could not be loaded. ${reasons[code] ?? "Check your connection and try again."}`;
}

/** Read only the current view's records. The catalog remains the authority for
 * watcher membership; configuration and schedule writes never use this loader. */
export async function loadWorkspaceRecords(
  request: ReturnType<typeof controlBrowser>,
  options: WorkspaceLoadOptions,
): Promise<WorkspaceRecords> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  options.signal?.addEventListener("abort", cancel, { once: true });
  if (options.signal?.aborted) controller.abort();
  const checkCancelled = () => {
    if (controller.signal.aborted)
      throw new DOMException("The request was cancelled.", "AbortError");
  };
  const entries: WorkspaceProgressEntry[] = [];
  let completed = 0;
  let failed = false;
  let authFailure: WorkspaceError | undefined;
  const progress = (phase: WorkspaceProgress["phase"]) => {
    if (!controller.signal.aborted && !failed)
      options.onProgress?.({
        phase,
        completed,
        total: entries.length,
        // Earlier notifications must stay immutable as requests finish.
        entries: entries.map((entry) => ({ ...entry })),
      });
  };
  try {
    checkCancelled();
    // A run link already identifies its events endpoint. The API has no
    // single-run metadata read, so never scan unrelated histories to open it.
    if (options.view === "history" && options.runId)
      return {
        watchers: [],
        jobs: [],
        runs: [],
        updatedAt: new Date().toISOString(),
        issues: [],
      };
    progress("catalog");
    const watchers = await request<ControlWatcher[]>("watchers", undefined, {
      signal: controller.signal,
    });
    checkCancelled();
    options.onCatalog?.(watchers);
    const relevant =
      options.view === "workflows"
        ? watchers.filter(
            (watcher) =>
              watcher.watcher_id === options.watcherId && watcher.watcher_id === xWatcherId,
          )
        : watchers;
    for (const watcher of relevant) {
      if (["overview", "workflows", "schedules"].includes(options.view))
        entries.push({ watcherId: watcher.watcher_id, resource: "jobs", status: "loading" });
      if (["overview", "workflows", "history"].includes(options.view))
        entries.push({ watcherId: watcher.watcher_id, resource: "runs", status: "loading" });
    }
    const jobs = new Map<number, ControlJob[]>();
    const runs = new Map<number, ControlRun[]>();
    const issues = new Map<number, WorkspaceIssue>();
    let next = 0;
    progress("details");
    const worker = async () => {
      while (next < entries.length) {
        checkCancelled();
        const index = next++;
        const entry = entries[index];
        try {
          const path = `watchers/${encodeURIComponent(entry.watcherId)}/${entry.resource}`;
          if (entry.resource === "jobs") {
            const rows = await request<ControlJob[]>(path, undefined, {
              signal: controller.signal,
            });
            checkCancelled();
            jobs.set(index, rows);
          } else {
            const rows = await request<ControlRun[]>(path, undefined, {
              signal: controller.signal,
            });
            checkCancelled();
            runs.set(index, rows);
          }
          entry.status = "ready";
        } catch (failure) {
          if (controller.signal.aborted)
            throw new DOMException("The request was cancelled.", "AbortError");
          if (failure instanceof WorkspaceError && failure.code === "auth") {
            // Authentication loss invalidates the entire read, including any
            // successful peers. Stop queued requests and discard partial data.
            failed = true;
            authFailure = new WorkspaceError("auth", "Your session has expired. Sign in again.");
            controller.abort();
            throw authFailure;
          }
          if (failure instanceof Error && failure.name === "AbortError") throw failure;
          entry.status = "error";
          entry.message = issueMessage(entry.resource, failure);
          issues.set(index, {
            watcherId: entry.watcherId,
            resource: entry.resource,
            message: entry.message,
          });
        }
        completed++;
        progress("details");
      }
    };
    // Each completed request frees its slot immediately. One slow watcher does
    // not hold up the next whole batch, and concurrency never exceeds six.
    await Promise.all(Array.from({ length: Math.min(6, entries.length) }, worker));
    checkCancelled();
    const ordered = <T>(rows: Map<number, T[]>) =>
      [...rows.entries()].sort(([a], [b]) => a - b).flatMap(([, value]) => value);
    return {
      watchers,
      jobs: ordered(jobs),
      runs: ordered(runs).sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at)),
      updatedAt: new Date().toISOString(),
      issues: [...issues.entries()].sort(([a], [b]) => a - b).map(([, issue]) => issue),
    };
  } catch (failure) {
    controller.abort();
    // Peer cancellation can settle before the originating auth request.
    if (authFailure) throw authFailure;
    throw failure;
  } finally {
    options.signal?.removeEventListener("abort", cancel);
  }
}
