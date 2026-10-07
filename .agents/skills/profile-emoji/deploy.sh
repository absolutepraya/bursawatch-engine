#!/usr/bin/env bash
# Deploy the reusable profile-emoji skill and wrapper to the VPS.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")" && pwd)"
"$repo_root/../../../scripts/require-published-commit"

ssh vps 'install -d -m 700 "$HOME/.agents/skills/profile-emoji/bin"'
rsync -a --exclude='__pycache__/' --exclude='*.pyc' "$repo_root/bin/" "vps:.agents/skills/profile-emoji/bin/"
rsync -a "$repo_root/SKILL.md" "vps:.agents/skills/profile-emoji/SKILL.md"
ssh vps 'chmod 755 "$HOME/.agents/skills/profile-emoji/bin/profile-emoji" && chmod 644 "$HOME/.agents/skills/profile-emoji/bin/profile_emoji.py" "$HOME/.agents/skills/profile-emoji/SKILL.md"'
echo "deployed profile-emoji skill"
