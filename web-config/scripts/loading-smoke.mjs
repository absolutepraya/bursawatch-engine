import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { setTimeout as delay } from "node:timers/promises";
import { chromium } from "playwright";
import { newProfile, validateWatcherConfig } from "../src/lib/watcher-fields.ts";

// Node 24. Use the isolated local server described in control-workspace-smoke.mjs.
// Auth and control requests are synthetic and intercepted before any network
// access. These checks never read live configuration or trigger a watcher.
const target = new URL(process.env.BURSAWATCH_TEST_URL ?? "http://127.0.0.1:3300");
assert.ok(["localhost", "127.0.0.1", "[::1]"].includes(target.hostname));
assert.ok(!target.username && !target.password, "Test URLs cannot contain credentials.");
const xId = "bursawatch-x-account-watch";
const instagramId = "bursawatch-ig-account-watch";
const sourceJobId = `${xId}-source`;
const ids = [
  xId,
  "bursawatch-ig-account-watch",
  "bursawatch-wa-channel-watch",
  "bursawatch-tg-market-news",
  "bursawatch-tg-kelas-investasi-gtw",
  "bursawatch-tg-phintraco-swing",
  "bursawatch-dc-swing-board",
];
const timestamp = new Date().toISOString();
const watchers = ids.map((watcher_id, index) => ({
  watcher_id,
  display_name: index === 0 ? "Synthetic X accounts" : `Synthetic workflow ${index}`,
  current_revision: 4,
  updated_at: timestamp,
}));
const profile = {
  ...newProfile("x"),
  id: "fixture_x",
  enabled: true,
  handle: "fixture_x",
  profile_url: "https://x.com/fixture_x",
  display_name: "Synthetic X account",
  twitter_emoji: "<:fixture:100000000000000003>",
  emoji: "<:fixture:100000000000000003>",
  discord_channels: [
    {
      key: "id_stocks_news",
      channel_id: "100000000000000001",
      description: "Synthetic company news",
    },
  ],
};
const snapshot = {
  api_version: 1,
  watcher_id: xId,
  revision: 4,
  config_version: 1,
  config_sha256: "a".repeat(64),
  updated_at: timestamp,
  config: { version: 1, profiles: [profile] },
};
assert.deepEqual(validateWatcherConfig(xId, snapshot.config), {});
const instagramSnapshot = {
  ...snapshot,
  watcher_id: instagramId,
  config: {
    version: 1,
    profiles: [
      {
        ...newProfile("instagram"),
        id: "fixture_ig",
        enabled: true,
        handle: "fixture_ig",
        profile_url: "https://instagram.com/fixture_ig",
        display_name: "Synthetic Instagram account",
        emoji: "<:fixture:100000000000000003>",
        discord_channels: profile.discord_channels,
      },
    ],
  },
};
assert.deepEqual(validateWatcherConfig(instagramId, instagramSnapshot.config), {});
const sourceJob = {
  job_id: sourceJobId,
  watcher_id: xId,
  display_name: "Synthetic source poller",
  schedule_kind: "interval",
  min_interval_seconds: 600,
  max_interval_seconds: 86400,
  schedule: {
    api_version: 1,
    job_id: sourceJobId,
    revision: 2,
    enabled: true,
    interval_seconds: 600,
    timezone: "Asia/Jakarta",
    schedule_sha256: "b".repeat(64),
    updated_at: timestamp,
  },
  reconciliation: { status: "applied", applied_revision: 2, effective: true },
};
const runs = [
  {
    run_id: "fixture-new-queue",
    watcher_id: xId,
    scheduler_job_id: `${xId}-queue-worker`,
    trigger: "queue",
    config_revision: 4,
    status: "ok",
    started_at: timestamp,
    finished_at: timestamp,
  },
  {
    run_id: "fixture-old-source",
    watcher_id: xId,
    scheduler_job_id: sourceJobId,
    trigger: "scheduled",
    config_revision: 3,
    status: "ok",
    started_at: new Date(Date.now() - 600_000).toISOString(),
    finished_at: new Date(Date.now() - 590_000).toISOString(),
  },
];
const user = {
  id: "00000000-0000-4000-8000-000000000004",
  aud: "authenticated",
  role: "authenticated",
  email: "loading-smoke@example.test",
  app_metadata: { provider: "email", providers: ["email"] },
  user_metadata: {},
  identities: [],
  created_at: "2026-01-01T00:00:00Z",
};
const password = "synthetic-loading-password";
const expiry = Math.floor(Date.now() / 1000) + 86400;
const encode = (value) => Buffer.from(JSON.stringify(value)).toString("base64url");
const token = `${encode({ alg: "HS256", typ: "JWT" })}.${encode({ sub: user.id, aud: "authenticated", role: "authenticated", exp: expiry, iat: expiry - 86400 })}.c3ludGhldGlj`;
const session = {
  access_token: token,
  token_type: "bearer",
  expires_in: 86400,
  expires_at: expiry,
  refresh_token: "synthetic-refresh-token",
  user,
};
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
});

