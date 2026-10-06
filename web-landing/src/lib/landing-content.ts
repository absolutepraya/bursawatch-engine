/**
 * Landing copy and showcase data. Discord messages, source names, prices and
 * charts are real Bursawatch deliveries from 16 Sep to 1 Oct 2026, matching
 * the launch film. The pain cards are illustrative, not real accounts.
 */

export const DEMO_DISCORD_URL = "https://discord.gg/REPLACE_WITH_DEMO_INVITE";

const SRC = "/landing/src";
export const src = (name: string) => `${SRC}/${name}.png`;

export type PriceTone = "up" | "down";
export type PriceRow = { label: string; value: string; tone: PriceTone };

export type FeedMessage = {
  time: string;
  source: string;
  title: string;
  author?: { name: string; avatar: string; badge?: string };
  summary: string;
  price?: { last: string; rows: PriceRow[] };
  image?: { src: string; alt: string; width: number; height: number };
};

/** The hero delivery: a real #id-stocks-news message. */
export const NEWS_FEED: FeedMessage[] = [
  {
    time: "Hari ini 18.00",
    source: "tuntun",
    title: "TRUK: PT Pukul Rata Kanan mengajukan VTO maksimal 65,25 juta saham",
    summary:
      "PT Pukul Rata Kanan mengajukan VTO maksimal 65,25 juta saham atau 15% saham TRUK pada harga Rp740 per saham.",
    price: {
      last: "2.580",
      rows: [
        { label: "1D", value: "+510 (+24,64%)", tone: "up" },
        { label: "1W", value: "+1.160 (+81,69%)", tone: "up" },
        { label: "1M", value: "+1.815 (+237,25%)", tone: "up" },
        { label: "3M", value: "+2.158 (+511,37%)", tone: "up" },
      ],
    },
  },
];

export const PAINS = [
  {
    id: "ig",
    question: "Follow akun berita saham di IG?",
    hero: "Beritanya telat...",
    tail: "sahamnya keburu terbang duluan 😅",
  },
  {
    id: "telegram",
    question: "Beli tiket grup Telegram “insider A1”?",
    hero: "Boncos bro,",
    tail: "balik modal? Boro-boro... 🥲",
  },
  {
    id: "kelas",
    question: "Ikut kelas saham sana-sini?",
    hero: "Udah mehong,",
    tail: "pas praktik ga sesuai yg dipelajari 😭",
  },
  {
    id: "x",
    question: "Ikut stockpick di X sama Threads?",
    hero: "Adoh rungkad!!",
    tail: "Ga lagi coba-coba 😤",
  },
] as const;

/** TRUE daily closes, 10 Nov 2025 to 6 Feb 2026 (every second session). */
export const TRUE_CLOSES = [
  116, 109, 111, 111, 113, 129, 137, 128, 126, 228, 228, 228, 228, 228, 250, 204, 174, 210, 326,
  438, 448, 530, 530, 530, 530, 432, 352, 348, 296, 226, 193,
];

/** The five live Bursawatch channels, with a real recent headline from each. */
export const CHANNELS = [
  {
    name: "id-stocks-news",
    label: "Berita emiten",
    body: "Aksi korporasi, kinerja, buyback sampai transaksi orang dalam emiten IDX. Tiap berita dirangkum, lengkap dengan harga terakhir 1D, 1W, 1M dan 3M.",
    example: {
      source: "writingtorch",
      title: "HRUM: Harum Energy siapkan buyback saham Rp120 miliar",
    },
    sources: ["tuntun", "bridanareksa", "phintraco", "aldotjahjadi", "writingtorch", "arvinhonami"],
  },
  {
    name: "id-stocks-swing",
    label: "Trading ideas",
    body: "Trading plan dari sekuritas: entry, stop-loss, target dan alasannya. Begitu target tercapai, kamu langsung dikabarin.",
    example: { source: "phintraco", title: "PGEO: First target 1090 achieved" },
    sources: ["phintraco", "bridanareksa"],
  },
  {
    name: "macro-news",
    label: "Makro",
    body: "Data ekonomi Indonesia dan dunia, kebijakan pemerintah, sampai pergerakan pasar global yang ngaruh ke IHSG.",
    example: { source: "tuntun", title: "Neraca dagang Agustus 2026 surplus US$3,55 miliar" },
    sources: ["tuntun", "kobeissiletter", "aldotjahjadi", "arvinhonami"],
  },
  {
    name: "id-industry-news",
    label: "Industri & regulasi",
    body: "Aturan baru, komoditas dan kabar sektor, dari pasokan gas dan RKAB tambang sampai harga minyak.",
    example: {
      source: "tuntun",
      title: "OJK terbitkan aturan Bursa Mineral dan Komoditas Strategis",
    },
    sources: ["tuntun", "bridanareksa"],
  },
  {
    name: "us-stocks-news",
    label: "Saham AS",
    body: "Transaksi insider, kinerja dan valuasi emiten Wall Street.",
    example: {
      source: "rickyho1989",
      title: "NVDA: Permintaan AI tetap jauh di atas kapasitas pasokan",
    },
    sources: ["insidertracker", "kobeissiletter", "rickyho1989"],
  },
] as const;

