import { notFound, redirect } from "next/navigation";
import { Suspense } from "react";
import { WorkspaceApp } from "@/components/workspace-app";
import { BrandMark } from "@/components/brand";
import { publicAuthSettings } from "@/lib/web-environment";

const allowed = [
  "overview",
  "sources",
  "workflows",
  "jobs",
  "history",
  "published",
  "schedules",
  "settings",
] as const;

// Only the public shell and public Auth settings are built into these pages.
// User sessions and every protected record are fetched in the browser after
// sign-in; /api/control keeps its independent no-store/authentication boundary.
export const dynamicParams = false;
export function generateStaticParams() {
  return [{ view: [] }, ...allowed.map((view) => ({ view: [view] }))];
}

export default async function WorkspacePage({ params }: { params: Promise<{ view?: string[] }> }) {
  const { view = [] } = await params;
  const active = view[0] ?? "overview";
  if (view.length > 1 || !allowed.includes(active as (typeof allowed)[number])) notFound();
  // Existing bookmarks keep working while schedules move into each workflow.
  if (active === "schedules") redirect("/workspace/jobs");
  const settings = publicAuthSettings({
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL,
    NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
  });
  return (
    <Suspense
      fallback={
        <main className="workspace-auth" aria-busy="true">
          <div className="workspace-brand">
            <BrandMark />
            <span>Bursawatch</span>
          </div>
          <div className="workspace-auth-content">
            <p role="status">Opening your workspace…</p>
          </div>
        </main>
      }
    >
      <WorkspaceApp
        settings={settings}
        view={active as Exclude<(typeof allowed)[number], "schedules">}
      />
    </Suspense>
  );
}
