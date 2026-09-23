import assert from "node:assert/strict";

const target = new URL(process.env.BURSAWATCH_TEST_URL ?? "http://127.0.0.1:3300");
assert.ok(["localhost", "127.0.0.1", "[::1]"].includes(target.hostname));
assert.ok(!target.username && !target.password);

// Public HTML may be cached; user-authorized API responses must never be.
// No credentials or live provider requests are used by these checks.
for (const path of ["", "/overview", "/workflows", "/history", "/schedules", "/settings"]) {
  const response = await fetch(`${target.origin}/workspace${path}`);
  assert.equal(response.status, 200, `Public shell ${path || "/"} must be available.`);
  assert.match(response.headers.get("cache-control") ?? "", /s-maxage=/);
  const html = await response.text();
  assert.match(html, /Bursawatch/);
  assert.match(html, /Opening your workspace/);
  assert.doesNotMatch(html, /sb_secret_|service_role|\"access_token\"|\"refresh_token\"/);
}
for (const path of ["/workspace/not-a-view", "/workspace/workflows/private-extra"]) {
  assert.equal((await fetch(`${target.origin}${path}`)).status, 404);
}
for (const path of ["watchers", "watchers/bursawatch-x-account-watch/config"]) {
  const response = await fetch(`${target.origin}/api/control/${path}`);
  assert.equal(response.status, 401, "Public HTML must not grant access to protected records.");
  assert.match(response.headers.get("cache-control") ?? "", /no-store/);
}
console.log(
  "PASS: six cacheable public shells, unknown-route rejection and uncached authenticated API boundary.",
);
