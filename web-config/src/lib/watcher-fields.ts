/** Explicit operator configuration rules, reviewed against control-plane 25079b3
 * and main f426e24 (WhatsApp v2 observe/forward modes).
 * These checks help editors; the service remains the authority for acceptance.
 * No live configuration or destination values belong in this module.
 */
export type ConfigSnapshot = {
  api_version: 1;
  watcher_id: string;
  revision: number;
  config_version: number;
  config: Record<string, unknown>;
  config_sha256: string;
  updated_at: string;
};

export type ConfigPath = (string | number)[];
export type FieldErrors = Record<string, string>;
export type ProfileKind = "x" | "instagram" | "whatsapp";

/** Supported payload versions are watcher-specific, not interchangeable. */
export function supportsWatcherConfig(watcherId: string, version: unknown): boolean {
  return (
    Boolean(watcherNames[watcherId]) &&
    version === (watcherId === "bursawatch-wa-channel-watch" ? 2 : 1)
  );
}

/** Map safe API field paths to controls without echoing upstream error bodies. */
export function configFieldErrors(fields: unknown): FieldErrors {
  if (!Array.isArray(fields)) return {};
  const result: FieldErrors = {};
  for (const field of fields.slice(0, 20)) {
    if (typeof field !== "string") continue;
    const path = field.replace(/\[(\d+)\]/g, ".$1").replace(/^(?:body\.)?(?:config\.)?/, "");
    if (
      /^[a-z_][a-z0-9_]*(?:\.(?:[a-z_][a-z0-9_]*|\d+))*$/i.test(path) &&
      !path.split(".").some((part) => ["__proto__", "prototype", "constructor"].includes(part))
    )
      result[path] = "The service did not accept this value. Review it and try again.";
  }
  return result;
}

export function nextDestination(
  kind: ProfileKind,
  rows: unknown[],
): Record<string, unknown> | null {
  const keys = ["id_stocks_news", "macro_news", "id_stocks_swing"];
  const available = keys.find((key) => !rows.some((row) => configValue(row, ["key"]) === key));
  if (kind === "whatsapp" && !available) return null;
  return { key: kind === "whatsapp" ? available : "", channel_id: "", description: "" };
}

export const watcherNames: Record<string, string> = {
  "bursawatch-x-account-watch": "X accounts",
  "bursawatch-ig-account-watch": "Instagram accounts",
  "bursawatch-wa-channel-watch": "WhatsApp channels",
  "bursawatch-tg-kelas-investasi-gtw": "Kelas Investasi GTW",
  "bursawatch-tg-market-news": "Telegram market news",
  "bursawatch-tg-phintraco-swing": "Phintraco swing calls",
  "bursawatch-dc-swing-board": "Discord swing board",
  "bursawatch-stockbit-snips": "Stockbit Snips",
};

export function profileKind(watcherId: string): ProfileKind | null {
  if (watcherId === "bursawatch-x-account-watch") return "x";
  if (watcherId === "bursawatch-ig-account-watch") return "instagram";
  if (watcherId === "bursawatch-wa-channel-watch") return "whatsapp";
  return null;
}

export function configValue(config: unknown, path: ConfigPath): unknown {
  let value = config;
  for (const key of path) {
    if (!value || typeof value !== "object") return undefined;
    value = (value as Record<string | number, unknown>)[key];
  }
  return value;
}

/** Clone only the changed branch. Unknown fields and siblings are retained. */
export function setConfigValue(
  config: Record<string, unknown>,
  path: ConfigPath,
  value: unknown,
): Record<string, unknown> {
  if (
    !path.length ||
    path.some((key) => ["__proto__", "constructor", "prototype"].includes(String(key)))
  ) {
    throw new Error("Unsupported configuration field.");
  }
  function update(current: unknown, index: number): unknown {
    const key = path[index];
    const copy = Array.isArray(current)
      ? [...current]
      : { ...(current as Record<string, unknown> | undefined) };
    (copy as Record<string | number, unknown>)[key] =
      index === path.length - 1 ? value : update(configValue(current, [key]), index + 1);
    return copy;
  }
  return update(config, 0) as Record<string, unknown>;
}

