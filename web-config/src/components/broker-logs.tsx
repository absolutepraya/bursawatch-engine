"use client";

import Link from "next/link";
import { ArrowRight, Check, SlidersHorizontal } from "lucide-react";
import { PageHeading } from "@/components/page-heading";
import { useBrokerWorkspace } from "@/components/use-broker-workspace";
import { findBroker } from "@/lib/brokers";

const actions = {
  added: "Added to watched securities",
  configured: "Configuration saved",
  paused: "Watch paused",
  resumed: "Watch resumed",
  removed: "Removed from watched securities",
};
export function BrokerLogs() {
  const { state, ready, error } = useBrokerWorkspace();
  return (
    <div className="page-wrap">
      <PageHeading
        title="Logs"
        description="Changes to your securities and preferences."
        action={
          <Link className="button secondary" href="/app/activity">
            Market activity <ArrowRight size={16} aria-hidden="true" />
          </Link>
        }
      />
      {error && (
        <p className="broker-error" role="alert">
          {error}
        </p>
      )}
      {!ready ? (
        <p role="status">Loading logs…</p>
      ) : state.events.length ? (
        <div className="broker-log-list">
          {state.events.map((event) => (
            <article key={event.id} className="broker-log">
              <Check size={17} aria-hidden="true" />
              <div>
                <h2>{actions[event.action]}</h2>
                <p>{findBroker(event.brokerId)?.name}</p>
              </div>
              <time dateTime={event.at}>
                {new Intl.DateTimeFormat("en-GB", {
                  day: "numeric",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                  timeZone: "Asia/Jakarta",
                }).format(new Date(event.at))}{" "}
                WIB
              </time>
            </article>
          ))}
        </div>
      ) : (
        <div className="broker-empty">
          <SlidersHorizontal size={28} aria-hidden="true" />
          <h2>No changes yet</h2>
          <p>Added securities and saved preferences will appear here.</p>
          <Link className="button primary" href="/app/securities/add">
            Browse securities
          </Link>
        </div>
      )}
      <p className="broker-attribution">
        Configuration history stored in this browser. Delivery receipts will appear after your
        channels are connected.
      </p>
    </div>
  );
}
