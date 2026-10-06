import assert from "node:assert/strict";
import { chromium } from "playwright";

const base = process.env.BURSAWATCH_TEST_URL ?? "http://localhost:3100";
const target = new URL(base);
if (!["localhost", "127.0.0.1", "[::1]"].includes(target.hostname)) {
  throw new Error("Browser smoke tests must target a local, isolated workspace.");
}

const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
});
const page = await browser.newPage({
  viewport: { width: 1440, height: 1000 },
  reducedMotion: "reduce",
});
page.setDefaultTimeout(10000);
const pageErrors = [];
const controlRequests = [];
const networkWrites = [];
page.on("pageerror", (error) => pageErrors.push(error.message));
page.on("request", (request) => {
  const url = new URL(request.url());
  if (url.origin === target.origin && url.pathname.startsWith("/api/control/")) {
    controlRequests.push(`${request.method()} ${url.pathname}`);
  }
  if (!['GET', 'HEAD'].includes(request.method())) {
    networkWrites.push(`${request.method()} ${url.pathname}`);
  }
});

const navigation = page.getByRole("navigation", { name: "Workspace navigation", exact: true });
const goToView = async (label) => {
  await navigation.getByRole("link", { name: label, exact: true }).click();
};
const assertNoHorizontalOverflow = async (message) => {
  const dimensions = await page.evaluate(() => ({
    viewport: innerWidth,
    document: document.documentElement.scrollWidth,
  }));
  assert.ok(dimensions.document <= dimensions.viewport, `${message}: ${JSON.stringify(dimensions)}`);
};

