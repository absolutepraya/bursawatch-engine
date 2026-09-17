#!/usr/bin/env bash
# Deploy the Cobalt media feature to the VPS: its media skill + container files.
set -euo pipefail
ROOT="$HOME/Documents/Projects/Hermes/service-cobalt"

"$ROOT/../scripts/require-published-commit"

rsync -a "$ROOT/skills/media/" "vps:.agents/skills/media/"
ssh vps 'chmod +x ~/.agents/skills/media/bin/* 2>/dev/null; chmod 600 ~/.agents/skills/media/SKILL.md 2>/dev/null; true'
echo "deployed skill: media"

ssh vps 'mkdir -p ~/cobalt'
rsync -a "$ROOT/compose/docker-compose.yml" "vps:cobalt/docker-compose.yml"
# never clobber a real cookies.json on the VPS
if ! ssh vps '[ -f ~/cobalt/cookies.json ]'; then
  rsync -a "$ROOT/compose/cookies.json" "vps:cobalt/cookies.json"
  echo "seeded cobalt/cookies.json"
fi
echo "deployed cobalt compose"
