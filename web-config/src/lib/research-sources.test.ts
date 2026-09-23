import { describe, expect, it } from "vitest";
import {
  blankSource,
  changeResearch,
  decodeResearch,
  emptyResearch,
  normalizeSourceUrl,
  sourceInputSchema,
} from "./research-sources";

const input = { ...blankSource, name: "Market research", url: "@market_notes" };

describe("public research sources", () => {
  it("restores legacy X defaults without overwriting existing choices", () => {
    const legacy = { ...input };
    delete legacy.includeOriginals;
    delete legacy.includeReplies;
    delete legacy.groupThreads;
    expect(sourceInputSchema.parse(legacy)).toMatchObject({
      includeOriginals: true,
      includeReplies: false,
      groupThreads: true,
    });
    const saved = changeResearch(emptyResearch, {
      type: "save",
      input: { ...input, includeReplies: true, groupThreads: false },
    });
    expect(decodeResearch(JSON.stringify(saved))?.sources[0].input).toMatchObject({
      includeReplies: true,
      groupThreads: false,
    });
  });
  it("requires an X post type but does not apply that rule to other platforms", () => {
    const none = {
      ...input,
      includeOriginals: false,
      includeReplies: false,
      includeQuotes: false,
      includeReposts: false,
    };
    expect(sourceInputSchema.safeParse(none).success).toBe(false);
    expect(sourceInputSchema.safeParse({ ...none, includeReplies: true }).success).toBe(true);
    expect(
      sourceInputSchema.safeParse({
        ...none,
        platform: "telegram",
        url: "https://t.me/marketnotes",
      }).success,
    ).toBe(true);
  });
  it("normalizes profile identities without treating posts as profiles", () => {
    expect(normalizeSourceUrl("x", "https://twitter.com/Market_Notes/?s=20")).toBe(
      "https://x.com/market_notes",
    );
    expect(normalizeSourceUrl("telegram", "https://t.me/MarketNotes/")).toBe(
      "https://t.me/marketnotes",
    );
    expect(normalizeSourceUrl("whatsapp", "https://whatsapp.com/channel/0123456789ABC")).toBe(
      "https://www.whatsapp.com/channel/0123456789ABC",
    );
    expect(() => normalizeSourceUrl("x", "https://x.com/market_notes/status/123")).toThrow();
    expect(() => normalizeSourceUrl("telegram", "https://t.me/marketnotes/123")).toThrow();
  });
  it("rejects unsafe and unrelated links", () => {
    for (const url of [
      "javascript:alert(1)",
      "https://x.com.evil.test/user",
      "https://user:secret@x.com/user",
      "https://x.com:444/user",
      "https://x.com/home",
      "http://x.com/user",
    ])
      expect(() => normalizeSourceUrl("x", url)).toThrow();
    expect(() => normalizeSourceUrl("whatsapp", "https://chat.whatsapp.com/invite")).toThrow();
    expect(() => normalizeSourceUrl("telegram", "https://t.me/+privateinvite")).toThrow();
  });
  it("normalizes Instagram handles and rejects publications, reserved paths and unsafe links", () => {
    expect(normalizeSourceUrl("instagram", "@avenirresearch.id")).toBe(
      "https://www.instagram.com/avenirresearch.id",
    );
    expect(normalizeSourceUrl("instagram", "https://instagram.com/SectorsApp/?igsh=abc")).toBe(
      "https://www.instagram.com/sectorsapp",
    );
    for (const url of [
      "https://instagram.com/p/ABC",
      "https://instagram.com/reel/ABC",
      "https://instagram.com/stories/example/123",
      "https://instagram.com/accounts",
      "https://instagram.com/direct",
      "https://instagram.com/reels",
      "https://instagram.com/username.",
      "https://instagram.com/user..name",
      "https://instagram.com.evil.test/example",
      "https://user:secret@instagram.com/example",
      "http://instagram.com/example",
    ])
      expect(() => normalizeSourceUrl("instagram", url)).toThrow();
  });
  it("keeps older preferences readable and persists independent Instagram publication options", () => {
    const legacy = { ...input };
    delete legacy.includePosts;
    delete legacy.includeReels;
    const parsed = sourceInputSchema.parse(legacy);
    expect(parsed.includePosts).toBe(true);
    expect(parsed.includeReels).toBe(true);
    const instagram = {
      ...input,
      platform: "instagram" as const,
      url: "@sectorsapp",
      includePosts: false,
      includeReels: true,
    };
    const state = changeResearch(emptyResearch, { type: "save", input: instagram });
    expect(decodeResearch(JSON.stringify(state))?.sources[0].input.includePosts).toBe(false);
    expect(sourceInputSchema.safeParse({ ...instagram, includeReels: false }).success).toBe(false);
    expect(() =>
      changeResearch(state, {
        type: "save",
        input: { ...instagram, url: "https://instagram.com/SectorsApp/" },
      }),
    ).toThrow("already follow");
  });
  it("requires a topic and limits custom instructions", () => {
    expect(sourceInputSchema.safeParse({ ...input, topics: [] }).success).toBe(false);
    expect(sourceInputSchema.safeParse({ ...input, instructions: "a".repeat(601) }).success).toBe(
      false,
    );
    expect(sourceInputSchema.safeParse({ ...input, topics: ["unknown"] }).success).toBe(false);
  });
  it("saves independent profiles and survives serialization", () => {
    let state = changeResearch(emptyResearch, { type: "save", input });
    state = changeResearch(state, {
      type: "save",
      input: {
        ...input,
        name: "Economy desk",
        platform: "telegram",
        url: "https://t.me/economydesk",
      },
    });
    const target = state.sources[1];
    state = changeResearch(state, {
      type: "save",
      id: target.id,
      revision: target.revision,
      input: { ...target.input, format: "original", topics: ["macro_news"] },
    });
    expect(state.sources[0].input.format).toBe("summary");
    expect(state.sources[1].input.format).toBe("original");
    expect(decodeResearch(JSON.stringify(state))).toEqual(state);
    expect(emptyResearch.sources).toHaveLength(0);
  });
  it("prevents duplicate identities across Twitter and X URLs", () => {
    const state = changeResearch(emptyResearch, { type: "save", input });
    expect(() =>
      changeResearch(state, {
        type: "save",
        input: { ...input, url: "https://twitter.com/MARKET_NOTES" },
      }),
    ).toThrow("already follow");
  });
  it("rejects stale edits rather than replacing another tab's changes", () => {
    const initial = changeResearch(emptyResearch, { type: "save", input });
    const source = initial.sources[0];
    const changed = changeResearch(initial, {
      type: "toggle",
      id: source.id,
      revision: source.revision,
    });
    expect(() =>
      changeResearch(changed, { type: "save", id: source.id, revision: source.revision, input }),
    ).toThrow("another tab");
    expect(changed.sources[0].enabled).toBe(false);
  });
  it("supports pause, resume and removal without rewriting other sources", () => {
    let state = changeResearch(emptyResearch, { type: "save", input });
    const id = state.sources[0].id;
    state = changeResearch(state, { type: "toggle", id, revision: 1 });
    expect(state.sources[0].enabled).toBe(false);
    state = changeResearch(state, { type: "toggle", id, revision: 2 });
    expect(state.sources[0].enabled).toBe(true);
    state = changeResearch(state, { type: "remove", id, revision: 3 });
    expect(state.sources).toEqual([]);
  });
  it("keeps unreadable storage distinct from an empty workspace", () => {
    expect(decodeResearch(null)).toEqual(emptyResearch);
    expect(decodeResearch("{")).toBeNull();
    expect(decodeResearch('{"version":5,"sources":[]}')).toBeNull();
  });
});
