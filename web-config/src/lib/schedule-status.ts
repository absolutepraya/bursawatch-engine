import { formatRelative, formatWib } from "./format";
import type { AutomationStatus } from "./types";

export function scheduleStatus(status: AutomationStatus, nextRunAt: string, now = new Date()) {
  if (status === "paused") return { label: "Schedule", value: "Paused", detail: "No run scheduled while paused" };
  const timestamp = Date.parse(nextRunAt);
  if (!Number.isFinite(timestamp)) return { label: "Schedule", value: "Not available", detail: "Check schedule configuration" };
  if (timestamp <= now.getTime()) return { label: "Last scheduled", value: formatWib(nextRunAt), detail: "Past due · check run history" };
  return { label: "Next scheduled", value: formatWib(nextRunAt), detail: formatRelative(nextRunAt, now) };
}
