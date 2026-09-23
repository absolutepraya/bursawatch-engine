import { describe, it, expect } from "vitest";
import {
  botSchema,
  changePreferences,
  decodePreferences,
  defaultBot,
  defaultDelivery,
  defaultInterests,
  deliverySchema,
  emptyPreferences,
  exampleMessage,
  isQuietTime,
  restoreBotDraft,
  restoreDeliveryDraft,
} from "./delivery-preferences";
const input = { ...defaultDelivery, destination: "Market desk" };
describe("delivery preferences", () => {
  it("migrates shared research interests without claiming onboarding is complete", () => {
    const legacyBot = Object.fromEntries(
      Object.entries(defaultBot).filter(
        ([key]) => !["interests", "onboardingComplete"].includes(key),
      ),
    );
    const state = decodePreferences(
      JSON.stringify({ ...emptyPreferences, bot: { ...legacyBot, name: "My research" } }),
    );
    expect(state?.bot).toMatchObject({
      name: "My research",
      interests: defaultInterests,
      onboardingComplete: false,
    });
    const saved = changePreferences(emptyPreferences, 0, {
      type: "bot",
      input: { ...defaultBot, interests: ["id_stocks_news"], onboardingComplete: true },
    });
    expect(decodePreferences(JSON.stringify(saved))?.bot).toMatchObject({
      interests: ["id_stocks_news"],
      onboardingComplete: true,
    });
  });
  it("requires a unique supported research interest", () => {
    for (const interests of [[], ["unknown"], ["macro_news", "macro_news"]]) {
      expect(botSchema.safeParse({ ...defaultBot, interests }).success).toBe(false);
    }
  });
  it("restores incomplete typed drafts without prematurely validating the form", () => {
    const bot = restoreBotDraft(
      JSON.stringify({
        revision: 2,
        input: { name: "", interests: [], instructions: "  Working note  " },
      }),
      2,
      defaultBot,
    );
    expect(bot).toEqual({
      ...defaultBot,
      name: "",
      interests: [],
      instructions: "  Working note  ",
    });
    expect(botSchema.safeParse(bot).success).toBe(false);
    const delivery = restoreDeliveryDraft(
      JSON.stringify({ revision: 2, input: { destination: "", digestTime: "", topics: [] } }),
      2,
      input,
    );
    expect(delivery).toEqual({ ...input, destination: "", digestTime: "", topics: [] });
    expect(deliverySchema.safeParse(delivery).success).toBe(false);
  });
  it("rejects corrupt draft field types, malformed JSON and stale revisions", () => {
    for (const raw of [
      "{",
      JSON.stringify({ revision: 0, input: { name: null } }),
      JSON.stringify({ revision: 0, input: { instructions: { length: 20 } } }),
      JSON.stringify({ revision: 0, input: { interests: "macro_news" } }),
      JSON.stringify({ revision: 1, input: { name: "Stale draft" } }),
    ]) {
      expect(restoreBotDraft(raw, 0, defaultBot)).toEqual(defaultBot);
    }
    for (const draft of [
      { topics: null },
      { topics: "brief" },
      { destination: {} },
      { enabled: "yes" },
      { cadence: "hourly" },
    ]) {
      expect(restoreDeliveryDraft(JSON.stringify({ revision: 0, input: draft }), 0, input)).toEqual(
        input,
      );
    }
  });
  it("merges only known partial draft fields and keeps saved arrays independent", () => {
    const bot = restoreBotDraft(
      JSON.stringify({ revision: 0, input: { name: "New draft", unexpected: "ignored" } }),
      0,
      defaultBot,
    );
    expect(bot).toEqual({ ...defaultBot, name: "New draft" });
    bot.interests.pop();
    expect(defaultBot.interests).toHaveLength(4);
  });
  it("keeps every channel independent through edits and serialization", () => {
    let state = changePreferences(emptyPreferences, 0, {
      type: "delivery",
      channel: "discord",
      input,
    });
    state = changePreferences(state, 1, {
      type: "delivery",
      channel: "email",
      input: { ...input, destination: "Research inbox", cadence: "digest" },
    });
    state = changePreferences(state, 2, {
      type: "bot",
      input: { ...defaultBot, name: "Market desk", language: "en" },
    });
    expect(state.delivery.discord?.cadence).toBe("as-ready");
    expect(state.delivery.email?.cadence).toBe("digest");
    expect(decodePreferences(JSON.stringify(state))).toEqual(state);
    expect(emptyPreferences.revision).toBe(0);
  });
  it("validates destination labels and update selections", () => {
    for (const destination of ["", "https://hooks.slack.com/services/secret", "line\nbreak"])
      expect(deliverySchema.safeParse({ ...input, destination }).success).toBe(false);
    expect(deliverySchema.safeParse({ ...input, topics: [] }).success).toBe(false);
    expect(deliverySchema.safeParse({ ...input, topics: ["brief", "brief"] }).success).toBe(false);
  });
  it("handles quiet hours across midnight with exclusive end", () => {
    expect(isQuietTime("23:00", "21:00", "07:00")).toBe(true);
    expect(isQuietTime("06:59", "21:00", "07:00")).toBe(true);
    expect(isQuietTime("07:00", "21:00", "07:00")).toBe(false);
    expect(
      deliverySchema.safeParse({ ...input, quietEnabled: true, quietEnd: "21:00" }).success,
    ).toBe(false);
    expect(
      deliverySchema.safeParse({
        ...input,
        quietEnabled: true,
        cadence: "digest",
        digestTime: "22:00",
      }).success,
    ).toBe(false);
    expect(
      deliverySchema.safeParse({
        ...input,
        quietEnabled: true,
        cadence: "digest",
        digestTime: "07:00",
      }).success,
    ).toBe(true);
  });
  it("rejects invalid times and unsupported zones", () => {
    expect(deliverySchema.safeParse({ ...input, digestTime: "25:01" }).success).toBe(false);
    expect(deliverySchema.safeParse({ ...input, timezone: "UTC+7" }).success).toBe(false);
  });
  it("prevents stale saves and removes only the selected channel", () => {
    const state = changePreferences(emptyPreferences, 0, {
      type: "delivery",
      channel: "telegram",
      input,
    });
    expect(() => changePreferences(state, 0, { type: "bot", input: defaultBot })).toThrow(
      "another tab",
    );
    expect(changePreferences(state, 1, { type: "remove", channel: "telegram" }).delivery).toEqual(
      {},
    );
  });
  it("preserves corruption as an error rather than resetting settings", () => {
    expect(decodePreferences("{")).toBeNull();
    expect(decodePreferences('{"version":4}')).toBeNull();
    expect(decodePreferences(null)).toEqual(emptyPreferences);
  });
  it("keeps source attribution mandatory and bounds customization", () => {
    expect(botSchema.safeParse({ ...defaultBot, includeSources: false }).success).toBe(false);
    expect(botSchema.safeParse({ ...defaultBot, instructions: "x".repeat(601) }).success).toBe(
      false,
    );
  });
  it("renders language, tone, length and time preferences without market claims", () => {
    const brief = exampleMessage({
      ...defaultBot,
      language: "en",
      length: "short",
      includeTime: false,
    });
    expect(brief).toContain("Market brief");
    expect(brief).not.toContain("16:30");
    const full = exampleMessage({
      ...defaultBot,
      language: "en",
      tone: "beginner",
      length: "detailed",
    });
    expect(full).toContain("There is a new update");
    expect(full).toContain("data limitations");
    expect(full).toContain("Source:");
  });
});
