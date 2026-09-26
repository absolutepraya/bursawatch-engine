"use client";

import Image from "next/image";
import { useCallback, useEffect, useId, useState } from "react";
import type { controlBrowser } from "@/lib/control-browser";
import { WorkspaceError } from "@/lib/control-browser";
import {
  catalogConfig,
  compatibleCapabilities,
  effectiveChoice,
  type CatalogConfig,
  type EffectiveCatalog,
  type SourceCatalog,
} from "@/lib/source-catalog";
import { StatusBadge } from "./status-badge";
import { useToast } from "./toast-provider";
import "@/app/connected-sources.css";

type Request = ReturnType<typeof controlBrowser>;
type Tab = "securities" | "institutions" | "people";
const institutionImages: Record<string, string> = {
  "bri-danareksa": "/securities/bri-danareksa-2026.webp",
  phintraco: "/securities/phintraco.webp",
  tuntun: "/securities/tuntun.webp",
  "samuel-sekuritas": "/securities/samuel-2026.webp",
};
const curatedPeopleImages: Record<string, string> = {
  "x-kutekians": "/sources/kutekians.png",
  "x-rickyho1989": "/sources/rickyho_1989.png",
  "x-writingtorch": "/sources/writingtorch.png",
  "x-arvinhonami": "/sources/arvinhonami.png",
  "x-doktermarket": "/sources/doktermarket.png",
  "x-txthariansaham": "/sources/txthariansaham.png",
  "x-wavetiga": "/sources/wavetiga.png",
  "x-aldotjahjadi8": "/sources/aldotjahjadi8.png",
  "x-kobeissiletter": "/sources/kobeissiletter.png",
};
const userPlatforms = ["telegram", "x", "instagram", "whatsapp"] as const;

function RegisteredEndpointList({ endpoints }: { endpoints: SourceCatalog["endpoints"] }) {
  if (endpoints.length === 0) return null;
  return (
    <ul className="source-endpoint-list" aria-label="Registered platform endpoints">
      {endpoints.map((endpoint) => (
        <li className="source-endpoint-row" key={endpoint.id}>
          <span className="source-endpoint-identity">
            <strong>{endpoint.platform}</strong> · {endpoint.address}
          </span>
          <StatusBadge
            status={endpoint.verified ? "verified" : "verification-pending"}
            label={endpoint.verified ? "Verified" : "Pending verification"}
          />
        </li>
      ))}
    </ul>
  );
}

