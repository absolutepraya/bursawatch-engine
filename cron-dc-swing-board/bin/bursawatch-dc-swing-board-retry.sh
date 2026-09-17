#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 0 ]] || exit 2
exec "$(dirname "$0")/bursawatch-dc-swing-board.sh" after-close --phase retry
