#!/usr/bin/env bash
# Run ON THE VPS. Saves a bookmark with 2 image assets, verifies they attach.
set -euo pipefail
KK=~/.agents/skills/karakeep/bin/karakeep
key=$(grep -E '^KARAKEEP_API_KEY=' ~/.hermes/.env | cut -d= -f2-)
addr=$(grep -E '^KARAKEEP_ADDR=' ~/.hermes/.env | cut -d= -f2-); addr=${addr:-http://localhost:3000}
api="$addr/api/v1"; AUTH=(-H "Authorization: Bearer $key")

d=$(mktemp -d); printf '%s' "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMCAQDXxxJ7AAAAAElFTkSuQmCC" | base64 -d > "$d/a.png"; cp "$d/a.png" "$d/b.png"

out=$("$KK" save --url "https://example.com/asset-test-$$" --title "asset test $$" \
  --note "two slides" --asset "$d/a.png" --asset "$d/b.png")
bid=$(echo "$out" | jq -r '.bookmarkId')
n=$(curl -sS "${AUTH[@]}" "$api/bookmarks/$bid" | jq '[.assets[]? | select(.assetType=="userUploaded")] | length')
[ "${n:-0}" -ge 2 ] && echo "PASS: $n image assets attached" || { echo "FAIL: assets=$n (inspect: curl $api/bookmarks/$bid)"; exit 1; }
curl -sS "${AUTH[@]}" -X DELETE "$api/bookmarks/$bid" >/dev/null
echo "PASS: cleaned up"
