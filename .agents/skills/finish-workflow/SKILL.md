---
name: finish-workflow
description: Complete an explicitly approved Hermes development worktree handoff by validating, committing, publishing the feature branch, and opening a pull request for collaboration. It leaves production untouched and retains the worktree for review follow-up. Use when the user says to commit, push, and create or open a PR, or gives equivalent approval.
---

# Finish a Hermes worktree with a pull request

Use this skill for an already implemented, reviewed change when the user has
explicitly approved the pull-request handoff. It coordinates the feature-branch
finish, not production deployment, main-branch integration, or cleanup.

For this PR handoff, this repository-local skill is authoritative over generic
branch-finishing workflows. Do not present an integration menu or merge the
feature directly into `main`.

## Approval boundary

Run the complete PR handoff only when the current user turn clearly authorizes
all of these actions: commit, push the feature branch, and create or update its
pull request. Phrases such as `finish this and open a PR`, `commit, push, and
create the PR`, or `go ahead with the PR` qualify when the intended reviewed
scope is clear.

Do not infer approval from `looks good`, `finish this`, `ready`, or approval of
only one step. If approval covers only part of the sequence, perform only that
part and stop at the boundary.

A pull request has no deployment authority. This workflow must not deploy,
change a scheduler, modify a destination, reset state, replay or backfill,
post a test message, place an order, merge to the base branch, push `main`, or
remove a worktree. Those actions need their own explicit approval after the
review decision.

The approval covers routine reversible branch recovery inside the reviewed
scope: fetching refs, merging the current base into the feature branch,
rebasing an unpublished feature branch, retrying a transient push at most twice,
and updating an existing PR's title or body to match the reviewed diff. It does
not authorize force-pushes, conflict resolution by guesswork, or remote branch
deletion.

## Automatic decision policy

Inspect first, choose the first matching case, and re-run the affected checks.
Keep `main` unchanged throughout the handoff.

| When | Automatically do | Stop and ask only when |
| --- | --- | --- |
| The base branch advanced and the published feature branch is clean | Fetch the base, merge it into the feature branch with `git merge --no-edit <base>`, validate, and push the feature branch. | The merge conflicts or the resulting scope is no longer reviewed. |
| The base branch advanced and the feature branch is local-only | Rebase onto the base when the feature has no merge commits. Otherwise merge the base. Validate and publish the result. | The operation conflicts. |
| The feature and base branches diverged | Apply the matching row above, validate the updated feature branch, and publish it without force. | A conflict, ambiguous remote work, or scope change occurs. |
| The remote feature ref moved | Fetch it. Fast-forward when possible, otherwise merge the remote feature ref into the local branch, validate, and push normally. | The merge conflicts, remote work is ambiguous, or a normal push is rejected. |
| Reviewed changes remain uncommitted in the feature worktree | Inspect the diff, stage only the explicit reviewed paths, validate, and commit. | The diff contains behavior outside the approved scope or cannot be separated safely. |
| Clearly unrelated changes exist in the feature worktree | Preserve them in a named recovery stash and complete the reviewed clean scope. Leave the stash and worktree for follow-up. | The changes overlap the reviewed scope or cannot be preserved exactly. |
| A PR already exists for the feature branch | Inspect its base, head, state, title, body, and checks. Update it only to reflect the reviewed scope. | The PR targets the wrong base, is owned by a different head branch, or its state is ambiguous. |
| PR creation or update fails | Preserve the published branch and worktree, then report the exact failure. | Always. Do not create a duplicate PR by guesswork. |

Never resolve conflicts with `ours` or `theirs`, edit conflict markers blindly,
reset, clean, force-push, force-delete a worktree, or delete a remote branch.
Stop on a repeated transient failure, a conflict, an ambiguous diff, or an
unsafe operation and report the evidence.

## 1. Establish the worktree and reviewed scope

Start read-only. Resolve the repository root, current worktree, feature branch,
managed-worktree identity, intended base, and pull-request state:

```bash
git rev-parse --show-toplevel
git status --short --branch
git worktree list --porcelain
wt ls --format agent
git fetch origin
gh pr list --head <feature-branch> --state all
```

Read the repository root `AGENTS.md`, the affected child `AGENTS.md`, and its
`CRON.md` or `SKILL.md`. Read the relevant test and deployment documentation,
but do not deploy as part of this workflow.

The workflow requires a named feature branch in a feature worktree. If invoked
from `main`, a detached HEAD, or an untracked unmanaged checkout, stop and ask
for a managed feature worktree. Confirm the base from repository instructions,
the branch relationship, or the existing PR. Never guess a base branch.

Record the exact intended paths from the conversation and diff. Preserve
unrelated work. `main` may have unrelated changes because this workflow does
not modify it. Do not stash, reset, clean, or otherwise alter `main`.

## 2. Validate and commit the reviewed change

Run focused tests first, then the repository's complete documented test suite.
For Bursawatch, this normally includes:

```bash
PYTHON=/Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python bash scripts/test-all
```

Use the actual repository instructions when a different project or test
environment applies. A failed test, lint, syntax check, or policy check stops
the workflow before commit or PR creation.

Before staging, inspect:

```bash
git diff --check
git diff --stat
git diff --name-status
```

Stage only explicit reviewed paths. Never use `git add -A` or `git add .` in
this workflow. Run `git diff --cached --check` and inspect the staged diff
before committing. Use the user's commit message when provided. Otherwise use
a concise conventional message describing the reviewed change.

Confirm the feature worktree is clean after committing. If no commit is needed,
record the existing reviewed commit instead.

## 3. Publish the feature branch

Publish the exact reviewed commit:

```bash
git push -u origin <feature-branch>
```

Use `git push origin <feature-branch>` only when upstream tracking already
exists. Verify the commit is reachable from the matching `origin` ref. If a
normal push is rejected because the remote branch moved, apply the automatic
decision policy. Never force-push.

## 4. Create or update the pull request

Refresh the base and ensure the published feature branch contains it when
required by the automatic decision policy. Then inspect for an existing PR:

```bash
gh pr list --head <feature-branch> --state all
```

For a new PR, create a non-draft PR against the confirmed base. Use a concise
title based on the reviewed change and a factual body with:

```text
## Summary
- <reviewed change>

## Validation
- <focused and complete test results>

## Deployment
- Not deployed. Production changes require explicit post-review approval.
```

If an open PR already exists for the exact head and base, update its title or
body only when it no longer describes the reviewed changes. Never silently
retarget, merge, close, approve, request reviewers, or delete a PR. Report its
URL, number, base, head, and current review/check state.

## 5. Retain the review workspace

Leave the feature worktree and both local and remote feature branches intact.
They are the collaboration workspace for review comments and follow-up commits.
Do not merge to `main`, deploy, or call `wt rm` as part of this skill.

After the PR is reviewed and merged, a separately approved workflow may verify
the merged commit, perform a deliberate deployment if needed, and remove the
now-complete worktree.

## Final report

Report evidence, not just a success label:

```text
PR handoff
- Scope: <changed paths>
- Tests: <focused and complete results>
- Commit: <hash and message>
- Feature push: <remote ref and hash>
- Pull request: <URL, number, base, head, state>
- Deployment: not performed
- Main: unchanged
- Worktree: retained at <path>
- Live state: unchanged
```

If the workflow stops, report completed stages, the exact blocker, preserved
feature branch and worktree, and the next safe action. Never claim a PR,
deployment, merge, delivery, or cleanup without direct evidence.
