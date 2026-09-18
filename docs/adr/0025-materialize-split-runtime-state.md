---
status: accepted
---

# Materialize split runtime state under current identities

The first Bursawatch and Hermes Personal cutover deliberately retained established VPS state locations through legacy aliases and symlinks. The second cutover materializes each cron-owned state host under its current `bursawatch-*` or `personal-*` runtime identity, so source, runtime, and ownership are unambiguous without redesigning state schemas.

## Decision

`runtime identity` means the deployed `bursawatch-*` or `personal-*` package name. A `state host` is the mutable database, JSON, outbox, media, lock, virtual environment, or dependency directory used by that runtime. A `state family` is the complete set of writers and readers that must be quiesced for one atomic move.

Where code derives package-local state from its current runtime directory, replace the legacy `state` symlink with physical state at that current path through an atomic same-filesystem move. Keep intentionally centralized state under `~/.hermes/state/`, including Bursawatch Market News, Kelas Investasi GTW, Swing Board, WhatsApp Channel Watch, and the Bursawatch-owned shared Telegram resilience control plane. Do not duplicate the shared control plane, rename centralized paths merely for cosmetic consistency, or import RSSHub runtime configuration, credentials, cookies, proxy settings, volumes, or data into Git.

Every cutover uses a chosen published Git commit, source-to-VPS checksum proof, writer quiescence, state-specific integrity evidence, atomic move, rollback archive, isolated no-post verification, and natural-run delivery proof. The relevant legacy runtime directory remains a protected VPS-only rollback archive at `~/backup/hermes/runtime-cutovers/<YYYY-MM-DD>/<runtime-identity>/` for 30 days and stays excluded from Git and dotfiles. Its later deletion requires separate approval.

## Consequences

The active scheduler, independent watchdogs, direct producers, and gateway bridge writers are all part of a state family even when they are outside the Hermes registry. Phintraco, GTW, X, and Swing Board therefore coordinate as one producer family when their shared Board write path is affected. The WhatsApp bridge patch is re-baselined against its current live preimage before any behavior change, but the already-central WhatsApp queue does not move. Runtime contracts and active documentation are synchronized with the deployed release; historical records remain historical.
