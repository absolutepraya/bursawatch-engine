import { z } from "zod";
import { topics as researchTopics, type Topic } from "./research-sources";

export const channels = {
  whatsapp: {
    name: "WhatsApp",
    destination: "Recipient label",
    placeholder: "My personal WhatsApp",
    hint: "Name the person or group. Pairing happens during connection setup.",
  },
  telegram: {
    name: "Telegram",
    destination: "Chat label",
    placeholder: "My research channel",
    hint: "Name the chat or channel. The bot will need permission to post.",
  },
  discord: {
    name: "Discord",
    destination: "Channel label",
    placeholder: "Market desk · #daily-brief",
    hint: "Choose a recognizable server and channel name. No webhook URL needed here.",
  },
  slack: {
    name: "Slack",
    destination: "Channel label",
    placeholder: "Research team · #markets",
    hint: "Name the workspace and channel. Workspace approval is required before delivery.",
  },
  email: {
    name: "Email",
    destination: "Inbox label",
    placeholder: "My research inbox",
    hint: "Name the inbox. A verified address will be requested during connection setup.",
  },
} as const;
export type Channel = keyof typeof channels;
export const deliveryTopics = {
  market: "Market alerts",
  research: "Research updates",
  brief: "Daily brief",
  health: "Connection issues",
} as const;
const time = z.string().regex(/^([01]\d|2[0-3]):[0-5]\d$/, "Choose a valid time.");
const deliveryFieldsSchema = z.object({
  destination: z.string().trim().min(3, "Use a label with at least 3 characters.").max(80),
  enabled: z.boolean(),
  cadence: z.enum(["as-ready", "digest"]),
  digestTime: time,
  timezone: z.enum(["Asia/Jakarta", "Asia/Makassar", "Asia/Jayapura"]),
  weekdaysOnly: z.boolean(),
  topics: z
    .array(z.enum(["market", "research", "brief", "health"]))
    .min(1, "Choose at least one update type.")
    .max(4)
    .refine((v) => new Set(v).size === v.length, "Choose each update type once."),
  quietEnabled: z.boolean(),
  quietStart: time,
  quietEnd: time,
});
export const deliverySchema = deliveryFieldsSchema.superRefine((v, ctx) => {
  if (v.quietEnabled && v.quietStart === v.quietEnd)
    ctx.addIssue({
      code: "custom",
      path: ["quietEnd"],
      message: "Quiet hours must have different start and end times.",
    });
  if (/https?:\/\/|[\r\n]/i.test(v.destination))
    ctx.addIssue({
      code: "custom",
      path: ["destination"],
      message: "Use a destination label, not a URL, webhook or credential.",
    });
  if (
    v.quietEnabled &&
    v.cadence === "digest" &&
    isQuietTime(v.digestTime, v.quietStart, v.quietEnd)
  )
    ctx.addIssue({
      code: "custom",
      path: ["digestTime"],
      message: "Choose a digest time outside your quiet hours.",
    });
});
export type DeliveryInput = z.infer<typeof deliverySchema>;
export const defaultDelivery: DeliveryInput = {
  destination: "",
  enabled: true,
  cadence: "as-ready",
  digestTime: "16:30",
  timezone: "Asia/Jakarta",
  weekdaysOnly: true,
  topics: ["market", "research", "brief"],
  quietEnabled: false,
  quietStart: "21:00",
  quietEnd: "07:00",
};
export function isQuietTime(value: string, start: string, end: string) {
  return start < end ? value >= start && value < end : value >= start || value < end;
}
export const defaultInterests: Topic[] = Object.keys(researchTopics) as Topic[];
const interestList = z.array(z.enum(defaultInterests)).max(4);
export const botSchema = z.object({
  name: z.string().trim().min(2, "Use a name with at least 2 characters.").max(32),
  language: z.enum(["id", "en"]),
  tone: z.enum(["concise", "beginner", "analyst"]),
  length: z.enum(["short", "standard", "detailed"]),
  includeSources: z.literal(true),
  includeTime: z.boolean(),
  includeCharts: z.boolean(),
  useEmoji: z.boolean(),
  instructions: z.string().trim().max(600, "Keep instructions within 600 characters."),
  interests: interestList
    .min(1, "Choose at least one research interest.")
    .refine((value) => new Set(value).size === value.length, "Choose each interest once.")
    .default([...defaultInterests]),
  onboardingComplete: z.boolean().default(false),
});
export type BotInput = z.infer<typeof botSchema>;
export const defaultBot: BotInput = {
  name: "Bursawatch",
  language: "id",
  tone: "concise",
  length: "standard",
  includeSources: true,
  includeTime: true,
  includeCharts: true,
  useEmoji: false,
  instructions: "",
  interests: [...defaultInterests],
  onboardingComplete: false,
};

export const deliveryDraftSchema = deliveryFieldsSchema
  .extend({
    destination: z.string().max(80),
    digestTime: z.string().max(5),
    quietStart: z.string().max(5),
    quietEnd: z.string().max(5),
    topics: z.array(z.enum(["market", "research", "brief", "health"])).max(4),
  })
  .partial();