async function fixture() {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: "reduce",
    serviceWorkers: "block",
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  const state = {
    calls: [],
    errors: [],
    unexpected: [],
    pending: [],
    pendingEvents: [],
    cancelledEvents: [],
    active: 0,
    maximum: 0,
    holdDetails: false,
    holdEvents: false,
    timelineAccessFailure: null,
    signedIn: false,
    closing: false,
  };
  page.on("pageerror", (error) => state.errors.push(error.message));
  page.on("requestfailed", (request) => {
    const url = new URL(request.url());
    if (url.origin === target.origin && /^\/api\/control\/runs\/[^/]+\/events$/.test(url.pathname))
      state.cancelledEvents.push(url.pathname.slice("/api/control/".length));
  });
  page.on("dialog", async (dialog) => {
    state.errors.push(`Unexpected ${dialog.type()} dialog.`);
    await dialog.dismiss();
  });
  await context.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const json = (body, status = 200) =>
      route.fulfill({
        status,
        json: body,
        headers: { "access-control-allow-origin": target.origin, "cache-control": "no-store" },
      });
    try {
      // Production bundles may contain a different public Supabase origin.
      // Fixed auth paths are fulfilled locally, never continued to a provider.
      if (url.protocol === "https:" && url.pathname.startsWith("/auth/v1/")) {
        if (method === "OPTIONS")
          return route.fulfill({
            status: 204,
            headers: {
              "access-control-allow-origin": target.origin,
              "access-control-allow-headers": "*",
              "access-control-allow-methods": "GET, POST, OPTIONS",
            },
          });
        if (url.pathname === "/auth/v1/token" && method === "POST") {
          const body = request.postDataJSON();
          assert.equal(body.email, user.email);
          assert.equal(body.password, password);
          state.signedIn = true;
          return json(session);
        }
        if (url.pathname === "/auth/v1/user" && method === "GET") return json(user);
      }
      if (url.origin === target.origin && url.pathname.startsWith("/api/control/")) {
        assert.equal(state.signedIn, true);
        assert.equal(request.headers().authorization, `Bearer ${token}`);
        assert.equal(method, "GET", "Loading checks must never write configuration.");
        const path = url.pathname.slice("/api/control/".length);
        state.calls.push(path);
        if (path === "watchers") return json(watchers);
        if (path === `watchers/${xId}/config`) return json(snapshot);
        if (path === `watchers/${instagramId}/config`) return json(instagramSnapshot);
        const timeline = /^runs\/([^/]+)\/events$/.exec(path);
        if (timeline) {
          if (state.timelineAccessFailure === "auth")
            return json({ code: "auth", message: "Your session has expired. Sign in again." }, 401);
          if (state.timelineAccessFailure === "forbidden")
            return json({ code: "forbidden", message: "Your account does not have access." }, 403);
          const body = [
            {
              run_id: timeline[1],
              event_id: `event-${timeline[1]}`,
              occurred_at: timestamp,
              level: "info",
              phase: "source",
              event_type: "source.fetch.completed",
              diagnostics: { profile_id: "fixture_source", items: 12, queued: 0 },
            },
            {
              run_id: timeline[1],
              event_id: `empty-${timeline[1]}`,
              occurred_at: timestamp,
              level: "warning",
              phase: "source",
              event_type: "source.fetch.completed",
              diagnostics: { profile_id: "fixture_empty", items: 0, queued: 0 },
            },
            {
              run_id: timeline[1],
              event_id: `unknown-${timeline[1]}`,
              occurred_at: timestamp,
              level: "info",
              phase: "source",
              event_type: "source.fetch.completed",
              diagnostics: { profile_id: "fixture_unknown" },
            },
            {
              run_id: timeline[1],
              event_id: `queued-${timeline[1]}`,
              occurred_at: timestamp,
              level: "info",
              phase: "source",
              event_type: "source.fetch.completed",
              diagnostics: { profile_id: "fixture_queued", items: 12, queued: 2 },
            },
            {
              run_id: timeline[1],
              event_id: `drain-${timeline[1]}`,
              occurred_at: timestamp,
              level: "info",
              phase: "delivery",
              event_type: "delivery.drain.completed",
              diagnostics: {
                delivered: 0,
                pending: 2,
                oldest_pending_minutes: 5,
                queue_only: true,
              },
            },
            {
              run_id: timeline[1],
              event_id: `failure-${timeline[1]}`,
              occurred_at: timestamp,
              level: "warning",
              phase: "source",
              event_type: "source.fetch.failed",
              diagnostics: { profile_id: "fixture_failed" },
            },
            {
              run_id: timeline[1],
              event_id: `start-${timeline[1]}`,
              occurred_at: timestamp,
              level: "info",
              phase: "lifecycle",
              event_type: "run.started",
              diagnostics: { dry_run: false, queue_only: false },
            },
          ];
          if (!state.holdEvents) return json(body);
          return await new Promise((resolve, reject) => {
            state.pendingEvents.push({
              path,
              release: async () => {
                try {
                  await json(body);
                  resolve();
                } catch (error) {
                  reject(error);
                }
              },
            });
          });
        }
        const match = /^watchers\/([^/]+)\/(jobs|runs)$/.exec(path);
        if (match && ids.includes(match[1])) {
          const [, id, resource] = match;
          const body = id === xId ? (resource === "jobs" ? [sourceJob] : runs) : [];
          if (!state.holdDetails) return json(body);
          state.active++;
          state.maximum = Math.max(state.maximum, state.active);
          return await new Promise((resolve, reject) => {
            state.pending.push({
              path,
              release: async (failure = false) => {
                state.active--;
                try {
                  await json(
                    failure
                      ? { code: "unavailable", message: "PRIVATE_FIXTURE_PROVIDER_DIAGNOSTIC" }
                      : body,
                    failure ? 503 : 200,
                  );
                  resolve();
                } catch (error) {
                  reject(error);
                }
              },
            });
          });
        }
      }
      // Only local documents/static assets pass through. Block API fallthrough,
      // mutations, remote assets and external URLs inside Next's image proxy.
      if (
        url.origin === target.origin &&
        ["GET", "HEAD"].includes(method) &&
        !url.pathname.startsWith("/api/")
      ) {
        if (url.pathname === "/_next/image")
          assert.match(url.searchParams.get("url") ?? "", /^\/(?:sources|brokers)\/[a-z0-9_.-]+$/i);
        return route.continue();
      }
      state.unexpected.push(`${method} ${url.origin}${url.pathname}`);
      return route.abort("blockedbyclient");
    } catch (error) {
      if (!state.closing) state.errors.push(error.message);
      await route.abort("failed").catch(() => {});
    }
  });
  const settle = () =>
    page.evaluate(
      () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
    );
  async function signIn() {
    await page.goto(`${target.origin}/workspace/settings`);
    await page.getByLabel("Email", { exact: true }).fill(user.email);
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.getByRole("heading", { name: "Account", exact: true }).waitFor();
    await settle();
  }
  async function verify() {
    assert.deepEqual(state.errors, [], "No browser/fixture errors are expected.");
    assert.deepEqual(state.unexpected, [], "Every auth/API/external request must be intercepted.");
  }
  async function close() {
    state.closing = true;
    await context.close();
  }
  return { page, state, signIn, settle, verify, close };
}

