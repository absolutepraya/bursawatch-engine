import { notFound, redirect } from "next/navigation";
import { Suspense } from "react";
import type { WorkspaceView } from "@/components/workspace-navigation";
import { SampleWorkspaceView } from "../sample-workspace";

const destinationViews: Record<string, WorkspaceView> = {
  sources: "sources",
  workflows: "workflows",
  jobs: "jobs",
  history: "history",
  published: "published",
  account: "settings",
};

const legacyRoutes: Record<string, string> = {
  insights: "/app",
  overview: "/app",
  discover: "/app/sources",
  following: "/app/sources",
  activity: "/app/history",
  logs: "/app/history",
  configuration: "/app/workflows",
  watchlist: "/app/workflows",
  securities: "/app/sources",
  setup: "/app",
};

export default async function SampleWorkspacePage({
  params,
}: {
  params: Promise<{ route?: string[] }>;
}) {
  const { route = [] } = await params;
  const first = route[0] ?? "";
  const second = route[1];

  if (route.length === 0) return samplePage("overview");
  if (first === "automations") redirect("/app/workflows");
  if (first === "settings") redirect("/app/account");
  if (first === "securities" && second === "add") redirect("/app/sources");
  if (route.length > 1) notFound();
  if (legacyRoutes[first]) redirect(legacyRoutes[first]);
  const view = destinationViews[first];
  if (!view) notFound();
  return samplePage(view);
}

function samplePage(view: WorkspaceView) {
  return (
    <Suspense
      fallback={
        <main className="sample-workspace-fallback" role="status" aria-busy="true">
          Opening the sample workspace…
        </main>
      }
    >
      <SampleWorkspaceView view={view} />
    </Suspense>
  );
}
