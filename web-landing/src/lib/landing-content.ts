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

export type Sentiment = { tone: "up" | "down" | "flat"; label: string };

export type FeedMessage = {
  time: string;
  source: string;
  title: string;
  author?: { name: string; avatar: string; badge?: string };
  via: string;
  summary: string;
  price?: { last: string; rows: PriceRow[] };
  cap?: string;
  sectors?: {
    sector: string;
    consensus: { rating: string; detail: string };
    sentiment: Sentiment;
  };
  image?: { src: string; alt: string; width: number; height: number };
};

/** The hero delivery: a real #id-stocks-news message (7 Oct 2026, title and summary shortened) in the current format. */
export const NEWS_FEED: FeedMessage[] = [
  {
    time: "Hari ini 09.22",
    source: "tuntun",
    via: "Tuntun",
    title: "REAL: Bersiap akuisisi HIGEN untuk ekspansi data center",
    summary:
      "REAL bersiap mengakuisisi PT Quanta Tunas Abadi (HIGEN) untuk masuk ke data center dan managed service. Anak usahanya, RGST, meneken MoU dengan HIGEN pada 6 Oktober 2026.",
    price: {
      last: "52",
      rows: [
        { label: "1D", value: "+9 (+20,93%)", tone: "up" },
        { label: "1W", value: "+17 (+48,57%)", tone: "up" },
        { label: "1M", value: "+2 (+4,00%)", tone: "up" },
        { label: "3M", value: "+2 (+4,00%)", tone: "up" },
      ],
    },
    cap: "Rp285,2 M",
    // Sector comes from Sectors; the analyst numbers and the sentiment read are samples until they feed in.
    sectors: {
      sector: "Properties & Real Estate",
      consensus: { rating: "BUY", detail: "8 analis, 100% Buy" },
      sentiment: { tone: "up", label: "Positif" },
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

/** Measured on Bursawatch deliveries, 25 Aug to 5 Oct 2026. Re-measure before changing the numbers. */
export const PROOF = {
  note: "Diukur dari pesan Bursawatch 25 Agu sampai 5 Okt 2026: 269 pesan di lima channel, dan 154 pos X untuk kecepatan.",
  items: [
    {
      figure: "100%",
      label: "pesan punya link ke sumber aslinya",
      detail: "269 dari 269 pesan yang diukur",
    },
    {
      figure: "22 menit",
      label: "median dari pos asli sampai ke Discord kamu",
      detail: "7 dari 10 pos X sampai dalam 30 menit",
    },
    {
      figure: "Dari teks sumber",
      label: "ringkasan berdasar isi sumber, bukan tebakan AI",
      detail: "Harga diambil dari data pasar",
    },
  ],
} as const;

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
  date: "Wed, 7 Oct 2026",
  close: {
    last: "6.193",
    rows: [
      { label: "1D", value: "+74 (+1.21%)", tone: "up" },
      { label: "1W", value: "+71 (+1.16%)", tone: "up" },
      { label: "1M", value: "-444 (-6.68%)", tone: "down" },
      { label: "3M", value: "+448 (+7.81%)", tone: "up" },
    ] as PriceRow[],
  },
  outlook:
    "Jika momentum beli semakin kuat, IHSG berpotensi menguji level 6.370. Sebaliknya, risiko koreksi kembali meningkat jika IHSG turun di bawah 6.120. Head of Retail Research BNI Sekuritas, Fanny Suherman menuturkan, IHSG berpotensi naik untuk tes resistance di 6200-6250 seiring FTSE pertahankan secondary emerging status Indonesia. \u201CHati-hati jika gagal break 6.250, IHSG potensi koreksi kembali,\u201D kata Fanny. IDXChannel - Pergerakan Indeks Harga Saham Gabungan (IHSG) diproyeksi berada dalam rentang 5.800 hingga 6.200 pada akhir 2026. Proyeksi ini skenario terburuk (worst case) apabila berbagai katalis positif yang dinantikan pasar modal gagal terealisasi.",
  global: [
    { emoji: "kospi", name: "KOSPI", change: "-137.49 poin (-1.98%)", tone: "down" },
    { emoji: "nikkei", name: "Nikkei", change: "-648.27 poin (-0.92%)", tone: "down" },
    { emoji: "spy", name: "SPY", change: "+4.26 USD (+0.55%)", tone: "up" },
    { emoji: "qqq", name: "QQQ", change: "+3.46 USD (+0.46%)", tone: "up" },
    { emoji: "eido", name: "EIDO", change: "+0.01 USD (+0.08%)", tone: "up" },
    { emoji: "usdidr", name: "USD/IDR", change: "-21.10 IDR (-0.12%)", tone: "up" },
  ] as { emoji: string; name: string; change: string; tone: PriceTone }[],
  agenda: [
    ["Perkembangan Indeks Harga Konsumen", "Mon, 02 Nov 2026"],
    ["Perkembangan Ekspor dan Impor", "Mon, 02 Nov 2026"],
    ["Pertumbuhan Ekonomi", "Thu, 05 Nov 2026"],
  ],
} as const;
