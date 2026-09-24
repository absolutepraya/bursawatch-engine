import { describe, expect, it } from "vitest";
import {
  configValue,
  configFieldErrors,
  isScheduleApplied,
  newProfile,
  nextDestination,
  setConfigValue,
  supportsWatcherConfig,
  validateScheduleMinutes,
  validateWatcherConfig,
  type ProfileKind,
} from "./watcher-fields";

// Synthetic identifiers only; these fixtures are unrelated to runtime settings.
const destination = "100000000000000001";
const heartbeat = "100000000000000002";
const sourceEmoji = "<:example:100000000000000003>";
const stockbitWatcherId = "bursawatch-stockbit-snips";
const validStockbitConfig = () => ({
  version: 1,
  feeds: [
    { id: "stockbit_commentary", enabled: true },
    { id: "unboxing", enabled: true },
    { id: "unboxing_ipo", enabled: true },
    { id: "ai_reports_stockbit", enabled: true },
  ],
  destinations: {
    id_stocks_news_channel_id: "123456789012345678",
    macro_news_channel_id: "234567890123456789",
  },
  additional_prompt_instruction: "",
});
const watcherFor = {
  x: "bursawatch-x-account-watch",
  instagram: "bursawatch-ig-account-watch",
  whatsapp: "bursawatch-wa-channel-watch",
};
function profile(kind: ProfileKind) {
  const value = newProfile(kind);
  Object.assign(value, {
    id: "example_source",
    enabled: true,
    display_name: "Example source",
    emoji: sourceEmoji,
    discord_channels: [
      { key: "id_stocks_news", channel_id: destination, description: "Company news" },
    ],
  });
  if (kind === "whatsapp")
    Object.assign(value, {
      channel_jid: "example@newsletter",
      channel_url: "https://whatsapp.com/channel/example",
    });
  else
    Object.assign(value, {
      handle: "example",
      profile_url: `https://${kind === "x" ? "x.com" : "instagram.com"}/example`,
      ...(kind === "x" ? { twitter_emoji: sourceEmoji } : {}),
    });
  return value;
}

