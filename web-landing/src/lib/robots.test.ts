import { describe, expect, it } from "vitest";
import { robotsTxt, SITE_ORIGIN } from "./robots";

describe("robots.txt", () => {
  it("welcomes crawlers in production and points at the sitemap", () => {
    const body = robotsTxt(false);
    expect(body).toContain("User-agent: *");
    expect(body).toContain("Allow: /");
    expect(body).toContain("Content-Signal: search=yes, ai-input=yes");
    expect(body).toContain(`Sitemap: ${SITE_ORIGIN}/sitemap.xml`);
    expect(body).not.toMatch(/^Disallow: \/$/m);
  });
  it("leaves ai-train unset so it is neither granted nor restricted", () => {
    expect(robotsTxt(false)).not.toContain("ai-train");
  });
  it("closes preview builds to every crawler", () => {
    expect(robotsTxt(true)).toBe("User-agent: *\nDisallow: /\n");
  });
});
