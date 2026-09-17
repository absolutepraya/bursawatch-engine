#!/usr/bin/env bash
# Deploy a BursaWatch cron or library bin/ tree to the VPS runtime.
#
# Usage:
#   ./deploy.sh cron-<slug>            # rsync a whole cron bin/ tree
#   ./deploy.sh cron-<slug> scan.py    # rsync a single cron bin/ file
#
# After deploy, verify with the cron's dry-run (see README). The dotfiles
# vps/agents/skills/<cron>/ copies are a separate FROM-VPS backup mirror — this
# script never touches them.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")" && pwd)"
"$repo_root/scripts/require-published-commit"

package="${1:?usage: deploy.sh cron-<slug>|lib-<slug> [file]}"
file="${2:-}"
case "$package" in
  cron-*) runtime="bursawatch-${package#cron-}" ;;
  lib-*) runtime="$package" ;;
  *) echo "package must start cron- or lib-: $package" >&2; exit 2 ;;
esac
src="$repo_root/$package/bin"
dst="vps:.agents/skills/$runtime/bin"

[[ "$package" =~ ^[a-z0-9][a-z0-9-]*$ ]] || {
  echo "invalid package name: $package" >&2
  exit 2
}
[ -d "$src" ] || { echo "no such package dev dir: $src" >&2; exit 1; }

if [ -n "$file" ]; then
  [[ "$file" != */* && "$file" != "." && "$file" != ".." ]] || {
    echo "file must name one item directly in bin/: $file" >&2
    exit 2
  }
  [ -f "$src/$file" ] || { echo "no such source file: $src/$file" >&2; exit 1; }
fi

ssh vps "install -d -m 700 -- \"\$HOME/.agents/skills/$runtime/bin\""

if [ -n "$file" ]; then
  rsync -a "$src/$file" "$dst/$file"
  echo "deployed $package/bin/$file → $runtime on VPS"
else
  rsync -a --exclude='__pycache__/' --exclude='*.pyc' "$src/" "$dst/"
  echo "deployed $package/bin/ → $runtime on VPS"
fi