describe("watcher configuration drafts", () => {
  it("validates the exact Stockbit v1 configuration shape", () => {
    expect(supportsWatcherConfig(stockbitWatcherId, 1)).toBe(true);
    expect(supportsWatcherConfig(stockbitWatcherId, 2)).toBe(false);
    expect(validateWatcherConfig(stockbitWatcherId, validStockbitConfig())).toEqual({});
    expect(
      validateWatcherConfig(stockbitWatcherId, { ...validStockbitConfig(), extra: true }),
    ).toHaveProperty("extra");
    expect(
      validateWatcherConfig(stockbitWatcherId, { ...validStockbitConfig(), version: 2 }),
    ).toHaveProperty("version");
  });

  it("requires four unique fixed Stockbit lanes with boolean switches", () => {
    const config = validStockbitConfig();
    expect(
      validateWatcherConfig(stockbitWatcherId, { ...config, feeds: config.feeds.slice(1) }),
    ).toHaveProperty("feeds");
    expect(
      validateWatcherConfig(stockbitWatcherId, {
        ...config,
        feeds: [config.feeds[0], config.feeds[0], ...config.feeds.slice(2)],
      }),
    ).toHaveProperty("feeds.1.id");
    expect(
      validateWatcherConfig(stockbitWatcherId, {
        ...config,
        feeds: [{ ...config.feeds[0], enabled: "true" }, ...config.feeds.slice(1)],
      }),
    ).toHaveProperty("feeds.0.enabled");
    expect(
      validateWatcherConfig(stockbitWatcherId, {
        ...config,
        feeds: [{ ...config.feeds[0], extra: true }, ...config.feeds.slice(1)],
      }),
    ).toHaveProperty("feeds.0.extra");
  });

  it("requires two distinct Stockbit Discord routes and 800 normalized code points", () => {
    const config = validStockbitConfig();
    expect(
      validateWatcherConfig(stockbitWatcherId, {
        ...config,
        destinations: { ...config.destinations, macro_news_channel_id: "bad" },
      }),
    ).toHaveProperty("destinations.macro_news_channel_id");
    for (const channelId of ["١٢٣٤٥٦٧٨٩٠١٢٣٤٥٦٧٨", "１２３４５６７８９０１２３４５６７８"])
      expect(
        validateWatcherConfig(stockbitWatcherId, {
          ...config,
          destinations: { ...config.destinations, macro_news_channel_id: channelId },
        }),
      ).toHaveProperty("destinations.macro_news_channel_id");
    expect(
      validateWatcherConfig(stockbitWatcherId, {
        ...config,
        destinations: {
          ...config.destinations,
          macro_news_channel_id: config.destinations.id_stocks_news_channel_id,
        },
      }),
    ).toHaveProperty("destinations.macro_news_channel_id");
    expect(
      validateWatcherConfig(stockbitWatcherId, {
        ...config,
        destinations: { ...config.destinations, extra: "123456789012345678" },
      }),
    ).toHaveProperty("destinations.extra");
    for (const text of ["x".repeat(800), "🧪".repeat(800)])
      expect(
        validateWatcherConfig(stockbitWatcherId, {
          ...config,
          additional_prompt_instruction: text,
        }),
      ).toEqual({});
    expect(
      validateWatcherConfig(stockbitWatcherId, {
        ...config,
        additional_prompt_instruction: "🧪".repeat(801),
      }),
    ).toHaveProperty("additional_prompt_instruction");
  });
  it("maps indexed API paths without exposing upstream error prose or unsafe keys", () => {
    expect(
      configFieldErrors([
        "body.config.profiles.0.handle",
        "profiles[1].emoji",
        "body.interval_seconds",
        "config.__proto__.polluted",
        "raw rejected payload",
      ]),
    ).toEqual({
      "profiles.0.handle": expect.any(String),
      "profiles.1.emoji": expect.any(String),
      interval_seconds: expect.any(String),
    });
  });

  it("adds only available WhatsApp route keys", () => {
    const routes = [nextDestination("whatsapp", [])];
    expect(routes[0]?.key).toBe("id_stocks_news");
    routes.push(nextDestination("whatsapp", routes));
    expect(routes[1]?.key).toBe("macro_news");
    routes.push(nextDestination("whatsapp", routes));
    expect(routes[2]?.key).toBe("id_stocks_swing");
    expect(nextDestination("whatsapp", routes)).toBeNull();
  });

  it("preserves case-sensitive WhatsApp identities and optional X quoted display", () => {
    const channel = profile("whatsapp");
    expect(
      validateWatcherConfig(watcherFor.whatsapp, {
        version: 2,
        profiles: [channel, { ...channel, id: "another", channel_jid: "EXAMPLE@newsletter" }],
      }),
    ).toEqual({});
    const account = profile("x");
    delete account.show_quoted_post;
    expect(validateWatcherConfig(watcherFor.x, { version: 1, profiles: [account] })).toEqual({});
    account.show_quoted_post = "false";
    expect(validateWatcherConfig(watcherFor.x, { version: 1, profiles: [account] })).toHaveProperty(
      "profiles.0.show_quoted_post",
    );
  });

  it("counts normalized Unicode characters and rejects explicit profile URL ports", () => {
    const account = profile("x");
    account.additional_prompt_instruction = "🧪".repeat(800);
    expect(validateWatcherConfig(watcherFor.x, { version: 1, profiles: [account] })).toEqual({});
    account.additional_prompt_instruction = "🧪".repeat(801);
    expect(validateWatcherConfig(watcherFor.x, { version: 1, profiles: [account] })).toHaveProperty(
      "profiles.0.additional_prompt_instruction",
    );
    account.profile_url = "https://x.com:443/example";
    expect(validateWatcherConfig(watcherFor.x, { version: 1, profiles: [account] })).toHaveProperty(
      "profiles.0.profile_url",
    );
  });

  it("patches one field without mutating the source or dropping unknown nested values", () => {
    const original = {
      version: 1,
      future: { setting: true },
      profiles: [{ ...profile("x"), future_profile: { nested: [1, 2] } }, profile("x")],
    };
    const changed = setConfigValue(
      original,
      ["profiles", 0, "thread_handling", "settle_minutes"],
      8,
    );
    expect(configValue(changed, ["profiles", 0, "thread_handling", "settle_minutes"])).toBe(8);
    expect(configValue(original, ["profiles", 0, "thread_handling", "settle_minutes"])).toBe(5);
    expect(changed.future).toEqual({ setting: true });
    expect(configValue(changed, ["profiles", 0, "future_profile"])).toEqual({ nested: [1, 2] });
    expect(configValue(changed, ["profiles", 1])).toEqual(original.profiles[1]);
  });

  it("rejects unsafe property paths", () => {
    expect(() => setConfigValue({}, ["__proto__", "polluted"], true)).toThrow();
    expect(() => setConfigValue({}, ["profiles", "constructor"], true)).toThrow();
  });

  it.each(["x", "instagram", "whatsapp"] as const)("accepts valid %s profile edits", (kind) => {
    expect(
      validateWatcherConfig(watcherFor[kind], {
        version: kind === "whatsapp" ? 2 : 1,
        profiles: [profile(kind)],
      }),
    ).toEqual({});
  });

  it("keeps Discord IDs as strings and rejects rounded numeric identifiers", () => {
    const config = { version: 1, profiles: [profile("x")] };
    const changed = setConfigValue(
      config,
      ["profiles", 0, "discord_channels", 0, "channel_id"],
      Number(destination),
    );
    expect(validateWatcherConfig(watcherFor.x, changed)).toHaveProperty(
      "profiles.0.discord_channels.0.channel_id",
    );
  });

  it("validates required X routing destinations and their uniqueness", () => {
    const item = profile("x");
    item.enable_llm_routing = true;
    expect(validateWatcherConfig(watcherFor.x, { version: 1, profiles: [item] })).toHaveProperty(
      "profiles.0.discord_channels",
    );
    item.discord_channels = [
      { key: "id_stocks_news", channel_id: destination, description: "News" },
      { key: "macro_news", channel_id: heartbeat, description: "Macro" },
    ];
    expect(validateWatcherConfig(watcherFor.x, { version: 1, profiles: [item] })).toEqual({});
    item.enable_llm_routing = false;
    expect(validateWatcherConfig(watcherFor.x, { version: 1, profiles: [item] })).toHaveProperty(
      "profiles.0.discord_channels",
    );
  });

  it("requires Instagram's two named routes for automatic routing", () => {
    const item = profile("instagram");
    Object.assign(item, {
      enable_llm_routing: true,
      discord_channels: [
        { key: "id_stocks_news", channel_id: destination, description: "News" },
        { key: "other", channel_id: heartbeat, description: "Other" },
      ],
    });
    expect(
      validateWatcherConfig(watcherFor.instagram, { version: 1, profiles: [item] }),
    ).toHaveProperty("profiles.0.discord_channels");
    const changed = setConfigValue(
      { version: 1, profiles: [item] },
      ["profiles", 0, "discord_channels", 1, "key"],
      "macro_news",
    );
    expect(validateWatcherConfig(watcherFor.instagram, changed)).toEqual({});
  });

  it("rejects mismatched handles, duplicate accounts, and unsupported URL additions", () => {
    const item = profile("x");
    expect(
      validateWatcherConfig(watcherFor.x, {
        version: 1,
        profiles: [item, { ...item, id: "different", handle: "EXAMPLE" }],
      }),
    ).toHaveProperty("profiles.1.handle");
    item.profile_url = "https://x.com/someone_else";
    expect(validateWatcherConfig(watcherFor.x, { version: 1, profiles: [item] })).toHaveProperty(
      "profiles.0.profile_url",
    );
    item.profile_url = "https://x.com/example?tracking=1";
    expect(validateWatcherConfig(watcherFor.x, { version: 1, profiles: [item] })).toHaveProperty(
      "profiles.0.profile_url",
    );
  });

  it("checks Instagram confidence and supported nonempty image languages", () => {
    const item = profile("instagram");
    Object.assign(item, { ocr_min_confidence: 1.01, ocr_languages: [], max_reel_frames: 9 });
    const errors = validateWatcherConfig(watcherFor.instagram, { version: 1, profiles: [item] });
    expect(errors).toHaveProperty("profiles.0.ocr_min_confidence");
    expect(errors).toHaveProperty("profiles.0.ocr_languages");
    expect(errors).toHaveProperty("profiles.0.max_reel_frames");
  });

  it("accepts empty WhatsApp sources and null optional status emojis", () => {
    expect(validateWatcherConfig(watcherFor.whatsapp, { version: 2, profiles: [] })).toEqual({});
    expect(
      validateWatcherConfig(watcherFor.whatsapp, { version: 2, profiles: [profile("whatsapp")] }),
    ).toEqual({});
    expect(validateWatcherConfig(watcherFor.x, { version: 1, profiles: [] })).toHaveProperty(
      "profiles",
    );
  });

  it("enforces WhatsApp channel identities, known routes, and per-poll limits", () => {
    const item = profile("whatsapp");
    Object.assign(item, {
      channel_jid: "not-a-channel",
      max_items_per_poll: 51,
      status_emojis: { up: "bad", down: null, hold: null },
    });
    const errors = validateWatcherConfig(watcherFor.whatsapp, { version: 2, profiles: [item] });
    expect(errors).toHaveProperty("profiles.0.channel_jid");
    expect(errors).toHaveProperty("profiles.0.max_items_per_poll");
    expect(errors).toHaveProperty("profiles.0.status_emojis.up");
  });

  it.each(["bursawatch-tg-phintraco-swing", "bursawatch-tg-kelas-investasi-gtw"])(
    "accepts valid %s source and destinations",
    (watcherId) => {
      const config = {
        version: 1,
        source: { telegram_channel_id: 123, telegram_username: "example_source" },
        destinations: {
          alert_discord_channel_id: destination,
          heartbeat_discord_channel_id: heartbeat,
        },
        ...(watcherId.endsWith("gtw") ? { additional_prompt_instruction: "" } : {}),
      };
      expect(validateWatcherConfig(watcherId, config)).toEqual({});
      expect(
        validateWatcherConfig(
          watcherId,
          setConfigValue(config, ["destinations", "heartbeat_discord_channel_id"], destination),
        ),
      ).toHaveProperty("destinations.heartbeat_discord_channel_id");
    },
  );

  it("validates the two news providers, four destinations and instruction length", () => {
    const config = {
      version: 1,
      providers: {
        phintraco: { telegram_username: "example_one" },
        tuntun: { telegram_username: "example_two" },
      },
      destinations: {
        id_stocks_news_discord_channel_id: destination,
        macro_news_discord_channel_id: heartbeat,
        industry_news_discord_channel_id: "100000000000000004",
        heartbeat_discord_channel_id: "100000000000000005",
      },
      additional_prompt_instruction: "",
    };
    expect(validateWatcherConfig("bursawatch-tg-market-news", config)).toEqual({});
    expect(
      validateWatcherConfig("bursawatch-tg-market-news", {
        ...config,
        additional_prompt_instruction: "x".repeat(801),
      }),
    ).toHaveProperty("additional_prompt_instruction");
  });

  it("validates the board's heartbeat without adding unsupported delivery fields", () => {
    expect(
      validateWatcherConfig("bursawatch-dc-swing-board", {
        version: 1,
        destinations: { heartbeat_discord_channel_id: heartbeat },
      }),
    ).toEqual({});
    expect(validateWatcherConfig("bursawatch-dc-swing-board", { version: 2 })).toHaveProperty(
      "version",
    );
  });
});

