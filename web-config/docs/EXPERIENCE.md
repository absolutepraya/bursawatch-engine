# Product experience: sources to brief

## Scope

The landing explains the product through a finite, controllable sources →
rules → Discord brief illustration. The workspace lets users prepare their own
workflows and clearly separates input access from output delivery. The backend
repository is untouched. These are local preferences, not active schedules or
verified connections.

## User paths

- Landing: the walkthrough plays once when visible; users can inspect a stage,
  pause or replay it, then enter
  the workspace through the server-validated application URL. Reduced motion
  keeps all stages available without animation.
- Workflows opens Your workflows: create, edit, duplicate or remove a workflow.
  Choose input platforms, research topics, event/daily/interval timing, timezone,
  summary style, language and destinations. Source attribution stays required.
  Unsaved drafts recover in the same browser tab; saved workflows use versioned
  browser storage. Revisions prevent stale editors from overwriting later saves.
- Settings → Account: prepare separately named input and output setups, or
  rename the local workspace. Connecting providers will require a future API
  and explicit account authorization. No credentials are collected here.
  An editor opens directly beneath its provider. Incomplete display names
  recover when that editor is reopened in the same tab; a newer saved version
  takes precedence over an older draft. Keep/discard confirmations manage focus.

## Acceptance and integration

Native controls, visible labels, keyboard focus, local-save toasts, inline
validation and confirmation before removal are required. Forms must fit 375px,
landscape and desktop viewports with 200% text. Corrupt storage must remain
intact; failed and stale saves must report an actionable error.

Only Discord is a reviewed backend delivery adapter. Other output preferences
are planned and must not acquire a connected badge simply because a label is
saved. Custom trigger combinations are frontend proposals, not a claim that
the current backend supports user-defined schedules. The backend owner must
agree on authenticated, tenant-scoped APIs, provider capabilities and schedule
validation before these records can be applied. No browser accesses a shared
database, and no web action starts a cron or sends a message.

The UI/UX Pro Max review prioritizes legibility and predictable controls over
decoration. Apple-inspired grouping and restrained motion preserve the existing
Signal Fold identity and Hanken Grotesk typography; they do not introduce a
second visual system.
