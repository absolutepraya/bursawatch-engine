import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { chromium } from "playwright";
import { newProfile, validateWatcherConfig } from "../src/lib/watcher-fields.ts";

// Node 24. Run against an isolated local server with the synthetic public
// settings documented in control-workspace-smoke.mjs. Every auth/API request
// is intercepted; this does not verify production access or change a backend.
const target = new URL(process.env.BURSAWATCH_TEST_URL ?? "http://127.0.0.1:3300");
assert.ok(["localhost", "127.0.0.1", "[::1]"].includes(target.hostname));
assert.ok(!target.username && !target.password, "Test URLs cannot contain credentials.");
const password = "synthetic-source-editor-password";
const emoji = "<:fixture:100000000000000003>";
const channel = "100000000000000001";
const updatedChannel = "100000000000000004";
const addedChannel = "100000000000000005";
const ids = {
  x: "bursawatch-x-account-watch",
  instagram: "bursawatch-ig-account-watch",
  whatsapp: "bursawatch-wa-channel-watch",
  gtw: "bursawatch-tg-kelas-investasi-gtw",
  board: "bursawatch-dc-swing-board",
};
const names = {
  x: "Synthetic X accounts",
  instagram: "Synthetic Instagram accounts",
  whatsapp: "Synthetic WhatsApp channels",
  gtw: "Synthetic GTW bundles",
  board: "Synthetic swing board",
};
const futureRoot = { fixture: "preserve-root", flags: [true, { version: 7 }] };
const futureProfile = { fixture: "preserve-profile", nested: [1, 2] };
const futureRoute = { fixture: "preserve-route" };
const publicChannel = "https://www.whatsapp.com/channel/0029VbAjdnb60eBhwVdJxj1c";

function sourceFixture(kind) {
  const profile = {
    ...newProfile(kind),
    id: "kutekians", // An internal ID alone must never select a public avatar.
    enabled: true,
    display_name: `Synthetic ${kind} source`,
    emoji,
    future_profile: structuredClone(futureProfile),
    discord_channels: [
      {
        key: "id_stocks_news",
        channel_id: channel,
        description: "Synthetic company news",
        future_route: structuredClone(futureRoute),
      },
    ],
  };
  if (kind === "whatsapp")
    Object.assign(profile, {
      mode: "forward",
      channel_jid: "synthetic_source@newsletter",
      channel_url: publicChannel,
    });
  else
    Object.assign(profile, {
      handle: kind === "x" ? "Kutekians" : "avenirresearch.id",
      profile_url:
        kind === "x" ? "https://x.com/Kutekians" : "https://instagram.com/avenirresearch.id",
      ...(kind === "x" ? { twitter_emoji: emoji } : {}),
    });
  if (kind === "whatsapp") {
    // WA v2 has an exact shape; unknown-field preservation is exercised by X/IG.
    delete profile.future_profile;
    delete profile.discord_channels[0].future_route;
    return { version: 2, profiles: [profile] };
  }
  return { version: 1, profiles: [profile], future_root: structuredClone(futureRoot) };
}

