#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
source_file="$repo_root/rsshub-instagram/proxy-dispatcher.cjs"

"$repo_root/scripts/require-published-commit"

local_sha="$(sha256sum "$source_file" | awk '{print $1}')"
remote_sha="$(ssh vps 'cd "$HOME/rsshub-instagram" && sha256sum proxy-dispatcher.cjs 2>/dev/null | cut -d" " -f1 || true')"

if [ "$local_sha" = "$remote_sha" ]; then
  printf 'rsshub-instagram dispatcher already matches: %s\n' "$local_sha"
  exit 0
fi

printf 'deploying rsshub-instagram dispatcher: local=%s remote=%s\n' "$local_sha" "${remote_sha:-missing}"
ssh vps 'install -d -m 700 "$HOME/rsshub-instagram"'
rsync -a "$source_file" vps:rsshub-instagram/proxy-dispatcher.cjs
ssh vps 'cd "$HOME/rsshub-instagram" && docker compose up -d --force-recreate rsshub-instagram >/dev/null'

deployed_sha="$(ssh vps 'cd "$HOME/rsshub-instagram" && sha256sum proxy-dispatcher.cjs | cut -d" " -f1')"
[ "$deployed_sha" = "$local_sha" ] || {
  echo 'rsshub-instagram dispatcher checksum mismatch after deploy' >&2
  exit 1
}
printf 'deployed rsshub-instagram dispatcher: %s\n' "$deployed_sha"
