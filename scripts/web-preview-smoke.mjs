import assert from "node:assert/strict";
import { createRequire } from "node:module";

const [packageName, origin] = process.argv.slice(2);
assert.ok(["web-config", "web-landing"].includes(packageName));
const require = createRequire(new URL(`../${packageName}/package.json`, import.meta.url));
const { chromium } = require("playwright");
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 375, height: 812 } });
  const forbidden = [];
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/control") || url.hostname.endsWith("supabase.co")) forbidden.push(url.href);
  });
  if (packageName === "web-config") {
    for (const path of ["/", "/workspace", "/workspace/sources"]) {
      const response = await fetch(new URL(path, origin), { redirect: "manual" });
      assert.equal(response.status, 307);
      assert.equal(new URL(response.headers.get("location"), origin).pathname, "/app");
    }
    await page.goto(origin);
    await page.getByText(/Synthetic examples only/i).first().waitFor();
    assert.match(new URL(page.url()).pathname, /^\/app/);
    for (const method of ["GET", "PUT", "POST"]) {
      const response = await fetch(new URL("/api/control/watchers", origin), {
        method, headers: { authorization: "Bearer e30.e30.signature" },
      });
      assert.equal(response.status, 503);
      assert.match(response.headers.get("cache-control"), /no-store/);
      assert.equal((await response.json()).code, "preview");
    }
  } else {
    const response = await page.goto(origin);
    assert.equal(response.status(), 200);
    assert.match(response.headers()["x-robots-tag"], /noindex/);
    const href = await page.getByRole("link", { name: /Masuk workspace/i }).first().getAttribute("href");
    assert.match(href, /^https:\/\/bursawatch-dash-pr-[1-9][0-9]*\.absolutepraya\.workers\.dev\/workspace$/);
    assert.equal(await page.getByRole("button", { name: "Demo coming soon", exact: true }).count(), 2);
  }
  assert.deepEqual(forbidden, []);
  assert.deepEqual(errors, []);
  console.log(`${packageName}: isolated preview browser smoke passed`);
} finally {
  await browser.close();
}
