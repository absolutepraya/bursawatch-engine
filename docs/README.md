# Documentation guide

Current operating guidance is deliberately kept close to the source it governs:

- Repository-wide rules: [`../AGENTS.md`](../AGENTS.md) and [`../README.md`](../README.md).
- A scheduled package: its `AGENTS.md` and exactly one root contract,
  `CRON.md` or `SKILL.md`.
- A reusable service or skill: its local `AGENTS.md`, `README.md`, or
  `SKILL.md` as applicable.

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
