import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright";

// Local, synthetic UI checks only: all Auth, control and remote-image requests
// are intercepted. No backend configuration, credentials or provider is used.
const target = new URL(process.env.BURSAWATCH_TEST_URL ?? "http://127.0.0.1:3300");
assert.ok(["localhost", "127.0.0.1", "[::1]"].includes(target.hostname));
assert.ok(!target.username && !target.password);
const watcherId = "bursawatch-tg-market-news";
const profileId = "fixture_source";
const profilePath = `watchers/${watcherId}/profiles`;
const avatarPath = `${profilePath}/${profileId}/avatar`;
const imageUrl = "https://images.example.test/synthetic-avatar.png";
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
});

async function scenario(role) {
  const timestamp = new Date().toISOString();
  const user = {
    id: "00000000-0000-4000-8000-000000000031",
    aud: "authenticated",
    role: "authenticated",
    email: `${role}@example.test`,
    app_metadata: { provider: "email", providers: ["email"] },
    user_metadata: {},
    identities: [],
    created_at: timestamp,
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
  let profile = {
    watcher_id: watcherId,
    profile_id: profileId,
    handle: "fixture_source",
    display_name: "Synthetic Source",
    profile_url: "https://t.me/fixture_source",
    enabled: true,
    avatar: {
      mode: "auto",
      url: imageUrl,
      source: "synthetic",
      fetched_at: null,
      last_success_at: null,
      has_error: false,
      updated_at: timestamp,
    },
  };
  const snapshot = {
    api_version: 1,
    watcher_id: watcherId,
    revision: 3,
    config_version: 1,
    config_sha256: "a".repeat(64),
    updated_at: timestamp,
    config: {
      version: 1,
      providers: {
        phintraco: { telegram_username: "fixture_source" },
        tuntun: { telegram_username: "fixture_macro" },
      },
      destinations: {
        id_stocks_news_discord_channel_id: "111111111111111111",
        macro_news_discord_channel_id: "222222222222222222",
        industry_news_discord_channel_id: "333333333333333333",
        heartbeat_discord_channel_id: "444444444444444444",
      },
      additional_prompt_instruction: "Synthetic fixture only.",
    },
  };
  let signedIn = false;
  let readFailure = false;
  let writeFailure = null;
  let holdWrite = false;
  let releaseWrite;
  const calls = [];
  const writes = [];
  const errors = [];
  const unexpected = [];
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: "reduce",
    serviceWorkers: "block",
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on("pageerror", (error) => errors.push(error.message));
  await context.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const json = (body, status = 200) => route.fulfill({
      status,
      json: body,
      headers: { "access-control-allow-origin": target.origin, "cache-control": "no-store" },
    });
    try {
      if (url.protocol === "https:" && url.pathname.startsWith("/auth/v1/")) {
        if (method === "OPTIONS") return route.fulfill({ status: 204, headers: {
          "access-control-allow-origin": target.origin,
          "access-control-allow-headers": "*",
          "access-control-allow-methods": "GET, POST, OPTIONS",
        } });
        if (url.pathname === "/auth/v1/token" && method === "POST") {
          assert.deepEqual(request.postDataJSON().email, user.email);
          assert.equal(request.postDataJSON().password, "synthetic-only-password");
          signedIn = true;
          return json(session);
        }
        if (url.pathname === "/auth/v1/user" && method === "GET") return json(user);
      }
      if (url.origin === target.origin && url.pathname.startsWith("/api/control/")) {
        assert.ok(signedIn);
        assert.equal(request.headers().authorization, `Bearer ${token}`);
        const path = url.pathname.slice("/api/control/".length);
        calls.push({ method, path });
        if (method === "GET" && path === "watchers") return json([{
          watcher_id: watcherId, display_name: "Synthetic market news", current_revision: 3, updated_at: timestamp,
        }]);
        if (method === "GET" && path === `watchers/${watcherId}/config`) {
          return role === "admin" ? json(snapshot) : json({ code: "forbidden", message: "Configuration is restricted to administrators." }, 403);
        }
        if (method === "GET" && path === profilePath) {
          return readFailure ? json({ code: "auth", message: "Your session has expired. Sign in again." }, 401) : json([profile]);
        }
        if (path === avatarPath || path === `${avatarPath}/refresh`) {
          assert.equal(role, "admin", "Viewers cannot submit photo changes.");
          const payload = request.postDataJSON();
          if (path.endsWith("/refresh")) {
            assert.equal(method, "POST");
            assert.deepEqual(payload, {});
          } else {
            assert.equal(method, "PUT");
            assert.deepEqual(Object.keys(payload).sort(), ["mode", "url"]);
            assert.ok(["manual", "auto"].includes(payload.mode));
            if (payload.mode === "auto") assert.equal(payload.url, null);
          }
          writes.push({ method, path, payload });
          if (holdWrite) await new Promise(resolve => { releaseWrite = resolve; });
          if (writeFailure) {
            const failure = writeFailure;
            writeFailure = null;
            return json(failure.body, failure.status);
          }
          if (method === "PUT") profile = { ...profile, avatar: { ...profile.avatar, ...payload } };
          return json(profile);
        }
        unexpected.push(`${method} ${path}`);
        return json({ code: "unavailable", message: "Unmocked control request." }, 500);
      }
      // This known failed fixture image must fall back to initials without
      // reaching its external origin. All other external requests are errors.
      if (url.href === imageUrl) return route.fulfill({ status: 404, body: "" });
      if (url.origin !== target.origin) {
        unexpected.push(`${method} ${url.origin}${url.pathname}`);
        return route.abort("blockedbyclient");
      }
      return route.continue();
    } catch (error) {
      errors.push(error.message);
      return json({ code: "unavailable", message: "Synthetic assertion failed." }, 500);
    }
  });
  const panel = page.getByRole("region", { name: "Source profiles", exact: true });
  const edit = () => panel.getByRole("button", { name: "Edit photo", exact: true });
  const save = () => panel.getByRole("button", { name: "Save photo settings", exact: true });
  const refresh = () => panel.getByRole("button", { name: "Refresh source photo", exact: true });
  try {
    await page.goto(`${target.origin}/workspace/workflows?watcher=${watcherId}`);
    await page.getByLabel("Email", { exact: true }).fill(user.email);
    await page.getByLabel("Password", { exact: true }).fill("synthetic-only-password");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await panel.getByRole("heading", { name: "Source profiles", exact: true }).waitFor();
    await page.getByRole("heading", { name: role === "viewer" ? "View access" : "Watcher configuration", exact: true }).waitFor();
    assert.equal(calls.filter((call) => call.path === profilePath).length, 0, "Profiles load only on request.");
    await panel.getByRole("button", { name: "Load profiles", exact: true }).click();
    await panel.getByRole("heading", { name: "Synthetic Source", exact: true }).waitFor();
    await panel.locator(".source-profile-photo").scrollIntoViewIfNeeded();
    await page.waitForFunction(() => document.querySelector(".source-profile-photo")?.textContent === "SY");
    assert.equal(await panel.locator(".source-profile-photo img").count(), 0);
    assert.equal(await edit().count(), role === "admin" ? 1 : 0);
    if (role === "admin") {
      await edit().click();
      await panel.getByLabel("Photo source", { exact: true }).selectOption("manual");
      await panel.getByLabel("Image URL", { exact: true }).fill(imageUrl);
      holdWrite = true;
      await save().click();
      await page.waitForFunction(() => document.querySelector(".source-avatar-editor fieldset")?.disabled === true);
      assert.ok(await panel.getByRole("button", { name: "Close photo settings", exact: true }).isDisabled(), "Cannot discard a photo write in progress.");
      assert.ok(await panel.getByRole("button", { name: "Reload profiles", exact: true }).isDisabled());
      await page.waitForTimeout(50);
      assert.equal(typeof releaseWrite, "function");
      holdWrite = false;
      releaseWrite();
      await panel.getByRole("status").filter({ hasText: "Photo settings saved." }).waitFor();
      assert.deepEqual(writes.at(-1), { method: "PUT", path: avatarPath, payload: { mode: "manual", url: imageUrl } });
      assert.ok(await refresh().isDisabled(), "Manual mode must not offer automatic refresh.");
      await panel.getByLabel("Photo source", { exact: true }).selectOption("auto");
      await save().click();
      await page.waitForFunction(() => document.querySelector(".source-avatar-editor fieldset")?.disabled === false);
      assert.deepEqual(writes.at(-1), { method: "PUT", path: avatarPath, payload: { mode: "auto", url: null } });
      await refresh().click();
      await panel.getByRole("status").filter({ hasText: "Photo refresh requested. Reload profiles to check the result." }).waitFor();
      assert.deepEqual(writes.at(-1), { method: "POST", path: `${avatarPath}/refresh`, payload: {} });
      assert.doesNotMatch(await panel.innerText(), /refresh completed|photo refreshed successfully/i);

      await panel.getByLabel("Photo source", { exact: true }).selectOption("manual");
      await panel.getByLabel("Image URL", { exact: true }).fill(imageUrl);
      writeFailure = { status: 502, body: { code: "unknown-outcome", message: "The save could not be confirmed. Reload profiles before trying again." } };
      await save().click();
      await panel.getByText("Reload profiles before another change; the previous outcome may be uncertain.", { exact: true }).waitFor();
      assert.ok(await save().isDisabled());
      assert.ok(await refresh().isDisabled());
      const countBeforeReload = writes.length;
      page.once("dialog", async (dialog) => { await dialog.accept(); });
      await panel.getByRole("button", { name: "Close photo settings", exact: true }).click();
      assert.ok(await edit().isDisabled(), "Closing an uncertain editor must not enable another write.");
      await page.getByRole("button", { name: "Reload configuration", exact: true }).click();
      await page.getByRole("heading", { name: "Watcher configuration", exact: true }).waitFor();
      assert.ok(await edit().isDisabled(), "Reloading workflow configuration must not clear photo-write uncertainty.");
      await panel.getByRole("button", { name: "Reload profiles", exact: true }).click();
      await edit().waitFor();
      assert.equal(writes.length, countBeforeReload, "Reload must not retry an uncertain write.");
      await edit().click();
      assert.ok(await panel.getByLabel("Photo source", { exact: true }).isEnabled());
      assert.equal(await panel.getByLabel("Photo source", { exact: true }).inputValue(), "auto");
    }
    await page.setViewportSize({ width: 375, height: 812 });
    await page.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
    await page.evaluate(() => document.fonts.ready);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Source profiles must fit 375px with enlarged text.");
    await mkdir("test-results/source-profiles", { recursive: true });
    await page.screenshot({ path: `test-results/source-profiles/${role}-mobile.png`, fullPage: true });
    readFailure = true;
    await panel.getByRole("button", { name: "Reload profiles", exact: true }).click();
    await panel.getByRole("alert").filter({ hasText: "Your session has expired" }).waitFor();
    assert.equal(await panel.getByRole("heading", { name: "Synthetic Source", exact: true }).count(), 0, "Authentication errors clear profile records.");
    assert.equal(await edit().count(), 0);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(errors, []);
    if (role === "viewer") assert.equal(writes.length, 0);
    console.log(`PASS: ${role} source profiles—on-demand reads, image fallback, bounded writes, accessible layout and cleared auth failures.`);
  } finally {
    await context.close();
  }
}

try {
  await scenario("viewer");
  await scenario("admin");
} finally {
  await browser.close();
}
