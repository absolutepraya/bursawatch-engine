---
name: finish-workflow
description: Complete the explicitly approved Hermes development worktree lifecycle by testing, committing, publishing, deploying, verifying, reconciling normal Git divergence, merging to main, pushing main, and removing the local worktree. Use this skill when the user says to go ahead with commit, deploy, merge to main, push, and delete or remove the worktree, or gives equivalent full-lifecycle approval. Automatically handle routine, reversible branch and preservation problems, and stop only for critical ambiguity, conflicts, unsafe operations, or failed verification.
---

# Finish a Hermes worktree

Use this skill for an already implemented change when the user has explicitly
approved the full finish sequence. It coordinates release and cleanup; it does
not implement new behavior or decide whether unfinished work is ready.

For this exact full-lifecycle trigger, this project-local skill is authoritative
over the generic `finishing-a-development-branch` workflow. Do not present that
workflow's integration menu or wait for another merge choice. Execute the named
sequence below. Use the decision policy in this document to recover from normal
Git state changes without asking the user again. Stop only at an explicit
critical safety gate or a real failure.

## Approval boundary

Run the full sequence only when the current user turn clearly authorizes all of
these actions: commit, deploy, merge to the intended base branch, push, and
remove the worktree. Phrases such as `ok go ahead commit, deploy, merge to
main, push, and then delete the worktree` qualify.

Do not infer the remaining approvals from `looks good`, `finish this`, `ready`,
or approval of only one step. If approval covers only part of the sequence,
perform only that part and stop at the boundary.

The approval covers the reviewed source and deployment scope. It does not
authorize scheduler changes, destination changes, state resets, replay or
backfill, posted-message changes, market orders, or remote feature-branch
deletion unless the user explicitly includes those actions.

Once this approval exists, it also covers routine reversible recovery inside
the reviewed scope: fetching the configured base and feature refs, choosing the
merge or rebase strategy below, creating named recovery stashes for clearly
unrelated work, restoring those stashes, repeating validation, republishing a
non-rewritten branch, and redeploying the final published commit. Do not ask for
confirmation for those routine operations.

## Automatic decision policy

Treat Git state as a decision problem. Inspect first, select the first matching
case, execute its operation, and re-run the affected verification gates. The
goal is to preserve user work while keeping published history and production
writes auditable.

| When | Automatically do | Stop and ask only when |
| --- | --- | --- |
| The base branch is ahead and the feature branch is clean and published | Fetch the base, merge it into the feature branch with `git merge --no-edit <base>`, validate, and push the feature branch. | The merge conflicts or the base change overlaps an ambiguous user edit. |
| The base branch is ahead and the feature branch is clean and local-only | Rebase onto the base when the feature has no merge commits; otherwise merge the base. Validate, then publish the resulting branch. | Rebase would rewrite a branch with a remote ref, or the operation conflicts. |
| The feature branch is ahead and contains the current base | Continue to deployment, then fast-forward `main` to the published feature ref. | `main` is not an ancestor of the feature ref. |
| The feature and base branches have diverged | Apply the first two rows based on whether the feature has a remote ref, validate the updated feature branch, republish it, then fast-forward `main` to it. | The merge or rebase conflicts, or the resulting scope is no longer the reviewed change. |
| The remote feature ref moved after local work began | Fetch it. Fast-forward local state when possible; otherwise merge the remote feature ref into the published local branch, validate, and push without force. | The remote contains ambiguous work, the merge conflicts, or a protected push rejects the result. |
| Local `main` contains commits not present on `origin/main` | Treat those commits as user-owned and inspect their relationship to the reviewed feature. | The commits are not an exact, known result of this finish run. Do not silently publish unknown local `main` work. |
| `main` has tracked, staged, or untracked changes clearly unrelated to the incoming scope | Capture status, diffs, and exact untracked-file hashes; create a named `--include-untracked` recovery stash; verify clean `main`; restore and compare it after the main push. | Any path overlaps the incoming scope, ownership is unclear, or restoration conflicts or differs. |
| The feature worktree has dirty changes clearly inside the reviewed scope | Inspect the diff, include only the explicit reviewed paths, and validate before committing. | The diff changes behavior outside the approved scope or intent cannot be separated. |
| The feature worktree has dirty changes clearly outside the reviewed scope | Create a named recovery stash, leave it intact, and continue with the reviewed clean state. | The stash cannot be created or the changes cannot be separated safely. |
| A deployment or no-post check fails for an environmental, path, or retryable reason | Apply the documented safe correction, rerun the same check, and record both attempts. | The correction would touch production state, bypass a guard, send a post, or the check still fails. |

