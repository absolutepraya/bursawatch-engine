/** Public navigation only: this module never reads or forwards credentials. */
export function configOrigin(value: string | undefined, production = false): string {
  if (!value?.trim()) {
    if (production) throw new Error("Set BURSAWATCH_CONFIG_URL to the HTTPS workspace origin.");
    return "http://localhost:3100";
  }
  let url: URL;
  try {
    url = new URL(value.trim());
  } catch {
    throw new Error("BURSAWATCH_CONFIG_URL must be an absolute HTTP(S) origin.");
  }
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash ||
    (url.protocol !== "https:" && !(url.protocol === "http:" && local && !production)) ||
    (production && local)
  ) {
    throw new Error(
      "BURSAWATCH_CONFIG_URL must be an HTTPS workspace origin without credentials, path, query or fragment; localhost is development-only.",
    );
  }
  return url.origin;
}

export type WorkspacePath =
  "/workspace" | "/app" | "/app/insights" | "/app/discover" | "/app/automations/new";

export function workspaceUrl(origin: string, path: WorkspacePath): string {
  if (
    !["/workspace", "/app", "/app/insights", "/app/discover", "/app/automations/new"].includes(path)
  ) {
    throw new Error("Unknown workspace destination.");
  }
  return new URL(path, origin).href;
}