const timestamp = new Date().toISOString();
const snapshots = new Map(
  Object.entries(ids).map(([kind, watcher_id]) => {
    const config = ["x", "instagram", "whatsapp"].includes(kind)
      ? sourceFixture(kind)
      : {
          version: 1,
          future_root: structuredClone(futureRoot),
          destinations: {
            heartbeat_discord_channel_id: "100000000000000002",
            future_destination: { fixture: "preserve-destination" },
            ...(kind === "gtw" ? { alert_discord_channel_id: channel } : {}),
          },
          ...(kind === "gtw"
            ? {
                source: {
                  telegram_username: "fixture_gtw",
                  telegram_channel_id: 123456789,
                  future_source: "preserve",
                },
                additional_prompt_instruction: "Synthetic GTW guidance.",
              }
            : {}),
        };
    assert.deepEqual(
      validateWatcherConfig(watcher_id, config),
      {},
      `${kind} fixture must be valid.`,
    );
    return [
      watcher_id,
      {
        api_version: 1,
        watcher_id,
        revision: 3,
        config_version: config.version,
        config,
        config_sha256: "a".repeat(64),
        updated_at: timestamp,
      },
    ];
  }),
);
const watchers = Object.entries(ids).map(([kind, watcher_id]) => ({
  watcher_id,
  display_name: names[kind],
  current_revision: 3,
  updated_at: timestamp,
}));
const user = {
  id: "00000000-0000-4000-8000-000000000011",
  aud: "authenticated",
  role: "authenticated",
  email: "source-editor@example.test",
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
const screenshotDir = resolve("test-results/source-editor");
const errors = [];
const unexpectedRequests = [];
const writes = [];
const configReads = [];
let signedIn = false;
let expectedDialog = null;
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  reducedMotion: "reduce",
  serviceWorkers: "block",
});
const page = await context.newPage();
page.setDefaultTimeout(15000);
page.on("pageerror", (error) => errors.push(error.message));
page.on("dialog", async (dialog) => {
  const expected = expectedDialog;
  expectedDialog = null;
  if (!expected) {
    errors.push(`Unexpected ${dialog.type()} dialog.`);
    await dialog.dismiss();
    return;
  }
  try {
    assert.equal(dialog.type(), "confirm");
    assert.match(dialog.message(), expected.message);
    await dialog.accept();
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
    // NEXT_PUBLIC settings can be baked into a production bundle. Fulfill
    // these fixed auth endpoints locally regardless of its Supabase origin;
    // never continue an auth request to the network.
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
        signedIn = true;
        return json(session);
      }
      if (url.pathname === "/auth/v1/user" && method === "GET") return json(user);
    }
    if (url.origin === target.origin && url.pathname.startsWith("/api/control/")) {
      assert.equal(signedIn, true);
      assert.equal(request.headers().authorization, `Bearer ${token}`);
      const path = url.pathname.slice("/api/control/".length);
      if (method === "GET" && path === "components")
        return json({ inventory_version: 1, components: [] });
      if (method === "GET" && (path === "jobs" || path === "observations")) return json([]);
      if (method === "GET" && path === "watchers") return json(watchers);
      const match = /^watchers\/([^/]+)\/(jobs|runs|config)$/.exec(path);
      if (match && snapshots.has(match[1])) {
        const [, id, resource] = match;
        if (method === "GET" && resource !== "config") return json([]);
        if (method === "GET") {
          configReads.push(id);
          return json(snapshots.get(id));
        }
        if (method === "PUT" && resource === "config") {
          const previous = snapshots.get(id);
          const payload = request.postDataJSON();
          assert.deepEqual(Object.keys(payload).sort(), [
            "config",
            "config_version",
            "expectedRevision",
          ]);
          assert.equal(payload.expectedRevision, previous.revision);
          assert.equal(payload.config_version, previous.config_version);
          assert.deepEqual(
            validateWatcherConfig(id, payload.config),
            {},
            "Invalid source draft must not reach PUT.",
          );
          writes.push({ id, payload: structuredClone(payload) });
          const next = { ...previous, revision: previous.revision + 1, config: payload.config };
          snapshots.set(id, next);
          watchers.find((watcher) => watcher.watcher_id === id).current_revision = next.revision;
          return json(next);
        }
      }
    }
    // Only app documents and static assets can reach the local server. No
    // unmatched API, mutation, external URL or external image proxy can escape.
    if (
      url.origin === target.origin &&
      ["GET", "HEAD"].includes(method) &&
      !url.pathname.startsWith("/api/")
    ) {
      if (url.pathname === "/_next/image") {
        const image = url.searchParams.get("url") ?? "";
        assert.match(image, /^\/(?:sources|brokers)\/[a-z0-9_.-]+$/i);
      }
      return route.continue();
    }
    unexpectedRequests.push(`${method} ${url.origin}${url.pathname}`);
    return route.abort("blockedbyclient");
  } catch (error) {
    errors.push(error.message);
    return json({ code: "unavailable", message: "Synthetic assertion failed." }, 500);
  }
});

