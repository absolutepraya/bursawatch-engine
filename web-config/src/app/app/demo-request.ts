import { WorkspaceError } from "@/lib/control-browser";
import reviewedSources from "@/lib/fixtures/reviewed-sources.json";
import { catalogWrite, type CatalogConfig, type EffectiveCatalog, type SourceCatalog } from "@/lib/source-catalog";
import { watcherNames, supportsWatcherConfig, validateWatcherConfig } from "@/lib/watcher-fields";
import type { OperatorComponent, OperatorComponentActivity, OperatorJob, OperatorObservation } from "@/lib/operator-inventory";
import type { Publication, PublicationCoverage } from "@/lib/publications";
import type { ControlConfigSnapshot, ControlJob, ControlRun, ControlWatcher } from "@/server/control-plane";
import type { controlBrowser } from "@/lib/control-browser";

export type DemoRequester = ReturnType<typeof controlBrowser>;

const sampleTime = "2026-10-01T08:00:00+07:00";
const hex = (digit: string) => digit.repeat(64);
const sampleDiscordChannel = "100000000000000001";

function sampleEmoji(name: string, id: string) {
  return `<:${name}:${id}>`;
}

function profileDefaults(sourceId: string, displayName: string, handle: string, url: string) {
  return {
    id: sourceId,
    enabled: true,
    display_name: displayName,
    emoji: sampleEmoji("sample", "100000000000000002"),
    discord_channels: [{ key: "macro_news", channel_id: sampleDiscordChannel, description: "Sample news route" }],
    forward_media: true,
    enable_llm_title: true,
    enable_llm_summary: false,
    enable_llm_routing: false,
    enable_llm_relevance_filter: true,
    additional_prompt_instruction: "",
    max_items_per_poll: 20,
    source: "rsshub",
    profile_url: url,
    handle,
    twitter_emoji: sampleEmoji("sample", "100000000000000003"),
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

const profile = profileDefaults("kutekians", "Kutekians", "Kutekians", "https://x.com/Kutekians");

function initialConfigs(): Record<string, Record<string, unknown>> {
  const destinations = (keys: string[]) =>
    Object.fromEntries(
      keys.map((key, index) => [key, `1000000000000000${String(index + 10).padStart(3, "0")}`]),
    );
  const genericChannel = (key: string) => ({ key, channel_id: sampleDiscordChannel, description: "Sample route" });
  return {
    "bursawatch-x-account-watch": { version: 1, profiles: [profile] },
    "bursawatch-ig-account-watch": {
      version: 1,
      profiles: [
        {
          id: "beyondthefundamental",
          enabled: false,
          display_name: "Beyond the Fundamental",
          emoji: "",
          discord_channels: [genericChannel("id_stocks_news")],
          forward_media: true,
          enable_llm_title: true,
          enable_llm_summary: false,
          enable_llm_routing: false,
          enable_llm_relevance_filter: true,
          additional_prompt_instruction: "",
          max_items_per_poll: 20,
          source: "rsshub",
          profile_url: "https://www.instagram.com/beyondthefundamental",
          handle: "beyondthefundamental",
          platform_emoji: "Instagram",
          forward_post: true,
          forward_reel: true,
          ocr_languages: ["eng", "ind"],
          ocr_min_confidence: 0.5,
          max_reel_frames: 4,
        },
      ],
    },
    "bursawatch-wa-channel-watch": {
      version: 2,
      profiles: [
        {
          id: "sample-channel",
          enabled: false,
          display_name: "Sample WhatsApp Channel",
          emoji: sampleEmoji("sample", "100000000000000004"),
          discord_channels: [genericChannel("id_stocks_news")],
          forward_media: true,
          enable_llm_title: true,
          enable_llm_summary: false,
          enable_llm_routing: false,
          enable_llm_relevance_filter: true,
          additional_prompt_instruction: "",
          max_items_per_poll: 20,
          mode: "forward",
          channel_jid: "sample-channel@newsletter",
          channel_url: "https://example.invalid/sample-channel",
          status_emojis: { up: null, down: null, hold: null },
          relevance_scope: "stock_market",
        },
      ],
    },
    "bursawatch-tg-market-news": {
      version: 1,
      providers: {
        phintraco: { telegram_username: "sample_phintraco" },
        tuntun: { telegram_username: "sample_tuntun" },
      },
      destinations: destinations([
        "id_stocks_news_discord_channel_id",
        "macro_news_discord_channel_id",
        "industry_news_discord_channel_id",
        "heartbeat_discord_channel_id",
      ]),
      additional_prompt_instruction: "",
    },
    "bursawatch-tg-phintraco-swing": {
      version: 1,
      source: { telegram_username: "sample_phintraco", telegram_channel_id: 10001 },
      destinations: destinations(["alert_discord_channel_id", "heartbeat_discord_channel_id"]),
    },
    "bursawatch-tg-kelas-investasi-gtw": {
      version: 1,
      source: { telegram_username: "sample_kelas", telegram_channel_id: 10002 },
      destinations: destinations(["alert_discord_channel_id", "heartbeat_discord_channel_id"]),
      additional_prompt_instruction: "",
    },
    "bursawatch-dc-swing-board": {
      version: 1,
      destinations: { heartbeat_discord_channel_id: "100000000000000020" },
    },
    "bursawatch-stockbit-snips": {
      version: 1,
      feeds: [
        { id: "stockbit_commentary", enabled: true },
        { id: "unboxing", enabled: false },
        { id: "unboxing_ipo", enabled: false },
        { id: "ai_reports_stockbit", enabled: false },
      ],
      destinations: {
        id_stocks_news_channel_id: "100000000000000021",
        macro_news_channel_id: "100000000000000022",
      },
      additional_prompt_instruction: "",
    },
    "bursawatch-dc-morning-brief": {
      version: 1,
      timezone: "Asia/Jakarta",
      cutoff_time: "07:30",
      delivery_days: "weekdays",
      delivery_time: "08:00",
      fallback_minutes: 5,
      retry_minutes: 15,
      destination_channel_id: null,
      instruments: ["SPY", "EIDO", "USDIDR"],
      logos: {},
    },
  };
}

const watcherIds = Object.keys(watcherNames);
const watchers: ControlWatcher[] = watcherIds.map((watcherId) => ({
  watcher_id: watcherId,
  display_name: watcherNames[watcherId],
  current_revision: 1,
  updated_at: sampleTime,
}));

const initialRuns: ControlRun[] = [
  {
    run_id: "sample-run-market-news-01",
    watcher_id: "bursawatch-tg-market-news",
    scheduler_job_id: "sample-market-news-job",
    trigger: "sample record",
    config_revision: 1,
    started_at: "2026-09-30T08:00:00+07:00",
    finished_at: "2026-09-30T08:00:08+07:00",
    status: "ok",
  },
  {
    run_id: "sample-run-x-01",
    watcher_id: "bursawatch-x-account-watch",
    scheduler_job_id: "sample-x-job",
    trigger: "sample record",
    config_revision: 1,
    started_at: "2026-10-01T08:15:00+07:00",
    finished_at: "2026-10-01T08:15:11+07:00",
    status: "degraded",
  },
  {
    run_id: "sample-run-swing-board-01",
    watcher_id: "bursawatch-dc-swing-board",
    scheduler_job_id: "sample-swing-board-job",
    trigger: "sample record",
    config_revision: 1,
    started_at: "2026-10-01T09:00:00+07:00",
    finished_at: "2026-10-01T09:00:06+07:00",
    status: "ok",
  },
];

const controlJobs: ControlJob[] = watcherIds.map((watcherId) => ({
  job_id: `sample-${watcherId.replaceAll("bursawatch-", "")}-job`,
  watcher_id: watcherId,
  display_name: `${watcherNames[watcherId]} example job`,
  schedule_kind: "fixed",
  min_interval_seconds: null,
  max_interval_seconds: null,
  schedule: null,
  reconciliation: { status: "not_connected", applied_revision: null, effective: false },
}));

const sourceAdapterId = "sample-source-intake";
const demoComponents: OperatorComponent[] = [
  {
    inventory_version: 1,
    component_id: sourceAdapterId,
    kind: "source_adapter",
    display_name: "Sample source intake",
    capabilities: [],
    pipeline_ids: [],
    config_resource_ids: [],
    related_component_ids: [],
    job_ids: [],
  },
  ...watcherIds.map((watcherId) => ({
    inventory_version: 1 as const,
    component_id: watcherId,
    kind: "domain_owner" as const,
    display_name: watcherNames[watcherId],
    capabilities: [],
    pipeline_ids: [],
    config_resource_ids: [`watcher:${watcherId}`],
    related_component_ids: [sourceAdapterId],
    job_ids: [controlJobs.find((job) => job.watcher_id === watcherId)!.job_id],
  })),
];

const operatorJobs: OperatorJob[] = [
  {
    job_id: "sample-source-intake-job",
    can_edit: false,
    watcher_id: null,
    component_ids: [sourceAdapterId, "bursawatch-tg-market-news"],
    display_name: "Sample source intake",
    runtime_job_key: "sample.source-intake",
    schedule_kind: "interval",
    min_interval_seconds: 300,
    max_interval_seconds: 86400,
    schedule: {
      api_version: 1,
      job_id: "sample-source-intake-job",
      revision: 1,
      enabled: true,
      interval_seconds: 900,
      timezone: "Asia/Jakarta",
      schedule_sha256: hex("a"),
      updated_at: sampleTime,
    },
    reconciliation: { status: "not_connected", applied_revision: null, effective: false, has_error: false },
  },
  {
    job_id: "sample-morning-brief-job",
    can_edit: false,
    watcher_id: null,
    component_ids: ["bursawatch-dc-morning-brief"],
    display_name: "Bursawatch Pagi example",
    runtime_job_key: "sample.morning-brief",
    schedule_kind: "fixed",
    min_interval_seconds: null,
    max_interval_seconds: null,
    schedule: null,
    reconciliation: { status: "not_connected", applied_revision: null, effective: false, has_error: false },
  },
];

const observations: OperatorObservation[] = [];
const componentActivity: OperatorComponentActivity = {
  component_id: sourceAdapterId,
  endpoints: [],
  pipelines: [],
  delivery_status: "not instrumented",
};

const sources = reviewedSources.filter((source) => source.platform === "x");
const sourceNames: Record<string, string> = {
  rickyho1989: "Ricky Ho",
  kutekians: "Kutekians",
  writingtorch: "Writing Torch",
  arvinhonami: "Arvin Honami",
  insidertracker: "Insider Tracker",
  doktermarket: "Dokter Market",
  txthariansaham: "Txt Harian Saham",
  wavetiga: "Wave Tiga",
  aldotjahjadi8: "IHSG Journal",
  kobeissiletter: "The Kobeissi Letter",
};

function emptyCatalogConfig(): CatalogConfig {
  return {
    selected_securities: [],
    people_org: [],
    endpoints: [],
    publisher_defaults: [],
    endpoint_overrides: [],
  };
}
const catalogPublishers = {
  institutions: [
    { id: "phintraco", name: "Phintraco Sekuritas", tier: 1, kind: "institution", asset_ref: null },
    { id: "bri-danareksa", name: "BRI Danareksa", tier: 1, kind: "institution", asset_ref: null },
    { id: "tuntun", name: "Tuntun Sekuritas", tier: 1, kind: "institution", asset_ref: null },
    { id: "samuel-sekuritas", name: "Samuel Sekuritas", tier: 1, kind: "institution", asset_ref: null },
  ],
  people_org: sources.map((source) => ({
    id: `x-${source.id}`,
    name: sourceNames[source.id] ?? source.id,
    tier: 1,
    kind: "person",
    asset_ref: null,
  })),
};
const registryEndpoints = sources.map((source) => {
  const address = new URL(source.url).pathname.split("/").filter(Boolean).at(-1) ?? source.id;
  return {
    id: `x-${source.id}`,
    publisher_id: `x-${source.id}`,
    platform: "x",
    address,
    provider_id: null,
    credential_ref: null,
    system_owned: true,
    verified: true,
  };
});
const sampleSecurities = [
  { symbol: "TRUK", name: "PT Pukul Rata Kanan" },
  { symbol: "HRTA", name: "PT Hartadinata Abadi Tbk" },
  { symbol: "ENRG", name: "PT Energi Mega Persada Tbk" },
];
const sourceCapabilities = [
  { id: "company_news", label: "Company news", pipeline: "company_news", version: 1 },
  { id: "macro_news", label: "Macro news", pipeline: "macro_news", version: 1 },
  { id: "stock_status", label: "Stock status", pipeline: "stock_status", version: 1 },
  { id: "trading_plans", label: "Trading plans", pipeline: "swing_plan", version: 1 },
  { id: "swing_support", label: "Swing supporting setup", pipeline: "swing_support", version: 1 },
  { id: "swing_chart_context", label: "Swing chart context", pipeline: "swing_chart_context", version: 1 },
  { id: "stockbit_snips", label: "Stockbit Snips", pipeline: "stockbit_snips", version: 1 },
];
const sourceCompatibility = [
  { endpoint_id: "x-rickyho1989", capability_id: "company_news", dispatch_group: "x_post_route" },
  { endpoint_id: "x-rickyho1989", capability_id: "macro_news", dispatch_group: "x_post_route" },
  {
    endpoint_id: "x-rickyho1989",
    capability_id: "swing_chart_context",
    dispatch_group: "x_post_route",
  },
];

function digest(revision: number) {
  return (revision % 16).toString(16).repeat(64);
}

function configSnapshot(watcherId: string, revision: number, config: Record<string, unknown>): ControlConfigSnapshot {
  const configVersion = watcherId === "bursawatch-wa-channel-watch" ? 2 : 1;
  return {
    api_version: 1,
    watcher_id: watcherId,
    revision,
    config_version: configVersion,
    config: structuredClone(config),
    config_sha256: digest(revision),
    updated_at: sampleTime,
  };
}

function currentCatalog(config: CatalogConfig, revision: number): SourceCatalog {
  const userEndpoints = config.endpoints.map((endpoint) => ({
    ...endpoint,
    provider_id: null,
    credential_ref: endpoint.credential_ref,
    system_owned: false,
    verified: false,
  }));
  return {
    can_edit: true,
    securities: structuredClone(sampleSecurities),
    institutions: structuredClone(catalogPublishers.institutions),
    people_org: structuredClone(catalogPublishers.people_org),
    endpoints: [...structuredClone(registryEndpoints), ...structuredClone(userEndpoints)],
    capabilities: structuredClone(sourceCapabilities),
    compatibility: structuredClone(sourceCompatibility),
    config: {
      revision,
      config: structuredClone(config),
      sha256: digest(revision),
      actor_id: "sample-fixture",
      updated_at: sampleTime,
    },
  };
}

function currentEffectiveCatalog(config: CatalogConfig, revision: number): EffectiveCatalog {
  return {
    revision,
    updated_at: sampleTime,
    selected_securities: structuredClone(config.selected_securities),
    subscriptions: sourceCompatibility.map((item) => {
      const endpoint = registryEndpoints.find((entry) => entry.id === item.endpoint_id)!;
      const override = config.endpoint_overrides.find(
        (entry) => entry.endpoint_id === item.endpoint_id && entry.capability_id === item.capability_id,
      );
      const inherited = config.publisher_defaults.find(
        (entry) =>
          entry.publisher_id === endpoint.publisher_id && entry.capability_id === item.capability_id,
      );
      const intent = override ?? inherited;
      const capability = sourceCapabilities.find((entry) => entry.id === item.capability_id)!;
      return {
        endpoint_id: endpoint.id,
        publisher_id: endpoint.publisher_id,
        platform: endpoint.platform,
        address: endpoint.address,
        provider_id: endpoint.provider_id,
        credential_ref: endpoint.credential_ref,
        capability_id: item.capability_id,
        pipeline: capability.pipeline,
        dispatch_group: item.dispatch_group,
        enabled: intent?.enabled ?? false,
        verification_status: endpoint.verified ? "verified" : "pending",
        settings: intent?.settings ?? {},
        source: override ? "endpoint_override" : inherited ? "publisher_default" : "unset",
      };
    }),
  };
}

const samplePublications: Publication[] = [
  {
    api_version: 1,
    publication_id: hex("1"),
    owner_id: "bursawatch-tg-market-news",
    owner_key: "sample:truk-news",
    version: 1,
    supersedes_version: null,
    type: "idx_company_news",
    route: "id_stocks_news",
    source_event_key: null,
    source_name: "Tuntun Sekuritas",
    source_url: null,
    source_published_at: null,
    market_data_as_of: null,
    delivery_confirmed_at: "2026-10-01T11:00:00+07:00",
    title: "TRUK: PT Pukul Rata Kanan mengajukan VTO maksimal 65,25 juta saham",
    ticker: "TRUK",
    broker_levels: null,
    parent_publication_id: null,
    board_episode_id: null,
    config_revision: 1,
    renderer_version: "sample-renderer-v1",
    source_version: null,
    required_operation_keys: ["sample:truk:leg-1"],
    legs: [
      {
        operation_key: "sample:truk:leg-1",
        operation_digest: hex("2"),
        receipt_operation_id: "sample-receipt-truk",
        destination: sampleDiscordChannel,
        receipt_id: "100000000000000023",
        status: "delivered",
        message_url: null,
        text: "PT Pukul Rata Kanan mengajukan VTO maksimal 65,25 juta saham atau 15% saham TRUK pada harga Rp740 per saham.\n\nLast: 2.580\n1D: +510 (+24,64%)\n1W: +1.160 (+81,69%)\n1M: +1.815 (+237,25%)\n3M: +2.158 (+511,37%)",
        attachments: [],
      },
    ],
    digest: hex("3"),
  },
  {
    api_version: 1,
    publication_id: hex("4"),
    owner_id: "bursawatch-tg-phintraco-swing",
    owner_key: "sample:enrg-plan",
    version: 1,
    supersedes_version: null,
    type: "broker_swing_plan",
    route: "id_stocks_swing",
    source_event_key: null,
    source_name: "Phintraco Sekuritas",
    source_url: null,
    source_published_at: "2026-09-24T05:14:00+07:00",
    market_data_as_of: null,
    delivery_confirmed_at: "2026-09-24T05:14:00+07:00",
    title: "ENRG: Buy",
    ticker: "ENRG",
    broker_levels: {
      entry: "1220 to 1240",
      stop: "<1195",
      targets: ["1325 to 1350"],
      units: "IDR per share",
      attribution: "Alrich Paskalis T, Phintraco Sekuritas",
    },
    parent_publication_id: null,
    board_episode_id: null,
    config_revision: 1,
    renderer_version: "sample-renderer-v1",
    source_version: null,
    required_operation_keys: ["sample:enrg:plan"],
    legs: [
      {
        operation_key: "sample:enrg:plan",
        operation_digest: hex("5"),
        receipt_operation_id: "sample-receipt-enrg-plan",
        destination: sampleDiscordChannel,
        receipt_id: "100000000000000024",
        status: "delivered",
        message_url: null,
        text: "Rebound pasca uji support area 1200 membuka peluang uji pivot area 1350. Golden cross pada Stochastic RSI sejalan dengan indikasi tersebut.",
        attachments: [{ filename: "enrg-plan.jpg", content_type: "image/jpeg", discord_url: null }],
      },
    ],
    digest: hex("6"),
  },
  {
    api_version: 1,
    publication_id: hex("7"),
    owner_id: "bursawatch-dc-swing-board",
    owner_key: "sample:hrta-chart-context",
    version: 1,
    supersedes_version: null,
    type: "swing_context",
    route: "swing_board",
    source_event_key: null,
    source_name: "Phintraco Sekuritas",
    source_url: null,
    source_published_at: "2026-10-01T05:00:00+07:00",
    market_data_as_of: null,
    delivery_confirmed_at: "2026-10-01T05:00:00+07:00",
    title: "HRTA · Primary plan · Below entry",
    ticker: "HRTA",
    broker_levels: null,
    parent_publication_id: null,
    board_episode_id: "sample-hrta",
    config_revision: 1,
    renderer_version: "sample-renderer-v1",
    source_version: null,
    required_operation_keys: ["sample:hrta:chart"],
    legs: [
      {
        operation_key: "sample:hrta:chart",
        operation_digest: hex("8"),
        receipt_operation_id: "sample-receipt-hrta",
        destination: sampleDiscordChannel,
        receipt_id: "100000000000000025",
        status: "delivered",
        message_url: null,
        text: "Primary plan · Below entry",
        attachments: [{ filename: "swing-HRTA.jpg", content_type: "image/jpeg", discord_url: null }],
      },
    ],
    digest: hex("9"),
  },
  {
    api_version: 1,
    publication_id: hex("a"),
    owner_id: "bursawatch-tg-phintraco-swing",
    owner_key: "sample:enrg-update",
    version: 1,
    supersedes_version: null,
    type: "broker_swing_update",
    route: "id_stocks_swing",
    source_event_key: null,
    source_name: "Phintraco Sekuritas",
    source_url: null,
    source_published_at: "2026-09-25T09:21:00+07:00",
    market_data_as_of: null,
    delivery_confirmed_at: "2026-09-25T09:21:00+07:00",
    title: "ENRG: Target 1350 achieved",
    ticker: "ENRG",
    broker_levels: null,
    parent_publication_id: hex("4"),
    board_episode_id: null,
    config_revision: 1,
    renderer_version: "sample-renderer-v1",
    source_version: null,
    required_operation_keys: ["sample:enrg:update"],
    legs: [
      {
        operation_key: "sample:enrg:update",
        operation_digest: hex("b"),
        receipt_operation_id: "sample-receipt-enrg-update",
        destination: sampleDiscordChannel,
        receipt_id: "100000000000000026",
        status: "delivered",
        message_url: null,
        text: "ENRG: Target 1350 achieved",
        attachments: [],
      },
    ],
    digest: hex("c"),
  },
];

const publicationCoverage: PublicationCoverage = {
  cutover: {
    boundary: "2026-09-16T00:00:00+07:00",
    owner_ids: ["bursawatch-tg-market-news", "bursawatch-tg-phintraco-swing", "bursawatch-dc-swing-board"],
  },
  overall_status: "incomplete",
  owners: [
    { owner_id: "bursawatch-tg-market-news", status: "unknown", checkpoint: null },
    { owner_id: "bursawatch-tg-phintraco-swing", status: "unknown", checkpoint: null },
    { owner_id: "bursawatch-dc-swing-board", status: "unknown", checkpoint: null },
  ],
};

function sampleProfileRows(watcherId: string, configs: Record<string, Record<string, unknown>>) {
  const config = configs[watcherId];
  const profileRows = Array.isArray(config?.profiles) ? config.profiles : [];
  return profileRows.map((raw) => {
    const item = raw as Record<string, unknown>;
    const handle = String(item.handle ?? item.id ?? "sample-profile");
    return {
      watcher_id: watcherId,
      profile_id: String(item.id ?? "sample-profile"),
      handle,
      display_name: String(item.display_name ?? handle),
      profile_url: String(item.profile_url ?? item.channel_url ?? "https://example.invalid/sample"),
      enabled: item.enabled === true,
      avatar: {
        mode: "auto" as const,
        url: null,
        source: null,
        fetched_at: null,
        last_success_at: null,
        last_error: null,
        updated_at: sampleTime,
        has_error: false,
      },
    };
  });
}

export function createDemoRequester(): DemoRequester {
  const configs = initialConfigs();
  const configRevisions = Object.fromEntries(watcherIds.map((id) => [id, 1]));
  let catalogRevision = 1;
  let liveCatalogConfig = emptyCatalogConfig();
  const schedules = new Map(operatorJobs.map((job) => [job.job_id, structuredClone(job)]));

  return async function request<T>(path: string, payload?: unknown, options: { signal?: AbortSignal; method?: "POST" } = {}): Promise<T> {
    if (options.signal?.aborted) throw new DOMException("The request was cancelled.", "AbortError");
    const [pathname, queryText = ""] = path.split("?", 2);
    const parts = pathname.split("/").map((part) => decodeURIComponent(part));
    const query = new URLSearchParams(queryText);

    if (pathname === "watchers") return structuredClone(watchers) as T;
    if (pathname === "components") return { inventory_version: 1, components: structuredClone(demoComponents) } as T;
    if (pathname === "jobs" || pathname.startsWith("jobs?")) {
      const componentId = query.get("component_id");
      const rows = [...schedules.values()].filter((job) => !componentId || job.component_ids.includes(componentId));
      return structuredClone(rows) as T;
    }
    if (pathname === "observations" || pathname.startsWith("observations?")) return structuredClone(observations) as T;
    if (parts[0] === "components" && parts.length === 3 && parts[2] === "activity")
      return structuredClone(componentActivity) as T;
    if (parts[0] === "watchers" && parts.length === 3) {
      const [, watcherId, resource] = parts;
      if (!Object.hasOwn(watcherNames, watcherId)) throw new WorkspaceError("missing", "This sample workflow is not available.");
      if (resource === "config" && payload === undefined) {
        return configSnapshot(watcherId, configRevisions[watcherId], configs[watcherId]) as T;
      }
      if (resource === "config" && payload !== undefined) {
        const body = payload as { expectedRevision?: number; config_version?: number; config?: Record<string, unknown> };
        if (body.expectedRevision !== configRevisions[watcherId]) throw new WorkspaceError("conflict", "These sample settings changed. Reload the configuration before saving again.");
        if (!body.config || body.config_version !== (watcherId === "bursawatch-wa-channel-watch" ? 2 : 1))
          throw new WorkspaceError("validation", "This sample configuration version is not supported.", ["version"]);
        const errors = validateWatcherConfig(watcherId, body.config);
        if (Object.keys(errors).length) throw new WorkspaceError("validation", "Review the highlighted fields before saving.", Object.keys(errors));
        if (!supportsWatcherConfig(watcherId, body.config.version)) throw new WorkspaceError("validation", "This sample configuration version is not supported.", ["version"]);
        configs[watcherId] = structuredClone(body.config);
        configRevisions[watcherId] += 1;
        return configSnapshot(watcherId, configRevisions[watcherId], configs[watcherId]) as T;
      }
      if (resource === "jobs") return structuredClone(controlJobs.filter((job) => job.watcher_id === watcherId)) as T;
      if (resource === "runs") return structuredClone(initialRuns.filter((run) => run.watcher_id === watcherId)) as T;
      if (resource === "profiles") return structuredClone(sampleProfileRows(watcherId, configs)) as T;
    }
    if (parts[0] === "watchers" && parts[2] === "profiles" && parts.length === 5 && parts[4] === "avatar" && payload !== undefined) {
      throw new WorkspaceError("forbidden", "Photo changes are disabled in the sample workspace.");
    }
    if (parts[0] === "watchers" && parts[2] === "profiles" && parts.length === 6 && parts[5] === "refresh") {
      throw new WorkspaceError("forbidden", "Photo refresh is disabled in the sample workspace.");
    }
    if (parts[0] === "runs" && parts.length === 3 && parts[2] === "events") return [] as T;
    if (pathname === "source-catalog") return currentCatalog(liveCatalogConfig, catalogRevision) as T;
    if (pathname === "source-catalog/effective") return currentEffectiveCatalog(liveCatalogConfig, catalogRevision) as T;
    if (pathname === "source-catalog/config" && payload !== undefined) {
      const parsed = catalogWrite.safeParse(payload);
      if (!parsed.success) throw new WorkspaceError("validation", "Review the source catalog fields before saving.", ["config"]);
      if (parsed.data.expected_revision !== catalogRevision) throw new WorkspaceError("conflict", "The sample source catalog changed. Reload before saving again.");
      liveCatalogConfig = structuredClone(parsed.data.config);
      catalogRevision += 1;
      return { revision: catalogRevision, config: structuredClone(liveCatalogConfig), sha256: digest(catalogRevision), actor_id: "sample-fixture", updated_at: sampleTime } as T;
    }
    if (pathname === "publications/coverage") return structuredClone(publicationCoverage) as T;
    if (parts[0] === "publications" && parts.length === 2 && !queryText) {
      const item = samplePublications.find((publication) => publication.publication_id === parts[1]);
      if (!item) throw new WorkspaceError("missing", "This sample publication is not available.");
      const linked = samplePublications
        .filter((publication) => publication.parent_publication_id === item.publication_id)
        .map((publication) => ({ publication_id: publication.publication_id, type: publication.type, delivery_confirmed_at: publication.delivery_confirmed_at }));
      return { publication_id: item.publication_id, versions: [structuredClone(item)], linked } as T;
    }
    if (parts[0] === "publications" && parts.length === 1) {
      const filtered = samplePublications.filter((item) =>
        (!query.get("group") || (query.get("group") === "swing" ? ["broker_swing_plan", "broker_swing_update", "swing_context", "swing_bundle", "swing_board_update"].includes(item.type) : !["broker_swing_plan", "broker_swing_update", "swing_context", "swing_bundle", "swing_board_update"].includes(item.type))) &&
        (!query.get("type") || query.get("type") === item.type) &&
        (!query.get("route") || query.get("route") === item.route) &&
        (!query.get("ticker") || query.get("ticker") === item.ticker) &&
        (!query.get("source") || item.source_name.toLowerCase().includes(query.get("source")!.toLowerCase()))
      );
      return { items: structuredClone(filtered), next_cursor: null } as T;
    }
    throw new WorkspaceError("missing", "This sample request is not available.");
  };
}
