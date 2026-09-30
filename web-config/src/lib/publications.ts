import { z } from "zod";

const hexId = z.string().regex(/^[0-9a-f]{64}$/);
const awareTime = z.iso.datetime({ offset: true });
const nullableTime = awareTime.nullable();
const safeHttps = z
  .url()
  .max(2048)
  .refine((value) => {
    try {
      const url = new URL(value);
      return (
        url.protocol === "https:" &&
        !url.username &&
        !url.password &&
        (!url.port || url.port === "443")
      );
    } catch {
      return false;
    }
  });
const discordMessage = safeHttps.refine((value) => {
  const url = new URL(value);
  return (
    ["discord.com", "www.discord.com"].includes(url.hostname) &&
    /^\/channels\/[0-9]{17,20}\/[0-9]{17,20}\/[0-9]{17,20}$/.test(url.pathname)
  );
});
const attachmentUrl = safeHttps.refine((value) => {
  const url = new URL(value);
  return (
    ["cdn.discordapp.com", "media.discordapp.net"].includes(url.hostname) &&
    url.pathname.startsWith("/attachments/")
  );
});
const owner = z.enum([
  "bursawatch-tg-market-news",
  "bursawatch-stockbit-snips",
  "bursawatch-x-account-watch",
  "bursawatch-ig-account-watch",
  "bursawatch-wa-channel-watch",
  "bursawatch-tg-phintraco-swing",
  "bursawatch-tg-kelas-investasi-gtw",
  "bursawatch-dc-swing-board",
]);
const type = z.enum([
  "idx_company_news",
  "us_company_news",
  "industry_news",
  "macro_news",
  "stock_status",
  "broker_swing_plan",
  "broker_swing_update",
  "swing_context",
  "swing_bundle",
  "swing_board_update",
]);
const route = z.enum([
  "id_stocks_news",
  "id_industry_news",
  "macro_news",
  "us_stocks_news",
  "id_stocks_swing",
  "swing_board",
]);
const attachment = z
  .object({
    filename: z.string().min(1).max(255),
    content_type: z.string().min(1).max(100),
    discord_url: attachmentUrl.nullable(),
  })
  .strict();
const leg = z
  .object({
    operation_key: z.string().min(1).max(256),
    operation_digest: hexId,
    receipt_operation_id: z.string().min(1).max(128),
    destination: z.string().regex(/^[0-9]{17,20}$/),
    receipt_id: z.string().regex(/^[0-9]{17,20}$/),
    status: z.literal("delivered"),
    message_url: discordMessage.nullable(),
    text: z.string().max(16000).nullable(),
    attachments: z.array(attachment).max(10),
  })
  .strict()
  .superRefine((value, ctx) => {
    if (value.message_url) {
      const parts = new URL(value.message_url).pathname.split("/");
      if (parts[3] !== value.destination || parts[4] !== value.receipt_id)
        ctx.addIssue({ code: "custom", message: "Discord receipt link mismatch" });
    }
    if (!value.text && value.attachments.length === 0)
      ctx.addIssue({ code: "custom", message: "Published leg has no output" });
  });
const brokerLevels = z
  .object({
    entry: z.string().min(1).max(200),
    stop: z.string().min(1).max(200),
    targets: z.array(z.string().min(1).max(200)).min(1).max(10),
    units: z.string().min(1).max(80),
    attribution: z.string().min(1).max(200),
  })
  .strict();

export const publication = z
  .object({
    api_version: z.literal(1),
    publication_id: hexId,
    owner_id: owner,
    owner_key: z.string().min(1).max(256),
    version: z.number().int().min(1),
    supersedes_version: z.number().int().min(1).nullable(),
    type,
    route,
    source_event_key: z.string().max(256).nullable(),
    source_name: z.string().min(1).max(200),
    source_url: safeHttps.nullable(),
    source_published_at: nullableTime,
    market_data_as_of: nullableTime,
    delivery_confirmed_at: awareTime,
    title: z.string().min(1).max(300),
    ticker: z
      .string()
      .regex(/^[A-Z0-9][A-Z0-9.\-]{0,19}$/)
      .nullable(),
    broker_levels: brokerLevels.nullable(),
    parent_publication_id: hexId.nullable(),
    board_episode_id: z.string().max(128).nullable(),
    config_revision: z.number().int().positive().nullable(),
    renderer_version: z.string().min(1).max(100),
    source_version: z.string().max(100).nullable(),
    required_operation_keys: z.array(z.string().min(1).max(256)).min(1).max(64),
    legs: z.array(leg).min(1).max(64),
    digest: hexId,
  })
  .strict()
  .superRefine((value, ctx) => {
    if (
      value.required_operation_keys.length !== value.legs.length ||
      value.required_operation_keys.some((key, index) => key !== value.legs[index].operation_key)
    )
      ctx.addIssue({ code: "custom", message: "Required delivery legs are incomplete" });
    if (value.type === "broker_swing_plan" && !value.broker_levels)
      ctx.addIssue({ code: "custom", message: "Broker plan levels are missing" });
    if (value.type !== "broker_swing_plan" && value.broker_levels)
      ctx.addIssue({ code: "custom", message: "Broker levels are only for broker plans" });
  });