async function confirm(message, action) {
  assert.equal(expectedDialog, null);
  let timeout;
  const result = new Promise((resolve, reject) => {
    expectedDialog = { message, resolve, reject };
    timeout = setTimeout(() => reject(new Error("Expected confirmation did not appear.")), 10000);
  });
  try {
    await Promise.all([action(), result]);
  } finally {
    clearTimeout(timeout);
    expectedDialog = null;
  }
}
const profiles = page.locator("details.watcher-profile");
async function openProfile(index) {
  const profile = profiles.nth(index);
  await profile.waitFor();
  if ((await profile.getAttribute("open")) === null)
    await profile.locator(":scope > summary").click();
  return profile;
}
async function openWorkflow(kind) {
  await page.goto(`${target.origin}/workspace/workflows?watcher=${ids[kind]}`);
  await page.getByRole("heading", { name: names[kind], exact: true }).waitFor();
  await page.getByRole("heading", { name: "Watcher configuration", exact: true }).waitFor();
  assert.ok(
    configReads.includes(ids[kind]),
    "Editors must read their real configuration endpoint.",
  );
  await page.getByRole("region", { name: "Workflow capabilities", exact: true }).waitFor();
}
async function save(kind, expectedConfig) {
  const count = writes.length;
  const revision = snapshots.get(ids[kind]).revision + 1;
  await page.getByRole("button", { name: "Save configuration", exact: true }).click();
  await page
    .getByRole("status")
    .filter({ hasText: `Configuration saved as revision ${revision}.` })
    .waitFor();
  assert.equal(writes.length, count + 1, "A save must issue exactly one PUT.");
  assert.equal(writes.at(-1).id, ids[kind]);
  assert.deepEqual(
    writes.at(-1).payload.config,
    expectedConfig,
    "Whole-config saves must preserve every unedited field.",
  );
}
async function captureX() {
  await mkdir(screenshotDir, { recursive: true });
  await page.evaluate(() => document.fonts.ready);
  const notification = page.getByRole("button", { name: "Dismiss notification", exact: true });
  if (await notification.isVisible()) await notification.click();
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.evaluate(() => window.scrollTo(0, 0));
    const dimensions = await page.evaluate(() => ({
      width: innerWidth,
      content: document.documentElement.scrollWidth,
    }));
    assert.ok(dimensions.content <= dimensions.width, `X editor overflows at ${width}px.`);
    await page.screenshot({
      path: resolve(screenshotDir, `synthetic-x-editor-${width}.png`),
      fullPage: true,
      animations: "disabled",
    });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
}
async function assertAvatar(profile, expectedPath) {
  const image = profile.locator(".watcher-source-avatar img");
  if (!expectedPath) {
    await image.waitFor({ state: "detached" });
    return;
  }
  await image.waitFor();
  const src = new URL(await image.getAttribute("src"), target.origin);
  assert.equal(src.origin, target.origin, "Profile images must remain local assets.");
  assert.equal(
    src.pathname === "/_next/image" ? src.searchParams.get("url") : src.pathname,
    expectedPath,
  );
  await page.waitForFunction(
    (path) =>
      [...document.querySelectorAll(".watcher-source-avatar img")].some((image) => {
        const src = new URL(image.currentSrc || image.src, location.origin);
        return (
          (src.searchParams.get("url") ?? src.pathname) === path &&
          image.complete &&
          image.naturalWidth > 0
        );
      }),
    expectedPath,
  );
}

