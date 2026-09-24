# RSS source ingest pilot

This package supplements the repository `AGENTS.md`. It is an unscheduled,
metadata-only Task 5 source adapter. Read `CRON.md` before changing intake.

The only supported feeds are the four system-owned `config.FEEDS` Stockbit
lanes. The adapter requires the existing Stockbit watcher's validated live
configuration revision and exact catalog agreement for enabled lanes. It
cannot accept an arbitrary RSS URL, new lane, or stale watcher config.

The current Stockbit watcher remains the live source reader and owner of its
versioned feed state, article queue, frozen settings, agent wake, rendering,
routes, Delivery Owner handoff, and heartbeat. This pilot has no production
job or `stockbit_snips` pipeline handler. Do not reuse or rewrite live cursors
or article state; a future cutover needs an exact queue and receipt inventory.
Articles with a parsed media URL remain fail-closed in this pilot. The feed
parser exposes provider-controlled HTTP(S) URLs, and this package has no
reviewed host allowlist or bounded, redirect-safe media downloader. Do not
fetch those URLs or submit them as accepted source-event payloads.

Run `../../../.venv/bin/python -m pytest -q tests` in this worktree. Tests
use fake feed pages, temporary state, and no Discord or source network calls.
