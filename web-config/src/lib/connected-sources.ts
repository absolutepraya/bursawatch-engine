import { recommendedSources } from "./recommended-sources";

export type ConnectedSourceKind = "x" | "instagram" | "whatsapp";
export type PublicSource = (typeof recommendedSources)[number];
export type SourceSettingsLink = { label: string; href: string };

function profileHandle(kind: "x" | "instagram", value: string): string | undefined {
  const handle = value.trim().replace(/^@/, "");
  const pattern = kind === "x" ? /^[a-z0-9_]{1,15}$/i : /^[a-z0-9_][a-z0-9_.]{0,29}$/i;
  if (!pattern.test(handle) || handle.endsWith(".") || handle.includes("..")) return;
  return handle.toLowerCase();
}

function publicUrl(kind: ConnectedSourceKind, value: string): string | undefined {
  try {
    const url = new URL(value.trim());
    if (
      url.protocol !== "https:" ||
      url.username ||
      url.password ||
      url.port ||
      url.search ||
      url.hash
    )
      return;
    const host = url.hostname.toLowerCase();
    const path = url.pathname.replace(/\/$/, "");
    if (kind === "whatsapp") {
      if (
        !["whatsapp.com", "www.whatsapp.com"].includes(host) ||
        !/^\/channel\/[a-zA-Z0-9]{10,128}$/.test(path)
      )
        return;
      return `https://www.whatsapp.com${path}`;
    }
    const hosts =
      kind === "x"
        ? ["x.com", "www.x.com", "twitter.com", "www.twitter.com"]
        : ["instagram.com", "www.instagram.com"];
    if (!hosts.includes(host) || !/^\/[^/]+$/.test(path)) return;
    const handle = profileHandle(kind, path.slice(1));
    if (!handle) return;
    return kind === "x" ? `https://x.com/${handle}` : `https://www.instagram.com/${handle}`;
  } catch {
    return;
  }
}

/** Public identity decoration only: never infer an account from its internal ID or name. */
export function matchSourceIdentity(
  kind: ConnectedSourceKind,
  profile: unknown,
): PublicSource | undefined {
  if (!profile || typeof profile !== "object" || Array.isArray(profile)) return;
  const record = profile as Record<string, unknown>;
  const rawUrl = record[kind === "whatsapp" ? "channel_url" : "profile_url"];
  if (rawUrl != null && typeof rawUrl !== "string") return;
  const urlText = typeof rawUrl === "string" ? rawUrl.trim() : "";
  const url = urlText ? publicUrl(kind, urlText) : undefined;
  if (urlText && !url) return;
  if (kind === "whatsapp") {
    return url
      ? recommendedSources.find((source) => source.platform === kind && source.url === url)
      : undefined;
  }
  const rawHandle = record.handle;
  if (rawHandle != null && typeof rawHandle !== "string") return;
  const handleText = typeof rawHandle === "string" ? rawHandle.trim() : "";
  const handle = handleText ? profileHandle(kind, handleText) : undefined;
  if (handleText && !handle) return;
  const handleUrl = handle
    ? kind === "x"
      ? `https://x.com/${handle}`
      : `https://www.instagram.com/${handle}`
    : undefined;
  if (url && handleUrl && url !== handleUrl) return;
  const identity = url ?? handleUrl;
  return identity
    ? recommendedSources.find((source) => source.platform === kind && source.url === identity)
    : undefined;
}

const sourceSettings = {
  x: { watcherId: "bursawatch-x-account-watch", label: "Open X settings" },
  instagram: { watcherId: "bursawatch-ig-account-watch", label: "Open Instagram settings" },
  whatsapp: { watcherId: "bursawatch-wa-channel-watch", label: "Open WhatsApp settings" },
} as const;

function availableLink(
  target: { watcherId: string; label: string },
  watcherIds: readonly string[],
): SourceSettingsLink | undefined {
  return watcherIds.includes(target.watcherId)
    ? {
        label: target.label,
        href: `/workspace/workflows?watcher=${encodeURIComponent(target.watcherId)}`,
      }
    : undefined;
}

/** Links lead to shared configuration; catalog membership never proves a configured source. */
export function sourceSettingsLink(
  kind: ConnectedSourceKind,
  watcherIds: readonly string[],
): SourceSettingsLink | undefined {
  return availableLink(sourceSettings[kind], watcherIds);
}

export function brokerSettingsLinks(
  brokerId: string,
  watcherIds: readonly string[],
): SourceSettingsLink[] {
  const targets =
    brokerId === "bri-danareksa"
      ? [sourceSettings.whatsapp]
      : brokerId === "phintraco"
        ? [
            { watcherId: "bursawatch-tg-phintraco-swing", label: "Open swing settings" },
            { watcherId: "bursawatch-tg-market-news", label: "Open market news settings" },
          ]
        : [];
  return targets.flatMap((target) => {
    const link = availableLink(target, watcherIds);
    return link ? [link] : [];
  });
}
