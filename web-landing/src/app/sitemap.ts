import type { MetadataRoute } from "next";
import { SITE_ORIGIN } from "@/lib/robots";

export const dynamic = "force-static";

export default function sitemap(): MetadataRoute.Sitemap {
  return [{ url: `${SITE_ORIGIN}/`, changeFrequency: "weekly", priority: 1 }];
}
