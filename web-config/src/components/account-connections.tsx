"use client";

import Link from "next/link";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  ArrowRight,
  Camera,
  Check,
  Globe2,
  Hash,
  Mail,
  MessageCircle,
  Send,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type FormEvent } from "react";
import { BrandMark } from "./brand";
import { PageHeading } from "./page-heading";
import { SettingsNavigation } from "./delivery-settings";
import { useToast } from "./toast-provider";
import {
  connectionProviders,
  connectionLabel,
  connectionPlansSnapshot,
  decodeConnectionPlans,
  saveConnectionPlan,
  subscribeConnectionPlans,
  connectionDraftKey,
  encodeConnectionDraft,
  restoreConnectionDraft,
  type ConnectionPlans,
  type ConnectionProvider,
} from "@/lib/connection-plans";

const icons = {
  x: Globe2,
  instagram: Camera,
  whatsapp: MessageCircle,
  telegram: Send,
  discord: Hash,
  slack: Hash,
  email: Mail,
};
type Editor = {
  provider: ConnectionProvider | "workspace";
  state: ConnectionPlans;
  initial: string;
};

function SetupEditor({ editor, onClose }: { editor: Editor; onClose: () => void }) {
  const { provider, state } = editor;
  const baseline =
    provider === "workspace" ? state.workspaceName : (state.connections[provider.id]?.label ?? "");
  const draftKey = connectionDraftKey(provider === "workspace" ? provider : provider.id);
  const [label, setLabel] = useState(editor.initial);
  const [error, setError] = useState("");
  const [fieldError, setFieldError] = useState(false);
  const [draftError, setDraftError] = useState(false);
  const [confirmation, setConfirmation] = useState<"discard" | "remove" | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const keep = useRef<HTMLButtonElement>(null);
  const removeTrigger = useRef<HTMLButtonElement>(null);
  const notify = useToast();
  const dirty = label !== baseline;
  useEffect(() => {
    input.current?.focus();
  }, []);
  useEffect(() => {
    if (confirmation) keep.current?.focus();
  }, [confirmation]);
  function clearDraft() {
    try {
      sessionStorage.removeItem(draftKey);
    } catch {
      /* Saving still works without session storage. */
    }
  }
  function update(value: string) {
    setLabel(value);
    setError("");
    setFieldError(false);
    try {
      const draft = encodeConnectionDraft(baseline, value);
      if (value === baseline || draft === null) sessionStorage.removeItem(draftKey);
      else sessionStorage.setItem(draftKey, draft);
      setDraftError(draft === null);
    } catch {
      setDraftError(true);
    }
  }
  function requestClose() {
    if (dirty) setConfirmation("discard");
    else onClose();
  }
  function save(event: FormEvent) {
    event.preventDefault();
    const parsed = connectionLabel.safeParse(label);
    if (!parsed.success) {
      setError(parsed.error.issues[0].message);
      setFieldError(true);
      input.current?.focus();
      return;
    }
    try {
      saveConnectionPlan(
        state.revision,
        provider === "workspace"
          ? { type: "rename", label: parsed.data }
          : { type: "save", id: provider.id, label: parsed.data },
      );
      clearDraft();
      notify(
        provider === "workspace"
          ? "Workspace name saved on this device."
          : `${provider.name} ${provider.direction} setup saved on this device.`,
      );
      onClose();
    } catch (e) {
      setError((e as Error).message);
      setFieldError(false);
    }
  }
  function remove() {
    if (provider === "workspace") return;
    try {
      saveConnectionPlan(state.revision, { type: "remove", id: provider.id });
      clearDraft();
      notify("Saved setup removed.");
      onClose();
    } catch (e) {
      setError((e as Error).message);
      setFieldError(false);
      setConfirmation(null);
      requestAnimationFrame(() => input.current?.focus());
    }
  }
  return (
    <section
      className="connection-editor"
      aria-labelledby="connection-editor-title"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          if (confirmation) {
            setConfirmation(null);
            requestAnimationFrame(() => input.current?.focus());
          } else requestClose();
        }
      }}
    >
      <div className="connection-editor-heading">
        <h3 id="connection-editor-title">
          {provider === "workspace"
            ? "Name your workspace"
            : `${provider.name} ${provider.direction} setup`}
        </h3>
        <button
          className="icon-button"
          aria-label="Close connection editor"
          type="button"
          onClick={requestClose}
        >
          <X size={19} aria-hidden="true" />
        </button>
      </div>
      {confirmation ? (
        <div
          className="connection-confirmation"
          role="group"
          aria-label={confirmation === "discard" ? "Discard unsaved changes" : "Remove saved setup"}
        >
          <p>
            {confirmation === "discard"
              ? "Discard your unsaved changes?"
              : "Remove this saved setup? Your followed sources and delivery preferences will stay."}
          </p>
          <div className="research-actions">
            <button
              ref={keep}
              type="button"
              className="button secondary"
              onClick={() => {
                const previous = confirmation;
                setConfirmation(null);
                requestAnimationFrame(() =>
                  previous === "remove" ? removeTrigger.current?.focus() : input.current?.focus(),
                );
              }}
            >
              {confirmation === "discard" ? "Keep editing" : "Keep setup"}
            </button>
            <button
              type="button"
              className="button secondary connection-danger"
              onClick={() => {
                if (confirmation === "remove") remove();
                else {
                  clearDraft();
                  onClose();
                }
              }}
            >
              {confirmation === "discard" ? "Discard changes" : "Remove setup"}
            </button>
          </div>
        </div>
      ) : (
        <form onSubmit={save} noValidate>
          <label className="field-label" htmlFor="connection-label">
            {provider === "workspace" ? "Workspace name" : "Connection label"}
          </label>
          <input
            ref={input}
            id="connection-label"
            className="text-input"
            maxLength={60}
            value={label}
            onChange={(event) => update(event.target.value)}
            aria-invalid={fieldError}
            aria-describedby={`connection-label-help${error ? " connection-error" : ""}`}
            autoComplete="off"
            placeholder={
              provider === "workspace"
                ? "My research desk"
                : provider.direction === "input"
                  ? "My research account"
                  : "My market brief"
            }
          />
          <p id="connection-label-help" className="field-help">
            {provider === "workspace"
              ? "A name for this workspace, saved on this device."
              : "A name to recognise this setup. Keep passwords, tokens and webhook URLs out of this field."}
          </p>
          {editor.initial !== baseline ? (
            <p className="field-help" role="status">
              Your unsaved draft was restored.
            </p>
          ) : null}
          {draftError ? (
            <p className="field-help" role="status">
              This edit cannot be recovered automatically. Keep the page open until you save a valid
              name.
            </p>
          ) : null}
          {error ? (
            <p id="connection-error" className="field-error" role="alert">
              {error}
            </p>
          ) : null}
          {provider !== "workspace" ? (
            <p className="connection-note">
              {provider.supported
                ? "Save the label now. Account connection is not available yet."
                : "Delivery to this platform is planned. You can save a label now."}
            </p>
          ) : null}
          <div className="connection-form-actions">
            <button type="submit" className="button primary" disabled={!dirty}>
              <Check size={17} aria-hidden="true" />
              {provider === "workspace" ? "Save name" : "Save setup"}
            </button>
            <button className="button secondary" type="button" onClick={requestClose}>
              Cancel
            </button>
            {provider !== "workspace" && state.connections[provider.id] ? (
              <button
                ref={removeTrigger}
                type="button"
                className="text-link connection-danger"
                onClick={() => setConfirmation("remove")}
              >
                Remove local setup
              </button>
            ) : null}
          </div>
        </form>
      )}
    </section>
  );
}

