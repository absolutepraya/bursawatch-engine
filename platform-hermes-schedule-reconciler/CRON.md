# Hermes schedule reconciler

## Purpose

The reconciler makes an approved Bursawatch desired interval schedule effective
on the VPS. It is a host-bound maintenance runner intended for a future,
separately reviewed systemd timer. The timer must run independently of Hermes
cron, so the reconciler does not depend on, or modify, its own scheduler.

## Controlled data flow

```text
Control-plane desired revision
  -> reconciler-only API credential
  -> read-only Hermes registry lookup by exact runtime job name
  -> hermes cron edit, pause, or resume
  -> registry reload and exact verification
  -> guarded applied or error report for the same desired revision
```

The reconciler sees only interval jobs. It converts an API-approved whole
minute interval to `every <minutes>m`; it never accepts arbitrary cron text.
For the first preserved baseline only, it also recognizes the exact existing
Hermes cron forms `* * * * *`, `*/10 * * * *`, and `0 * * * *` as equivalent
to one, 10, and 60 minute intervals. This prevents the initial reconciliation
from shifting a normal cron's schedule anchor. A later dashboard cadence change
uses `every <minutes>m` through the supported Hermes CLI.
The desired timezone is fixed to the Bursawatch host timezone, `Asia/Jakarta`.
An outcome only becomes effective after the control plane records `applied` for
the same current revision. If an administrator writes a newer revision mid-run,
the old report is rejected and the next timer pass fetches the new desired
state.

## Environment

The future VPS wrapper loads only these values from `~/.hermes/.env`:

```text
BURSAWATCH_SCHEDULE_RECONCILER_CONTROL_PLANE_URL=https://<control-plane-host>
BURSAWATCH_SCHEDULE_RECONCILER_TOKEN=<same-secret-as-CONTROL_PLANE_RECONCILER_TOKEN>
BURSAWATCH_SCHEDULE_RECONCILER_TIMEOUT_SECONDS=15
BURSAWATCH_SCHEDULE_RECONCILER_JOBS_PATH=/home/praya/.hermes/cron/jobs.json
BURSAWATCH_SCHEDULE_RECONCILER_HERMES_CLI=/home/praya/.local/bin/hermes
BURSAWATCH_SCHEDULE_RECONCILER_PYTHON=/usr/bin/python3
BURSAWATCH_SCHEDULE_RECONCILER_LOG_PATH=/home/praya/.logs/bursawatch-schedule-reconciler.log
```

Keep the token only in the backend service environment and VPS environment.
Never put it in the separate web repository, browser bundle, GitHub Actions,
or this repository. The service-side environment name is
`CONTROL_PLANE_RECONCILER_TOKEN`; it is intentionally distinct from the cron
machine credential.

## Planned timer

The reviewed future systemd templates are under `deployment/systemd/`. The
timer runs at most once per minute with a small randomized delay. It must not
be installed until the control-plane API has passed local and public health
checks, and its first invocation must set
`BURSAWATCH_SCHEDULE_RECONCILER_DRY_RUN=1`. The systemd timer removes no state
when disabled or removed; removing its worktree only removes the deployment
source, not a live unit.

## Safe operation

Run the package tests before any deployment review:

```bash
../.venv/bin/python -m pytest -q platform-hermes-schedule-reconciler/tests
```

The first VPS check must use dry-run mode. It reads the API and registry, shows
the planned actions, does not invoke Hermes CLI, and does not report an outcome:

```bash
BURSAWATCH_SCHEDULE_RECONCILER_DRY_RUN=1 \
  bash ~/.hermes/scripts/bursawatch-hermes-schedule-reconciler.sh
```

Do not deploy this package, create or enable a timer, manually run it without
dry-run mode, pause or resume a live job, or change a schedule without explicit
current-chat approval. A natural timer pass after approved deployment is the
only accepted scheduler smoke test.
