"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { RefreshCw, Save } from "lucide-react";
import { useToast } from "@/components/toast-provider";
import { useUnsavedWarning } from "@/components/watcher-config-editor";
import { useOperatorDraft, type DraftAttempt } from "@/hooks/use-operator-draft";
import {
  configFieldErrors,
  isScheduleApplied,
  validateScheduleMinutes,
} from "@/lib/watcher-fields";
import type { ControlJob } from "@/server/control-plane";
import "@/app/watcher-editor.css";

type ScheduleInput = { enabled: boolean; interval_seconds: number; timezone: "Asia/Jakarta" };
type ScheduleDraft = { enabled: boolean; minutes: string };

function scheduleDraft(job: ControlJob): ScheduleDraft {
  return {
    enabled: job.schedule?.enabled ?? false,
    minutes: String((job.schedule?.interval_seconds ?? job.min_interval_seconds ?? 300) / 60),
  };
}

export function ScheduleEditor({
  job,
  onSave,
  onRefresh,
  onDirtyChange,
}: {
  job: ControlJob;
  onSave: (input: ScheduleInput, attempt: DraftAttempt) => Promise<ControlJob>;
  onRefresh: (attempt: DraftAttempt) => Promise<ControlJob>;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const id = useId();
  const [refreshing, setRefreshing] = useState(false);
  const [pollRevision, setPollRevision] = useState<number | null>(null);
  const [awaitingRevision, setAwaitingRevision] = useState<number | null>(null);
  const recovery = useOperatorDraft<ControlJob, ScheduleDraft>({
    draftKey: `schedule:${job.job_id}`,
    snapshot: job,
    toDraft: scheduleDraft,
    revision: (value) => value.schedule?.revision,
    suspendReceive: refreshing || pollRevision !== null,
    protectRevision: awaitingRevision !== null,
    refreshBaseWhenDirty: true,
    messages: {
      restoredConflict:
        "The schedule changed while you were away. Your draft is preserved; reload to review the latest saved schedule.",
      changed:
        "The schedule changed elsewhere. Your draft is preserved; reload to review the current schedule.",
      reload: "Reload the saved schedule before trying to save again.",
      unconfirmed:
        "A previous save has not been confirmed here. Reload the saved schedule before trying again.",
    },
  });
  const {
    base: current,
    setBase: setCurrent,
    draft,
    setDraft,
    dirty,
    blocked,
    setBlocked,
    failure,
    setFailure,
    saving,
    restoredNotice,
  } = recovery;
  const beginRead = recovery.beginRead;
  const { enabled, minutes } = draft;
  const setEnabled = (value: boolean) => setDraft((previous) => ({ ...previous, enabled: value }));
  const setMinutes = (value: string) => setDraft((previous) => ({ ...previous, minutes: value }));
  const [initialPollStarted, setInitialPollStarted] = useState(false);
  if (!initialPollStarted) {
    setInitialPollStarted(true);
    if (
      !recovery.restored &&
      job.schedule &&
      !isScheduleApplied(job) &&
      job.reconciliation.status === "pending"
    )
      setPollRevision(job.schedule.revision);
  }
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState(false);
  const failureRef = useRef<HTMLDivElement>(null);
  const refreshRef = useRef(onRefresh);
  const toast = useToast();
  const toastRef = useRef(toast);
  useUnsavedWarning(dirty || saving);
  useEffect(() => {
    onDirtyChange?.(dirty || saving);
    return () => onDirtyChange?.(false);
  }, [dirty, saving, onDirtyChange]);

  useEffect(() => {
    refreshRef.current = onRefresh;
    toastRef.current = toast;
  }, [onRefresh, toast]);

  useEffect(() => {
    if (pollRevision === null) return;
    const attempt = beginRead();
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
        const next = await refreshRef.current({
          isCurrent: () => !cancelled && attempt.isCurrent(),
        });
        if (cancelled || !attempt.isCurrent()) return;
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
        if (cancelled || !attempt.isCurrent()) return;
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
  }, [pollRevision, beginRead, setCurrent, setBlocked, setFailure]);

  async function refresh(reload = false) {
    if (refreshing || saving || pollRevision !== null) return;
    if (
      reload &&
      dirty &&
      !window.confirm("Discard your draft and load the latest saved schedule?")
    )
      return;
    const attempt = recovery.beginRead();
    setRefreshing(true);
    setFailure("");
    try {
      const next = await onRefresh(attempt);
      if (!attempt.isCurrent()) return;
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
          recovery.reload(next);
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
      if (!attempt.isCurrent()) return;
      setFailure(
        error instanceof Error ? error.message : "Could not check the schedule. Try again shortly.",
      );
      requestAnimationFrame(() => failureRef.current?.focus());
    } finally {
      if (attempt.isCurrent()) setRefreshing(false);
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
    setPollRevision(null);
    setTimedOut(false);
    await recovery.save(
      (attempt) =>
        onSave(
          { enabled, interval_seconds: Number(minutes) * 60, timezone: "Asia/Jakarta" },
          attempt,
        ),
      {
        failureMessage: "Could not save the schedule. Your changes are still here.",
        onSaved: (next) => {
          if (isScheduleApplied(next)) toast("Schedule applied.");
          else {
            toast("Schedule saved. Waiting for it to take effect.");
            setAwaitingRevision(next.schedule?.revision ?? null);
            if (next.reconciliation.status === "pending")
              setPollRevision(next.schedule?.revision ?? null);
          }
        },
        onError: (error) => {
          const fields = configFieldErrors(
            error && typeof error === "object" && "fields" in error ? error.fields : [],
          );
          setFieldError(fields.interval_seconds ?? null);
          requestAnimationFrame(() => {
            if (fields.interval_seconds) document.getElementById(`${id}-minutes`)?.focus();
            else failureRef.current?.focus();
          });
        },
      },
    );
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
                  recovery.discard();
                  setFieldError(null);
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
