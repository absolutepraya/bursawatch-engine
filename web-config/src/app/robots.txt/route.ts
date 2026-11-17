export const dynamic = "force-static";

/** The workspace is private, so no crawler has any business indexing it. */
export function GET(): Response {
  return new Response("User-agent: *\nDisallow: /\n", {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
