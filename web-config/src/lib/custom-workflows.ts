import { z } from "zod";

// A frontend planning contract, not the backend's scheduler or database schema.
export const workflowInputs = {
  x: "X / Twitter",
  instagram: "Instagram",
  whatsapp: "WhatsApp Channels",
  telegram: "Telegram",
} as const;
export const workflowOutputs = {
  discord: "Discord",
  whatsapp: "WhatsApp",
  telegram: "Telegram",
  slack: "Slack",
  email: "Email",
} as const;
export const workflowTopics = {
  macro_news: "Macro & economy",
  id_stocks_news: "IDX company news",
  id_stocks_swing: "Technical research",
  us_stocks_news: "US company news",
} as const;
export const workflowZones = {
  "Asia/Jakarta": "WIB · Jakarta",
  "Asia/Makassar": "WITA · Makassar",
  "Asia/Jayapura": "WIT · Jayapura",
} as const;
const unique = <T>(values: T[]) => new Set(values).size === values.length;
const fields = z
  .object({
    name: z.string().max(70, "Keep the name within 70 characters."),
    inputs: z
      .array(z.enum(["x", "instagram", "whatsapp", "telegram"]))
      .max(4)
      .refine(unique),
    topics: z
      .array(z.enum(["macro_news", "id_stocks_news", "id_stocks_swing", "us_stocks_news"]))
      .max(4)
      .refine(unique),
    trigger: z.enum(["event", "daily", "interval"]),
    time: z.string().max(5),
    // Drafts retain incomplete/invalid edits so validation never erases other fields.
    intervalMinutes: z.number(),
    weekdaysOnly: z.boolean(),
    timezone: z.enum(["Asia/Jakarta", "Asia/Makassar", "Asia/Jayapura"]),
    outputs: z
      .array(z.enum(["discord", "whatsapp", "telegram", "slack", "email"]))
      .max(5)
      .refine(unique),
    summary: z.enum(["concise", "detailed", "original"]),
    language: z.enum(["id", "en"]),
    includeSources: z.literal(true),
  })
  .strict();
export const workflowDraftSchema = fields;
export const customWorkflowSchema = fields
  .extend({
    name: z.string().trim().min(3, "Use a name with at least 3 characters.").max(70),
    inputs: fields.shape.inputs.refine((v) => v.length > 0, "Choose at least one input platform."),
    topics: fields.shape.topics.refine((v) => v.length > 0, "Choose at least one research topic."),
    outputs: fields.shape.outputs.refine(
      (v) => v.length > 0,
      "Choose at least one output channel.",
    ),
  })
  .superRefine((value, ctx) => {
    if (value.trigger === "daily" && !/^([01]\d|2[0-3]):[0-5]\d$/.test(value.time))
      ctx.addIssue({
        code: "custom",
        path: ["time"],
        message: "Choose a daily time between 00:00 and 23:59.",
      });
    if (
      value.trigger === "interval" &&
      (!Number.isInteger(value.intervalMinutes) ||
        value.intervalMinutes < 30 ||
        value.intervalMinutes > 1440)
    )
      ctx.addIssue({
        code: "custom",
        path: ["intervalMinutes"],
        message: "Choose an interval between 30 and 1,440 minutes.",
      });
  });
export type WorkflowInput = z.infer<typeof fields>;
export const blankWorkflow: WorkflowInput = {
  name: "",
  inputs: ["x"],
  topics: ["macro_news", "id_stocks_news"],
  trigger: "daily",
  time: "07:30",
  intervalMinutes: 60,
  weekdaysOnly: true,
  timezone: "Asia/Jakarta",
  outputs: ["discord"],
  summary: "concise",
  language: "id",
  includeSources: true,
};
const recordSchema = z
  .object({
    id: z.uuid(),
    revision: z.number().int().positive(),
    updatedAt: z.iso.datetime(),
    input: customWorkflowSchema,
  })
  .strict();
export type CustomWorkflow = z.infer<typeof recordSchema>;
const stateSchema = z
  .object({
    version: z.literal(1),
    workflows: z
      .array(recordSchema)
      .max(30)
      .refine((v) => unique(v.map((item) => item.id))),
  })
  .strict();
