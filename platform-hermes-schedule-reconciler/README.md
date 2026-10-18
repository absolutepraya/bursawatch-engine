# Bursawatch schedule reconciler

This VPS worker reads desired interval schedules from the Control Plane,
matches each to one exact Hermes registry job name, applies a supported change
through the Hermes CLI, reads the registry again, and reports the revision
outcome. The web application cannot call this worker or the Hermes CLI.

Stockbit naming cutover: migration `027_stockbit_scheduler_prefix.sql`, the Hermes
job rename, and this worker mapping were deployed together under an approved
manual rollout on 2026-10-18. The 11:58 WIB read-only production snapshot
confirmed `bursawatch-stockbit-snips` active every 15 minutes and all nine
desired interval schedules matching the registry.
The observer mapping must advance with the same cutover if installed.

The read-only registry check on 2026-10-18 identified job `0c6b17e4c944` as
active every 15 minutes with script `bursawatch-rss-source-ingest.sh`. The
reviewed name-only command is:

```sh
~/.local/bin/hermes cron edit 0c6b17e4c944 --name bursawatch-stockbit-snips
```

Before any VPS write, compare the deployed worker with source and obtain
current-session approval. Coordinate the worker mapping, migration, and CLI
rename between natural reconciler passes, confirming no reconciliation is in
flight. Do not stop the source writer or change its desired schedule for this
metadata-only rename. Apply only migration 027 through the migration ledger,
without applying unrelated pending migrations. Verify the registry retains the
same ID, enabled state, schedule, script, skills, and next-run timestamp; check
the worker checksum and dry-run output, then verify the next natural timer
pass and all nine desired schedule matches. Preserve historical migration 012.
The observer was absent at the inspected path, so this change does not install
or activate an observer.

## Reviewed interval jobs

| Control Plane job ID | Exact Hermes name | Allowed seconds |
| --- | --- | --- |
| `bursawatch-tg-source-ingest` | `bursawatch-tg-source-ingest` | 60 to 3,600 |
| `bursawatch-x-account-watch-source` | `bursawatch-x-account-watch` | 600 to 86,400 |
| `bursawatch-ig-account-watch-source` | `bursawatch-ig-account-watch` | 3,600 to 86,400 |
| `bursawatch-tg-market-news` | `bursawatch-tg-market-news` | 60 to 3,600 |
| `bursawatch-tg-phintraco-swing` | `bursawatch-tg-phintraco-swing` | 60 to 3,600 |
| `bursawatch-tg-kelas-investasi-gtw` | `bursawatch-tg-kelas-investasi-gtw` | 300 to 21,600 |
| `bursawatch-wa-channel-watch` | `bursawatch-wa-channel-watch` | 60 to 21,600 |
| `bursawatch-stockbit-snips` | `bursawatch-stockbit-snips` | 300 to 3,600 |
| `bursawatch-dc-morning-brief` | `bursawatch-dc-morning-brief` | 60 only |

Morning timing comes from its revisioned operator configuration. The minute
tick performs bounded preparation before cutoff, freezes once at cutoff and
waits until the configured delivery target. The source schedule baseline is
paused; the manual migration does not create a Hermes job. Installing the
reviewed wrapper, creating a paused job and enabling its desired revision remain
separate host rollout steps after input readiness checks.

The Instagram source adapter currently has no registered production job. A
desired row alone does not create one. Paused legacy Telegram reader jobs stay
separate from the shared source-ingest job. Fixed Board and worker jobs are
read-only and are not accepted by this reconciler.

The mapping and bounds above are enforced locally in `bin/reconcile.py` even
when the Control Plane response is well formed. A legacy cron expression that
exactly matches a desired one, ten, or sixty minute interval is acknowledged
without editing the job. Any other schedule change uses only the supported
Hermes CLI and must pass registry read-back before it is reported as applied.

## Local verification and deployment boundary

Run `../../../.venv/bin/python -m pytest -q tests/test_reconcile.py` from this
package for synthetic registry and API tests. `BURSAWATCH_SCHEDULE_RECONCILER_DRY_RUN=1`
is required for the first runtime verification after a separately approved
deployment. A source change or passing local test does not authorize a live
schedule change, service installation, or registry edit.
