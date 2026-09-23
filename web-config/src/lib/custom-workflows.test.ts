import { describe, expect, it } from "vitest";
import {
  blankWorkflow,
  changeWorkflows,
  customWorkflowSchema,
  decodeWorkflows,
  emptyWorkflows,
  restoreWorkflowDraft,
  saveWorkflowChange,
  workflowTiming,
  workflowsKey,
} from "./custom-workflows";

const input = { ...blankWorkflow, name: "Morning research" };
const now = "2026-09-18T10:00:00.000Z";

describe("custom workflow configuration", () => {
  it("creates independent, dated configurations and preserves inputs vs outputs", () => {
    const state = changeWorkflows(
      emptyWorkflows,
      {
        type: "save",
        input: { ...input, inputs: ["whatsapp", "instagram"], outputs: ["discord", "email"] },
      },
      now,
    );
    expect(state.workflows[0]).toMatchObject({
      revision: 1,
      updatedAt: now,
      input: {
        inputs: ["whatsapp", "instagram"],
        outputs: ["discord", "email"],
        includeSources: true,
      },
    });
    expect(decodeWorkflows(JSON.stringify(state))).toEqual(state);
    expect(emptyWorkflows.workflows).toHaveLength(0);
  });
  it("requires a name and at least one unique input, topic and output", () => {
    for (const fields of [
      { name: "  " },
      { name: "ab" },
      { name: "x".repeat(71) },
      { inputs: [] },
      { inputs: ["x", "x"] },
      { inputs: ["email"] },
      { topics: [] },
      { topics: ["macro_news", "macro_news"] },
      { topics: ["secret"] },
      { outputs: [] },
      { outputs: ["discord", "discord"] },
      { outputs: ["webhook"] },
    ])
      expect(customWorkflowSchema.safeParse({ ...input, ...fields }).success).toBe(false);
  });
  it("bounds interval cadence, validates daily time, rejects unknown zones and secrets", () => {
    for (const fields of [
      { trigger: "daily", time: "24:00" },
      { trigger: "daily", time: "7:00" },
      { trigger: "interval", intervalMinutes: 29 },
      { trigger: "interval", intervalMinutes: 1441 },
      { trigger: "interval", intervalMinutes: 30.5 },
      { trigger: "interval", intervalMinutes: NaN },
      { timezone: "UTC+7" },
      { token: "secret" },
      { webhook: "https://example.com" },
      { includeSources: false },
    ])
      expect(customWorkflowSchema.safeParse({ ...input, ...fields }).success).toBe(false);
    for (const intervalMinutes of [30, 60, 1440])
      expect(
        customWorkflowSchema.safeParse({ ...input, trigger: "interval", intervalMinutes }).success,
      ).toBe(true);
    expect(
      customWorkflowSchema.safeParse({ ...input, trigger: "event", time: "", intervalMinutes: 0 })
        .success,
    ).toBe(true);
  });
  it("edits and removes only the expected revision", () => {
    const initial = changeWorkflows(emptyWorkflows, { type: "save", input }, now);
    const item = initial.workflows[0];
    const next = changeWorkflows(
      initial,
      { type: "save", id: item.id, revision: 1, input: { ...input, trigger: "event" } },
      now,
    );
    expect(next.workflows[0].revision).toBe(2);
    expect(initial.workflows[0].input.trigger).toBe("daily");
    expect(() => changeWorkflows(next, { type: "save", id: item.id, revision: 1, input })).toThrow(
      "another tab",
    );
    expect(() => changeWorkflows(next, { type: "remove", id: item.id, revision: 1 })).toThrow(
      "another tab",
    );
    const removed = changeWorkflows(next, { type: "remove", id: item.id, revision: 2 });
    expect(removed.workflows).toHaveLength(0);
    expect(() =>
      changeWorkflows(removed, { type: "save", id: item.id, revision: 2, input }),
    ).toThrow("another tab");
  });
  it("prevents duplicate names and bounds saved workflow count", () => {
    let state = changeWorkflows(emptyWorkflows, { type: "save", input }, now);
    expect(() =>
      changeWorkflows(state, { type: "save", input: { ...input, name: "  MORNING RESEARCH " } }),
    ).toThrow("already have");
    for (let i = 1; i < 30; i++)
      state = changeWorkflows(
        state,
        { type: "save", input: { ...input, name: `Workflow ${i}` } },
        now,
      );
    expect(() =>
      changeWorkflows(state, { type: "save", input: { ...input, name: "One too many" } }),
    ).toThrow("30 workflows");
  });
  it("keeps malformed saved storage intact rather than resetting it", () => {
    for (const raw of ["", "{", '{"version":2,"workflows":[]}', '{"version":1,"workflows":null}']) {
      let value = raw;
      const storage = {
        getItem: () => value,
        setItem: (_key: string, next: string) => {
          value = next;
        },
      };
      expect(decodeWorkflows(raw)).toBeNull();
      expect(() => saveWorkflowChange({ type: "save", input }, storage)).toThrow(
        "existing data has been kept",
      );
      expect(value).toBe(raw);
    }
    expect(decodeWorkflows(null)).toEqual(emptyWorkflows);
  });
  it("checks latest storage on each save so unrelated changes survive", () => {
    let value: string | null = null;
    const storage = {
      getItem: () => value,
      setItem: (key: string, next: string) => {
        expect(key).toBe(workflowsKey);
        value = next;
      },
    };
    const first = saveWorkflowChange({ type: "save", input }, storage).workflows[0];
    saveWorkflowChange({ type: "save", input: { ...input, name: "Company updates" } }, storage);
    const edited = saveWorkflowChange(
      { type: "save", id: first.id, revision: 1, input: { ...input, trigger: "event" } },
      storage,
    );
    expect(edited.workflows).toHaveLength(2);
    expect(() =>
      saveWorkflowChange({ type: "remove", id: first.id, revision: 1 }, storage),
    ).toThrow("another tab");
  });
  it("reports blocked reads and full storage without claiming a successful save", () => {
    expect(() =>
      saveWorkflowChange(
        { type: "save", input },
        {
          getItem: () => {
            throw new Error();
          },
          setItem: () => {},
        },
      ),
    ).toThrow("storage is unavailable");
    expect(() =>
      saveWorkflowChange(
        { type: "save", input },
        {
          getItem: () => null,
          setItem: () => {
            throw new Error();
          },
        },
      ),
    ).toThrow("could not save");
  });
  it("restores incomplete drafts only for their current revision", () => {
    const draft = { ...input, name: "", inputs: [], outputs: [], time: "", intervalMinutes: 0 };
    expect(restoreWorkflowDraft(JSON.stringify({ revision: 2, input: draft }), 2, input)).toEqual(
      draft,
    );
    expect(restoreWorkflowDraft(JSON.stringify({ revision: 1, input: draft }), 2, input)).toEqual(
      input,
    );
    for (const raw of [
      "{",
      JSON.stringify({ revision: 2, input: { ...draft, inputs: "x" } }),
      JSON.stringify({ revision: 2, input: { ...draft, botToken: "secret" } }),
    ])
      expect(restoreWorkflowDraft(raw, 2, input)).toEqual(input);
  });
  it("describes configured cadence without claiming it is scheduled", () => {
    expect(workflowTiming(input)).toBe("Mon–Fri at 07:30 WIB");
    expect(workflowTiming({ ...input, weekdaysOnly: false, timezone: "Asia/Jayapura" })).toBe(
      "Every day at 07:30 WIT",
    );
    expect(workflowTiming({ ...input, trigger: "event" })).toBe("When a matching update arrives");
    expect(workflowTiming({ ...input, trigger: "interval", intervalMinutes: 30 })).toBe(
      "Every 30 minutes · WIB",
    );
  });
  it("recovers invalid interval drafts and validates only the selected timing rule", () => {
    for (const intervalMinutes of [-1, 30.5, 1441]) {
      const draft = { ...input, trigger: "interval" as const, intervalMinutes };
      expect(restoreWorkflowDraft(JSON.stringify({ revision: 1, input: draft }), 1, input)).toEqual(
        draft,
      );
      expect(customWorkflowSchema.safeParse(draft).success).toBe(false);
      expect(customWorkflowSchema.safeParse({ ...draft, trigger: "daily" }).success).toBe(true);
      expect(customWorkflowSchema.safeParse({ ...draft, trigger: "event" }).success).toBe(true);
    }
  });
});
