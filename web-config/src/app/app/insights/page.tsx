import { WorkflowInsights } from "@/components/workflow-insights";
import { getWorkspaceRecords } from "@/lib/sample-workspace";
import { insightsRunLimit } from "@/lib/run-analytics";

export const dynamic = "force-dynamic";

export default function InsightsPage() {
  const db = getWorkspaceRecords();
  const runs = db.listRuns(insightsRunLimit);
  const evidence = runs.map((run) => ({ runId: run.id, items: db.listEvidence(run.id) }));
  return <WorkflowInsights runs={runs} evidence={evidence} asOf={new Date().toISOString()} />;
}
