#!/usr/bin/env bash
# Explicit VPS bootstrap for the static Bursawatch release-agent boundary.
set -euo pipefail

if [[ "${1:-}" != "--apply" || "$#" -ne 1 ]]; then
  echo "refused: run bootstrap only with the explicit --apply flag" >&2
  exit 2
fi

package_dir="$(cd "$(dirname "$0")/.." && pwd)"
agent_dir="$HOME/.local/lib/bursawatch-release"
state_root="$HOME/.local/share/bursawatch-release"
environment_file="$HOME/.hermes/bursawatch-release-agent.env"

[[ -r "$environment_file" ]] || {
  echo "refused: create $environment_file with mode 0600 first" >&2
  exit 1
}
[[ "$(stat -c '%a' "$environment_file")" == "600" ]] || {
  echo "refused: $environment_file must have mode 0600" >&2
  exit 1
}
grep -q '^BURSAWATCH_RELEASE_GITHUB_TOKEN=.' "$environment_file" || {
  echo "refused: release environment does not define the GitHub token" >&2
  exit 1
}
command -v git >/dev/null
command -v rsync >/dev/null
command -v sudo >/dev/null

install -d -m 0700 "$agent_dir" "$state_root"
install -m 0700 "$package_dir/bin/bursawatch-release-agent.sh" "$agent_dir/bursawatch-release-agent.sh"
install -m 0600 "$package_dir/bin/release_agent.py" "$agent_dir/release_agent.py"

sudo install -m 0644 "$package_dir/deployment/systemd/bursawatch-release-agent.service" \
  /etc/systemd/system/bursawatch-release-agent.service
sudo install -m 0644 "$package_dir/deployment/systemd/bursawatch-release-agent.timer" \
  /etc/systemd/system/bursawatch-release-agent.timer
sudo install -m 0440 "$package_dir/deployment/sudoers.d/bursawatch-release-agent" \
  /etc/sudoers.d/bursawatch-release-agent
sudo visudo -cf /etc/sudoers.d/bursawatch-release-agent
sudo systemctl daemon-reload
sudo systemctl enable --now bursawatch-release-agent.timer
sudo systemctl start bursawatch-release-agent.service
