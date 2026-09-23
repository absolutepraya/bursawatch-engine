import { AlertTriangle, Check, Clock3, Minus, Play, FileCheck2 } from "lucide-react";

import { classNames } from "@/lib/format";

const icons = {
  active: Play,
  healthy: Check,
  delivered: Check,
  "prepared-preview": FileCheck2,
  "no-change": Minus,
  running: Clock3,
  delayed: Clock3,
  degraded: AlertTriangle,
  disconnected: AlertTriangle,
  failed: AlertTriangle,
  paused: Minus,
};

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const Icon = icons[status as keyof typeof icons] ?? Minus;
  return (
    <span className={classNames("status-badge", `status-${status}`)}>
      <Icon aria-hidden="true" size={13} strokeWidth={2} />
      {label ?? status.replaceAll("-", " ")}
    </span>
  );
}
