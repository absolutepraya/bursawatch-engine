"use client";

import { useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";
import type { WorkspaceProgress } from "@/lib/workspace-loader";
import { watcherNames } from "@/lib/watcher-fields";
import "@/app/workspace-loading.css";

export function WorkspaceLoading({
  title = "Loading your workspace",
  progress,
  compact = false,
}: {
  title?: string;
  progress?: WorkspaceProgress | null;
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
            {progress?.phase === "details"
              ? `${progress.completed} of ${progress.total} status requests finished.`
              : "Waiting for the workspace service."}
          </p>
        </div>
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
            {!progress || progress.phase === "catalog" ? (
              <p>
                {progress?.phase === "catalog" ? "Workflow list" : title.replace(/…$/, "")} ·
                awaiting response
              </p>
            ) : (
              <ul>
                {progress.entries.map((entry) => (
                  <li key={`${entry.watcherId}:${entry.resource}`}>
                    <span>
                      {watcherNames[entry.watcherId] ?? "Workflow"} ·{" "}
                      {entry.resource === "jobs" ? "schedules" : "history"}
                    </span>
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
