import type { ControlRun, ControlWatcher } from "@/server/control-plane";

export type WorkflowConfigurationFilter = "all" | "configured" | "needs-setup";
export type RunOutcomeFilter = "all" | ControlRun["status"];

function searchWords(query: string) {
  return query.trim().toLocaleLowerCase("en").split(/\s+/).filter(Boolean);
}

function matchesWords(value: string, words: string[]) {
  const searchable = value.toLocaleLowerCase("en");
  return words.every((word) => searchable.includes(word));
}

export function filterWorkspaceWatchers(
  watchers: ControlWatcher[],
  query: string,
  configuration: WorkflowConfigurationFilter,
) {
  const words = searchWords(query);
  return watchers.filter(
    (watcher) =>
      (configuration === "all" ||
        (configuration === "configured") === (watcher.current_revision !== null)) &&
      matchesWords(`${watcher.display_name} ${watcher.watcher_id}`, words),
  );
}

export function filterWorkspaceRuns(
  runs: ControlRun[],
  watchers: ControlWatcher[],
  query: string,
  watcherId: string,
  outcome: RunOutcomeFilter,
) {
  const names = new Map(watchers.map((watcher) => [watcher.watcher_id, watcher.display_name]));
  const words = searchWords(query);
  return runs.filter(
    (run) =>
      (watcherId === "all" || run.watcher_id === watcherId) &&
      (outcome === "all" || run.status === outcome) &&
      matchesWords(
        `${names.get(run.watcher_id) ?? ""} ${run.watcher_id} ${run.trigger} ${run.run_id}`,
        words,
      ),
  );
}
