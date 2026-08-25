#!/usr/bin/env bash
# Deploy the cobalt feature to the VPS: skills + cobalt container files.
set -euo pipefail
ROOT="$HOME/Documents/Projects/Hermes/cobalt"

for s in media karakeep; do
  [ -d "$ROOT/skills/$s" ] || continue
  rsync -a "$ROOT/skills/$s/" "vps:.agents/skills/$s/"
  ssh vps "chmod +x ~/.agents/skills/$s/bin/* 2>/dev/null; chmod 600 ~/.agents/skills/$s/SKILL.md 2>/dev/null; true"
  echo "deployed skill: $s"
done

ssh vps 'mkdir -p ~/cobalt'
rsync -a "$ROOT/compose/docker-compose.yml" "vps:cobalt/docker-compose.yml"
# never clobber a real cookies.json on the VPS
if ! ssh vps '[ -f ~/cobalt/cookies.json ]'; then
  rsync -a "$ROOT/compose/cookies.json" "vps:cobalt/cookies.json"
  echo "seeded cobalt/cookies.json"
fi
echo "deployed cobalt compose"