describe("WhatsApp v2 mode boundaries", () => {
  const observing = () => ({
    ...profile("whatsapp"),
    id: "observed_channel",
    channel_jid: "observed@newsletter",
    mode: "observe",
    emoji: null,
    discord_channels: [],
    forward_media: false,
    enable_llm_title: false,
    enable_llm_summary: false,
    enable_llm_routing: false,
    enable_llm_relevance_filter: false,
  });
  it("accepts mixed modes and preserves the other profile on edits", () => {
    const config = { version: 2, profiles: [profile("whatsapp"), observing()] };
    expect(validateWatcherConfig(watcherFor.whatsapp, config)).toEqual({});
    const updated = setConfigValue(config, ["profiles", 1, "display_name"], "Observed channel");
    expect(configValue(updated, ["profiles", 0])).toEqual(config.profiles[0]);
    expect(configValue(updated, ["profiles", 1, "mode"])).toBe("observe");
    expect(updated.version).toBe(2);
    expect(validateWatcherConfig(watcherFor.whatsapp, updated)).toEqual({});
  });
  it.each([
    "forward_media",
    "enable_llm_title",
    "enable_llm_summary",
    "enable_llm_routing",
    "enable_llm_relevance_filter",
  ])("rejects observe mode with %s enabled", (key) => {
    const errors = validateWatcherConfig(watcherFor.whatsapp, {
      version: 2,
      profiles: [{ ...observing(), [key]: true }],
    });
    expect(errors).toHaveProperty(`profiles.0.${key}`);
  });
  it("rejects observe presentation/routing and incomplete forward mode", () => {
    const item = profile("whatsapp");
    const errors = validateWatcherConfig(watcherFor.whatsapp, {
      version: 2,
      profiles: [{ ...item, mode: "observe" }],
    });
    expect(errors).toHaveProperty("profiles.0.emoji");
    expect(errors).toHaveProperty("profiles.0.discord_channels");
    const forward = validateWatcherConfig(watcherFor.whatsapp, {
      version: 2,
      profiles: [{ ...observing(), mode: "forward" }],
    });
    expect(forward).toHaveProperty("profiles.0.emoji");
    expect(forward).toHaveProperty("profiles.0.discord_channels");
  });
  it("changes only mode until the operator explicitly edits other fields", () => {
    const config = { version: 2, profiles: [profile("whatsapp")] };
    const changed = setConfigValue(config, ["profiles", 0, "mode"], "observe");
    expect(configValue(changed, ["profiles", 0])).toEqual({
      ...config.profiles[0],
      mode: "observe",
    });
    expect(validateWatcherConfig(watcherFor.whatsapp, changed)).not.toEqual({});
    expect(newProfile("whatsapp")).toMatchObject({ mode: "forward", enabled: false });
  });
  it("supports only each watcher's reviewed version", () => {
    expect(supportsWatcherConfig(watcherFor.whatsapp, 2)).toBe(true);
    for (const version of [1, 3, "2", null]) {
      expect(supportsWatcherConfig(watcherFor.whatsapp, version)).toBe(false);
      expect(validateWatcherConfig(watcherFor.whatsapp, { version, profiles: [] })).toHaveProperty(
        "version",
      );
    }
    for (const id of [
      watcherFor.x,
      watcherFor.instagram,
      "bursawatch-tg-kelas-investasi-gtw",
      "bursawatch-tg-market-news",
      "bursawatch-tg-phintraco-swing",
      "bursawatch-dc-swing-board",
    ]) {
      expect(supportsWatcherConfig(id, 1)).toBe(true);
      expect(supportsWatcherConfig(id, 2)).toBe(false);
    }
    expect(supportsWatcherConfig("unknown", 1)).toBe(false);
  });
});

