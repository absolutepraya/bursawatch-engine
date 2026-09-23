import { AutomationWizard } from "@/components/automation-wizard";
import { PageHeading } from "@/components/page-heading";
import { getWorkspaceRecords } from "@/lib/sample-workspace";

export const dynamic = "force-dynamic";

export default function NewAutomationPage() {
  const sources = getWorkspaceRecords().listSources();
  return (
    <div className="page-wrap wizard-page">
      <PageHeading
        title="Create a workflow"
        description="Your stocks, your schedule, your brief."
      />
      <AutomationWizard sources={sources} />
    </div>
  );
}
