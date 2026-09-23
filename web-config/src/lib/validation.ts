import { z } from "zod";

import { normalizeTicker } from "@/lib/format";

const tickerSchema = z.string().transform(normalizeTicker).pipe(
  z.string().regex(/^[A-Z]{4}$/, "Use a four-letter IDX ticker such as BBRI."),
);

export const createAutomationSchema = z.object({
  name: z.string().trim().min(3, "Name must be at least 3 characters.").max(48),
  sourceIds: z.array(z.enum(["sectors", "bri-danareksa"])).max(2).refine((ids) => ids.includes("sectors"), {
    message: "Sectors evidence is required.",
  }),
  symbols: z.array(tickerSchema).min(1, "Add at least one IDX stock.").max(6),
  horizon: z.enum(["days-to-weeks", "months-to-years"]),
  triggers: z.object({
    sourceMention: z.boolean(),
    postClose: z.boolean(),
    priceMove: z.boolean(),
    priceMoveThreshold: z.number().min(1).max(15),
    filingOrFlow: z.boolean(),
  }).refine((triggers) => triggers.sourceMention || triggers.postClose || triggers.priceMove || triggers.filingOrFlow, {
    message: "Enable at least one trigger.",
  }).refine((triggers) => !triggers.sourceMention && !triggers.filingOrFlow, {
    message: "Source-mention and filing/flow adapters are not active in this MVP.",
  }),
  scheduleTime: z.string().regex(/^([01]\d|2[0-3]):[0-5]\d$/, "Use a valid 24-hour time."),
  destination: z.string().trim().regex(/^\+?[0-9][0-9\s-]{8,20}$/, "Enter a valid WhatsApp number with country code."),
  language: z.enum(["id", "en"]),
  tone: z.enum(["concise", "beginner", "analyst"]),
});

export const automationStatusSchema = z.object({
  status: z.enum(["active", "paused"]),
});
