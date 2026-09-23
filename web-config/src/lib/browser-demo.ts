import { z } from "zod";
import { maskDestination } from "@/lib/format";
import { createAutomationSchema } from "@/lib/validation";
import type { CreateAutomationInput } from "@/lib/types";

const key = "bursawatch-demo-watches-v1";
const savedSchema = z.object({ id: z.string(), name: z.string(), symbols: z.array(z.string()), scheduleTime: z.string(), destinationMasked: z.string(), paused: z.boolean(), threshold: z.number(), createdAt: z.string(), language: z.enum(["id", "en"]).default("id"), tone: z.enum(["concise", "beginner", "analyst"]).default("concise"), horizon: z.enum(["days-to-weeks", "months-to-years"]).default("days-to-weeks"), sourceIds: z.array(z.string()).default(["sectors"]), triggers: createAutomationSchema.shape.triggers.optional() });
export type BrowserWatch = z.infer<typeof savedSchema>;
export function readBrowserWatches(): BrowserWatch[] {
  try { return z.array(savedSchema).parse(JSON.parse(localStorage.getItem(key) ?? "[]")); } catch { return []; }
}
function write(watches: BrowserWatch[]) {
  localStorage.setItem(key, JSON.stringify(watches));
  window.dispatchEvent(new Event("bursawatch-saved"));
}
export function saveBrowserWatch(input: CreateAutomationInput) {
  const parsed = createAutomationSchema.safeParse(input);
  if (!parsed.success) throw new Error(parsed.error.issues[0]?.message ?? "Check your watch settings.");
  const { name, symbols, scheduleTime, destination, triggers, language, tone, horizon, sourceIds } = parsed.data;
  write([{ id: crypto.randomUUID(), name, symbols, scheduleTime, destinationMasked: maskDestination(destination), paused: false, threshold: triggers.priceMoveThreshold, createdAt: new Date().toISOString(), language, tone, horizon, sourceIds, triggers }, ...readBrowserWatches()].slice(0, 20));
}
export function toggleBrowserWatch(id: string) { write(readBrowserWatches().map(watch => watch.id === id ? { ...watch, paused: !watch.paused } : watch)); }
