import assert from "node:assert/strict";
import { chromium } from "playwright";

const base = process.env.BURSAWATCH_TEST_URL ?? "http://127.0.0.1:3100";
if (!["localhost", "127.0.0.1", "[::1]"].includes(new URL(base).hostname)) throw new Error("Use a local isolated workspace.");
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
const errors = [];
page.on("pageerror", error => errors.push(error.message));
const key = "bursawatch-connection-plans-v1";
try {
  await page.goto(`${base}/app/settings/account`);
  await page.keyboard.press("Tab");
  assert.equal(await page.getByRole("link", { name: "Skip to main content", exact: true }).evaluate(el => document.activeElement === el), true);
  assert.equal(await page.getByRole("link", { name: "Skip to main content", exact: true }).evaluate(el => getComputedStyle(el).opacity), "1");
  await page.getByRole("button", { name: "Prepare Telegram input", exact: true }).click();
  await page.getByLabel("Connection label", { exact: true }).fill("ab");
  await page.getByRole("button", { name: "Save setup", exact: true }).click();
  assert.equal(await page.getByLabel("Connection label", { exact: true }).getAttribute("aria-invalid"), "true");
  await page.getByLabel("Connection label", { exact: true }).fill("My research channels");
  // An unrelated workspace rename must not invalidate this provider's draft.
  await page.goto(`${base}/app/settings/account`);
  await page.getByRole("button", { name: "Edit name", exact: true }).click();
  await page.getByLabel("Workspace name", { exact: true }).fill("Research workspace");
  await page.getByRole("button", { name: "Save name", exact: true }).click();
  await page.getByRole("heading", { name: "Research workspace", exact: true }).waitFor();
  await page.reload();
  await page.getByRole("button", { name: "Prepare Telegram input", exact: true }).click();
  assert.equal(await page.getByLabel("Connection label", { exact: true }).inputValue(), "My research channels");
  await page.getByText("Your unsaved draft was restored.", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Save setup", exact: true }).click();
  await page.getByText("Telegram input setup saved on this device.", { exact: true }).waitFor();
  await page.reload();
  await page.getByRole("button", { name: "Edit Telegram input", exact: true }).click();
  assert.equal(await page.getByLabel("Connection label", { exact: true }).inputValue(), "My research channels");
  await page.getByLabel("Connection label", { exact: true }).fill("Discard this edit");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.waitForFunction(() => document.activeElement?.textContent?.trim() === "Keep editing");
  await page.getByRole("button", { name: "Keep editing", exact: true }).click();
  await page.waitForFunction(() => document.activeElement?.id === "connection-label");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Discard changes", exact: true }).click();
  await page.getByRole("button", { name: "Output destinations", exact: false }).click();
  await page.getByRole("button", { name: "Prepare Telegram output", exact: true }).click();
  await page.getByLabel("Connection label", { exact: true }).fill("My brief destination");
  await page.getByRole("button", { name: "Save setup", exact: true }).click();
  const saved = await page.evaluate(key => JSON.parse(localStorage.getItem(key)), key);
  assert.equal(saved.connections["input:telegram"].label, "My research channels");
  assert.equal(saved.connections["output:telegram"].label, "My brief destination");
  await page.getByRole("button", { name: "Edit Telegram output", exact: true }).click();
  await page.getByRole("button", { name: "Remove local setup", exact: true }).click();
  await page.evaluate(key => { const state = JSON.parse(localStorage.getItem(key)); state.revision++; localStorage.setItem(key, JSON.stringify(state)); }, key);
  await page.getByRole("button", { name: "Remove setup", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "another tab" }).waitFor();
  await page.waitForFunction(() => document.activeElement?.id === "connection-label");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.reload();
  await page.getByRole("button", { name: "Output destinations", exact: false }).click();
  await page.getByRole("button", { name: "Edit Telegram output", exact: true }).click();
  await page.getByRole("button", { name: "Remove local setup", exact: true }).click();
  await page.getByRole("button", { name: "Remove setup", exact: true }).click();
  await page.getByRole("button", { name: "Prepare Telegram output", exact: true }).waitFor();
  await page.getByRole("button", { name: "Edit name", exact: true }).click();
  await page.getByLabel("Workspace name", { exact: true }).fill("Jakarta research desk");
  await page.getByRole("button", { name: "Save name", exact: true }).click();
  await page.getByRole("heading", { name: "Jakarta research desk", exact: true }).waitFor();

  // Stale editors cannot silently overwrite another tab's save.
  await page.getByRole("button", { name: "Edit name", exact: true }).click();
  await page.evaluate(key => { const state = JSON.parse(localStorage.getItem(key)); state.revision++; state.workspaceName = "Other tab workspace"; localStorage.setItem(key, JSON.stringify(state)); }, key);
  await page.getByLabel("Workspace name", { exact: true }).fill("Stale workspace name");
  await page.getByRole("button", { name: "Save name", exact: true }).click();
  await page.getByText("Setup changed in another tab. Close this editor and reopen it before saving.", { exact: true }).waitFor();
  await page.reload();
  await page.getByRole("heading", { name: "Other tab workspace", exact: true }).waitFor();
  for (const width of [375, 812, 1440]) {
    await page.setViewportSize({ width, height: width === 812 ? 375 : 1000 });
    for (const enlarge of [false, true]) {
      await page.goto(`${base}/app/settings/account`);
      await page.getByRole("button", { name: "Prepare X input", exact: true }).click();
      const editorParent = page.locator(".connection-item").filter({ has: page.getByRole("heading", { name: "X input setup", exact: true }) });
      assert.equal(await editorParent.getByRole("button", { name: "Prepare X input", exact: true }).count(), 1, "The editor must stay with its provider row.");
      await page.evaluate(async enlarge => { await document.fonts.ready; document.documentElement.style.fontSize = enlarge ? "200%" : "100%"; }, enlarge);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `Account editor overflow at ${width}, enlarged=${enlarge}`);
      if (!enlarge && process.env.BURSAWATCH_SCREENSHOT_DIR) await page.screenshot({ path: `${process.env.BURSAWATCH_SCREENSHOT_DIR}/connections-${width}.png`, fullPage: true });
    }
  }
  await page.evaluate(key => localStorage.setItem(key, "unreadable"), key);
  await page.reload();
  await page.getByText("Saved setup could not be read. Your existing data has been kept.", { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Prepare X input", exact: true }).isDisabled(), true);
  assert.equal(await page.evaluate(key => localStorage.getItem(key), key), "unreadable");
  assert.deepEqual(errors, []);
  console.log("Connections smoke passed: validation, save/reload, cancel, input/output isolation, removal, rename, stale-save protection, corrupt-store preservation and responsive editors at 200% text.");
} finally { await browser.close(); }
