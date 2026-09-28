# ADR 0031: Swing Board inactivity and archive lifecycle

Status: Accepted, 2026-09-28.

The Board owner runs `reconcile-lifecycle` daily at 17:10 WIB. It counts
reviewed IDX trading sessions after the last material source date and resolves
each open episode at 20 sessions of inactivity. A newer distinct Phintraco
BUY supersedes its active Primary episode and opens a new thread. Stale and
superseded closures use the existing `Resolved` tag, clear the market tag,
and add a factual resolution, last close price, check time, and state to the
managed card. A BUY older than the latest material in an open source-only
episode is a labeled historical reply and cannot promote it. A
source-only card explicitly says no Phintraco close was recorded. Stop-loss
and final-target resolutions retain their terminal market tag.

Each new thread title uses the opening source event's timestamp in WIB, for
example `CPIN - Wed, 23 Sep 2026`. Promotion keeps that title. The existing
title repair command derives the same canonical name from the episode's stored
opening timestamp. This updates the older ticker-only title rule in ADR 0020.

The episode row stores `resolution_reason`, `quiet_started_at`, and
`archived_at`. A backward-compatible schema migration adds these nullable
fields without rewriting existing source or outbox records. The Board starts
the 48-hour quiet period only after all episode messages and resolution
changes have completed or been tombstoned. A late source event published
before resolution is delivered as dated history in the resolved thread and
restarts the timer after delivery. An archived thread receives no later
source event. Every archive is a durable `patch_thread` intent; only its
accepted receipt records completion. A queued archive is canceled if its
quiet-period identity changes before delivery.

The daily schedule can archive up to 24 hours after the 48-hour threshold.
It never archives early. The lifecycle job sends a durable `#hermes` heartbeat
on no-op, normal, degraded, and fatal runs. Deployment and Hermes job
registration remain separate reviewed operations.
