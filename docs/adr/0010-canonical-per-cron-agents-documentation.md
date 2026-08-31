# Canonical per-cron AGENTS.md documentation

Status: proposed

## Context

Hermes cron source directories currently use inconsistent combinations of `AGENTS.md`, `CRON.md`, `SKILL.md`, `README.md`, `SPEC.md`, `DEPLOY.md`, profile documents, prompt documents, and ignored `CONTEXT.md` files. This makes it difficult for agents to determine which instructions are current and encourages duplicate or stale rules.

At the same time, Hermes genuinely loads `~/.agents/skills/<name>/SKILL.md` for agent-backed crons. Treating every `SKILL.md` as redundant would break the runtime prompt contract. No-agent crons do not need that file.

The repository also has a root `CONTEXT-MAP.md` that points to ignored context files rather than the tracked project instructions. Hermes development source is intentionally separate from the dotfiles mirror, but stale legacy capture logic still references old Hermes and Marka paths.

## Decision

Use `AGENTS.md` as the single canonical development and domain document for every cron. Keep exactly one additional contract file: `CRON.md` for a deterministic no-agent cron, or `SKILL.md` for a scheduled cron that is explicitly agent-backed and whose Hermes runtime loads that prompt. `CRON.md` is a concise operational contract. `SKILL.md` is a narrow model-facing interface. Neither is a competing handbook.

Maintain these repository-level roles:

- Root `AGENTS.md` owns shared policy and the child-project map.
- Root `README.md` owns the concise human-facing index.
- Cron-root `AGENTS.md` owns current cron knowledge.
- `docs/adr/`, `docs/superpowers/specs/`, and `docs/superpowers/plans/` preserve durable decisions and historical work records.

Consolidate active cron documentation into `AGENTS.md`, remove the root `CONTEXT-MAP.md` after preserving unique relationships and knowledge, and enforce the document shape with tests. Keep reusable non-cron skill packages on their own `SKILL.md` contract.

Keep the Hermes repository independent from dotfiles. Remove stale Hermes and Marka source capture references in a separate dotfiles change, without changing the active scheduler or adding Hermes development source back into the capture map.

## Considered options

- **Use only `SKILL.md` for every cron:** Rejected because it conflates model-facing runtime prompts with development and operational documentation, and it leaves no canonical place for no-agent cron contracts.
- **Use only `AGENTS.md` for every cron:** Rejected because Hermes loads `SKILL.md` for agent-backed jobs and no-agent crons still need a concise scheduler and deployment contract.
- **Keep the current mix of documents:** Rejected because duplicate sources have already produced stale paths, contradictory rules, and avoidable agent confusion.
- **Use `AGENTS.md` plus exactly one contract file, `CRON.md` or `SKILL.md`:** Accepted because it preserves the real Hermes runtime contract, gives deterministic crons an explicit operational contract, and gives development work one canonical domain document.
- **Keep `CONTEXT-MAP.md` as a separate index:** Rejected because the map points to ignored context files and duplicates the project map already maintained in root `AGENTS.md`.
- **Clean dotfiles in the same commit:** Rejected because it crosses repository boundaries and makes review, rollback, and ownership less clear. The cleanup will happen in the same overall session as a separate subtask and commit.

## Consequences

- Agents have one predictable development document and one predictable contract document in every cron directory.
- Agent-backed cron changes require keeping `AGENTS.md` and the runtime `SKILL.md` consistent.
- No-agent cron changes require keeping `AGENTS.md` and `CRON.md` consistent.
- Historical records remain available without competing with current instructions.
- A documentation policy test becomes part of the repository contract.
- The migration requires a careful content audit because ignored context files and legacy documents may contain unique knowledge.
- Dotfiles remains a backup and machine-configuration mirror, not a second Hermes source tree.

## Status and follow-up

This ADR is proposed alongside the design specification. The user approved the design after the contract was clarified to require `CRON.md` for no-agent crons and `SKILL.md` for agent-backed crons. It becomes accepted with the implementation commit. The implementation must preserve the current uncommitted worktree changes unless they are separately reviewed and must verify that no runtime schedule, state, credential, or delivery behavior changed.