async function waitUntil(predicate, message) {
  const deadline = Date.now() + 10000;
  while (!predicate()) {
    assert.ok(Date.now() < deadline, message);
    await delay(20);
  }
}

async function demandDrivenReads() {
  const fixtureState = await fixture();
  const { page, state } = fixtureState;
  try {
    await fixtureState.signIn();
    assert.deepEqual(state.calls, [], "Account must not fetch workflow/status records.");
    const navigation = page.getByRole("navigation", { name: "Workspace navigation", exact: true });
    await navigation.getByRole("link", { name: "Workflows", exact: true }).click();
    await page.getByRole("heading", { name: "Workflows", exact: true }).waitFor();
    await fixtureState.settle();
    assert.deepEqual(state.calls, ["watchers"], "The workflow list needs only its catalog.");

    state.calls.length = 0;
    state.holdDetails = true;
    await page.getByRole("button", { name: /Open watcher details: Synthetic workflow 1/ }).click();
    await page.getByRole("heading", { name: "Watcher configuration", exact: true }).waitFor();
    await waitUntil(
      () => state.pending.length === 1,
      "Selected workflow schedule jobs were not requested.",
    );
    await fixtureState.settle();
    assert.deepEqual(
      [...state.calls].sort(),
      ["watchers", `watchers/${instagramId}/config`, `watchers/${instagramId}/jobs`].sort(),
      "A non-X editor needs catalog membership, configuration and its own jobs.",
    );
    assert.equal(state.active, 1, "Non-X detail must not request unrelated run history.");
    for (const item of state.pending.splice(0)) await item.release();
    state.holdDetails = false;
    await page.locator(".control-back").click();
    await page.getByRole("heading", { name: "Workflows", exact: true }).waitFor();
    await fixtureState.settle();
    state.calls.length = 0;
    state.holdDetails = true;
    await page.getByRole("button", { name: /Open watcher details: Synthetic X accounts/ }).click();
    await page.getByRole("heading", { name: "Watcher configuration", exact: true }).waitFor();
    await waitUntil(
      () => state.pending.length === 2,
      "Selected watcher status requests were not started.",
    );
    assert.equal(
      state.active,
      2,
      "The editor opens while both history and schedules are still pending.",
    );
    assert.deepEqual(
      [...state.calls].sort(),
      ["watchers", `watchers/${xId}/config`, `watchers/${xId}/jobs`, `watchers/${xId}/runs`].sort(),
      "Selecting X must not fetch other workflows' details.",
    );
    const diagnostic = page.getByRole("region", { name: "X → Discord checks", exact: true });
    await diagnostic.waitFor();
    assert.equal(await diagnostic.getByText("Checking…", { exact: true }).count(), 2);
    for (const item of state.pending.splice(0)) await item.release();
    await diagnostic.getByText("Every 10 minutes", { exact: true }).waitFor();
    await diagnostic.getByText(/No source-poll run using revision 4 is visible yet/).waitFor();
    const latest = diagnostic
      .locator("dl > div")
      .filter({ has: page.locator("dt", { hasText: "Latest source run" }) });
    assert.match(await latest.innerText(), /revision 3/);
    assert.doesNotMatch(
      await latest.innerText(),
      /revision 4/,
      "A newer queue run cannot prove that the saved revision was source-polled.",
    );
    await diagnostic.getByText("A post has not arrived?", { exact: true }).click();
    await diagnostic
      .getByText(/first successful nonempty poll establishes a starting point/)
      .waitFor();
    await diagnostic.getByText(/Relevance filtering can skip personal or test posts/).waitFor();
    await page.getByRole("button", { name: "Add account", exact: true }).click();
    const added = page.locator("details.watcher-profile").nth(1);
    await added.locator(":scope > summary").click();
    assert.equal(await added.getByLabel("Watch this source", { exact: true }).isChecked(), false);
    await added
      .getByText("This source is paused. It will not collect posts until you enable it and save.", {
        exact: true,
      })
      .waitFor();
    await fixtureState.verify();
    console.log(
      "PASS: Account/list reads, non-X editor scope, early X editor access, source-vs-queue evidence and paused onboarding.",
    );
  } finally {
    await fixtureState.close();
  }
}

