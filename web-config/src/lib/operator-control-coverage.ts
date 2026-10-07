/**
 * Reviewed field-level map for the operator controls. Paths use [] for repeated
 * rows. A runtime effect is stated only where the migrated owner consumes it.
 */
export type OperatorFieldCoverage = {
  path: string;
  editor: string;
  validator: string;
  api: string;
  consumer: string;
  effect: string;
  state: "editable" | "read-only legacy";
};

const watcher = (id: string, paths: string[], consumer: string, effect: string) =>
  paths.map((path) => ({
    path: `${id}:${path}`,
    editor: "WatcherConfigEditor",
    validator: "validateWatcherConfig / owner config parser",
    api: "PUT /v1/watchers/{watcher_id}/config",
    consumer,
    effect,
    state: "editable" as const,
  }));
const legacy = (id: string) =>
  ["source.telegram_channel_id", "source.telegram_username"].map((path) => ({
    path: `${id}:${path}`,
    editor: "WatcherConfigEditor (read-only legacy metadata)",
    validator: "owner config parser; migrated pipeline_owner pins canonical pair",
    api: "PUT /v1/watchers/{watcher_id}/config preserves existing values",
    consumer: "No migrated source-selection consumer; shared intake selection is Source Catalog",
    effect: "Display only. Changing shared Telegram selection is done through Sources.",
    state: "read-only legacy" as const,
  }));

const profileCommon = [
  "profiles[].id",
  "profiles[].enabled",
  "profiles[].display_name",
  "profiles[].emoji",
  "profiles[].discord_channels[].key",
  "profiles[].discord_channels[].channel_id",
  "profiles[].discord_channels[].description",
  "profiles[].forward_media",
  "profiles[].enable_llm_title",
  "profiles[].enable_llm_summary",
  "profiles[].enable_llm_routing",
  "profiles[].enable_llm_relevance_filter",
  "profiles[].additional_prompt_instruction",
  "profiles[].max_items_per_poll",
];

const catalogPaths = [
  "selected_securities[]",
  "people_org[].name",
  "people_org[].kind",
  "people_org[].asset_ref.url",
  "people_org[].asset_ref.kind",
  "endpoints[].publisher_id",
  "endpoints[].platform",
  "endpoints[].address",
  "publisher_defaults[].enabled",
  "endpoint_overrides[].enabled",
].map((path) => ({
  path: `source_catalog:${path}`,
  editor: "SourceCatalog",
  validator: "catalogConfig / Control Plane source_catalog.validate_config",
  api: "PUT /v1/source-catalog/config",
  consumer: "Source Inbox capability snapshot; endpoint adapter binding",
  effect: "Saved intent only; verified identity and a supported adapter are also required.",
  state: "editable" as const,
}));

