"use client";

import { useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";
import type { WorkspaceProgress } from "@/lib/workspace-loader";
import { watcherNames } from "@/lib/watcher-fields";
import "@/app/workspace-loading.css";

export type LoadingRequest = {
  label: string;
  status: "loading" | "ready" | "error";
  message?: string;
};

export function WorkspaceLoading({
  title = "Loading your workspace",
  progress,
  requests,
  compact = false,
}: {
  title?: string;
  progress?: WorkspaceProgress | null;
  requests?: LoadingRequest[];
  compact?: boolean;
}) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(
      () => setElapsed(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, []);
  const slow = elapsed >= 8;
  const entries =
    requests ??
    progress?.entries.map((entry) => ({
      label: `${watcherNames[entry.watcherId] ?? "Workflow"} · ${entry.resource === "jobs" ? "schedules" : "history"}`,
      status: entry.status,
      message: entry.message,
    }));
  const total = entries?.length ?? 0;
  const completed = entries?.filter((entry) => entry.status !== "loading").length ?? 0;
  return (
    <section
      className={`workspace-progress${compact ? " is-compact" : ""}`}
      aria-label="Loading status"
    >
      <div className="workspace-progress-heading" role="status">
        {elapsed >= 2 ? (
          <LoaderCircle className="workspace-progress-spinner" size={20} aria-hidden="true" />
        ) : null}
        <div>
          <strong>{slow ? "This is taking longer than usual" : title}</strong>
          <p>
            {total > 0
              ? `${completed} of ${total} requests finished.`
              : "Waiting for the workspace service."}
          </p>
        </div>
      </div>
      <div className="workspace-progress-meter">
        <div
          className={`workspace-progress-track${total === 0 ? " is-indeterminate" : ""}`}
          role="progressbar"
          aria-label="Loading progress"
          aria-valuemin={total > 0 ? 0 : undefined}
          aria-valuemax={total > 0 ? total : undefined}
          aria-valuenow={total > 0 ? completed : undefined}
        >
          <span style={total > 0 ? { width: `${(completed / total) * 100}%` } : undefined} />
        </div>
        {total > 0 ? (
          <span className="workspace-progress-count" aria-hidden="true">
            {completed} / {total}
          </span>
        ) : null}
      </div>
      {!compact && elapsed < 8 ? (
        <div className="workspace-skeleton" aria-hidden="true">
          <span />
          <div>
            <span />
            <span />
            <span />
          </div>
          <span />
          <span />
        </div>
      ) : null}
      {slow ? (
        <div className="workspace-progress-slow">
          <p>
            Waiting {elapsed}s. You can switch pages. Each request has a time limit; failed requests
            will show a recovery action.
          </p>
          <details open>
            <summary>Request details</summary>
            {!entries?.length ? (
              <p>
                {progress?.phase === "catalog" ? "Workflow list" : title.replace(/…$/, "")} ·
                awaiting response
              </p>
            ) : (
              <ul>
                {entries.map((entry) => (
                  <li key={entry.label}>
                    <span>{entry.label}</span>
                    <span>
                      {entry.status === "ready"
                        ? "Loaded"
                        : entry.status === "error"
                          ? (entry.message ?? "Could not load")
                          : "Pending"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </details>
        </div>
      ) : null}
    </section>
  );
}
