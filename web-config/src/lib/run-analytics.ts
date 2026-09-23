import type { EvidenceRecord, RunOutcome, RunRecord } from "@/lib/types";

const DAY_MS = 86_400_000;
const WIB_OFFSET_MS = 7 * 3_600_000;
export const insightsRunLimit = 20;
export type RunEvidence = { runId: string; items: EvidenceRecord[] };

export function latestStockMoves(runs: RunRecord[], evidence: RunEvidence[]) {
  const included = new Set(runs.map((run) => run.id));
  const latest = new Map<string, { runId: string; evidence: EvidenceRecord; change: number }>();
  for (const group of evidence) {
    if (!included.has(group.runId)) continue;
    for (const item of group.items) {
      if (
        item.metric !== "daily_close_change" ||
        item.unit !== "%" ||
        !item.value.trim() ||
        !Number.isFinite(Number(item.value)) ||
        !/^\d{4}-\d{2}-\d{2}$/.test(item.marketAsOf) ||
        !Number.isFinite(Date.parse(item.marketAsOf)) ||
        !Number.isFinite(Date.parse(item.retrievedAt))
      )
        continue;
      const prior = latest.get(item.symbol);
      if (
        !prior ||
        item.marketAsOf > prior.evidence.marketAsOf ||
        (item.marketAsOf === prior.evidence.marketAsOf &&
          Date.parse(item.retrievedAt) > Date.parse(prior.evidence.retrievedAt))
      ) {
        latest.set(item.symbol, { runId: group.runId, evidence: item, change: Number(item.value) });
      }
    }
  }
  return [...latest.values()].sort((a, b) => a.evidence.symbol.localeCompare(b.evidence.symbol));
}
export const outcomeLabels: Record<RunOutcome, string> = {
  "prepared-preview": "Brief prepared",
  "no-change": "No change",
  degraded: "Degraded",
  failed: "Failed",
  running: "In progress",
};

function emptyOutcomes(): Record<RunOutcome, number> {
  return { "prepared-preview": 0, "no-change": 0, degraded: 0, failed: 0, running: 0 };
}

export function summarizeRuns(records: RunRecord[], range: 7 | 30, asOf: string) {
  const end = Date.parse(asOf);
  if (!Number.isFinite(end)) throw new Error("A valid reporting time is required.");
  const today = Math.floor((end + WIB_OFFSET_MS) / DAY_MS) * DAY_MS - WIB_OFFSET_MS;
  const start = today - (range - 1) * DAY_MS;
  const days = Array.from({ length: range }, (_, index) => ({
    date: new Date(start + index * DAY_MS + WIB_OFFSET_MS).toISOString().slice(0, 10),
    count: 0,
    outcomes: emptyOutcomes(),
  }));
  const runs = records
    .filter((run) => {
      const timestamp = Date.parse(run.startedAt);
      return Number.isFinite(timestamp) && timestamp >= start && timestamp <= end;
    })
    .sort((a, b) => Date.parse(b.startedAt) - Date.parse(a.startedAt));
  const outcomes = emptyOutcomes();
  for (const run of runs) {
    const index = Math.floor((Date.parse(run.startedAt) - start) / DAY_MS);
    days[index].count++;
    days[index].outcomes[run.outcome]++;
    outcomes[run.outcome]++;
  }
  const sampleCount = runs.filter((run) => run.evidenceMode === "synthetic-demo").length;
  return {
    start: new Date(start).toISOString(),
    end: new Date(end).toISOString(),
    days,
    runs,
    outcomes,
    checks: runs.length,
    prepared: outcomes["prepared-preview"],
    issues: outcomes.degraded + outcomes.failed,
    recordedDays: days.filter((day) => day.count > 0).length,
    sampleCount,
    liveCount: runs.length - sampleCount,
  };
}