export const publicationPage = z
  .object({
    items: z.array(publication).max(100),
    next_cursor: z.string().min(1).max(2048).nullable(),
  })
  .strict();
export const publicationFilters = z
  .object({
    limit: z.number().int().min(1).max(100).optional(),
    cursor: z.string().min(1).max(2048).optional(),
    group: z.enum(["news", "swing"]).optional(),
    type: type.optional(),
    route: route.optional(),
    date_from: awareTime.optional(),
    date_to: awareTime.optional(),
    source: z.string().min(1).max(200).optional(),
    ticker: z
      .string()
      .regex(/^[A-Z0-9][A-Z0-9.\-]{0,19}$/)
      .optional(),
  })
  .strict();
export const publicationDetail = z
  .object({
    publication_id: hexId,
    versions: z.array(publication).min(1).max(100),
    linked: z
      .array(
        z
          .object({
            publication_id: hexId,
            type,
            delivery_confirmed_at: awareTime,
          })
          .strict(),
      )
      .max(100),
  })
  .strict()
  .superRefine((value, ctx) => {
    if (value.versions.some((item) => item.publication_id !== value.publication_id))
      ctx.addIssue({ code: "custom", message: "Publication detail identity mismatch" });
  });
const checkpoint = z
  .object({
    compared_at: awareTime,
    confirmed_through_at: nullableTime,
    accepted_through_at: nullableTime,
    outstanding_count: z.number().int().min(0).max(1_000_000),
  })
  .strict();
export const publicationCoverage = z
  .object({
    cutover: z
      .object({ boundary: awareTime, owner_ids: z.array(owner).min(1).max(8) })
      .strict()
      .nullable(),
    overall_status: z.enum(["not_started", "incomplete", "complete"]),
    owners: z
      .array(
        z
          .object({
            owner_id: owner,
            status: z.enum(["complete", "lagging", "unknown", "paused/unverified"]),
            checkpoint: checkpoint.nullable(),
          })
          .strict(),
      )
      .max(8),
  })
  .strict()
  .superRefine((value, ctx) => {
    if (
      value.overall_status === "complete" &&
      (!value.cutover ||
        value.owners.length !== value.cutover.owner_ids.length ||
        value.owners.some((item) => item.status !== "complete"))
    )
      ctx.addIssue({ code: "custom", message: "All-owner coverage is inconsistent" });
  });

export type Publication = z.infer<typeof publication>;
export type PublicationPage = z.infer<typeof publicationPage>;
export type PublicationDetail = z.infer<typeof publicationDetail>;
export type PublicationCoverage = z.infer<typeof publicationCoverage>;
export type PublicationFilters = z.infer<typeof publicationFilters>;

export const publicationTypeLabels: Record<Publication["type"], string> = {
  idx_company_news: "IDX company news",
  us_company_news: "US company news",
  industry_news: "Industry news",
  macro_news: "Macro news",
  stock_status: "Stock status",
  broker_swing_plan: "Broker swing plan",
  broker_swing_update: "Broker swing update",
  swing_context: "Swing context",
  swing_bundle: "Swing bundle",
  swing_board_update: "Swing Board update",
};

export const publicationOwnerLabels: Record<Publication["owner_id"], string> = {
  "bursawatch-tg-market-news": "Telegram Market News",
  "bursawatch-stockbit-snips": "Stockbit Snips",
  "bursawatch-x-account-watch": "X Account Watch",
  "bursawatch-ig-account-watch": "Instagram Account Watch",
  "bursawatch-wa-channel-watch": "WhatsApp Channel Watch",
  "bursawatch-tg-phintraco-swing": "Phintraco Swing",
  "bursawatch-tg-kelas-investasi-gtw": "Kelas Investasi GTW",
  "bursawatch-dc-swing-board": "Discord Swing Board",
};

export function appendPublicationPage(
  previous: Publication[],
  next: PublicationPage,
): Publication[] {
  const byId = new Map(previous.map((item) => [item.publication_id, item]));
  for (const item of next.items) byId.set(item.publication_id, item);
  return [...byId.values()];
}