async function progressiveLoading() {
  const fixtureState = await fixture();
  const { page, state } = fixtureState;
  try {
    await fixtureState.signIn();
    state.holdDetails = true;
    await page
      .getByRole("navigation", { name: "Workspace navigation", exact: true })
      .getByRole("link", { name: "Overview", exact: true })
      .click();
    await waitUntil(
      () => state.pending.length === 6,
      "Overview did not start six concurrent reads.",
    );
    const loading = page.getByRole("region", { name: "Loading status", exact: true });
    await loading.locator(".workspace-skeleton").waitFor();
    assert.equal(
      await loading.locator(".workspace-progress-spinner").count(),
      0,
      "Brief loads should start with a quiet skeleton.",
    );
    assert.equal(await loading.getByText("Request details", { exact: true }).count(), 0);
    await loading.locator(".workspace-progress-spinner").waitFor();
    assert.equal(
      await loading
        .locator(".workspace-progress-spinner")
        .evaluate((element) => getComputedStyle(element).animationName),
      "none",
      "Longer loading feedback must respect reduced motion.",
    );

    const first = state.pending.shift();
    await first.release(true);
    await waitUntil(
      () => state.calls.filter((path) => /\/(jobs|runs)$/.test(path)).length === 7,
      "A freed slot must start the next request while its earlier peers are still pending.",
    );
    assert.equal(state.active, 6);
    await loading.getByText("This is taking longer than usual", { exact: true }).waitFor();
    await loading.getByText("Request details", { exact: true }).waitFor();
    assert.equal(await loading.locator("details li").count(), ids.length * 2);
    await loading.getByText(/Schedule status could not be loaded/).waitFor();
    assert.doesNotMatch(
      await page.locator("body").innerText(),
      /PRIVATE_FIXTURE_PROVIDER_DIAGNOSTIC/,
      "Progress must expose safe recovery details, never arbitrary provider error content.",
    );
    assert.equal(
      await loading
        .locator("details")
        .evaluate((element) => Boolean(element.closest('[role="status"], [aria-live]'))),
      false,
      "Detailed logs must not repeatedly flood a screen reader's live region.",
    );
    await loading
      .getByRole("status")
      .getByText("This is taking longer than usual", { exact: true })
      .waitFor();

    await page.setViewportSize({ width: 375, height: 1000 });
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "200%";
    });
    await fixtureState.settle();
    const dimensions = await page.evaluate(() => ({
      width: innerWidth,
      content: document.documentElement.scrollWidth,
    }));
    assert.ok(
      dimensions.content <= dimensions.width,
      "Slow-load details must fit 375px at enlarged text size.",
    );
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "";
    });
    await page.setViewportSize({ width: 1440, height: 1000 });

    while (
      state.active > 0 ||
      state.calls.filter((path) => /\/(jobs|runs)$/.test(path)).length < ids.length * 2
    ) {
      await waitUntil(() => state.pending.length > 0, "Remaining status requests stalled.");
      await state.pending.shift().release();
    }
    await loading.waitFor({ state: "detached" });
    assert.equal(state.maximum, 6, "Status reads must never exceed six concurrent requests.");
    await page
      .getByRole("status")
      .filter({ hasText: /available records|incomplete/i })
      .waitFor();
    assert.doesNotMatch(
      await page.locator("body").innerText(),
      /PRIVATE_FIXTURE_PROVIDER_DIAGNOSTIC/,
    );
    await fixtureState.verify();
    console.log(
      "PASS: Six-request concurrency, progressive skeleton/spinner/details, safe failures and accessible mobile layout.",
    );
  } finally {
    await fixtureState.close();
  }
}

