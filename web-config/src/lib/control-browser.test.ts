import { afterEach, describe, expect, it, vi } from "vitest";
import type { SupabaseClient } from "@supabase/supabase-js";
import { controlBrowser } from "./control-browser";
const session = {
  auth: {
    getSession: vi.fn(async () => ({
      data: { session: { access_token: "synthetic-user-token" } },
      error: null,
    })),
  },
};
const client = session as unknown as SupabaseClient;
afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  vi.useRealTimers();
});
describe("browser control transport", () => {
  it("uses explicit POST for avatar refresh and never retries an uncertain response", async () => {
    const fetch = vi.fn(async () => new Response("unreadable", { status: 502 }));
    vi.stubGlobal("fetch", fetch);
    await expect(controlBrowser(client)("watchers/x/profiles/example/avatar/refresh", {}, { method: "POST" }))
      .rejects.toMatchObject({ code: "unknown-outcome" });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith("/api/control/watchers/x/profiles/example/avatar/refresh", expect.objectContaining({ method: "POST", body: "{}", cache: "no-store" }));
  });
  it("gets the current user's token and uses same-origin uncached requests", async () => {
    const fetch = vi.fn(async () => Response.json([]));
    vi.stubGlobal("fetch", fetch);
    await expect(controlBrowser(client)("watchers")).resolves.toEqual([]);
    expect(fetch).toHaveBeenCalledWith(
      "/api/control/watchers",
      expect.objectContaining({
        method: "GET",
        cache: "no-store",
        headers: { Authorization: "Bearer synthetic-user-token" },
      }),
    );
  });
  it.each([200, 502])(
    "never permits blind write retry after unreadable HTTP %s",
    async (status) => {
      const fetch = vi.fn(async () => new Response("unreadable upstream page", { status }));
      vi.stubGlobal("fetch", fetch);
      await expect(
        controlBrowser(client)("watchers/x/config", { config: {} }),
      ).rejects.toMatchObject({ code: "unknown-outcome" });
      expect(fetch).toHaveBeenCalledTimes(1);
    },
  );
  it("preserves sanitized validation paths and does not retry", async () => {
    const fetch = vi.fn(async () =>
      Response.json(
        { code: "validation", message: "Check these fields.", fields: ["profiles.0.username"] },
        { status: 422 },
      ),
    );
    vi.stubGlobal("fetch", fetch);
    await expect(controlBrowser(client)("watchers/x/config", {})).rejects.toMatchObject({
      code: "validation",
      fields: ["profiles.0.username"],
    });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("sanitizes authentication transport failures before any API request", async () => {
    session.auth.getSession.mockRejectedValueOnce(new Error("private-provider-detail"));
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await expect(controlBrowser(client)("watchers")).rejects.toMatchObject({
      code: "auth",
      message: "Your session could not be restored. Sign in again.",
    });
    expect(fetch).not.toHaveBeenCalled();
  });
  it("stops a stalled session restore at the read deadline without later sending a request", async () => {
    vi.useFakeTimers();
    let restore!: (value: Awaited<ReturnType<typeof session.auth.getSession>>) => void;
    session.auth.getSession.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          restore = resolve;
        }),
    );
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const result = controlBrowser(client)("watchers");
    const rejected = expect(result).rejects.toMatchObject({ code: "timeout" });
    await vi.advanceTimersByTimeAsync(15000);
    await rejected;
    restore({ data: { session: { access_token: "late-token" } }, error: null });
    await Promise.resolve();
    expect(fetch).not.toHaveBeenCalled();
  });
  it("uses one read deadline across session restoration, fetch and decoding", async () => {
    vi.useFakeTimers();
    session.auth.getSession.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          setTimeout(
            () => resolve({ data: { session: { access_token: "current-token" } }, error: null }),
            9000,
          );
        }),
    );
    const fetch = vi.fn(async () => ({ ok: true, json: () => new Promise(() => {}) }));
    vi.stubGlobal("fetch", fetch);
    const rejected = expect(controlBrowser(client)("watchers")).rejects.toMatchObject({
      code: "timeout",
    });
    await vi.advanceTimersByTimeAsync(14999);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await rejected;
  });
  it("cancels reads during session restoration with a sanitized AbortError", async () => {
    session.auth.getSession.mockImplementationOnce(() => new Promise(() => {}));
    const controller = new AbortController();
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const result = controlBrowser(client)("watchers", undefined, { signal: controller.signal });
    controller.abort(new Error("private-cancellation-reason"));
    await expect(result).rejects.toMatchObject({
      name: "AbortError",
      message: "The request was cancelled.",
    });
    expect(fetch).not.toHaveBeenCalled();
  });
  it("does not restore a session or fetch for an already cancelled request", async () => {
    const controller = new AbortController();
    controller.abort();
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await expect(
      controlBrowser(client)("watchers", undefined, { signal: controller.signal }),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(session.auth.getSession).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });
  it("aborts an active fetch when its caller leaves", async () => {
    const controller = new AbortController();
    let receivedSignal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) => {
        receivedSignal = init.signal ?? undefined;
        return new Promise<Response>(() => {});
      }),
    );
    const result = controlBrowser(client)("watchers", undefined, { signal: controller.signal });
    await Promise.resolve();
    await Promise.resolve();
    expect(receivedSignal?.aborted).toBe(false);
    controller.abort();
    await expect(result).rejects.toMatchObject({ name: "AbortError" });
    expect(receivedSignal?.aborted).toBe(true);
  });
  it.each(["timeout", "cancel"])("keeps %s writes uncertain and never retries", async (mode) => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const fetch = vi.fn(() => new Promise<Response>(() => {}));
    vi.stubGlobal("fetch", fetch);
    const result = controlBrowser(client)(
      "watchers/x/config",
      { config: {} },
      { signal: controller.signal },
    );
    const rejected = expect(result).rejects.toMatchObject({ code: "unknown-outcome" });
    await vi.advanceTimersByTimeAsync(15000);
    expect(fetch).toHaveBeenCalledTimes(1);
    if (mode === "cancel") controller.abort();
    else await vi.advanceTimersByTimeAsync(10000);
    await rejected;
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("reads current identity for each request and preserves a forbidden response", async () => {
    session.auth.getSession.mockResolvedValueOnce({
      data: { session: { access_token: "viewer-token" } },
      error: null,
    });
    const fetch = vi.fn(async () =>
      Response.json({ code: "forbidden", message: "Access denied." }, { status: 403 }),
    );
    vi.stubGlobal("fetch", fetch);
    await expect(controlBrowser(client)("watchers/x/config")).rejects.toMatchObject({
      code: "forbidden",
    });
    expect(fetch).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ headers: { Authorization: "Bearer viewer-token" } }),
    );
  });
});
