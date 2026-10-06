import { describe, expect, it } from "vitest";
import { countConfigChanges, matchesConfigSearch } from "./config-changes";

describe("configuration change counts", () => {
  it("counts an identity removal once and preserves keyed siblings across reordering", () => {
    const previous = [
      { id: "first", enabled: true, name: "First" },
      { id: "second", enabled: false, name: "Second" },
    ];
    expect(countConfigChanges(previous, [previous[1], previous[0]])).toBe(0);
    expect(countConfigChanges(previous, [previous[1]])).toBe(1);
    expect(countConfigChanges(previous, [previous[1], { ...previous[0], enabled: false }])).toBe(1);
  });
  it("counts removing one account override without changing the source default", () => {
    const setting = {
      endpoint_id: "x:MixedCase",
      capability_id: "company_news",
      enabled: false,
      settings: {},
    };
    expect(
      countConfigChanges(
        { endpoint_overrides: [setting], untouched: { version: 1 } },
        { endpoint_overrides: [], untouched: { version: 1 } },
      ),
    ).toBe(1);
  });
  it("matches every search word regardless of case or extra spaces", () => {
    expect(matchesConfigSearch("Example Analyst x example_handle", " X   analyst ")).toBe(true);
    expect(matchesConfigSearch("Example Analyst x example_handle", "x missing")).toBe(false);
  });
});
