import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { chromium } from "playwright";

// Start a separate local server with synthetic public settings:
// NEXT_PUBLIC_SUPABASE_URL=https://workspace-smoke.example.test \
// NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_workspace_smoke_fixture \
// npm run dev -- --hostname 127.0.0.1 --port 3300
// Then run: node scripts/control-workspace-smoke.mjs
// All auth and control requests are intercepted. This tests browser behavior,
// not real authentication, backend authorization, persistence or deployment.
const base = process.env.BURSAWATCH_TEST_URL ?? "http://127.0.0.1:3300";
const target = new URL(base);
assert.ok(
  ["localhost", "127.0.0.1", "[::1]"].includes(target.hostname),
  "Workspace smoke tests must target a local, isolated server.",
);
assert.ok(!target.username && !target.password, "Do not put credentials in the test URL.");

const watcherId = "bursawatch-tg-market-news";
const swingId = "bursawatch-tg-phintraco-swing";
const stockbitId = "bursawatch-stockbit-snips";
const jobId = "fixture-market-news";
const stockbitJobId = "fixture-stockbit-snips";
const password = "synthetic-only-password";
const screenshotDir = resolve("test-results/control-workspace");
await mkdir(screenshotDir, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
});

function fixtures() {
  const now = Date.now();
  const updatedAt = new Date(now).toISOString();
  const snapshot = {
    api_version: 1,
    watcher_id: watcherId,
    revision: 3,
    config_version: 1,
    config_sha256: "a".repeat(64),
    updated_at: updatedAt,
    config: {
      version: 1,
      providers: {
        phintraco: { telegram_username: "fixture_news" },
        tuntun: { telegram_username: "fixture_macro" },
      },
      destinations: {
        id_stocks_news_discord_channel_id: "111111111111111111",
        macro_news_discord_channel_id: "222222222222222222",
        industry_news_discord_channel_id: "333333333333333333",
        heartbeat_discord_channel_id: "444444444444444444",
      },
      additional_prompt_instruction: "Synthetic browser fixture only.",
    },
  };
  const job = {
    job_id: jobId,
    watcher_id: watcherId,
    display_name: "Market news check",
    schedule_kind: "interval",
    min_interval_seconds: 60,
    max_interval_seconds: 86400,
    schedule: {
      api_version: 1,
      job_id: jobId,
      revision: 2,
      enabled: true,
      interval_seconds: 3600,
      timezone: "Asia/Jakarta",
      schedule_sha256: "b".repeat(64),
      updated_at: updatedAt,
    },
    reconciliation: { status: "applied", applied_revision: 2, effective: true },
  };
  const stockbitSnapshot = {
    api_version: 1,
    watcher_id: stockbitId,
    revision: 1,
    config_version: 1,
    config_sha256: "c".repeat(64),
    updated_at: updatedAt,
    config: {
      version: 1,
      feeds: [
        { id: "stockbit_commentary", enabled: true },
        { id: "unboxing", enabled: true },
        { id: "unboxing_ipo", enabled: true },
        { id: "ai_reports_stockbit", enabled: true },
      ],
      destinations: {
        id_stocks_news_channel_id: "123456789012345678",
        macro_news_channel_id: "234567890123456789",
      },
      additional_prompt_instruction: "",
    },
  };
  const stockbitJob = {
    ...job,
    job_id: stockbitJobId,
    watcher_id: stockbitId,
    display_name: "Stockbit Snips check",
    min_interval_seconds: 300,
    max_interval_seconds: 3600,
    schedule: { ...job.schedule, job_id: stockbitJobId, revision: 1, interval_seconds: 900 },
    reconciliation: { status: "applied", applied_revision: 1, effective: true },
  };
  const watchers = [
    {
      watcher_id: watcherId,
      display_name: "Market news",
      current_revision: 3,
      updated_at: updatedAt,
    },
    {
      watcher_id: swingId,
      display_name: "Swing calls",
      current_revision: 1,
      updated_at: updatedAt,
    },
    {
      watcher_id: stockbitId,
      display_name: "Stockbit Snips",
      current_revision: 1,
      updated_at: updatedAt,
    },
  ];
  const runs = ["ok", "degraded", "failed", "blocked", "running"].map((status, index) => {
    const started = now - (index * 23 + 1) * 3_600_000;
    return {
      run_id: `fixture-run-${index}`,
      watcher_id: watcherId,
      scheduler_job_id: jobId,
      trigger: "schedule",
      config_revision: 3,
      status,
      started_at: new Date(started).toISOString(),
      finished_at: status === "running" ? null : new Date(started + 72000).toISOString(),
    };
  });
  return { snapshot, job, stockbitSnapshot, stockbitJob, watchers, runs };
}

