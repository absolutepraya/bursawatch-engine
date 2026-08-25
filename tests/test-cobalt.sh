#!/usr/bin/env bash
# Run ON THE VPS. Tests the cobalt skill's TikTok (tikwm) path.
# Override TEST_TT to use a different public TikTok photo URL.
set -euo pipefail
TEST_TT="${TEST_TT:-https://vt.tiktok.com/ZSCFXvRDG/}"
BIN=~/.agents/skills/cobalt/bin/cobalt

out=$("$BIN" "$TEST_TT")
echo "$out" | jq -e '.host=="tiktok" and .count >= 2 and (.images|length)==.count and .type=="carousel"' >/dev/null \
  && echo "PASS: tiktok carousel count=$(echo "$out" | jq .count), caption=$(echo "$out" | jq -r '.caption' | head -c 30)" \
  || { echo "FAIL: $out"; exit 1; }
for f in $(echo "$out" | jq -r '.images[]'); do [ -s "$f" ] || { echo "FAIL: missing $f"; exit 1; }; done
echo "PASS: all image files present"
if "$BIN" "https://example.com/x" 2>/dev/null; then echo "FAIL: bad host accepted"; exit 1; else echo "PASS: bad host rejected"; fi
