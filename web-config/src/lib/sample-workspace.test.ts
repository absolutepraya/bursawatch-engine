import { afterEach, describe, expect, it, vi } from "vitest";
import { getWorkspaceRecords } from "./sample-workspace";
import { GET, POST } from "@/app/api/automations/route";
import { PATCH } from "@/app/api/automations/[id]/route";

afterEach(() => vi.unstubAllEnvs());
describe("sample workspace boundary", () => {
  it("returns independent copies so one visitor cannot mutate another's records", () => {
    const records = getWorkspaceRecords();
    records.listAutomations()[0].symbols.push("FAKE");
    records.listSources()[0].name = "Changed";
    expect(records.listAutomations()[0].symbols).not.toContain("FAKE");
    expect(records.listSources()[0].name).toBe("Sectors market signals");
  });
  it("keeps evidence dated and synthetic, with no delivered or live-evidence claim", () => {
    const records = getWorkspaceRecords();
    expect(records.latestRun()?.startedAt).toBe("2026-09-16T08:30:00.000Z");
    expect(records.latestRun()?.outcome).toBe("prepared-preview");
    expect(records.listEvidence("demo-run-001")[0].origin).toBe("synthetic-demo");
    expect(records.counts().liveEvidence).toBe(0);
    expect(records.listRuns(0)).toEqual([]);
    expect(records.listRuns(-1)).toEqual([]);
    expect(records.getAutomation("unknown")).toBeNull();
    expect(records.listActivity("unknown")).toEqual([]);
    expect(records.listEvidence("unknown")).toEqual([]);
  });
  it("serves sample reads but denies server mutations regardless of old demo flags", async () => {
    vi.stubEnv("NEXT_PUBLIC_HOSTED_DEMO", "0");
    const before = await GET().json();
    expect(POST().status).toBe(403);
    expect(PATCH().status).toBe(403);
    expect(await GET().json()).toEqual(before);
  });
});
