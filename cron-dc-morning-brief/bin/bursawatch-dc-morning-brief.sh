#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd "$(dirname "$0")" && pwd)
exec "${BURSAWATCH_MORNING_PYTHON:-python3}" "$script_dir/runner.py" "$@"
