---
status: accepted
---

# Release Bursawatch from a VPS-local pull agent

Bursawatch keeps CI read-only and releases only after CI passes for an exact
`main` commit. A VPS-local systemd timer will poll GitHub for the latest
successful `main` SHA, materialize that SHA in an isolated release worktree,
and apply only its affected release units. This keeps production credentials
and deployment authority on the VPS instead of granting them to GitHub
Actions.

The release agent uses a dedicated read-only GitHub credential, an optional
separate commit-status write credential, an exclusive release lock, checksum
and package-specific no-post verification, and durable structured release
records with a concise Hermes heartbeat. When configured, it publishes the
`bursawatch/release` status for the exact candidate SHA, but status publication
is best effort and never grants GitHub Actions production access. It completes
an in-flight release before considering a newer commit, and it never
auto-rolls back database migrations. Schema migrations are immutable and
eligible for automatic application only when they are forward-compatible and
have passed ephemeral-Postgres CI validation. Active watcher configuration is
not a release artifact: baseline configuration seeds only absent histories,
while every existing live revision changes through the authenticated, audited
control-plane API.

A tracked declarative release manifest maps source paths to release units,
their dependencies, deployment commands, and verification commands. A change
outside that manifest fails closed rather than guessing a deployment target.
Every new migration declares either automatic or manual release eligibility in
a required header. The existing immutable migration files retain their exact
production checksums, so their eligibility lives in a checked legacy registry
rather than modifying their SQL. CI validates all migrations against ephemeral
PostgreSQL; manual, destructive, rewriting, backfill, or schedule-changing
migrations stop automatic deployment and require explicit operations work.

The release agent's systemd units, timer, credential file, and privilege
boundary are bootstrap infrastructure. Ordinary releases cannot modify them.
Changes to that boundary remain explicit reviewed VPS operations. The first
automatic scope is the control plane, shared libraries, and the seven
scheduled Bursawatch watcher packages. Cobalt, RSSHub, profile-emoji, and
other host-bound services stay outside it until they have equivalent bounded
deployment and no-post verification contracts.

The release candidate is the exact SHA currently at `main` with a successful
`CI / validate` workflow. Code review remains advisory and is not a release
gate. A transient fetch or GitHub API failure retries with backoff. A failure
after deployment begins, including migration or verification failure, blocks
that SHA and sends a Hermes alert until an operator explicitly clears the
block or a newer eligible SHA supersedes it. Bootstrap is an explicit one-time
VPS operation. Once installed, the agent immediately evaluates the current
verified `main` commit under these same rules.
