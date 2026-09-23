import { describe, expect, it } from "vitest";
import { scheduleStatus } from "./schedule-status";

const now = new Date("2026-09-17T06:00:00Z");
describe("schedule status", () => {
  it("does not promise a run for a paused schedule", () => {
    expect(scheduleStatus("paused", "2026-09-18T08:30:00Z", now)).toEqual({ label: "Schedule", value: "Paused", detail: "No run scheduled while paused" });
  });
  it("labels a past timestamp as past due, not next", () => {
    expect(scheduleStatus("active", "2026-09-16T08:30:00Z", now)).toMatchObject({ label: "Last scheduled", detail: "Past due · check run history" });
  });
  it("includes the exact due boundary", () => {
    expect(scheduleStatus("active", now.toISOString(), now).label).toBe("Last scheduled");
  });
  it("describes a future time as scheduled, not guaranteed execution", () => {
    expect(scheduleStatus("active", "2026-09-17T06:30:00Z", now)).toEqual({ label: "Next scheduled", value: "17 Sept, 13:30", detail: "in 30 min" });
  });
  it("does not invent dates for invalid scheduler data", () => {
    expect(scheduleStatus("degraded", "invalid", now).value).toBe("Not available");
  });
});
