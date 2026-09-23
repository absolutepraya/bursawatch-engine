import { ArrowRight, CalendarClock, Plus, RadioTower } from "lucide-react";
import Link from "next/link";

import { AutomationStatusControl } from "@/components/automation-status-control";
import { PageHeading } from "@/components/page-heading";
import { StatusBadge } from "@/components/status-badge";
import { WorkflowNavigation } from "@/components/workflow-navigation";
import { getWorkspaceRecords } from "@/lib/sample-workspace";
import { BrowserWatches } from "@/components/browser-watches";
import { formatWib } from "@/lib/format";
import { scheduleStatus } from "@/lib/schedule-status";

export const dynamic = "force-dynamic";

export default function AutomationsPage() {
  const db = getWorkspaceRecords();
  const automations = db.listAutomations();
  const runs = db.listRuns(30);
  return (
    <div className="page-wrap">
      <PageHeading
        title="Workflows"
        description="Manage your schedules and review their results."
        action={
          <Link className="button primary" href="/app/automations/library">
            <Plus aria-hidden="true" size={18} /> Browse workflows
          </Link>
        }
      />
      <WorkflowNavigation />
      <BrowserWatches />
      <section className="automation-list" aria-label="Configured automations">
        {automations.map((automation) => {
          const latest = runs.find((run) => run.automationId === automation.id);
          const schedule = scheduleStatus(automation.status, automation.nextRunAt);
          return (
            <article className="automation-row" key={automation.id}>
              <div className="automation-identity">
                <span className="automation-icon">
                  <RadioTower aria-hidden="true" />
                </span>
                <div>
                  <div className="title-line">
                    <h2>{automation.name}</h2>
                    <StatusBadge status={automation.status} />
                  </div>
                  <p>
                    {automation.sourceIds.length} sources · {automation.symbols.join(", ")}
                  </p>
                </div>
              </div>
              <div className="automation-facts">
                <div>
                  <CalendarClock aria-hidden="true" size={17} />
                  <span>
                    <small>{schedule.label}</small>
                    <strong>{schedule.value}</strong>
                    <em>{schedule.detail}</em>
                  </span>
                </div>
                <div>
                  <span>
                    <small>Latest outcome</small>
                    <strong>{latest?.outcome.replaceAll("-", " ") ?? "Awaiting first run"}</strong>
                    <em>
                      {latest?.completedAt
                        ? formatWib(latest.completedAt)
                        : automation.scheduleLabel}
                    </em>
                  </span>
                </div>
              </div>
              <div className="automation-actions">
                <AutomationStatusControl id={automation.id} status={automation.status} />
                {latest ? (
                  <Link className="button secondary small" href={`/app/activity?run=${latest.id}`}>
                    View run <ArrowRight aria-hidden="true" size={16} />
                  </Link>
                ) : (
                  <span className="field-help">No recorded run</span>
                )}
              </div>
            </article>
          );
        })}
      </section>
    </div>
  );
}
