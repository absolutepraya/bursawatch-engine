#!/usr/bin/env bash
# Explicit VPS bootstrap for the static Bursawatch release-agent boundary.
set -euo pipefail

if [[ "${1:-}" != "--apply" || "$#" -gt 2 ]]; then
  echo "refused: run bootstrap with --apply, optionally followed by --retry-blocked" >&2
  exit 2
fi
retry_blocked=false
if [[ "$#" -eq 2 ]]; then
  [[ "$2" == "--retry-blocked" ]] || {
    echo "refused: unknown bootstrap option: $2" >&2
    exit 2
  }
  retry_blocked=true
fi

[[ "$(id -un)" == "praya" && "$HOME" == "/home/praya" ]] || {
  echo "refused: run this bootstrap as praya from /home/praya" >&2
  exit 1
}

package_dir="$(cd "$(dirname "$0")/.." && pwd)"
agent_dir="$HOME/.local/lib/bursawatch-release"
state_root="$HOME/.local/share/bursawatch-release"
environment_file="$HOME/.hermes/bursawatch-release-agent.env"
delivery_client_bin="$HOME/.agents/skills/lib-bursawatch-discord-delivery/bin"
delivery_client_token_file="$HOME/.hermes/secrets/bursawatch-discord-delivery-client-token"

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
[[ -r "$delivery_client_bin/bursawatch_discord_delivery/client.py" ]] || {
  echo "refused: the shared Discord Delivery client is not installed" >&2
  exit 1
}
[[ -r "$delivery_client_token_file" ]] || {
  echo "refused: create $delivery_client_token_file with mode 0600 first" >&2
  exit 1
}
[[ "$(stat -c '%a' "$delivery_client_token_file")" == "600" ]] || {
  echo "refused: $delivery_client_token_file must have mode 0600" >&2
  exit 1
}
command -v git >/dev/null
command -v rsync >/dev/null
command -v sudo >/dev/null
release_user="$(id -un)"
release_group="$(id -gn "$release_user")"
id -nG "$release_user" | tr ' ' '\n' | grep -Fxq sudo || {
  echo "refused: $release_user must retain passworded sudo-group access" >&2
  exit 1
}

# One root transaction performs the boundary change and service start. This
# avoids needing broad passwordless sudo for follow-up bootstrap commands.
sudo bash -s -- "$HOME" "$agent_dir" "$state_root" "$package_dir" "$release_user" "$release_group" "$retry_blocked" <<'ROOT'
set -euo pipefail

release_home="$1"
agent_dir="$2"
state_root="$3"
package_dir="$4"
release_user="$5"
release_group="$6"
retry_blocked="$7"
broad_sudoers_file=/etc/sudoers.d/praya
expected_broad_rule='praya ALL=(ALL) NOPASSWD:ALL'

if [[ -e "$broad_sudoers_file" ]]; then
  [[ -f "$broad_sudoers_file" && ! -L "$broad_sudoers_file" ]] || {
    echo "refused: $broad_sudoers_file is not a regular file" >&2
    exit 1
  }
  [[ "$(cat "$broad_sudoers_file")" == "$expected_broad_rule" ]] || {
    echo "refused: $broad_sudoers_file differs from the reviewed blanket rule" >&2
    exit 1
  }
fi
id -nG "$release_user" | tr ' ' '\n' | grep -Fxq sudo || {
  echo "refused: $release_user no longer has passworded sudo-group access" >&2
  exit 1
}
for target in \
  /etc/systemd/system/bursawatch-release-agent.service \
  /etc/systemd/system/bursawatch-release-agent.timer \
  /etc/sudoers.d/bursawatch-release-agent; do
  [[ ! -L "$target" ]] || {
    echo "refused: $target is a symlink" >&2
    exit 1
  }
done

backup_root="$release_home/backup/hermes/runtime-releases/bursawatch-release-agent"
install -d -o root -g root -m 0700 "$backup_root"
backup_dir="$(mktemp -d "$backup_root/$(date +%Y%m%d-%H%M%S).XXXXXX")"
chown root:root "$backup_dir"
chmod 0700 "$backup_dir"
backup_if_present() {
  local source_path="$1"
  local backup_name="$2"
  if [[ -f "$source_path" ]]; then
    install -o root -g root -m 0600 "$source_path" "$backup_dir/$backup_name"
  fi
}

systemctl stop bursawatch-release-agent.timer || true
systemctl stop bursawatch-release-agent.service || true
backup_if_present /etc/systemd/system/bursawatch-release-agent.service release-agent.service
backup_if_present /etc/systemd/system/bursawatch-release-agent.timer release-agent.timer
backup_if_present /etc/sudoers.d/bursawatch-release-agent release-agent.sudoers
backup_if_present "$broad_sudoers_file" praya.sudoers

install -d -o "$release_user" -g "$release_group" -m 0700 "$agent_dir" "$state_root"
install -o "$release_user" -g "$release_group" -m 0700 \
  "$package_dir/bin/bursawatch-release-agent.sh" "$agent_dir/bursawatch-release-agent.sh"
install -o "$release_user" -g "$release_group" -m 0600 \
  "$package_dir/bin/release_agent.py" "$agent_dir/release_agent.py"

install -o root -g root -m 0644 \
  "$package_dir/deployment/systemd/bursawatch-release-agent.service" \
  /etc/systemd/system/bursawatch-release-agent.service
install -o root -g root -m 0644 \
  "$package_dir/deployment/systemd/bursawatch-release-agent.timer" \
  /etc/systemd/system/bursawatch-release-agent.timer
install -o root -g root -m 0440 \
  "$package_dir/deployment/sudoers.d/bursawatch-release-agent" \
  /etc/sudoers.d/bursawatch-release-agent

if [[ -e "$broad_sudoers_file" ]]; then
  rm "$broad_sudoers_file"
fi
visudo -c
systemctl daemon-reload

if [[ "$retry_blocked" == true ]]; then
  runuser -u "$release_user" -- env HOME="$release_home" \
    "$agent_dir/bursawatch-release-agent.sh" --clear-block
fi

systemctl enable --now bursawatch-release-agent.timer
systemctl start bursawatch-release-agent.service
printf 'Bootstrap backup: %s\n' "$backup_dir"
ROOT