describe("schedule confirmation", () => {
  it("uses schedule metadata for Stockbit bounds", () => {
    expect(validateScheduleMinutes("5", 300, 3600)).toBeNull();
    expect(validateScheduleMinutes("60", 300, 3600)).toBeNull();
    expect(validateScheduleMinutes("4", 300, 3600)).not.toBeNull();
    expect(validateScheduleMinutes("61", 300, 3600)).not.toBeNull();
  });

  it("requires effective status and both matching revisions", () => {
    const pending = {
      schedule: { revision: 4 },
      reconciliation: { status: "pending", effective: false, applied_revision: 3 },
    };
    expect(isScheduleApplied(pending)).toBe(false);
    expect(
      isScheduleApplied({
        ...pending,
        reconciliation: { status: "applied", effective: true, applied_revision: 3 },
      }),
    ).toBe(false);
    const applied = {
      ...pending,
      reconciliation: { status: "applied", effective: true, applied_revision: 4 },
    };
    expect(isScheduleApplied(applied, 4)).toBe(true);
    expect(isScheduleApplied(applied, 3)).toBe(false);
    expect(
      isScheduleApplied({
        ...applied,
        reconciliation: { ...applied.reconciliation, effective: false },
      }),
    ).toBe(false);
    expect(isScheduleApplied({ ...applied, schedule: null })).toBe(false);
  });

  it("enforces each job's bounds and whole-minute cadence", () => {
    expect(validateScheduleMinutes("5", 300, 3600)).toBeNull();
    expect(validateScheduleMinutes("60", 300, 3600)).toBeNull();
    for (const value of ["", "4", "61", "5.5", "NaN", "Infinity"])
      expect(validateScheduleMinutes(value, 300, 3600)).not.toBeNull();
    expect(validateScheduleMinutes("1441", null, null)).not.toBeNull();
  });
});
