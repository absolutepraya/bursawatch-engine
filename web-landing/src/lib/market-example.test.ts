import { describe, expect, it } from "vitest";
import { changeFromOpen, formatMove, formatPrice, marketExamples } from "./market-example";

describe("sample stock prices", () => {
  it("measures changes from the open, including dips and unchanged prices", () => {
    expect(changeFromOpen(4080, 4100)).toBeCloseTo(-0.4878, 4);
    expect(changeFromOpen(4100, 4100)).toBe(0);
    expect(changeFromOpen(4240, 4100)).toBeCloseTo(3.4146, 4);
  });

  it("shows signed changes and the price currency without implying extra precision", () => {
    expect(formatMove(changeFromOpen(4240, 4100))).toBe("+3.4%");
    expect(formatMove(changeFromOpen(4080, 4100))).toBe("-0.5%");
    expect(formatMove(0)).toBe("+0.0%");
    expect(formatPrice(4240)).toBe("Rp4,240");
  });

  it("provides both matching and quiet scenarios at the default 3% threshold", () => {
    const decisions = marketExamples.map(({ symbol, prices }) => ({
      symbol,
      matches: changeFromOpen(prices.at(-1)!, prices[0]) >= 3,
    }));
    expect(decisions).toEqual([
      { symbol: "BBRI", matches: true },
      { symbol: "TLKM", matches: false },
      { symbol: "BMRI", matches: true },
    ]);
  });
});
