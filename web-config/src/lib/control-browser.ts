import type { SupabaseClient } from "@supabase/supabase-js";

export class WorkspaceError extends Error {
  constructor(
    public code: string,
    message: string,
    public fields: string[] = [],
  ) {
    super(message);
  }
}

export function controlBrowser(client: SupabaseClient) {
  return async function request<T>(
    path: string,
    payload?: unknown,
    options: { signal?: AbortSignal; method?: "POST" } = {},
  ): Promise<T> {
    const writing = payload !== undefined || options.method === "POST";
    const controller = new AbortController();
    let timedOut = false;
    const interrupted = () =>
      writing
        ? new WorkspaceError(
            "unknown-outcome",
            "The save could not be confirmed. Reload the current settings before trying again.",
          )
        : timedOut
          ? new WorkspaceError(
              "timeout",
              "The workspace did not respond within 15 seconds. Try again.",
            )
          : new DOMException("The request was cancelled.", "AbortError");
    const cancel = () => controller.abort();
    options.signal?.addEventListener("abort", cancel, { once: true });
    if (options.signal?.aborted) controller.abort();
    const timer = setTimeout(
      () => {
        timedOut = true;
        controller.abort();
      },
      writing ? 25000 : 15000,
    );
    const checkCancelled = () => {
      if (controller.signal.aborted) throw interrupted();
    };
    let stopListening: (() => void) | undefined;
    try {
      checkCancelled();
      // Race the whole operation, including session restoration and response
      // decoding. A stalled auth lock must not leave the workspace loading forever.
      const cancelled = new Promise<never>((_, reject) => {
        const abort = () => reject(interrupted());
        controller.signal.addEventListener("abort", abort, { once: true });
        stopListening = () => controller.signal.removeEventListener("abort", abort);
      });
      return await Promise.race([perform(), cancelled]);
    } finally {
      clearTimeout(timer);
      stopListening?.();
      options.signal?.removeEventListener("abort", cancel);
    }

    async function perform(): Promise<T> {
      const sessionResult = await client.auth.getSession().catch(() => null);
      // Session restoration itself is not cancellable. Never start a later
      // request if the caller has left or the overall deadline has expired.
      checkCancelled();
      if (!sessionResult)
        throw new WorkspaceError("auth", "Your session could not be restored. Sign in again.");
      const { data, error } = sessionResult;
      if (error || !data.session)
        throw new WorkspaceError("auth", "Your session has expired. Sign in again.");
      let response: Response;
      try {
        response = await fetch(`/api/control/${path}`, {
          method: options.method ?? (writing ? "PUT" : "GET"),
          cache: "no-store",
          headers: {
            Authorization: `Bearer ${data.session.access_token}`,
            ...(writing ? { "Content-Type": "application/json" } : {}),
          },
          body: writing ? JSON.stringify(payload ?? {}) : undefined,
          signal: controller.signal,
        });
      } catch {
        checkCancelled();
        throw new WorkspaceError(
          writing ? "unknown-outcome" : "unavailable",
          !writing
            ? "Could not reach the workspace. Check your connection and try again."
            : "The save could not be confirmed. Reload the current settings before trying again.",
        );
      }
      const result = await response.json().catch(() => null);
      checkCancelled();
      if ((!response.ok && !result?.code) || result === null) {
        throw new WorkspaceError(
          writing ? "unknown-outcome" : "unavailable",
          !writing
            ? "The workspace returned an unreadable response. Refresh and try again."
            : "The save could not be confirmed. Reload the current settings before trying again.",
        );
      }
      if (!response.ok)
        throw new WorkspaceError(
          result.code,
          result.message ?? "The workspace could not complete this request.",
          Array.isArray(result.fields) ? result.fields : [],
        );
      return result as T;
    }
  };
}
