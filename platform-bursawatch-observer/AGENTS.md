# Bursawatch operator observer

This host-bound package reads the Hermes job registry and reports bounded
observations to the Bursawatch Control Plane. It has a distinct machine
credential from the Hermes schedule reconciler and never invokes the Hermes
CLI or changes scheduler state.

`bin/observe.py` is standard-library Python. It requires one registry match
for every declared Hermes runtime name, rejects duplicates and malformed
schedules, and copies only job identity, enabled state, schedule, and
allowlisted last-execution time/status. Do not add raw errors, command fields,
provider data, credentials, paths, or runtime state to reports.

The release manifest classifies this package as manual. A first VPS install,
service/timer activation, environment file, and observer credential require a
separately reviewed and approved host operation. Do not install, enable, start,
or invoke this package against a live registry as part of source development.