export const SOURCES = [
  { name: "Phintraco Sekuritas", logo: src("phintraco") },
  { name: "BRI Danareksa", logo: src("bridanareksa") },
  { name: "Samuel Sekuritas", logo: src("samuel") },
  { name: "Tuntun Sekuritas", logo: src("tuntun") },
  { name: "IDX Keterbukaan Informasi", logo: src("idx") },
  { name: "Stockbit", logo: src("stockbit") },
  { name: "Ricky Ho", logo: src("rickyho1989") },
  { name: "The Kobeissi Letter", logo: src("kobeissiletter") },
  { name: "IHSG Journal", logo: src("aldotjahjadi") },
  { name: "Kalender Ekonomi Indonesia", logo: src("bankindonesia") },
] as const;

export type ForumTag =
  "primary" | "support" | "below" | "above" | "zone" | "resolved" | "stop" | "onSupport" | "tp1";

export const FORUM_TAG_LABEL: Record<ForumTag, string> = {
  primary: "Primary plan",
  support: "Supporting setup",
  below: "Below entry",
  above: "Above entry",
  zone: "Entry zone",
  resolved: "Resolved",
  stop: "Stop-loss breached",
  onSupport: "On support",
  tp1: "TP1 reached",
};

export type ForumPost = {
  ticker: string;
  date: string;
  tags: ForumTag[];
  source: string;
  image: string;
  replies: number;
  ago: string;
};

export const FORUM_POSTS: ForumPost[] = [
  {
    ticker: "ENRG",
    date: "Thu, 24 Sep 2026",
    tags: ["primary", "tp1"],
    source: "phintraco",
    image: "/landing/product/enrg-plan.jpg",
    replies: 1,
    ago: "1d ago",
  },
  {
    ticker: "PACK",
    date: "Thu, 1 Oct 2026",
    tags: ["stop", "resolved"],
    source: "phintraco",
    image: "/landing/product/swing-PACK.jpg",
    replies: 0,
    ago: "7h ago",
  },
  {
    ticker: "HRTA",
    date: "Thu, 1 Oct 2026",
    tags: ["primary", "below"],
    source: "phintraco",
    image: "/landing/product/swing-HRTA.jpg",
    replies: 0,
    ago: "7h ago",
  },
  {
    ticker: "BBNI",
    date: "Mon, 28 Sep 2026",
    tags: ["primary", "onSupport"],
    source: "phintraco",
    image: "/landing/product/swing-BBNI.jpg",
    replies: 2,
    ago: "3d ago",
  },
  {
    ticker: "AMMN",
    date: "Wed, 23 Sep 2026",
    tags: ["support", "zone"],
    source: "bridanareksa",
    image: "/landing/product/swing-AMMN.jpg",
    replies: 3,
    ago: "8d ago",
  },
];

/** Real Phintraco ENRG plan (24 Sep 2026) and its first-target follow-up. */
export const ENRG_PLAN = {
  analyst: "Alrich Paskalis T, Phintraco Sekuritas",
  rows: [
    ["Type", "Trading Buy"],
    ["Entry", "1220 to 1240"],
    ["Stop-loss", "<1195"],
    ["Target 1", "1325 to 1350"],
  ],
  reasons:
    "Rebound pasca uji support area 1200 membuka peluang uji pivot area 1350. Golden cross pada Stochastic RSI sejalan dengan indikasi tersebut.",
};

/** Bursawatch Pagi example (preview of 5 Oct 2026). Figures are dummy data. */
export const BRIEF = {
  date: "Mon, 5 Oct 2026",
  timing: "Cutoff data: 07:30 WIB · Target terbit: 08:00 WIB",
  rotationBasis:
    "Basis: ilustrasi historis, bobot cap snapshot tetap. Data harga dan kapitalisasi: Sectors.",
  verdict: "tunggu konfirmasi pemulihan.",
  scenario:
    "Pergerakan di atas 6.100 membuka ruang pemulihan, sementara kehilangan 6.000 mengembalikan tekanan.",
  watch:
    "Rilis cadangan devisa September minggu ini. Cadangan yang naik bisa menahan tekanan rupiah dan memberi ruang IHSG pulih.",
  plan: "lihat respons harga di area kunci sebelum menyimpulkan arah. RSI mendekati oversold sendiri belum cukup untuk memastikan pembalikan.",
  global: [
    { emoji: "kospi", name: "KOSPI", change: "+28,60 (+0,42%)", tone: "up" },
    { emoji: "nikkei", name: "NIKKEI", change: "-210,00 (-0,31%)", tone: "down" },
    { emoji: "qqq", name: "QQQ", change: "+$2,10 (+0,28%)", tone: "up" },
  ] as { emoji: string; name: string; change: string; tone: PriceTone }[],
  snapshot: "Acuan: Asia 07.30 WIB · AS penutupan Fri, 2 Oct 2026. (Sources: Yahoo Finance)",
  agenda: [
    ["Rab, 7 Okt", "Cadangan devisa September", "BI"],
    ["Kam, 15 Okt", "Neraca perdagangan September", "BPS"],
    ["Rab, 21 Okt", "Keputusan BI-Rate", "BI"],
  ],
  sectors: [
    ["Energy", "Leading", "kekuatan relatif +2,3 pp; momentum +1,1 pp."],
    ["Financials", "Improving", "kekuatan relatif -0,6 pp; momentum +0,9 pp."],
    ["Technology", "Weakening", "kekuatan relatif +1,6 pp; momentum -0,8 pp."],
  ],
  konglo: [
    ["Barito", "Leading", "kekuatan relatif +2,5 pp; momentum +1,4 pp."],
    ["Djarum", "Improving", "kekuatan relatif -0,5 pp; momentum +1,1 pp."],
    ["Astra / Jardine", "Weakening", "kekuatan relatif +1,7 pp; momentum -0,9 pp."],
  ],
} as const;
