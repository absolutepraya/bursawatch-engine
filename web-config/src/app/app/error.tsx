"use client";

import { AlertTriangle, RotateCcw } from "lucide-react";

export default function AppError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="sample-workspace-fallback">
      <section className="control-empty" aria-labelledby="workspace-error-title">
        <AlertTriangle aria-hidden="true" size={28} />
        <h1 id="workspace-error-title">This view could not be loaded.</h1>
        <p>Please try again. Sample changes are held in this page session.</p>
        <button className="button primary" type="button" onClick={reset}>
          <RotateCcw aria-hidden="true" size={17} /> Retry
        </button>
      </section>
    </main>
  );
}