Never resolve a conflict by choosing `ours` or `theirs`, editing conflict markers
blindly, resetting, cleaning, force-pushing, force-deleting a worktree, or
changing scheduler, delivery, state, credential, or production configuration.
Those are critical gates. A normal divergence is not a critical gate by itself.
Bound automatic recovery: retry a transient command or remote-race recovery at
most twice after the initial attempt. If the same failure repeats, stop with the
exact command and evidence instead of looping.

## 1. Establish the worktree and scope

Start read-only. Resolve the repository root, current worktree, branch, main
worktree, and managed-worktree identity:

```bash
git rev-parse --show-toplevel
git status --short --branch
git worktree list --porcelain
wt ls
```

Read the repository root `AGENTS.md`, the relevant child `AGENTS.md`, and the
child's `CRON.md` or `SKILL.md`. Read the deployment helper and any documented
verification commands that apply to the changed project.

Record the exact intended changed paths from the conversation and the diff.
Preserve unrelated user work. If the changed scope is ambiguous, if the
feature worktree is detached, or if dirty paths overlap the reviewed scope in
an ambiguous way, stop and explain the blocker. Route clearly unrelated dirty
paths through the automatic decision policy instead of stopping by default.

The base branch must be established from the conversation, repository
instructions, or the worktree's actual branch relationship. Use `main` only
when it is confirmed as the intended base. Do not merge into a guessed branch.

The main worktree must be clean before integration. Never reset, clean,
force-delete, or overwrite unrelated work. If main is dirty, compare its
modified, staged, and untracked paths with the incoming feature paths. An
overlap, ambiguous ownership, or inability to capture an exact snapshot is a
hard stop. When the changes are clearly unrelated and preservation is exact,
use the reversible procedure below:

1. From main, capture `git status --porcelain=v1 -uall`, `git diff`,
   `git diff --cached`, and the complete untracked-file snapshot, including
   hashes for every untracked file.
2. Create a named stash that includes untracked files:
   `git stash push --include-untracked -m "finish-workflow preserve <feature-branch>"`.
3. Verify main is clean and the stash contains the captured changes before
   merging or pushing main. Keep the stash identifier as a recovery point.
4. After main is pushed and before removing the feature worktree, restore with
   `git stash pop --index`. Compare status, staged and unstaged diffs, untracked
   paths, and untracked contents with the pre-stash snapshot.
5. If restoration conflicts or differs, stop immediately, preserve the stash
   and both worktrees, and report the mismatch. Do not force cleanup. A verified
   restoration may leave the named stash as a recoverable backup unless the
   user explicitly asks for its removal.

If new unrelated work appears after the initial snapshot, capture and preserve
that new work with another uniquely named stash before continuing. Never let a
later filesystem change silently invalidate the original preservation proof.

## 2. Validate before committing

Run the project's focused tests first, then its complete documented test suite.
For Hermes, this normally means the affected watcher suite followed by:

```bash
PYTHON=/Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python bash scripts/test-all
```

Use the actual repository instructions when a different project or test
environment applies. A failed test, lint, syntax check, or policy check stops
the workflow before commit, deployment, merge, or cleanup.

Before staging, inspect:

```bash
git diff --check
git diff --stat
git diff --name-status
```

Stage only explicit reviewed paths. Never use `git add -A` or `git add .` in
this workflow. Run `git diff --cached --check` and inspect the staged diff
before creating the commit. Use the user's commit message when supplied. If
none is supplied, choose a concise conventional message that describes the
reviewed change.

## 3. Commit and publish the feature branch

Commit only after the validation gates pass and the staged diff matches the
approved scope. Confirm the worktree is clean after committing.

Publish the exact commit before deploying:

```bash
git push -u origin <feature-branch>
```

Use `git push origin <feature-branch>` when upstream tracking already exists.
Verify that the commit is reachable from the corresponding `origin` ref. A
deployment helper that requires a published commit must be allowed to enforce
that boundary.

