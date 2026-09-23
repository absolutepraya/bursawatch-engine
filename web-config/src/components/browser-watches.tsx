"use client";

import { useSyncExternalStore, useState } from "react";
import { ArrowRight, Pause, Play } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { hostedDemo } from "@/lib/demo-mode";
import { readBrowserWatches, toggleBrowserWatch } from "@/lib/browser-demo";

const subscribe = (callback: () => void) => {
  window.addEventListener("storage", callback);
  window.addEventListener("bursawatch-saved", callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener("bursawatch-saved", callback);
  };
};
const snapshot = () => {
  try {
    return localStorage.getItem("bursawatch-demo-watches-v1") ?? "[]";
  } catch {
    return "[]";
  }
};

export function BrowserWatches() {
  const searchParams = useSearchParams();
  useSyncExternalStore(subscribe, snapshot, () => "[]");
  const [error, setError] = useState("");
  const ready = useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
  if (!hostedDemo || !ready) return null;
  const watches = readBrowserWatches();
  if (!watches.length)
    return (
      <Link className="demo-start" href="/app/automations/new">
        <span>
          <strong>Create your first watch</strong>
          <span>Choose your stocks, conditions, and schedule.</span>
        </span>
        <ArrowRight size={19} aria-hidden="true" />
      </Link>
    );
  return (
    <section className="browser-watches" aria-label="Your saved watches">
      {searchParams.has("created") ? (
        <p className="saved-confirmation" role="status">
          Watch saved.
        </p>
      ) : null}
      <div className="section-heading">
        <div>
          <h2>Your watches</h2>
          <p>Your saved stocks and alert conditions.</p>
        </div>
        <span>{watches.length} saved</span>
      </div>
      {error ? <p role="alert">{error}</p> : null}
      {watches.length ? (
        watches.map((watch) => (
          <article className="browser-watch" key={watch.id}>
            <div>
              <strong>{watch.name}</strong>
              <span>
                {watch.symbols.join(" · ")} · {watch.scheduleTime} WIB · {watch.threshold}%
                threshold
              </span>
            </div>
            <span>{watch.paused ? "Paused" : "Saved"}</span>
            <button
              className="button secondary small"
              type="button"
              onClick={() => {
                try {
                  toggleBrowserWatch(watch.id);
                  setError("");
                } catch {
                  setError("Browser storage is unavailable. Enable site storage and try again.");
                }
              }}
            >
              {watch.paused ? (
                <Play size={15} aria-hidden="true" />
              ) : (
                <Pause size={15} aria-hidden="true" />
              )}
              {watch.paused ? "Resume" : "Pause"}
            </button>
          </article>
        ))
      ) : (
        <Link className="demo-empty" href="/app/automations/new">
          <span>Choose your stocks and build your first watch.</span>
          <ArrowRight aria-hidden="true" size={18} />
        </Link>
      )}
    </section>
  );
}
