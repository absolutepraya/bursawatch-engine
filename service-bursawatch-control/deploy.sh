#!/usr/bin/env bash
# Repeat-release helper for the already-bootstrapped BursaWatch control-plane API.
set -euo pipefail

package_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$package_dir/.." && pwd)"
remote_host="${BURSAWATCH_CONTROL_PLANE_REMOTE:-vps}"
runtime_dir="/home/praya/.hermes/bursawatch-control-plane"
runtime_env="/home/praya/.hermes/bursawatch-control-plane.env"
service_name="bursawatch-control-plane.service"
public_url="https://api.bursawatch.abhipraya.dev"

usage() {
  cat <<'USAGE'
Usage: ./service-bursawatch-control/deploy.sh <command> [--apply]

Read-only commands:
  plan                 Show the service payload that would be synchronized.
  status               Check the VPS service and loopback health endpoint.
  verify               Check status and the public HTTPS health endpoint.

Mutating commands, each requiring --apply:
  sync --apply         Synchronize service code and dependencies only.
  migrate --apply      Apply migrations and seed missing baseline revisions.
  restart --apply      Restart the API and wait for loopback health.
  release --apply      Run sync, migrate, restart, and public verification.

This helper never copies a local .env file or changes the dedicated VPS
environment, systemd unit, Nginx, DNS, TLS, Hermes cron registry, or scheduler
reconciler. Those remain separately reviewed deployment work.
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
  local source_dir
  for source_dir in baseline-configs bin migrations validator-sources; do
    rsync -ain --no-perms --omit-dir-times --delete --itemize-changes \
      --exclude='__pycache__/' --exclude='*.pyc' \
      "$package_dir/$source_dir/" "$remote_host:$runtime_dir/$source_dir/"
  done

  rsync -ain --no-perms --omit-dir-times --itemize-changes \
    "$package_dir/requirements.txt" "$remote_host:$runtime_dir/requirements.txt"
}

prepare_remote_layout() {
  ssh "$remote_host" 'sh -s' -- "$runtime_dir" <<'REMOTE'
set -eu
runtime_dir=$1
install -d -m 0750 "$runtime_dir"
for source_dir in baseline-configs bin migrations validator-sources; do
  install -d -m 0750 "$runtime_dir/$source_dir"
done
REMOTE
}

sync_payload() {
  prepare_remote_layout

  local source_dir
  for source_dir in baseline-configs bin migrations validator-sources; do
    rsync -a --no-perms --omit-dir-times --delete \
      --exclude='__pycache__/' --exclude='*.pyc' \
      "$package_dir/$source_dir/" "$remote_host:$runtime_dir/$source_dir/"
  done

  rsync -a --no-perms --omit-dir-times "$package_dir/requirements.txt" "$remote_host:$runtime_dir/requirements.txt"

  ssh "$remote_host" 'sh -s' -- "$runtime_dir" <<'REMOTE'
set -eu
runtime_dir=$1
for source_dir in baseline-configs bin migrations validator-sources; do
  find "$runtime_dir/$source_dir" -type d -exec chmod 0750 {} +
  find "$runtime_dir/$source_dir" -type f -exec chmod 0640 {} +
done
chmod 0640 "$runtime_dir/requirements.txt"
test -x "$runtime_dir/venv/bin/python"
"$runtime_dir/venv/bin/python" -m pip install --disable-pip-version-check --no-input \
  --requirement "$runtime_dir/requirements.txt"
REMOTE
}

apply_migrations() {
  ssh "$remote_host" 'sh -s' -- "$runtime_dir" "$runtime_env" <<'REMOTE'
set -eu
runtime_dir=$1
runtime_env=$2
test -r "$runtime_env"
test -x "$runtime_dir/venv/bin/python"
cd "$runtime_dir"
set -a
. "$runtime_env"
set +a
./venv/bin/python bin/migrate.py
./venv/bin/python bin/seed_baseline_configs.py
REMOTE
}

restart_service() {
  ssh "$remote_host" "sudo systemctl restart $service_name"

  ssh "$remote_host" 'sh -s' -- "$service_name" <<'REMOTE'
set -eu
service_name=$1
for attempt in $(seq 1 15); do
  if systemctl --quiet is-active "$service_name" \
    && curl --noproxy '*' --fail --silent --show-error http://127.0.0.1:9120/healthz; then
    exit 0
  fi
  sleep 1
done
echo "deployment failed: service did not become healthy within 15 seconds" >&2
exit 1
REMOTE
}

show_status() {
  ssh "$remote_host" 'sh -s' -- "$service_name" <<'REMOTE'
set -eu
service_name=$1
active=$(systemctl is-active "$service_name" 2>/dev/null || true)
enabled=$(systemctl is-enabled "$service_name" 2>/dev/null || true)
printf 'service: %s (enabled: %s)\n' "$active" "$enabled"
test "$active" = active
test "$enabled" = enabled
printf 'loopback health: '
curl --noproxy '*' --fail --silent --show-error http://127.0.0.1:9120/healthz
printf '\n'
REMOTE
}

verify_public_health() {
  ssh "$remote_host" 'sh -s' -- "$public_url" <<'REMOTE'
set -eu
public_url=$1
printf 'public health: '
curl --noproxy '*' --fail --silent --show-error "$public_url/healthz"
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
    verify_public_health
    ;;
  sync)
    require_apply "${@:2}"
    require_published_commit
    sync_plan
    sync_payload
    ;;
  migrate)
    require_apply "${@:2}"
    require_published_commit
    apply_migrations
    ;;
  restart)
    require_apply "${@:2}"
    require_published_commit
    restart_service
    ;;
  release)
    require_apply "${@:2}"
    require_published_commit
    sync_plan
    sync_payload
    apply_migrations
    restart_service
    verify_public_health
    ;;
  -h|--help|help|'')
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
