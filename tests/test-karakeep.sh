#!/usr/bin/env bash
# Run ON THE VPS. Creates a throwaway list, saves into it, verifies, cleans up.
set -euo pipefail
KK=~/.agents/skills/karakeep/bin/karakeep
key=$(grep -E '^KARAKEEP_API_KEY=' ~/.hermes/.env | cut -d= -f2-)
addr=$(grep -E '^KARAKEEP_ADDR=' ~/.hermes/.env | cut -d= -f2-); addr=${addr:-http://localhost:3000}
api="$addr/api/v1"; AUTH=(-H "Authorization: Bearer $key")
TL="zz-test-$$"

lid=$(curl -sS "${AUTH[@]}" -X POST "$api/lists" -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg n "$TL" '{name:$n, icon:"🧪"}')" | jq -r '.id')
[ -n "$lid" ] && [ "$lid" != null ] || { echo "FAIL: could not create test list"; exit 1; }

out=$("$KK" save --url "https://example.com/karakeep-test-$$" --title "KK test $$" \
  --note "line one
- item A — detail
- item B — detail" --list "$TL")
bid=$(echo "$out" | jq -r '.bookmarkId')
[ -n "$bid" ] && [ "$bid" != null ] || { echo "FAIL: no bookmarkId: $out"; exit 1; }
echo "PASS: created bookmark $bid"

note=$(curl -sS "${AUTH[@]}" "$api/bookmarks/$bid" | jq -r '.note')
echo "$note" | grep -q "item A" && echo "PASS: note saved" || { echo "FAIL: note missing"; exit 1; }
inlist=$(curl -sS "${AUTH[@]}" "$api/lists/$lid/bookmarks" | jq --arg b "$bid" '[.bookmarks[]?.id] | index($b) != null')
[ "$inlist" = true ] && echo "PASS: bookmark in list" || { echo "FAIL: not in list"; exit 1; }
"$KK" save --url https://example.com/x --list "definitely-not-a-list-$$" 2>/dev/null && { echo "FAIL: missing list accepted"; exit 1; } || echo "PASS: missing list rejected"

curl -sS "${AUTH[@]}" -X DELETE "$api/bookmarks/$bid" >/dev/null
curl -sS "${AUTH[@]}" -X DELETE "$api/lists/$lid" >/dev/null
echo "PASS: cleaned up"
