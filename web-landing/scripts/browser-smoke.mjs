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
  assert.equal(await page.locator("html").getAttribute("lang"), "id");
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Langsung ke konten", exact: true });
  assert.equal(
    await skip.evaluate(
      (element) => element === document.activeElement && getComputedStyle(element).opacity === "1",
    ),
    true,
  );
  await page.keyboard.press("Tab");
  assert.equal(await skip.evaluate((element) => getComputedStyle(element).opacity), "0");

  for (const [name, path] of [
    ["Workspace demo", "/app"],
    ["Masuk workspace", "/workspace"],
    ["Coba workspace demo", "/app"],
    ["Udah punya akun? Masuk workspace", "/workspace"],
  ]) {
    for (const link of await page.getByRole("link", { name, exact: true }).all()) {
      assert.equal(await link.getAttribute("href"), new URL(path, workspace).href, name);
    }
  }
  const demoLinks = page.getByRole("link", { name: "Coba Discord demo", exact: true });
  assert.equal(await demoLinks.count(), 2);
  for (const link of await demoLinks.all()) {
    assert.match(await link.getAttribute("href"), /^https:\/\/discord\.(gg|com)\//);
    assert.equal(await link.getAttribute("rel"), "noreferrer");
  }

  for (const label of [
    "Contoh pesan asli Bursawatch di channel id-stocks-news",
    "Contoh forum swing board Bursawatch",
    "Contoh thread trading plan ENRG",
    "Contoh morning brief Bursawatch Pagi",
  ]) {
    await page.getByRole("figure", { name: label }).waitFor();
  }
  assert.equal(await page.getByRole("img", { name: /^Contoh pengaturan:/ }).count(), 4);
  await page.getByText("contoh dengan angka dummy", { exact: false }).waitFor();
  for (const image of await page.locator("img").all()) {
    await image.scrollIntoViewIfNeeded();
    assert.ok(
      await image.evaluate((element) => element.complete && element.naturalWidth > 0),
      `Image loads: ${await image.getAttribute("src")}`,
    );
  }

  for (const width of [375, 812, 1440]) {
    await page.setViewportSize({ width, height: width === 812 ? 375 : 1000 });
    await page.evaluate(() => document.fonts.ready);
    for (const size of ["100%", "200%"]) {
      await page.evaluate((value) => {
        document.documentElement.style.fontSize = value;
      }, size);
      assert.equal(
        await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
        false,
        `No horizontal scroll at ${width}px with ${size} text`,
      );
      for (const control of await page.locator("main a, header a, footer a").all()) {
        if (!(await control.isVisible())) continue;
        const target = await control.boundingBox();
        assert.ok(
          target && target.height >= 44,
          `Link meets the 44px target at ${width}px: ${await control.innerText()}`,
        );
      }
    }
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "";
    });
  }
  // Reduced motion: no animation anywhere, nothing hidden, motion never armed.
  await page.goto(base);
  assert.equal(await page.locator("html").getAttribute("data-motion"), null);
  assert.equal(
    await page
      .locator(".hero-sources li")
      .first()
      .evaluate((el) => getComputedStyle(el).animationName),
    "none",
    "Reduced motion removes the hero sequence",
  );
  assert.notEqual(
    await page
      .locator(".cfg-seg")
      .first()
      .evaluate((el) => getComputedStyle(el, "::before").transform),
    "matrix(1, 0, 0, 1, 0, 0)",
    "Reduced motion shows the finished weekly switch",
  );

  // Motion allowed: the hero plays once and every scroll beat ends fully visible.
  const motion = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    reducedMotion: "no-preference",
  });
  motion.setDefaultTimeout(10000);
  motion.on("pageerror", (error) => errors.push(error.message));
  await motion.goto(base);
  await motion.waitForFunction(() => document.documentElement.dataset.motion === "on");
  assert.notEqual(
    await motion
      .locator(".hero-sources li")
      .first()
      .evaluate((el) => getComputedStyle(el).animationName),
    "none",
    "The hero sequence runs when motion is allowed",
  );
  assert.equal(
    await motion.locator(".pain-grid").getAttribute("data-inview"),
    null,
    "Beats below the fold wait for the viewport",
  );
  for (const beat of await motion.locator("[data-reveal], [data-stagger], [data-seq]").all()) {
    await beat.scrollIntoViewIfNeeded();
    const handle = await beat.elementHandle();
    await motion.waitForFunction((el) => el.hasAttribute("data-inview"), handle);
  }
  await motion.waitForTimeout(2500);
  for (const element of await motion
    .locator("[data-reveal], [data-stagger] > *, .swing-update, .lp-bisa")
    .all()) {
    assert.ok(
      (await element.evaluate((el) => Number(getComputedStyle(el).opacity))) > 0.99,
      "Every scroll beat finishes fully visible",
    );
  }
  await motion.close();
  assert.deepEqual(errors, []);
  console.log(
    "Landing smoke passed: skip link, Indonesian locale, Discord demo, workspace demo and sign-in URLs, config illustrations, labelled Discord recreations, images, three viewports, 200% text, 44px targets, hero sequence, scroll beats and reduced motion.",
  );
} finally {
  await browser.close();
}