async function socialEditor(kind) {
  await openWorkflow(kind);
  let profile = await openProfile(0);
  const expected = structuredClone(snapshots.get(ids[kind]).config);
  const original = expected.profiles[0];
  await assertAvatar(
    profile,
    kind === "x"
      ? "/sources/kutekians.png"
      : kind === "whatsapp"
        ? "/brokers/brids-logo.png"
        : null,
  );
  if (kind === "x") {
    const count = writes.length;
    await profile.getByLabel("Account handle", { exact: true }).fill("fixture_unknown");
    await assertAvatar(profile, null);
    await profile.getByLabel("Profile URL", { exact: true }).fill("https://x.com/fixture_unknown");
    await assertAvatar(profile, null); // A known internal ID/display name is insufficient.
    await profile.getByLabel("Account handle", { exact: true }).fill(original.handle);
    await profile.getByLabel("Profile URL", { exact: true }).fill(original.profile_url);
    await assertAvatar(profile, "/sources/kutekians.png");
    assert.equal(writes.length, count, "Identity edits cannot save themselves.");
  }
  assert.equal(
    await profile.getByRole("button", { name: "Remove source", exact: true }).isDisabled(),
    kind !== "whatsapp",
  );
  const displayName = `Edited synthetic ${kind} source`;
  await profile.getByLabel("Display name", { exact: true }).fill(displayName);
  await profile.getByLabel("Discord channel ID", { exact: true }).fill(updatedChannel);
  await profile.getByLabel("Summarize posts", { exact: true }).uncheck();
  await profile
    .getByLabel("Additional instructions", { exact: true })
    .fill("Only synthetic source editor guidance.");
  Object.assign(original, {
    display_name: displayName,
    enable_llm_summary: false,
    additional_prompt_instruction: "Only synthetic source editor guidance.",
  });
  original.discord_channels[0].channel_id = updatedChannel;
  await save(kind, expected);
  if (kind === "x") await captureX();

  const beforeAdd = writes.length;
  await page
    .getByRole("button", { name: kind === "whatsapp" ? "Add channel" : "Add account", exact: true })
    .click();
  profile = await openProfile(1);
  assert.equal(writes.length, beforeAdd, "Adding a source must remain an unsaved draft.");
  const added = newProfile(kind);
  Object.assign(added, {
    id: `added_${kind}`,
    display_name: `Synthetic added ${kind}`,
    emoji,
    discord_channels: [
      { key: "id_stocks_news", channel_id: addedChannel, description: "Stock news" },
    ],
  });
  await profile.getByLabel("Profile ID", { exact: true }).fill(added.id);
  await profile.getByLabel("Display name", { exact: true }).fill(added.display_name);
  await profile.getByLabel("Discord channel ID", { exact: true }).fill(addedChannel);
  if (kind === "whatsapp") {
    Object.assign(added, {
      channel_jid: "synthetic_added@newsletter",
      channel_url: "https://www.whatsapp.com/channel/SyntheticFixture12345",
    });
    await profile
      .getByLabel("WhatsApp channel identifier", { exact: true })
      .fill(added.channel_jid);
    await profile.getByLabel("Channel URL", { exact: true }).fill(added.channel_url);
  } else {
    Object.assign(added, {
      handle: "fixture_added",
      profile_url: `https://${kind === "x" ? "x.com" : "instagram.com"}/fixture_added`,
    });
    await profile.getByLabel("Account handle", { exact: true }).fill(added.handle);
    await profile.getByLabel("Profile URL", { exact: true }).fill(added.profile_url);
  }
  await profile.getByText("Processing and appearance", { exact: true }).click();
  await profile.getByLabel("Source emoji", { exact: true }).fill(emoji);
  if (kind === "x") {
    added.twitter_emoji = emoji;
    await profile.getByLabel("X platform emoji", { exact: true }).fill(emoji);
  }
  expected.profiles.push(added);
  await save(kind, expected);
  profile = await openProfile(1);
  const beforeRemove = writes.length;
  await confirm(/Remove this source from the draft/, () =>
    profile.getByRole("button", { name: "Remove source", exact: true }).click(),
  );
  assert.equal(await profiles.count(), 1);
  assert.equal(writes.length, beforeRemove, "Removing a source must remain an unsaved draft.");
  expected.profiles.pop();
  await save(kind, expected);
  profile = await openProfile(0);
  assert.equal(
    await profile.getByRole("button", { name: "Remove source", exact: true }).isDisabled(),
    kind !== "whatsapp",
  );
  if (kind === "whatsapp") {
    await confirm(/Remove this source from the draft/, () =>
      profile.getByRole("button", { name: "Remove source", exact: true }).click(),
    );
    expected.profiles = [];
    await save(kind, expected);
    assert.equal(await profiles.count(), 0, "WhatsApp permits an empty configured source list.");
  }
  console.log(
    `${kind}: local identity, source edit/add/remove, revisioned PUT and unknown-field preservation passed.`,
  );
}

