/** Invented chart fixtures. These are never represented as historical or live quotes. */
export const marketTimes = [
  "09:00",
  "09:20",
  "09:40",
  "10:00",
  "10:20",
  "10:40",
  "11:00",
  "11:20",
  "11:40",
  "13:30",
  "13:50",
  "14:10",
  "14:30",
  "14:50",
  "15:10",
  "15:30",
];

export const marketExamples = [
  {
    symbol: "BBRI",
    name: "Bank Rakyat Indonesia",
    shortName: "Bank Rakyat",
    prices: [
      4100, 4110, 4080, 4120, 4140, 4110, 4130, 4160, 4150, 4140, 4180, 4200, 4190, 4230, 4210,
      4240,
    ],
    context: "Review company results and the original research before drawing a conclusion.",
  },
  {
    symbol: "TLKM",
    name: "Telkom Indonesia",
    shortName: "Telkom",
    prices: [
      3250, 3260, 3240, 3250, 3270, 3280, 3260, 3270, 3260, 3280, 3290, 3270, 3290, 3280, 3300,
      3290,
    ],
    context: "A price change is one observation. Company announcements add context.",
  },
  {
    symbol: "BMRI",
    name: "Bank Mandiri",
    shortName: "Bank Mandiri",
    prices: [
      6100, 6125, 6100, 6150, 6125, 6175, 6200, 6175, 6225, 6200, 6250, 6300, 6275, 6325, 6300,
      6350,
    ],
    context: "A price move alone does not explain why a stock moved. Check the source.",
  },
];

export function changeFromOpen(price: number, open: number) {
  return ((price - open) / open) * 100;
}

export function formatMove(change: number) {
  return `${change >= 0 ? "+" : ""}${change.toFixed(1)}%`;
}

export function formatPrice(price: number) {
  return `Rp${new Intl.NumberFormat("en-US").format(price)}`;
}