export function AccountConnections() {
  const raw = useSyncExternalStore(
    subscribeConnectionPlans,
    connectionPlansSnapshot,
    () => "pending",
  );
  const state = useMemo(() => decodeConnectionPlans(raw === "pending" ? null : raw), [raw]);
  const [direction, setDirection] = useState<"input" | "output">("input");
  const [editing, setEditing] = useState<Editor | null>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  const ready = raw !== "pending" && state !== null;
  function edit(provider: ConnectionProvider | "workspace") {
    if (!state) return;
    triggerRef.current = document.activeElement as HTMLElement;
    const baseline =
      provider === "workspace"
        ? state.workspaceName
        : (state.connections[provider.id]?.label ?? "");
    let initial = baseline;
    try {
      initial = restoreConnectionDraft(
        sessionStorage.getItem(
          connectionDraftKey(provider === "workspace" ? provider : provider.id),
        ),
        baseline,
      );
    } catch {
      /* Recovery is optional. */
    }
    setEditing({ provider, state: structuredClone(state), initial });
  }
  function close() {
    setEditing(null);
    requestAnimationFrame(() => triggerRef.current?.focus());
  }
  return (
    <div className="page-wrap preferences-page account-page">
      <PageHeading
        title="Account & connections"
        description="Manage your workspace and the accounts behind your brief."
      />
      <SettingsNavigation active="account" />
      <div className="account-content">
        <section className="account-identity" aria-label="Workspace identity">
          <span className="account-mark">
            <BrandMark />
          </span>
          <div>
            <h2>{state?.workspaceName ?? "Your workspace"}</h2>
            <p>Saved on this device</p>
          </div>
          <button
            className="button secondary"
            type="button"
            disabled={!ready || !!editing}
            onClick={() => edit("workspace")}
          >
            Edit name
          </button>
        </section>
        {editing?.provider === "workspace" ? (
          <SetupEditor editor={editing} onClose={close} />
        ) : null}
        {raw === "pending" ? (
          <p role="status">Loading your setup…</p>
        ) : !state ? (
          <div className="research-notice" role="alert">
            <p>Saved setup could not be read. Your existing data has been kept.</p>
            <button className="button secondary" onClick={() => location.reload()} type="button">
              Reload setup
            </button>
          </div>
        ) : null}
        <section className="account-connections-section" aria-labelledby="connections-title">
          <div className="account-section-heading">
            <div>
              <h2 id="connections-title">Connections</h2>
              <p>Prepare accounts for research and destinations for your brief.</p>
            </div>
            <span className="connection-state">Connection pending</span>
          </div>
          <div className="connection-switch" role="group" aria-label="Connection direction">
            <button
              type="button"
              aria-pressed={direction === "input"}
              disabled={!!editing}
              onClick={() => setDirection("input")}
            >
              <ArrowDownToLine size={17} aria-hidden="true" />
              Input sources
            </button>
            <button
              type="button"
              aria-pressed={direction === "output"}
              disabled={!!editing}
              onClick={() => setDirection("output")}
            >
              <ArrowUpFromLine size={17} aria-hidden="true" />
              Output destinations
            </button>
          </div>
          <p className="connection-direction-help">
            {direction === "input"
              ? "The platforms your followed sources publish on."
              : "The places you want to receive your brief. Each needs its own connection."}
          </p>
          <div className="connection-list">
            {connectionProviders
              .filter((item) => item.direction === direction)
              .map((item) => {
                const Icon = icons[item.provider];
                const saved = state?.connections[item.id];
                const isEditing =
                  editing?.provider !== "workspace" && editing?.provider.id === item.id;
                return (
                  <div className={`connection-item${isEditing ? " is-editing" : ""}`} key={item.id}>
                    <div className="connection-row">
                      <span className="connection-icon">
                        <Icon size={21} aria-hidden="true" />
                      </span>
                      <div className="connection-copy">
                        <h3>{item.name}</h3>
                        <p>{saved?.label ?? item.description}</p>
                      </div>
                      <span className="connection-status">
                        {saved ? "Setup saved" : item.supported ? "Not connected" : "Planned"}
                      </span>
                      <button
                        type="button"
                        className="button secondary"
                        disabled={!ready || !!editing}
                        aria-expanded={isEditing}
                        aria-label={`${saved ? "Edit" : "Prepare"} ${item.name} ${direction}`}
                        onClick={() => edit(item)}
                      >
                        {saved ? "Edit setup" : "Prepare"}
                      </button>
                    </div>
                    {isEditing && editing ? (
                      <SetupEditor key={item.id} editor={editing} onClose={close} />
                    ) : null}
                  </div>
                );
              })}
          </div>
          <div className="connection-footer">
            <p>Setups stay in this browser until account connection is available.</p>
            <Link
              className="text-link"
              href={direction === "input" ? "/app/following" : "/app/settings"}
            >
              {direction === "input" ? "Manage followed sources" : "Delivery preferences"}
              <ArrowRight size={16} aria-hidden="true" />
            </Link>
          </div>
        </section>
        <details className="account-data">
          <summary>Storage & market data</summary>
          <div>
            <h2>On this device</h2>
            <p>
              Sign-in and cross-device sync are not available yet. Saved setups do not grant account
              access or send messages. Reopen an editor in this tab to recover an unfinished label.
            </p>
          </div>
          <div>
            <h2>Sectors market data</h2>
            <p>Not connected. Market figures in this workspace are examples.</p>
          </div>
        </details>
      </div>
    </div>
  );
}
