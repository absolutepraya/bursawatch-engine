export const WIB_TIME_ZONE = "Asia/Jakarta";

export function formatWib(value: string | Date, options?: Intl.DateTimeFormatOptions) {
  const date = value instanceof Date ? value : new Date(value);
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: WIB_TIME_ZONE,
    ...(options ?? {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }),
  }).format(date);
}

export function formatRelative(value: string, now = new Date()) {
  const delta = new Date(value).getTime() - now.getTime();
  const minutes = Math.round(Math.abs(delta) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return delta > 0 ? `in ${minutes} min` : `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return delta > 0 ? `in ${hours} hr` : `${hours} hr ago`;
  const days = Math.round(hours / 24);
  return delta > 0 ? `in ${days} days` : `${days} days ago`;
}

export function maskDestination(value: string) {
  const digits = value.replace(/\D/g, "");
  if (digits.length < 7) return "+62 ••••";
  const local = digits.startsWith("62") ? digits.slice(2) : digits.replace(/^0/, "");
  return `+62 ${local.slice(0, 3)} •••• ${local.slice(-4)}`;
}

export function normalizeTicker(value: string) {
  return value.trim().toUpperCase().replace(/\.JK$/, "");
}

export function classNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}
