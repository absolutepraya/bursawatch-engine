# Bursawatch schedule reconciler

This VPS worker reads desired interval schedules from the Control Plane,
matches each to one exact Hermes registry job name, applies a supported change
through the Hermes CLI, reads the registry again, and reports the revision
outcome. The web application cannot call this worker or the Hermes CLI.

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
| `bursawatch-stockbit-snips` | `cron-stockbit-snips` | 300 to 3,600 |

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
