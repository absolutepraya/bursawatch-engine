/** Private editor drafts live only in this browser tab's JavaScript memory.
 * They never survive a reload, sign-out, or a change of signed-in user.
 */
export type WorkspaceDraftKey = `config:${string}` | `schedule:${string}` | "source-catalog";
export type WorkspaceDraftScope = "workspace" | "sample";

export type WorkspaceDraft<Base, Draft> = {
  base: Base;
  draft: Draft;
  blocked?: boolean;
  failure?: string;
};

let draftOwner: string | null = null;
const drafts = new Map<WorkspaceDraftKey, WorkspaceDraft<unknown, unknown>>();
const sampleDrafts = new Map<WorkspaceDraftKey, WorkspaceDraft<unknown, unknown>>();

function draftStore(scope: WorkspaceDraftScope) {
  return scope === "sample" ? sampleDrafts : drafts;
}

export function getDraftOwner(): string | null {
  return typeof window === "undefined" ? null : draftOwner;
}

export function clearWorkspaceDrafts(): void {
  drafts.clear();
  sampleDrafts.clear();
}

export function hasWorkspaceDrafts(): boolean {
  return Boolean(getDraftOwner()) && drafts.size > 0;
}

export function setDraftOwner(userId: string | null): void {
  if (typeof window === "undefined") return;
  if (draftOwner !== userId) clearWorkspaceDrafts();
  draftOwner = userId;
}

export function discardWorkspaceDraft(
  key: WorkspaceDraftKey,
  owner: string | null = getDraftOwner(),
  scope: WorkspaceDraftScope = "workspace",
): void {
  if (scope === "workspace" && owner !== getDraftOwner()) return;
  draftStore(scope).delete(key);
}

export function readWorkspaceDraft<Base, Draft>(
  key: WorkspaceDraftKey,
  scope: WorkspaceDraftScope = "workspace",
): WorkspaceDraft<Base, Draft> | null {
  if (scope === "workspace" && !getDraftOwner()) return null;
  const entry = draftStore(scope).get(key);
  return entry ? (structuredClone(entry) as WorkspaceDraft<Base, Draft>) : null;
}

/** Call from browser effects; retaining a clean form removes its old draft.
 * Editors pass their original owner so a late effect cannot cross accounts.
 */
export function retainWorkspaceDraft<Base, Draft>(
  key: WorkspaceDraftKey,
  entry: WorkspaceDraft<Base, Draft>,
  dirty: boolean,
  owner: string | null = getDraftOwner(),
  scope: WorkspaceDraftScope = "workspace",
): void {
  if (scope === "workspace" && (!owner || owner !== getDraftOwner())) return;
  const store = draftStore(scope);
  if (dirty) store.set(key, structuredClone(entry));
  else store.delete(key);
}
