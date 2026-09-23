"use client";

import Image from "next/image";
import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Pause, Play, Plus, SlidersHorizontal, Trash2 } from "lucide-react";
import { PageHeading } from "@/components/page-heading";
import { useBrokerWorkspace } from "@/components/use-broker-workspace";
import { findBroker, type BrokerId } from "@/lib/brokers";
import { updateWorkspace } from "@/lib/broker-workspace";

export function WatchedSecurities() {
  const { state, ready, error: storageError } = useBrokerWorkspace();
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [removing, setRemoving] = useState<BrokerId | null>(null);
  function change(type: "toggle" | "remove", id: BrokerId) {
    try {
      updateWorkspace({ type, id });
      setRemoving(null);
      setError("");
      setMessage(
        type === "remove"
          ? "Security removed from this browser."
          : "Watch preference saved in this browser.",
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save your changes.");
    }
  }
  return (
    <div className="page-wrap">
      <PageHeading
        title="Watched securities"
        description="Your research sources, with your preferences."
        action={
          <Link className="button primary" href="/app/securities/add">
            <Plus size={18} aria-hidden="true" /> Add securities
          </Link>
        }
      />
      {(error || storageError) && (
        <p className="broker-error" role="alert">
          {error || storageError}
        </p>
      )}
      {message && (
        <p className="broker-save-status" role="status">
          {message}
        </p>
      )}
      {!ready ? (
        <p role="status">Loading your securities…</p>
      ) : !state.watches.length ? (
        <div className="broker-empty">
          <SlidersHorizontal size={28} strokeWidth={1.5} aria-hidden="true" />
          <h2>Start with the research you trust.</h2>
          <p>Add a securities firm, then choose what goes into your brief.</p>
          <Link className="button primary" href="/app/securities/add">
            Browse securities <ArrowRight size={18} aria-hidden="true" />
          </Link>
        </div>
      ) : (
        <div className="watched-broker-list">
          {state.watches.map((watch) => {
            const broker = findBroker(watch.brokerId)!;
            return (
              <article className="watched-broker" key={broker.id}>
                <div className="watched-broker-main">
                  <div className="broker-logo">
                    <Image src={broker.logo} alt={`${broker.name} logo`} width={176} height={40} />
                  </div>
                  <div>
                    <h2>{broker.name}</h2>
                    <p>
                      <span className="broker-goal-label">{watch.preferences.goal}</span> ·{" "}
                      {watch.preferences.priceSummary ? "Price summary on" : "Research only"} ·{" "}
                      {watch.preferences.language === "id" ? "Bahasa Indonesia" : "English"}
                    </p>
                  </div>
                  <span className={`broker-watch-state ${watch.paused ? "paused" : ""}`}>
                    {watch.paused ? "Paused" : "Watching"}
                  </span>
                </div>
                <div className="watched-broker-actions">
                  <Link
                    className="button secondary small"
                    href={`/app/configuration?firm=${broker.id}`}
                  >
                    <SlidersHorizontal size={16} aria-hidden="true" /> Configure
                  </Link>
                  <button
                    className="button ghost small"
                    onClick={() => change("toggle", broker.id)}
                  >
                    {watch.paused ? (
                      <Play size={15} aria-hidden="true" />
                    ) : (
                      <Pause size={15} aria-hidden="true" />
                    )}
                    {watch.paused ? "Resume" : "Pause"}
                  </button>
                  <button
                    className="icon-button"
                    aria-label={`Remove ${broker.name}`}
                    onClick={() => setRemoving(broker.id)}
                  >
                    <Trash2 size={17} aria-hidden="true" />
                  </button>
                </div>
                {removing === broker.id && (
                  <div
                    className="broker-remove-confirm"
                    role="group"
                    aria-label={`Confirm removal of ${broker.name}`}
                  >
                    <p>Remove {broker.shortName}? Its saved preferences will be removed too.</p>
                    <button className="button secondary small" onClick={() => setRemoving(null)}>
                      Keep security
                    </button>
                    <button
                      className="button secondary small"
                      onClick={() => change("remove", broker.id)}
                    >
                      Remove security
                    </button>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
      <div className="broker-related">
        <span>Following individual stocks too?</span>
        <Link className="text-link" href="/app/watchlist">
          Open stock watchlist <ArrowRight size={15} aria-hidden="true" />
        </Link>
      </div>
    </div>
  );
}