const coverage: OperatorFieldCoverage[] = [
  ...catalogPaths,
  ...watcher(
    "bursawatch-x-account-watch",
    [
      ...profileCommon,
      "profiles[].source",
      "profiles[].profile_url",
      "profiles[].handle",
      "profiles[].twitter_emoji",
      "profiles[].forward_normal_post",
      "profiles[].forward_quote_post",
      "profiles[].show_quoted_post",
      "profiles[].forward_reply",
      "profiles[].forward_repost",
      "profiles[].media_policy",
      "profiles[].relevance_scope",
      "profiles[].thread_handling.mode",
      "profiles[].thread_handling.max_posts",
      "profiles[].thread_handling.max_age_minutes",
      "profiles[].thread_handling.settle_minutes",
    ],
    "cron-x-source-ingest adapter and cron-x-account-watch owner",
    "Enabled profiles govern source selection and owner processing; settings do not prove a poll or delivery.",
  ),
  ...watcher(
    "bursawatch-ig-account-watch",
    [
      ...profileCommon,
      "profiles[].profile_url",
      "profiles[].handle",
      "profiles[].platform_emoji",
      "profiles[].forward_post",
      "profiles[].forward_reel",
      "profiles[].ocr_languages",
      "profiles[].ocr_min_confidence",
      "profiles[].max_reel_frames",
    ],
    "cron-ig-account-watch config owner",
    "Saved domain settings only; Instagram source ingest has no scheduled job and is not currently collected.",
  ),
  ...watcher(
    "bursawatch-wa-channel-watch",
    [
      ...profileCommon,
      "profiles[].mode",
      "profiles[].channel_jid",
      "profiles[].channel_url",
      "profiles[].status_emojis.up",
      "profiles[].status_emojis.down",
      "profiles[].status_emojis.hold",
      "profiles[].relevance_scope",
    ],
    "cron-wa-source-ingest adapter and cron-wa-channel-watch owner",
    "Enabled forward profiles can accept shared intake; observe profiles collect without forwarding.",
  ),
  ...watcher(
    "bursawatch-tg-market-news",
    [
      "providers.phintraco.telegram_username",
      "providers.tuntun.telegram_username",
      "destinations.id_stocks_news_discord_channel_id",
      "destinations.macro_news_discord_channel_id",
      "destinations.industry_news_discord_channel_id",
      "destinations.heartbeat_discord_channel_id",
      "additional_prompt_instruction",
    ],
    "cron-tg-market-news config and news_source_work",
    "Provider usernames are consumed metadata, not shared Telegram reader selection; destinations and instruction affect this owner.",
  ),
  ...watcher(
    "bursawatch-tg-phintraco-swing",
    ["destinations.alert_discord_channel_id", "destinations.heartbeat_discord_channel_id"],
    "cron-tg-phintraco-swing pipeline_owner",
    "Destinations affect owner output. Telegram source identity is fixed legacy metadata.",
  ),
  ...legacy("bursawatch-tg-phintraco-swing"),
  ...watcher(
    "bursawatch-tg-kelas-investasi-gtw",
    [
      "destinations.alert_discord_channel_id",
      "destinations.heartbeat_discord_channel_id",
      "additional_prompt_instruction",
    ],
    "cron-tg-kelas-investasi-gtw pipeline_owner and scan",
    "Destinations and required additive instruction affect owner output. Telegram source identity is fixed legacy metadata.",
  ),
  ...legacy("bursawatch-tg-kelas-investasi-gtw"),
  ...watcher(
    "bursawatch-dc-swing-board",
    ["destinations.heartbeat_discord_channel_id"],
    "cron-dc-swing-board board owner",
    "Changes operational heartbeat routing, not publication routing.",
  ),
  ...watcher(
    "bursawatch-dc-morning-brief",
    [
      "cutoff_time",
      "delivery_time",
      "fallback_minutes",
      "retry_minutes",
      "destination_channel_id",
      "instruments",
      ...["KOSPI", "Nikkei", "SPY", "QQQ", "EIDO", "USDIDR"].map((name) => `logos.${name}`),
    ],
    "cron-dc-morning-brief runner and immutable operator_config",
    "Next unfrozen verified session only; saving neither creates nor activates a scheduler job.",
  ),
  ...watcher(
    "bursawatch-stockbit-snips",
    [
      "feeds[].enabled",
      "destinations.id_stocks_news_channel_id",
      "destinations.macro_news_channel_id",
      "additional_prompt_instruction",
    ],
    "cron-stockbit-snips scan and config owner",
    "Feed switches gate intake; distinct Discord routes and additive guidance affect future article work.",
  ),
  {
    path: "source_catalog:settings",
    editor: "No editor (must remain empty)",
    validator: "catalogConfig strict empty object",
    api: "PUT /v1/source-catalog/config",
    consumer: "None approved",
    effect: "No typed owner consumer exists.",
    state: "read-only legacy",
  },
  ...["enabled", "interval_seconds"].map((field) => ({
    path: `interval_job:${field}`,
    editor: "ScheduleEditor",
    validator: "Control Plane schedule validator and per-job min/max bounds",
    api: "PUT /v1/jobs/{job_id}/schedule",
    consumer: "Hermes schedule reconciler and registered runtime job",
    effect: "Desired schedule only until the matching revision is reconciled as effective.",
    state: "editable" as const,
  })),
];

export const operatorFieldCoverage = coverage;
export const editableOperatorFieldPaths = coverage
  .filter((field) => field.state === "editable")
  .map((field) => field.path);
