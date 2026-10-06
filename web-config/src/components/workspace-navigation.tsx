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
}: {
  view: WorkspaceView;
  onSignOut: () => void;
  signingOut: boolean;
}) {
  const navigation = useRef<HTMLElement>(null);

  useEffect(() => {
    const element = navigation.current;
    const workspace = element?.closest<HTMLElement>(".has-connected-navigation");
    if (!element || !workspace) return;

    // Text enlargement can increase the row height. Reserve it and keep the
    // current destination in view so content remains reachable above the bar.
    const keepCurrentDestinationVisible = () => {
      const activeLink = element.querySelector<HTMLElement>('[aria-current="page"]');
      if (!activeLink) return;

      const navigationStyle = window.getComputedStyle(element);
      const navigationBounds = element.getBoundingClientRect();
      const contentLeft =
        navigationBounds.left +
        element.clientLeft +
        (Number.parseFloat(navigationStyle.paddingLeft) || 0);
      const contentRight =
        navigationBounds.left +
        element.clientLeft +
        element.clientWidth -
        (Number.parseFloat(navigationStyle.paddingRight) || 0);
      const activeBounds = activeLink.getBoundingClientRect();

      if (activeBounds.left < contentLeft) {
        element.scrollLeft += activeBounds.left - contentLeft;
      } else if (activeBounds.right > contentRight) {
        element.scrollLeft += activeBounds.right - contentRight;
      }
    };

    const reserveNavigationSpace = () => {
      const height = `${Math.ceil(element.getBoundingClientRect().height)}px`;
      workspace.style.setProperty("--connected-navigation-height", height);
      document.documentElement.style.setProperty("--workspace-mobile-navigation-height", height);
      keepCurrentDestinationVisible();
    };
    reserveNavigationSpace();
    const observer = new ResizeObserver(reserveNavigationSpace);
    observer.observe(element);
    return () => {
      observer.disconnect();
      workspace.style.removeProperty("--connected-navigation-height");
      document.documentElement.style.removeProperty("--workspace-mobile-navigation-height");
    };
  }, [view]);

  return (
    <aside className="connected-navigation">
      <Link
        href="/workspace"
        className="connected-navigation-brand"
        aria-label="Bursawatch workspace"
      >
        <BrandMark />
        <span>Bursawatch</span>
      </Link>

      <nav
        ref={navigation}
        className="connected-navigation-links"
        aria-label="Workspace navigation"
      >
        {destinations.map(({ id, label, href, icon: Icon }) => (
          <Link key={id} href={href} aria-current={view === id ? "page" : undefined}>
            <Icon size={19} strokeWidth={1.8} aria-hidden="true" />
            <span>{label}</span>
          </Link>
        ))}
      </nav>

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
    </aside>
  );
}
