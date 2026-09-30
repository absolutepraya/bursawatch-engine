"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { RefreshCw, Save } from "lucide-react";
import { useToast } from "@/components/toast-provider";
import { useUnsavedWarning } from "@/components/watcher-config-editor";
import {
  discardWorkspaceDraft,
  getDraftOwner,
  readWorkspaceDraft,
  retainWorkspaceDraft,
  type WorkspaceDraftKey,
} from "@/lib/workspace-drafts";
import {
  configFieldErrors,
  isScheduleApplied,
  validateScheduleMinutes,
} from "@/lib/watcher-fields";
import type { ControlJob } from "@/server/control-plane";
import "@/app/watcher-editor.css";

type ScheduleInput = { enabled: boolean; interval_seconds: number; timezone: "Asia/Jakarta" };
type ScheduleDraft = { enabled: boolean; minutes: string };

export function ScheduleEditor({
  job,
  onSave,
  onRefresh,
  onDirtyChange,
}: {
  job: ControlJob;
  onSave: (input: ScheduleInput) => Promise<ControlJob>;
  onRefresh: () => Promise<ControlJob>;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const id = useId();
  const draftKey: WorkspaceDraftKey = `schedule:${job.job_id}`;
  const [draftOwner] = useState(getDraftOwner);
  const [restored] = useState(() => readWorkspaceDraft<ControlJob, ScheduleDraft>(draftKey));
  const restoredConflict = Boolean(
    restored && restored.base.schedule?.revision !== job.schedule?.revision,
  );
  const [current, setCurrent] = useState(restoredConflict ? restored!.base : job);
  const [receivedJob, setReceivedJob] = useState(job);
  const [enabled, setEnabled] = useState(restored?.draft.enabled ?? job.schedule?.enabled ?? false);
  const [minutes, setMinutes] = useState(
    restored?.draft.minutes ??
      String((job.schedule?.interval_seconds ?? job.min_interval_seconds ?? 300) / 60),
  );
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [pollRevision, setPollRevision] = useState<number | null>(
    !restored && job.schedule && !isScheduleApplied(job) && job.reconciliation.status === "pending"
      ? job.schedule.revision
      : null,
  );
  const [failure, setFailure] = useState(
    restoredConflict
      ? "The schedule changed while you were away. Your draft is preserved; reload to review the latest saved schedule."
      : restored?.failure ||
          (restored?.blocked ? "Reload the saved schedule before trying to save again." : ""),
  );
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [blocked, setBlocked] = useState(restoredConflict || (restored?.blocked ?? false));
  const [restoredNotice, setRestoredNotice] = useState(Boolean(restored));
  const [timedOut, setTimedOut] = useState(false);
  const [awaitingRevision, setAwaitingRevision] = useState<number | null>(null);
  const failureRef = useRef<HTMLDivElement>(null);
  const refreshRef = useRef(onRefresh);
  const toast = useToast();
  const toastRef = useRef(toast);
  const dirty =
    enabled !== (current.schedule?.enabled ?? false) ||
    minutes !==
      String((current.schedule?.interval_seconds ?? current.min_interval_seconds ?? 300) / 60);
  useUnsavedWarning(dirty || saving);
  useEffect(() => {
    retainWorkspaceDraft(
      draftKey,
      {
        base: current,
        draft: { enabled, minutes },
        blocked: blocked || saving,
        failure: saving
          ? "A previous save has not been confirmed here. Reload the saved schedule before trying again."
          : failure,
      },
      dirty,
      draftOwner,
    );
  }, [draftKey, draftOwner, current, enabled, minutes, blocked, saving, failure, dirty]);
  useEffect(() => {
    onDirtyChange?.(dirty || saving);
    return () => onDirtyChange?.(false);
  }, [dirty, saving, onDirtyChange]);

  // A refresh may update the parent's job independently. Keep edits intact and
  // never adopt a newer revision beneath an unsaved draft.
  if (job !== receivedJob) {
    setReceivedJob(job);
    if (!saving && !refreshing && pollRevision === null && !blocked) {
      if (
        job.schedule?.revision !== current.schedule?.revision &&
        (dirty || awaitingRevision !== null)
      ) {
        setBlocked(true);
        setFailure(
          "The schedule changed elsewhere. Your draft is preserved; reload to review the current schedule.",
        );
      } else {
        setCurrent(job);
        if (!dirty) {
          setEnabled(job.schedule?.enabled ?? false);
          setMinutes(
            String((job.schedule?.interval_seconds ?? job.min_interval_seconds ?? 300) / 60),
          );
        }
      }
    }
  }
  useEffect(() => {
    refreshRef.current = onRefresh;
    toastRef.current = toast;
  }, [onRefresh, toast]);

  useEffect(() => {
    if (pollRevision === null) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    let checking = false;
    function scheduleCheck() {
      if (!cancelled && document.visibilityState !== "hidden" && !checking)
        timer = setTimeout(check, 3000);
    }
    function visibilityChanged() {
      if (timer) clearTimeout(timer);
      scheduleCheck();
    }
    async function check() {
      if (cancelled || checking || document.visibilityState === "hidden") return;
      checking = true;
      try {
        const next = await refreshRef.current();
        if (cancelled) return;
        if (next.schedule?.revision !== pollRevision) {
          setFailure(
            "The schedule changed while you were waiting. Reload to review the latest settings.",
          );
          setBlocked(true);
          setPollRevision(null);
          return;
        }
        setCurrent(next);
        if (isScheduleApplied(next, pollRevision)) {
          toastRef.current("Schedule applied.");
          setPollRevision(null);
          setTimedOut(false);
          setAwaitingRevision(null);
          return;
        }
        if (
          next.reconciliation.status === "error" ||
          next.reconciliation.status === "not_connected"
        ) {
          setPollRevision(null);
          return;
        }
      } catch (error) {
        if (cancelled) return;
        setFailure(
          error instanceof Error
            ? error.message
            : "Could not check the schedule. Refresh its status to try again.",
        );
        setPollRevision(null);
        return;
      } finally {
        checking = false;
      }
      attempts += 1;
      if (attempts >= 10) {
        setTimedOut(true);
        setPollRevision(null);
        return;
      }
      scheduleCheck();
    }
    scheduleCheck();
    document.addEventListener("visibilitychange", visibilityChanged);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", visibilityChanged);
    };
  }, [pollRevision]);

  async function refresh(reload = false) {
    if (refreshing || saving || pollRevision !== null) return;
    if (
      reload &&
      dirty &&
      !window.confirm("Discard your draft and load the latest saved schedule?")
    )
      return;
    setRefreshing(true);
    setFailure("");
    try {
      const next = await onRefresh();
      if (
        !reload &&
        (dirty || awaitingRevision !== null) &&
        next.schedule?.revision !== current.schedule?.revision
      ) {
        setBlocked(true);
        setFailure(
          "The schedule changed elsewhere. Your draft is preserved; reload to review the current schedule.",
        );
      } else {
        setCurrent(next);
        if (!dirty || reload) {
          setEnabled(next.schedule?.enabled ?? false);
          setMinutes(
            String((next.schedule?.interval_seconds ?? next.min_interval_seconds ?? 300) / 60),
          );
        }
        if (reload) {
          discardWorkspaceDraft(draftKey, draftOwner);
          setRestoredNotice(false);
          setBlocked(false);
          setAwaitingRevision(null);
          setFieldError(null);
          setTimedOut(false);
        } else if (blocked)
          setFailure(
            "Status refreshed. Reload this editor and review the saved settings before making another change.",
          );
        if (
          isScheduleApplied(
            next,
            reload ? next.schedule?.revision : (awaitingRevision ?? next.schedule?.revision),
          )
        ) {
          if (awaitingRevision !== null) toast("Schedule applied.");
          setTimedOut(false);
          setAwaitingRevision(null);
        } else if (
          (!blocked || reload) &&
          next.schedule &&
          next.reconciliation.status === "pending"
        ) {
          setTimedOut(false);
          setPollRevision(next.schedule.revision);
        }
      }
    } catch (error) {
      setFailure(
        error instanceof Error ? error.message : "Could not check the schedule. Try again shortly.",
      );
      requestAnimationFrame(() => failureRef.current?.focus());
    } finally {
      setRefreshing(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (
      saving ||
      refreshing ||
      blocked ||
      pollRevision !== null ||
      current.reconciliation.status === "pending" ||
      current.schedule_kind !== "interval" ||
      !dirty
    )
      return;
    const invalid = validateScheduleMinutes(
      minutes,
      current.min_interval_seconds,
      current.max_interval_seconds,
    );
    setFieldError(invalid);
    setFailure("");
    if (invalid) {
      document.getElementById(`${id}-minutes`)?.focus();
      return;
    }
    setSaving(true);
    setPollRevision(null);
    setTimedOut(false);
    try {
      const next = await onSave({
        enabled,
        interval_seconds: Number(minutes) * 60,
        timezone: "Asia/Jakarta",
      });
      discardWorkspaceDraft(draftKey, draftOwner);
      setRestoredNotice(false);
      setCurrent(next);
      setEnabled(next.schedule?.enabled ?? enabled);
      setMinutes(String((next.schedule?.interval_seconds ?? Number(minutes) * 60) / 60));
      if (isScheduleApplied(next)) toast("Schedule applied.");
      else {
        toast("Schedule saved. Waiting for it to take effect.");
        setAwaitingRevision(next.schedule?.revision ?? null);
        if (next.reconciliation.status === "pending")
          setPollRevision(next.schedule?.revision ?? null);
      }
    } catch (error) {
      const code = error && typeof error === "object" && "code" in error ? error.code : undefined;
      const fields = configFieldErrors(
        error && typeof error === "object" && "fields" in error ? error.fields : [],
      );
      setFieldError(fields.interval_seconds ?? null);
      setBlocked(code === "unknown-outcome" || code === "conflict");
      setFailure(
        error instanceof Error
          ? error.message
          : "Could not save the schedule. Your changes are still here.",
      );
      requestAnimationFrame(() => {
        if (fields.interval_seconds) document.getElementById(`${id}-minutes`)?.focus();
        else failureRef.current?.focus();
      });
    } finally {
      setSaving(false);
    }
  }

  const effective = isScheduleApplied(current);
  const status =
    current.schedule_kind === "fixed"
      ? "Fixed schedule"
      : effective
        ? "Applied"
        : current.reconciliation.status === "error"
          ? "Could not apply"
          : current.reconciliation.status === "not_connected"
            ? "Awaiting connection"
            : "Pending";
  return (
    <form
      className="watcher-editor watcher-schedule"
      onSubmit={submit}
      noValidate
      aria-busy={saving || refreshing}
    >
      <header className="watcher-editor-header">
        <div>
          <h3>{current.display_name}</h3>
          <p>All times use Jakarta time (WIB).</p>
        </div>
        <span
          className={`watcher-draft-status${!effective && current.schedule_kind !== "fixed" ? " is-dirty" : ""}`}
        >
          {status}
        </span>
      </header>
      {current.schedule_kind === "fixed" ? (
        <p className="watcher-help">
          This job has a fixed schedule managed by its service. It cannot be changed here.
        </p>
      ) : (
        <>
          {restoredNotice ? (
            <p className="watcher-feedback" role="status">
              Your unsaved draft was restored for this tab. It will be cleared when you reload the
              page or sign out.
            </p>
          ) : null}
          <fieldset
            className="watcher-form-body"
            disabled={
              saving ||
              refreshing ||
              blocked ||
              current.reconciliation.status === "pending" ||
              pollRevision !== null
            }
          >
            <label className="watcher-toggle" htmlFor={`${id}-enabled`}>
              <input
                id={`${id}-enabled`}
                name="enabled"
                type="checkbox"
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
              />
              <span>
                Run this job
                <small>Turn off to pause future scheduled runs once the change is applied.</small>
              </span>
            </label>
            <div className="watcher-fields">
              <div className="watcher-field">
                <label htmlFor={`${id}-minutes`}>Check every (minutes)</label>
                <input
                  id={`${id}-minutes`}
                  name="interval_seconds"
                  type="number"
                  inputMode="numeric"
                  step={1}
                  min={Math.ceil((current.min_interval_seconds ?? 60) / 60)}
                  max={Math.floor((current.max_interval_seconds ?? 86400) / 60)}
                  value={minutes}
                  aria-invalid={Boolean(fieldError)}
                  aria-describedby={`${id}-${fieldError ? "error" : "help"}`}
                  onChange={(event) => {
                    setMinutes(event.target.value);
                    setFieldError(null);
                  }}
                  onBlur={() =>
                    setFieldError(
                      validateScheduleMinutes(
                        minutes,
                        current.min_interval_seconds,
                        current.max_interval_seconds,
                      ),
                    )
                  }
                />
                <small id={`${id}-help`}>
                  Allowed range: {Math.ceil((current.min_interval_seconds ?? 60) / 60)}–
                  {Math.floor((current.max_interval_seconds ?? 86400) / 60)} minutes.
                </small>
                {fieldError ? (
                  <small id={`${id}-error`} className="watcher-field-error">
                    {fieldError}
                  </small>
                ) : null}
              </div>
              <div className="watcher-field">
                <span className="watcher-field-label">Time zone</span>
                <p className="watcher-readonly">Asia/Jakarta · UTC+7</p>
              </div>
            </div>
          </fieldset>
          <div
            className={`watcher-feedback${current.reconciliation.status === "error" ? " is-error" : ""}`}
            role="status"
          >
            {effective
              ? `Revision ${current.schedule?.revision} is applied. This job is ${current.schedule?.enabled ? "enabled" : "paused"}.`
              : current.reconciliation.status === "error"
                ? "The saved schedule could not be applied. Refresh its status or contact your administrator."
                : current.reconciliation.status === "not_connected"
                  ? "The saved schedule is waiting for a scheduler connection. It has not taken effect."
                  : timedOut
                    ? "The change is still pending. Automatic checks have stopped; refresh its status to check again."
                    : pollRevision !== null
                      ? "Schedule saved. Checking until the change is confirmed…"
                      : "The saved schedule has not yet been confirmed as applied."}
          </div>
          {failure ? (
            <div className="watcher-feedback is-error" role="alert" tabIndex={-1} ref={failureRef}>
              <p>{failure}</p>
              {blocked ? (
                <p>
                  Your draft is preserved. Reload the schedule to review the latest saved settings
                  before making another change.
                </p>
              ) : null}
              {blocked ? (
                <button
                  className="button secondary"
                  type="button"
                  disabled={saving || refreshing}
                  onClick={() => void refresh(true)}
                >
                  Reload schedule
                </button>
              ) : null}
            </div>
          ) : null}
          <footer className="watcher-editor-actions">
            <p>
              {dirty
                ? "Unsaved schedule changes"
                : current.schedule
                  ? `Saved revision ${current.schedule.revision}`
                  : "No schedule saved"}
            </p>
            <div>
              <button
                className="button secondary"
                type="button"
                disabled={!dirty || saving || refreshing || blocked || pollRevision !== null}
                onClick={() => {
                  if (!window.confirm("Discard your unsaved schedule changes?")) return;
                  discardWorkspaceDraft(draftKey, draftOwner);
                  setEnabled(current.schedule?.enabled ?? false);
                  setMinutes(
                    String(
                      (current.schedule?.interval_seconds ?? current.min_interval_seconds ?? 300) /
                        60,
                    ),
                  );
                  setFailure("");
                  setFieldError(null);
                  setRestoredNotice(false);
                }}
              >
                Discard changes
              </button>
              <button
                className="button secondary"
                type="button"
                disabled={saving || refreshing || pollRevision !== null}
                onClick={() => void refresh()}
              >
                <RefreshCw size={16} aria-hidden="true" />
                {refreshing ? "Checking…" : "Refresh status"}
              </button>
              <button
                className="button primary"
                disabled={
                  saving ||
                  refreshing ||
                  blocked ||
                  pollRevision !== null ||
                  current.reconciliation.status === "pending" ||
                  !dirty
                }
              >
                <Save size={16} aria-hidden="true" />
                {saving ? "Saving…" : "Save schedule"}
              </button>
            </div>
          </footer>
        </>
      )}
    </form>
  );
}
