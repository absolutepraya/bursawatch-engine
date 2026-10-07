"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import { WorkspaceApp } from "@/components/workspace-app";
import type { WorkspaceView } from "@/components/workspace-navigation";
import { createDemoRequester, type DemoRequester } from "./demo-request";
import { SampleMorningBrief } from "./sample-morning-brief";

const SampleRequestContext = createContext<DemoRequester | null>(null);

const notices: Record<WorkspaceView, string> = {
  overview:
    "Synthetic examples only. No live runs, deliveries, connections, or current system state.",
  sources:
    "Public catalog entries and synthetic selections. Compatible endpoint capabilities can be saved as sample intent, with no live source connection.",
  workflows:
    "Only fields supported by the real editor can be changed here. Source Catalog settings do not attach identities to watcher profiles. Morning Brief timing, destination and instrument settings can be saved for the next unfrozen session. There is no separate evening digest, and saving does not activate a job.",
  jobs: "Read-only sample jobs. Real interval schedules run from 1 minute to 24 hours, with no weekly interval. Morning Brief timing is configured in its workflow editor; job activation remains read-only here.",
  history:
    "Synthetic example records only. No real runs, source polls, or deliveries are represented.",
  published:
    "Public examples from the landing page only. This view does not query publisher coverage or verify live delivery.",
  settings:
    "No account, session, or bot connection is attached. Account access is managed in the authenticated workspace.",
};

export function SampleWorkspaceProvider({ children }: { children: ReactNode }) {
  const [request] = useState(() => createDemoRequester());
  return <SampleRequestContext.Provider value={request}>{children}</SampleRequestContext.Provider>;
}

export function SampleWorkspaceView({ view }: { view: WorkspaceView }) {
  const request = useContext(SampleRequestContext);
  if (!request) throw new Error("The sample workspace provider is missing.");
  return (
    <WorkspaceApp
      settings={null}
      view={view}
      demo={{
        request,
        notices,
        children: view === "overview" ? <SampleMorningBrief /> : undefined,
      }}
    />
  );
}
