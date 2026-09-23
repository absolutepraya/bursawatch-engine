import { describe, expect, it } from "vitest";

import { createAutomationSchema } from "@/lib/validation";

const validInput = {
  name: "Banking watch",
  sourceIds: ["sectors", "bri-danareksa"],
  symbols: ["bbri.jk"],
  horizon: "days-to-weeks" as const,
  triggers: {
    sourceMention: false,
    postClose: true,
    priceMove: true,
    priceMoveThreshold: 3,
    filingOrFlow: false,
  },
  scheduleTime: "15:30",
  destination: "+62 812 0000 1847",
  language: "id" as const,
  tone: "concise" as const,
};

describe("createAutomationSchema", () => {
  it("normalizes IDX tickers", () => {
    expect(createAutomationSchema.parse(validInput).symbols).toEqual(["BBRI"]);
  });

  it("requires at least one trigger", () => {
    const result = createAutomationSchema.safeParse({
      ...validInput,
      triggers: { ...validInput.triggers, sourceMention: false, postClose: false, priceMove: false },
    });
    expect(result.success).toBe(false);
  });

  it("rejects malformed tickers and WhatsApp destinations", () => {
    expect(createAutomationSchema.safeParse({ ...validInput, symbols: ["BAD"] }).success).toBe(false);
    expect(createAutomationSchema.safeParse({ ...validInput, destination: "123" }).success).toBe(false);
  });

  it("rejects unimplemented trigger adapters at the API boundary", () => {
    const result = createAutomationSchema.safeParse({
      ...validInput,
      triggers: { ...validInput.triggers, sourceMention: true },
    });
    expect(result.success).toBe(false);
  });
});
