"use client";

import Image from "next/image";
import Link from "next/link";
import { countConfigChanges, matchesConfigSearch } from "@/lib/config-changes";
import { watcherNames } from "@/lib/watcher-fields";
import { SaveButton } from "./save-button";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { controlBrowser } from "@/lib/control-browser";
import type { OperatorComponent, OperatorComponentActivity } from "@/lib/operator-inventory";
import { isEffectiveSubscription } from "@/lib/control-analytics";
import { WorkspaceError } from "@/lib/control-browser";
import {
  catalogConfig,
  compatibleCapabilities,
  effectiveChoice,
  type CatalogConfig,
  type EffectiveCatalog,
  type SourceCatalog,
} from "@/lib/source-catalog";
import {
  discardWorkspaceDraft,
  getDraftOwner,
  readWorkspaceDraft,
  retainWorkspaceDraft,
} from "@/lib/workspace-drafts";
import { StatusBadge } from "./status-badge";
import { useToast } from "./toast-provider";
import { WorkspaceLoading, type LoadingRequest } from "./workspace-loading";
import { useUnsavedWarning } from "./watcher-config-editor";
import "@/app/connected-sources.css";

type Request = ReturnType<typeof controlBrowser>;
type Tab = "securities" | "institutions" | "people";
type RetainedCatalogDraft = { config: CatalogConfig; tab: Tab; writeRefreshFailed: boolean };
const catalogDraftKey = "source-catalog";
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

function RegisteredEndpointList({
  endpoints,
  effective = [],
}: {
  endpoints: SourceCatalog["endpoints"];
  effective?: EffectiveCatalog["subscriptions"];
}) {
  if (endpoints.length === 0) return null;
  return (
    <ul className="source-endpoint-list" aria-label="Registered accounts and channels">
      {endpoints.map((endpoint) => (
        <li className="source-endpoint-row" key={endpoint.id}>
          <div className="source-endpoint-detail">
            <span className="source-endpoint-identity">
              <strong>{endpoint.platform}</strong> · {endpoint.address}
            </span>
            <span className="source-endpoint-subscriptions">
              Resolved:{" "}
              {
                effective.filter(
                  (row) => row.endpoint_id === endpoint.id && isEffectiveSubscription(row),
                ).length
              }{" "}
              effective ·{" "}
              {
                effective.filter(
                  (row) =>
                    row.endpoint_id === endpoint.id &&
                    row.enabled &&
                    row.verification_status === "pending",
                ).length
              }{" "}
              awaiting verification
            </span>
          </div>
          <StatusBadge
            status={endpoint.verified ? "verified" : "verification-pending"}
            label={endpoint.verified ? "Identity verified" : "Identity pending"}
          />
        </li>
      ))}
    </ul>
  );
}

