import type { EvidenceMode } from "@/lib/types";
import { normalizeTicker } from "@/lib/format";

export interface DailyPoint {
  symbol: string;
  date: string;
  close: number;
  volume: number;
  market_cap: number;
}

export interface DailyEvidence {
  symbol: string;
  points: DailyPoint[];
  origin: EvidenceMode;
  endpoint: string;
  retrievedAt: string;
}

export interface PriceSignal {
  previousClose: number;
  latestClose: number;
  changePercent: number;
  latestDate: string;
}

export function computePriceSignal(points: DailyPoint[]): PriceSignal {
  if (points.length < 2) throw new Error("At least two daily observations are required.");
  const sorted = [...points].sort((a, b) => a.date.localeCompare(b.date));
  const previous = sorted.at(-2)!;
  const latest = sorted.at(-1)!;
  if (!Number.isFinite(previous.close) || previous.close <= 0 || !Number.isFinite(latest.close)) {
    throw new Error("Daily evidence contains an invalid closing price.");
  }
  return {
    previousClose: previous.close,
    latestClose: latest.close,
    changePercent: Number((((latest.close - previous.close) / previous.close) * 100).toFixed(2)),
    latestDate: latest.date,
  };
}

function syntheticDaily(symbol: string, now: Date): DailyPoint[] {
  const normalized = normalizeTicker(symbol);
  const base = normalized === "TLKM" ? 2920 : 4080;
  const moves = [-0.006, 0.004, -0.002, 0.008, 0.036];
  return moves.map((move, index) => {
    const date = new Date(now);
    date.setUTCDate(now.getUTCDate() - (moves.length - 1 - index));
    const prior = index === 0 ? base : base * (1 + moves.slice(0, index).reduce((sum, item) => sum + item, 0));
    return {
      symbol: `${normalized}.JK`,
      date: date.toISOString().slice(0, 10),
      close: Math.round(prior * (1 + move)),
      volume: 120_000_000 + index * 8_500_000,
      market_cap: 620_000_000_000_000,
    };
  });
}

export async function getDailyEvidence(
  symbol: string,
  options: { apiKey?: string; baseUrl?: string; now?: Date; fetchImpl?: typeof fetch } = {},
): Promise<DailyEvidence> {
  const normalized = normalizeTicker(symbol);
  const now = options.now ?? new Date();
  const endpoint = `/v2/daily/${normalized}/`;
  if (!options.apiKey) {
    return {
      symbol: normalized,
      points: syntheticDaily(normalized, now),
      origin: "synthetic-demo",
      endpoint,
      retrievedAt: now.toISOString(),
    };
  }

  const fetchImpl = options.fetchImpl ?? fetch;
  const baseUrl = (options.baseUrl ?? "https://api.sectors.app").replace(/\/$/, "");
  const response = await fetchImpl(`${baseUrl}${endpoint}`, {
    headers: { Authorization: options.apiKey },
    cache: "no-store",
    signal: AbortSignal.timeout(12_000),
  });
  if (!response.ok) {
    throw new Error(`Sectors request failed with status ${response.status}.`);
  }
  const body: unknown = await response.json();
  if (!Array.isArray(body)) throw new Error("Sectors returned an unexpected daily-data shape.");
  const points = body.filter((point): point is DailyPoint =>
    Boolean(point) && typeof point === "object" && typeof (point as DailyPoint).date === "string" && Number.isFinite((point as DailyPoint).close),
  );
  if (points.length < 2) throw new Error("Sectors returned insufficient daily observations.");
  return {
    symbol: normalized,
    points,
    origin: "sectors-live",
    endpoint,
    retrievedAt: now.toISOString(),
  };
}
