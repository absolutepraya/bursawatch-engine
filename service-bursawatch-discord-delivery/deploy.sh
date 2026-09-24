#!/usr/bin/env bash
# Repeat-release helper for an already bootstrapped Discord Delivery Owner.
set -euo pipefail

package_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$package_dir/.." && pwd)"
remote_host="${BURSAWATCH_DISCORD_DELIVERY_REMOTE:-vps}"
runtime_dir="/home/praya/.hermes/bursawatch-discord-delivery"
service_name="bursawatch-discord-delivery.service"
health_url="http://127.0.0.1:9120/healthz"

usage() {
  cat <<'USAGE'
Usage: ./service-bursawatch-discord-delivery/deploy.sh <command> [--apply]

Read-only commands:
  plan                 Show the source-to-VPS sync diff (rsync dry run).
  status               Check the existing unit and loopback health endpoint.
  verify               Run status checks and show any source-to-VPS sync diff.

Mutating commands, each requiring --apply and a clean commit published to origin:
  sync --apply         Synchronize service code and install requirements.
  restart --apply      Restart the already installed service unit.
  release --apply      Sync, restart, and verify the loopback health endpoint.

Every mutating command also requires explicit current-chat deployment approval.
This helper does not install the environment, secrets, virtual environment,
systemd unit, network exposure, or migrate watcher/Board operation state.
USAGE
}

require_apply() {
  if [ "$#" -ne 1 ] || [ "$1" != "--apply" ]; then
    echo "deployment refused: this command requires the explicit --apply flag" >&2
    exit 2
  fi
}

require_published_commit() {
  "$repo_root/scripts/require-published-commit"
}

sync_plan() {
  rsync -ain --checksum --no-perms --no-times --omit-dir-times --delete --itemize-changes \
    --exclude='__pycache__/' --exclude='*.pyc' \
    "$package_dir/bin/" "$remote_host:$runtime_dir/bin/"
  rsync -ain --checksum --no-perms --no-times --omit-dir-times --itemize-changes \
    "$package_dir/requirements.txt" "$remote_host:$runtime_dir/requirements.txt"
}

prepare_remote_layout() {
  ssh "$remote_host" 'sh -s' -- "$runtime_dir" <<'REMOTE'
set -eu
runtime_dir=$1
install -d -m 0750 "$runtime_dir" "$runtime_dir/bin"
REMOTE
}

sync_payload() {
  prepare_remote_layout
  rsync -a --checksum --no-perms --no-times --omit-dir-times --delete \
    --exclude='__pycache__/' --exclude='*.pyc' \
    "$package_dir/bin/" "$remote_host:$runtime_dir/bin/"
  rsync -a --checksum --no-perms --no-times --omit-dir-times \
    "$package_dir/requirements.txt" "$remote_host:$runtime_dir/requirements.txt"

  ssh "$remote_host" 'sh -s' -- "$runtime_dir" <<'REMOTE'
set -eu
runtime_dir=$1
test -x "$runtime_dir/venv/bin/python" || {
  echo "service virtual environment is missing; complete the separately reviewed host bootstrap first" >&2
  exit 1
}
find "$runtime_dir/bin" -type d -exec chmod 0750 {} +
find "$runtime_dir/bin" -type f -exec chmod 0640 {} +
chmod 0640 "$runtime_dir/requirements.txt"
"$runtime_dir/venv/bin/python" -m pip install --disable-pip-version-check --no-input \
  --requirement "$runtime_dir/requirements.txt"
REMOTE
}

restart_service() {
  ssh "$remote_host" "sudo systemctl restart $service_name"
}

show_status() {
  ssh "$remote_host" 'sh -s' -- "$service_name" "$health_url" <<'REMOTE'
set -eu
service_name=$1
health_url=$2
active=$(systemctl is-active "$service_name")
enabled=$(systemctl is-enabled "$service_name" 2>/dev/null || true)
printf 'service: %s (enabled: %s)\n' "$active" "$enabled"
test "$active" = active
printf 'loopback health: '
curl --noproxy '*' --fail --silent --show-error "$health_url"
printf '\n'
REMOTE
}

command_name="${1:-}"
case "$command_name" in
  plan)
    [ "$#" -eq 1 ] || { usage >&2; exit 2; }
    sync_plan
    ;;
  status)
    [ "$#" -eq 1 ] || { usage >&2; exit 2; }
    show_status
    ;;
  verify)
    [ "$#" -eq 1 ] || { usage >&2; exit 2; }
    show_status
    sync_plan
    ;;
  sync)
    require_apply "${@:2}"
    require_published_commit
    sync_plan
    sync_payload
    ;;
  restart)
    require_apply "${@:2}"
    require_published_commit
    restart_service
    show_status
    ;;
  release)
    require_apply "${@:2}"
    require_published_commit
    sync_plan
    sync_payload
    restart_service
    show_status
    ;;
  -h|--help|help|'')
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
