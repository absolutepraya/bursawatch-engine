"use client";

import { useEffect, useId, useRef, useState } from "react";
import { controlBrowser, WorkspaceError } from "@/lib/control-browser";
import type { ControlProfile } from "@/server/control-plane";
import { WorkspaceLoading } from "@/components/workspace-loading";
import { useToast } from "@/components/toast-provider";
import { useUnsavedWarning } from "@/components/watcher-config-editor";
import "@/app/source-profiles.css";

type Requester = ReturnType<typeof controlBrowser>;

export function SourceProfiles({
  watcherId,
  request,
  canEdit,
  sampleMode = false,
  onDirtyChange,
}: {
  watcherId: string;
  request: Requester;
  canEdit: boolean;
  sampleMode?: boolean;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [profiles, setProfiles] = useState<ControlProfile[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState<Set<string>>(new Set());
  const controller = useRef<AbortController | null>(null);
  const id = useId();
  useUnsavedWarning(dirty);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);
  async function load() {
    if (busy) return;
    if (dirty && !window.confirm("Discard unsaved photo changes and reload profiles?")) return;
    controller.current?.abort();
    const read = new AbortController();
    controller.current = read;
    setLoading(true);
    setError("");
    setSelected(null);
    setDirty(false);
    try {
      const result = await request<ControlProfile[]>(
        `watchers/${encodeURIComponent(watcherId)}/profiles`,
        undefined,
        { signal: read.signal },
      );
      if (!read.signal.aborted) {
        setProfiles(result);
        setUncertain(new Set());
      }
    } catch (failure) {
      if (read.signal.aborted) return;
      setProfiles(null);
      setError(
        failure instanceof WorkspaceError
          ? failure.message
          : "Could not load source profiles. Try again.",
      );
    } finally {
      if (!read.signal.aborted) setLoading(false);
    }
  }
  const visible = profiles?.filter((p) =>
    `${p.display_name} ${p.handle} ${p.profile_id}`.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <section className="source-profiles" aria-labelledby={`${id}-heading`}>
      <div className="source-profiles-heading">
        <div>
          <h2 id={`${id}-heading`}>{sampleMode ? "Sample source profiles" : "Source profiles"}</h2>
          <p>
            {sampleMode
              ? "Synthetic identity rows only. Photo state and source connections are not checked."
              : "Saved identities and photos from the connected engine."}
          </p>
        </div>
        <button
          className="button secondary"
          type="button"
          disabled={loading || busy}
          onClick={() => void load()}
        >
          {profiles
            ? sampleMode
              ? "Reload sample profiles"
              : "Reload profiles"
            : sampleMode
              ? "Load sample profiles"
              : "Load profiles"}
        </button>
      </div>
      {loading ? <WorkspaceLoading title="Loading source profiles…" compact /> : null}
      {error ? (
        <p role="alert" className="workspace-error">
          {error}
        </p>
      ) : null}
      {!loading && profiles ? (
        <>
          <label htmlFor={`${id}-search`}>Find a source</label>
          <input
            id={`${id}-search`}
            type="search"
            value={query}
            disabled={dirty}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Name, handle or source ID"
          />
          {profiles.length === 0 ? (
            <p>No source profiles were returned for this workflow.</p>
          ) : visible?.length === 0 ? (
            <p>No profiles match your search.</p>
          ) : null}
          <ul className="source-profiles-list">
            {visible?.map((profile) => (
              <li key={profile.profile_id}>
                <div className="source-profile-row">
                  <ProfilePhoto
                    key={profile.avatar.url}
                    url={profile.avatar.url}
                    name={profile.display_name || profile.profile_id}
                  />
                  <div className="source-profile-name">
                    <h3>{profile.display_name || profile.profile_id}</h3>
                    <p>
                      {profile.handle || profile.profile_id} ·{" "}
                      {sampleMode
                        ? profile.enabled
                          ? "Enabled in sample"
                          : "Paused in sample"
                        : profile.enabled
                          ? "Enabled"
                          : "Paused"}
                    </p>
                    {!sampleMode ? <small>Source ID: {profile.profile_id}</small> : null}
                    <p className="source-photo-status">
                      {sampleMode
                        ? "Example photo state, no refresh recorded"
                        : `Photo: ${profile.avatar.mode === "auto" ? "automatic" : "custom"} · ${profile.avatar.last_success_at ? `Last successful refresh ${new Date(profile.avatar.last_success_at).toLocaleString("en-GB", { timeZone: "Asia/Jakarta" })} WIB` : "No successful refresh recorded"}`}
                    </p>
                  </div>
                  {canEdit ? (
                    <button
                      type="button"
                      className="button secondary"
                      aria-expanded={selected === profile.profile_id}
                      disabled={
                        busy ||
                        (selected !== profile.profile_id && uncertain.has(profile.profile_id))
                      }
                      onClick={() => {
                        if (dirty && !window.confirm("Discard unsaved photo changes?")) return;
                        setDirty(false);
                        setSelected(selected === profile.profile_id ? null : profile.profile_id);
                      }}
                    >
                      {selected === profile.profile_id ? "Close photo settings" : "Edit photo"}
                    </button>
                  ) : null}
                </div>
                {profile.avatar.has_error ? (
                  <p className="control-muted">
                    The last photo refresh failed. Any previously saved image is retained.
                  </p>
                ) : null}
                {uncertain.has(profile.profile_id) && selected !== profile.profile_id ? (
                  <p className="control-muted">
                    Reload profiles before editing this photo again; the last change has not been
                    confirmed.
                  </p>
                ) : null}
                {selected === profile.profile_id && canEdit ? (
                  <AvatarEditor
                    key={profile.profile_id}
                    profile={profile}
                    request={request}
                    initiallyBlocked={uncertain.has(profile.profile_id)}
                    onBusyChange={setBusy}
                    onUncertainChange={(value) =>
                      setUncertain((current) => {
                        const next = new Set(current);
                        if (value) next.add(profile.profile_id);
                        else next.delete(profile.profile_id);
                        return next;
                      })
                    }
                    onDirtyChange={setDirty}
                    onUpdate={(value) =>
                      setProfiles(
                        (current) =>
                          current?.map((p) => (p.profile_id === value.profile_id ? value : p)) ??
                          null,
                      )
                    }
                    onAccessFailure={() => {
                      setProfiles(null);
                      setSelected(null);
                      setError("Profile access changed. Reload profiles to check your access.");
                    }}
                  />
                ) : null}
              </li>
            ))}
          </ul>
          {!canEdit ? (
            <p className="control-muted">Workspace administrators can change source photos.</p>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function ProfilePhoto({ url, name }: { url: string | null; name: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <span className="source-profile-photo" aria-hidden="true">
      {url && !failed ? (
        // Provider metadata is validated by the server; do not proxy arbitrary remote images through Next.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={url}
          alt=""
          width={44}
          height={44}
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      ) : (
        name.slice(0, 2).toUpperCase()
      )}
    </span>
  );
}

function AvatarEditor({
  profile,
  request,
  initiallyBlocked,
  onBusyChange,
  onUncertainChange,
  onUpdate,
  onAccessFailure,
  onDirtyChange,
}: {
  profile: ControlProfile;
  request: Requester;
  initiallyBlocked: boolean;
  onBusyChange: (value: boolean) => void;
  onUncertainChange: (value: boolean) => void;
  onUpdate: (profile: ControlProfile) => void;
  onAccessFailure: () => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [mode, setMode] = useState(profile.avatar.mode);
  const [url, setUrl] = useState(profile.avatar.url ?? "");
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState(initiallyBlocked);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const id = useId();
  const controller = useRef<AbortController | null>(null);
  const toast = useToast();
  const dirty =
    mode !== profile.avatar.mode || (mode === "manual" && url !== (profile.avatar.url ?? ""));
  useEffect(
    () => () => {
      controller.current?.abort();
      onBusyChange(false);
    },
    [onBusyChange],
  );
  useEffect(() => {
    onDirtyChange(dirty || busy);
    return () => onDirtyChange(false);
  }, [dirty, busy, onDirtyChange]);
  async function write(refresh: boolean) {
    if (busy || blocked) return;
    if (!refresh && mode === "manual") {
      try {
        const parsed = new URL(url);
        if (
          parsed.protocol !== "https:" ||
          parsed.username ||
          parsed.password ||
          parsed.hash ||
          parsed.port
        )
          throw new Error();
      } catch {
        setError(
          "Enter a public HTTPS image URL without credentials, a fragment or a custom port.",
        );
        return;
      }
    }
    const operation = new AbortController();
    controller.current = operation;
    setBusy(true);
    onBusyChange(true);
    onUncertainChange(true);
    setError("");
    setNotice("");
    const path = `watchers/${encodeURIComponent(profile.watcher_id)}/profiles/${encodeURIComponent(profile.profile_id)}/avatar`;
    try {
      const result = await request<ControlProfile>(
        refresh ? `${path}/refresh` : path,
        refresh ? {} : mode === "manual" ? { mode, url } : { mode: "auto", url: null },
        { signal: operation.signal, ...(refresh ? { method: "POST" as const } : {}) },
      );
      if (operation.signal.aborted) return;
      onUpdate(result);
      onUncertainChange(false);
      setMode(result.avatar.mode);
      setUrl(result.avatar.url ?? "");
      const message = refresh
        ? "Photo refresh requested. Reload profiles to check the result."
        : "Photo settings saved.";
      setNotice(message);
      toast(message);
    } catch (failure) {
      if (operation.signal.aborted) return;
      if (failure instanceof WorkspaceError && ["auth", "forbidden"].includes(failure.code)) {
        onAccessFailure();
        return;
      }
      setError(
        failure instanceof WorkspaceError
          ? failure.message
          : "The change could not be confirmed. Reload profiles before trying again.",
      );
      const uncertainOutcome =
        !(failure instanceof WorkspaceError) ||
        !["validation", "rate-limit"].includes(failure.code);
      setBlocked(uncertainOutcome);
      onUncertainChange(uncertainOutcome);
    } finally {
      if (!operation.signal.aborted) {
        setBusy(false);
        onBusyChange(false);
      }
    }
  }
  return (
    <form
      className="source-avatar-editor"
      onSubmit={(e) => {
        e.preventDefault();
        void write(false);
      }}
    >
      <fieldset disabled={busy || blocked}>
        <legend>Source photo</legend>
        <label htmlFor={`${id}-mode`}>Photo source</label>
        <select
          id={`${id}-mode`}
          value={mode}
          onChange={(e) => setMode(e.target.value as "auto" | "manual")}
        >
          <option value="auto">Automatic from source</option>
          <option value="manual">Custom image URL</option>
        </select>
        {mode === "manual" ? (
          <>
            <label htmlFor={`${id}-url`}>Image URL</label>
            <input
              id={`${id}-url`}
              type="url"
              value={url}
              required
              onChange={(e) => setUrl(e.target.value)}
            />
            <p>
              Use an image you have permission to display. URLs are saved separately from workflow
              configuration.
            </p>
          </>
        ) : (
          <p>
            The engine discovers this source’s photo. Saving or requesting refresh does not
            guarantee an image is available.
          </p>
        )}
        <div className="source-avatar-actions">
          <button className="button primary" type="submit" disabled={!dirty}>
            {busy ? "Saving…" : "Save photo settings"}
          </button>
          <button
            type="button"
            className="button secondary"
            disabled={dirty || profile.avatar.mode !== "auto"}
            onClick={() => void write(true)}
          >
            Refresh source photo
          </button>
        </div>
      </fieldset>
      {error ? (
        <p role="alert" className="workspace-error">
          {error}
        </p>
      ) : null}
      {blocked ? (
        <p>Reload profiles before another change; the previous outcome may be uncertain.</p>
      ) : null}
      {notice ? <p role="status">{notice}</p> : null}
    </form>
  );
}
