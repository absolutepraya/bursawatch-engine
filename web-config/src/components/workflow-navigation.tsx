"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const views = [
  { href: "/app/automations/custom", label: "Your workflows" },
  { href: "/app/automations/library", label: "Library" },
  { href: "/app/automations", label: "Schedules" },
  { href: "/app/activity", label: "History" },
];

export function WorkflowNavigation() {
  const pathname = usePathname();

  return (
    <nav className="preferences-nav workflow-nav" aria-label="Workflow views">
      {views.map(({ href, label }) => (
        <Link key={href} href={href} aria-current={pathname === href ? "page" : undefined}>
          {label}
        </Link>
      ))}
    </nav>
  );
}
