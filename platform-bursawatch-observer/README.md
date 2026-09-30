# Bursawatch operator observer

This host-bound package reads `~/.hermes/cron/jobs.json` without modifying it
and reports sanitized job observations to the Control Plane. Its dedicated
observer token is separate from the Hermes schedule reconciler credential.
The process does not invoke the Hermes CLI and has no schedule-write route.

The registry parser requires exactly one matching entry per declared runtime
name. It accepts interval schedules and fixed cron schedules, and emits only
the exact runtime identity, enabled state, bounded schedule, and optional
last-execution timestamp/status. Duplicate, missing, malformed, or oversized
registry content fails closed. Raw commands, errors, paths, credentials, and
provider fields are discarded.

## Local checks

From this directory, run:

```sh
../../../.venv/bin/python -m pytest -q tests/test_observe.py
```

## Host deployment boundary

The release manifest marks this package `manual`; the automatic release timer
cannot install or activate it. The checked-in systemd unit and timer are source
templates for the host-owned service files. A first VPS installation, the
dedicated environment file and credential, and timer activation require a
separately reviewed and approved host operation. Do not use a development test
to read the live registry or contact the live Control Plane.

The service expects these private environment values in
`/home/praya/.hermes/bursawatch-operator-observer.env`:

- `BURSAWATCH_OPERATOR_OBSERVER_CONTROL_PLANE_ORIGIN`
- `BURSAWATCH_OPERATOR_OBSERVER_TOKEN`
- Optional `BURSAWATCH_OPERATOR_OBSERVER_JOBS_PATH`

The token must be provisioned through the separately approved host operation.
Never place it in this repository, unit file, command arguments, or logs.

## Production status

The first VPS installation, private environment, credential, and timer
activation were completed through a manual host operation on 2026-09-30. The
timer is enabled. A natural timer run reported all 13 declared job
observations to the Control Plane, and the Jobs page showed 13 observed jobs
with no unknown or attention state. The 2026-09-30 production snapshot showed
8 active jobs, 5 paused jobs, and all 8 desired interval schedules matching
the Hermes registry. This verifies the observation path, not natural
source-to-delivery coverage. The release manifest continues to classify this
host-bound package as manual.
