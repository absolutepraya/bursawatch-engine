import assert from "node:assert/strict";
import { chromium } from "playwright";

const base = process.env.BURSAWATCH_TEST_URL ?? "http://localhost:3100";
if (!["localhost", "127.0.0.1", "[::1]"].includes(new URL(base).hostname)) {
  throw new Error("Workflow tests must target a local, isolated workspace.");
}
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  reducedMotion: "reduce",
});
const page = await context.newPage();
page.setDefaultTimeout(10000);
page.on("dialog", (dialog) => dialog.accept());
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const route = `${base}/app/automations/custom`;
const key = "bursawatch-custom-workflows-v1";
const click = (name) => page.getByRole("button", { name, exact: true }).click();
const focused = async (locator) => {
  await page.waitForFunction((element) => element === document.activeElement, await locator.elementHandle());
};
const save = async () => {
  await click("Save workflow");
  await page.getByRole("heading", { name: "Saved configurations", exact: true }).waitFor();
};
const noOverflow = async () => {
  await page.evaluate(() => document.fonts.ready);
  const report = await page.evaluate(() => ({
    width: innerWidth,
    actual: document.documentElement.scrollWidth,
    textSize: document.documentElement.style.fontSize,
    overflowing: [...document.querySelectorAll(".custom-workflows *")]
      .filter((element) => element.getBoundingClientRect().right > innerWidth + 1)
      .slice(0, 5)
      .map((element) => ({ tag: element.tagName, class: element.className })),
  }));
  assert.ok(report.actual <= report.width, JSON.stringify(report));
};

