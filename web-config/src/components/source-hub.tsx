"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { Check, ChevronRight, Plus, Search, Settings2, Trash2 } from "lucide-react";
import { PageHeading } from "./page-heading";
import { useResearchSources } from "./use-research-sources";
import { useBrokerWorkspace } from "./use-broker-workspace";
import { useToast } from "./toast-provider";
import { SourceEditor } from "./research-sources";
import { recommendedSources } from "@/lib/recommended-sources";
import { brokers, type BrokerId } from "@/lib/brokers";
import { updateWorkspace } from "@/lib/broker-workspace";
import {
  blankSource,
  platforms,
  updateResearch,
  type ResearchSource,
  type Platform,
} from "@/lib/research-sources";
import { decodePreferences, preferencesSnapshot } from "@/lib/delivery-preferences";

// One brokerage entry owns the BRIDS identity; its channel is not a duplicate suggestion.
const people = recommendedSources.filter((p) => p.id !== "bri-danareksa-sekuritas");
function RemoveConfirmation({
  onKeep,
  onRemove,
  error,
}: {
  onKeep: () => void;
  onRemove: () => void;
  error: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    ref.current?.showModal();
    return () => trigger?.focus();
  }, []);
  return (
    <dialog
      ref={ref}
      className="hub-remove"
      aria-labelledby="remove-source-title"
      onCancel={onKeep}
    >
      <h2 id="remove-source-title">Remove this source?</h2>
      <p>Its saved preferences will also be removed. You can follow it again from Discover.</p>
      {error ? (
        <p className="field-error" role="alert">
          {error} Your source is still followed. Keep following to return, or try removing it again.
        </p>
      ) : null}
      <div className="research-actions">
        <button type="button" className="button secondary" onClick={onKeep}>
          Keep following
        </button>
        <button type="button" className="button secondary" onClick={onRemove}>
          Remove source
        </button>
      </div>
    </dialog>
  );
}
export function SourceHub({
  following = false,
  initialPlatform = "all",
  initialType = "all",
}: {
  following?: boolean;
  initialPlatform?: Platform | "all";
  initialType?: "all" | "people" | "firms";
}) {
  const research = useResearchSources();
  const firms = useBrokerWorkspace();
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "people" | "firms">(initialType);
  const [platform, setPlatform] = useState<Platform | "all">(initialPlatform);
  const [editor, setEditor] = useState<ResearchSource | "new" | null>(null);
  const [error, setError] = useState("");
  const [removing, setRemoving] = useState<{ kind: "person" | "firm"; id: string } | null>(null);
  const [removeError, setRemoveError] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const ready = research.ready && firms.ready;
  const storageError = research.error || firms.error;
  const followedUrls = new Set(research.state.sources.map((s) => s.input.url));
  const followedFirms = new Set(firms.state.watches.map((w) => w.brokerId));
  const matches = (text: string) => text.toLowerCase().includes(query.trim().toLowerCase());
  const matchesPlatform = (value: Platform) => platform === "all" || platform === value;
  const personRows = following
    ? research.state.sources.filter(
        (s) => matchesPlatform(s.input.platform) && matches(s.input.name + " " + s.input.url),
      )
    : people.filter(
        (p) =>
          matchesPlatform(p.platform) &&
          matches(p.name + " " + p.handle + " " + p.coverage + " " + platforms[p.platform]),
      );
  const firmRows = brokers.filter(
    (b) =>
      platform === "all" &&
      (!following || followedFirms.has(b.id)) &&
      matches(b.name + " " + b.coverage.join(" ")),
  );
  const visibleCount =
    (filter === "firms" ? 0 : personRows.length) + (filter === "people" ? 0 : firmRows.length);
  function followPerson(profile: (typeof people)[number]) {
    try {
      const preferences = decodePreferences(preferencesSnapshot());
      if (!preferences)
        throw new Error(
          "Your brief preferences could not be read. Allow browser storage and reload.",
        );
      updateResearch({
        type: "save",
        input: {
          ...blankSource,
          name: profile.name,
          url: profile.url,
          platform: profile.platform,
          topics: [...preferences.bot.interests],
        },
      });
      setError("");
      toast(`Following ${profile.name}.`);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function followFirm(id: BrokerId, name: string) {
    try {
      updateWorkspace({ type: "add", ids: [id] });
      setError("");
      toast(`Following ${name}.`);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function remove() {
    if (!removing) return;
    try {
      if (removing.kind === "firm")
        updateWorkspace({ type: "remove", id: removing.id as BrokerId });
      else {
        const s = research.state.sources.find((s) => s.id === removing.id);
        if (s) updateResearch({ type: "remove", id: s.id, revision: s.revision });
      }
      toast("Removed from Following.");
      setRemoving(null);
      setRemoveError("");
      setError("");
    } catch (e) {
      setRemoveError((e as Error).message);
    }
  }
  return (
    <div className="page-wrap source-hub">
      <PageHeading
        title={following ? "Following" : "Discover"}
        description={
          following
            ? "Your people and brokerages. Configure each one here."
            : "People, publications and brokerages worth following."
        }
        action={
          following ? (
            <Link
              href={`/app/discover?${new URLSearchParams({ platform, type: filter })}`}
              className="button primary"
            >
              <Plus size={17} aria-hidden="true" />
              Follow sources
            </Link>
          ) : (
            <button
              className="button secondary"
              type="button"
              disabled={!ready || !!storageError || !!editor}
              onClick={() => setEditor("new")}
            >
              <Plus size={17} aria-hidden="true" />
              Add a source
            </button>
          )
        }
      />
      {error || storageError ? (
        <div className="research-notice" role="alert">
          <p>
            {error ||
              "Saved sources could not be read. Your existing data is unchanged. Allow browser storage and reload."}
          </p>
          {storageError ? (
            <button type="button" className="button secondary" onClick={() => location.reload()}>
              Reload sources
            </button>
          ) : null}
        </div>
      ) : null}
      {editor ? (
        <>
          <SourceEditor
            key={editor === "new" ? "new" : editor.id}
            source={editor === "new" ? undefined : editor}
            initial={
              editor === "new" && platform !== "all" ? { ...blankSource, platform } : undefined
            }
            onClose={() => setEditor(null)}
            onSaved={() => {
              setEditor(null);
              toast("Source preferences saved.");
            }}
          />
        </>
      ) : (
        <>
          <div className="hub-controls">
            <div className="hub-filters" aria-label="Source types">
              {(
                [
                  ["all", "All"],
                  ["people", "People & publications"],
                  ["firms", "Brokerages"],
                ] as const
              ).map(([id, label]) => (
                <button
                  type="button"
                  key={id}
                  aria-pressed={filter === id}
                  onClick={() => {
                    setFilter(id);
                    if (id === "firms") setPlatform("all");
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
            <label className="research-search">
              <Search size={17} aria-hidden="true" />
              <span className="sr-only">Search {following ? "following" : "discover"}</span>
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search by name"
              />
            </label>
          </div>
          <label className="capability-filter hub-platform-filter">
            <span id="source-platform-filter-label">Source platform</span>
            <select
              aria-labelledby="source-platform-filter-label"
              value={platform}
              onChange={(event) => {
                setPlatform(event.target.value as Platform | "all");
                setFilter("all");
              }}
            >
              <option value="all">All platforms</option>
              {Object.entries(platforms).map(([id, label]) => (
                <option value={id} key={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {!ready ? <p role="status">Loading your sources…</p> : null}
          {!following && filter !== "people" ? (
            <div className="hub-broker-grid">
              {firmRows.map((b) => {
                const saved = followedFirms.has(b.id);
                return (
                  <article className="hub-broker" key={b.id}>
                    <div className="hub-broker-identity">
                      <Image src={b.logo} width={160} height={48} alt={`${b.name} logo`} />
                      <span>Brokerage</span>
                    </div>
                    <div className="hub-broker-images">
                      <figure>
                        <Image src={b.portrait} width={280} height={180} alt={b.leader} />
                        <figcaption>
                          {b.leader}
                          <span>{b.role}</span>
                        </figcaption>
                      </figure>
                      <figure>
                        <Image
                          src={b.building}
                          width={280}
                          height={180}
                          alt={`${b.office}, ${b.location}`}
                        />
                        <figcaption>
                          {b.office}
                          <span>{b.location}</span>
                        </figcaption>
                      </figure>
                    </div>
                    <div className="hub-broker-copy">
                      <h2>{b.name}</h2>
                      <p>{b.description}</p>
                      <div className="hub-row-actions">
                        <a className="text-link" href={b.profile} target="_blank" rel="noreferrer">
                          Profile <ChevronRight size={15} aria-hidden="true" />
                        </a>
                        <button
                          type="button"
                          className={`button ${saved ? "ghost" : "secondary"}`}
                          disabled={!ready || !!storageError || saved}
                          onClick={() => followFirm(b.id, b.shortName)}
                        >
                          {saved ? (
                            <Check size={17} aria-hidden="true" />
                          ) : (
                            <Plus size={17} aria-hidden="true" />
                          )}
                          {saved ? "Following" : "Follow"}
                        </button>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : null}
          <div className="hub-source-list">
            {following && filter !== "people"
              ? firmRows.map((b) => {
                  const watch = firms.state.watches.find((w) => w.brokerId === b.id)!;
                  return (
                    <article className="hub-source" key={b.id}>
                      <div className="hub-avatar is-institution">
                        <Image src={b.logo} width={100} height={40} alt="" />
                      </div>
                      <div className="hub-source-copy">
                        <h2>{b.name}</h2>
                        <p>
                          Brokerage ·{" "}
                          {watch.paused
                            ? "Paused"
                            : watch.preferences.goal === "invest"
                              ? "Long-term research"
                              : "Market research"}
                        </p>
                      </div>
                      <div className="hub-row-actions">
                        <Link className="button secondary" href={`/app/configuration?firm=${b.id}`}>
                          <Settings2 size={16} aria-hidden="true" />
                          Configure
                        </Link>
                        <button
                          className="icon-button"
                          aria-label={`Remove ${b.shortName}`}
                          type="button"
                          onClick={() => setRemoving({ kind: "firm", id: b.id })}
                        >
                          <Trash2 size={17} aria-hidden="true" />
                        </button>
                      </div>
                    </article>
                  );
                })
              : null}
            {filter !== "firms" &&
              (following
                ? research.state.sources
                    .filter(
                      (s) =>
                        matchesPlatform(s.input.platform) &&
                        matches(s.input.name + " " + s.input.url),
                    )
                    .map((s) => {
                      const profile = people.find((p) => p.url === s.input.url);
                      return (
                        <article className="hub-source" key={s.id}>
                          <div className="hub-avatar">
                            {profile?.image ? (
                              <Image src={profile.image} width={64} height={64} alt="" />
                            ) : (
                              <span>{s.input.name.slice(0, 2)}</span>
                            )}
                          </div>
                          <div className="hub-source-copy">
                            <h2>{s.input.name}</h2>
                            <p>
                              {platforms[s.input.platform]} · {s.enabled ? "Followed" : "Paused"}
                            </p>
                          </div>
                          <div className="hub-row-actions">
                            <button
                              className="button secondary"
                              type="button"
                              onClick={() => setEditor(s)}
                            >
                              <Settings2 size={16} aria-hidden="true" />
                              Configure
                            </button>
                            <button
                              className="icon-button"
                              type="button"
                              aria-label={`Remove ${s.input.name}`}
                              onClick={() => setRemoving({ kind: "person", id: s.id })}
                            >
                              <Trash2 size={17} aria-hidden="true" />
                            </button>
                          </div>
                        </article>
                      );
                    })
                : people
                    .filter(
                      (p) =>
                        matchesPlatform(p.platform) &&
                        matches(
                          p.name + " " + p.handle + " " + p.coverage + " " + platforms[p.platform],
                        ),
                    )
                    .map((p) => {
                      const saved = followedUrls.has(p.url);
                      return (
                        <article className="hub-source" key={p.id}>
                          <div
                            className={`hub-avatar${p.image && !p.portrait ? " is-institution" : ""}`}
                          >
                            {p.image ? (
                              <Image src={p.image} width={64} height={64} alt="" />
                            ) : (
                              <span aria-hidden="true">
                                {p.name
                                  .split(/\s+/)
                                  .slice(0, 2)
                                  .map((word) => word[0])
                                  .join("")}
                              </span>
                            )}
                          </div>
                          <div className="hub-source-copy">
                            <h2>
                              {p.name}
                              <span>{p.label}</span>
                            </h2>
                            <p>
                              {p.handle} · {platforms[p.platform]} · {p.coverage}
                            </p>
                            <button
                              type="button"
                              className="text-link hub-about"
                              aria-expanded={expanded === p.id}
                              onClick={() => setExpanded(expanded === p.id ? null : p.id)}
                            >
                              About this source <ChevronRight size={14} aria-hidden="true" />
                            </button>
                            {expanded === p.id ? (
                              <div className="hub-source-about">
                                <p>
                                  {p.background} {p.reason}
                                </p>
                                <a
                                  className="text-link"
                                  href={p.evidence}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  View public profile <ChevronRight size={14} aria-hidden="true" />
                                </a>
                              </div>
                            ) : null}
                          </div>
                          <button
                            type="button"
                            className={`button ${saved ? "ghost" : "secondary"}`}
                            disabled={!ready || !!storageError || saved}
                            onClick={() => followPerson(p)}
                          >
                            {saved ? (
                              <Check size={17} aria-hidden="true" />
                            ) : (
                              <Plus size={17} aria-hidden="true" />
                            )}
                            {saved ? "Following" : "Follow"}
                          </button>
                        </article>
                      );
                    }))}
          </div>
          {ready && !storageError && !visibleCount ? (
            <div className="research-empty">
              <h2>
                {query || platform !== "all" || filter !== "all"
                  ? "No matching sources"
                  : "Your research starts here."}
              </h2>
              <p>
                {query || platform !== "all" || filter !== "all"
                  ? "Try another name or platform, or follow a source from Discover."
                  : "Follow a person or brokerage to keep their settings here."}
              </p>
              {query || platform !== "all" || filter !== "all" ? (
                <button
                  type="button"
                  className="button secondary"
                  onClick={() => {
                    setQuery("");
                    setFilter("all");
                    setPlatform("all");
                  }}
                >
                  Clear filters
                </button>
              ) : (
                <Link className="button primary" href="/app/discover">
                  Discover sources
                </Link>
              )}
            </div>
          ) : null}
          {!following ? (
            <p className="hub-caption">
              Team selections are not investment endorsements. Followed sources are saved on this
              device.
            </p>
          ) : null}
        </>
      )}
      {removing ? (
        <RemoveConfirmation
          error={removeError}
          onKeep={() => {
            setRemoving(null);
            setRemoveError("");
          }}
          onRemove={remove}
        />
      ) : null}
    </div>
  );
}