async function scenario(role) {
  const state = fixtures();
  const adapterId = "bursawatch-tg-source-ingest";
  const component = (componentId, kind, displayName, relatedComponentIds, jobIds, configIds = []) => ({
    inventory_version: 1,
    component_id: componentId,
    kind,
    display_name: displayName,
    capabilities: [],
    pipeline_ids: [],
    config_resource_ids: configIds,
    related_component_ids: relatedComponentIds,
    job_ids: jobIds,
  });
  state.components = [
    component(adapterId, "source_adapter", "Telegram Source Inbox", [watcherId], [jobId]),
    component(watcherId, "domain_owner", "Market News", [adapterId], [jobId], [`watcher:${watcherId}`]),
    component(stockbitId, "domain_owner", "Stockbit Snips", [], [stockbitJobId], [`watcher:${stockbitId}`]),
  ];
  const operatorJob = (sourceJob, displayName, runtimeJobKey, componentIds, canEdit) => ({
    job_id: sourceJob.job_id,
    can_edit: canEdit,
    watcher_id: null,
    component_ids: componentIds,
    display_name: displayName,
    runtime_job_key: runtimeJobKey,
    schedule_kind: "interval",
    min_interval_seconds: sourceJob.min_interval_seconds,
    max_interval_seconds: sourceJob.max_interval_seconds,
    schedule: sourceJob.schedule,
    reconciliation: { ...sourceJob.reconciliation, has_error: false },
  });
  state.operatorJobs = [
    operatorJob(state.job, "Shared Telegram reader", "bursawatch-tg-source-ingest", [adapterId, watcherId], role === "admin"),
    operatorJob(state.stockbitJob, "Stockbit Snips check", "bursawatch-stockbit-snips", [stockbitId], role === "admin"),
  ];
  const observationFor = (job) => ({
    api_version: 1,
    identity_kind: "job",
    identity_id: job.job_id,
    observer_id: "vps-hermes-observer",
    observed_at: new Date().toISOString(),
    received_at: new Date().toISOString(),
    status: job.schedule.enabled ? "enabled" : "disabled",
    freshness: "fresh",
    evidence: {
      runtime_job_key: job.runtime_job_key,
      enabled: job.schedule.enabled,
      schedule: { kind: "interval", minutes: job.schedule.interval_seconds / 60 },
      last_execution: { at: new Date().toISOString(), status: "success" },
    },
    comparison: "match",
    desired: job.schedule,
    reconciliation: {
      status: job.reconciliation.status,
      applied_revision: job.reconciliation.applied_revision,
    },
  });
  state.observations = state.operatorJobs.map(observationFor);
  const syncOperatorJob = (id, sourceJob, observed = false) => {
    const operator = state.operatorJobs.find((item) => item.job_id === id);
    operator.schedule = sourceJob.schedule;
    operator.reconciliation = { ...sourceJob.reconciliation, has_error: false };
    const index = state.observations.findIndex((item) => item.identity_id === id);
    if (observed && index >= 0) state.observations[index] = observationFor(operator);
  };
  const sourceConfig = { selected_securities: [], people_org: [], endpoints: [], publisher_defaults: [], endpoint_overrides: [] };
  const sourceCatalog = {
    can_edit: role === "admin",
    securities: [],
    institutions: [{ id: "phintraco", name: "Phintraco Sekuritas", tier: 1, asset_ref: null }],
    people_org: [{ id: "x-ricky", name: "Ricky Ho", kind: null, tier: 3, asset_ref: null }],
    endpoints: [{ id: "x:ricky", publisher_id: "x-ricky", platform: "x", address: "rickyho", provider_id: null, credential_ref: null, system_owned: true, verified: true }],
    capabilities: [{ id: "company_news", label: "Company News", pipeline: "company_news", version: 1 }, { id: "macro_news", label: "Macro News", pipeline: "macro_news", version: 1 }, { id: "swing_chart_context", label: "Swing Chart Context", pipeline: "swing_chart_context", version: 1 }, { id: "trading_plans", label: "Trading Plans", pipeline: "swing_plan", version: 1 }],
    compatibility: [{ endpoint_id: "x:ricky", capability_id: "company_news", dispatch_group: "x_post_route" }, { endpoint_id: "x:ricky", capability_id: "macro_news", dispatch_group: "x_post_route" }, { endpoint_id: "x:ricky", capability_id: "swing_chart_context", dispatch_group: "x_post_route" }],
    config: { revision: 1, config: sourceConfig, sha256: "a".repeat(64), actor_id: "baseline", updated_at: new Date().toISOString() },
  };
  const effectiveCatalog = () => ({ revision: sourceCatalog.config.revision, updated_at: sourceCatalog.config.updated_at, selected_securities: [], subscriptions: [{ endpoint_id: "x:ricky", publisher_id: "x-ricky", platform: "x", address: "rickyho", provider_id: null, credential_ref: null, capability_id: "company_news", pipeline: "company_news", dispatch_group: "x_post_route", enabled: false, verification_status: "verified", settings: {}, source: "unset" }, { endpoint_id: "x:ricky", publisher_id: "x-ricky", platform: "x", address: "rickyho", provider_id: null, credential_ref: null, capability_id: "macro_news", pipeline: "macro_news", dispatch_group: "x_post_route", enabled: false, verification_status: "verified", settings: {}, source: "unset" }, { endpoint_id: "x:ricky", publisher_id: "x-ricky", platform: "x", address: "rickyho", provider_id: null, credential_ref: null, capability_id: "swing_chart_context", pipeline: "swing_chart_context", dispatch_group: "x_post_route", enabled: false, verification_status: "verified", settings: {}, source: "unset" }] });
  const writes = [];
  const attempts = [];
  const failures = { config: [], schedule: [] };
  const errors = [];
  const unexpectedRequests = [];
  let signedIn = false;
  let scheduleChecks = 0;
  let stockbitScheduleChecks = 0;
  let signouts = 0;
  let expectedDialog = null;
  const user = {
    id:
      role === "admin"
        ? "00000000-0000-4000-8000-000000000001"
        : "00000000-0000-4000-8000-000000000002",
    aud: "authenticated",
    role: "authenticated",
    email: `${role}@example.test`,
    app_metadata: { provider: "email", providers: ["email"] },
    user_metadata: {},
    identities: [],
    created_at: "2026-01-01T00:00:00Z",
  };
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
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: "reduce",
    serviceWorkers: "block",
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.text().includes("Multiple GoTrueClient instances"))
      errors.push("Navigation created concurrent Supabase auth clients.");
  });
  page.on("dialog", async (dialog) => {
    const expected = expectedDialog;
    expectedDialog = null;
    if (!expected) {
      errors.push(`Unexpected ${dialog.type()} dialog: ${dialog.message()}`);
      await dialog.dismiss();
      return;
    }
    try {
      assert.equal(dialog.type(), expected.type);
      assert.match(dialog.message(), expected.message);
      if (expected.accept) await dialog.accept();
      else await dialog.dismiss();
      expected.resolve();
    } catch (error) {
      await dialog.dismiss().catch(() => {});
      expected.reject(error);
    }
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
      if (url.pathname.startsWith("/auth/v1/")) {
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
          if (body.email !== user.email || body.password !== password)
            return json(
              { error_code: "invalid_credentials", msg: "Synthetic credentials rejected" },
              400,
            );
          signedIn = true;
          return json(session);
        }
        if (url.pathname === "/auth/v1/user" && method === "GET") return json(user);
        if (url.pathname === "/auth/v1/logout" && method === "POST") {
          signedIn = false;
          signouts++;
          return route.fulfill({
            status: 204,
            headers: { "access-control-allow-origin": target.origin },
          });
        }
        unexpectedRequests.push(`Unmocked auth operation: ${method} ${url.pathname}`);
        return json({ message: "Unmocked auth operation" }, 500);
      }
      if (url.origin === target.origin && url.pathname.startsWith("/api/control/")) {
        assert.equal(
          request.headers().authorization,
          `Bearer ${token}`,
          "Use the current synthetic user's access token.",
        );
        assert.equal(signedIn, true, "Control requests require a signed-in synthetic user.");
        const path = url.pathname.slice("/api/control/".length);
        if (method === "GET" && path === "components")
          return json({ inventory_version: 1, components: state.components });
        if (method === "GET" && path === "jobs") return json(state.operatorJobs);
        if (method === "GET" && path === "observations") return json(state.observations);
        const activityMatch = method === "GET" && path.match(/^components\/([^/]+)\/activity$/);
        if (activityMatch)
          return json({
            component_id: decodeURIComponent(activityMatch[1]),
            endpoints: [],
            pipelines: [],
            delivery_status: "not instrumented",
          });
        if (method === "GET" && path === "source-catalog") return json(sourceCatalog);
        if (method === "GET" && path === "source-catalog/effective") return json(effectiveCatalog());
        if (method === "PUT" && path === "source-catalog/config") {
          if (role === "viewer") return json({ code: "forbidden", message: "Admin access required." }, 403);
          const payload = request.postDataJSON();
          assert.equal(payload.expected_revision, sourceCatalog.config.revision);
          assert.ok(payload.config.people_org.every((item) => item.kind));
          assert.ok(payload.config.endpoint_overrides.every((item) => item.capability_id === "company_news"));
          writes.push({ resource: "source-catalog", payload });
          sourceCatalog.config = { ...sourceCatalog.config, revision: sourceCatalog.config.revision + 1, config: payload.config, updated_at: new Date().toISOString() };
          sourceCatalog.people_org.push(...payload.config.people_org.map((item) => ({ ...item, tier: 3 })));
          sourceCatalog.endpoints.push(...payload.config.endpoints.map((item) => ({ ...item, provider_id: null, verified: false, system_owned: false })));
          sourceCatalog.compatibility.push(...payload.config.endpoints.flatMap((item) => ["company_news", "macro_news", "swing_chart_context"].map((capability_id) => ({ endpoint_id: item.id, capability_id, dispatch_group: item.platform === "x" ? "x_post_route" : null }))));
          return json(sourceCatalog.config);
        }
        if (method === "GET" && path === "watchers") return json(state.watchers);
        if (method === "GET" && path === `watchers/${watcherId}/jobs`) return json([state.job]);
        if (method === "GET" && path === `watchers/${swingId}/jobs`) return json([]);
        if (method === "GET" && path === `watchers/${stockbitId}/jobs`) return json([state.stockbitJob]);
        if (method === "GET" && path === `watchers/${watcherId}/runs`) return json(state.runs);
        if (method === "GET" && path === `watchers/${swingId}/runs`) return json([]);
        if (method === "GET" && path === `watchers/${stockbitId}/runs`) return json([]);
        if (method === "GET" && /^runs\/fixture-run-\d\/events$/.test(path)) {
          const run = state.runs.find((item) => path.split("/")[1] === item.run_id);
          return json([
            {
              run_id: run.run_id,
              event_id: "fixture-event",
              occurred_at: run.started_at,
              level: "info",
              phase: "scan",
              event_type: "source_checked",
            },
          ]);
        }
        if (path === `watchers/${watcherId}/config`) {
          if (role === "viewer")
            return json(
              { code: "forbidden", message: "Configuration is restricted to administrators." },
              403,
            );
          if (method === "GET") return json(state.snapshot);
          if (method === "PUT") {
            const payload = request.postDataJSON();
            assert.equal(payload.expectedRevision, state.snapshot.revision);
            assert.equal(payload.config_version, 1);
            attempts.push({ resource: "config", payload });
            const failure = failures.config.shift();
            if (failure) return json(failure.body, failure.status);
            writes.push({ resource: "config", payload });
            state.snapshot = {
              ...state.snapshot,
              revision: state.snapshot.revision + 1,
              config: payload.config,
            };
            state.watchers[0].current_revision = state.snapshot.revision;
            return json(state.snapshot);
          }
        }
        if (path === `watchers/${stockbitId}/config`) {
          if (role === "viewer")
            return json({ code: "forbidden", message: "Configuration is restricted to administrators." }, 403);
          if (method === "GET") return json(state.stockbitSnapshot);
          if (method === "PUT") {
            const payload = request.postDataJSON();
            assert.equal(payload.expectedRevision, state.stockbitSnapshot.revision);
            assert.equal(payload.config_version, 1);
            attempts.push({ resource: "stockbit-config", payload });
            const failure = failures.config.shift();
            if (failure) return json(failure.body, failure.status);
            writes.push({ resource: "stockbit-config", payload });
            state.stockbitSnapshot = {
              ...state.stockbitSnapshot,
              revision: state.stockbitSnapshot.revision + 1,
              config: payload.config,
            };
            state.watchers[2].current_revision = state.stockbitSnapshot.revision;
            return json(state.stockbitSnapshot);
          }
        }
        if (path === `jobs/${jobId}/schedule`) {
          assert.equal(role, "admin", "Viewers must never submit a schedule write.");
          if (method === "PUT") {
            const payload = request.postDataJSON();
            assert.equal(payload.expectedRevision, state.job.schedule.revision);
            assert.equal(payload.timezone, "Asia/Jakarta");
            attempts.push({ resource: "schedule", payload });
            const failure = failures.schedule.shift();
            if (failure) return json(failure.body, failure.status);
            writes.push({ resource: "schedule", payload });
            state.job = {
              ...state.job,
              schedule: {
                ...state.job.schedule,
                revision: state.job.schedule.revision + 1,
                enabled: payload.enabled,
                interval_seconds: payload.interval_seconds,
              },
              reconciliation: {
                status: "pending",
                applied_revision: state.job.schedule.revision,
                effective: false,
              },
            };
            syncOperatorJob(jobId, state.job);
            return json(state.job);
          }
          if (method === "GET") {
            scheduleChecks++;
            state.job.reconciliation = {
              status: "applied",
              applied_revision: state.job.schedule.revision,
              effective: true,
            };
            syncOperatorJob(jobId, state.job, true);
            return json(state.job);
          }
        }
        if (path === `jobs/${stockbitJobId}/schedule`) {
          assert.equal(role, "admin");
          if (method === "PUT") {
            const payload = request.postDataJSON();
            assert.equal(payload.expectedRevision, state.stockbitJob.schedule.revision);
            attempts.push({ resource: "stockbit-schedule", payload });
            writes.push({ resource: "stockbit-schedule", payload });
            stockbitScheduleChecks = 0;
            state.stockbitJob = {
              ...state.stockbitJob,
              schedule: {
                ...state.stockbitJob.schedule,
                revision: state.stockbitJob.schedule.revision + 1,
                interval_seconds: payload.interval_seconds,
                enabled: payload.enabled,
              },
              reconciliation: {
                status: "pending",
                applied_revision: state.stockbitJob.schedule.revision,
                effective: false,
              },
            };
            syncOperatorJob(stockbitJobId, state.stockbitJob);
            return json(state.stockbitJob);
          }
          if (method === "GET") {
            stockbitScheduleChecks++;
            if (stockbitScheduleChecks > 1)
              state.stockbitJob.reconciliation = {
                status: "applied",
                applied_revision: state.stockbitJob.schedule.revision,
                effective: true,
              };
            syncOperatorJob(stockbitJobId, state.stockbitJob, true);
            return json(state.stockbitJob);
          }
        }
        unexpectedRequests.push(`Unmocked control operation: ${method} ${path}`);
        return json({ code: "unavailable", message: "Unmocked control operation" }, 500);
      }
      if (url.origin !== target.origin) {
        unexpectedRequests.push(`Blocked external request: ${method} ${url.origin}${url.pathname}`);
        return route.abort("blockedbyclient");
      }
      return route.continue();
    } catch (error) {
      errors.push(error.message);
      return json({ code: "unavailable", message: "Synthetic fixture assertion failed." }, 500);
    }
  });

  const navigation = page.getByRole("navigation", { name: "Workspace navigation", exact: true });
  const confirm = async (message, accept, action, type = "confirm") => {
    assert.equal(expectedDialog, null);
    let timeout;
    const result = new Promise((resolve, reject) => {
      expectedDialog = { message, accept, type, resolve, reject };
      timeout = setTimeout(
        () => reject(new Error(`Expected ${type} confirmation did not appear.`)),
        10000,
      );
    });
    try {
      await Promise.all([action(), result]);
    } finally {
      clearTimeout(timeout);
      expectedDialog = null;
    }
  };
  const capture = async (name) => {
    if (role !== "admin") return;
    await page.evaluate(() => document.fonts.ready);
    try {
      await page.waitForFunction(() =>
        [...document.images]
          .filter((image) => {
            const box = image.getBoundingClientRect();
            return (
              box.width > 0 &&
              box.height > 0 &&
              box.bottom > 0 &&
              box.top < innerHeight &&
              box.right > 0 &&
              box.left < innerWidth
            );
          })
          .every((image) => image.complete && image.naturalWidth > 0),
      );
    } catch (error) {
      const images = await page.evaluate(() =>
        [...document.images]
          .filter((image) => {
            const box = image.getBoundingClientRect();
            return box.width > 0 && box.height > 0 && box.bottom > 0 && box.top < innerHeight;
          })
          .map((image) => ({ src: image.currentSrc, complete: image.complete, width: image.naturalWidth })),
      );
      throw new Error(`Visible images failed to load in ${name}: ${JSON.stringify(images)}`, { cause: error });
    }
    const decodedImages = await page.evaluate(async () => {
      // Offscreen lazy images do not belong to these viewport captures and
      // must not hold them open waiting for a scroll that never occurs.
      const images = [...document.images].filter((image) => {
        const box = image.getBoundingClientRect();
        return (
          box.width > 0 &&
          box.height > 0 &&
          box.bottom > 0 &&
          box.top < innerHeight &&
          box.right > 0 &&
          box.left < innerWidth
        );
      });
      await Promise.all(images.map((image) => image.decode()));
      return images.length;
    });
    if (name.includes("source-library"))
      console.log(`${name}: ${decodedImages} visible source images loaded and decoded.`);
    await page.screenshot({
      path: resolve(screenshotDir, `synthetic-${name}.png`),
      fullPage: !name.includes("source-library"),
      animations: "disabled",
    });
  };
  const failNext = (resource, status, code, fields = []) => {
    const message = {
      validation: "The service did not accept this value. Review it and try again.",
      conflict:
        "These settings changed since you opened them. Reload the latest version before saving.",
      "unknown-outcome":
        "The save could not be confirmed. Reload the current settings before trying again.",
    }[code];
    failures[resource].push({ status, body: { code, message, fields } });
    return message;
  };
  const navigate = async (name, heading) => {
    await navigation.getByRole("link", { name, exact: true }).click();
    await page.getByRole("heading", { name: heading, exact: true }).waitFor();
  };
  const noOverflow = async (label) => {
    await page.evaluate(() => document.fonts.ready);
    const report = await page.evaluate(() => ({
      width: innerWidth,
      actual: document.documentElement.scrollWidth,
      textSize: document.documentElement.style.fontSize,
      overflowing: [...document.querySelectorAll("main *, .connected-navigation *")]
        .filter((element) => element.getBoundingClientRect().right > innerWidth + 1)
        .slice(0, 8)
        .map((element) => ({ tag: element.tagName, class: element.className })),
    }));
    assert.ok(report.actual <= report.width, `${label}: ${JSON.stringify(report)}`);
  };
  try {
    const documentResponse = await page.goto(`${target.origin}/workspace`);
    assert.equal(documentResponse.headers()["x-frame-options"], "DENY");
    assert.equal(documentResponse.headers()["referrer-policy"], "no-referrer");
    assert.ok(
      documentResponse.headers()["content-security-policy"].includes("frame-ancestors 'none'"),
    );
    await page.getByLabel("Email", { exact: true }).waitFor();
    await page.getByLabel("Email", { exact: true }).fill(user.email);
    await page.getByLabel("Password", { exact: true }).fill("invalid-synthetic-password");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "We couldn’t sign you in" }).waitFor();
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Show password", exact: true }).click();
    assert.equal(await page.getByLabel("Password", { exact: true }).getAttribute("type"), "text");
    await page.getByRole("button", { name: "Hide password", exact: true }).click();
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.getByRole("heading", { name: "Overview", exact: true }).waitFor();
    assert.equal(await navigation.getByRole("link").count(), 7);
    await page
      .getByText("Up to 50 latest runs per watcher. This range may be incomplete.", { exact: true })
      .waitFor();
    await noOverflow(`${role} desktop overview`);
    await capture("overview-desktop");
    await page.getByRole("radio", { name: "7 days", exact: true }).focus();
    await page.keyboard.press("ArrowLeft");
    assert.equal(
      await page.getByRole("radio", { name: "24 hours", exact: true }).isChecked(),
      true,
    );
    await page.getByText("View activity table", { exact: true }).click();
    assert.equal(await page.locator(".control-chart-table tbody tr").count(), 24);
    assert.equal(
      (await page.locator(".control-chart-table tbody td:first-of-type").allTextContents()).reduce(
        (total, count) => total + Number(count),
        0,
      ),
      1,
      "The trailing 24-hour chart must exclude older returned records.",
    );
    await page.getByRole("radio", { name: "24 hours", exact: true }).focus();
    await page.keyboard.press("ArrowRight");
    assert.equal(await page.getByRole("radio", { name: "7 days", exact: true }).isChecked(), true);
    assert.equal(await page.locator(".control-chart-table tbody tr").count(), 7);
    assert.equal(
      (await page.locator(".control-chart-table tbody td:first-of-type").allTextContents()).reduce(
        (total, count) => total + Number(count),
        0,
      ),
      state.runs.length,
    );
    await page.getByText("View activity table", { exact: true }).click();
    await navigate("History", "Run history");
    const runSearch = page.getByRole("searchbox", { name: "Search runs", exact: true });
    await page.getByLabel("Outcome", { exact: true }).selectOption("failed");
    await page.getByText("Showing 1 of 5 returned runs", { exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: /^View run details:/ }).count(), 1);
    await page.getByLabel("Workflow", { exact: true }).selectOption(swingId);
    await page.getByText("No runs match these filters", { exact: true }).waitFor();
    await page.getByRole("button", { name: "Clear filters", exact: true }).click();
    await runSearch.fill("fixture-run-2");
    await page.getByText("Showing 1 of 5 returned runs", { exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: /^View run details:/ }).count(), 1);
    await runSearch.fill("no matching run");
    await page.getByText("No runs match these filters", { exact: true }).waitFor();
    await page.getByRole("button", { name: "Clear filters", exact: true }).click();
    await page
      .getByRole("button", { name: /^View run details: Market news/ })
      .first()
      .click();
    await page.getByRole("heading", { name: "Run timeline", exact: true }).waitFor();
    await page.getByRole("heading", { name: "source checked", exact: true }).waitFor();
    await navigate("Sources", "Sources");
    await page.getByRole("heading", { name: "Source Catalog", exact: true }).waitFor();
    const securitiesTab = page.getByRole("tab", { name: "Securities", exact: true });
    const institutionsTab = page.getByRole("tab", { name: "Institutions", exact: true });
    const peopleTab = page.getByRole("tab", { name: "People & Org", exact: true });
    await page.getByText("No engine supported securities are available yet.", { exact: false }).waitFor();
    assert.equal(await page.getByRole("button", { name: "Add security" }).count(), 0);
    await securitiesTab.focus();
    await page.keyboard.press("ArrowRight");
    assert.equal(await institutionsTab.getAttribute("aria-selected"), "true");
    await page.getByRole("heading", { name: "Phintraco Sekuritas", exact: true }).waitFor();
    await page.keyboard.press("ArrowRight");
    assert.equal(await peopleTab.getAttribute("aria-selected"), "true");
    await page.getByRole("heading", { name: "Ricky Ho", exact: true }).waitFor();
    await capture("source-library-people-desktop");
    if (role === "viewer") {
      await page.getByText("View access. An admin can change source catalog settings.", { exact: true }).waitFor();
      assert.equal(await page.getByRole("group", { name: "Add People & Org identity" }).count(), 0);
      assert.equal(await page.getByRole("group", { name: "Add an endpoint for People & Org" }).count(), 0);
      assert.equal(await page.getByRole("button", { name: "Apply setting to draft" }).count(), 0);
      assert.equal(await page.getByRole("button", { name: "Save catalog" }).count(), 0);
      assert.equal(writes.filter((item) => item.resource === "source-catalog").length, 0);
    }
    if (role === "admin") {
      await page.getByRole("group", { name: "Add People & Org identity" }).getByLabel("Name").fill("Fixture Analyst");
      await page.getByRole("button", { name: "Add identity to draft" }).click();
      await page.getByRole("group", { name: "Add an endpoint for People & Org" }).getByLabel("Publisher").selectOption("fixture-analyst");
      await page.getByRole("group", { name: "Add an endpoint for People & Org" }).getByLabel("Canonical handle").fill("fixture_analyst");
      await page.getByRole("button", { name: "Add pending endpoint to draft" }).click();
      await page.getByRole("group", { name: "Capability setting" }).locator("select").nth(0).selectOption("x-fixture-analyst");
      assert.equal(await page.getByRole("group", { name: "Capability setting" }).locator("select").nth(1).locator("option").count(), 1, "Unsaved endpoints have no backend compatibility yet.");
      await page.getByRole("group", { name: "Capability setting" }).locator("select").nth(0).selectOption("x:ricky");
      assert.equal(await page.getByRole("group", { name: "Capability setting" }).locator("select").nth(1).getByRole("option", { name: "Trading Plans" }).count(), 0);
      assert.equal(await page.getByRole("group", { name: "Capability setting" }).locator("select").nth(1).getByRole("option", { name: "Swing Chart Context" }).count(), 1);
      await page.getByRole("group", { name: "Capability setting" }).locator("select").nth(1).selectOption("swing_chart_context");
      assert.equal(await page.getByRole("group", { name: "Capability setting" }).getByLabel("Enabled intent").isChecked(), false);
      await page.getByRole("group", { name: "Capability setting" }).locator("select").nth(1).selectOption("company_news");
      await page.getByRole("group", { name: "Capability setting" }).getByLabel("Enabled intent").check();
      await page.getByRole("button", { name: "Apply setting to draft" }).click();
      await page.getByRole("button", { name: "Save catalog" }).click();
      await page.getByText("Saved catalog", { exact: false }).waitFor();
      assert.equal(writes.filter((item) => item.resource === "source-catalog").length, 1);
      await page.reload();
      await page.getByRole("heading", { name: "Source Catalog", exact: true }).waitFor();
      await page.getByRole("tab", { name: "People & Org", exact: true }).click();
      await page.getByRole("heading", { name: "Fixture Analyst", exact: true }).waitFor();
      await page.getByRole("group", { name: "Capability setting" }).locator("select").nth(0).selectOption("x-fixture-analyst");
      await page.getByRole("group", { name: "Capability setting" }).locator("select").nth(1).selectOption("company_news");
      await page.getByText("pending", { exact: false }).first().waitFor();
    }
    await securitiesTab.click();
    await capture("source-library-desktop");
    await page.goto(`${target.origin}/workspace/workflows?tab=sources`);
    await page.waitForURL(`${target.origin}/workspace/sources`);
    await page.getByRole("heading", { name: "Source Catalog", exact: true }).waitFor();
    await navigate("Workflows", "Workflows");
    const workflowSearch = page.getByRole("searchbox", {
      name: "Search workflows",
      exact: true,
    });
    await workflowSearch.fill("stockbit");
    await page.getByText("Showing 1 of 3 workflows", { exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: /^Open watcher details:/ }).count(), 1);
    await page.getByLabel("Configuration", { exact: true }).selectOption("needs-setup");
    await page.getByText("No workflows match these filters", { exact: true }).waitFor();
    await page.getByRole("button", { name: "Clear filters", exact: true }).click();
    await page.getByText("Showing 3 of 3 workflows", { exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: /^Open watcher details:/ }).count(), 3);
    assert.equal(writes.filter((item) => item.resource !== "source-catalog").length, 0, "Browsing workflows must not write watcher configuration.");
    await page.getByRole("button", { name: /^Open watcher details: Market news/ }).click();
    await page.getByRole("heading", { name: "Market news", exact: true }).waitFor();
    if (role === "viewer") {
      await page.getByRole("heading", { name: "View access", exact: true }).waitFor();
      assert.equal(
        await page.getByRole("button", { name: "Save configuration", exact: true }).count(),
        0,
      );
    } else {
      const instructions = page.getByLabel("Additional instructions", { exact: true });
      const saveConfig = page.getByRole("button", { name: "Save configuration", exact: true });
      await instructions.fill("Draft awaiting server validation.");
      failNext("config", 422, "validation", ["config.additional_prompt_instruction"]);
      await saveConfig.click();
      await page
        .locator(".watcher-field-error")
        .filter({ hasText: "The service did not accept this value" })
        .waitFor();
      assert.equal(await instructions.inputValue(), "Draft awaiting server validation.");
      assert.equal(await instructions.getAttribute("aria-invalid"), "true");
      assert.equal(
        await saveConfig.isEnabled(),
        true,
        "Validation failures must allow a corrected retry.",
      );
      assert.equal(writes.filter((item) => item.resource !== "source-catalog").length, 0);
      await instructions.fill("Updated synthetic fixture instructions.");
      await saveConfig.click();
      await page
        .locator(".watcher-editor-header")
        .getByText("Revision 4 · Telegram market news", { exact: true })
        .waitFor();
      assert.equal(await instructions.inputValue(), "Updated synthetic fixture instructions.");
      for (const [status, code] of [
        [409, "conflict"],
        [502, "unknown-outcome"],
      ]) {
        const draft = `Preserved draft after ${status}.`;
        await instructions.fill(draft);
        const message = failNext("config", status, code);
        await saveConfig.click();
        await page.getByRole("alert").filter({ hasText: message }).waitFor();
        assert.equal(await instructions.inputValue(), draft);
        assert.equal(await instructions.isDisabled(), true);
        assert.equal(
          await saveConfig.isDisabled(),
          true,
          "Conflicts and uncertain writes must block repeat saves.",
        );
        await confirm(/Discard unsaved changes and reload/, false, () =>
          page.getByRole("button", { name: "Reload configuration", exact: true }).click(),
        );
        assert.equal(await instructions.inputValue(), draft);
        assert.equal(await saveConfig.isDisabled(), true);
        await confirm(/Discard unsaved changes and reload/, true, () =>
          page.getByRole("button", { name: "Reload configuration", exact: true }).click(),
        );
        await page
          .locator(".watcher-editor-header")
          .getByText("Revision 4 · Telegram market news", { exact: true })
          .waitFor();
        assert.equal(await instructions.inputValue(), "Updated synthetic fixture instructions.");
        assert.equal(
          await instructions.isEnabled(),
          true,
          "Reload must recover from the blocked editor.",
        );
      }
      assert.equal(attempts.filter((attempt) => attempt.resource === "config").length, 4);
      await capture("configuration-desktop");
      assert.equal(
        await page.getByRole("button", { name: "Save configuration", exact: true }).isDisabled(),
        true,
      );
      assert.equal(writes.filter((write) => write.resource === "config").length, 1);
      await page.reload();
      await page
        .locator(".watcher-editor-header")
        .getByText("Revision 4 · Telegram market news", { exact: true })
        .waitFor();
      assert.equal(await instructions.inputValue(), "Updated synthetic fixture instructions.");
      // Same-document Back/Forward does not fire beforeunload. Preserve the
      // signed-in user's draft in memory instead of silently losing it.
      await navigate("Workflows", "Workflows");
      await page.getByRole("button", { name: /^Open watcher details: Market news/ }).click();
      await instructions.fill("Retained through browser history.");
      await page.goBack();
      await page.getByRole("heading", { name: "Workflows", exact: true }).waitFor();
      await page.goForward();
      await instructions.waitFor();
      assert.equal(await instructions.inputValue(), "Retained through browser history.");
      await confirm(/Discard unsaved changes and reload/, true, () =>
        page.getByRole("button", { name: "Reload configuration", exact: true }).click(),
      );
      await page.waitForFunction(
        () =>
          document.querySelector(".watcher-editor textarea")?.value ===
          "Updated synthetic fixture instructions.",
      );
    }
    await noOverflow(`${role} desktop workflow details`);
    await navigate("Workflows", "Workflows");
    await page.getByRole("button", { name: /^Open watcher details: Stockbit Snips/ }).click();
    await page.getByRole("heading", { name: "Stockbit Snips", exact: true }).waitFor();
    await page.getByText("Four Stockbit Snips feeds", { exact: true }).waitFor();
    if (role === "admin") {
      const feedLabels = ["Stockbit Commentary", "Unboxing", "Unboxing IPO", "AI Reports Stockbit"];
      for (const label of feedLabels)
        assert.equal(await page.getByRole("checkbox", { name: label, exact: true }).count(), 1);
      for (const label of ["Stock news channel ID", "Macro news channel ID", "Additional instructions"])
        assert.equal(await page.getByLabel(label, { exact: true }).count(), 1);
      assert.equal(await page.getByLabel("Heartbeat channel ID", { exact: true }).count(), 0);
      const unboxing = page.getByRole("checkbox", { name: "Unboxing", exact: true });
      const instructions = page.getByLabel("Additional instructions", { exact: true });
      await unboxing.uncheck();
      await instructions.fill("Synthetic article guidance.");
      await page.getByRole("button", { name: "Save configuration", exact: true }).click();
      await page.getByText("Configuration saved as revision 2.", { exact: true }).waitFor();
      assert.deepEqual(writes.find((write) => write.resource === "stockbit-config").payload.config, {
        ...fixtures().stockbitSnapshot.config,
        feeds: [
          { id: "stockbit_commentary", enabled: true },
          { id: "unboxing", enabled: false },
          { id: "unboxing_ipo", enabled: true },
          { id: "ai_reports_stockbit", enabled: true },
        ],
        additional_prompt_instruction: "Synthetic article guidance.",
      });
      await instructions.fill("Stale synthetic draft.");
      const message = failNext("config", 409, "conflict");
      await page.getByRole("button", { name: "Save configuration", exact: true }).click();
      await page.getByRole("alert").filter({ hasText: message }).waitFor();
      assert.equal(await instructions.inputValue(), "Stale synthetic draft.");
      assert.equal(await page.getByRole("button", { name: "Save configuration", exact: true }).isDisabled(), true);
      await confirm(/Discard unsaved changes and reload/, true, () =>
        page.getByRole("button", { name: "Reload configuration", exact: true }).click(),
      );
      await page.getByText("Revision 2 · Stockbit Snips", { exact: true }).waitFor();
      assert.equal(await instructions.inputValue(), "Synthetic article guidance.");
      await noOverflow("admin desktop Stockbit editor");
      await capture("stockbit-configuration-desktop");
    } else {
      await page.getByRole("heading", { name: "View access", exact: true }).waitFor();
    }
    await navigate("Workflows", "Workflows");
    await page.getByRole("button", { name: /^Open watcher details: Market news/ }).click();
    await page.getByRole("heading", { name: "Market news", exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "Save schedule", exact: true }).count(), 0);
    assert.equal(
      await page.getByRole("link", { name: "Shared Telegram reader", exact: true }).getAttribute("href"),
      "/workspace/jobs#job-fixture-market-news",
    );
    await page.getByRole("link", { name: "Shared Telegram reader", exact: true }).click();
    await page.waitForURL(`${target.origin}/workspace/jobs#job-fixture-market-news`);
    await page.getByRole("heading", { name: "Jobs", exact: true }).waitFor();
    const marketJob = page.locator("#job-fixture-market-news");
    await marketJob.getByRole("heading", { name: "Shared Telegram reader", exact: true, level: 2 }).waitFor();
    if (role === "viewer") {
      await page
        .locator("#job-fixture-market-news")
        .getByText("You have view access. An administrator can change this schedule.", {
          exact: true,
        })
        .waitFor();
      assert.equal(
        await marketJob.getByRole("button", { name: "Save schedule", exact: true }).count(),
        0,
      );
    } else {
      const interval = marketJob.getByLabel("Check every (minutes)", { exact: true });
      const saveSchedule = marketJob.getByRole("button", { name: "Save schedule", exact: true });
      await interval.fill("45");
      failNext("schedule", 422, "validation", ["interval_seconds"]);
      await saveSchedule.click();
      await page
        .locator(".watcher-field-error")
        .filter({ hasText: "The service did not accept this value" })
        .waitFor();
      assert.equal(await interval.inputValue(), "45");
      assert.equal(await saveSchedule.isEnabled(), true);
      await marketJob.getByLabel("Check every (minutes)", { exact: true }).fill("30");
      await marketJob.getByRole("button", { name: "Save schedule", exact: true }).click();
      await page
        .locator("#job-fixture-market-news .watcher-schedule .watcher-draft-status")
        .getByText("Pending", { exact: true })
        .waitFor();
      assert.equal(
        await marketJob.getByRole("button", { name: "Save schedule", exact: true }).isDisabled(),
        true,
      );
      await page
        .getByText("Revision 3 is applied. This job is enabled.", { exact: true })
        .waitFor();
      assert.equal(
        await marketJob.getByLabel("Check every (minutes)", { exact: true }).inputValue(),
        "30",
      );
      assert.ok(scheduleChecks >= 1, "Applied status must follow a separate scheduler response.");
      assert.equal(
        writes.find((write) => write.resource === "schedule").payload.interval_seconds,
        1800,
      );
      await interval.fill("40");
      const message = failNext("schedule", 409, "conflict");
      await saveSchedule.click();
      await page.getByRole("alert").filter({ hasText: message }).waitFor();
      assert.equal(await interval.inputValue(), "40");
      assert.equal(await interval.isDisabled(), true);
      assert.equal(await saveSchedule.isDisabled(), true);
      await marketJob.getByRole("button", { name: "Refresh status", exact: true }).click();
      await page
        .getByRole("alert")
        .filter({ hasText: "Status refreshed. Reload this editor" })
        .waitFor();
      assert.equal(
        await interval.inputValue(),
        "40",
        "A status refresh must preserve the blocked draft.",
      );
      assert.equal(await saveSchedule.isDisabled(), true);
      await confirm(/Discard your draft and load/, false, () =>
        marketJob.getByRole("button", { name: "Reload schedule", exact: true }).click(),
      );
      assert.equal(await interval.inputValue(), "40");
      await confirm(/Discard your draft and load/, true, () =>
        marketJob.getByRole("button", { name: "Reload schedule", exact: true }).click(),
      );
      await page
        .locator("#job-fixture-market-news")
        .getByRole("button", { name: "Reload schedule", exact: true })
        .waitFor({ state: "hidden" });
      await page.waitForFunction(() => {
        const input = document.querySelector('.watcher-schedule input[type="number"]');
        return input && !input.matches(":disabled") && input.value === "30";
      });
      await page
        .getByText("Revision 3 is applied. This job is enabled.", { exact: true })
        .waitFor();
      assert.equal(await interval.inputValue(), "30");
      await capture("schedules-desktop");
      await interval.fill("42");
      await page.goBack();
      await page.getByRole("heading", { name: "Market news", exact: true }).waitFor();
      state.job.schedule.revision += 1;
      state.job.reconciliation.applied_revision = state.job.schedule.revision;
      syncOperatorJob(jobId, state.job, true);
      await page.goForward();
      await interval.waitFor();
      assert.equal(
        await interval.inputValue(),
        "42",
        "Back/Forward must preserve a schedule draft.",
      );
      assert.equal(
        await saveSchedule.isDisabled(),
        true,
        "Restored drafts based on an older revision must not save.",
      );
      await confirm(/Discard your draft and load/, true, () =>
        marketJob.getByRole("button", { name: "Reload schedule", exact: true }).click(),
      );
      await page.waitForFunction(() => {
        const input = document.querySelector('.watcher-schedule input[type="number"]');
        return input && !input.matches(":disabled") && input.value === "30";
      });
      await navigate("Workflows", "Workflows");
      await page.getByRole("button", { name: /^Open watcher details: Stockbit Snips/ }).click();
      await page.getByRole("heading", { name: "Stockbit Snips", exact: true }).waitFor();
      assert.equal(await page.getByRole("button", { name: "Save schedule", exact: true }).count(), 0);
      await page.getByRole("link", { name: "Stockbit Snips check", exact: true }).click();
      await page.getByRole("heading", { name: "Jobs", exact: true }).waitFor();
      const stockbitJob = page.locator("#job-fixture-stockbit-snips");
      await stockbitJob.getByRole("heading", { name: "Stockbit Snips check", exact: true, level: 2 }).waitFor();
      await stockbitJob.getByText("Revision 1 is applied. This job is enabled.", { exact: true }).waitFor();
      const stockbitInterval = stockbitJob.getByLabel("Check every (minutes)", { exact: true });
      assert.equal(await stockbitInterval.inputValue(), "15");
      await stockbitInterval.fill("4");
      await stockbitJob.getByRole("button", { name: "Save schedule", exact: true }).click();
      assert.equal(writes.filter((write) => write.resource === "stockbit-schedule").length, 0);
      await stockbitInterval.fill("20");
      await stockbitJob.getByRole("button", { name: "Save schedule", exact: true }).click();
      await stockbitJob.getByText("Revision 2 is applied. This job is enabled.", { exact: true }).waitFor();
      assert.equal(writes.find((write) => write.resource === "stockbit-schedule").payload.interval_seconds, 1200);
      await navigate("Workflows", "Workflows");
      await page.getByRole("button", { name: /^Open watcher details: Market news/ }).click();
      await page.getByRole("heading", { name: "Market news", exact: true }).waitFor();
    }
    for (const textSize of ["100%", "200%"]) {
      await page.setViewportSize({ width: 375, height: 900 });
      await page.evaluate((size) => {
        document.documentElement.style.fontSize = size;
      }, textSize);
      await navigate("Jobs", "Jobs");
      await noOverflow(`${role} ${textSize} jobs`);
      if (textSize === "100%") await capture("jobs-375");
      await navigate("Overview", "Overview");
      await noOverflow(`${role} ${textSize} overview`);
      await capture(textSize === "100%" ? "overview-375" : "overview-375-text-200");
      await page.getByText("View activity table", { exact: true }).click();
      await noOverflow(`${role} ${textSize} activity table`);
      await page.getByText("View activity table", { exact: true }).click();
      await navigate("History", "Run history");
      await noOverflow(`${role} ${textSize} history`);
      await navigate("Workflows", "Workflows");
      await navigate("Sources", "Sources");
      await page.getByRole("heading", { name: "Source Catalog", exact: true }).waitFor();
      await noOverflow(`${role} ${textSize} Securities library`);
      await capture(textSize === "100%" ? "source-library-375" : "source-library-375-text-200");
      await page.getByRole("tab", { name: "People & Org", exact: true }).click();
      await noOverflow(`${role} ${textSize} People library`);
      await navigate("Workflows", "Workflows");
      await page.getByRole("button", { name: /^Open watcher details: Market news/ }).click();
      await page
        .getByRole("heading", {
          name: role === "admin" ? "Watcher configuration" : "View access",
          exact: true,
        })
        .waitFor();
      await noOverflow(`${role} ${textSize} workflow details`);
      if (textSize === "100%") await capture("configuration-375");
      await navigate("Workflows", "Workflows");
      await page.getByRole("button", { name: /^Open watcher details: Stockbit Snips/ }).click();
      await page.getByRole("heading", { name: "Stockbit Snips", exact: true }).waitFor();
      await noOverflow(`${role} ${textSize} Stockbit editor`);
      if (role === "admin") {
        const feedLabels = ["Stockbit Commentary", "Unboxing", "Unboxing IPO", "AI Reports Stockbit"];
        for (const label of feedLabels)
          assert.equal(await page.getByRole("checkbox", { name: label, exact: true }).count(), 1);
        for (const label of ["Stock news channel ID", "Macro news channel ID", "Additional instructions"])
          assert.equal(await page.getByLabel(label, { exact: true }).count(), 1);
        assert.equal(await page.getByLabel("Heartbeat channel ID", { exact: true }).count(), 0);
        if (textSize === "100%") {
          const expectedConfig = {
            version: 1,
            feeds: [
              { id: "stockbit_commentary", enabled: false },
              { id: "unboxing", enabled: true },
              { id: "unboxing_ipo", enabled: false },
              { id: "ai_reports_stockbit", enabled: false },
            ],
            destinations: {
              id_stocks_news_channel_id: "345678901234567890",
              macro_news_channel_id: "456789012345678901",
            },
            additional_prompt_instruction: "Mobile synthetic guidance.",
          };
          for (const feed of expectedConfig.feeds) {
            const label = {
              stockbit_commentary: "Stockbit Commentary",
              unboxing: "Unboxing",
              unboxing_ipo: "Unboxing IPO",
              ai_reports_stockbit: "AI Reports Stockbit",
            }[feed.id];
            await page.getByRole("checkbox", { name: label, exact: true }).setChecked(feed.enabled);
          }
          await page.getByLabel("Stock news channel ID", { exact: true }).fill(expectedConfig.destinations.id_stocks_news_channel_id);
          await page.getByLabel("Macro news channel ID", { exact: true }).fill(expectedConfig.destinations.macro_news_channel_id);
          const mobileInstruction = page.getByLabel("Additional instructions", { exact: true });
          await mobileInstruction.fill(expectedConfig.additional_prompt_instruction);
          const mobileSave = page.getByRole("button", { name: "Save configuration", exact: true });
          await noOverflow("admin 375px Stockbit edited form");
          await mobileSave.click();
          await page.getByText("Configuration saved as revision 3.", { exact: true }).waitFor();
          const mobileWrite = writes.filter((write) => write.resource === "stockbit-config").at(-1);
          assert.equal(mobileWrite.payload.config_version, 1);
          assert.equal(mobileWrite.payload.expectedRevision, 2);
          assert.deepEqual(mobileWrite.payload.config, expectedConfig);
          await mobileInstruction.fill("Stale mobile synthetic draft.");
          const staleMessage = failNext("config", 409, "conflict");
          await mobileSave.click();
          await page.getByRole("alert").filter({ hasText: staleMessage }).waitFor();
          assert.equal(await mobileInstruction.inputValue(), "Stale mobile synthetic draft.");
          assert.equal(await mobileSave.isDisabled(), true);
          await confirm(/Discard unsaved changes and reload/, false, () =>
            page.getByRole("button", { name: "Reload configuration", exact: true }).click(),
          );
          assert.equal(await mobileInstruction.inputValue(), "Stale mobile synthetic draft.");
          await confirm(/Discard unsaved changes and reload/, true, () =>
            page.getByRole("button", { name: "Reload configuration", exact: true }).click(),
          );
          await page.getByText("Revision 3 · Stockbit Snips", { exact: true }).waitFor();
          assert.equal(await mobileInstruction.inputValue(), expectedConfig.additional_prompt_instruction);
          assert.equal(await page.getByLabel("Stock news channel ID", { exact: true }).inputValue(), expectedConfig.destinations.id_stocks_news_channel_id);
          assert.equal(await page.getByLabel("Macro news channel ID", { exact: true }).inputValue(), expectedConfig.destinations.macro_news_channel_id);
          for (const feed of expectedConfig.feeds) {
            const label = {
              stockbit_commentary: "Stockbit Commentary",
              unboxing: "Unboxing",
              unboxing_ipo: "Unboxing IPO",
              ai_reports_stockbit: "AI Reports Stockbit",
            }[feed.id];
            assert.equal(await page.getByRole("checkbox", { name: label, exact: true }).isChecked(), feed.enabled);
          }
          await noOverflow("admin 375px Stockbit saved form");
          await capture("stockbit-configuration-375");
        }
      }
      await navigate("Account", "Account");
      await page.getByText(user.email, { exact: true }).waitFor();
      await noOverflow(`${role} ${textSize} account`);
      await navigate("Workflows", "Workflows");
      await page.getByRole("button", { name: /^Open watcher details: Stockbit Snips/ }).click();
      await page.getByRole("heading", { name: "Stockbit Snips", exact: true }).waitFor();
      assert.equal(await page.getByRole("button", { name: "Save schedule", exact: true }).count(), 0);
      await page.getByRole("link", { name: "Stockbit Snips check", exact: true }).click();
      await page.getByRole("heading", { name: "Jobs", exact: true }).waitFor();
      const mobileStockbitJob = page.locator("#job-fixture-stockbit-snips");
      await mobileStockbitJob.getByRole("heading", { name: "Stockbit Snips check", exact: true, level: 2 }).waitFor();
      if (role === "admin") {
        const mobileInterval = mobileStockbitJob.getByLabel("Check every (minutes)", { exact: true });
        const expectedRevision = textSize === "100%" ? 2 : 3;
        await mobileStockbitJob.getByText(`Revision ${expectedRevision} is applied. This job is enabled.`, { exact: true }).waitFor();
        assert.equal(await mobileInterval.inputValue(), textSize === "100%" ? "20" : "25");
        assert.equal(await mobileInterval.getAttribute("min"), "5");
        assert.equal(await mobileInterval.getAttribute("max"), "60");
        if (textSize === "100%") {
          await mobileInterval.fill("25");
          await mobileStockbitJob.getByRole("button", { name: "Save schedule", exact: true }).click();
          await page.locator(".watcher-schedule .watcher-draft-status").getByText("Pending", { exact: true }).waitFor();
          await mobileStockbitJob.getByText("Revision 3 is applied. This job is enabled.", { exact: true }).waitFor();
          const mobileScheduleWrite = writes.filter((write) => write.resource === "stockbit-schedule").at(-1);
          assert.equal(mobileScheduleWrite.payload.expectedRevision, 2);
          assert.equal(mobileScheduleWrite.payload.interval_seconds, 1500);
        }
        await noOverflow(`${role} ${textSize} Stockbit schedule`);
      } else {
        assert.match(await mobileStockbitJob.locator(".operator-job-evidence").innerText(), /Enabled · every 15 minutes/);
        assert.match(await mobileStockbitJob.locator(".operator-job-evidence").innerText(), /every 15 minutes/);
      }
      await navigate("Workflows", "Workflows");
      await page.getByRole("button", { name: /^Open watcher details: Market news/ }).click();
      await page.getByRole("heading", { name: "Market news", exact: true }).waitFor();
    }
    const signOut = () =>
      page
        .locator(".connected-navigation")
        .getByRole("button", { name: "Sign out", exact: true })
        .click();
    if (role === "admin") {
      await navigate("Jobs", "Jobs");
      const marketJob = page.locator("#job-fixture-market-news");
      await marketJob.getByLabel("Check every (minutes)", { exact: true }).fill("45");
      await confirm(/Discard unsaved changes and sign out/, false, signOut);
      assert.equal(signouts, 0);
      assert.equal(
        await marketJob.getByLabel("Check every (minutes)", { exact: true }).inputValue(),
        "45",
      );
      await confirm(/Discard unsaved changes and sign out/, true, signOut);
    } else await signOut();
    await page.getByRole("button", { name: "Sign in", exact: true }).waitFor();
    await noOverflow(`${role} 200% sign-in`);
    await page.reload();
    await page.getByRole("button", { name: "Sign in", exact: true }).waitFor();
    assert.equal(signouts, 1);
    if (role === "viewer") assert.deepEqual(writes, []);
    assert.deepEqual(failures, { config: [], schedule: [] });
    assert.deepEqual(unexpectedRequests, [], "No request may escape fixture coverage.");
    assert.deepEqual(errors, [], "The browser and synthetic API fixture must remain error-free.");
    console.log(
      `${role}: mocked sign-in, overview/history, permissions, schedules, sign-out and 375px/200% layouts passed${role === "admin" ? "; config revision and pending→applied schedule verified" : ""}.`,
    );
  } catch (error) {
    console.error("Synthetic browser diagnostics:", { errors, unexpectedRequests });
    await page.screenshot({ path: resolve(screenshotDir, `synthetic-${role}-failure.png`) }).catch(() => {});
    throw error;
  } finally {
    await context.close();
  }
}

try {
  await scenario("viewer");
  await scenario("admin");
  console.log(
    "Control workspace smoke passed using synthetic auth and API fixtures; no real backend calls or writes.",
  );
  console.log(`Synthetic review screenshots: ${screenshotDir}`);
} finally {
  await browser.close();
}
