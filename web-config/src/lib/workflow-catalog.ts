// Public capability projection, not runtime configuration or live health.
export const reviewedBackend = "6abf28732f92cc8c1249372141f575f794d307b5";
export const workflowGroups = {
  sources: "Social sources",
  research: "Market research",
  tracking: "Plan tracking",
} as const;
export type WorkflowGroup = keyof typeof workflowGroups;
export type WorkflowCapability = {
  id: string;
  name: string;
  group: WorkflowGroup;
  input: string;
  summary: string;
  produces: string[];
  boundary: string;
  timing: string;
  module: string;
  contract: string;
  action?: { href: string; label: string };
};
export const workflowCatalog: WorkflowCapability[] = [
  {
    id: "market-news",
    name: "Company & macro news",
    group: "research",
    input: "Telegram · Tuntun and Phintraco",
    summary: "Separate company developments from wider market news.",
    produces: [
      "Source-grounded Indonesian summaries",
      "Company price context across 1 day, 1 week, 1 month and 3 months",
      "Separate company, industry and macro coverage",
    ],
    boundary:
      "Price context currently uses Yahoo, not Sectors. Source access and routing are managed by the backend.",
    timing:
      "Scheduled Telegram intake; source eligibility and duplicate checks happen before summarisation.",
    module: "cron-tg-market-news",
    contract: "AGENTS.md",
  },
  {
    id: "phintraco-swing",
    name: "Phintraco Swing calls",
    group: "research",
    input: "Telegram · Phintraco Daily",
    summary: "Keep the broker’s entries, targets and updates together.",
    produces: [
      "Trading Buy, Buy on Support and Speculative Buy calls",
      "Original entry, target, stop-loss and chart",
      "Subsequent source status updates",
    ],
    boundary:
      "Original source calls are forwarded without inventing a strategy. This is not order execution or a generated recommendation.",
    timing: "Scheduled source checks; eligible calls are forwarded once.",
    module: "cron-tg-phintraco-swing",
    contract: "CRON.md",
  },
  {
    id: "gtw-research",
    name: "GTW research bundles",
    group: "research",
    input: "Telegram · Kelas Investasi GTW",
    summary: "Read completed research bundles without losing their source context.",
    produces: [
      "Completed-bundle summaries",
      "Original header image",
      "Supporting setup context for the Swing board",
    ],
    boundary:
      "A supporting setup is not a primary plan or an independently monitored price strategy. Channel access remains backend-owned.",
    timing: "Future-only bundle intake; incomplete bundles are not treated as finished research.",
    module: "cron-tg-kelas-investasi-gtw",
    contract: "SKILL.md",
  },
  {
    id: "x-accounts",
    name: "X account watch",
    group: "sources",
    input: "X · selected public accounts",
    summary: "Follow relevant posts and threads from the accounts you choose.",
    produces: [
      "Original posts, quotes, replies and reposts",
      "Grouped threads and source media",
      "Relevant market summaries with source attribution",
    ],
    boundary:
      "Public posts are evidence, not verified investment advice. Following an account in this web app does not start its backend watcher yet.",
    timing:
      "Scheduled account intake and a separate queue worker; thread settling prevents partial summaries.",
    module: "cron-x-account-watch",
    contract: "SKILL.md",
    action: { href: "/app/following?platform=x", label: "X preferences" },
  },
  {
    id: "instagram-accounts",
    name: "Instagram account watch",
    group: "sources",
    input: "Instagram · posts, carousels and reels",
    summary: "Bring captions and visual research into the same reading flow.",
    produces: [
      "Post and reel intake",
      "Caption and carousel text extraction with selective image analysis",
      "Company and macro summaries grounded in the publication",
    ],
    boundary:
      "The reviewed watcher excludes generic education and trade setups. Media analysis does not make unsupported claims reliable.",
    timing: "Scheduled feed checks; media extraction and relevance checks precede delivery.",
    module: "cron-ig-account-watch",
    contract: "SKILL.md",
    action: { href: "/app/following?platform=instagram", label: "Instagram preferences" },
  },
  {
    id: "whatsapp-channels",
    name: "WhatsApp Channel watch",
    group: "sources",
    input: "WhatsApp · public Channels",
    summary: "Follow Channel updates without confusing them with your private chats.",
    produces: [
      "Channel text, images and video",
      "Company and macro routing",
      "Source technical reviews routed to Swing, preserving the original stance",
    ],
    boundary:
      "This reads public Channels; it does not read personal inboxes or establish outbound WhatsApp delivery.",
    timing:
      "Channel events enter a durable queue, then scheduled processing handles eligible updates.",
    module: "cron-wa-channel-watch",
    contract: "SKILL.md",
    action: { href: "/app/following?platform=whatsapp", label: "WhatsApp source preferences" },
  },
  {
    id: "swing-board",
    name: "Swing plan tracking",
    group: "tracking",
    input: "Source-backed cash-equity plans",
    summary: "Separate primary plans from supporting research and chart context.",
    produces: [
      "Primary plan, Supporting setup and Chart context tiers",
      "Original source history and target or stop status",
      "Resolved topics archived after two calendar dates",
    ],
    boundary:
      "Only a same-date closing bar can update a plan. Missing data leaves previous facts intact. The board does not infer trades or execute orders.",
    timing:
      "Weekdays at 16:30 WIB; 17:00 retry only when the initial close is unavailable. These are documented schedules, not live health.",
    module: "cron-dc-swing-board",
    contract: "CRON.md",
  },
];
export const supportingCapabilities = [
  {
    name: "Evidence-led stock identification",
    module: "skill-guess-stock",
    description:
      "A non-scheduled research skill compares chart, financial and transaction clues with dated evidence and rejection reasons. No web upload or analysis endpoint is available.",
  },
  {
    name: "Source identity",
    module: "skill-profile-emoji",
    description:
      "Reviewed X and Instagram profile snapshots identify source messages in Discord. These are not continuously synchronised avatars.",
  },
  {
    name: "Consistent Swing messages",
    module: "lib-swing-format",
    description:
      "Shared formatting preserves source-backed calls. The BRI adapter is future-only, not an active WhatsApp-to-board connection.",
  },
  {
    name: "Telegram connection recovery",
    module: "lib-telegram-resilience",
    description:
      "Shared session coordination, authorisation holds and bounded retries protect Telegram intake. The backend owns this state.",
  },
  {
    name: "Public feed intake",
    module: "service-rsshub",
    description:
      "Shared feed transport supports X and Instagram intake. Cookies, proxies and service controls are never browser preferences.",
  },
  {
    name: "Source media",
    module: "service-cobalt",
    description:
      "Media extraction supports source research. Service credentials and deployment stay with the backend operator.",
  },
];
export function filterWorkflows(query: string, group: WorkflowGroup | "all") {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return workflowCatalog.filter(
    (item) =>
      (group === "all" || item.group === group) &&
      words.every((word) =>
        `${item.name} ${item.input} ${item.summary} ${item.produces.join(" ")}`
          .toLowerCase()
          .includes(word),
      ),
  );
}
export function backendContractUrl(item: WorkflowCapability) {
  return `https://github.com/absolutepraya/bursawatch-engine/blob/${reviewedBackend}/${item.module}/${item.contract}`;
}
