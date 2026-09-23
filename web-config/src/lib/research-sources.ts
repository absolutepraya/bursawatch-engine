import { z } from "zod";

export const platforms = {
  x: "X / Twitter",
  instagram: "Instagram",
  whatsapp: "WhatsApp",
  telegram: "Telegram",
} as const;
export type Platform = keyof typeof platforms;
export const topics = {
  macro_news: {
    label: "Macro & economy",
    description: "Rates, currencies, policy and the wider market.",
  },
  id_stocks_news: {
    label: "IDX company news",
    description: "Earnings, dividends and corporate developments.",
  },
  id_stocks_swing: {
    label: "Technical research",
    description: "Source-published charts and trading setups.",
  },
  us_stocks_news: { label: "US company news", description: "Developments in US-listed companies." },
} as const;
export type Topic = keyof typeof topics;

export function normalizeSourceUrl(platform: Platform, input: string): string {
  let value = input.trim();
  if (platform === "x" && /^@?[a-zA-Z0-9_]{1,15}$/.test(value))
    value = `https://x.com/${value.replace(/^@/, "")}`;
  if (platform === "instagram" && /^@?[a-zA-Z0-9_][a-zA-Z0-9_.]{0,29}$/.test(value))
    value = `https://www.instagram.com/${value.replace(/^@/, "")}`;
  if (!/^https:\/\//i.test(value)) throw new Error("Paste a public HTTPS profile or channel link.");
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error("Check the link and try again.");
  }
  if (url.username || url.password || url.port)
    throw new Error("Use a public link without login details or a port.");
  const host = url.hostname.toLowerCase();
  const path = url.pathname.replace(/\/$/, "");
  if (
    platform === "x" &&
    ["x.com", "www.x.com", "twitter.com", "www.twitter.com"].includes(host) &&
    /^\/[a-zA-Z0-9_]{1,15}$/.test(path) &&
    !/^\/(home|explore|search|i|intent|settings|compose)$/i.test(path)
  )
    return `https://x.com${path.toLowerCase()}`;
  if (
    platform === "instagram" &&
    ["instagram.com", "www.instagram.com"].includes(host) &&
    /^\/[a-zA-Z0-9_][a-zA-Z0-9_.]{0,29}$/.test(path) &&
    !path.endsWith(".") &&
    !path.includes("..") &&
    !/^\/(p|reel|reels|stories|explore|accounts|direct|about|developer|legal|web)$/i.test(path)
  )
    return `https://www.instagram.com${path.toLowerCase()}`;
  if (
    platform === "whatsapp" &&
    ["whatsapp.com", "www.whatsapp.com"].includes(host) &&
    /^\/channel\/[a-zA-Z0-9]{10,128}$/.test(path)
  )
    return `https://www.whatsapp.com${path}`;
  if (
    platform === "telegram" &&
    ["t.me", "www.t.me"].includes(host) &&
    /^\/[a-zA-Z][a-zA-Z0-9_]{4,31}$/.test(path)
  )
    return `https://t.me${path.toLowerCase()}`;
  throw new Error(
    platform === "x"
      ? "Use an X profile link, not an individual post."
      : platform === "instagram"
        ? "Use an Instagram profile link, not a post, reel or story."
        : platform === "whatsapp"
          ? "Use a public whatsapp.com/channel/… link, not a chat or group invite."
          : "Use a public t.me/channelname link, not an invite or individual message.",
  );
}

const sourceFieldsSchema = z.object({
  name: z.string().trim().min(3, "Use a name with at least 3 characters.").max(60),
  platform: z.enum(["x", "instagram", "whatsapp", "telegram"]),
  url: z.string().trim().max(300),
  topics: z
    .array(z.enum(["macro_news", "id_stocks_news", "id_stocks_swing", "us_stocks_news"]))
    .min(1, "Choose at least one topic.")
    .max(4)
    .refine((v) => new Set(v).size === v.length, "Choose each topic once."),
  format: z.enum(["summary", "original"]),
  includeMedia: z.boolean(),
  includeQuotes: z.boolean(),
  includeReposts: z.boolean(),
  includeOriginals: z.boolean().default(true),
  includeReplies: z.boolean().default(false),
  groupThreads: z.boolean().default(true),
  includePosts: z.boolean().default(true),
  includeReels: z.boolean().default(true),
  instructions: z.string().trim().max(600, "Keep instructions within 600 characters."),
});
export const sourceDraftSchema = sourceFieldsSchema.extend({
  name: z.string().max(60),
  url: z.string().max(300),
  topics: z
    .array(z.enum(["macro_news", "id_stocks_news", "id_stocks_swing", "us_stocks_news"]))
    .max(4),
});
export const sourceInputSchema = sourceFieldsSchema
  .superRefine((value, ctx) => {
    if (
      value.platform === "x" &&
      !value.includeOriginals &&
      !value.includeReplies &&
      !value.includeQuotes &&
      !value.includeReposts
    )
      ctx.addIssue({
        code: "custom",
        path: ["includeOriginals"],
        message: "Include at least one X post type.",
      });
    if (value.platform === "instagram" && !value.includePosts && !value.includeReels)
      ctx.addIssue({
        code: "custom",
        path: ["includePosts"],
        message: "Include posts, reels or both.",
      });
    try {
      normalizeSourceUrl(value.platform, value.url);
    } catch (e) {
      ctx.addIssue({ code: "custom", path: ["url"], message: (e as Error).message });
    }
  })
  .transform((value) => ({ ...value, url: normalizeSourceUrl(value.platform, value.url) }));
