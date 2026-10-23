"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  discardWorkspaceDraft,
  getDraftOwner,
  getDraftEpoch,
  readWorkspaceDraft,
  retainWorkspaceDraft,
  type WorkspaceDraftKey,
  type WorkspaceDraftScope,
} from "@/lib/workspace-drafts";

/** Passed through async adapters so parent state and editor state share a visit boundary. */
export type DraftAttempt = { isCurrent: () => boolean };

type Messages = {
  restoredConflict: string;
  changed: string;
  reload: string;
  unconfirmed: string;
};

/** Owns the memory-only recovery policy for a revisioned operator editor.
 * A write belongs to the mounted visit that started it. Leaving that visit
 * preserves an unconfirmed draft, even if the server later accepts the write.
 * Only an explicit fresh read may unlock that draft.
 */
export function useOperatorDraft<Base, Draft>({
  draftKey,
  snapshot,
  toDraft,
  revision,
  messages,
  scope = "workspace",
  suspendReceive = false,
  protectRevision = false,
  refreshBaseWhenDirty = false,
}: {
  draftKey: WorkspaceDraftKey;
  snapshot: Base;
  toDraft: (base: Base) => Draft;
  revision: (base: Base) => unknown;
  messages: Messages;
  scope?: WorkspaceDraftScope;
  suspendReceive?: boolean;
  protectRevision?: boolean;
  refreshBaseWhenDirty?: boolean;
}) {
  const [owner] = useState(getDraftOwner);
  const [epoch] = useState(getDraftEpoch);
  const [restored] = useState(() => readWorkspaceDraft<Base, Draft>(draftKey, scope));
  const conflict = Boolean(restored && revision(restored.base) !== revision(snapshot));
  const [base, setBase] = useState(
    restored && (!refreshBaseWhenDirty || conflict) ? restored.base : snapshot,
  );
  const [draft, setDraft] = useState(() => structuredClone(restored?.draft ?? toDraft(snapshot)));
  const [received, setReceived] = useState(snapshot);
  const [blocked, setBlocked] = useState(conflict || (restored?.blocked ?? false));
  const [failure, setFailure] = useState(
    conflict
      ? messages.restoredConflict
      : restored?.failure || (restored?.blocked ? messages.reload : ""),
  );
  const [restoredNotice, setRestoredNotice] = useState(Boolean(restored));
  const [saving, setSaving] = useState(false);
  const visit = useRef({ active: false, attempt: 0 });
  const dirty = JSON.stringify(toDraft(base)) !== JSON.stringify(draft);

  if (snapshot !== received) {
    setReceived(snapshot);
    if (!saving && !blocked && !suspendReceive) {
      if ((dirty || protectRevision) && revision(snapshot) !== revision(base)) {
        setBlocked(true);
        setFailure(messages.changed);
      } else {
        if (!dirty || refreshBaseWhenDirty) setBase(snapshot);
        if (!dirty) setDraft(structuredClone(toDraft(snapshot)));
      }
    }
  }

  useEffect(() => {
    const current = visit.current;
    current.active = true;
    return () => {
      current.active = false;
      current.attempt += 1;
    };
  }, []);
  useEffect(() => {
    if (epoch !== getDraftEpoch()) return;
    retainWorkspaceDraft(
      draftKey,
      { base, draft, blocked: blocked || saving, failure: saving ? messages.unconfirmed : failure },
      dirty,
      owner,
      scope,
    );
  }, [
    draftKey,
    owner,
    epoch,
    scope,
    base,
    draft,
    blocked,
    saving,
    failure,
    dirty,
    messages.unconfirmed,
  ]);

  const beginRead = useCallback((): DraftAttempt => {
    const current = visit.current;
    const attempt = ++current.attempt;
    return {
      isCurrent: () =>
        current.active &&
        current.attempt === attempt &&
        epoch === getDraftEpoch() &&
        (scope === "sample" || owner === getDraftOwner()),
    };
  }, [epoch, owner, scope]);
  function accept(next: Base) {
    discardWorkspaceDraft(draftKey, owner, scope);
    setBase(next);
    setDraft(structuredClone(toDraft(next)));
    setRestoredNotice(false);
  }
  function reload(next: Base) {
    accept(next);
    setBlocked(false);
    setFailure("");
  }
  function fail(error: unknown, fallback: string) {
    const code = error && typeof error === "object" && "code" in error ? error.code : undefined;
    setBlocked(code === "unknown-outcome" || code === "conflict");
    setFailure(error instanceof Error ? error.message : fallback);
  }
  async function save(
    write: (attempt: DraftAttempt) => Promise<Base>,
    feedback: {
      failureMessage: string;
      onSaved: (next: Base) => void;
      onError?: (error: unknown) => void;
    },
  ) {
    const attempt = beginRead();
    setSaving(true);
    try {
      const next = await write(attempt);
      if (!attempt.isCurrent()) return;
      accept(next);
      feedback.onSaved(next);
    } catch (error) {
      if (!attempt.isCurrent()) return;
      fail(error, feedback.failureMessage);
      feedback.onError?.(error);
    } finally {
      if (attempt.isCurrent()) setSaving(false);
    }
  }
  function discard() {
    discardWorkspaceDraft(draftKey, owner, scope);
    setDraft(structuredClone(toDraft(base)));
    setRestoredNotice(false);
    setFailure("");
  }
  return {
    base,
    setBase,
    draft,
    setDraft,
    dirty,
    blocked,
    setBlocked,
    failure,
    setFailure,
    restored: Boolean(restored),
    restoredNotice,
    saving,
    beginRead,
    save,
    reload,
    discard,
  };
}
