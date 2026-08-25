#!/usr/bin/env bash
# Deploy a Hermes cron skill's bin/ to the VPS runtime (~/.agents/skills/<cron>/bin/).
#
# Usage:
#   ./deploy.sh <cron>            # rsync the whole bin/ for that cron
#   ./deploy.sh <cron> scan.py    # rsync a single file
#
# After deploy, verify with the cron's dry-run (see README). The dotfiles
# vps/agents/skills/<cron>/ copies are a separate FROM-VPS backup mirror — this
# script never touches them.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")" && pwd)"
"$repo_root/scripts/require-published-commit"

cron="${1:?usage: deploy.sh <cron> [file]}"
file="${2:-}"
src="$HOME/Documents/Projects/Hermes/$cron/bin"
dst="vps:.agents/skills/$cron/bin"

[[ "$cron" =~ ^[a-z0-9][a-z0-9-]*$ ]] || {
  echo "invalid cron name: $cron" >&2
  exit 2
}
[ -d "$src" ] || { echo "no such cron dev dir: $src" >&2; exit 1; }

if [ -n "$file" ]; then
  [[ "$file" != */* && "$file" != "." && "$file" != ".." ]] || {
    echo "file must name one item directly in bin/: $file" >&2
    exit 2
  }
  [ -f "$src/$file" ] || { echo "no such source file: $src/$file" >&2; exit 1; }
fi

ssh vps "install -d -m 700 -- \"\$HOME/.agents/skills/$cron/bin\""

if [ -n "$file" ]; then
  rsync -a "$src/$file" "$dst/$file"
  echo "deployed $cron/bin/$file → VPS"
else
  rsync -a --exclude='__pycache__/' --exclude='*.pyc' "$src/" "$dst/"
  echo "deployed $cron/bin/ → VPS"
fi
