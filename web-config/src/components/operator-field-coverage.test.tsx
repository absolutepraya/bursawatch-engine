// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { WatcherConfigEditor } from "./watcher-config-editor";
import { operatorFieldCoverage } from "@/lib/operator-control-coverage";
import type { ConfigSnapshot } from "@/lib/watcher-fields";

afterEach(cleanup);

const route = [{ key: "id_stocks_news", channel_id: "100000000000000001", description: "News" }];
const profile = (kind: "x" | "instagram" | "whatsapp") => ({
  id: "example_source",
  enabled: false,
  display_name: "Example",
  emoji: "<:example:100000000000000003>",
  discord_channels: kind === "whatsapp" ? route : route,
  forward_media: true,
  enable_llm_title: true,
  enable_llm_summary: true,
  enable_llm_routing: false,
  enable_llm_relevance_filter: true,
  additional_prompt_instruction: "",
  max_items_per_poll: 20,
  ...(kind === "x"
    ? {
        source: "rsshub",
        handle: "example",
        profile_url: "https://x.com/example",
        twitter_emoji: "<:example:100000000000000003>",
        forward_normal_post: true,
        forward_quote_post: true,
        show_quoted_post: false,
        forward_reply: false,
        forward_repost: false,
        media_policy: "all",
        relevance_scope: "stock_market",
        thread_handling: {
          mode: "self_chain",
          max_posts: 10,
          max_age_minutes: 120,
          settle_minutes: 5,
        },
      }
    : {}),
  ...(kind === "instagram"
    ? {
        source: "rsshub",
        handle: "example",
        profile_url: "https://instagram.com/example",
        platform_emoji: "Instagram",
        forward_post: true,
        forward_reel: true,
        ocr_languages: ["eng", "ind"],
        ocr_min_confidence: 0.5,
        max_reel_frames: 4,
      }
    : {}),
  ...(kind === "whatsapp"
    ? {
        mode: "forward",
        channel_jid: "example@newsletter",
        channel_url: "https://whatsapp.com/channel/example",
        relevance_scope: "stock_market",
        status_emojis: { up: null, down: null, hold: null },
      }
    : {}),
});

const cases: Array<[string, Record<string, unknown>]> = [
  ["bursawatch-x-account-watch", { version: 1, profiles: [profile("x")] }],
  ["bursawatch-ig-account-watch", { version: 1, profiles: [profile("instagram")] }],
  ["bursawatch-wa-channel-watch", { version: 2, profiles: [profile("whatsapp")] }],
  [
    "bursawatch-tg-market-news",
    {
      version: 1,
      providers: {
        phintraco: { telegram_username: "exampleph" },
        tuntun: { telegram_username: "exampletuntun" },
      },
      destinations: {
        id_stocks_news_discord_channel_id: "100000000000000001",
        macro_news_discord_channel_id: "100000000000000002",
        industry_news_discord_channel_id: "100000000000000003",
        heartbeat_discord_channel_id: "100000000000000004",
      },
      additional_prompt_instruction: "",
    },
  ],
  [
    "bursawatch-tg-phintraco-swing",
    {
      version: 1,
      source: { telegram_channel_id: 12345, telegram_username: "exampleph" },
      destinations: {
        alert_discord_channel_id: "100000000000000001",
        heartbeat_discord_channel_id: "100000000000000002",
      },
    },
  ],
  [
    "bursawatch-tg-kelas-investasi-gtw",
    {
      version: 1,
      source: { telegram_channel_id: 12345, telegram_username: "examplegtw" },
      destinations: {
        alert_discord_channel_id: "100000000000000001",
        heartbeat_discord_channel_id: "100000000000000002",
      },
      additional_prompt_instruction: "",
    },
  ],
  [
    "bursawatch-dc-swing-board",
    { version: 1, destinations: { heartbeat_discord_channel_id: "100000000000000001" } },
  ],
  [
    "bursawatch-stockbit-snips",
    {
      version: 1,
      feeds: ["stockbit_commentary", "unboxing", "unboxing_ipo", "ai_reports_stockbit"].map(
        (id) => ({ id, enabled: true }),
      ),
      destinations: {
        id_stocks_news_channel_id: "100000000000000001",
        macro_news_channel_id: "100000000000000002",
      },
      additional_prompt_instruction: "",
    },
  ],
];

function normalize(name: string) {
  return name.replace(/\.\d+(?=\.|$)/g, "[]");
}

describe("rendered watcher controls match the field coverage map", () => {
  for (const [watcherId, config] of cases) {
    it(watcherId, () => {
      const snapshot: ConfigSnapshot = {
        api_version: 1,
        watcher_id: watcherId,
        revision: 1,
        config_version: Number(config.version),
        config,
        config_sha256: "a".repeat(64),
        updated_at: "2026-09-30T00:00:00Z",
      };
      render(<WatcherConfigEditor snapshot={snapshot} onSave={async () => snapshot} />);
      const rendered = [
        ...document.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
          "input[name],select[name],textarea[name]",
        ),
      ]
        .filter((element) => !(element instanceof HTMLInputElement && element.readOnly))
        .map((element) => `${watcherId}:${normalize(element.name)}`);
      const expected = operatorFieldCoverage
        .filter((field) => field.path.startsWith(`${watcherId}:`))
        .filter((field) => field.state === "editable")
        .map((field) => field.path);
      expect(new Set(rendered)).toEqual(new Set(expected));
      if (watcherId.includes("phintraco-swing") || watcherId.includes("kelas-investasi")) {
        expect(screen.getByLabelText("Legacy channel username")).toHaveProperty("readOnly", true);
        expect(screen.getByLabelText("Legacy Telegram channel ID")).toHaveProperty(
          "readOnly",
          true,
        );
      }
      if (watcherId.includes("ig-account-watch"))
        expect(screen.getByRole("status").textContent).toContain("has no scheduled job");
    });
  }
});