function SourceAdapterEvidence({
  components,
  activity,
  unavailable,
}: {
  components: OperatorComponent[];
  activity: OperatorComponentActivity[];
  unavailable: boolean;
}) {
  const sourceAdapters = components.filter((item) => item.kind === "source_adapter");
  const activityById = new Map(activity.map((item) => [item.component_id, item]));
  if (!sourceAdapters.length && !unavailable) return null;
  return (
    <section className="source-adapter-evidence" aria-labelledby="source-adapter-evidence-title">
      <div>
        <h2 id="source-adapter-evidence-title">Adapter and intake evidence</h2>
        <p>
          Catalog choices show intent. Adapter binding and accepted Source Inbox input are reported
          separately.
        </p>
      </div>
      {unavailable ? (
        <p role="status">
          Some adapter evidence could not be loaded. Missing rows are unavailable, not zero.
        </p>
      ) : null}
      <ul>
        {sourceAdapters.map((adapter) => {
          const row = activityById.get(adapter.component_id);
          const latest = row?.endpoints
            .filter((endpoint) => endpoint.accepted_at)
            .sort((a, b) => Date.parse(b.accepted_at!) - Date.parse(a.accepted_at!))[0];
          const binding = adapter.source_gate?.capabilities ?? [];
          const enabled = binding.reduce((sum, item) => sum + item.enabled_endpoint_count, 0);
          const total = binding.reduce((sum, item) => sum + item.endpoint_count, 0);
          const status = latest?.status ?? "unknown";
          return (
            <li key={adapter.component_id}>
              <strong>{adapter.display_name}</strong>
              <span>
                Adapter binding:{" "}
                {binding.length
                  ? `${enabled} of ${total} enabled catalog endpoints`
                  : "unavailable"}
              </span>
              <span>
                Last accepted input:{" "}
                {latest?.accepted_at ? (
                  <time dateTime={latest.accepted_at}>
                    {new Date(latest.accepted_at).toLocaleString("en-GB", {
                      timeZone: "Asia/Jakarta",
                    })}{" "}
                    WIB
                  </time>
                ) : status === "unknown" ? (
                  "Unknown"
                ) : (
                  "No accepted input recorded"
                )}
              </span>
              <span>
                Input status:{" "}
                {status === "observed" ? "Observed" : status === "stale" ? "Stale" : "Unknown"}
              </span>
              <span>Delivery: {row?.delivery_status ?? "Not instrumented"}</span>
              {adapter.component_id === "bursawatch-ig-source-ingest" &&
              adapter.job_ids.length === 0 ? (
                <span>Schedule: no registered source job</span>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
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

const revisionMismatchMessage = "Catalog revisions differ. Refresh to read a consistent snapshot.";
const sourceRequests: LoadingRequest[] = [
  { label: "Source catalog", status: "loading" },
  { label: "Effective subscriptions", status: "loading" },
];

function safeReadError(error: unknown) {
  if (error instanceof Error && error.message === revisionMismatchMessage) return error.message;
  if (error instanceof WorkspaceError) {
    const reasons: Record<string, string> = {
      auth: "Your session has expired. Sign in again.",
      forbidden: "Your account cannot access the source catalog.",
      timeout: "The request timed out. Try again.",
      "rate-limit": "The service is busy. Wait a moment, then try again.",
      setup: "The workspace owner needs to finish connecting the service.",
      "invalid-response": "The response could not be verified. Try again.",
    };
    if (reasons[error.code]) return reasons[error.code];
  }
  return "The source catalog could not be loaded. Check your connection and try again.";
}

export function SourceCatalogView({
  request,
  onDirtyChange,
  components = [],
  activity = [],
  activityUnavailable = false,
}: {
  request: Request;
  onDirtyChange: (dirty: boolean) => void;
  components?: OperatorComponent[];
  activity?: OperatorComponentActivity[];
  activityUnavailable?: boolean;
}) {
  const [draftOwner] = useState(getDraftOwner);
  const [restored] = useState(() =>
    readWorkspaceDraft<SourceCatalog["config"], RetainedCatalogDraft>(catalogDraftKey),
  );
  const mounted = useRef(false);
  const readController = useRef<AbortController | null>(null);
  const [catalog, setCatalog] = useState<SourceCatalog | null>(null);
  const [effective, setEffective] = useState<EffectiveCatalog | null>(null);
  const [draft, setDraft] = useState<CatalogConfig | null>(null);
  const [tab, setTab] = useState<Tab>(restored?.draft.tab ?? "securities");
  const [loading, setLoading] = useState(true);
  const [readRequests, setReadRequests] = useState<LoadingRequest[]>(sourceRequests);
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
  const [choiceEdit, setChoiceEdit] = useState<{ key: string; value: string } | null>(null);
  const [query, setQuery] = useState("");
  const [platformFilter, setPlatformFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [focusedPublisher, setFocusedPublisher] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const id = useId();
  const toast = useToast();
  const changes = countConfigChanges(catalog?.config.config, draft);
  const dirty = Boolean(
    catalog && draft && JSON.stringify(catalog.config.config) !== JSON.stringify(draft),
  );
  const canEdit = catalog?.can_edit === true;
  useUnsavedWarning(canEdit && (dirty || saving));
  useEffect(() => {
    onDirtyChange(canEdit && (dirty || saving));
    return () => onDirtyChange(false);
  }, [canEdit, dirty, saving, onDirtyChange]);
  useEffect(() => {
    if (!catalog || !draft || !canEdit) return;
    retainWorkspaceDraft(
      catalogDraftKey,
      {
        base: catalog.config,
        draft: { config: draft, tab, writeRefreshFailed },
        blocked: saveBlocked || saving,
        failure: saving
          ? "A previous catalog save has not been confirmed here. Reload the current catalog before trying again."
          : error,
      },
      dirty || saving || writeRefreshFailed,
      draftOwner,
    );
  }, [
    catalog,
    draft,
    canEdit,
    tab,
    writeRefreshFailed,
    saveBlocked,
    saving,
    error,
    dirty,
    draftOwner,
  ]);
  const reload = useCallback(
    async (signal?: AbortSignal, recoverDraft = false) => {
      if (!mounted.current) return false;
      setLoading(true);
      setReadRequests(sourceRequests.map((entry) => ({ ...entry })));
      setError("");
      readController.current?.abort();
      const controller = new AbortController();
      readController.current = controller;
      const cancel = () => controller.abort();
      signal?.addEventListener("abort", cancel, { once: true });
      if (signal?.aborted) controller.abort();
      const mark = (index: number, status: LoadingRequest["status"], failure?: unknown) => {
        if (controller.signal.aborted) return;
        setReadRequests((current) =>
          current.map((entry, position) =>
            position === index
              ? { ...entry, status, message: failure ? safeReadError(failure) : undefined }
              : entry,
          ),
        );
      };
      async function read<T>(path: string, index: number): Promise<T> {
        try {
          const result = await request<T>(path, undefined, { signal: controller.signal });
          mark(index, "ready");
          return result;
        } catch (failure) {
          mark(index, "error", failure);
          if (
            failure instanceof WorkspaceError &&
            ["auth", "forbidden"].includes(failure.code) &&
            !controller.signal.aborted &&
            mounted.current
          ) {
            discardWorkspaceDraft(catalogDraftKey, draftOwner);
            setCatalog(null);
            setDraft(null);
            setEffective(null);
            controller.abort();
          }
          throw failure;
        }
      }
      try {
        const [catalogResult, effectiveResult] = await Promise.allSettled([
          read<SourceCatalog>("source-catalog", 0),
          read<EffectiveCatalog>("source-catalog/effective", 1),
        ]);
        const failures = [catalogResult, effectiveResult].filter(
          (result): result is PromiseRejectedResult => result.status === "rejected",
        );
        if (failures.length) {
          const accessFailure = failures.find(
            (result) =>
              result.reason instanceof WorkspaceError &&
              ["auth", "forbidden"].includes(result.reason.code),
          );
          throw (accessFailure ?? failures[0]).reason;
        }
        if (catalogResult.status !== "fulfilled" || effectiveResult.status !== "fulfilled")
          throw new Error("The source catalog could not be loaded.");
        const nextCatalog = catalogResult.value;
        const nextEffective = effectiveResult.value;
        if (nextCatalog.config.revision !== nextEffective.revision)
          throw new Error(revisionMismatchMessage);
        if (controller.signal.aborted || !mounted.current || draftOwner !== getDraftOwner())
          return false;
        setEffective(nextEffective);
        if (recoverDraft && restored && nextCatalog.can_edit) {
          const conflict = restored.base.revision !== nextCatalog.config.revision;
          setCatalog({ ...nextCatalog, config: restored.base });
          setDraft(structuredClone(restored.draft.config));
          setSaveBlocked(conflict || Boolean(restored.blocked));
          setWriteRefreshFailed(restored.draft.writeRefreshFailed);
          setError(
            conflict
              ? "The catalog changed while you were away. Your draft is preserved; reload to review the latest saved catalog."
              : restored.failure || "",
          );
        } else {
          setCatalog(nextCatalog);
          setDraft(structuredClone(nextCatalog.config.config));
          setSaveBlocked(false);
          setWriteRefreshFailed(false);
          setFieldErrors({});
          setChoiceEdit(null);
          setFocusedPublisher("");
          setSelectedEndpoint("");
          setSelectedCapability("");
          discardWorkspaceDraft(catalogDraftKey, draftOwner);
        }
        return true;
      } catch (failure) {
        if (signal?.aborted || !mounted.current) return false;
        setError(safeReadError(failure));
        setSaveBlocked(true);
        if (failure instanceof WorkspaceError && ["auth", "forbidden"].includes(failure.code)) {
          discardWorkspaceDraft(catalogDraftKey, draftOwner);
          setCatalog(null);
          setDraft(null);
          setEffective(null);
        }
        return false;
      } finally {
        signal?.removeEventListener("abort", cancel);
        if (!signal?.aborted && mounted.current) setLoading(false);
      }
    },
    [request, restored, draftOwner],
  );
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    queueMicrotask(() => {
      if (!controller.signal.aborted) void reload(controller.signal, true);
    });
    return () => {
      mounted.current = false;
      controller.abort();
      readController.current?.abort();
    };
  }, [reload]);
  const update = (value: CatalogConfig) => {
    if (!canEdit || saveBlocked || saving) return;
    setDraft(value);
    setError("");
    setFieldErrors({});
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
      const errors: Record<string, string> = {};
      for (const issue of parsed.error.issues) errors[issue.path.join(".")] = issue.message;
      setFieldErrors(errors);
      setTab("people");
      const identityIssue = parsed.error.issues.find((issue) => issue.path[0] === "people_org");
      setFocusedPublisher(
        identityIssue ? (draft.people_org[Number(identityIssue.path[1])]?.id ?? "") : "",
      );
      setQuery("");
      setPlatformFilter("all");
      setStatusFilter("all");
      setError("Review the marked source fields before saving.");
      requestAnimationFrame(() =>
        document.querySelector<HTMLElement>('.source-catalog [aria-invalid="true"]')?.focus(),
      );
      return;
    }
    setSaving(true);
    setError("");
    try {
      await request("source-catalog/config", {
        expected_revision: catalog.config.revision,
        config: parsed.data,
      });
      if (!mounted.current) return;
      const refreshed = await reload();
      if (!mounted.current) return;
      if (refreshed) {
        toast("Source catalog saved. Pending endpoints still require identity verification.");
      } else {
        setSaveBlocked(true);
        setWriteRefreshFailed(true);
        setError(
          "The save response was received, but the catalog refresh could not be confirmed. Your draft is locked. Reload current catalog before editing again.",
        );
      }
    } catch (failure) {
      if (!mounted.current) return;
      setError(message(failure));
      if (failure instanceof WorkspaceError && ["auth", "forbidden"].includes(failure.code)) {
        discardWorkspaceDraft(catalogDraftKey, draftOwner);
        setCatalog(null);
        setDraft(null);
        setEffective(null);
      }
      if (
        failure instanceof WorkspaceError &&
        ["conflict", "unknown-outcome", "forbidden"].includes(failure.code)
      )
        setSaveBlocked(true);
    } finally {
      if (mounted.current) setSaving(false);
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
      invalidField("new-name", "Use a unique name of at least two letters for this identity.");
      return;
    }
    if (assetUrl && !/^https:\/\/[A-Za-z0-9.-]+\//.test(assetUrl)) {
      invalidField("new-image", "Use a public HTTPS image URL, or leave the asset empty.");
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
      invalidField(
        publisherId ? "new-handle" : "new-publisher",
        "Choose a source and a unique handle using letters, numbers, dots or underscores.",
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
  const allEndpoints = [
    ...endpoints,
    ...(draft?.endpoints ?? [])
      .filter((item) => !endpoints.some((entry) => entry.id === item.id))
      .map((item) => ({ ...item, provider_id: null, system_owned: false, verified: false })),
  ];
  const currentSetting =
    level === "endpoint"
      ? draft?.endpoint_overrides.find(
          (item) =>
            item.endpoint_id === selectedEndpoint && item.capability_id === selectedCapability,
        )
      : draft?.publisher_defaults.find(
          (item) =>
            item.publisher_id === selected?.publisher_id &&
            item.capability_id === selectedCapability,
        );
  const choiceKey = `${selectedEndpoint}:${selectedCapability}:${level}`;
  const savedChoice = currentSetting ? (currentSetting.enabled ? "on" : "off") : "default";
  const choice = choiceEdit?.key === choiceKey ? choiceEdit.value : savedChoice;
  const focusedSource = [...(draft?.people_org ?? []), ...publishers].find(
    (item) => item.id === focusedPublisher,
  );
  function invalidField(key: string, value: string) {
    setFieldErrors({ [key]: value });
    setError(value);
    requestAnimationFrame(() => document.getElementById(`${id}-${key}`)?.focus());
  }
  function fieldProps(key: string, label: string) {
    return {
      id: `${id}-${key}`,
      "aria-label": label,
      "aria-invalid": Boolean(fieldErrors[key]),
      "aria-describedby": fieldErrors[key] ? `${id}-${key}-error` : undefined,
    };
  }
  function fieldError(key: string) {
    return fieldErrors[key] ? (
      <small className="source-field-error" id={`${id}-${key}-error`}>
        {fieldErrors[key]}
      </small>
    ) : null;
  }
  function openSource(publisherId: string) {
    setFocusedPublisher(publisherId);
    setEndpointPublisher(publisherId);
    setSelectedEndpoint(allEndpoints.find((item) => item.publisher_id === publisherId)?.id ?? "");
    setSelectedCapability("");
    setChoiceEdit(null);
    requestAnimationFrame(() => {
      const heading = document.getElementById(`${id}-configuration`);
      heading?.focus();
      heading?.scrollIntoView({ block: "start", behavior: "instant" });
    });
  }
  function showPublisher(item: { id: string; name: string }) {
    if (focusedPublisher) return item.id === focusedPublisher;
    const accounts = allEndpoints.filter((entry) => entry.publisher_id === item.id);
    return (
      matchesConfigSearch(
        `${item.name} ${accounts.map((entry) => `${entry.platform} ${entry.address}`).join(" ")}`,
        query,
      ) &&
      (platformFilter === "all" || accounts.some((entry) => entry.platform === platformFilter)) &&
      (statusFilter === "all" ||
        accounts.some((entry) =>
          statusFilter === "verified"
            ? entry.verified
            : statusFilter === "pending"
              ? !entry.verified
              : compatibleCapabilities(catalog!, entry.id).some(
                  (capability) =>
                    entry.verified &&
                    effectiveChoice(draft!, item.id, entry.id, capability.id).enabled,
                ),
        ))
    );
  }
  const relatedWorkflows =
    focusedPublisher && catalog
      ? components
          .filter(
            (component) =>
              component.kind === "domain_owner" &&
              component.pipeline_ids.some((pipeline) =>
                allEndpoints
                  .filter((item) => item.publisher_id === focusedPublisher)
                  .some((endpoint) =>
                    compatibleCapabilities(catalog, endpoint.id).some(
                      (capability) => capability.pipeline === pipeline,
                    ),
                  ),
              ),
          )
          .flatMap((component) => {
            const ids = [
              ...new Set(
                component.config_resource_ids
                  .map((resource) => resource.replace(/^watcher:/, ""))
                  .filter((watcherId) => Object.hasOwn(watcherNames, watcherId)),
              ),
            ];
            return ids.length === 1 ? ids : [];
          })
      : [];
  function applyChoice() {
    if (
      !draft ||
      !selectedCapability ||
      !selected ||
      !canEdit ||
      saveBlocked ||
      saving ||
      choice === savedChoice
    )
      return;
    if (!compatible.some((item) => item.id === selectedCapability)) return;
    if (level === "endpoint") {
      const rows = draft.endpoint_overrides.filter(
        (item) => item.endpoint_id !== selected.id || item.capability_id !== selectedCapability,
      );
      update({
        ...draft,
        endpoint_overrides:
          choice === "default"
            ? rows
            : currentSetting
              ? draft.endpoint_overrides.map((item) =>
                  item === currentSetting ? { ...item, enabled: choice === "on" } : item,
                )
              : [
                  ...rows,
                  {
                    endpoint_id: selected.id,
                    capability_id: selectedCapability,
                    enabled: choice === "on",
                    settings: {},
                  },
                ],
      });
    } else {
      const rows = draft.publisher_defaults.filter(
        (item) =>
          item.publisher_id !== selected.publisher_id || item.capability_id !== selectedCapability,
      );
      update({
        ...draft,
        publisher_defaults:
          choice === "default"
            ? rows
            : currentSetting
              ? draft.publisher_defaults.map((item) =>
                  item === currentSetting ? { ...item, enabled: choice === "on" } : item,
                )
              : [
                  ...rows,
                  {
                    publisher_id: selected.publisher_id,
                    capability_id: selectedCapability,
                    enabled: choice === "on",
                    settings: {},
                  },
                ],
      });
    }
    setChoiceEdit(null);
  }
  return (
    <section className="connected-source-library source-catalog" aria-label="Source catalog">
      <div className="connected-library-heading">
        <h2>Source Catalog</h2>
        <p>
          Choose catalog sources and content here.{" "}
          <Link href="/workspace/workflows">Workflows</Link> manage their own inputs, processing and
          destinations. <Link href="/workspace/jobs">Jobs</Link> controls schedules.
        </p>
      </div>
      {error && (
        <div role="alert" className="control-alert">
          <p>{error}</p>
          <button
            className="button secondary small"
            type="button"
            disabled={loading || saving}
            onClick={() => {
              if (
                (!dirty && !readWorkspaceDraft(catalogDraftKey)) ||
                window.confirm("Discard unsaved changes and reload the current catalog?")
              )
                void reload();
            }}
          >
            Reload current catalog
          </button>
        </div>
      )}
      {loading && (
        <WorkspaceLoading
          title="Loading source catalog…"
          requests={readRequests}
          compact={Boolean(catalog)}
        />
      )}
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
                onClick={() => {
                  setTab(value);
                  setFocusedPublisher("");
                  setSelectedEndpoint("");
                  setSelectedCapability("");
                }}
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
                    setFocusedPublisher("");
                    setSelectedEndpoint("");
                    setSelectedCapability("");
                    document.getElementById(`${id}-${next}-tab`)?.focus();
                  }
                }}
              >
                {value === "people" ? "People & Org" : value[0].toUpperCase() + value.slice(1)}
              </button>
            ))}
          </div>
          {focusedSource ? (
            <div className="source-catalog-focus-heading">
              <button
                className="button secondary small"
                type="button"
                onClick={() => {
                  setFocusedPublisher("");
                  setSelectedEndpoint("");
                  setSelectedCapability("");
                  requestAnimationFrame(() =>
                    document.getElementById(`${id}-source-${focusedSource.id}`)?.focus(),
                  );
                }}
              >
                Back to all sources
              </button>
              <p>
                Accounts and content for <strong>{focusedSource.name}</strong>
              </p>
            </div>
          ) : (
            <div className="config-browse-tools" role="search" aria-label="Find catalog sources">
              <label>
                Search {tab === "securities" ? "securities" : "sources"}
                <input
                  type="search"
                  value={query}
                  placeholder={
                    tab === "securities" ? "Symbol or company name" : "Name, platform or handle"
                  }
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
              {tab !== "securities" && (
                <>
                  <label>
                    Platform
                    <select
                      value={platformFilter}
                      onChange={(event) => setPlatformFilter(event.target.value)}
                    >
                      <option value="all">All platforms</option>
                      {[...new Set(allEndpoints.map((endpoint) => endpoint.platform))]
                        .sort()
                        .map((platform) => (
                          <option key={platform} value={platform}>
                            {platform}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label>
                    Source status
                    <select
                      value={statusFilter}
                      onChange={(event) => setStatusFilter(event.target.value)}
                    >
                      <option value="all">All sources</option>
                      <option value="included">Content included</option>
                      <option value="verified">Identity verified</option>
                      <option value="pending">Identity pending</option>
                    </select>
                  </label>
                </>
              )}
              {(query || platformFilter !== "all" || statusFilter !== "all") && (
                <button
                  className="button secondary small"
                  type="button"
                  onClick={() => {
                    setQuery("");
                    setPlatformFilter("all");
                    setStatusFilter("all");
                  }}
                >
                  Clear filters
                </button>
              )}
            </div>
          )}
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
              <>
                <p role="status" className="config-search-count">
                  {
                    catalog.securities.filter((item) =>
                      matchesConfigSearch(`${item.symbol} ${item.name}`, query),
                    ).length
                  }{" "}
                  of {catalog.securities.length} securities
                </p>
                <ul className="source-catalog-list">
                  {catalog.securities
                    .filter((item) => matchesConfigSearch(`${item.symbol} ${item.name}`, query))
                    .map((item) => (
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
              </>
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
              Open an institution to choose content from its accounts and channels. Institutions are
              managed by the engine. Identity verification is separate from content inclusion and
              run health.
            </p>
            {catalog.institutions.filter(showPublisher).length === 0 && (
              <p role="status" className="connected-library-empty">
                No institutions match these filters.
              </p>
            )}
            <ul className={`connected-securities-grid${focusedPublisher ? " is-focused" : ""}`}>
              {catalog.institutions.filter(showPublisher).map((item) => (
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
                      {!focusedPublisher && (
                        <button
                          id={`${id}-source-${item.id}`}
                          className="button secondary small"
                          type="button"
                          aria-label={`View accounts and content for ${item.name}`}
                          onClick={() => openSource(item.id)}
                        >
                          View accounts and content
                        </button>
                      )}
                      <p>
                        Tier {item.tier} ·{" "}
                        {endpoints.filter((entry) => entry.publisher_id === item.id).length}{" "}
                        registered accounts
                      </p>
                      <p>
                        4:3 banner or logo:{" "}
                        {item.asset_ref?.url ? "Registered" : "No registered asset"}
                      </p>
                      {focusedPublisher && (
                        <RegisteredEndpointList
                          endpoints={allEndpoints.filter((entry) => entry.publisher_id === item.id)}
                          effective={effective?.subscriptions ?? []}
                        />
                      )}
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
              People, groups and communities. Open a source to choose accounts and content. New
              accounts remain pending verification before their content can be included.
            </p>
            {[
              ...catalog.people_org.filter(
                (item) => !draft.people_org.some((entry) => entry.id === item.id),
              ),
              ...draft.people_org,
            ].filter(showPublisher).length === 0 && (
              <p role="status" className="connected-library-empty">
                No people or organizations match these filters.
              </p>
            )}
            <ul className={`connected-people-grid${focusedPublisher ? " is-focused" : ""}`}>
              {catalog.people_org
                .filter(
                  (item) =>
                    !draft.people_org.some((entry) => entry.id === item.id) && showPublisher(item),
                )
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
                        {!focusedPublisher && (
                          <button
                            id={`${id}-source-${item.id}`}
                            className="button secondary small"
                            type="button"
                            aria-label={`View accounts and content for ${item.name}`}
                            onClick={() => openSource(item.id)}
                          >
                            View accounts and content
                          </button>
                        )}
                        <p>
                          {item.kind ?? "Type unverified"} · Tier {item.tier}
                        </p>
                        <p>
                          {endpoints.filter((entry) => entry.publisher_id === item.id).length}{" "}
                          registered accounts
                        </p>
                        <p>
                          {item.asset_ref?.kind === "logo"
                            ? "Logo"
                            : item.asset_ref?.kind === "profile_picture"
                              ? "Profile picture"
                              : "No registered image"}
                        </p>
                        {focusedPublisher && (
                          <RegisteredEndpointList
                            endpoints={allEndpoints.filter(
                              (entry) => entry.publisher_id === item.id,
                            )}
                            effective={effective?.subscriptions ?? []}
                          />
                        )}
                      </div>
                    </article>
                  </li>
                ))}
              {draft.people_org
                .map((item, index) => ({ item, index }))
                .filter(({ item }) => showPublisher(item))
                .map(({ item, index }) => (
                  <li key={item.id}>
                    <article className="connected-person-card">
                      <div className="connected-security-content">
                        <h3>{item.name}</h3>
                        {!focusedPublisher && (
                          <button
                            id={`${id}-source-${item.id}`}
                            className="button secondary small"
                            type="button"
                            aria-label={`View accounts and content for ${item.name}`}
                            onClick={() => openSource(item.id)}
                          >
                            View accounts and content
                          </button>
                        )}
                        <p>
                          {item.kind} ·{" "}
                          {catalog.people_org.some((entry) => entry.id === item.id)
                            ? "User managed"
                            : "Unsaved"}
                        </p>
                        {focusedPublisher && (
                          <RegisteredEndpointList
                            endpoints={allEndpoints.filter(
                              (entry) => entry.publisher_id === item.id,
                            )}
                            effective={effective?.subscriptions ?? []}
                          />
                        )}
                        {canEdit && !saveBlocked && focusedPublisher === item.id && (
                          <>
                            <label>
                              Name
                              <input
                                {...fieldProps(`people_org.${index}.name`, "Name")}
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
                              {fieldError(`people_org.${index}.name`)}
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
                                              kind: event.target.value as
                                                "logo" | "profile_picture",
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
                                {...fieldProps(`people_org.${index}.asset_ref.url`, "Image URL")}
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
                              {fieldError(`people_org.${index}.asset_ref.url`)}
                            </label>
                          </>
                        )}
                      </div>
                    </article>
                  </li>
                ))}
            </ul>
            {canEdit && !saveBlocked && !focusedPublisher && (
              <fieldset className="source-catalog-form">
                <legend>Add People & Org identity</legend>
                <label>
                  Name
                  <input
                    {...fieldProps("new-name", "Name")}
                    value={name}
                    maxLength={120}
                    onChange={(event) => {
                      setName(event.target.value);
                      setFieldErrors({});
                    }}
                  />
                  {fieldError("new-name")}
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
                    {...fieldProps("new-image", "Public image URL (optional)")}
                    type="url"
                    value={assetUrl}
                    onChange={(event) => setAssetUrl(event.target.value)}
                    placeholder="https://…"
                  />
                  {fieldError("new-image")}
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
          <section
            className="source-catalog-config"
            aria-labelledby={`${id}-configuration`}
            hidden={tab === "securities"}
          >
            <h2 id={`${id}-configuration`} tabIndex={-1}>
              Accounts and content{focusedSource ? ` · ${focusedSource.name}` : ""}
            </h2>
            <p>
              Choose which content to include from each account or channel. Account choices override
              source defaults. Save the catalog to use your changes; identity verification and
              delivery are separate.
            </p>
            <fieldset className="source-catalog-form">
              <legend>Content choices</legend>
              <label>
                Account or channel
                <select
                  aria-label="Account or channel"
                  value={selectedEndpoint}
                  onChange={(event) => {
                    setSelectedEndpoint(event.target.value);
                    setSelectedCapability("");
                    setChoiceEdit(null);
                  }}
                >
                  <option value="">Choose an account or channel</option>
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
                  ]
                    .filter((item) => !focusedPublisher || item.publisher_id === focusedPublisher)
                    .map((item) => (
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
                Content type
                <select
                  aria-label="Content type"
                  value={selectedCapability}
                  onChange={(event) => {
                    setSelectedCapability(event.target.value);
                    setChoiceEdit(null);
                  }}
                  disabled={!selectedEndpoint}
                >
                  <option value="">Choose a supported content type</option>
                  {compatible.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
              {selected && !catalog.endpoints.some((item) => item.id === selected.id) && (
                <p role="status">
                  Save this pending account first to load its supported content types.
                </p>
              )}
              {chosen && (
                <p role="status">
                  Source default:{" "}
                  {draft.publisher_defaults.find(
                    (item) =>
                      item.publisher_id === selected?.publisher_id &&
                      item.capability_id === selectedCapability,
                  )?.enabled
                    ? "On"
                    : draft.publisher_defaults.some(
                          (item) =>
                            item.publisher_id === selected?.publisher_id &&
                            item.capability_id === selectedCapability,
                        )
                      ? "Off"
                      : "Unset"}
                  . Account override:{" "}
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
              {canEdit && !saveBlocked && (
                <>
                  <label>
                    Apply to
                    <select
                      value={level}
                      onChange={(event) => {
                        setLevel(event.target.value as typeof level);
                        setChoiceEdit(null);
                      }}
                    >
                      <option value="publisher">Source default (all compatible accounts)</option>
                      <option value="endpoint">This account only</option>
                    </select>
                  </label>
                  <label>
                    Include this content
                    <select
                      value={choice}
                      disabled={!selectedCapability || saving}
                      onChange={(event) =>
                        setChoiceEdit({ key: choiceKey, value: event.target.value })
                      }
                    >
                      <option value="default">
                        {level === "endpoint" ? "Use source default" : "No default (off)"}
                      </option>
                      <option value="on">On</option>
                      <option value="off">Off</option>
                    </select>
                  </label>
                  <button
                    type="button"
                    className="button secondary"
                    disabled={!selectedCapability || saving || choice === savedChoice}
                    onClick={applyChoice}
                  >
                    Apply setting to draft
                  </button>
                </>
              )}
            </fieldset>
            {canEdit && !saveBlocked && tab === "people" && (
              <fieldset className="source-catalog-form">
                <legend>Add an account or channel</legend>
                <label>
                  Source
                  <select
                    {...fieldProps("new-publisher", "Source")}
                    value={endpointPublisher}
                    onChange={(event) => setEndpointPublisher(event.target.value)}
                  >
                    <option value="">Choose a source</option>
                    {[
                      ...catalog.people_org,
                      ...draft.people_org
                        .filter((item) => !catalog.people_org.some((entry) => entry.id === item.id))
                        .map((item) => ({ ...item, tier: 3 })),
                    ]
                      .filter((item) => !focusedPublisher || item.id === focusedPublisher)
                      .map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name}
                        </option>
                      ))}
                  </select>
                  {fieldError("new-publisher")}
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
                  Handle (without @)
                  <input
                    {...fieldProps("new-handle", "Handle (without @)")}
                    value={endpointAddress}
                    onChange={(event) => setEndpointAddress(event.target.value)}
                    maxLength={64}
                  />
                  {fieldError("new-handle")}
                </label>
                <button className="button secondary" type="button" onClick={addEndpoint}>
                  Add pending account to draft
                </button>
              </fieldset>
            )}
            {relatedWorkflows.length > 0 && (
              <nav className="source-related-workflows" aria-label="Related workflow settings">
                <strong>Workflows for supported content</strong>
                <p>
                  These workflows support this source’s content types. Their processing rules are
                  configured separately.
                </p>
                {[...new Set(relatedWorkflows)].map((watcherId) => (
                  <Link
                    key={watcherId}
                    href={`/workspace/workflows?watcher=${encodeURIComponent(watcherId)}`}
                  >
                    {watcherNames[watcherId]}
                  </Link>
                ))}
              </nav>
            )}
          </section>
          <details className="source-collection-status">
            <summary>Collection status and intake evidence</summary>
            <SourceAdapterEvidence
              components={components}
              activity={activity}
              unavailable={activityUnavailable}
            />
            {!components.some((item) => item.kind === "source_adapter") && !activityUnavailable && (
              <p>No source adapter records are available.</p>
            )}
          </details>
          <div
            className={`source-catalog-save config-save-rail${dirty || saving ? " is-active" : ""}`}
          >
            <p role="status">
              Revision {catalog.config.revision} ·{" "}
              {writeRefreshFailed
                ? "Save acknowledged, refresh unconfirmed"
                : dirty
                  ? `${changes} unsaved ${changes === 1 ? "change" : "changes"}`
                  : "Saved catalog"}
            </p>
            {canEdit && (
              <div className="config-save-actions">
                <button
                  className="button secondary"
                  type="button"
                  disabled={!dirty || saving || saveBlocked}
                  onClick={() => {
                    if (window.confirm("Discard your unsaved catalog changes?")) {
                      discardWorkspaceDraft(catalogDraftKey, draftOwner);
                      setDraft(structuredClone(catalog.config.config));
                      setError("");
                      setFieldErrors({});
                      setChoiceEdit(null);
                      setFocusedPublisher("");
                      setSelectedEndpoint("");
                      setSelectedCapability("");
                    }
                  }}
                >
                  Discard changes
                </button>
                <SaveButton
                  type="button"
                  disabled={!dirty || saving || saveBlocked}
                  onClick={() => void save()}
                >
                  {saving ? "Saving…" : "Save catalog"}
                </SaveButton>
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
