import reviewedSources from "./fixtures/reviewed-sources.json";
import { describe, expect, it } from "vitest";
import { recommendedSources } from "./recommended-sources";
import {
  blankSource,
  normalizeSourceUrl,
  sourceInputSchema,
  type Platform,
} from "./research-sources";

// Public-only snapshot reviewed at absolutepraya/bursawatch f36823f.
// Tests are independent of private backend files and never imply live sync.
describe("reviewed public source catalog", () => {
  it("matches the reviewed X, Instagram and WhatsApp public identity snapshot", () => {
    const identities: string[] = [];
    for (const profile of reviewedSources) {
      identities.push(profile.id);
      const publicSource = recommendedSources.find((item) => item.id === profile.id);
      expect(publicSource, profile.id).toBeDefined();
      expect(publicSource?.platform).toBe(profile.platform);
      expect(publicSource?.url).toBe(normalizeSourceUrl(profile.platform as Platform, profile.url));
      expect(publicSource?.topics).toEqual(profile.topics);
    }
    expect(
      recommendedSources
        .filter((item) => item.label === "Team selection")
        .map((item) => item.id)
        .sort(),
    ).toEqual(identities.sort());
  });
  it("contains only allowlisted public presentation fields and valid follow inputs", () => {
    const keys = [
      "id",
      "name",
      "handle",
      "url",
      "image",
      "portrait",
      "platform",
      "background",
      "coverage",
      "reason",
      "evidence",
      "label",
      "topics",
    ].sort();
    for (const source of recommendedSources) {
      expect(Object.keys(source).sort()).toEqual(keys);
      expect(
        sourceInputSchema.safeParse({
          ...blankSource,
          name: source.name,
          platform: source.platform,
          url: source.url,
          topics: source.topics,
        }).success,
      ).toBe(true);
    }
    expect(new Set(recommendedSources.map((source) => source.url)).size).toBe(
      recommendedSources.length,
    );
  });
});
