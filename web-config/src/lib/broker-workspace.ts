import { z } from "zod";
import type { BrokerId } from "@/lib/brokers";

export const workspaceKey = "bursawatch-broker-workspace-v1";
export const workspaceEvent = "bursawatch-brokers-changed";
const brokerIdSchema = z.enum(["bri-danareksa", "phintraco"]);
export const preferencesSchema = z.object({
  goal: z.enum(["scalp", "swing", "invest"]),
  priceSummary: z.boolean(),
  language: z.enum(["id", "en"]),
  tone: z.enum(["concise", "plain", "analytical"]),
  instructions: z.string().trim().max(600, "Keep instructions under 600 characters."),
});
export type BrokerPreferences = z.infer<typeof preferencesSchema>;
export const defaultPreferences: BrokerPreferences = {
  goal: "swing",
  priceSummary: true,
  language: "id",
  tone: "concise",
  instructions: "",
};
const draftSchema = z.object({ baseline: preferencesSchema, draft: preferencesSchema });
const draftKey = (id: BrokerId) => `bursawatch-broker-draft-v1:${id}`;
export function readBrokerDraft(
  id: BrokerId,
  baseline: BrokerPreferences,
): BrokerPreferences | null {
  try {
    const raw = sessionStorage.getItem(draftKey(id));
    if (!raw) return null;
    const parsed = draftSchema.parse(JSON.parse(raw));
    return JSON.stringify(parsed.baseline) === JSON.stringify(baseline) ? parsed.draft : null;
  } catch {
    return null;
  }
}
export function saveBrokerDraft(
  id: BrokerId,
  baseline: BrokerPreferences,
  draft: BrokerPreferences,
): boolean {
  try {
    sessionStorage.setItem(draftKey(id), JSON.stringify(draftSchema.parse({ baseline, draft })));
    return true;
  } catch {
    return false;
  }
}
export function clearBrokerDraft(id: BrokerId) {
  try {
    sessionStorage.removeItem(draftKey(id));
  } catch {
    /* Persisted configuration remains authoritative. */
  }
}
const watchSchema = z.object({
  brokerId: brokerIdSchema,
  preferences: preferencesSchema,
  paused: z.boolean(),
  updatedAt: z.iso.datetime(),
});
const eventSchema = z.object({
  id: z.string(),
  brokerId: brokerIdSchema,
  action: z.enum(["added", "configured", "paused", "resumed", "removed"]),
  at: z.iso.datetime(),
});
export const workspaceSchema = z.object({
  version: z.literal(1),
  watches: z
    .array(watchSchema)
    .max(2)
    .refine((items) => new Set(items.map((x) => x.brokerId)).size === items.length),
  events: z.array(eventSchema).max(50),
});
export type BrokerWorkspace = z.infer<typeof workspaceSchema>;
export const emptyWorkspace: BrokerWorkspace = { version: 1, watches: [], events: [] };
export function decodeWorkspace(raw: string | null): BrokerWorkspace | null {
  if (raw === null) return emptyWorkspace;
  try {
    return workspaceSchema.parse(JSON.parse(raw));
  } catch {
    return null;
  }
}
export function workspaceSnapshot(): string {
  try {
    return localStorage.getItem(workspaceKey) ?? "";
  } catch {
    return "unavailable";
  }
}
export function subscribeWorkspace(callback: () => void) {
  const storageListener = (event: StorageEvent) => {
    if (event.key === workspaceKey || event.key === null) callback();
  };
  window.addEventListener("storage", storageListener);
  window.addEventListener(workspaceEvent, callback);
  return () => {
    window.removeEventListener("storage", storageListener);
    window.removeEventListener(workspaceEvent, callback);
  };
}
type Change =
  | { type: "add"; ids: BrokerId[] }
  | { type: "configure"; id: BrokerId; preferences: BrokerPreferences }
  | { type: "toggle" | "remove"; id: BrokerId };

// Pure transition: the future server adapter can retain the same validation rules.
export function changeWorkspace(
  state: BrokerWorkspace,
  change: Change,
  now = new Date().toISOString(),
): BrokerWorkspace {
  const next = structuredClone(workspaceSchema.parse(state));
  const log = (brokerId: BrokerId, action: BrokerWorkspace["events"][number]["action"]) => {
    next.events.unshift({ id: crypto.randomUUID(), brokerId, action, at: now });
  };
  if (change.type === "add") {
    for (const id of new Set(change.ids)) {
      brokerIdSchema.parse(id);
      if (next.watches.some((watch) => watch.brokerId === id)) continue;
      next.watches.push({
        brokerId: id,
        preferences: { ...defaultPreferences },
        paused: false,
        updatedAt: now,
      });
      log(id, "added");
    }
  } else {
    const watch = next.watches.find((watch) => watch.brokerId === change.id);
    if (!watch)
      throw new Error(
        "This firm is no longer in your watched securities. Add it again to configure it.",
      );
    if (change.type === "configure") {
      watch.preferences = preferencesSchema.parse(change.preferences);
      watch.updatedAt = now;
      log(change.id, "configured");
    } else if (change.type === "toggle") {
      watch.paused = !watch.paused;
      watch.updatedAt = now;
      log(change.id, watch.paused ? "paused" : "resumed");
    } else {
      next.watches = next.watches.filter((watch) => watch.brokerId !== change.id);
      log(change.id, "removed");
    }
  }
  next.events = next.events.slice(0, 50);
  return workspaceSchema.parse(next);
}
export function updateWorkspace(change: Change): BrokerWorkspace {
  let raw: string | null;
  try {
    raw = localStorage.getItem(workspaceKey);
  } catch {
    throw new Error("Browser storage is unavailable. Allow site storage and try again.");
  }
  const state = decodeWorkspace(raw);
  if (!state)
    throw new Error("Saved settings could not be read. Your stored data has not been changed.");
  const next = changeWorkspace(state, change);
  try {
    localStorage.setItem(workspaceKey, JSON.stringify(next));
  } catch {
    throw new Error("Could not save your settings. Free some browser storage and try again.");
  }
  window.dispatchEvent(new Event(workspaceEvent));
  return next;
}