try {
  await page.goto(route);
  await click("Create your own");
  await click("Save workflow");
  await page.getByText("Use a name with at least 3 characters.", { exact: true }).waitFor();
  await focused(page.locator("#workflow-name"));
  await page.getByLabel("Workflow name", { exact: true }).fill("Morning research");
  await page.getByText("Brief format & language", { exact: true }).click();
  await page.getByLabel("Brief format", { exact: true }).selectOption("original");
  assert.equal(await page.getByLabel("Summary language", { exact: true }).isDisabled(), true);
  await page.getByLabel("Brief format", { exact: true }).selectOption("concise");
  assert.equal(await page.getByLabel("Summary language", { exact: true }).isEnabled(), true);
  await page.getByLabel("Daily time", { exact: true }).fill("08:15");
  await page.getByLabel("Time zone", { exact: true }).selectOption("Asia/Makassar");
  await page.getByRole("checkbox", { name: "Instagram", exact: true }).check();
  await page.getByRole("checkbox", { name: "Email Planned output", exact: true }).check();
  await save();
  await page.getByText("Workflow saved in this browser. It is not running.", { exact: true }).waitFor();
  await page.getByText("Mon–Fri at 08:15 WITA", { exact: true }).waitFor();
  await page.reload();
  await click("Edit Morning research");
  assert.equal(await page.getByLabel("Daily time", { exact: true }).inputValue(), "08:15");
  assert.equal(await page.getByRole("checkbox", { name: "Instagram", exact: true }).isChecked(), true);
  await page.getByLabel("Trigger", { exact: true }).selectOption("interval");
  await page.getByLabel("Interval in minutes", { exact: true }).fill("29");
  await click("Save workflow");
  await page.getByText("Choose an interval between 30 and 1,440 minutes.", { exact: true }).waitFor();
  await focused(page.locator("#workflow-interval"));
  // Invalid values remain recoverable without losing unrelated draft edits.
  await page.getByLabel("Interval in minutes", { exact: true }).fill("1441");
  await page.reload();
  await click("Edit Morning research");
  assert.equal(await page.getByLabel("Interval in minutes", { exact: true }).inputValue(), "1441");
  await page.getByLabel("Interval in minutes", { exact: true }).fill("90");
  await page.reload();
  await click("Edit Morning research");
  await page.getByText("Your unsaved draft was restored.", { exact: true }).waitFor();
  assert.equal(await page.getByLabel("Interval in minutes", { exact: true }).inputValue(), "90");
  await click("Cancel");
  await focused(page.getByRole("button", { name: "Keep editing", exact: true }));
  await click("Keep editing");
  await save();
  await page.getByText("Every 90 minutes · WITA", { exact: true }).waitFor();

  // A duplicate has its own recoverable draft; it must not erase an unfinished new workflow.
  await click("Create your own");
  await page.getByLabel("Workflow name", { exact: true }).fill("Unfinished new workflow");
  await page.goto(route);
  await click("Duplicate Morning research");
  assert.equal(await page.getByLabel("Workflow name", { exact: true }).inputValue(), "Morning research copy");
  await save();
  await click("Create your own");
  assert.equal(await page.getByLabel("Workflow name", { exact: true }).inputValue(), "Unfinished new workflow");
  await click("Cancel");
  await click("Discard changes");
  assert.equal(await page.locator(".custom-saved-row").count(), 2);
  await click("Remove Morning research copy");
  await focused(page.getByRole("button", { name: "Keep workflow", exact: true }));
  await click("Keep workflow");
  await focused(page.getByRole("button", { name: "Remove Morning research copy", exact: true }));
  await click("Remove Morning research copy");
  await click("Remove workflow");
  await page.getByText("Workflow removed from this browser.", { exact: true }).waitFor();
  assert.equal(await page.locator(".custom-saved-row").count(), 1);

  // A stale editor cannot overwrite a change saved by another tab.
  await click("Edit Morning research");
  await page.getByLabel("Workflow name", { exact: true }).fill("Stale edit");
  const peer = await context.newPage();
  await peer.goto(route);
  await peer.getByRole("button", { name: "Edit Morning research", exact: true }).click();
  await peer.getByLabel("Workflow name", { exact: true }).fill("Updated in another tab");
  await peer.getByRole("button", { name: "Save workflow", exact: true }).click();
  await peer.getByRole("heading", { name: "Updated in another tab", exact: true }).waitFor();
  await click("Save workflow");
  await page.getByRole("alert").filter({ hasText: "changed in another tab" }).waitFor();
  assert.equal(await page.getByLabel("Workflow name", { exact: true }).inputValue(), "Stale edit");
  await click("Cancel");
  await click("Discard changes");
  await page.getByRole("heading", { name: "Updated in another tab", exact: true }).waitFor();
  await peer.close();

  for (const viewport of [{ width: 375, height: 812 }, { width: 812, height: 375 }, { width: 1440, height: 1000 }]) {
    await page.setViewportSize(viewport);
    for (const fontSize of ["100%", "200%"]) {
      await page.evaluate((size) => { document.documentElement.style.fontSize = size; }, fontSize);
      await noOverflow();
      await click("Create your own");
      await noOverflow();
      await page.getByLabel("Trigger", { exact: true }).selectOption("interval");
      await noOverflow();
      await click("Cancel");
      await click("Discard changes");
    }
  }
  if (process.env.BURSAWATCH_SCREENSHOT_DIR) {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.evaluate(() => { document.documentElement.style.fontSize = "100%"; });
    await click("Edit Updated in another tab");
    await page.screenshot({ path: `${process.env.BURSAWATCH_SCREENSHOT_DIR}/custom-workflow-desktop.png`, fullPage: true });
    await page.setViewportSize({ width: 375, height: 812 });
    await page.screenshot({ path: `${process.env.BURSAWATCH_SCREENSHOT_DIR}/custom-workflow-mobile.png`, fullPage: true });
    await click("Cancel");
  }
  const before = await page.evaluate((storageKey) => localStorage.getItem(storageKey), key);
  await page.evaluate((storageKey) => localStorage.setItem(storageKey, "malformed fixture"), key);
  await page.reload();
  await page.getByRole("alert").filter({ hasText: "Your existing data has been kept" }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Create your own", exact: true }).count(), 0);
  assert.equal(await page.evaluate((storageKey) => localStorage.getItem(storageKey), key), "malformed fixture");
  await page.evaluate(({ storageKey, value }) => localStorage.setItem(storageKey, value), { storageKey: key, value: before });
  assert.deepEqual(errors, []);
  console.log("Custom workflow browser checks passed: CRUD, validation, recovery, copy isolation, conflict protection, safe removal, reduced motion and 200% text at 375/812/1440px.");
} finally {
  await browser.close();
}
