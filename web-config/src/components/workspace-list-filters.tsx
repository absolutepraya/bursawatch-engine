"use client";

import { useMemo, useState } from "react";
import { Activity, CircleDashed, Search } from "lucide-react";
import type { ControlJob, ControlRun, ControlWatcher } from "@/server/control-plane";
import type { ControlCoverageIssue } from "@/lib/control-analytics";
import type { OperatorComponent, OperatorJob, OperatorObservation } from "@/lib/operator-inventory";
import { controlStatusLabels, controlStatuses } from "@/lib/control-analytics";
import {
  filterWorkspaceRuns,
  filterWorkspaceWatchers,
  type RunOutcomeFilter,
  type WorkflowConfigurationFilter,
} from "@/lib/workspace-list-filters";
import { ControlRunList, ControlWatcherList } from "@/components/control-dashboard";
import "@/app/workspace-list-filters.css";

function FilteredEmpty({ kind, onClear }: { kind: "workflows" | "runs"; onClear: () => void }) {
  const Icon = kind === "workflows" ? CircleDashed : Activity;
  return (
    <div className="control-list-empty workspace-filter-empty">
      <Icon size={24} aria-hidden="true" />
      <strong>No {kind} match these filters</strong>
      <p>Try another search or clear the filters to see all returned {kind}.</p>
      <button type="button" className="button secondary small" onClick={onClear}>
        Clear filters
      </button>
    </div>
  );
}

export function SearchableWorkflowList({
  watchers,
  runs,
  jobs,
  updatedAt,
  onSelectWatcher,
  issues = [],
  statusLoaded = false,
  components = [],
  operatorJobs = [],
  observations = [],
}: {
  watchers: ControlWatcher[];
  runs: ControlRun[];
  jobs: ControlJob[];
  updatedAt: string;
  onSelectWatcher: (watcherId: string) => void;
  issues?: ControlCoverageIssue[];
  statusLoaded?: boolean;
  components?: OperatorComponent[];
  operatorJobs?: OperatorJob[];
  observations?: OperatorObservation[];
}) {
  const [query, setQuery] = useState("");
  const [configuration, setConfiguration] = useState<WorkflowConfigurationFilter>("all");
  const visible = useMemo(
    () => filterWorkspaceWatchers(watchers, query, configuration),
    [watchers, query, configuration],
  );
  const clear = () => {
    setQuery("");
    setConfiguration("all");
  };
  return (
    <section className="workspace-filtered-list" aria-label="Workflow list">
      <div className="workspace-list-controls workspace-list-controls-workflows">
        <label
          className="workspace-list-field workspace-list-search"
          htmlFor="workspace-workflow-search"
        >
          <span>Search workflows</span>
          <span className="workspace-list-search-input">
            <Search size={17} aria-hidden="true" />
            <input
              id="workspace-workflow-search"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Name or workflow ID"
            />
          </span>
        </label>
        <div className="workspace-list-field">
          <label htmlFor="workspace-workflow-configuration">Configuration</label>
          <select
            id="workspace-workflow-configuration"
            value={configuration}
            onChange={(event) =>
              setConfiguration(event.target.value as WorkflowConfigurationFilter)
            }
          >
            <option value="all">All workflows</option>
            <option value="configured">Configured</option>
            <option value="needs-setup">Needs setup</option>
          </select>
        </div>
      </div>
      <div className="workspace-list-feedback">
        <p role="status" aria-live="polite">
          Showing {visible.length} of {watchers.length} workflows
        </p>
        {(query || configuration !== "all") && visible.length > 0 ? (
          <button type="button" onClick={clear}>
            Clear filters
          </button>
        ) : null}
      </div>
      {visible.length === 0 && watchers.length > 0 ? (
        <FilteredEmpty kind="workflows" onClear={clear} />
      ) : (
        <ControlWatcherList
          watchers={visible}
          runs={runs}
          jobs={jobs}
          updatedAt={updatedAt}
          onSelectWatcher={onSelectWatcher}
          issues={issues}
          statusLoaded={statusLoaded}
          components={components}
          operatorJobs={operatorJobs}
          observations={observations}
        />
      )}
    </section>
  );
}

export function SearchableRunHistory({
  runs,
  watchers,
  onSelectRun,
}: {
  runs: ControlRun[];
  watchers: ControlWatcher[];
  onSelectRun: (runId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [watcherId, setWatcherId] = useState("all");
  const [outcome, setOutcome] = useState<RunOutcomeFilter>("all");
  const visible = useMemo(
    () => filterWorkspaceRuns(runs, watchers, query, watcherId, outcome),
    [runs, watchers, query, watcherId, outcome],
  );
  const watcherOptions = useMemo(
    () => [...watchers].sort((a, b) => a.display_name.localeCompare(b.display_name)),
    [watchers],
  );
  const clear = () => {
    setQuery("");
    setWatcherId("all");
    setOutcome("all");
  };
  return (
    <section className="workspace-filtered-list" aria-label="Run history list">
      <div className="workspace-list-controls workspace-list-controls-runs">
        <label
          className="workspace-list-field workspace-list-search"
          htmlFor="workspace-run-search"
        >
          <span>Search runs</span>
          <span className="workspace-list-search-input">
            <Search size={17} aria-hidden="true" />
            <input
              id="workspace-run-search"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Workflow, trigger or run ID"
            />
          </span>
        </label>
        <div className="workspace-list-field">
          <label htmlFor="workspace-run-workflow">Workflow</label>
          <select
            id="workspace-run-workflow"
            value={watcherId}
            onChange={(event) => setWatcherId(event.target.value)}
          >
            <option value="all">All workflows</option>
            {watcherOptions.map((watcher) => (
              <option key={watcher.watcher_id} value={watcher.watcher_id}>
                {watcher.display_name}
              </option>
            ))}
          </select>
        </div>
        <div className="workspace-list-field">
          <label htmlFor="workspace-run-outcome">Outcome</label>
          <select
            id="workspace-run-outcome"
            value={outcome}
            onChange={(event) => setOutcome(event.target.value as RunOutcomeFilter)}
          >
            <option value="all">All outcomes</option>
            {controlStatuses.map((status) => (
              <option key={status} value={status}>
                {controlStatusLabels[status]}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="workspace-list-feedback">
        <p role="status" aria-live="polite">
          Showing {visible.length} of {runs.length} returned runs
        </p>
        {(query || watcherId !== "all" || outcome !== "all") && visible.length > 0 ? (
          <button type="button" onClick={clear}>
            Clear filters
          </button>
        ) : null}
      </div>
      {visible.length === 0 && runs.length > 0 ? (
        <FilteredEmpty kind="runs" onClear={clear} />
      ) : (
        <ControlRunList runs={visible} watchers={watchers} onSelectRun={onSelectRun} />
      )}
    </section>
  );
}
