"use client";

import { ArrowUpRight, Search } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useId, useRef, useState, type KeyboardEvent } from "react";
import { recommendedSources } from "@/lib/recommended-sources";
import {
  brokerSettingsLinks,
  sourceSettingsLink,
  type PublicSource,
  type SourceSettingsLink,
} from "@/lib/connected-sources";
import "@/app/connected-sources.css";

type LibraryTab = "securities" | "people";
type PlatformFilter = "all" | "x" | "instagram";

const platformLabels = {
  x: "X",
  instagram: "Instagram",
  whatsapp: "WhatsApp",
  telegram: "Telegram",
} as const;

// Visual catalog entries, not a projection of saved backend profiles.
const securities = [
  {
    id: "bri-danareksa",
    name: "BRI Danareksa Sekuritas",
    image: "/securities/bri-danareksa.webp",
    description: "Equity research and market commentary.",
    website: "https://www.bridanareksasekuritas.co.id/",
    previewStatus: "Added in preview",
  },
  {
    id: "phintraco",
    name: "Phintraco Sekuritas",
    image: "/securities/phintraco.webp",
    description: "Market, company and technical research.",
    website: "https://phintracosekuritas.com/",
    previewStatus: "Added in preview",
  },
  {
    id: "tuntun",
    name: "Tuntun Sekuritas Indonesia",
    image: "/securities/tuntun.webp",
    description: "A brokerage source in the visual preview.",
    website: "https://tuntun.co.id/id/about",
    previewStatus: "Added in preview",
  },
  {
    id: "stockbit",
    name: "Stockbit",
    image: "/securities/stockbit.webp",
    description: "Stockbit research and Snips source preview.",
    website: "https://stockbit.com/about",
    previewStatus: "Added in preview",
  },
  {
    id: "samuel",
    name: "Samuel Sekuritas Indonesia",
    image: "/securities/samuel.webp",
    description: "A brokerage source under consideration.",
    website: "https://samuel.co.id/",
    previewStatus: "To add",
  },
] as const;

type Security = (typeof securities)[number];
const publicPeople = recommendedSources.filter((source) => source.id !== "bri-danareksa-sekuritas");

function securitySettingsLinks(id: string, watcherIds: string[]): SourceSettingsLink[] {
  if (id === "stockbit") {
    return watcherIds.includes("bursawatch-stockbit-snips")
      ? [
          {
            href: "/workspace/workflows?watcher=bursawatch-stockbit-snips",
            label: "Open Stockbit settings",
          },
        ]
      : [];
  }
  return brokerSettingsLinks(id, watcherIds);
}

function SecurityCard({ security, watcherIds }: { security: Security; watcherIds: string[] }) {
  const settingsLinks = securitySettingsLinks(security.id, watcherIds);
  return (
    <article className="connected-security-card">
      <figure className="connected-security-figure">
        <Image
          src={security.image}
          alt={"Illustrative thumbnail for " + security.name}
          width={1448}
          height={1086}
          sizes="(max-width: 800px) 100vw, (max-width: 1200px) 50vw, 560px"
        />
        <figcaption>AI-generated illustration · not a verified photograph</figcaption>
      </figure>
      <div className="connected-security-content">
        <div className="connected-security-title-row">
          <h3>{security.name}</h3>
          <span
            className={
              "connected-preview-status" +
              (security.previewStatus === "To add" ? " is-pending" : "")
            }
          >
            {security.previewStatus}
          </span>
        </div>
        <p>{security.description}</p>
        <div className="connected-card-actions">
          {settingsLinks.map((link) => (
            <Link className="button secondary small" href={link.href} key={link.href}>
              {link.label}
            </Link>
          ))}
          <a
            className="connected-public-link"
            href={security.website}
            target="_blank"
            rel="noopener noreferrer"
          >
            Company website <ArrowUpRight size={15} aria-hidden="true" />
            <span className="sr-only"> for {security.name}</span>
          </a>
        </div>
      </div>
    </article>
  );
}

