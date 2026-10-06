import "server-only";
import { configOrigin, workspaceUrl } from "./config-url";

export function getWorkspaceLinks() {
  const origin = configOrigin(
    process.env.BURSAWATCH_CONFIG_URL,
    process.env.NODE_ENV === "production",
  );
  return {
    /** The authenticated workspace; it handles sign-in itself. */
    workspace: workspaceUrl(origin, "/workspace"),
    /** The sample workspace: no sign-in, data stays in the browser. */
    demo: workspaceUrl(origin, "/app"),
  };
}
