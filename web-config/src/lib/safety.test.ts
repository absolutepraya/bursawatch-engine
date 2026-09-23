import { describe, expect, it } from "vitest";

import { assertInformationOnly } from "@/lib/safety";

describe("assertInformationOnly", () => {
  it("allows evidence-first informational language", () => {
    const text = "BBRI moved 3.60% in the latest daily evidence. Review the cited source.";
    expect(assertInformationOnly(text)).toBe(text);
  });

  it.each(["Buy BBRI", "Target price 6,000", "Guaranteed return", "Use a stop-loss"])(
    "blocks financial-advice language: %s",
    (text) => expect(() => assertInformationOnly(text)).toThrow(/unsafe investment-language/i),
  );
});
