"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight, Check, ExternalLink, Plus, Search, SlidersHorizontal } from "lucide-react";
import { PageHeading } from "@/components/page-heading";
import { useBrokerWorkspace } from "@/components/use-broker-workspace";
import { brokers, type BrokerId } from "@/lib/brokers";
import { updateWorkspace } from "@/lib/broker-workspace";

export function BrokerDirectory() {
  const { state, ready, error: storageError } = useBrokerWorkspace();
  const [selection, setSelection] = useState<BrokerId[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const router = useRouter();
  const watched = new Set(state.watches.map((watch) => watch.brokerId));
  const selected = selection.filter((id) => !watched.has(id));
  const filtered = brokers.filter((broker) =>
    broker.name.toLowerCase().includes(query.trim().toLowerCase()),
  );
  function addSelected() {
    try {
      updateWorkspace({ type: "add", ids: selected });
      router.push("/app/securities?added=1");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not add securities. Try again.");
    }
  }
  return (
    <div className="page-wrap broker-directory">
      <PageHeading
        title="Available securities"
        description="Choose whose research you want to follow."
        action={
          <Link className="button secondary" href="/app/securities">
            Watched securities <ArrowRight size={16} aria-hidden="true" />
          </Link>
        }
      />
      <div className="broker-toolbar">
        <div className="broker-search">
          <Search size={18} aria-hidden="true" />
          <label className="sr-only" htmlFor="broker-search">
            Search securities firms
          </label>
          <input
            id="broker-search"
            type="search"
            placeholder="Search securities firms"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <span aria-live="polite">
          {filtered.length} {filtered.length === 1 ? "firm" : "firms"}
        </span>
      </div>
      {(error || storageError) && (
        <p className="broker-error" role="alert">
          {error || storageError}
        </p>
      )}
      <div className="broker-grid">
        {filtered.map((broker) => {
          const isWatched = watched.has(broker.id);
          const isSelected = selected.includes(broker.id);
          return (
            <article
              key={broker.id}
              className={`broker-card${isSelected ? " is-selected" : ""}`}
              aria-labelledby={`${broker.id}-title`}
            >
              <div className="broker-identity">
                <div className="broker-logo">
                  <Image src={broker.logo} alt={`${broker.name} logo`} width={176} height={40} />
                </div>
                <span>{isWatched ? "In your securities" : "Research provider"}</span>
              </div>
              <div className={`broker-photographs ${broker.id}`}>
                <figure>
                  <div className="broker-photo leader">
                    <Image
                      src={broker.portrait}
                      alt={broker.leader}
                      fill
                      sizes="(max-width: 700px) 45vw, 24vw"
                    />
                  </div>
                  <figcaption>
                    <strong>{broker.leader}</strong>
                    <span>{broker.role}</span>
                  </figcaption>
                </figure>
                <figure>
                  <div className="broker-photo building">
                    <Image
                      src={broker.building}
                      alt={`${broker.office}, ${broker.location}`}
                      fill
                      sizes="(max-width: 700px) 45vw, 24vw"
                    />
                  </div>
                  <figcaption>
                    <strong>{broker.office}</strong>
                    <span>{broker.location}</span>
                  </figcaption>
                </figure>
              </div>
              <div className="broker-card-copy">
                <h2 id={`${broker.id}-title`}>{broker.name}</h2>
                <p>{broker.description}</p>
                <ul className="broker-coverage" aria-label="Research coverage">
                  {broker.coverage.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
              <footer className="broker-card-footer">
                <a
                  className="broker-profile-link"
                  href={broker.profile}
                  target="_blank"
                  rel="noreferrer"
                >
                  Company profile <ExternalLink size={14} aria-hidden="true" />
                </a>
                {isWatched ? (
                  <Link
                    className="button secondary small"
                    href={`/app/configuration?firm=${broker.id}`}
                  >
                    <SlidersHorizontal size={16} aria-hidden="true" /> Configure
                  </Link>
                ) : (
                  <button
                    type="button"
                    className={`button ${isSelected ? "primary" : "secondary"} small`}
                    disabled={!ready || !!storageError}
                    aria-pressed={isSelected}
                    aria-label={`${isSelected ? "Deselect" : "Select"} ${broker.name}`}
                    onClick={() =>
                      setSelection((items) =>
                        isSelected ? items.filter((id) => id !== broker.id) : [...items, broker.id],
                      )
                    }
                  >
                    {isSelected ? (
                      <Check size={16} aria-hidden="true" />
                    ) : (
                      <Plus size={16} aria-hidden="true" />
                    )}
                    {isSelected ? "Selected" : "Select"}
                  </button>
                )}
              </footer>
            </article>
          );
        })}
      </div>
      {filtered.length === 0 && (
        <div className="broker-empty">
          <h2>No matching securities</h2>
          <p>Try a firm name such as Phintraco.</p>
          <button className="button secondary" onClick={() => setQuery("")}>
            Clear search
          </button>
        </div>
      )}
      <p className="broker-attribution">
        Profiles checked 17 Sep 2026 · Logos and photographs belong to their respective owners.
        Listing does not imply a partnership.
      </p>
      {selected.length > 0 && (
        <div className="broker-selection-tray">
          <div aria-live="polite">
            <strong>
              {selected.length} {selected.length === 1 ? "security" : "securities"} selected
            </strong>
            <span>
              {selected
                .map((id) => brokers.find((broker) => broker.id === id)?.shortName)
                .join(" · ")}
            </span>
          </div>
          <button type="button" className="button primary" onClick={addSelected}>
            Add to watched securities <ArrowRight size={18} aria-hidden="true" />
          </button>
          <button type="button" className="button ghost" onClick={() => setSelection([])}>
            Clear
          </button>
        </div>
      )}
    </div>
  );
}
