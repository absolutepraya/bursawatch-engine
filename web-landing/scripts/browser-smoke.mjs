import assert from "node:assert/strict";
import { chromium } from "playwright";

const base = process.env.BURSAWATCH_TEST_URL ?? "http://localhost:3200";
if (!["localhost", "127.0.0.1", "[::1]"].includes(new URL(base).hostname)) {
  throw new Error("Browser checks must target an isolated local landing server.");
}
const workspace = process.env.BURSAWATCH_CONFIG_URL ?? "http://localhost:3100";
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
});
const page = await browser.newPage({ reducedMotion: "reduce" });
page.setDefaultTimeout(10000);
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
try {
  await page.goto(base);
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to main content", exact: true });
  assert.equal(await skip.evaluate(element => element === document.activeElement && getComputedStyle(element).opacity === "1"), true);
  await page.keyboard.press("Tab");
  assert.equal(await skip.evaluate(element => getComputedStyle(element).opacity), "0");
  const market = page.getByRole("region", { name: "Interactive example watch" });
  const price = market.getByRole("slider", { name: /Inspect a price/ });
  const threshold = market.getByLabel("Daily rise at least");
  assert.equal(await market.getByRole("button", { name: /price story/ }).count(), 0);
  assert.equal(await market.locator(".chart-price-line").evaluate(element => getComputedStyle(element).animationName), "none");
  await price.focus();
  await page.keyboard.press("Home");
  assert.match(await price.getAttribute("aria-valuetext"), /09:00 WIB, Rp4,100, \+0.0%/);
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  assert.match(await price.getAttribute("aria-valuetext"), /09:40 WIB, Rp4,080, -0.5%/);
  assert.equal(await market.locator(".price-value .stock-change").getAttribute("data-negative"), "true");
  await market.getByRole("button", { name: "Follow the move", exact: true }).click();
  await market.getByRole("heading", { name: "Follow BBRI, one observation at a time." }).waitFor();
  assert.equal(await market.locator(".chart-rule").getAttribute("data-visible"), "false");
  await market.getByRole("button", { name: "Check your rule", exact: true }).click();
  await market.getByRole("heading", { name: "Check for a rise of at least 3%." }).waitFor();
  assert.equal(await market.locator(".chart-rule").getAttribute("data-visible"), "true");
  await market.getByRole("button", { name: /TLKM/ }).click();
  await market.getByRole("heading", { name: "TLKM stayed within your threshold." }).waitFor();
  await market.getByRole("button", { name: /BMRI/ }).click();
  await threshold.selectOption("5");
  await market.getByRole("heading", { name: "BMRI stayed within your threshold." }).waitFor();
  await threshold.selectOption("2");
  await market.getByRole("heading", { name: "BMRI crossed the 2% threshold." }).waitFor();
  await market.getByText("View sample prices", { exact: true }).click();
  assert.equal(await market.getByRole("row").count(), 17);
  assert.match(await market.getByRole("row").last().innerText(), /15:30\s+Rp6,350\s+\+4.1%/);
  await market.getByText("View sample prices", { exact: true }).click();
  await threshold.selectOption("3");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await market.getByRole("button", { name: "Replay price story" }).click();
  await market.getByRole("button", { name: "Pause price story" }).click();
  await page.waitForTimeout(3400);
  assert.equal(await market.getAttribute("data-stage"), "0", "Pausing keeps the current price stage");
  assert.equal(await market.locator(".chart-price-line").evaluate(element => getComputedStyle(element).animationPlayState), "paused");
  await market.getByRole("button", { name: "Resume price story" }).click();
  await page.waitForFunction(() => document.querySelector(".market-preview")?.getAttribute("data-stage") === "1");
  await market.getByRole("button", { name: "Keep the context", exact: true }).click();
  assert.equal(await market.getAttribute("data-playing"), "false", "Manual price stage stops playback");
  await market.getByRole("button", { name: "Replay price story" }).click();
  await market.getByRole("button", { name: "Replay price story" }).waitFor({ timeout: 12000 });
  assert.equal(await market.getAttribute("data-stage"), "2", "Price story ends without looping");
  await market.getByRole("button", { name: "Replay price story" }).click();
  await page.locator("footer").scrollIntoViewIfNeeded();
  await page.waitForFunction(() => document.querySelector(".market-preview")?.getAttribute("data-playing") === "false");
  assert.equal(await market.getByRole("button", { name: "Resume price story" }).count(), 1, "Offscreen story pauses");
  await market.getByRole("button", { name: "Resume price story" }).click();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await market.getByRole("heading", { name: "BMRI crossed the 3% threshold." }).waitFor();
  assert.equal(await market.getAttribute("data-animated"), "false", "Reduced motion immediately restores the complete static chart");
  const walkthrough = page.getByRole("region", { name: "How Bursawatch works" });
  const scene = walkthrough.locator("#walkthrough-scene");
  const sourceStep = walkthrough.getByRole("button", { name: "Choose sources" });
  const rulesStep = walkthrough.getByRole("button", { name: "Set your rules" });
  const briefStep = walkthrough.getByRole("button", { name: "Read your brief" });
  assert.equal(
    await walkthrough.getByRole("button", { name: /Play walkthrough/ }).count(),
    0,
    "Reduced motion offers manual stages only",
  );
  assert.equal(await scene.getAttribute("data-stage"), "0");
  await rulesStep.focus();
  await page.keyboard.press("Enter");
  assert.equal(await rulesStep.getAttribute("aria-pressed"), "true");
  await walkthrough.getByText("Concise, with source links", { exact: true }).waitFor();
  await briefStep.focus();
  await page.keyboard.press("Space");
  await walkthrough.getByRole("heading", { name: "BBRI: a new research note." }).waitFor();
  assert.equal(
    await scene
      .locator(".demo-scene-content")
      .evaluate((element) => getComputedStyle(element).animationName),
    "none",
    "Reduced motion removes scene animation",
  );
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await walkthrough.getByRole("button", { name: "Replay walkthrough" }).click();
  assert.equal(await scene.getAttribute("data-stage"), "0");
  await walkthrough.getByRole("button", { name: "Pause walkthrough" }).click();
  await page.waitForTimeout(6700);
  assert.equal(await scene.getAttribute("data-stage"), "0", "Paused playback must not advance");
  await walkthrough.getByRole("button", { name: "Resume walkthrough" }).click();
  await page.waitForFunction(
    () => document.querySelector("#walkthrough-scene")?.getAttribute("data-stage") === "1",
  );
  await briefStep.click();
  assert.equal(
    await walkthrough.getByRole("button", { name: "Pause walkthrough" }).count(),
    0,
    "Manual stage selection pauses playback",
  );
  await walkthrough.getByRole("button", { name: "Replay walkthrough" }).click();
  await page.waitForFunction(
    () => document.querySelector("#walkthrough-scene")?.getAttribute("data-stage") === "2",
    undefined,
    { timeout: 15000 },
  );
  await walkthrough.getByRole("button", { name: "Pause walkthrough" }).click();
  await page.waitForTimeout(6700);
  assert.equal(await scene.getAttribute("data-stage"), "2", "Pausing the brief keeps it visible");
  await walkthrough.getByRole("button", { name: "Resume walkthrough" }).click();
  assert.equal(await scene.getAttribute("data-stage"), "2", "Resuming the brief must not restart");
  await walkthrough.getByRole("button", { name: "Replay walkthrough" }).waitFor({ timeout: 8000 });
  assert.equal(
    await scene.getAttribute("data-stage"),
    "2",
    "Playback finishes on the brief without looping",
  );
  await walkthrough.getByRole("button", { name: "Replay walkthrough" }).click();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.waitForTimeout(6700);
  assert.equal(
    await scene.getAttribute("data-stage"),
    "0",
    "Enabling reduced motion must stop playback",
  );
  await page.getByRole("button", { name: /TLKM/ }).click();
  await page.getByRole("heading", { name: "TLKM stayed within your threshold." }).waitFor();
  await page.getByRole("button", { name: /BMRI/ }).click();
  await page.getByRole("heading", { name: "BMRI crossed the 3% threshold." }).waitFor();
  for (const [name, path] of [
    ["Build your brief", "/workspace"],
    ["Open workspace", "/workspace"],
    ["Explore sample", "/app/discover"],
    ["Configure your sources", "/workspace"],
    ["Get started", "/workspace"],
  ]) {
    assert.equal(
      await page.getByRole("link", { name, exact: true }).getAttribute("href"),
      new URL(path, workspace).href,
    );
  }
  for (const width of [375, 812, 1440]) {
    await page.setViewportSize({ width, height: width === 812 ? 375 : 1000 });
    await page.evaluate(() => document.fonts.ready);
    for (const size of ["100%", "200%"]) {
      await page.evaluate((value) => {
        document.documentElement.style.fontSize = value;
      }, size);
      for (const step of [sourceStep, rulesStep, briefStep]) {
        await step.click();
        assert.equal(
          await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
          false,
          `${width}px at ${size} text for ${await step.innerText()}`,
        );
        const target = await step.boundingBox();
        assert.ok(
          target && target.height >= 44 && target.width >= 44,
          "Stage controls meet 44px touch target minimum",
        );
      }
      await market.getByText("View sample prices", { exact: true }).click();
      for (const symbol of ["BBRI", "TLKM", "BMRI"]) {
        await market.getByRole("button", { name: new RegExp(symbol) }).click();
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${symbol} chart/table fits ${width}px with ${size} text`);
      }
      for (const control of await market.locator("button, input, select, summary").all()) {
        const target = await control.boundingBox();
        assert.ok(target && target.height >= 44 && target.width >= 44, "Chart controls meet 44px touch target minimum");
      }
      await market.getByText("View sample prices", { exact: true }).click();
    }
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "";
    });
  }
  assert.match(
    await page.locator("#price-watch-title").textContent(),
    /signal\.\s+Not/,
    "The mobile heading retains a word boundary when its line break is hidden",
  );
  const auto = await browser.newPage({ viewport: { width: 375, height: 667 }, reducedMotion: "no-preference" });
  await auto.goto(base);
  const autoScene = auto.locator("#walkthrough-scene");
  assert.equal(await autoScene.getAttribute("data-playing"), "false", "Autoplay waits for the scene to enter the viewport");
  await autoScene.scrollIntoViewIfNeeded();
  await auto.waitForFunction(() => document.querySelector("#walkthrough-scene")?.getAttribute("data-playing") === "true");
  assert.equal(await autoScene.locator(".demo-arrival").evaluate(element => getComputedStyle(element).animationName), "demo-event-in", "The source update animates inside the scene");
  await auto.getByRole("button", { name: "Set your rules" }).click();
  assert.equal(await autoScene.getAttribute("data-animated"), "false", "Manual selection shows complete static content");
  await autoScene.scrollIntoViewIfNeeded();
  await auto.waitForTimeout(6700);
  assert.equal(await autoScene.getAttribute("data-stage"), "1", "Viewport entry never overrides manual selection");
  await auto.close();
  assert.deepEqual(errors, []);
  console.log(
    "Landing smoke passed: finite price/walkthrough playback, pause/resume/replay, offscreen pause, keyboard price/stage controls, reduced motion, thresholds, price table, cross-app URLs, three viewports and 200% text.",
  );
} finally {
  await browser.close();
}