export type WorkflowState = z.infer<typeof stateSchema>;
export const emptyWorkflows: WorkflowState = { version: 1, workflows: [] };
export const workflowsKey = "bursawatch-custom-workflows-v1";
const changedEvent = "bursawatch-custom-workflows-changed";

export function decodeWorkflows(raw: string | null): WorkflowState | null {
  if (raw === null) return structuredClone(emptyWorkflows);
  try {
    return stateSchema.parse(JSON.parse(raw));
  } catch {
    return null;
  }
}
export type WorkflowChange =
  | { type: "save"; id?: string; revision?: number; input: WorkflowInput }
  | { type: "remove"; id: string; revision: number };

export function changeWorkflows(
  state: WorkflowState,
  change: WorkflowChange,
  now = new Date().toISOString(),
): WorkflowState {
  const next = structuredClone(stateSchema.parse(state));
  const saved = change.id ? next.workflows.find((item) => item.id === change.id) : undefined;
  if (change.id && (!saved || saved.revision !== change.revision))
    throw new Error(
      "This workflow changed in another tab. Keep your draft, then reopen the workflow to review the latest version.",
    );
  if (change.type === "remove") {
    next.workflows = next.workflows.filter((item) => item.id !== change.id);
  } else {
    const input = customWorkflowSchema.parse(change.input);
    if (
      next.workflows.some(
        (item) =>
          item.id !== change.id && item.input.name.toLowerCase() === input.name.toLowerCase(),
      )
    )
      throw new Error(
        "You already have a workflow with this name. Choose another name or edit the existing workflow.",
      );
    if (saved) {
      saved.input = input;
      saved.revision++;
      saved.updatedAt = now;
    } else {
      if (next.workflows.length >= 30)
        throw new Error("You have 30 workflows. Remove one before creating another.");
      next.workflows.unshift({ id: crypto.randomUUID(), revision: 1, updatedAt: now, input });
    }
  }
  return stateSchema.parse(next);
}

type WorkflowStorage = Pick<Storage, "getItem" | "setItem">;
export function saveWorkflowChange(
  change: WorkflowChange,
  storage: WorkflowStorage = localStorage,
): WorkflowState {
  let state: WorkflowState | null;
  try {
    state = decodeWorkflows(storage.getItem(workflowsKey));
  } catch {
    throw new Error(
      "Browser storage is unavailable. Allow storage and try saving again; your draft is still open.",
    );
  }
  if (!state)
    throw new Error(
      "Saved workflows could not be read. Your existing data has been kept. Reload to try again.",
    );
  const next = changeWorkflows(state, change);
  try {
    storage.setItem(workflowsKey, JSON.stringify(next));
  } catch {
    throw new Error(
      "Your browser could not save this workflow. Free some storage and try again; your draft is still open.",
    );
  }
  if (typeof window !== "undefined") window.dispatchEvent(new Event(changedEvent));
  return next;
}
export function workflowSnapshot(): string | null {
  try {
    return localStorage.getItem(workflowsKey);
  } catch {
    return "unavailable";
  }
}
export function subscribeWorkflows(listener: () => void) {
  const onStorage = (event: StorageEvent) => {
    if (event.key === workflowsKey || event.key === null) listener();
  };
  window.addEventListener("storage", onStorage);
  window.addEventListener(changedEvent, listener);
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(changedEvent, listener);
  };
}
export function workflowDraftKey(id?: string) {
  return `bursawatch-workflow-draft-${id ?? "new"}`;
}
export function restoreWorkflowDraft(
  raw: string | null,
  revision: number,
  fallback: WorkflowInput,
): WorkflowInput {
  try {
    const draft = z
      .object({ revision: z.number().int().nonnegative(), input: workflowDraftSchema })
      .strict()
      .parse(JSON.parse(raw ?? "null"));
    if (draft.revision === revision) return draft.input;
  } catch {
    /* Invalid draft data never replaces saved settings. */
  }
  return structuredClone(fallback);
}
export function workflowTiming(input: WorkflowInput): string {
  if (input.trigger === "event") return "When a matching update arrives";
  const zone = workflowZones[input.timezone].split(" · ")[0];
  if (input.trigger === "daily")
    return `${input.weekdaysOnly ? "Mon–Fri" : "Every day"} at ${input.time || "—"} ${zone}`;
  return `Every ${input.intervalMinutes || "—"} minutes · ${zone}`;
}
