#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
source_file="$repo_root/rsshub-instagram/proxy-dispatcher.cjs"
compose_file="$repo_root/rsshub-instagram/docker-compose.yml"

"$repo_root/scripts/require-published-commit"

local_sha="$(sha256sum "$source_file" | awk '{print $1}')"
local_compose_sha="$(sha256sum "$compose_file" | awk '{print $1}')"
remote_sha="$(ssh vps 'cd "$HOME/rsshub-instagram" && sha256sum proxy-dispatcher.cjs 2>/dev/null | cut -d" " -f1 || true')"
remote_compose_sha="$(ssh vps 'cd "$HOME/rsshub-instagram" && sha256sum docker-compose.yml 2>/dev/null | cut -d" " -f1 || true')"

if [ "$local_sha" = "$remote_sha" ] && [ "$local_compose_sha" = "$remote_compose_sha" ]; then
  printf 'rsshub-instagram runtime files already match: dispatcher=%s compose=%s\n' "$local_sha" "$local_compose_sha"
  exit 0
fi

printf 'deploying rsshub-instagram runtime files: dispatcher=%s/%s compose=%s/%s\n' "$local_sha" "${remote_sha:-missing}" "$local_compose_sha" "${remote_compose_sha:-missing}"
ssh vps 'install -d -m 700 "$HOME/rsshub-instagram"'
rsync -a "$source_file" "$compose_file" vps:rsshub-instagram/
ssh vps 'cd "$HOME/rsshub-instagram" && docker compose up -d --force-recreate rsshub-instagram >/dev/null'

deployed_sha="$(ssh vps 'cd "$HOME/rsshub-instagram" && sha256sum proxy-dispatcher.cjs | cut -d" " -f1')"
deployed_compose_sha="$(ssh vps 'cd "$HOME/rsshub-instagram" && sha256sum docker-compose.yml | cut -d" " -f1')"
[ "$deployed_sha" = "$local_sha" ] || {
  echo 'rsshub-instagram dispatcher checksum mismatch after deploy' >&2
  exit 1
}
[ "$deployed_compose_sha" = "$local_compose_sha" ] || {
  echo 'rsshub-instagram compose checksum mismatch after deploy' >&2
  exit 1
}
printf 'deployed rsshub-instagram runtime files: dispatcher=%s compose=%s\n' "$deployed_sha" "$deployed_compose_sha"
