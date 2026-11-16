export const SITE_ORIGIN = "https://bursawatch.abhipraya.dev";

/**
 * Crawler policy for the public landing page. Production welcomes search and
 * AI retrieval; `ai-train` is omitted so it is neither granted nor restricted.
 * Preview builds are closed to every crawler.
 */
export function robotsTxt(preview: boolean): string {
  if (preview) return "User-agent: *\nDisallow: /\n";
  return [
    "User-agent: *",
    "Content-Signal: search=yes, ai-input=yes",
    "Allow: /",
    "",
    `Sitemap: ${SITE_ORIGIN}/sitemap.xml`,
    "",
  ].join("\n");
}
