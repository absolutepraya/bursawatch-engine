"use client";

import { ArrowUpRight, Search } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useId, useState } from "react";
import { brokers } from "@/lib/brokers";
import { recommendedSources } from "@/lib/recommended-sources";
import {
  brokerSettingsLinks,
  sourceSettingsLink,
  type PublicSource,
} from "@/lib/connected-sources";
import "@/app/connected-sources.css";

const platformLabels = {
  x: "X",
  instagram: "Instagram",
  whatsapp: "WhatsApp",
  telegram: "Telegram",
} as const;
type PlatformFilter = "all" | keyof typeof platformLabels;
const publicAccounts = recommendedSources.filter(
  (source) => source.id !== "bri-danareksa-sekuritas",
);

function SourceRows({ sources, watcherIds }: { sources: PublicSource[]; watcherIds: string[] }) {
  return (
    <ul className="connected-source-rows">
      {sources.map((source) => {
        const settings = sourceSettingsLink(source.platform, watcherIds);
        return (
          <li key={source.id} className="connected-source-row">
            <div className={`connected-source-avatar${source.portrait ? " is-portrait" : ""}`}>
              {source.image ? (
                <Image src={source.image} alt="" width={48} height={48} />
              ) : (
                <span aria-hidden="true">
                  {source.name
                    .split(/\s+/)
                    .slice(0, 2)
                    .map((part) => part[0])
                    .join("")}
                </span>
              )}
            </div>
            <div className="connected-source-copy">
              <h3>{source.name}</h3>
              <p className="connected-source-handle">
                {source.handle} · {platformLabels[source.platform]}
              </p>
              <p>{source.coverage}</p>
              <details>
                <summary>About this source</summary>
                <p>{source.background}</p>
                <a href={source.evidence} target="_blank" rel="noreferrer">
                  Public reference <ArrowUpRight size={14} aria-hidden="true" />
                </a>
              </details>
            </div>
            <div className="connected-source-actions">
              {settings ? (
                <Link className="button secondary small" href={settings.href}>
                  {settings.label}
                </Link>
              ) : null}
              <a
                className="connected-public-link"
                href={source.url}
                target="_blank"
                rel="noreferrer"
              >
                Public profile <ArrowUpRight size={15} aria-hidden="true" />
                <span className="sr-only"> for {source.name}</span>
              </a>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function ConnectedSourceLibrary({ watcherIds }: { watcherIds: string[] }) {
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState<PlatformFilter>("all");
  const id = useId();
  const match = (value: string) => value.toLowerCase().includes(query.trim().toLowerCase());
  const visibleBrokers = brokers.filter((broker) => {
    const brokerPlatform = broker.id === "bri-danareksa" ? "whatsapp" : "telegram";
    return (
      (platform === "all" || platform === brokerPlatform) &&
      match(`${broker.name} ${broker.coverage.join(" ")} ${platformLabels[brokerPlatform]}`)
    );
  });
  const visibleAccounts = publicAccounts.filter(
    (source) =>
      (platform === "all" || source.platform === platform) &&
      match(
        `${source.name} ${source.handle} ${source.coverage} ${platformLabels[source.platform]}`,
      ),
  );
  const people = visibleAccounts.filter((source) => source.label !== "Official institution");
  const institutions = visibleAccounts.filter((source) => source.label === "Official institution");
  const count = visibleBrokers.length + visibleAccounts.length;
  return (
    <section className="connected-source-library" aria-labelledby={`${id}-title`}>
      <header className="connected-library-heading">
        <h2 id={`${id}-title`}>Public source library</h2>
        <p>
          Explore people, publications and brokerages. Open a workflow’s settings to review its
          saved sources and Discord destinations.
        </p>
        <p className="connected-library-note">
          These are public references. A listing does not mean the source is enabled in this shared
          workspace.
        </p>
      </header>
      <div className="connected-library-filters">
        <label className="connected-library-search" htmlFor={`${id}-search`}>
          <span>Search sources</span>
          <div>
            <Search size={18} aria-hidden="true" />
            <input
              id={`${id}-search`}
              type="search"
              placeholder="Name, handle or coverage"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
        </label>
        <label className="connected-library-platform" htmlFor={`${id}-platform`}>
          <span>Source platform</span>
          <select
            id={`${id}-platform`}
            value={platform}
            onChange={(event) => setPlatform(event.target.value as PlatformFilter)}
          >
            <option value="all">All platforms</option>
            {Object.entries(platformLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <p role="status">
          {count} {count === 1 ? "source" : "sources"}
        </p>
      </div>
      {visibleBrokers.length ? (
        <section className="connected-library-section" aria-labelledby={`${id}-brokers`}>
          <div className="connected-library-section-heading">
            <h2 id={`${id}-brokers`}>Brokerages</h2>
            <p>Profiles and photographs reviewed 17 Sep 2026.</p>
          </div>
          <div className="connected-broker-grid">
            {visibleBrokers.map((broker) => (
              <article className="connected-broker-card" key={broker.id}>
                <div className="connected-broker-brand">
                  <Image
                    src={broker.logo}
                    alt={`${broker.name} logo`}
                    width={176}
                    height={40}
                    loading="eager"
                  />
                  <span>
                    {broker.id === "bri-danareksa" ? "WhatsApp research" : "Telegram research"}
                  </span>
                </div>
                <div className="connected-broker-photos">
                  <figure>
                    <Image
                      src={broker.portrait}
                      alt={broker.leader}
                      width={320}
                      height={220}
                      loading="eager"
                      className={`connected-broker-portrait ${broker.id}`}
                    />
                    <figcaption>
                      <strong>{broker.leader}</strong>
                      <span>{broker.role}</span>
                    </figcaption>
                  </figure>
                  <figure>
                    <Image
                      src={broker.building}
                      alt={`${broker.office}, ${broker.location}`}
                      width={320}
                      height={220}
                      loading="eager"
                    />
                    <figcaption>
                      <strong>{broker.office}</strong>
                      <span>{broker.location}</span>
                    </figcaption>
                  </figure>
                </div>
                <div className="connected-broker-copy">
                  <h3>{broker.name}</h3>
                  <p>{broker.description}</p>
                  <div className="connected-broker-coverage">
                    {broker.coverage.map((item) => (
                      <span key={item}>{item}</span>
                    ))}
                  </div>
                </div>
                <div className="connected-broker-actions">
                  {brokerSettingsLinks(broker.id, watcherIds).map((link) => (
                    <Link className="button secondary small" href={link.href} key={link.href}>
                      {link.label}
                    </Link>
                  ))}
                  <a
                    className="connected-public-link"
                    href={broker.profile}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Company profile <ArrowUpRight size={15} aria-hidden="true" />
                    <span className="sr-only"> for {broker.name}</span>
                  </a>
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}
      {people.length ? (
        <section className="connected-library-section" aria-labelledby={`${id}-people`}>
          <div className="connected-library-section-heading">
            <h2 id={`${id}-people`}>People and publications</h2>
            <p>Team selections · public catalog reviewed 18 Sep 2026.</p>
          </div>
          <SourceRows sources={people} watcherIds={watcherIds} />
        </section>
      ) : null}
      {institutions.length ? (
        <section className="connected-library-section" aria-labelledby={`${id}-institutions`}>
          <div className="connected-library-section-heading">
            <h2 id={`${id}-institutions`}>Institutions</h2>
            <p>Official public accounts for policy and regulatory context.</p>
          </div>
          <SourceRows sources={institutions} watcherIds={watcherIds} />
        </section>
      ) : null}
      {!count ? (
        <div className="connected-library-empty">
          <h3>No sources match these filters</h3>
          <p>Try another name or choose a different platform.</p>
          <button
            type="button"
            className="button secondary"
            onClick={() => {
              setQuery("");
              setPlatform("all");
            }}
          >
            Clear filters
          </button>
        </div>
      ) : null}
    </section>
  );
}