async function promptTimelines(accessFailure) {
  const fixtureState = await fixture();
  const { page, state } = fixtureState;
  try {
    await fixtureState.signIn();
    state.holdDetails = true;
    const directRun = "fixture-direct-run";
    await page.goto(`${target.origin}/workspace/history?run=${directRun}`);
    await page
      .getByRole("heading", { name: "source fetch completed", exact: true })
      .first()
      .waitFor();
    await fixtureState.settle();
    assert.deepEqual(
      state.calls,
      [`runs/${directRun}/events`],
      "Direct timelines request only their events, even if all histories would stall.",
    );
    assert.equal(state.pending.length, 0);
    assert.equal(
      await page.locator(".control-run-meta").count(),
      0,
      "An event read must not invent unavailable status, trigger or revision metadata.",
    );
    await page.getByText("Recorded events for this run.", { exact: true }).waitFor();
    const sourceEvent = page.locator(".control-timeline li").filter({ hasText: "fixture_source" });
    assert.match(await sourceEvent.innerText(), /Source ID\s+fixture_source/);
    assert.match(await sourceEvent.innerText(), /Items queued\s+0/);
    assert.match(await sourceEvent.innerText(), /Items were fetched, but none were queued/);
    assert.match(await sourceEvent.innerText(), /does not establish which reason applies/);
    const emptyEvent = page.locator(".control-timeline li").filter({ hasText: "fixture_empty" });
    assert.match(await emptyEvent.innerText(), /Items fetched\s+0/);
    assert.match(
      await emptyEvent.innerText(),
      /This fetch returned no items/,
    );
    assert.match(await emptyEvent.innerText(), /does not explain why it was empty/);
    const unknownEvent = page
      .locator(".control-timeline li")
      .filter({ hasText: "fixture_unknown" });
    assert.doesNotMatch(
      await unknownEvent.innerText(),
      /Items fetched|Items queued|returned no items|none were queued/,
    );
    assert.match(await unknownEvent.innerText(), /unavailable, not zero/);
    const queuedEvent = page.locator(".control-timeline li").filter({ hasText: "fixture_queued" });
    assert.match(await queuedEvent.innerText(), /Items queued\s+2/);
    assert.match(await queuedEvent.innerText(), /New items were queued for processing/);
    assert.match(await queuedEvent.innerText(), /does not confirm delivery to Discord/);
    const failedEvent = page
      .locator(".control-timeline li")
      .filter({ has: page.getByRole("heading", { name: "source fetch failed", exact: true }) });
    assert.match(await failedEvent.innerText(), /Source ID\s+fixture_failed/);
    assert.doesNotMatch(await failedEvent.innerText(), /Items fetched|Items queued/);
    const startedEvent = page
      .locator(".control-timeline li")
      .filter({ has: page.getByRole("heading", { name: "run started", exact: true }) });
    assert.match(await startedEvent.innerText(), /Dry run\s+No/);
    const deliveryEvent = page
      .locator(".control-timeline li")
      .filter({
        has: page.getByRole("heading", { name: "delivery drain completed", exact: true }),
      });
    assert.match(await deliveryEvent.innerText(), /Delivery count \(run total\)\s+0/);
    assert.match(await deliveryEvent.innerText(), /Analysis queue \(run total\)\s+2/);
    assert.match(await deliveryEvent.innerText(), /Oldest eligible queue item \(minutes\)\s+5/);
    await mkdir("test-results/run-diagnostics", { recursive: true });
    await page.screenshot({ path: "test-results/run-diagnostics/desktop.png", fullPage: true });
    await page.setViewportSize({ width: 375, height: 812 });
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "200%";
    });
    assert.ok(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      "Timeline diagnostics must fit enlarged mobile text.",
    );
    await page.screenshot({
      path: "test-results/run-diagnostics/mobile-enlarged.png",
      fullPage: true,
    });
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "";
    });
    await page.setViewportSize({ width: 1440, height: 1000 });
    assert.equal(
      await page.getByRole("note", { name: "Queue check, not a source poll" }).count(),
      0,
      "Without run metadata, event names must not be used to infer a queue-only run.",
    );
    await page
      .getByText(/Queue processing finished; there may have been nothing to send/)
      .waitFor();

    state.holdDetails = false;
    await page.locator(".control-back").click();
    await page.getByRole("heading", { name: "Run history", exact: true }).waitFor();
    state.calls.length = 0;
    state.holdDetails = true;
    await page
      .getByRole("button", { name: /^View run details: Synthetic X accounts/ })
      .first()
      .click();
    await page
      .getByRole("heading", { name: "source fetch completed", exact: true })
      .first()
      .waitFor();
    await fixtureState.settle();
    assert.deepEqual(
      state.calls,
      [`runs/${runs[0].run_id}/events`],
      "Opening a listed run must not refresh unrelated histories.",
    );
    assert.match(await page.locator(".control-run-meta").innerText(), /Completed/);
    assert.match(await page.locator(".control-run-meta").innerText(), /Queue/);
    const queueNote = page.getByRole("note", { name: "Queue check, not a source poll" });
    await queueNote.waitFor();
    assert.match(await queueNote.innerText(), /It did not fetch X/);
    assert.equal(
      await queueNote.getByRole("link", { name: "Check X source polling" }).getAttribute("href"),
      `/workspace/workflows?watcher=${xId}`,
    );
    await page
      .getByText("Synthetic X accounts · Configuration revision 4", { exact: true })
      .waitFor();

    state.holdDetails = false;
    await page.locator(".control-back").click();
    await page.getByRole("heading", { name: "Run history", exact: true }).waitFor();
    state.timelineAccessFailure = accessFailure;
    await page
      .getByRole("button", { name: /^View run details: Synthetic X accounts/ })
      .first()
      .click();
    await page
      .getByRole("alert")
      .getByText(
        accessFailure === "auth"
          ? "Your session has expired. Sign in again."
          : "Your account does not have access to this timeline.",
        { exact: true },
      )
      .waitFor();
    assert.equal(await page.locator(".control-run-meta").count(), 0);
    assert.equal(
      await page.getByRole("heading", { name: "Run timeline", exact: true }).count(),
      0,
      "Authentication or permission loss must clear existing private timeline records.",
    );
    await page
      .getByRole("alert")
      .getByRole("button", {
        name: accessFailure === "auth" ? "Sign in again" : "Try again",
        exact: true,
      })
      .waitFor();
    await fixtureState.verify();
    console.log(
      `PASS: Immediate direct timelines, no history fan-out, retained known metadata and ${accessFailure}-failure clearing.`,
    );
  } finally {
    await fixtureState.close();
  }
}

