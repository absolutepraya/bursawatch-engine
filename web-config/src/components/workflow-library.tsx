"use client";

import Link from "next/link";
import { ArrowLeft, ArrowRight, ChevronRight, Search } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { PageHeading } from "./page-heading";
import { WorkflowNavigation } from "./workflow-navigation";
import {
  backendContractUrl,
  filterWorkflows,
  supportingCapabilities,
  workflowCatalog,
  workflowGroups,
  type WorkflowGroup,
} from "@/lib/workflow-catalog";

export function WorkflowLibrary() {
  const params = useSearchParams();
  const workflowId = params.get("workflow");
  const query = (params.get("q") ?? "").slice(0, 200);
  const rawGroup = params.get("group") ?? "all";
  const group: WorkflowGroup | "all" = Object.hasOwn(workflowGroups, rawGroup)
    ? (rawGroup as WorkflowGroup)
    : "all";
  const workflow = workflowCatalog.find((item) => item.id === workflowId);
  const back = `/app/automations/library?${new URLSearchParams({ q: query, group })}`;
  const results = filterWorkflows(query, group);
  function updateFilters(nextQuery: string, nextGroup: WorkflowGroup | "all") {
    // Keep native Back and copied links consistent without a request per keystroke.
    window.history.replaceState(
      null,
      "",
      `/app/automations/library?${new URLSearchParams({ q: nextQuery, group: nextGroup })}`,
    );
  }
  if (workflowId)
    return (
      <div className="page-wrap capability-page">
        <Link className="text-link capability-back" href={back}>
          <ArrowLeft size={17} aria-hidden="true" /> Workflow library
        </Link>
        <PageHeading
          title={workflow?.name ?? "Workflow not found"}
          description={
            workflow?.summary ??
            "This link does not match an available workflow. Return to the library to choose one."
          }
        />
        <WorkflowNavigation />
        {workflow ? (
          <>
            <div className="capability-detail">
              <section aria-labelledby="capability-output">
                <p className="capability-source">{workflow.input}</p>
                <h2 id="capability-output">What you receive</h2>
                <ul>
                  {workflow.produces.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
                <h2>When it runs</h2>
                <p>{workflow.timing}</p>
                <h2>What to know</h2>
                <p>{workflow.boundary}</p>
                <details className="capability-evidence">
                  <summary>Implementation details</summary>
                  <p>
                    Implemented in <code>{workflow.module}</code>. Repository support does not
                    confirm that the service is running.
                  </p>
                  <a
                    className="text-link"
                    href={backendContractUrl(workflow)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Reviewed backend contract <ArrowRight size={16} aria-hidden="true" />
                  </a>
                </details>
              </section>
              <aside className="capability-setup" aria-labelledby="capability-setup-title">
                <h2 id="capability-setup-title">Web connection pending</h2>
                <p>
                  The backend implements this workflow. Applying settings from this workspace still
                  needs its configuration API.
                </p>
                <dl>
                  <div>
                    <dt>Backend output</dt>
                    <dd>Discord</dd>
                  </div>
                  <div>
                    <dt>Web saves</dt>
                    <dd>This browser only</dd>
                  </div>
                  <div>
                    <dt>Live status</dt>
                    <dd>Not connected</dd>
                  </div>
                </dl>
                {workflow.action ? (
                  <>
                    <Link className="button secondary" href={workflow.action.href}>
                      {workflow.action.label}
                      <ChevronRight size={17} aria-hidden="true" />
                    </Link>
                    <p className="field-help">
                      Prepare source preferences here. Saving does not change the running watcher.
                    </p>
                  </>
                ) : workflow.group === "tracking" ? (
                  <p>
                    Plan state and close reconciliation are owned by the backend. There is no manual
                    run or trade button.
                  </p>
                ) : (
                  <p>
                    These provider-specific Telegram sources are managed by the backend owner.
                    Public-profile preferences do not configure this workflow.
                  </p>
                )}
              </aside>
            </div>
          </>
        ) : null}
      </div>
    );
  return (
    <div className="page-wrap capability-page">
      <PageHeading
        title="Workflow library"
        description="Choose the research you want to follow."
        action={
          <Link className="button primary" href="/app/automations/custom">
            Create your workflow
          </Link>
        }
      />
      <WorkflowNavigation />
      <p className="capability-boundary">
        Explore seven research routines. Account connection is not available yet.
      </p>
      <div className="capability-controls">
        <label className="research-search">
          <Search size={17} aria-hidden="true" />
          <span className="sr-only">Search workflows</span>
          <input
            type="search"
            maxLength={200}
            placeholder="Search news, accounts or plans"
            value={query}
            onChange={(event) => updateFilters(event.target.value, group)}
          />
        </label>
        <label className="capability-filter">
          <span id="workflow-filter-label">Show</span>
          <select
            aria-labelledby="workflow-filter-label"
            value={group}
            onChange={(event) => updateFilters(query, event.target.value as WorkflowGroup | "all")}
          >
            <option value="all">All workflows</option>
            {Object.entries(workflowGroups).map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="field-help" role="status">
        {results.length} {results.length === 1 ? "workflow" : "workflows"}
      </p>
      <div className="capability-list">
        {results.map((item) => (
          <Link
            className="capability-row"
            key={item.id}
            href={`/app/automations/library?${new URLSearchParams({ workflow: item.id, q: query, group })}`}
          >
            <div>
              <span className="capability-source">{item.input}</span>
              <h2>{item.name}</h2>
              <p>{item.summary}</p>
            </div>
            <span className="capability-row-action">
              View workflow <ArrowRight size={18} aria-hidden="true" />
            </span>
          </Link>
        ))}
      </div>
      {!results.length ? (
        <div className="research-empty">
          <h2>No matching workflows</h2>
          <p>Try a source such as Telegram, or clear your filters.</p>
          <button
            className="button secondary"
            type="button"
            onClick={() => {
              updateFilters("", "all");
            }}
          >
            Clear filters
          </button>
        </div>
      ) : null}
      <details className="capability-support">
        <summary>Research tools & supporting services</summary>
        <p>
          These support the workflows. They are not extra schedules or live connection indicators.
        </p>
        <dl>
          {supportingCapabilities.map((item) => (
            <div key={item.module}>
              <dt>{item.name}</dt>
              <dd>{item.description}</dd>
            </div>
          ))}
        </dl>
      </details>
      <p className="capability-footnote">
        Looking for daily price alerts?{" "}
        <Link className="text-link" href="/app/automations/new">
          Prepare a price watch
        </Link>
        . This separate web prototype still needs Sectors and scheduler integration.
      </p>
    </div>
  );
}
