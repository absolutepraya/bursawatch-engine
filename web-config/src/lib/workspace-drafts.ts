/** Private editor drafts live only in this browser tab's JavaScript memory.
 * They never survive a reload, sign-out, or a change of signed-in user.
 */
export type WorkspaceDraftKey = `config:${string}` | `schedule:${string}`;

export type WorkspaceDraft<Base, Draft> = {
  base: Base;
  draft: Draft;
  blocked?: boolean;
  failure?: string;
};

let draftOwner: string | null = null;
const drafts = new Map<WorkspaceDraftKey, WorkspaceDraft<unknown, unknown>>();

export function getDraftOwner(): string | null {
  return typeof window === "undefined" ? null : draftOwner;
}

export function clearWorkspaceDrafts(): void {
  drafts.clear();
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
): void {
  if (owner !== getDraftOwner()) return;
  drafts.delete(key);
}

export function readWorkspaceDraft<Base, Draft>(
  key: WorkspaceDraftKey,
): WorkspaceDraft<Base, Draft> | null {
  if (!getDraftOwner()) return null;
  const entry = drafts.get(key);
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
): void {
  if (!owner || owner !== getDraftOwner()) return;
  if (dirty) drafts.set(key, structuredClone(entry));
  else drafts.delete(key);
}