function PeopleCards({ sources, watcherIds }: { sources: PublicSource[]; watcherIds: string[] }) {
  return (
    <ul className="connected-people-grid">
      {sources.map((source) => {
        const settings = sourceSettingsLink(source.platform, watcherIds);
        return (
          <li key={source.id}>
            <article className="connected-person-card">
              <div className="connected-person-top">
                <div
                  className={"connected-source-avatar" + (source.portrait ? " is-portrait" : "")}
                >
                  {source.image ? (
                    <Image src={source.image} alt="" width={52} height={52} />
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
                <span className="connected-person-platform">{platformLabels[source.platform]}</span>
              </div>
              <h3>{source.name}</h3>
              <p className="connected-source-handle">{source.handle}</p>
              <p className="connected-person-coverage">{source.coverage}</p>
              <details className="connected-person-about">
                <summary>About this source</summary>
                <p>{source.background}</p>
                <a href={source.evidence} target="_blank" rel="noopener noreferrer">
                  Public reference <ArrowUpRight size={14} aria-hidden="true" />
                </a>
              </details>
              <div className="connected-card-actions">
                {settings ? (
                  <Link className="button secondary small" href={settings.href}>
                    {settings.label}
                  </Link>
                ) : null}
                <a
                  className="connected-public-link"
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Public profile <ArrowUpRight size={15} aria-hidden="true" />
                  <span className="sr-only"> for {source.name}</span>
                </a>
              </div>
            </article>
          </li>
        );
      })}
    </ul>
  );
}

function EmptyResults({ onClear }: { onClear: () => void }) {
  return (
    <div className="connected-library-empty">
      <h3>No sources match these filters</h3>
      <p>Try another name or clear your filters.</p>
      <button type="button" className="button secondary" onClick={onClear}>
        Clear filters
      </button>
    </div>
  );
}

export function ConnectedSourceLibrary({ watcherIds }: { watcherIds: string[] }) {
  const [activeTab, setActiveTab] = useState<LibraryTab>("securities");
  const [securityQuery, setSecurityQuery] = useState("");
  const [peopleQuery, setPeopleQuery] = useState("");
  const [platform, setPlatform] = useState<PlatformFilter>("all");
  const securitiesTabRef = useRef<HTMLButtonElement>(null);
  const peopleTabRef = useRef<HTMLButtonElement>(null);
  const id = useId();

  const visibleSecurities = securities.filter((security) =>
    (security.name + " " + security.description + " " + security.previewStatus)
      .toLowerCase()
      .includes(securityQuery.trim().toLowerCase()),
  );
  const visiblePeople = publicPeople.filter(
    (source) =>
      (platform === "all" || source.platform === platform) &&
      (
        source.name +
        " " +
        source.handle +
        " " +
        source.coverage +
        " " +
        platformLabels[source.platform]
      )
        .toLowerCase()
        .includes(peopleQuery.trim().toLowerCase()),
  );

  function onTabKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    let next: LibraryTab;
    switch (event.key) {
      case "ArrowRight":
        next = activeTab === "securities" ? "people" : "securities";
        break;
      case "End":
        next = "people";
        break;
      case "ArrowLeft":
        next = activeTab === "people" ? "securities" : "people";
        break;
      case "Home":
        next = "securities";
        break;
      default:
        return;
    }
    event.preventDefault();
    setActiveTab(next);
    (next === "securities" ? securitiesTabRef : peopleTabRef).current?.focus();
  }

  return (
    <section className="connected-source-library" aria-labelledby={id + "-title"}>
      <header className="connected-library-heading">
        <h2 id={id + "-title"}>Public source library</h2>
        <p>Browse visual securities concepts and public people or institution references.</p>
        <p className="connected-library-note">
          This catalog is a preview. Its entries do not establish a saved source, an enabled
          watcher, or Discord delivery. Open available workflow settings to inspect the shared
          workspace.
        </p>
      </header>

      <div className="connected-library-tabs" role="tablist" aria-label="Source category">
        <button
          ref={securitiesTabRef}
          type="button"
          role="tab"
          id={id + "-securities-tab"}
          aria-controls={id + "-securities-panel"}
          aria-selected={activeTab === "securities"}
          tabIndex={activeTab === "securities" ? 0 : -1}
          onClick={() => setActiveTab("securities")}
          onKeyDown={onTabKeyDown}
        >
          Securities
        </button>
        <button
          ref={peopleTabRef}
          type="button"
          role="tab"
          id={id + "-people-tab"}
          aria-controls={id + "-people-panel"}
          aria-selected={activeTab === "people"}
          tabIndex={activeTab === "people" ? 0 : -1}
          onClick={() => setActiveTab("people")}
          onKeyDown={onTabKeyDown}
        >
          People
        </button>
      </div>

      <section
        className="connected-library-panel"
        id={id + "-securities-panel"}
        role="tabpanel"
        aria-labelledby={id + "-securities-tab"}
        tabIndex={0}
        hidden={activeTab !== "securities"}
      >
        <p className="connected-panel-intro">
          Four sources appear in this visual preview; Samuel is proposed next. Thumbnails are
          illustrations, not official company artwork or proof of a live connection.
        </p>
        <div className="connected-library-filters">
          <label className="connected-library-search" htmlFor={id + "-securities-search"}>
            <span>Search sources</span>
            <span className="connected-search-control">
              <Search size={18} aria-hidden="true" />
              <input
                id={id + "-securities-search"}
                type="search"
                placeholder="Securities name"
                value={securityQuery}
                onChange={(event) => setSecurityQuery(event.target.value)}
              />
            </span>
          </label>
          <p role="status">
            {visibleSecurities.length} {visibleSecurities.length === 1 ? "security" : "securities"}
          </p>
        </div>
        {visibleSecurities.length ? (
          <ul className="connected-securities-grid">
            {visibleSecurities.map((security) => (
              <li key={security.id}>
                <SecurityCard security={security} watcherIds={watcherIds} />
              </li>
            ))}
          </ul>
        ) : (
          <EmptyResults onClear={() => setSecurityQuery("")} />
        )}
      </section>

      <section
        className="connected-library-panel"
        id={id + "-people-panel"}
        role="tabpanel"
        aria-labelledby={id + "-people-tab"}
        tabIndex={0}
        hidden={activeTab !== "people"}
      >
        <p className="connected-panel-intro">
          Public people, publications and institutions selected for reference. Browse their
          profiles; catalog membership does not mean they are configured or monitored.
        </p>
        <div className="connected-library-filters">
          <label className="connected-library-search" htmlFor={id + "-people-search"}>
            <span>Search sources</span>
            <span className="connected-search-control">
              <Search size={18} aria-hidden="true" />
              <input
                id={id + "-people-search"}
                type="search"
                placeholder="Name, handle or coverage"
                value={peopleQuery}
                onChange={(event) => setPeopleQuery(event.target.value)}
              />
            </span>
          </label>
          <label className="connected-library-platform" htmlFor={id + "-platform"}>
            <span>Platform</span>
            <select
              id={id + "-platform"}
              value={platform}
              onChange={(event) => setPlatform(event.target.value as PlatformFilter)}
            >
              <option value="all">All platforms</option>
              <option value="x">X</option>
              <option value="instagram">Instagram</option>
            </select>
          </label>
          <p role="status">
            {visiblePeople.length} {visiblePeople.length === 1 ? "source" : "sources"}
          </p>
        </div>
        {visiblePeople.length ? (
          <PeopleCards sources={visiblePeople} watcherIds={watcherIds} />
        ) : (
          <EmptyResults
            onClear={() => {
              setPeopleQuery("");
              setPlatform("all");
            }}
          />
        )}
      </section>
    </section>
  );
}
