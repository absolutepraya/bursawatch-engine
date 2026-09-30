# Documentation guide

Current operating guidance is deliberately kept close to the source it governs:

- Repository-wide rules: [`../AGENTS.md`](../AGENTS.md) and [`../README.md`](../README.md).
- A scheduled package: its `AGENTS.md` and exactly one root contract,
  `CRON.md` or `SKILL.md`.
- A reusable service or skill: its local `AGENTS.md`, `README.md`, or
  `SKILL.md` as applicable.

Before documenting current VPS schedules or release status, run
[`scripts/production_snapshot.py`](../scripts/production_snapshot.py) with
`--production`. The helper is read-only, reports gateway health, filters the
Hermes listing to Bursawatch jobs, compares desired interval schedules with
the live registry, and compares the release-agent SHA with published `main`.
Its scheduler results do not prove runtime checksums or a natural
source-to-delivery event.

The current operator workspace contract and production verification are in
[`web-config/docs/CONTROL_PLANE.md`](../web-config/docs/CONTROL_PLANE.md).
The backend API and confirmed-publication contract are in
[`service-bursawatch-control/README.md`](../service-bursawatch-control/README.md),
and the read-only VPS job reporter and its host status are documented in
[`platform-bursawatch-observer/README.md`](../platform-bursawatch-observer/README.md).
The dated operator-workspace and Published-feed specs and plans below preserve
design rationale and implementation history; their production status notes
point to the current operating contracts.

The Bursawatch Discord Delivery Owner is the only Discord REST path. Its
service contract and deployment gates are in
[`service-bursawatch-discord-delivery/README.md`](../service-bursawatch-discord-delivery/README.md)
and its caller contract is in
[`lib-bursawatch-discord-delivery/README.md`](../lib-bursawatch-discord-delivery/README.md).
The service and its initial host bootstrap remain manual rollout boundaries.
The all-client Discord boundary is recorded in
[`adr/0030-shared-discord-delivery-owner.md`](adr/0030-shared-discord-delivery-owner.md).
The Swing Board inactivity and archive lifecycle is recorded in
[`adr/0031-swing-board-inactivity-and-archive-lifecycle.md`](adr/0031-swing-board-inactivity-and-archive-lifecycle.md).

The Bursawatch Source Media Owner is the only Supabase Storage path for private
source media. Its service contract and shared client live in
[`service-bursawatch-source-media/README.md`](../service-bursawatch-source-media/README.md)
and [`lib-bursawatch-source-media/README.md`](../lib-bursawatch-source-media/README.md).
The service and its initial host bootstrap remain manual rollout boundaries.

The platform source migration inventory documents checked-in endpoint and state
ownership contracts, plus the read-only evidence needed before a production
cutover. It is not a live inventory; exact cursors, queues, receipts, and Hermes
job IDs require a separate approved VPS read:
[`source-pipeline migration inventory`](superpowers/specs/2026-09-25-bursawatch-source-pipeline-migration-inventory.md).

Dated incident reviews preserve time-bounded runtime findings and unresolved
causes. They are investigation records, not operating contracts; check current
package contracts and take a fresh production snapshot before acting. The
2026-09-30 platform ingestion audit is in
[`incident-reviews/2026-09-30-platform-ingestion-audit.md`](incident-reviews/2026-09-30-platform-ingestion-audit.md).

The first proposed reader-state repair is described in the
[`catalog transition recovery design`](superpowers/specs/2026-09-30-bursawatch-catalog-transition-recovery-design.md).
The user approved the design on 2026-09-30; it authorizes planning and the
scoped work described there, subject to the release and live-state checks in
the document. It is not an operating contract.

The implementation sequence is in the
[`catalog transition recovery plan`](superpowers/plans/2026-09-30-bursawatch-catalog-transition-recovery.md).
The user approved the plan on 2026-09-30, and implementation is underway in
the `bug-squashing` worktree. Production observations remain time-bound; use a
fresh production snapshot and state read before any live transition.

For collaboration, `.wt/config.toml` defines managed feature worktrees and the
repository-local `finish-workflow` skill ends with a pull request. It does not
deploy, merge, or remove the review workspace.

`adr/` contains accepted architectural decision records. `plans/`, `specs/`,
and `superpowers/` preserve implementation and design history. They may name
pre-split directories, commands, or runtime identities, so they are evidence
of how a decision was made, not current deployment instructions. Reconcile a
historical record with the active package contract and source before acting.

The split decision and the current Bursawatch to Hermes Personal boundary are
recorded in [`adr/0024-separate-bursawatch-and-hermes-personal.md`](adr/0024-separate-bursawatch-and-hermes-personal.md).
The physical state-cutover decision is recorded in
[`adr/0025-materialize-split-runtime-state.md`](adr/0025-materialize-split-runtime-state.md).
The VPS-local, CI-gated Bursawatch release boundary is recorded in
[`adr/0027-vps-pull-release-agent.md`](adr/0027-vps-pull-release-agent.md).
The BRI WhatsApp Swing presentation, media, Board, and guarded back-edit
contract is recorded in
[`adr/0028-bri-whatsapp-swing-presentation.md`](adr/0028-bri-whatsapp-swing-presentation.md).
The distinction between terminal text-only news delivery and strict technical
review media delivery is recorded in
[`adr/0029-wa-nontechnical-text-fallback.md`](adr/0029-wa-nontechnical-text-fallback.md).
