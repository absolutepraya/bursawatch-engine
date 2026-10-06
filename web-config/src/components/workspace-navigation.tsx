"use client";

import {
  Activity,
  BookOpenCheck,
  BriefcaseBusiness,
  LayoutDashboard,
  LibraryBig,
  LogOut,
  Settings2,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef } from "react";
import { BrandMark } from "@/components/brand";
import "@/app/workspace-navigation.css";

export type WorkspaceView =
  "overview" | "sources" | "workflows" | "jobs" | "history" | "published" | "settings";

const destinations = [
  { id: "overview", label: "Overview", href: "/workspace", icon: LayoutDashboard },
  { id: "sources", label: "Sources", href: "/workspace/sources", icon: LibraryBig },
  { id: "workflows", label: "Workflows", href: "/workspace/workflows", icon: Workflow },
  { id: "jobs", label: "Jobs", href: "/workspace/jobs", icon: BriefcaseBusiness },
  { id: "history", label: "History", href: "/workspace/history", icon: Activity },
  { id: "published", label: "Published", href: "/workspace/published", icon: BookOpenCheck },
  { id: "settings", label: "Account", href: "/workspace/settings", icon: Settings2 },
] as const;

export function WorkspaceNavigation({
  view,
  onSignOut,
  signingOut,
  basePath = "/workspace",
  sampleMode = false,
}: {
  view: WorkspaceView;
  onSignOut?: () => void;
  signingOut: boolean;
  basePath?: string;
  sampleMode?: boolean;
}) {
  const navigation = useRef<HTMLElement>(null);

  useEffect(() => {
    const element = navigation.current;
    const workspace = element?.closest<HTMLElement>(".has-connected-navigation");
    if (!element || !workspace) return;

    // Text enlargement can wrap labels. Reserve the bar's actual height so
    // the final content and footer remain reachable above mobile navigation.
    const reserveNavigationSpace = () => {
      const height = `${Math.ceil(element.getBoundingClientRect().height)}px`;
      workspace.style.setProperty("--connected-navigation-height", height);
      document.documentElement.style.setProperty("--workspace-mobile-navigation-height", height);
    };
    reserveNavigationSpace();
    const observer = new ResizeObserver(reserveNavigationSpace);
    observer.observe(element);
    return () => {
      observer.disconnect();
      workspace.style.removeProperty("--connected-navigation-height");
      document.documentElement.style.removeProperty("--workspace-mobile-navigation-height");
    };
  }, []);

  return (
    <aside className={`connected-navigation${sampleMode ? " sample-workspace-navigation" : ""}`}>
      <Link
        href={basePath}
        className="connected-navigation-brand"
        aria-label={sampleMode ? "Bursawatch sample workspace" : "Bursawatch workspace"}
      >
        <BrandMark />
        <span>Bursawatch</span>
      </Link>
      {sampleMode ? <span className="sample-workspace-nav-label">Sample workspace</span> : null}

      <nav
        ref={navigation}
        className="connected-navigation-links"
        aria-label="Workspace navigation"
      >
        {destinations.map(({ id, label, icon: Icon }) => (
          <Link
            key={id}
            href={workspaceHref(basePath, id)}
            aria-current={view === id ? "page" : undefined}
          >
            <Icon size={19} strokeWidth={1.8} aria-hidden="true" />
            <span>{label}</span>
          </Link>
        ))}
      </nav>

      {!sampleMode && onSignOut ? (
        <div className="connected-navigation-footer">
          <button
            type="button"
            className="connected-navigation-signout"
            onClick={onSignOut}
            disabled={signingOut}
            aria-busy={signingOut}
          >
            <LogOut size={19} strokeWidth={1.8} aria-hidden="true" />
            <span>{signingOut ? "Signing out…" : "Sign out"}</span>
          </button>
        </div>
      ) : null}
    </aside>
  );
}

export function workspaceHref(basePath: string, view: WorkspaceView) {
  if (view === "overview") return basePath;
  if (view === "settings") return `${basePath}/${basePath === "/app" ? "account" : "settings"}`;
  return `${basePath}/${view}`;
}