export function newProfile(kind: ProfileKind): Record<string, unknown> {
  const base = {
    id: "",
    enabled: false,
    display_name: "",
    emoji: "",
    discord_channels: [{ key: "id_stocks_news", channel_id: "", description: "Stock news" }],
    forward_media: true,
    enable_llm_title: true,
    enable_llm_summary: true,
    enable_llm_routing: false,
    enable_llm_relevance_filter: true,
    additional_prompt_instruction: "",
    max_items_per_poll: 20,
  };
  if (kind === "whatsapp")
    return {
      ...base,
      mode: "forward",
      channel_jid: "",
      channel_url: "",
      status_emojis: { up: null, down: null, hold: null },
      relevance_scope: "stock_market",
    };
  if (kind === "instagram")
    return {
      ...base,
      source: "rsshub",
      profile_url: "",
      handle: "",
      platform_emoji: "Instagram",
      forward_post: true,
      forward_reel: true,
      ocr_languages: ["eng", "ind"],
      ocr_min_confidence: 0.5,
      max_reel_frames: 4,
    };
  return {
    ...base,
    source: "rsshub",
    profile_url: "",
    handle: "",
    twitter_emoji: "",
    forward_normal_post: true,
    forward_quote_post: true,
    show_quoted_post: false,
    forward_reply: false,
    forward_repost: false,
    media_policy: "all",
    relevance_scope: "stock_market",
    thread_handling: { mode: "self_chain", max_posts: 10, max_age_minutes: 120, settle_minutes: 5 },
  };
}

