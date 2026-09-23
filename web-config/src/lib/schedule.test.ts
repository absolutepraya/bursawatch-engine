import { describe, expect, it } from "vitest";

import { nextScheduledRun } from "@/lib/schedule";

describe("nextScheduledRun", () => {
  it("schedules the same trading day before the WIB cutoff", () => {
    const now = new Date("2024-01-08T07:00:00.000Z"); // Monday, 14:00 WIB
    expect(nextScheduledRun(now, "15:30").toISOString()).toBe("2024-01-08T08:30:00.000Z");
  });

  it("moves to the next weekday after the cutoff", () => {
    const now = new Date("2024-01-12T09:00:00.000Z"); // Friday, 16:00 WIB
    expect(nextScheduledRun(now, "15:30").toISOString()).toBe("2024-01-15T08:30:00.000Z");
  });

  it("supports an explicit fast demo cadence", () => {
    const now = new Date("2024-01-08T07:00:00.000Z");
    expect(nextScheduledRun(now, "15:30", 60).toISOString()).toBe("2024-01-08T07:01:00.000Z");
  });
});
