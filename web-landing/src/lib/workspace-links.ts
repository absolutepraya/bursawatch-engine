import "server-only";
import { configOrigin, workspaceUrl } from "./config-url";

export function getWorkspaceLinks() {
  const origin = configOrigin(
    process.env.BURSAWATCH_CONFIG_URL,
    process.env.NODE_ENV === "production",
  );
  return {
    setup: workspaceUrl(origin, "/workspace"),
    home: workspaceUrl(origin, "/workspace"),
    discover: workspaceUrl(origin, "/app/discover"),
    createWatch: workspaceUrl(origin, "/workspace"),
  };
}
