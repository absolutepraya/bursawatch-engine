#!/usr/bin/env bash
# Explicit live entrypoint for the reviewed, paused-first Hermes command job.
set -euo pipefail
if [ "$#" -ne 0 ]; then
  echo 'morning job entrypoint accepts no arguments; use scheduled.sh --check for verification' >&2
  exit 2
fi
exec "$HOME/.hermes/scripts/bursawatch-dc-morning-brief-scheduled.sh" --live
