import { platforms, type Platform } from "./research-sources";

export function parseSourceFilters(params: Record<string, string | string[] | undefined>): {
  platform: Platform | "all";
  type: "all" | "people" | "firms";
} {
  const platform =
    typeof params.platform === "string" && Object.hasOwn(platforms, params.platform)
      ? (params.platform as Platform)
      : "all";
  // A specific social platform never sends someone to a brokerage-only list.
  const type =
    platform !== "all"
      ? "all"
      : params.type === "firms" || params.type === "people"
        ? params.type
        : "all";
  return { platform, type };
}