export function validateWatcherConfig(
  watcherId: string,
  config: Record<string, unknown>,
): FieldErrors {
  const errors: FieldErrors = {};
  const get = (path: ConfigPath) => configValue(config, path);
  const error = (path: ConfigPath, message: string) => {
    errors[path.join(".")] = message;
  };
  const text = (path: ConfigPath, pattern?: RegExp, message = "Enter a value.") => {
    const value = get(path);
    if (typeof value !== "string" || !value.trim() || (pattern && !pattern.test(value)))
      error(path, message);
  };
  const numeric = (path: ConfigPath, min: number, max: number, integer = true) => {
    const value = get(path);
    if (
      typeof value !== "number" ||
      !Number.isFinite(value) ||
      (integer && !Number.isInteger(value)) ||
      value < min ||
      value > max
    )
      error(path, `Enter ${integer ? "a whole number" : "a number"} from ${min} to ${max}.`);
  };
  const choice = (path: ConfigPath, values: string[], optional = false) => {
    if (optional && get(path) === undefined) return;
    if (!values.includes(String(get(path)))) error(path, "Choose a supported option.");
  };
  const bool = (path: ConfigPath) => {
    if (typeof get(path) !== "boolean") error(path, "Choose whether this option is enabled.");
  };
  const discord = (path: ConfigPath) =>
    text(path, /^\d{17,20}$/, "Enter a Discord channel ID with 17–20 digits.");
  const emoji = (path: ConfigPath, nullable = false) => {
    if (nullable && get(path) === null) return;
    text(path, /^<:[A-Za-z0-9_]+:\d{17,20}>$/, "Use a Discord custom emoji: <:name:ID>.");
  };
  const prompt = (path: ConfigPath, bounded: boolean) => {
    const value = get(path);
    if (typeof value !== "string") error(path, "Enter text, or leave this field empty.");
    else if (bounded && Array.from(value.trim().split(/\s+/u).join(" ")).length > 800)
      error(path, "Use 800 characters or fewer.");
  };
  const unique = (items: unknown[], paths: ConfigPath[], message: string) => {
    const seen = new Map<unknown, number>();
    items.forEach((value, index) => {
      if (seen.has(value)) {
        error(paths[index], message);
        error(paths[seen.get(value)!], message);
      } else seen.set(value, index);
    });
  };
  if (!watcherNames[watcherId]) {
    error([], "This watcher does not have an editor yet.");
    return errors;
  }
  if (!supportsWatcherConfig(watcherId, config.version))
    error(["version"], "This configuration version is not supported by this editor.");
  if (watcherId === "bursawatch-stockbit-snips") {
    const exactKeys = (value: unknown, path: ConfigPath, allowed: string[]) => {
      if (!value || typeof value !== "object" || Array.isArray(value)) {
        error(path, "This setting must be an object.");
        return false;
      }
      const keys = Object.keys(value);
      for (const key of keys)
        if (!allowed.includes(key)) error([...path, key], "Unsupported setting.");
      for (const key of allowed)
        if (!keys.includes(key)) error([...path, key], "This setting is required.");
      return true;
    };
    exactKeys(config, [], ["version", "feeds", "destinations", "additional_prompt_instruction"]);
    const feeds = config.feeds;
    const feedIds = ["stockbit_commentary", "unboxing", "unboxing_ipo", "ai_reports_stockbit"];
    if (!Array.isArray(feeds) || feeds.length !== feedIds.length)
      error(["feeds"], "Keep all four fixed Stockbit feeds.");
    if (Array.isArray(feeds)) {
      const seen = new Set<unknown>();
      feeds.forEach((feed, index) => {
        const path: ConfigPath = ["feeds", index];
        if (!exactKeys(feed, path, ["id", "enabled"])) return;
        const id = get([...path, "id"]);
        if (!feedIds.includes(String(id)) || seen.has(id))
          error([...path, "id"], "Choose each fixed feed once.");
        seen.add(id);
        bool([...path, "enabled"]);
      });
      if (feedIds.some((id) => !seen.has(id)))
        error(["feeds"], "Keep all four fixed Stockbit feeds.");
    }
    const destinations: ConfigPath = ["destinations"];
    const routeKeys = ["id_stocks_news_channel_id", "macro_news_channel_id"];
    if (exactKeys(config.destinations, destinations, routeKeys)) {
      routeKeys.forEach((key) => discord([...destinations, key]));
      if (get([...destinations, routeKeys[0]]) === get([...destinations, routeKeys[1]]))
        error([...destinations, routeKeys[1]], "Choose a different destination channel.");
    }
    prompt(["additional_prompt_instruction"], true);
    return errors;
  }
  const kind = profileKind(watcherId);
  if (kind) {
    const profiles = config.profiles;
    if (!Array.isArray(profiles) || (!profiles.length && kind !== "whatsapp")) {
      error(["profiles"], "Add at least one profile.");
      return errors;
    }
    const paths = profiles.map((_, index) => ["profiles", index] as ConfigPath);
    unique(
      paths.map((path) => get([...path, "id"])),
      paths.map((path) => [...path, "id"]),
      "Use a unique profile ID.",
    );
    const identity = kind === "whatsapp" ? "channel_jid" : "handle";
    unique(
      paths.map((path) => {
        const value = String(get([...path, identity]));
        return kind === "whatsapp" ? value : value.toLowerCase();
      }),
      paths.map((path) => [...path, identity]),
      "This source is already included.",
    );
    paths.forEach((path) => {
      const at = (key: string) => [...path, key];
      text(
        at("id"),
        kind === "whatsapp" ? /^[a-z0-9][a-z0-9_-]{1,63}$/ : /^[a-z0-9][a-z0-9_-]*$/,
        "Use lowercase letters, numbers, underscores or hyphens.",
      );
      text(at("display_name"));
      for (const key of [
        "enabled",
        "forward_media",
        "enable_llm_title",
        "enable_llm_summary",
        "enable_llm_routing",
        "enable_llm_relevance_filter",
      ])
        bool(at(key));
      numeric(at("max_items_per_poll"), 1, kind === "whatsapp" ? 50 : 100);
      prompt(at("additional_prompt_instruction"), kind === "x");
      if (kind !== "instagram")
        choice(
          at("relevance_scope"),
          ["stock_market", "financial_market", "indonesia_economy"],
          kind === "x",
        );
      if (kind === "whatsapp") {
        choice(at("mode"), ["observe", "forward"]);
        text(
          at("channel_jid"),
          /^[^@\s]+@newsletter$/,
          "Enter a channel identifier ending in @newsletter.",
        );
        try {
          const url = new URL(String(get(at("channel_url"))));
          if (url.protocol !== "https:") throw new Error();
        } catch {
          error(at("channel_url"), "Enter an HTTPS channel URL.");
        }
        const observing = get(at("mode")) === "observe";
        if (observing) {
          if (get(at("emoji")) !== null)
            error(at("emoji"), "Clear the source emoji for observe-only mode.");
          for (const key of [
            "forward_media",
            "enable_llm_title",
            "enable_llm_summary",
            "enable_llm_routing",
            "enable_llm_relevance_filter",
          ]) {
            if (get(at(key)) !== false) error(at(key), "Turn this off for observe-only mode.");
          }
        } else {
          emoji(at("emoji"));
        }
        for (const key of ["up", "down", "hold"]) emoji([...at("status_emojis"), key], true);
      } else {
        text(
          at("handle"),
          kind === "x" ? /^[A-Za-z0-9_]{1,15}$/ : /^[A-Za-z0-9._]{1,30}$/,
          "Enter a valid account handle without @.",
        );
        const handle = String(get(at("handle")));
        try {
          const raw = String(get(at("profile_url")));
          const url = new URL(raw);
          const host = kind === "x" ? "x.com" : "instagram.com";
          const match =
            kind === "x"
              ? url.pathname.toLowerCase() === `/${handle.toLowerCase()}`
              : raw === `https://${url.hostname}/${handle}`;
          if (
            url.protocol !== "https:" ||
            !/^https:\/\/(?:www\.)?(?:x\.com|instagram\.com)\//i.test(raw) ||
            ![host, `www.${host}`].includes(url.host) ||
            url.search ||
            url.hash ||
            url.username ||
            url.password ||
            !match
          )
            throw new Error();
        } catch {
          error(
            at("profile_url"),
            `Use https://${kind === "x" ? "x.com" : "instagram.com"}/${handle || "handle"} with no trailing slash.`,
          );
        }
        choice(at("source"), kind === "x" ? ["rsshub", "hybrid", "direct_x"] : ["rsshub"], kind === "x");
        if (kind === "x") {
          if (get(at("show_quoted_post")) !== undefined) bool(at("show_quoted_post"));
          emoji(at("emoji"));
          emoji(at("twitter_emoji"));
          for (const key of [
            "forward_normal_post",
            "forward_quote_post",
            "forward_reply",
            "forward_repost",
          ])
            bool(at(key));
          choice(at("media_policy"), ["all", "omit_last"], true);
          choice([...at("thread_handling"), "mode"], ["self_chain", "disabled"]);
          numeric([...at("thread_handling"), "max_posts"], 1, 20);
          numeric([...at("thread_handling"), "max_age_minutes"], 1, 1440);
          numeric([...at("thread_handling"), "settle_minutes"], 1, 240);
        } else {
          text(at("platform_emoji"));
          if (typeof get(at("emoji")) !== "string")
            error(at("emoji"), "Enter text or leave empty.");
          bool(at("forward_post"));
          bool(at("forward_reel"));
          numeric(at("ocr_min_confidence"), 0, 1, false);
          numeric(at("max_reel_frames"), 1, 8);
          const languages = get(at("ocr_languages"));
          if (
            !Array.isArray(languages) ||
            !languages.length ||
            languages.some((value) => !["eng", "ind"].includes(String(value))) ||
            new Set(languages).size !== languages.length
          )
            error(at("ocr_languages"), "Choose English, Indonesian, or both.");
        }
      }
      const channels = get(at("discord_channels"));
      const observing = kind === "whatsapp" && get(at("mode")) === "observe";
      if (!Array.isArray(channels) || (!observing && !channels.length)) {
        error(
          at("discord_channels"),
          observing
            ? "Use an empty destination list for observe-only mode."
            : "Add at least one destination.",
        );
        return;
      }
      if (observing && channels.length)
        error(at("discord_channels"), "Remove Discord destinations for observe-only mode.");
      const channelPaths = channels.map((_, index) => [...at("discord_channels"), index]);
      channelPaths.forEach((route) => {
        if (kind === "whatsapp")
          choice(
            [...route, "key"],
            ["macro_news", "id_stocks_news", "id_industry_news", "id_stocks_swing"],
          );
        else
          text(
            [...route, "key"],
            /^[a-z0-9][a-z0-9_-]*$/,
            "Use lowercase letters, numbers, underscores or hyphens.",
          );
        discord([...route, "channel_id"]);
        text([...route, "description"]);
      });
      unique(
        channelPaths.map((route) => get([...route, "key"])),
        channelPaths.map((route) => [...route, "key"]),
        "Use a unique destination key.",
      );
      if (kind !== "whatsapp")
        unique(
          channelPaths.map((route) => get([...route, "channel_id"])),
          channelPaths.map((route) => [...route, "channel_id"]),
          "Choose a different destination channel.",
        );
      const routing = get(at("enable_llm_routing"));
      if (kind === "x" && ((routing && channels.length < 2) || (!routing && channels.length !== 1)))
        error(
          at("discord_channels"),
          routing
            ? "Automatic routing needs at least two destinations."
            : "Use one destination, or enable automatic routing.",
        );
      if (
        kind === "instagram" &&
        routing &&
        !["macro_news", "id_stocks_news"].every((key) =>
          channelPaths.some((route) => get([...route, "key"]) === key),
        )
      )
        error(
          at("discord_channels"),
          "Automatic routing needs macro_news and id_stocks_news destinations.",
        );
    });
    return errors;
  }
  const board = watcherId === "bursawatch-dc-swing-board";
  const news = watcherId === "bursawatch-tg-market-news";
  const destinationKeys = board
    ? ["heartbeat_discord_channel_id"]
    : news
      ? [
          "id_stocks_news_discord_channel_id",
          "macro_news_discord_channel_id",
          "industry_news_discord_channel_id",
          "heartbeat_discord_channel_id",
        ]
      : ["alert_discord_channel_id", "heartbeat_discord_channel_id"];
  destinationKeys.forEach((key) => discord(["destinations", key]));
  unique(
    destinationKeys.map((key) => get(["destinations", key])),
    destinationKeys.map((key) => ["destinations", key]),
    "Choose a different destination channel.",
  );
  if (news) {
    for (const provider of ["phintraco", "tuntun"])
      text(
        ["providers", provider, "telegram_username"],
        /^[A-Za-z][A-Za-z0-9_]{4,31}$/,
        "Enter a Telegram username without @.",
      );
  } else if (!board) {
    numeric(["source", "telegram_channel_id"], 1, 9_999_999_999);
    text(
      ["source", "telegram_username"],
      /^[A-Za-z][A-Za-z0-9_]{4,31}$/,
      "Enter a Telegram username without @.",
    );
  }
  if (news || watcherId === "bursawatch-tg-kelas-investasi-gtw")
    prompt(["additional_prompt_instruction"], true);
  return errors;
}

type ScheduleState = {
  schedule: { revision: number } | null;
  reconciliation: { status: string; effective: boolean; applied_revision: number | null };
};

export function isScheduleApplied(
  job: ScheduleState,
  expectedRevision = job.schedule?.revision,
): boolean {
  return (
    expectedRevision !== undefined &&
    job.schedule?.revision === expectedRevision &&
    job.reconciliation.status === "applied" &&
    job.reconciliation.effective &&
    job.reconciliation.applied_revision === expectedRevision
  );
}

export function validateScheduleMinutes(
  value: string,
  minSeconds: number | null,
  maxSeconds: number | null,
): string | null {
  const minutes = Number(value);
  const min = Math.max(60, minSeconds ?? 60) / 60;
  const max = Math.min(86400, maxSeconds ?? 86400) / 60;
  if (!value.trim() || !Number.isInteger(minutes) || minutes < min || minutes > max)
    return `Enter a whole number from ${Math.ceil(min)} to ${Math.floor(max)} minutes.`;
  return null;
}
