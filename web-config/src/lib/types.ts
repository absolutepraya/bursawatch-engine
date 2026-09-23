export type SourceStatus = "healthy" | "delayed" | "disconnected";
export type AutomationStatus = "active" | "paused" | "degraded";
export type Horizon = "days-to-weeks" | "months-to-years";
export type EvidenceMode = "sectors-live" | "synthetic-demo";
export type RunOutcome = "running" | "prepared-preview" | "no-change" | "degraded" | "failed";

export interface SourceRecord {
  id: string;
  name: string;
  kind: "sectors" | "whatsapp-channel";
  status: SourceStatus;
  description: string;
  capabilities: string[];
  lastEventAt: string | null;
  reconciledAt: string | null;
}

export interface AutomationTriggers {
  sourceMention: boolean;
  postClose: boolean;
  priceMove: boolean;
  priceMoveThreshold: number;
  filingOrFlow: boolean;
}

export interface AutomationRecord {
  id: string;
  name: string;
  status: AutomationStatus;
  version: number;
  sourceIds: string[];
  symbols: string[];
  horizon: Horizon;
  triggers: AutomationTriggers;
  scheduleLabel: string;
  scheduleTime: string;
  nextRunAt: string;
  destinationMasked: string;
  language: "id" | "en";
  tone: "concise" | "beginner" | "analyst";
  conditionState: "unknown" | "false" | "true" | "stale";
  createdAt: string;
  updatedAt: string;
}

export interface RunRecord {
  id: string;
  automationId: string;
  automationName: string;
  configVersion: number;
  trigger: string;
  startedAt: string;
  completedAt: string | null;
  outcome: RunOutcome;
  evidenceMode: EvidenceMode;
  conditionResult: string;
  summary: string;
}

export interface ActivityEventRecord {
  id: number;
  runId: string;
  stage: string;
  title: string;
  detail: string;
  status: "complete" | "info" | "warning" | "failed";
  occurredAt: string;
  evidenceRef: string | null;
}

export interface EvidenceRecord {
  id: string;
  runId: string;
  symbol: string;
  endpoint: string;
  metric: string;
  value: string;
  unit: string;
  marketAsOf: string;
  retrievedAt: string;
  origin: EvidenceMode;
}

export interface CreateAutomationInput {
  name: string;
  sourceIds: string[];
  symbols: string[];
  horizon: Horizon;
  triggers: AutomationTriggers;
  scheduleTime: string;
  destination: string;
  language: "id" | "en";
  tone: "concise" | "beginner" | "analyst";
}