If the push is rejected because the remote feature ref moved, fetch that ref
and apply the remote-feature row in the automatic decision policy. Retry only
with a normal fast-forward or merge. Stop for ambiguous remote work, a merge
conflict, protected-branch policy, or any need to force-push. Never force-push
without explicit approval.

## 4. Compare, deploy, and verify the runtime

Deploy only the reviewed runtime files. Before the first VPS write, compare
each local target with its live counterpart and show the exact file scope and
diff in the progress update. Use the repository's supported deployment helper,
not an improvised copy command. For Hermes this is normally:

```bash
./deploy.sh <cron> [reviewed-file]
```

Use a single-file deployment when only one runtime file changed. If a cron's
`SKILL.md` or `CRON.md` changed, follow that cron's documented separate-sync
procedure after comparison. Do not edit the dotfiles VPS mirror, live state,
logs, databases, caches, or credentials as part of deployment.

After deployment, compare SHA-256 checksums for every changed runtime file.
Then run the documented no-post or dry-run control using isolated temporary
state and media paths. A smoke test must not send Discord or Telegram messages,
place orders, reset cursors, replay history, or use production state. If the
project has no safe verification control, stop before merging.

Treat a checksum mismatch, unsafe smoke, or failed smoke after a documented
safe correction as a hard stop. For a path, environment, or retryable error,
apply only the documented non-production correction, rerun the same check, and
leave the feature branch and worktree intact if it still fails.

Do not manually trigger a production scheduler merely to prove deployment.
Inspect natural scheduled execution only when the project contract requires it
and the user has approved that operational action.

## 5. Merge and push main

Only after deployment and runtime verification succeed:

1. Refresh `origin` and recheck that the main worktree is clean.
2. Confirm the feature commit and intended base relationship. If the base moved
   since the last feature validation, return to the automatic decision policy:
   update the feature branch with the current base, rerun validation, publish
   it, and redeploy and re-smoke the final published commit.
3. From the main worktree, merge the pushed feature ref. If `main` is an
   ancestor of the feature ref, use `git merge --ff-only`. If a race caused
   `main` to move after the last fetch, fetch again and update the feature
   branch with the new base before retrying this fast-forward.
4. Run the documented post-merge validation when the project requires it.
5. Push `main` and verify local `HEAD` equals `origin/main`. If the push is
   rejected because remote `main` moved, fetch it, update the published feature
   branch with that base, revalidate and redeploy as needed, then retry the
   fast-forward integration. Do not merge an unreviewed remote change directly
   into `main` when the feature branch can carry the updated base.

Use an explicit merge command such as:

```bash
git fetch origin
git merge --ff-only origin/<feature-branch>
git push origin main
```

If the feature update or integration merge conflicts, post-merge validation
fails, restoration conflicts or differs, or the final scope becomes ambiguous,
stop without deleting the worktree. Do not auto-resolve conflicts,
force-push, or silently change merge strategy. If a preservation stash was
created, restore it only after the main push succeeds; the restoration itself
is a separate verification gate before cleanup.

## 6. Remove the managed worktree

Cleanup happens only after the integrated commit is pushed and main has either
remained clean or had its exact pre-stash state restored and verified.
Run it from outside the target worktree, preferably from the main worktree:

```bash
wt rm <worktree-name>
```

Do not use `--force` to bypass dirty or unmerged safeguards. If `wt rm`
refuses because clearly unrelated recoverable work remains, preserve it with a
named stash and retry. If it refuses because of an unresolved Git operation,
ambiguous user work, or a file that cannot be preserved exactly, inspect and
stop. Do not remove a different worktree.

The default cleanup removes the local feature branch with the worktree. Leave
the remote feature branch on `origin` unless the user separately asks for
remote branch deletion.

## Final report

Report evidence, not just success labels:

```text
Finish workflow
- Scope: <changed paths>
- Tests: <focused and complete results>
- Commit: <hash and message>
- Feature push: <remote ref and hash>
- Deployment: <runtime files and checksum result>
- Runtime verification: <no-post or dry-run result>
- Main: <merge result, push result, local and origin hashes>
- Worktree: <removed path and local branch result>
- Remote feature branch: <left or explicitly deleted>
- Live state: unchanged
```

If the workflow stops, report the completed stages, exact blocker, preserved
worktree and branch, and the next safe action. Never claim deployment,
delivery, merge, or cleanup without direct evidence.
