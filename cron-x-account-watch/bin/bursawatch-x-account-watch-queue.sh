#!/usr/bin/env bash
set -euo pipefail

export X_POST_WATCH_QUEUE_ONLY=1
exec "$HOME/.hermes/scripts/bursawatch-x-account-watch.sh" "$@"
