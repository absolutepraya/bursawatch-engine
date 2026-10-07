# Backend-aligned workflow navigation

Historical planning snapshot. The current authenticated operator surface and
its API contract are documented in [CONTROL_PLANE.md](CONTROL_PLANE.md). The
repository move to `bursawatch-engine` is recorded in [MIGRATION.md](MIGRATION.md).

## Specification

Review the teammate-owned repository at `ca8ff1af5c9aeecce3acfd941ccd281283293f3b`
without modifying its checkout, history, configuration or runtime. At this
stage, the web stayed in `dafandikri/bursawatch-web`, with `web-landing` and
`web-config` as independent package boundaries. New commits used their actual
creation dates.

Keep five primary destinations. Discover finds sources; Following configures
owned sources; Workflows holds the library, saved preferences and run history;
Settings holds delivery and bot preferences; Insights explains recorded results.
Do not turn backend package names into sidebar items.

The workflow library exposes all seven scheduled market packages through plain
language tasks. Search and category filters reduce the list and stay in the URL
so browser Back restores the user's context. Each detail has a stable URL,
source/output explanation and backend-owned timing. X, Instagram and WhatsApp
workflow details link to their platform-filtered Following forms. The three
provider-specific Telegram workflows and the Swing Board remain read-only,
owner-managed descriptions; they do not link to generic source or brokerage
configuration. There are no Library-to-Settings deep links.

There is no new per-workflow draft store or pretend activation button. Existing
forms show local-save toast feedback; reload restores preferences and cancel
preserves saved data. New-source drafts are isolated by platform, while saved
source drafts remain keyed by source identity. Corrupted storage is not silently
overwritten. Unsupported workflow IDs have a recovery path. X preferences include
original posts, replies and threads.

Shared libraries, reusable skills and media services appear in a secondary
disclosure, not as extra workflows. Repository support is not live service
health. Discord is the reviewed output; X, Instagram, WhatsApp Channels and
Telegram are inputs. Other outbound channel choices remain unconnected plans.
No trade execution or speculative performance/return figures are introduced.

## Implementation plan

1. Pin an allowlisted capability catalog to the reviewed snapshot and contract paths.
2. Add the workflow library under Workflows; keep existing daily-price planning
   separate from backend-supported workflows and label its integration boundary.
3. Reuse source preference forms through platform-filtered Following links for
   X, Instagram and WhatsApp only. Keep provider-managed Telegram workflows and
   Swing state read-only. Settings retains the existing bot/delivery forms and
   explicitly distinguishes supported from planned outbound providers.
4. Cover filtering, storage and validation with unit tests; exercise navigation,
   save/reload/cancel, mobile layouts, enlarged text and API boundaries in Chromium.
5. Run both application checks; publish only the existing feature branch/PR.

## Seven scheduled packages

| User task                   | Reviewed package              | What it does and does not do                                                                                                                                                                                                                    |
| --------------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Read company and macro news | `cron-tg-market-news`         | Selected Tuntun and Phintraco Telegram posts become factual Indonesian summaries. Routes issuer, macro and industry news separately. Issuer cards include Yahoo price context and 1D/1W/1M/3M comparisons when available; no investment advice. |
| Follow broker Swing calls   | `cron-tg-phintraco-swing`     | Preserves individual eligible Phintraco calls, entry, targets, stop-loss, source chart and later source status. Deterministic forwarding, not generated recommendations.                                                                        |
| Follow research bundles     | `cron-tg-kelas-investasi-gtw` | Summarizes completed Kelas Investasi GTW bundles with the header image. Supporting setup only; never independently starts price monitoring or becomes a Primary Plan.                                                                           |
| Track source-backed plans   | `cron-dc-swing-board`         | Owns Primary Plan, Supporting setup and Chart context episodes, source history, close reconciliation and resolved/archived status. No trading or inferred plan.                                                                                 |
| Follow X accounts           | `cron-x-account-watch`        | Configured post types, ordered threads, relevant source-grounded summaries and media. Routes macro, IDX news, IDX Swing or US news according to source policy.                                                                                  |
| Follow Instagram accounts   | `cron-ig-account-watch`       | Public posts/reels, caption and carousel/frame OCR with selective vision. Company/macro analysis, not generic trading lessons or actionable setup forwarding.                                                                                   |
| Follow WhatsApp Channels    | `cron-wa-channel-watch`       | Public Channel text, image and video intake through the existing bridge. Company/macro routing; an exact leading `#TechnicalReview` tag selects Swing. Not personal-chat monitoring.                                                            |

For source-of-truth behavior, read each package's `AGENTS.md` and its single
`SKILL.md` or `CRON.md`. Output is Discord in all seven reviewed packages.
Source platforms must not be advertised as implemented outbound adapters.
First observation is generally future-only: following a source does not
authorize historical replay.

The Swing Board's documented reconciliation runs on weekdays at 16:30 WIB,
with a 17:00 retry only for an unavailable initial attempt. It requires an
exact-date Yahoo bar, preserves state when the close is unavailable, and
explicitly archives resolved topics after two calendar dates. This is a source
contract, not observed live health. Compared with the prior `f36823f` review,
the two newer commits affect these Board date/archival rules, not web APIs.

## Supporting components

Keep these in a secondary disclosure, not extra primary navigation:

- `profile-emoji` skill: reviewed static X/Instagram identity snapshots for
  Discord. Creation requires operator approval; it is not avatar synchronization.
- `lib-swing-format`: consistent provider-neutral Swing rendering. The BRI
  normalized adapter is future-only, not connected to the WhatsApp watcher.
- `lib-telegram-resilience`: shared authorization, probe leases and transport
  backoff. It does not own a user destination or login interface.
- `service-rsshub`: backend-owned feed transport; credentials and source-health
  details are not browser settings.

## Acceptance boundary

These controls prepare preferences; they do not update cron JSON or a shared DB.
No HTTP configuration API is published in the reviewed tree. Backend connection
needs an agreed authenticated, tenant-scoped contract. The proposal in
[WEB_API_HANDOFF.md](WEB_API_HANDOFF.md) requires backend-owner agreement before
implementation. Unattended execution and
Sectors-core-data qualification must be proved with actual backend evidence,
not the sample history supplied by this frontend.
