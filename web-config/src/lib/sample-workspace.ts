import type { ActivityEventRecord, AutomationRecord, EvidenceRecord, RunRecord, SourceRecord } from "@/lib/types";

// Fixed illustrative records, not a database or scheduler. Historical
// timestamps never advance to imply that a new unattended run has occurred.
const runId = "demo-run-001";
const sources: SourceRecord[] = [
  { id: "sectors", name: "Sectors market signals", kind: "sectors", status: "healthy",
    description: "Daily prices and company evidence for stock workflows.",
    capabilities: ["Daily price", "Volume", "Company evidence"],
    lastEventAt: "2026-09-16T08:30:00.000Z", reconciledAt: "2026-09-16T08:30:12.000Z" },
  { id: "bri-danareksa", name: "BRI Danareksa", kind: "whatsapp-channel", status: "healthy",
    description: "Research notes and market commentary from BRI Danareksa.",
    capabilities: ["Research notes", "Market calls", "Linked documents"],
    lastEventAt: "2026-09-16T07:50:00.000Z", reconciledAt: "2026-09-16T08:10:00.000Z" },
  { id: "mandiri-sekuritas", name: "Mandiri Sekuritas", kind: "whatsapp-channel", status: "disconnected",
    description: "A public source reference is needed before this source can be connected.",
    capabilities: ["Research notes", "Market calls"], lastEventAt: null, reconciledAt: null },
];
const automations: AutomationRecord[] = [{
  id: "demo-banking-watch", name: "Banking watch", status: "active", version: 1,
  sourceIds: ["sectors", "bri-danareksa"], symbols: ["BBRI", "TLKM"], horizon: "days-to-weeks",
  triggers: { sourceMention: false, postClose: true, priceMove: true, priceMoveThreshold: 3, filingOrFlow: false },
  scheduleLabel: "Weekdays · 15:30 WIB", scheduleTime: "15:30", nextRunAt: "2026-09-17T08:30:00.000Z",
  destinationMasked: "+62 812 •••• 1847", language: "id", tone: "concise", conditionState: "false",
  createdAt: "2026-09-15T08:30:00.000Z", updatedAt: "2026-09-16T08:30:47.000Z",
}];
const runs: RunRecord[] = [{
  id: runId, automationId: "demo-banking-watch", automationName: "Banking watch", configVersion: 1,
  trigger: "post-close schedule", startedAt: "2026-09-16T08:30:00.000Z", completedAt: "2026-09-16T08:30:47.000Z",
  outcome: "prepared-preview", evidenceMode: "synthetic-demo", conditionResult: "false → true",
  summary: "BBRI crossed the 3% daily price threshold. The brief is ready to review.",
}];
const steps = [
  ["schedule", "Schedule started", "Weekday post-close check", "complete", 0, null],
  ["sectors", "Daily prices checked", "BBRI closing-price change: +3.60%", "info", 12, "evidence:demo-bbri"],
  ["condition", "Price threshold reached", "Daily price move crossed 3%", "complete", 25, "metric:price-change"],
  ["analysis", "Brief prepared", "Price data and source references included", "info", 36, "brief:demo-001"],
  ["delivery", "WhatsApp preview ready", "Review the brief before connecting delivery", "warning", 47, "preview:demo-001"],
] as const;
const activity: ActivityEventRecord[] = steps.map(([stage, title, detail, status, seconds, evidenceRef], index) => ({
  id: index + 1, runId, stage, title, detail, status, evidenceRef,
  occurredAt: new Date(Date.parse(runs[0].startedAt) + seconds * 1000).toISOString(),
}));
const evidence: EvidenceRecord[] = [{
  id: "evidence:demo-bbri", runId, symbol: "BBRI", endpoint: "/v2/daily/BBRI/",
  metric: "daily_close_change", value: "3.60", unit: "%", marketAsOf: "2026-09-16",
  retrievedAt: "2026-09-16T08:30:12.000Z", origin: "synthetic-demo",
}];

/** Read-only presentation seam for a future authenticated backend adapter. */
export function getWorkspaceRecords() {
  return {
    listSources: () => structuredClone(sources),
    listAutomations: () => structuredClone(automations),
    getAutomation: (id: string) => structuredClone(automations.find((item) => item.id === id) ?? null),
    listRuns: (limit = 20) => structuredClone(runs.slice(0, Math.max(0, Math.trunc(limit)))),
    latestRun: () => structuredClone(runs[0] ?? null),
    listActivity: (id: string) => structuredClone(activity.filter((item) => item.runId === id)),
    listEvidence: (id: string) => structuredClone(evidence.filter((item) => item.runId === id)),
    counts: () => ({ active: automations.filter((item) => item.status === "active").length,
      issues: sources.filter((item) => item.status !== "healthy").length, liveEvidence: 0 }),
  };
}
