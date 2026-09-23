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
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
page.setDefaultTimeout(10000);
const errors = [];
page.on("pageerror", error => errors.push(error.message));
const overflow = async () => {
  const report = await page.evaluate(() => ({
    overflowing: document.documentElement.scrollWidth > innerWidth,
    url: location.href, width: innerWidth, textSize: document.documentElement.style.fontSize,
    elements: [...document.querySelectorAll("body *")].filter(el => el.getBoundingClientRect().right > innerWidth + 1).slice(0, 8).map(el => ({ tag: el.tagName, class: el.className, text: el.textContent?.slice(0, 70) })),
  }));
  assert.equal(report.overflowing, false, JSON.stringify(report));
};

try {
  await page.goto(`${base}/app/discover`);
  await page.getByRole("navigation", { name: "Workspace navigation", exact: true }).getByRole("link", { name: "Workflows", exact: true }).click();
  await page.waitForURL("**/app/automations/custom");
  await page.getByRole("heading", { name: "Your workflows", exact: true }).waitFor();
  await page.goto(`${base}/app/discover`);
  await page.getByLabel("Search discover").fill("Avenir");
  const source = page.locator("article").filter({ has: page.getByRole("heading", { name: "Avenir Research" }) });
  const initials = source.locator(".hub-avatar");
  assert.equal(await initials.locator("img").count(), 0);
  assert.equal(await initials.evaluate(el => el.classList.contains("is-institution")), false);
  await source.getByRole("button", { name: "Follow", exact: true }).click();
  await page.getByText("Following Avenir Research.", { exact: true }).waitFor();
  assert.equal(await page.getByRole("heading", { name: "What matters to you?" }).count(), 0);
  await page.goto(`${base}/app/following`);
  await page.getByRole("button", { name: "Configure", exact: true }).click();
  assert.equal(await page.getByLabel("Where is it published?").inputValue(), "instagram");
  assert.equal(await page.getByLabel("Profile link or handle").inputValue(), "https://www.instagram.com/avenirresearch.id");
  await page.getByText("Media & extra preferences", { exact: true }).click();
  await page.getByLabel("Posts and carousels", { exact: true }).uncheck();
  await page.getByLabel("Reels", { exact: true }).uncheck();
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await page.locator("#instagram-publications-error").waitFor();
  assert.equal(await page.getByLabel("Posts and carousels", { exact: true }).getAttribute("aria-invalid"), "true");
  await page.getByLabel("Reels", { exact: true }).check();
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await page.getByText("Source preferences saved.", { exact: true }).waitFor();
  await page.reload();
  await page.getByRole("button", { name: "Configure", exact: true }).click();
  await page.getByText("Media & extra preferences", { exact: true }).click();
  assert.equal(await page.getByLabel("Posts and carousels", { exact: true }).isChecked(), false);
  assert.equal(await page.getByLabel("Reels", { exact: true }).isChecked(), true);
  await page.getByLabel("Profile link or handle").fill("https://www.instagram.com/reel/not-a-profile");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  assert.equal(await page.getByLabel("Profile link or handle").getAttribute("aria-invalid"), "true");

  await page.goto(`${base}/app/automations/library`);
  assert.equal(await page.locator(".capability-row").count(), 7);
  await page.getByLabel("Show", { exact: true }).selectOption("sources");
  assert.equal(await page.locator(".capability-row").count(), 3);
  await page.getByLabel("Search workflows").fill("Instagram");
  await page.locator(".capability-row").click();
  await page.getByRole("heading", { name: "Instagram account watch", exact: true }).waitFor();
  await page.waitForURL(url => url.searchParams.get("workflow") === "instagram-accounts");
  await page.goBack();
  assert.equal(await page.getByLabel("Search workflows").inputValue(), "Instagram");
  assert.equal(await page.getByLabel("Show", { exact: true }).inputValue(), "sources");
  await page.locator(".capability-row").click();
  await page.getByRole("link", { name: "Workflow library", exact: true }).click();
  assert.equal(await page.getByLabel("Search workflows").inputValue(), "Instagram");
  assert.equal(await page.getByLabel("Show", { exact: true }).inputValue(), "sources");
  await page.locator(".capability-row").click();
  await page.getByRole("link", { name: "Instagram preferences", exact: true }).click();
  assert.equal(await page.getByLabel("Source platform", { exact: true }).inputValue(), "instagram");
  await page.getByRole("heading", { name: "Avenir Research", exact: true }).waitFor();
  assert.equal(await page.locator(".hub-broker").count(), 0);
  await page.getByRole("link", { name: "Follow sources", exact: true }).click();
  assert.equal(await page.getByLabel("Source platform", { exact: true }).inputValue(), "instagram");
  await page.getByRole("button", { name: "Add a source", exact: true }).click();
  assert.equal(await page.getByLabel("Where is it published?").inputValue(), "instagram");
  await page.getByLabel("Source name", { exact: true }).fill("Unfinished Instagram source");
  await page.goto(`${base}/app/discover?platform=telegram`);
  await page.getByRole("button", { name: "Add a source", exact: true }).click();
  assert.equal(await page.getByLabel("Where is it published?").inputValue(), "telegram");
  assert.equal(await page.getByLabel("Source name", { exact: true }).inputValue(), "");
  await page.goto(`${base}/app/automations/library?workflow=unknown`);
  await page.getByRole("heading", { name: "Workflow not found" }).waitFor();
  await page.getByRole("link", { name: "Workflow library", exact: true }).click();
  await page.getByLabel("Search workflows").fill("nonexistent source");
  await page.getByRole("heading", { name: "No matching workflows" }).waitFor();
  await page.getByRole("button", { name: "Clear filters", exact: true }).click();
  assert.equal(await page.locator(".capability-row").count(), 7);

  await page.goto(`${base}/app/discover`);
  await page.getByLabel("Source platform", { exact: true }).selectOption("x");
  await page.getByLabel("Search discover").fill("Almer");
  await page.getByRole("button", { name: "Follow", exact: true }).click();
  await page.getByText("Following Almer Sad.", { exact: true }).waitFor();
  await page.goto(`${base}/app/following?platform=x`);
  await page.getByRole("button", { name: "Configure", exact: true }).click();
  await page.getByText("Media & extra preferences", { exact: true }).click();
  await page.getByLabel("Include original posts", { exact: true }).uncheck();
  await page.getByLabel("Include quote posts", { exact: true }).uncheck();
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await page.locator("#x-publications-error").waitFor();
  await page.waitForFunction(() => document.activeElement?.getAttribute("aria-describedby") === "x-publications-error");
  await page.getByLabel("Include replies", { exact: true }).check();
  await page.getByLabel("Group posts from the same thread", { exact: true }).uncheck();
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await page.getByText("Source preferences saved.", { exact: true }).waitFor();
  await page.reload();
  await page.getByRole("button", { name: "Configure", exact: true }).click();
  await page.getByText("Media & extra preferences", { exact: true }).click();
  assert.equal(await page.getByLabel("Include replies", { exact: true }).isChecked(), true);
  assert.equal(await page.getByLabel("Group posts from the same thread", { exact: true }).isChecked(), false);
  await page.getByLabel("Include original posts", { exact: true }).check();
  await page.getByRole("button", { name: "Close source editor", exact: true }).click();
  await page.getByRole("button", { name: "Discard changes", exact: true }).click();
  await page.getByRole("button", { name: "Configure", exact: true }).click();
  await page.getByText("Media & extra preferences", { exact: true }).click();
  assert.equal(await page.getByLabel("Include original posts", { exact: true }).isChecked(), false);

  for (const [channel, label] of [["WhatsApp", "Recipient label"], ["Telegram", "Chat label"], ["Discord", "Channel label"], ["Slack", "Channel label"], ["Email", "Inbox label"]]) {
    await page.goto(`${base}/app/settings`);
    await page.getByRole("button", { name: `Configure ${channel}`, exact: true }).click();
    await page.getByLabel(label, { exact: true }).fill(`Test ${channel} desk`);
    await page.getByRole("button", { name: "Save channel", exact: true }).click();
    await page.getByText(`${channel} preferences saved. Connection is still required.`, { exact: true }).waitFor();
    await page.reload();
    await page.getByRole("button", { name: `Configure ${channel}`, exact: true }).click();
    assert.equal(await page.getByLabel(label, { exact: true }).inputValue(), `Test ${channel} desk`);
  }
  for (const width of [375, 812, 1440]) {
    await page.setViewportSize({ width, height: width === 812 ? 375 : 1000 });
    for (const route of ["discover", "following", "insights", "automations", "automations/library", "automations/library?workflow=swing-board", "activity", "settings", "settings/bot"]) {
      await page.goto(`${base}/app/${route}`);
      await page.getByRole("heading", { level: 1 }).waitFor();
      await page.evaluate(() => document.fonts.ready);
      await overflow();
      await page.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
      await overflow();
    }
    await page.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
    await overflow();
  }
  await page.goto(base);
  await page.waitForURL("**/workspace");
  assert.equal((await page.request.post(`${base}/api/automations`, { data: {} })).status(), 403);
  assert.equal((await page.request.patch(`${base}/api/automations/demo-banking-watch`, { data: { status: "paused" } })).status(), 403);
  assert.deepEqual(errors, []);
  if (process.env.BURSAWATCH_SCREENSHOT_DIR) {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(`${base}/app/automations/library`);
    await page.screenshot({ path: `${process.env.BURSAWATCH_SCREENSHOT_DIR}/workflow-library.png`, fullPage: true });
    await page.setViewportSize({ width: 375, height: 900 });
    await page.goto(`${base}/app/automations/library?workflow=swing-board`);
    await page.screenshot({ path: `${process.env.BURSAWATCH_SCREENSHOT_DIR}/workflow-mobile.png`, fullPage: true });
  }
  console.log("Browser smoke passed: workflow search/deep links/recovery, source filters, X and Instagram save/reload/validation/cancel, five delivery forms, 27 responsive routes at normal/enlarged text, root redirect and read-only API.");
} finally {
  await browser.close();
}