export const botDraftSchema = botSchema
  .extend({
    name: z.string().max(32),
    instructions: z.string().max(600),
    interests: interestList,
    onboardingComplete: z.boolean(),
  })
  .partial();

function restoreDraft<T>(
  raw: string | null,
  revision: number,
  fallback: T,
  schema: z.ZodType<Partial<T>>,
): T {
  try {
    const draft = z
      .object({ revision: z.number().int().nonnegative(), input: schema })
      .parse(JSON.parse(raw ?? "null"));
    if (draft.revision === revision) return structuredClone({ ...fallback, ...draft.input });
  } catch {
    /* Invalid drafts never replace saved preferences. */
  }
  return structuredClone(fallback);
}
export function restoreDeliveryDraft(
  raw: string | null,
  revision: number,
  fallback: DeliveryInput,
): DeliveryInput {
  return restoreDraft(raw, revision, fallback, deliveryDraftSchema);
}
export function restoreBotDraft(
  raw: string | null,
  revision: number,
  fallback: BotInput,
): BotInput {
  return restoreDraft(raw, revision, fallback, botDraftSchema);
}
const stateSchema = z.object({
  version: z.literal(1),
  revision: z.number().int().nonnegative(),
  bot: botSchema,
  delivery: z.partialRecord(
    z.enum(["whatsapp", "telegram", "discord", "slack", "email"]),
    deliverySchema,
  ),
});
export type Preferences = z.infer<typeof stateSchema>;
export const emptyPreferences: Preferences = {
  version: 1,
  revision: 0,
  bot: defaultBot,
  delivery: {},
};
export const preferencesKey = "bursawatch-delivery-preferences-v1";
const changedEvent = "bursawatch-delivery-changed";
export function decodePreferences(raw: string | null): Preferences | null {
  if (!raw) return emptyPreferences;
  try {
    return stateSchema.parse(JSON.parse(raw));
  } catch {
    return null;
  }
}
type Change =
  | { type: "bot"; input: BotInput }
  | { type: "delivery"; channel: Channel; input: DeliveryInput }
  | { type: "remove"; channel: Channel };
export function changePreferences(
  state: Preferences,
  revision: number,
  change: Change,
): Preferences {
  const next = structuredClone(stateSchema.parse(state));
  if (next.revision !== revision)
    throw new Error("Settings changed in another tab. Reload the latest settings before saving.");
  if (change.type === "bot") next.bot = botSchema.parse(change.input);
  else if (change.type === "delivery")
    next.delivery[change.channel] = deliverySchema.parse(change.input);
  else delete next.delivery[change.channel];
  next.revision++;
  return stateSchema.parse(next);
}
export function preferencesSnapshot() {
  try {
    return localStorage.getItem(preferencesKey) ?? "";
  } catch {
    return "unavailable";
  }
}
export function subscribePreferences(callback: () => void) {
  const listener = (e: StorageEvent) => {
    if (e.key === preferencesKey || e.key === null) callback();
  };
  window.addEventListener("storage", listener);
  window.addEventListener(changedEvent, callback);
  return () => {
    window.removeEventListener("storage", listener);
    window.removeEventListener(changedEvent, callback);
  };
}
export function savePreferences(revision: number, change: Change) {
  const state = decodePreferences(preferencesSnapshot());
  if (!state)
    throw new Error("Saved settings could not be read. Your existing data has been kept.");
  const next = changePreferences(state, revision, change);
  try {
    localStorage.setItem(preferencesKey, JSON.stringify(next));
  } catch {
    throw new Error("Could not save. Allow browser storage or free some space, then try again.");
  }
  window.dispatchEvent(new Event(changedEvent));
  return next;
}

export function exampleMessage(bot: BotInput) {
  const id = bot.language === "id";
  const title = id ? "Ringkasan pasar" : "Market brief";
  const opening = id
    ? bot.tone === "beginner"
      ? "Ada kabar baru untuk saham yang kamu ikuti."
      : bot.tone === "analyst"
        ? "Tinjauan sumber: pembaruan emiten dan konteks pasar."
        : "Pembaruan dari sumber yang kamu ikuti."
    : bot.tone === "beginner"
      ? "There is a new update about a company you follow."
      : bot.tone === "analyst"
        ? "Source review: company developments and market context."
        : "Updates from the sources you follow.";
  const detail = id
    ? "Pisahkan fakta emiten dari pandangan analis. Baca sumber sebelum mengambil keputusan."
    : "Keep company facts separate from analyst views. Read the source before making a decision.";
  const extra = id
    ? "Yang perlu diperhatikan: tanggal publikasi, konteks berita, dan keterbatasan data."
    : "What to check: publication date, context, and data limitations.";
  return `${bot.useEmoji ? "📰 " : ""}${title}\n${opening}${bot.length !== "short" ? "\n\n" + detail : ""}${bot.length === "detailed" ? "\n\n" + extra : ""}\n\n${id ? "Sumber: tautan publikasi asli" : "Source: original publication link"}${bot.includeTime ? "\n16:30 WIB" : ""}`;
}
