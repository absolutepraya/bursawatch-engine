import { z } from "zod";

export const connectionProviders = [
  {
    id: "input:x",
    provider: "x",
    direction: "input",
    name: "X",
    description: "Public accounts, posts and threads",
    supported: true,
  },
  {
    id: "input:instagram",
    provider: "instagram",
    direction: "input",
    name: "Instagram",
    description: "Public posts, carousels and reels",
    supported: true,
  },
  {
    id: "input:whatsapp",
    provider: "whatsapp",
    direction: "input",
    name: "WhatsApp Channels",
    description: "Public Channel updates, not private chats",
    supported: true,
  },
  {
    id: "input:telegram",
    provider: "telegram",
    direction: "input",
    name: "Telegram",
    description: "Owner-managed research channels",
    supported: true,
  },
  {
    id: "output:discord",
    provider: "discord",
    direction: "output",
    name: "Discord",
    description: "Briefs and source-backed plan updates",
    supported: true,
  },
  {
    id: "output:whatsapp",
    provider: "whatsapp",
    direction: "output",
    name: "WhatsApp",
    description: "A future destination for your brief",
    supported: false,
  },
  {
    id: "output:telegram",
    provider: "telegram",
    direction: "output",
    name: "Telegram",
    description: "A future bot or channel destination",
    supported: false,
  },
  {
    id: "output:slack",
    provider: "slack",
    direction: "output",
    name: "Slack",
    description: "A future destination for your team",
    supported: false,
  },
  {
    id: "output:email",
    provider: "email",
    direction: "output",
    name: "Email",
    description: "A future inbox for your brief",
    supported: false,
  },
] as const;
export type ConnectionProvider = (typeof connectionProviders)[number];
export type ConnectionId = ConnectionProvider["id"];
const connectionId = z.enum([
  "input:x",
  "input:instagram",
  "input:whatsapp",
  "input:telegram",
  "output:discord",
  "output:whatsapp",
  "output:telegram",
  "output:slack",
  "output:email",
]);
export const connectionLabel = z
  .string()
  .trim()
  .min(3, "Use a name with at least 3 characters.")
  .max(60, "Keep the name within 60 characters.")
  .refine(
    (value) => !/https?:\/\/|[\r\n]|(?:bearer\s|token[=:]|password[=:]|secret[=:])/i.test(value),
    "Use a display name, not a URL, token or login details.",
  );
const planSchema = z.object({ label: connectionLabel, updatedAt: z.iso.datetime() }).strict();
const draftSchema = z
  .object({
    baseline: z.string().max(60),
    label: z
      .string()
      .max(60)
      .refine(
        (value) =>
          !/https?:\/\/|[\r\n]|(?:bearer\s|token[=:]|password[=:]|secret[=:])/i.test(value),
      ),
  })
  .strict();
export const connectionDraftKey = (id: ConnectionId | "workspace") =>
  `bursawatch-connection-draft:${id}`;
export function encodeConnectionDraft(baseline: string, label: string): string | null {
  const parsed = draftSchema.safeParse({ baseline, label });
  return parsed.success ? JSON.stringify(parsed.data) : null;
}
export function restoreConnectionDraft(raw: string | null, fallback: string): string {
  try {
    const draft = draftSchema.parse(JSON.parse(raw ?? "null"));
    return draft.baseline === fallback ? draft.label : fallback;
  } catch {
    return fallback;
  }
}
const accountSchema = z
  .object({
    version: z.literal(1),
    revision: z.number().int().nonnegative(),
    workspaceName: connectionLabel,
    connections: z.partialRecord(connectionId, planSchema),
  })
  .strict();
export type ConnectionPlans = z.infer<typeof accountSchema>;
export const emptyConnectionPlans: ConnectionPlans = {
  version: 1,
  revision: 0,
  workspaceName: "Personal workspace",
  connections: {},
};
export const connectionPlansKey = "bursawatch-connection-plans-v1";
const eventName = "bursawatch-connections-changed";
export function decodeConnectionPlans(raw: string | null): ConnectionPlans | null {
  if (raw === null) return structuredClone(emptyConnectionPlans);
  try {
    return accountSchema.parse(JSON.parse(raw));
  } catch {
    return null;
  }
}
type Change =
  | { type: "rename"; label: string }
  | { type: "save"; id: ConnectionId; label: string }
  | { type: "remove"; id: ConnectionId };
export function changeConnectionPlans(
  state: ConnectionPlans,
  revision: number,
  change: Change,
  now = new Date().toISOString(),
): ConnectionPlans {
  const next = structuredClone(accountSchema.parse(state));
  if (next.revision !== revision)
    throw new Error("Setup changed in another tab. Close this editor and reopen it before saving.");
  if (change.type === "rename") next.workspaceName = connectionLabel.parse(change.label);
  else {
    const id = connectionId.parse(change.id);
    if (change.type === "save")
      next.connections[id] = planSchema.parse({ label: change.label, updatedAt: now });
    else delete next.connections[id];
  }
  next.revision++;
  return accountSchema.parse(next);
}
export function connectionPlansSnapshot() {
  try {
    return localStorage.getItem(connectionPlansKey);
  } catch {
    return "unavailable";
  }
}
export function subscribeConnectionPlans(callback: () => void) {
  const listener = (event: StorageEvent) => {
    if (event.key === connectionPlansKey || event.key === null) callback();
  };
  window.addEventListener("storage", listener);
  window.addEventListener(eventName, callback);
  return () => {
    window.removeEventListener("storage", listener);
    window.removeEventListener(eventName, callback);
  };
}
export function saveConnectionPlan(revision: number, change: Change) {
  const state = decodeConnectionPlans(connectionPlansSnapshot());
  if (!state)
    throw new Error(
      "Saved setup could not be read. Your existing data has been kept. Enable browser storage and reload.",
    );
  const next = changeConnectionPlans(state, revision, change);
  try {
    localStorage.setItem(connectionPlansKey, JSON.stringify(next));
  } catch {
    throw new Error("Could not save. Allow browser storage or free some space and try again.");
  }
  window.dispatchEvent(new Event(eventName));
  return next;
}
