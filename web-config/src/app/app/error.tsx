"use client";

import { AlertTriangle, RotateCcw } from "lucide-react";

export default function AppError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="page-wrap">
      <section className="empty-state" aria-labelledby="workspace-error-title">
        <AlertTriangle aria-hidden="true" size={28} />
        <h1 id="workspace-error-title">This view could not be loaded.</h1>
        <p>Please try again. Your saved settings have not been changed.</p>
        <button className="button primary" type="button" onClick={reset}>
          <RotateCcw aria-hidden="true" size={17} /> Retry
        </button>
      </section>
    </div>
  );
}