try {
  await page.goto(`${base}/app`);
  await navigation.waitFor();
  await page.getByRole("heading", { name: "Overview", exact: true }).waitFor();
  await page.getByText("Synthetic examples only. No live runs, deliveries, connections, or current system state.", { exact: true }).waitFor();
  await page.getByRole("heading", { name: "BURSAWATCH PAGI", exact: true }).waitFor();
  await page.getByText("Example only · dummy figures", { exact: true }).waitFor();

  const expectedViews = [
    ["Overview", "/app"],
    ["Sources", "/app/sources"],
    ["Workflows", "/app/workflows"],
    ["Jobs", "/app/jobs"],
    ["History", "/app/history"],
    ["Published", "/app/published"],
    ["Account", "/app/account"],
  ];
  assert.equal(await navigation.getByRole("link").count(), expectedViews.length);
  for (const [label, href] of expectedViews) {
    assert.equal(
      await navigation.getByRole("link", { name: label, exact: true }).getAttribute("href"),
      href,
    );
  }
  assert.equal(await page.getByRole("button", { name: /sign out/i }).count(), 0);

  await goToView("Sources");
  await page.getByRole("tablist", { name: "Source category", exact: true }).waitFor();
  await page.getByRole("tab", { name: "People & Org", exact: true }).click();
  await page.getByRole("heading", { name: "Ricky Ho", exact: true }).waitFor();
  await page.getByText(/People & Org identity is not attached to a watcher profile\./).waitFor();
  const contentChoices = page.getByRole("group", { name: "Content choices", exact: true });
  await contentChoices.getByLabel("Account or channel", { exact: true }).selectOption("x-rickyho1989");
  await contentChoices.getByLabel("Content type", { exact: true }).selectOption("company_news");
  await contentChoices.getByLabel("Include this content").selectOption("on");
  await contentChoices.getByRole("button", { name: "Apply setting to draft", exact: true }).click();
  await page.getByRole("tab", { name: "Securities", exact: true }).click();
  const enrg = page.getByLabel("ENRG · PT Energi Mega Persada Tbk", { exact: true });
  await enrg.check();
  await page.getByRole("button", { name: "Save catalog", exact: true }).click();
  await page.getByText("Sample source catalog saved for this session.", { exact: true }).waitFor();
  await page.getByRole("tab", { name: "People & Org", exact: true }).click();
  await contentChoices.getByLabel("Account or channel", { exact: true }).selectOption("x-rickyho1989");
  await contentChoices.getByLabel("Content type", { exact: true }).selectOption("company_news");
  await page.getByText(/Saved: On \(endpoint_override, verified\)/).waitFor();

  await goToView("Workflows");
  await page.getByRole("button", { name: /Open watcher details: X accounts/ }).click();
  await page.getByRole("heading", { name: "X accounts", exact: true }).waitFor();
  const summaries = page.getByLabel("Summarize posts", { exact: true });
  await summaries.waitFor();
  await summaries.check();
  await page.getByRole("button", { name: "Save configuration", exact: true }).click();
  await page.getByText("Sample configuration saved for this session.", { exact: true }).waitFor();
  await goToView("Sources");
  await page.getByRole("tab", { name: "Securities", exact: true }).click();
  assert.equal(await page.getByLabel("ENRG · PT Energi Mega Persada Tbk", { exact: true }).isChecked(), true);
  await goToView("Workflows");
  await page.getByRole("button", { name: /Open watcher details: X accounts/ }).click();
  assert.equal(await page.getByLabel("Summarize posts", { exact: true }).isChecked(), true);
  await page.getByText(/no evening digest/i).waitFor();

  await goToView("Jobs");
  await page.getByRole("heading", { name: "Jobs", exact: true }).waitFor();
  await page.getByText(/no weekly interval or clock-time morning schedule/i).waitFor();
  assert.equal(await page.getByRole("button", { name: /save schedule|run now|run job/i }).count(), 0);

  await goToView("History");
  await page.getByRole("heading", { name: "Run history", exact: true }).waitFor();
  await page.getByText("These are synthetic example timelines, not real runs or deliveries.", { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: /save|run now|run job/i }).count(), 0);

  await goToView("Published");
  await page.getByRole("heading", { name: "Published", exact: true }).waitFor();
  await page.getByText("Public examples from the Bursawatch landing page. This sample does not check live delivery or publisher coverage.", { exact: true }).waitFor();
  for (const title of [
    /TRUK: PT Pukul Rata Kanan/,
    /HRTA/,
    /ENRG: Buy/,
    /ENRG: Target 1350 achieved/,
  ]) {
    await page.getByRole("button", { name: title }).waitFor();
  }
  await page.getByRole("button", { name: /TRUK: PT Pukul Rata Kanan/i }).click();
  await page.getByRole("heading", { name: /TRUK: PT Pukul Rata Kanan/i }).waitFor();
  await page.getByRole("heading", { name: "Sample content", exact: true }).waitFor();
  assert.equal(await page.getByText(/destination [0-9]+/i).count(), 0);
  assert.equal(await page.getByText("Delivered", { exact: true }).count(), 0);
  assert.equal(await page.getByText("Sample record", { exact: true }).count(), 1);

  await goToView("Account");
  await page.getByRole("heading", { name: "Account", exact: true }).waitFor();
  await page.getByText("No account is signed in to this sample workspace.", { exact: true }).waitFor();
  await page.getByRole("link", { name: "Open the real workspace", exact: true }).waitFor();
  assert.equal(await page.getByText("Account ID", { exact: true }).count(), 0);
  assert.equal(await page.getByRole("button", { name: /sign out|invite|connect bot/i }).count(), 0);

  const legacyRedirects = [
    ["/app/insights", "/app"],
    ["/app/overview", "/app"],
    ["/app/discover", "/app/sources"],
    ["/app/following", "/app/sources"],
    ["/app/securities", "/app/sources"],
    ["/app/securities/add", "/app/sources"],
    ["/app/automations", "/app/workflows"],
    ["/app/automations/custom", "/app/workflows"],
    ["/app/automations/library", "/app/workflows"],
    ["/app/automations/new", "/app/workflows"],
    ["/app/settings", "/app/account"],
    ["/app/settings/bot", "/app/account"],
    ["/app/settings/account", "/app/account"],
    ["/app/activity", "/app/history"],
    ["/app/logs", "/app/history"],
    ["/app/configuration", "/app/workflows"],
    ["/app/watchlist", "/app/workflows"],
    ["/app/setup", "/app"],
  ];
  for (const [path, destination] of legacyRedirects) {
    await page.goto(`${base}${path}`);
    await page.waitForURL(`**${destination}`);
  }

  await page.goto(`${base}/app`);
  await page.setViewportSize({ width: 375, height: 812 });
  await navigation.waitFor();
  const navLinks = navigation.getByRole("link");
  assert.equal(await navLinks.count(), 7);
  const assertMobileNavigation = async () => {
    await page.waitForFunction(() => {
      const bar = document.querySelector(".connected-navigation-links");
      const active = bar?.querySelector('a[aria-current="page"]');
      if (!bar || !active) return false;
      const barBounds = bar.getBoundingClientRect();
      const activeBounds = active.getBoundingClientRect();
      return activeBounds.left >= barBounds.left && activeBounds.right <= barBounds.right;
    });
    const layout = await navigation.evaluate((bar) => {
      const barBounds = bar.getBoundingClientRect();
      const links = [...bar.querySelectorAll("a")];
      const active = bar.querySelector('a[aria-current="page"]');
      const activeBounds = active?.getBoundingClientRect();
      return {
        clientWidth: bar.clientWidth,
        scrollWidth: bar.scrollWidth,
        overflowX: getComputedStyle(bar).overflowX,
        activeVisible: Boolean(
          activeBounds && activeBounds.left >= barBounds.left && activeBounds.right <= barBounds.right,
        ),
        links: links.map((link) => {
          const bounds = link.getBoundingClientRect();
          return { top: bounds.top, height: bounds.height };
        }),
      };
    });
    assert.equal(layout.overflowX, "auto");
    assert.ok(layout.scrollWidth > layout.clientWidth, "The seven mobile destinations must scroll in one row.");
    assert.equal(new Set(layout.links.map((link) => link.top)).size, 1);
    assert.equal(layout.activeVisible, true, "The active mobile destination must remain in view.");
    for (const link of layout.links) assert.ok(link.height >= 44, "Mobile navigation targets must be at least 44px high.");
  };
  await assertMobileNavigation();
  await assertNoHorizontalOverflow("Sample workspace overflows at 375px");
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "200%";
  });
  await assertNoHorizontalOverflow("Sample workspace overflows with enlarged text");
  assert.equal(await navLinks.count(), 7);
  await assertMobileNavigation();
  for (const [label, path] of [
    ["Overview", "/app"],
    ["Sources", "/app/sources"],
    ["Workflows", "/app/workflows"],
    ["Jobs", "/app/jobs"],
    ["History", "/app/history"],
    ["Published", "/app/published"],
    ["Account", "/app/account"],
  ]) {
    await navigation.getByRole("link", { name: label, exact: true }).click();
    await page.waitForURL((url) => url.pathname === path);
    await assertMobileNavigation();
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await assertNoHorizontalOverflow("Sample workspace overflows on desktop");

  assert.deepEqual(controlRequests, [], "The sample workspace must never call /api/control.");
  assert.deepEqual(networkWrites, [], "The sample workspace must not send network writes.");
  assert.deepEqual(pageErrors, [], "The sample workspace should not produce browser errors.");
  console.log("Sample workspace smoke passed: shared seven-view navigation, horizontally scrollable mobile destinations, in-memory catalog and watcher saves, read-only Jobs and History, public sample records, legacy redirects, zero /api/control requests, and 375px plus enlarged-text layouts.");
} finally {
  await browser.close();
}
