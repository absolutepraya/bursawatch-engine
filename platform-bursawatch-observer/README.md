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
cannot install or activate it. The systemd unit and timer are templates only.
A first VPS installation, the dedicated environment file and credential, and
timer activation require a separately reviewed and approved host operation.
Do not use a development test to read the live registry or contact the live
Control Plane.

The service expects these private environment values in
`/home/praya/.hermes/bursawatch-operator-observer.env`:

- `BURSAWATCH_OPERATOR_OBSERVER_CONTROL_PLANE_ORIGIN`
- `BURSAWATCH_OPERATOR_OBSERVER_TOKEN`
- Optional `BURSAWATCH_OPERATOR_OBSERVER_JOBS_PATH`

The token must be provisioned through the separately approved host operation.
Never place it in this repository, unit file, command arguments, or logs.
