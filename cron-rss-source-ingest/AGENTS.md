# RSS source ingest pilot

This package supplements the repository `AGENTS.md`. It is an unscheduled,
agent-backed Task 5 source adapter. Read `SKILL.md` before changing intake.

The only supported feeds are the four system-owned `config.FEEDS` Stockbit
lanes. The adapter requires the existing Stockbit watcher's validated live
configuration revision and exact catalog agreement for enabled lanes. It
cannot accept an arbitrary RSS URL, new lane, or stale watcher config.

The current Stockbit watcher remains the live source reader and owner of its
versioned feed state, article queue, frozen settings, agent wake, rendering,
routes, Delivery Owner handoff, and heartbeat. The RSS runner claims only
`stockbit_snips` work and submits text-only articles through the existing
Stockbit article owner. The owner binds the validated live configuration
snapshot included when the source event was accepted. A retry with the same
effect is idempotent; a legacy article collision or mismatched revision fails
closed. The runner claims at most one Stockbit agent item per run and emits the
existing bounded payload. This pilot has no production job. Do not reuse or
rewrite live cursors or article state; a future cutover needs an exact queue
and receipt inventory. A later intake revision mismatch does not prevent
already accepted work from settling against its frozen snapshot. Never run the
new reader beside the live source job.
Articles with a parsed media URL remain fail-closed in this pilot. The feed
parser exposes provider-controlled HTTP(S) URLs, and this package has no
reviewed host allowlist or bounded, redirect-safe media downloader. Do not
fetch those URLs or submit them as accepted source-event payloads.

Run `../../../.venv/bin/python -m pytest -q tests` in this worktree. Tests
use fake feed pages, temporary state, and no Discord or source network calls.