async function cancelledTimeline() {
  const fixtureState = await fixture();
  const { page, state } = fixtureState;
  try {
    await fixtureState.signIn();
    state.holdEvents = true;
    const eventPath = "runs/fixture-slow-run/events";
    await page.goto(`${target.origin}/workspace/history?run=fixture-slow-run`);
    await page.getByText("Loading timeline…", { exact: true }).waitFor();
    await waitUntil(() => state.pendingEvents.length === 1, "The timeline request did not start.");
    await page
      .getByRole("navigation", { name: "Workspace navigation", exact: true })
      .getByRole("link", { name: "Account", exact: true })
      .click();
    await page.getByRole("heading", { name: "Account", exact: true }).waitFor();
    await waitUntil(
      () => state.cancelledEvents.includes(eventPath),
      "Leaving a timeline must cancel its pending event request before the read deadline.",
    );
    assert.deepEqual(state.calls, [eventPath]);
    await state.pendingEvents.shift().release();
    await fixtureState.settle();
    assert.equal(
      await page.getByRole("heading", { name: "source fetch completed", exact: true }).count(),
      0,
    );
    assert.equal(
      await page.getByRole("alert").filter({ hasText: /\S/ }).count(),
      0,
      "A cancelled read must not show a stale error (empty live regions are allowed).",
    );
    await fixtureState.verify();
    console.log("PASS: Navigation aborts a pending timeline read and discards late results.");
  } finally {
    await fixtureState.close();
  }
}

try {
  await demandDrivenReads();
  await promptTimelines("auth");
  await promptTimelines("forbidden");
  await cancelledTimeline();
  await progressiveLoading();
} finally {
  await browser.close();
}
