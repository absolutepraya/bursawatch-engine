import { describe, expect, it } from "vitest";
import { briefPreviewText } from "./brief-copy";

describe("brief preview preferences", () => {
  it("changes the summary for every tone, in both supported languages", () => {
    for (const language of ["id", "en"] as const) {
      const variants = ["concise", "beginner", "analyst"].map(tone => briefPreviewText({ language, tone: tone as "concise" | "beginner" | "analyst" }));
      expect(new Set(variants).size).toBe(3);
      expect(variants.every(text => text.length > 60)).toBe(true);
    }
  });
  it("keeps the language selection independent of tone", () => {
    expect(briefPreviewText({ language: "id", tone: "concise" })).toContain("harga");
    expect(briefPreviewText({ language: "en", tone: "concise" })).toContain("price");
  });
});
