// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WatcherConfigEditor } from "./watcher-config-editor";
import { operatorFieldCoverage } from "@/lib/operator-control-coverage";
import type { ConfigSnapshot } from "@/lib/watcher-fields";
import { setDraftOwner } from "@/lib/workspace-drafts";

afterEach(() => {
  cleanup();
  setDraftOwner(null);
});

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
    "bursawatch-dc-morning-brief",
    {
      version: 1,
      timezone: "Asia/Jakarta",
      cutoff_time: "07:30",
      delivery_time: "08:00",
      fallback_minutes: 5,
      retry_minutes: 15,
      destination_channel_id: null,
      instruments: ["SPY"],
      logos: {},
    },
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
  it("keeps the focused source mounted while its name stops matching the search", () => {
    const snapshot: ConfigSnapshot = {
      api_version: 1,
      watcher_id: "bursawatch-x-account-watch",
      revision: 1,
      config_version: 1,
      config: {
        version: 1,
        profiles: [profile("x"), { ...profile("x"), id: "second", display_name: "Second Analyst" }],
      },
      config_sha256: "a".repeat(64),
      updated_at: "2026-09-30T00:00:00Z",
    };
    render(<WatcherConfigEditor snapshot={snapshot} onSave={vi.fn()} />);
    const search = screen.getByRole("searchbox");
    fireEvent.change(search, { target: { value: "Second Analyst" } });
    document.querySelector<HTMLDetailsElement>(".watcher-profile")!.open = true;
    const name = screen.getByLabelText("Display name");
    act(() => name.focus());
    fireEvent.change(name, { target: { value: "Second Analys" } });
    expect(document.querySelectorAll(".watcher-profile")).toHaveLength(1);
    expect(document.activeElement).toBe(name);
    expect(search).toHaveProperty("value", "Second Analyst");
    fireEvent.change(name, { target: { value: "Replacement" } });
    expect(document.activeElement).toBe(name);
    act(() => search.focus());
    expect(document.querySelectorAll(".watcher-profile")).toHaveLength(0);
  });

  it.each(["search", "enabled"])(
    "reveals and focuses a new source through the %s filter",
    async (filter) => {
      const snapshot: ConfigSnapshot = {
        api_version: 1,
        watcher_id: "bursawatch-x-account-watch",
        revision: 1,
        config_version: 1,
        config: {
          version: 1,
          profiles: [
            { ...profile("x"), enabled: true },
            { ...profile("x"), id: "second" },
          ],
        },
        config_sha256: "a".repeat(64),
        updated_at: "2026-09-30T00:00:00Z",
      };
      const onSave = vi.fn();
      render(<WatcherConfigEditor snapshot={snapshot} onSave={onSave} />);
      if (filter === "search")
        fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Example" } });
      else
        fireEvent.change(screen.getByLabelText("Watch status"), { target: { value: "enabled" } });
      fireEvent.click(screen.getByRole("button", { name: "Add account" }));
      expect(screen.getByRole("searchbox")).toHaveProperty("value", "");
      expect(screen.getByLabelText("Watch status")).toHaveProperty("value", "all");
      expect(document.querySelectorAll(".watcher-profile")).toHaveLength(3);
      await waitFor(() => expect(document.activeElement).toHaveProperty("name", "profiles.2.id"));
      const added = document.querySelectorAll<HTMLDetailsElement>(".watcher-profile")[2];
      expect(added.open).toBe(true);
      expect(added.querySelector(".watcher-profile-state")?.textContent).toBe("Paused");
      expect(onSave).not.toHaveBeenCalled();
    },
  );

  it("edits the original account behind a filtered result and preserves hidden siblings and unknown fields", async () => {
    setDraftOwner("synthetic-filter-operator");
    const profiles = ["first", "second", "third"].map((handle) => ({
      ...profile("x"),
      id: handle,
      handle,
      display_name: handle,
      profile_url: `https://x.com/${handle}`,
      untouched: { future_setting: true },
    }));
    const snapshot: ConfigSnapshot = {
      api_version: 1,
      watcher_id: "bursawatch-x-account-watch",
      revision: 1,
      config_version: 1,
      config: { version: 1, profiles, future_option: "preserve" },
      config_sha256: "a".repeat(64),
      updated_at: "2026-09-30T00:00:00Z",
    };
    const onSave = vi.fn(async (config) => ({ ...snapshot, revision: 2, config }));
    render(<WatcherConfigEditor snapshot={snapshot} onSave={onSave} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "second" } });
    expect(document.querySelectorAll(".watcher-profile")).toHaveLength(1);
    document.querySelector<HTMLDetailsElement>(".watcher-profile")!.open = true;
    fireEvent.change(screen.getByLabelText("Display name"), {
      target: { value: "Updated second" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const submitted = onSave.mock.calls[0][0];
    expect(submitted.profiles[0]).toEqual(profiles[0]);
    expect(submitted.profiles[1]).toEqual({ ...profiles[1], display_name: "Updated second" });
    expect(submitted.profiles[2]).toEqual(profiles[2]);
    expect(submitted.future_option).toBe("preserve");
  });

  it("reveals filtered-out validation errors before focusing the invalid field", async () => {
    const broken = {
      ...profile("x"),
      display_name: "Broken",
      handle: "bad handle",
      profile_url: "https://x.com/example",
    };
    const other = {
      ...profile("x"),
      id: "other",
      display_name: "Other",
      handle: "other",
      profile_url: "https://x.com/other",
    };
    const snapshot: ConfigSnapshot = {
      api_version: 1,
      watcher_id: "bursawatch-x-account-watch",
      revision: 1,
      config_version: 1,
      config: { version: 1, profiles: [broken, other] },
      config_sha256: "a".repeat(64),
      updated_at: "2026-09-30T00:00:00Z",
    };
    const onSave = vi.fn(async () => snapshot);
    render(<WatcherConfigEditor snapshot={snapshot} onSave={onSave} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Other" } });
    document.querySelector<HTMLDetailsElement>(".watcher-profile")!.open = true;
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Other updated" } });
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await waitFor(() => expect(document.activeElement?.getAttribute("aria-invalid")).toBe("true"));
    expect(screen.getByRole("searchbox")).toHaveProperty("value", "");
    expect(document.querySelectorAll(".watcher-profile")).toHaveLength(2);
    expect(onSave).not.toHaveBeenCalled();
  });

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
        expect(screen.getByText(/Instagram source settings are saved/).textContent).toContain(
          "has no scheduled job",
        );
    });
  }
});
