import { robotsTxt } from "@/lib/robots";

export const dynamic = "force-static";

export function GET(): Response {
  return new Response(robotsTxt(process.env.BURSAWATCH_PREVIEW_MODE === "1"), {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
