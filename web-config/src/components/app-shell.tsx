"use client";

import { Activity, Compass, ListChecks, Menu, Settings, Workflow, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRef, useState } from "react";
import { Brand } from "@/components/brand";
import { hostedDemo } from "@/lib/demo-mode";

const navItems = [
  { href: "/app/insights", label: "Insights", icon: Activity },
  { href: "/app/discover", label: "Discover", icon: Compass },
  { href: "/app/following", label: "Following", icon: ListChecks },
  { href: "/app/automations/custom", label: "Workflows", icon: Workflow },
  { href: "/app/settings", label: "Settings", icon: Settings },
];
function isCurrent(pathname: string, href: string) {
  const matches = (path: string) => pathname === path || pathname.startsWith(`${path}/`);
  if (matches("/app/sources") || matches("/app/securities/add")) {
    return href === "/app/discover";
  }
  if (matches("/app/securities") || matches("/app/configuration") || matches("/app/logs")) {
    return href === "/app/following";
  }
  if (matches("/app/activity") || matches("/app/workflows") || matches("/app/automations")) {
    return href === "/app/automations/custom";
  }
  if (matches("/app/overview") || matches("/app/watchlist") || pathname === "/app") {
    return href === "/app/insights";
  }
  return matches(href);
}
function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav className="primary-nav" aria-label="Workspace navigation">
      {navItems.map(({ href, label, icon: Icon }) => (
        <Link
          key={href}
          href={href}
          aria-current={isCurrent(pathname, href) ? "page" : undefined}
          onClick={onNavigate}
        >
          <Icon aria-hidden="true" size={19} strokeWidth={1.8} />
          <span>{label}</span>
        </Link>
      ))}
    </nav>
  );
}
export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const pathname = usePathname();
  const pageName =
    pathname === "/app/setup"
      ? "Setup"
      : pathname === "/app/securities/add"
        ? "Add securities"
        : pathname.includes("/new")
          ? "New workflow"
          : (navItems.find((item) => isCurrent(pathname, item.href))?.label ?? "Workspace");
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <aside className="sidebar">
        <Brand compact />
        <NavLinks />
        <div className="sidebar-footer">
          <p>Sectors connection pending</p>
        </div>
      </aside>
      <header className="mobile-header">
        <Brand compact />
        <button
          ref={menuButton}
          className="icon-button"
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls="mobile-menu"
          aria-label={open ? "Close navigation" : "Open navigation"}
        >
          {open ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
        </button>
      </header>
      {open ? (
        <div
          className="mobile-menu"
          id="mobile-menu"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setOpen(false);
              menuButton.current?.focus();
            }
          }}
        >
          <NavLinks onNavigate={() => setOpen(false)} />
        </div>
      ) : null}
      <main id="main-content" className="app-main" tabIndex={-1}>
        <div className="app-topbar">
          <p>
            Workspace <span aria-hidden="true">/</span> {pageName}
          </p>
          <span className="demo-chip">{hostedDemo ? "Sample workspace" : "Local workspace"}</span>
          <Link href="/" className="workspace-home">
            Bursawatch home
          </Link>
        </div>
        {children}
      </main>
      <nav className="bottom-nav" aria-label="Mobile primary navigation">
        {navItems.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            aria-current={isCurrent(pathname, href) ? "page" : undefined}
            onClick={() => setOpen(false)}
          >
            <Icon aria-hidden="true" size={20} strokeWidth={1.8} />
            <span>{label}</span>
          </Link>
        ))}
      </nav>
    </div>
  );
}
