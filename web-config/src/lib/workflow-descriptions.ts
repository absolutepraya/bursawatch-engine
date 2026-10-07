export const workflowDescriptions: Record<
  string,
  { input: string; processing: string; output: string }
> = {
  "bursawatch-x-account-watch": {
    input: "X accounts",
    processing: "Post filters, threads and summaries",
    output: "Discord channels",
  },
  "bursawatch-ig-account-watch": {
    input: "Instagram accounts",
    processing: "Posts, reels and image text",
    output: "Discord channels",
  },
  "bursawatch-wa-channel-watch": {
    input: "WhatsApp Channels",
    processing: "Relevance, summaries and routing",
    output: "Discord channels",
  },
  "bursawatch-tg-market-news": {
    input: "Telegram news sources",
    processing: "Company, industry and macro news",
    output: "Discord channels",
  },
  "bursawatch-tg-phintraco-swing": {
    input: "Telegram swing calls",
    processing: "Original source calls and updates",
    output: "Discord alerts",
  },
  "bursawatch-tg-kelas-investasi-gtw": {
    input: "Telegram research bundles",
    processing: "Completed bundles and summaries",
    output: "Discord alerts",
  },
  "bursawatch-dc-swing-board": {
    input: "Source-backed plans",
    processing: "Closing-price checks and plan status",
    output: "Discord swing board",
  },
  "bursawatch-dc-morning-brief": {
    input: "Frozen source and market evidence",
    processing: "Factual brief and rotation charts",
    output: "Discord morning brief",
  },
  "bursawatch-stockbit-snips": {
    input: "Four Stockbit Snips feeds",
    processing: "Article analysis and source summaries",
    output: "Two Discord news routes",
  },
};
