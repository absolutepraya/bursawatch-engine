---
name: finish-workflow
description: Complete the explicitly approved Hermes development worktree lifecycle by testing, committing, publishing, deploying, verifying, merging to main, pushing main, and removing the local worktree. Use this skill when the user says to go ahead with commit, deploy, merge to main, push, and delete or remove the worktree, or gives equivalent full-lifecycle approval.
---

# Finish a Hermes worktree

Use this skill for an already implemented change when the user has explicitly
approved the full finish sequence. It coordinates release and cleanup; it does
not implement new behavior or decide whether unfinished work is ready.

For this exact full-lifecycle trigger, this project-local skill is authoritative
over the generic `finishing-a-development-branch` workflow. Do not present that
workflow's integration menu or wait for another merge choice. Execute the named
sequence below, stopping only at an explicit safety gate or a real failure.

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
feature worktree contains unrelated modified or untracked files, or if the
current branch is detached, stop and explain the blocker.

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
   `git diff --cached`, and the complete untracked-file snapshot.
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
   user explicitly asks to remove it.

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

If the push is rejected or the remote moved, stop and investigate. Never
force-push without explicit approval.

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

Treat a deployment error, checksum mismatch, unsafe smoke, or failed smoke as
a hard stop. Leave the feature branch and worktree intact so the failure can
be repaired without losing work.

Do not manually trigger a production scheduler merely to prove deployment.
Inspect natural scheduled execution only when the project contract requires it
and the user has approved that operational action.

## 5. Merge and push main

Only after deployment and runtime verification succeed:

1. Refresh `origin` and recheck that the main worktree is clean.
2. Confirm the feature commit and intended base relationship.
3. From the main worktree, merge the pushed feature ref. Prefer a fast-forward
   merge when the feature branch was created from the current base.
4. Run the documented post-merge validation when the project requires it.
5. Push `main` and verify local `HEAD` equals `origin/main`.

Use an explicit merge command such as:

```bash
git fetch origin
git merge --ff-only origin/<feature-branch>
git push origin main
```

If fast-forwarding is impossible, a merge conflicts, post-merge validation
fails, or main becomes dirty, stop without deleting the worktree. Do not
auto-resolve conflicts, force-push, or silently change merge strategy. If a
preservation stash was created, restore it only after the main push succeeds;
the restoration itself is a separate verification gate before cleanup.

## 6. Remove the managed worktree

Cleanup happens only after the integrated commit is pushed and main has either
remained clean or had its exact pre-stash state restored and verified.
Run it from outside the target worktree, preferably from the main worktree:

```bash
wt rm <worktree-name>
```

Do not use `--force` to bypass dirty or unmerged safeguards. If `wt rm`
refuses, inspect and report the remaining files, then stop. Do not remove a
different worktree.

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