async function whatsappModes() {
  const config = sourceFixture("whatsapp");
  const observed = {
    ...structuredClone(config.profiles[0]),
    id: "fixture_observe",
    channel_jid: "synthetic_observe@newsletter",
    channel_url: "https://www.whatsapp.com/channel/SyntheticObserve12345",
    display_name: "Synthetic observed channel",
    mode: "observe",
    emoji: null,
    discord_channels: [],
    forward_media: false,
    enable_llm_title: false,
    enable_llm_summary: false,
    enable_llm_routing: false,
    enable_llm_relevance_filter: false,
  };
  config.profiles.push(observed);
  snapshots.set(ids.whatsapp, {
    ...snapshots.get(ids.whatsapp),
    config_version: 2,
    config,
  });
  await openWorkflow("whatsapp");
  let profile = await openProfile(1);
  assert.equal(await profile.getByLabel("Channel mode", { exact: true }).inputValue(), "observe");
  await profile.getByLabel("Display name", { exact: true }).fill("Edited observed channel");
  const expected = structuredClone(config);
  expected.profiles[1].display_name = "Edited observed channel";
  await save("whatsapp", expected);
  // Changing modes must not silently discard existing Discord routing or flags.
  profile = await openProfile(0);
  const count = writes.length;
  await profile.getByLabel("Channel mode", { exact: true }).selectOption("observe");
  assert.equal(
    await profile.getByLabel("Discord channel ID", { exact: true }).inputValue(),
    channel,
  );
  await page.getByRole("button", { name: "Save configuration", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "Review the marked fields" }).waitFor();
  assert.equal(writes.length, count, "Invalid observe settings must never reach PUT.");
  await profile.getByLabel("Channel mode", { exact: true }).selectOption("forward");
  await profile.getByLabel("Display name", { exact: true }).fill("Edited forward channel");
  expected.profiles[0].display_name = "Edited forward channel";
  await save("whatsapp", expected);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "200%";
  });
  const dimensions = await page.evaluate(() => ({
    width: innerWidth,
    content: document.documentElement.scrollWidth,
  }));
  assert.ok(
    dimensions.content <= dimensions.width,
    "WhatsApp mode controls must fit 375px with enlarged text.",
  );
  await page.screenshot({
    path: resolve(screenshotDir, "synthetic-wa-v2-375-text-200.png"),
    fullPage: true,
    animations: "disabled",
  });
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "";
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  for (const version of [1, 3]) {
    snapshots.set(ids.whatsapp, {
      ...snapshots.get(ids.whatsapp),
      config_version: version,
      config: { ...expected, version },
    });
    await openWorkflow("whatsapp");
    await page
      .getByRole("alert")
      .filter({ hasText: "configuration version is not supported" })
      .waitFor();
    assert.equal(
      await page.getByRole("button", { name: "Save configuration", exact: true }).count(),
      0,
    );
  }
  console.log(
    "WhatsApp v2: mixed observe/forward edits, version preservation, invalid-mode prevention and unsupported-version protection passed.",
  );
}

try {
  await page.goto(`${target.origin}/workspace`);
  await page.getByLabel("Email", { exact: true }).fill(user.email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("heading", { name: "Overview", exact: true }).waitFor();
  for (const kind of ["x", "instagram", "whatsapp"]) await socialEditor(kind);
  await whatsappModes();
  for (const kind of ["gtw", "board"]) {
    await openWorkflow(kind);
    const expected = structuredClone(snapshots.get(ids[kind]).config);
    await page.getByLabel("Heartbeat channel ID", { exact: true }).fill(updatedChannel);
    expected.destinations.heartbeat_discord_channel_id = updatedChannel;
    if (kind === "gtw") {
      assert.equal(await page.getByLabel("Legacy channel username", { exact: true }).isEditable(), false);
      await page
        .getByLabel("Additional instructions", { exact: true })
        .fill("Updated synthetic GTW guidance.");
      expected.additional_prompt_instruction = "Updated synthetic GTW guidance.";
    } else assert.equal(await page.getByLabel("Legacy channel username", { exact: true }).count(), 0);
    await save(kind, expected);
  }
  assert.equal(writes.length, 14);
  assert.deepEqual(errors, []);
  assert.deepEqual(unexpectedRequests, []);
  console.log(
    "Source editor smoke passed: X, Instagram, WhatsApp v2, GTW and swing board; 14 synthetic saves, no real API requests. X screenshots captured at 1440px and 375px.",
  );
} catch (error) {
  console.error("Synthetic source editor diagnostics:", {
    errors,
    unexpectedRequests,
    signedIn,
    headings: await page
      .getByRole("heading")
      .allTextContents()
      .catch(() => []),
    alerts: await page
      .getByRole("alert")
      .allTextContents()
      .catch(() => []),
  });
  throw error;
} finally {
  await context.close();
  await browser.close();
}