export type SourceInput = z.input<typeof sourceInputSchema>;
export const blankSource: SourceInput = {
  name: "",
  platform: "x",
  url: "",
  topics: ["macro_news", "id_stocks_news"],
  format: "summary",
  includeMedia: true,
  includeQuotes: true,
  includeReposts: false,
  includeOriginals: true,
  includeReplies: false,
  groupThreads: true,
  includePosts: true,
  includeReels: true,
  instructions: "",
};
const savedSourceSchema = z.object({
  id: z.string().uuid(),
  revision: z.number().int().positive(),
  enabled: z.boolean(),
  updatedAt: z.iso.datetime(),
  input: sourceInputSchema,
});
export type ResearchSource = z.infer<typeof savedSourceSchema>;
const stateSchema = z.object({
  version: z.literal(1),
  sources: z
    .array(savedSourceSchema)
    .max(30)
    .refine(
      (items) =>
        new Set(items.map((i) => i.input.url)).size === items.length &&
        new Set(items.map((i) => i.id)).size === items.length,
    ),
});
export type ResearchState = z.infer<typeof stateSchema>;
export const researchKey = "bursawatch-research-sources-v1";
const eventName = "bursawatch-research-changed";
export const emptyResearch: ResearchState = { version: 1, sources: [] };
export function decodeResearch(raw: string | null): ResearchState | null {
  if (!raw) return emptyResearch;
  try {
    return stateSchema.parse(JSON.parse(raw));
  } catch {
    return null;
  }
}
type Change =
  | { type: "save"; id?: string; revision?: number; input: SourceInput }
  | { type: "toggle" | "remove"; id: string; revision: number };
export function changeResearch(
  state: ResearchState,
  change: Change,
  now = new Date().toISOString(),
): ResearchState {
  const next = structuredClone(stateSchema.parse(state));
  const source = change.id ? next.sources.find((s) => s.id === change.id) : undefined;
  if (change.id && (!source || source.revision !== change.revision))
    throw new Error(
      "This source changed in another tab. Close the editor and reopen it to load the latest settings.",
    );
  if (change.type === "save") {
    const input = sourceInputSchema.parse(change.input);
    if (next.sources.some((s) => s.id !== change.id && s.input.url === input.url))
      throw new Error("You already follow this source. Edit its existing settings instead.");
    if (source) {
      source.input = input;
      source.revision++;
      source.updatedAt = now;
    } else {
      if (next.sources.length >= 30)
        throw new Error("You have 30 sources. Remove one before adding another.");
      next.sources.unshift({
        id: crypto.randomUUID(),
        revision: 1,
        enabled: true,
        updatedAt: now,
        input,
      });
    }
  } else if (source && change.type === "toggle") {
    source.enabled = !source.enabled;
    source.revision++;
    source.updatedAt = now;
  } else if (source) next.sources = next.sources.filter((s) => s.id !== source.id);
  return stateSchema.parse(next);
}
export function researchSnapshot() {
  try {
    return localStorage.getItem(researchKey) ?? "";
  } catch {
    return "unavailable";
  }
}
export function subscribeResearch(callback: () => void) {
  const listener = (e: StorageEvent) => {
    if (e.key === researchKey || e.key === null) callback();
  };
  window.addEventListener("storage", listener);
  window.addEventListener(eventName, callback);
  return () => {
    window.removeEventListener("storage", listener);
    window.removeEventListener(eventName, callback);
  };
}
export function updateResearch(change: Change) {
  const state = decodeResearch(researchSnapshot());
  if (!state) throw new Error("Saved sources could not be read. Your existing data has been kept.");
  const next = changeResearch(state, change);
  try {
    localStorage.setItem(researchKey, JSON.stringify(next));
  } catch {
    throw new Error("Could not save. Allow browser storage or free some space, then try again.");
  }
  window.dispatchEvent(new Event(eventName));
  return next;
}