function message(error: unknown) {
  if (error instanceof WorkspaceError && error.code === "forbidden")
    return "This account can view sources but cannot change them. An admin must save catalog changes.";
  if (error instanceof WorkspaceError && error.code === "conflict")
    return "The catalog changed since you opened it. Reload current settings before editing again.";
  if (error instanceof WorkspaceError && error.code === "unknown-outcome")
    return "The save could not be confirmed. Reload current settings before editing again.";
  return error instanceof Error ? error.message : "Could not load the source catalog.";
}
export function SourceCatalogView({
  request,
  onDirtyChange,
}: {
  request: Request;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [catalog, setCatalog] = useState<SourceCatalog | null>(null);
  const [effective, setEffective] = useState<EffectiveCatalog | null>(null);
  const [draft, setDraft] = useState<CatalogConfig | null>(null);
  const [tab, setTab] = useState<Tab>("securities");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saveBlocked, setSaveBlocked] = useState(false);
  const [writeRefreshFailed, setWriteRefreshFailed] = useState(false);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"person" | "group" | "community">("person");
  const [assetUrl, setAssetUrl] = useState("");
  const [assetKind, setAssetKind] = useState<"logo" | "profile_picture">("profile_picture");
  const [endpointPublisher, setEndpointPublisher] = useState("");
  const [endpointPlatform, setEndpointPlatform] = useState<
    "telegram" | "x" | "instagram" | "whatsapp"
  >("x");
  const [endpointAddress, setEndpointAddress] = useState("");
  const [selectedEndpoint, setSelectedEndpoint] = useState("");
  const [selectedCapability, setSelectedCapability] = useState("");
  const [level, setLevel] = useState<"publisher" | "endpoint">("endpoint");
  const [enabled, setEnabled] = useState(false);
  const id = useId();
  const toast = useToast();
  const dirty = Boolean(
    catalog && draft && JSON.stringify(catalog.config.config) !== JSON.stringify(draft),
  );
  const canEdit = catalog?.can_edit === true;
  useEffect(() => onDirtyChange(canEdit && dirty), [canEdit, dirty, onDirtyChange]);
  const reload = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError("");
      try {
        const [nextCatalog, nextEffective] = await Promise.all([
          request<SourceCatalog>("source-catalog", undefined, { signal }),
          request<EffectiveCatalog>("source-catalog/effective", undefined, { signal }),
        ]);
        if (nextCatalog.config.revision !== nextEffective.revision)
          throw new Error("Catalog revisions differ. Refresh to read a consistent snapshot.");
        setCatalog(nextCatalog);
        setEffective(nextEffective);
        setDraft(structuredClone(nextCatalog.config.config));
        setSaveBlocked(false);
        setWriteRefreshFailed(false);
        return true;
      } catch (failure) {
        if (signal?.aborted) return false;
        setError(message(failure));
        setSaveBlocked(true);
        if (failure instanceof WorkspaceError && ["auth", "forbidden"].includes(failure.code)) {
          setCatalog(null);
          setDraft(null);
          setEffective(null);
        }
        return false;
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [request],
  );
  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => {
      if (!controller.signal.aborted) void reload(controller.signal);
    });
    return () => controller.abort();
  }, [reload]);
  const update = (value: CatalogConfig) => {
    if (!canEdit || saveBlocked || saving) return;
    setDraft(value);
    setError("");
  };
  const publishers = catalog ? [...catalog.institutions, ...catalog.people_org] : [];
  const endpoints = catalog?.endpoints ?? [];
  const selected = [
    ...endpoints,
    ...(draft?.endpoints ?? []).map((item) => ({
      ...item,
      provider_id: null,
      system_owned: false,
      verified: false,
    })),
  ].find((item) => item.id === selectedEndpoint);
  const compatible = selected && catalog ? compatibleCapabilities(catalog, selected.id) : [];
  const chosen =
    selectedCapability && draft && selected
      ? effectiveChoice(draft, selected.publisher_id, selected.id, selectedCapability)
      : null;
  const subscription = effective?.subscriptions.find(
    (item) => item.endpoint_id === selectedEndpoint && item.capability_id === selectedCapability,
  );
  async function save() {
    if (!catalog || !draft || !canEdit || saveBlocked || saving) return;
    const parsed = catalogConfig.safeParse(draft);
    if (!parsed.success) {
      setError("Review the identity, endpoint, and asset fields before saving.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await request("source-catalog/config", {
        expected_revision: catalog.config.revision,
        config: parsed.data,
      });
      if (await reload()) {
        toast("Source catalog saved. Pending endpoints still require identity verification.");
      } else {
        setSaveBlocked(true);
        setWriteRefreshFailed(true);
        setError(
          "The save response was received, but the catalog refresh could not be confirmed. Your draft is locked. Reload current catalog before editing again.",
        );
      }
    } catch (failure) {
      setError(message(failure));
      if (
        failure instanceof WorkspaceError &&
        ["conflict", "unknown-outcome", "forbidden"].includes(failure.code)
      )
        setSaveBlocked(true);
    } finally {
      setSaving(false);
    }
  }
  function addPerson() {
    if (!draft || !catalog || !canEdit || saveBlocked || saving) return;
    const slug = name
      .trim()
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 64);
    if (
      !/^[a-z0-9][a-z0-9-]{1,63}$/.test(slug) ||
      publishers.some((item) => item.id === slug) ||
      draft.people_org.some((item) => item.id === slug)
    ) {
      setError("Use a unique name of at least two letters for this identity.");
      return;
    }
    if (assetUrl && !/^https:\/\/[A-Za-z0-9.-]+\//.test(assetUrl)) {
      setError("Use a public HTTPS image URL, or leave the asset empty.");
      return;
    }
    update({
      ...draft,
      people_org: [
        ...draft.people_org,
        {
          id: slug,
          name: name.trim(),
          kind,
          asset_ref: assetUrl ? { url: assetUrl, kind: assetKind } : null,
        },
      ],
    });
    setName("");
    setAssetUrl("");
  }
  function addEndpoint() {
    if (!draft || !catalog || !canEdit || saveBlocked || saving) return;
    const publisherId = endpointPublisher;
    const address = endpointAddress.trim();
    const endpointId = `${endpointPlatform}-${address
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")}`.slice(0, 64);
    if (
      !publisherId ||
      !/^[A-Za-z0-9_.]{1,64}$/.test(address) ||
      !/^[a-z0-9][a-z0-9-]{1,63}$/.test(endpointId) ||
      endpoints.some(
        (item) =>
          item.platform === endpointPlatform &&
          item.address.toLowerCase() === address.toLowerCase(),
      ) ||
      draft.endpoints.some(
        (item) =>
          item.id === endpointId ||
          (item.platform === endpointPlatform &&
            item.address.toLowerCase() === address.toLowerCase()),
      )
    ) {
      setError(
        "Choose a People & Org identity and a unique canonical handle (letters, numbers, dot or underscore).",
      );
      return;
    }
    update({
      ...draft,
      endpoints: [
        ...draft.endpoints,
        {
          id: endpointId,
          publisher_id: publisherId,
          platform: endpointPlatform,
          address,
          credential_ref: null,
        },
      ],
    });
    setEndpointAddress("");
    setSelectedEndpoint(endpointId);
  }
  function applyChoice() {
    if (!draft || !selectedCapability || !selected || !canEdit || saveBlocked || saving) return;
    const supported = compatible.some((item) => item.id === selectedCapability);
    if (!supported) {
      setError("This endpoint does not support that capability.");
      return;
    }
    if (level === "endpoint")
      update({
        ...draft,
        endpoint_overrides: [
          ...draft.endpoint_overrides.filter(
            (item) => item.endpoint_id !== selected.id || item.capability_id !== selectedCapability,
          ),
          { endpoint_id: selected.id, capability_id: selectedCapability, enabled, settings: {} },
        ],
      });
    else
      update({
        ...draft,
        publisher_defaults: [
          ...draft.publisher_defaults.filter(
            (item) =>
              item.publisher_id !== selected.publisher_id ||
              item.capability_id !== selectedCapability,
          ),
          {
            publisher_id: selected.publisher_id,
            capability_id: selectedCapability,
            enabled,
            settings: {},
          },
        ],
      });
  }
  return (
    <section className="connected-source-library source-catalog" aria-label="Source catalog">
      <div className="connected-library-heading">
        <h2>Source Catalog</h2>
        <p>
          Engine supported sources and saved configuration. Changes to this catalog do not change
          the fixed workflow editors or prove delivery.
        </p>
      </div>
      {error && (
        <div role="alert" className="control-alert">
          <p>{error}</p>
          <button
            className="button secondary small"
            type="button"
            disabled={loading || saving}
            onClick={() => void reload()}
          >
            Reload current catalog
          </button>
        </div>
      )}
      {loading && <p role="status">Loading source catalog…</p>}
      {catalog && draft && (
        <>
          {!canEdit && (
            <p role="status" className="connected-panel-intro">
              View access. An admin can change source catalog settings.
            </p>
          )}
          {writeRefreshFailed && (
            <p role="status" className="connected-panel-intro">
              The last write was acknowledged but its saved state has not been refreshed.
            </p>
          )}
          <div className="connected-library-tabs" role="tablist" aria-label="Source category">
            {(["securities", "institutions", "people"] as const).map((value) => (
              <button
                key={value}
                type="button"
                role="tab"
                id={`${id}-${value}-tab`}
                aria-controls={`${id}-${value}-panel`}
                aria-selected={tab === value}
                tabIndex={tab === value ? 0 : -1}
                onClick={() => setTab(value)}
                onKeyDown={(event) => {
                  const tabs: Tab[] = ["securities", "institutions", "people"];
                  const index = tabs.indexOf(value);
                  const next =
                    event.key === "ArrowRight"
                      ? tabs[(index + 1) % 3]
                      : event.key === "ArrowLeft"
                        ? tabs[(index + 2) % 3]
                        : event.key === "Home"
                          ? tabs[0]
                          : event.key === "End"
                            ? tabs[2]
                            : null;
                  if (next) {
                    event.preventDefault();
                    setTab(next);
                    document.getElementById(`${id}-${next}-tab`)?.focus();
                  }
                }}
              >
                {value === "people" ? "People & Org" : value[0].toUpperCase() + value.slice(1)}
              </button>
            ))}
          </div>
          <section
            id={`${id}-securities-panel`}
            role="tabpanel"
            aria-labelledby={`${id}-securities-tab`}
            hidden={tab !== "securities"}
            className="connected-library-panel"
          >
            <p className="connected-panel-intro">
              Only engine supported securities can be enabled.
            </p>
            {catalog.securities.length ? (
              <ul className="source-catalog-list">
                {catalog.securities.map((item) => (
                  <li key={item.symbol}>
                    <label>
                      <input
                        type="checkbox"
                        checked={draft.selected_securities.includes(item.symbol)}
                        disabled={!canEdit || saveBlocked || saving}
                        onChange={(event) =>
                          update({
                            ...draft,
                            selected_securities: event.target.checked
                              ? [...draft.selected_securities, item.symbol]
                              : draft.selected_securities.filter(
                                  (symbol) => symbol !== item.symbol,
                                ),
                          })
                        }
                      />{" "}
                      {item.symbol} · {item.name}
                    </label>
                  </li>
                ))}
              </ul>
            ) : (
              <p role="status" className="connected-library-empty">
                No engine supported securities are available yet. Securities can be enabled when
                authoritative records are published.
              </p>
            )}
          </section>
          <section
            id={`${id}-institutions-panel`}
            role="tabpanel"
            aria-labelledby={`${id}-institutions-tab`}
            hidden={tab !== "institutions"}
            className="connected-library-panel"
          >
            <p className="connected-panel-intro">
              Curated institutions and their registered platform endpoints. Institution records are
              managed by the engine. Endpoint badges show identity verification, not subscription
              state or run health.
            </p>
            <ul className="connected-securities-grid">
              {catalog.institutions.map((item) => (
                <li key={item.id}>
                  <article className="connected-security-card">
                    {institutionImages[item.id] && (
                      <figure className="connected-security-figure">
                        <Image src={institutionImages[item.id]} alt="" width={1448} height={1086} />
                        <figcaption>Curated 4:3 illustration</figcaption>
                      </figure>
                    )}
                    <div className="connected-security-content">
                      <h3>{item.name}</h3>
                      <p>
                        Tier {item.tier} ·{" "}
                        {endpoints.filter((entry) => entry.publisher_id === item.id).length}{" "}
                        registered endpoints
                      </p>
                      <p>
                        4:3 banner or logo:{" "}
                        {item.asset_ref?.url ? "Registered" : "No registered asset"}
                      </p>
                      <RegisteredEndpointList
                        endpoints={endpoints.filter((entry) => entry.publisher_id === item.id)}
                      />
                    </div>
                  </article>
                </li>
              ))}
            </ul>
          </section>
          <section
            id={`${id}-people-panel`}
            role="tabpanel"
            aria-labelledby={`${id}-people-tab`}
            hidden={tab !== "people"}
            className="connected-library-panel"
          >
            <p className="connected-panel-intro">
              People, groups and communities. New endpoints remain pending identity verification and
              are not effective subscriptions. Endpoint badges show identity verification only.
            </p>
            <ul className="connected-people-grid">
              {catalog.people_org
                .filter((item) => !draft.people_org.some((entry) => entry.id === item.id))
                .map((item) => (
                  <li key={item.id}>
                    <article className="connected-person-card">
                      <div className="connected-security-content">
                        {curatedPeopleImages[item.id] && (
                          <Image
                            src={curatedPeopleImages[item.id]}
                            alt=""
                            width={52}
                            height={52}
                            className="source-catalog-avatar"
                          />
                        )}
                        <h3>{item.name}</h3>
                        <p>
                          {item.kind ?? "Type unverified"} · Tier {item.tier}
                        </p>
                        <p>
                          {endpoints.filter((entry) => entry.publisher_id === item.id).length}{" "}
                          registered endpoints
                        </p>
                        <p>
                          {item.asset_ref?.kind === "logo"
                            ? "Logo"
                            : item.asset_ref?.kind === "profile_picture"
                              ? "Profile picture"
                              : "No registered image"}
                        </p>
                        <RegisteredEndpointList
                          endpoints={endpoints.filter((entry) => entry.publisher_id === item.id)}
                        />
                      </div>
                    </article>
                  </li>
                ))}
              {draft.people_org.map((item) => (
                <li key={item.id}>
                  <article className="connected-person-card">
                    <div className="connected-security-content">
                      <h3>{item.name}</h3>
                      <p>
                        {item.kind} ·{" "}
                        {catalog.people_org.some((entry) => entry.id === item.id)
                          ? "User managed"
                          : "Unsaved"}
                      </p>
                      <RegisteredEndpointList
                        endpoints={endpoints.filter((entry) => entry.publisher_id === item.id)}
                      />
                      {canEdit && !saveBlocked && (
                        <>
                          <label>
                            Name
                            <input
                              value={item.name}
                              onChange={(event) =>
                                update({
                                  ...draft,
                                  people_org: draft.people_org.map((entry) =>
                                    entry.id === item.id
                                      ? { ...entry, name: event.target.value }
                                      : entry,
                                  ),
                                })
                              }
                            />
                          </label>
                          <label>
                            Type
                            <select
                              value={item.kind}
                              onChange={(event) =>
                                update({
                                  ...draft,
                                  people_org: draft.people_org.map((entry) =>
                                    entry.id === item.id
                                      ? { ...entry, kind: event.target.value as typeof item.kind }
                                      : entry,
                                  ),
                                })
                              }
                            >
                              <option value="person">Person</option>
                              <option value="group">Group</option>
                              <option value="community">Community</option>
                            </select>
                          </label>
                          <label>
                            Image type
                            <select
                              value={item.asset_ref?.kind === "logo" ? "logo" : "profile_picture"}
                              onChange={(event) =>
                                update({
                                  ...draft,
                                  people_org: draft.people_org.map((entry) =>
                                    entry.id === item.id && entry.asset_ref
                                      ? {
                                          ...entry,
                                          asset_ref: {
                                            ...entry.asset_ref,
                                            kind: event.target.value as "logo" | "profile_picture",
                                          },
                                        }
                                      : entry,
                                  ),
                                })
                              }
                            >
                              <option value="profile_picture">Profile picture</option>
                              <option value="logo">Logo</option>
                            </select>
                          </label>
                          <label>
                            Image URL
                            <input
                              type="url"
                              value={item.asset_ref?.url ?? ""}
                              onChange={(event) =>
                                update({
                                  ...draft,
                                  people_org: draft.people_org.map((entry) =>
                                    entry.id === item.id
                                      ? {
                                          ...entry,
                                          asset_ref: event.target.value
                                            ? {
                                                url: event.target.value,
                                                kind:
                                                  item.asset_ref?.kind === "logo"
                                                    ? "logo"
                                                    : "profile_picture",
                                              }
                                            : null,
                                        }
                                      : entry,
                                  ),
                                })
                              }
                            />
                          </label>
                        </>
                      )}
                    </div>
                  </article>
                </li>
              ))}
            </ul>
            {canEdit && !saveBlocked && (
              <fieldset className="source-catalog-form">
                <legend>Add People & Org identity</legend>
                <label>
                  Name
                  <input
                    value={name}
                    maxLength={120}
                    onChange={(event) => setName(event.target.value)}
                  />
                </label>
                <label>
                  Type
                  <select
                    value={kind}
                    onChange={(event) => setKind(event.target.value as typeof kind)}
                  >
                    <option value="person">Person</option>
                    <option value="group">Group</option>
                    <option value="community">Community</option>
                  </select>
                </label>
                <label>
                  Public image URL (optional)
                  <input
                    type="url"
                    value={assetUrl}
                    onChange={(event) => setAssetUrl(event.target.value)}
                    placeholder="https://…"
                  />
                </label>
                <label>
                  Image type
                  <select
                    value={assetKind}
                    onChange={(event) => setAssetKind(event.target.value as typeof assetKind)}
                  >
                    <option value="profile_picture">Profile picture</option>
                    <option value="logo">Logo</option>
                  </select>
                </label>
                <button type="button" className="button secondary" onClick={addPerson}>
                  Add identity to draft
                </button>
              </fieldset>
            )}
          </section>
          <section className="source-catalog-config" aria-labelledby={`${id}-configuration`}>
            <h2 id={`${id}-configuration`}>Endpoint configuration</h2>
            <p>
              Publisher defaults apply to compatible endpoints. Endpoint overrides take precedence.
              This saves catalog intent only.
            </p>
            {canEdit && !saveBlocked && (
              <fieldset className="source-catalog-form">
                <legend>Add an endpoint for People & Org</legend>
                <label>
                  Publisher
                  <select
                    value={endpointPublisher}
                    onChange={(event) => setEndpointPublisher(event.target.value)}
                  >
                    <option value="">Choose a publisher</option>
                    {[
                      ...catalog.people_org,
                      ...draft.people_org
                        .filter((item) => !catalog.people_org.some((entry) => entry.id === item.id))
                        .map((item) => ({ ...item, tier: 3 })),
                    ].map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Platform
                  <select
                    value={endpointPlatform}
                    onChange={(event) =>
                      setEndpointPlatform(event.target.value as typeof endpointPlatform)
                    }
                  >
                    {userPlatforms.map((item) => (
                      <option key={item} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Canonical handle
                  <input
                    value={endpointAddress}
                    onChange={(event) => setEndpointAddress(event.target.value)}
                    maxLength={64}
                  />
                </label>
                <button className="button secondary" type="button" onClick={addEndpoint}>
                  Add pending endpoint to draft
                </button>
              </fieldset>
            )}
            <fieldset className="source-catalog-form">
              <legend>Capability setting</legend>
              <label>
                Endpoint
                <select
                  aria-label="Endpoint"
                  value={selectedEndpoint}
                  onChange={(event) => {
                    setSelectedEndpoint(event.target.value);
                    setSelectedCapability("");
                  }}
                >
                  <option value="">Choose an endpoint</option>
                  {[
                    ...endpoints,
                    ...draft.endpoints
                      .filter((item) => !endpoints.some((entry) => entry.id === item.id))
                      .map((item) => ({
                        ...item,
                        provider_id: null,
                        system_owned: false,
                        verified: false,
                      })),
                  ].map((item) => (
                    <option key={item.id} value={item.id}>
                      {publishers.find((publisher) => publisher.id === item.publisher_id)?.name ??
                        draft.people_org.find((publisher) => publisher.id === item.publisher_id)
                          ?.name ??
                        item.publisher_id}{" "}
                      · {item.platform} · {item.address}
                      {item.verified ? "" : " (pending)"}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Capability
                <select
                  aria-label="Capability"
                  value={selectedCapability}
                  onChange={(event) => setSelectedCapability(event.target.value)}
                  disabled={!selectedEndpoint}
                >
                  <option value="">Choose a compatible capability</option>
                  {compatible.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
              {selected && !catalog.endpoints.some((item) => item.id === selected.id) && (
                <p role="status">
                  Save this pending endpoint first to load its backend-supported capabilities.
                </p>
              )}
              {canEdit && !saveBlocked && (
                <>
                  <label>
                    Set at
                    <select
                      value={level}
                      onChange={(event) => setLevel(event.target.value as typeof level)}
                    >
                      <option value="publisher">Publisher default</option>
                      <option value="endpoint">Endpoint override</option>
                    </select>
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={(event) => setEnabled(event.target.checked)}
                    />{" "}
                    Enabled intent
                  </label>
                  {chosen && (
                    <p role="status">
                      Publisher default:{" "}
                      {draft.publisher_defaults.find(
                        (item) =>
                          item.publisher_id === selected?.publisher_id &&
                          item.capability_id === selectedCapability,
                      )?.enabled
                        ? "On"
                        : "Off or unset"}
                      . Endpoint override:{" "}
                      {draft.endpoint_overrides.find(
                        (item) =>
                          item.endpoint_id === selectedEndpoint &&
                          item.capability_id === selectedCapability,
                      )?.enabled === true
                        ? "On"
                        : draft.endpoint_overrides.some(
                              (item) =>
                                item.endpoint_id === selectedEndpoint &&
                                item.capability_id === selectedCapability,
                            )
                          ? "Off"
                          : "Unset"}
                      . Effective draft: {chosen.enabled && selected?.verified ? "On" : "Off"} (
                      {chosen.source}). Saved: {subscription?.enabled ? "On" : "Off"} (
                      {subscription?.source ?? "unset"},{" "}
                      {subscription?.verification_status ?? "pending"}).
                    </p>
                  )}
                  <button
                    type="button"
                    className="button secondary"
                    disabled={!selectedCapability}
                    onClick={applyChoice}
                  >
                    Apply setting to draft
                  </button>
                </>
              )}
            </fieldset>
          </section>
          <div className="source-catalog-save">
            <p role="status">
              Revision {catalog.config.revision} ·{" "}
              {writeRefreshFailed
                ? "Save acknowledged, refresh unconfirmed"
                : dirty
                  ? "Unsaved changes"
                  : "Saved catalog"}
            </p>
            {canEdit && (
              <button
                type="button"
                className="button"
                disabled={!dirty || saving || saveBlocked}
                onClick={() => void save()}
              >
                {saving ? "Saving…" : "Save catalog"}
              </button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
