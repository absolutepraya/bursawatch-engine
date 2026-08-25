# Social-post → KaraKeep (via Cobalt) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Abhip DM Yanto a TikTok/Instagram/Twitter(X) link and have Yanto fetch the post's images, read them, and save a KaraKeep bookmark (URL + images + extracted note) into a named folder, replying with the list.

**Architecture:** A self-hosted, localhost-only cobalt container does the media fetch. Two model-invoked bash skills wrap it: `cobalt` (download media from a URL → temp dir + JSON) and `karakeep` (create a bookmark, attach images, set note, add to a list). Yanto orchestrates conversationally (reads the images with its own vision between the two skill calls). No orchestrator skill.

**Tech Stack:** Docker Compose (cobalt), bash + curl + jq skills (matches the existing `chart`/`cf-dns` skill pattern), KaraKeep REST API (`/api/v1`, Bearer `ak2_`), self-hosted RSSHub (Twitter fallback path, already token-fixed).

## Global Constraints

- **Runtime is the VPS.** Skills call localhost services (`cobalt` `127.0.0.1:9000`, `karakeep` `127.0.0.1:3000`) that exist only on the VPS, so every test runs **on the VPS** after deploy. Dev home is the Mac.
- **Dev home:** `~/Documents/Projects/Hermes/cobalt/`. **Deploy targets (VPS):** cobalt container `~/cobalt/`; skills `~/.agents/skills/{cobalt,karakeep}/`.
- **Skills are bash** (`#!/usr/bin/env bash`, `set -euo pipefail`), bin executable, `SKILL.md` mode `600`. Self-source secrets from `~/.hermes/.env` (Hermes does not propagate env to subprocesses).
- **Secrets already set + validated on the VPS** in `~/.hermes/.env`: `KARAKEEP_API_KEY`, `KARAKEEP_ADDR=http://localhost:3000`. Add `COBALT_API_URL=http://localhost:9009/` in Task 1. RSSHub `~/rsshub/.env` `TWITTER_AUTH_TOKEN` (2 tokens) already done.
- **Cobalt API:** `POST /` with headers `Accept: application/json` + `Content-Type: application/json`, body `{"url": "..."}`. Responses: `{"status":"picker","picker":[{"type":"photo|video|gif","url":...,"thumb":...}],"audio":...}` / `{"status":"tunnel|redirect","url":...,"filename":...}` / `{"status":"error","error":{"code":...}}`.
- **KaraKeep API** (base `http://localhost:3000/api/v1`, header `Authorization: Bearer ak2_…`): `POST /bookmarks {type:"link",url}` → `{id,…}`; `PATCH /bookmarks/{id} {title,note}`; `POST /assets` multipart field `file` → `{assetId,contentType,size,fileName}`; `POST /bookmarks/{id}/assets {id:<assetId>,assetType:"image"}`; `GET /lists` → `{lists:[{id,name,icon,parentId}]}`; `PUT /lists/{listId}/bookmarks/{bookmarkId}`.
- **Platform validation in the `cobalt` skill** (only tiktok/instagram/twitter/x), not in cobalt config.
- **No watchtower/auto-update for cobalt** (manual `docker compose pull`). `mem_limit: 512m`.
- **Version control:** the dev home is not a git repo. **Task 1 Step 1 runs `git init`** there so the commit steps work; if you prefer no repo, skip every "Commit" step.
- **A real TikTok photo-mode URL is required for tests** (`https://www.tiktok.com/@user/photo/<id>`). Get one from Abhip (his perfume/watch carousels). Referenced below as `$TEST_TT` (export it before testing).

---

## File Structure

```
~/Documents/Projects/Hermes/cobalt/          # Mac dev home
├── docs/specs/2026-06-25-social-carousel-to-karakeep-design.md   # (exists)
├── docs/plans/2026-06-25-social-carousel-to-karakeep-plan.md     # (this file)
├── compose/docker-compose.yml               # cobalt container
├── compose/cookies.json                     # minimal (IG/X cookies later)
├── skills/cobalt/SKILL.md
├── skills/cobalt/bin/cobalt                  # bash, executable
├── skills/karakeep/SKILL.md
├── skills/karakeep/bin/karakeep             # bash, executable
├── tests/test-cobalt.sh                      # integration test (run on VPS)
├── tests/test-karakeep.sh                    # integration test (run on VPS)
├── deploy.sh                                 # rsync skills + compose to VPS
└── README.md
```

VPS runtime layout (created by deploy): `~/cobalt/{docker-compose.yml,cookies.json}`, `~/.agents/skills/cobalt/{SKILL.md,bin/cobalt}`, `~/.agents/skills/karakeep/{SKILL.md,bin/karakeep}`.

---

## Task 1: Cobalt container + deploy script

**Files:**
- Create: `~/Documents/Projects/Hermes/cobalt/compose/docker-compose.yml`
- Create: `~/Documents/Projects/Hermes/cobalt/compose/cookies.json`
- Create: `~/Documents/Projects/Hermes/cobalt/deploy.sh`
- Create on VPS (by deploy): `~/cobalt/docker-compose.yml`, `~/cobalt/cookies.json`

**Interfaces:**
- Produces: a cobalt HTTP API at `http://127.0.0.1:9000/` on the VPS that returns `status:"picker"` JSON for a TikTok carousel.

- [ ] **Step 1: Init the dev home for version control**

```bash
cd ~/Documents/Projects/Hermes/cobalt && git init -q && printf 'compose/cookies.json\n.DS_Store\n' > .gitignore
```
(Skip this and all Commit steps if you do not want a repo. Note `cookies.json` is gitignored — it will hold X/IG session cookies later.)

- [ ] **Step 2: Write the cobalt compose**

`compose/docker-compose.yml`:
```yaml
# Self-hosted cobalt (imput) — localhost only, used by Yanto's `cobalt` skill.
services:
  cobalt-api:
    image: ghcr.io/imputnet/cobalt:11
    init: true
    read_only: true
    restart: unless-stopped
    mem_limit: 512m
    ports:
      - 127.0.0.1:9009:9000   # localhost only; UFW blocks external regardless
    environment:
      API_URL: "http://localhost:9009/"
      COOKIE_PATH: "/cookies.json"
    volumes:
      - ./cookies.json:/cookies.json
```

- [ ] **Step 3: Write the minimal cookies.json**

`compose/cookies.json` (empty object now; IG/X cookies dropped in later):
```json
{}
```

- [ ] **Step 4: Write the deploy script**

`deploy.sh`:
```bash
#!/usr/bin/env bash
# Deploy the cobalt feature to the VPS: skills + cobalt container files.
set -euo pipefail
ROOT="$HOME/Documents/Projects/Hermes/cobalt"

for s in cobalt karakeep; do
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
```
```bash
chmod +x ~/Documents/Projects/Hermes/cobalt/deploy.sh
```

- [ ] **Step 5: Add COBALT_API_URL to the VPS env**

```bash
ssh vps 'grep -q "^COBALT_API_URL=" ~/.hermes/.env || echo "COBALT_API_URL=http://localhost:9009/" >> ~/.hermes/.env; grep "^COBALT_API_URL=" ~/.hermes/.env'
```
Expected: prints `COBALT_API_URL=http://localhost:9009/`

- [ ] **Step 6: Deploy + start cobalt**

```bash
~/Documents/Projects/Hermes/cobalt/deploy.sh
ssh vps 'cd ~/cobalt && docker compose pull && docker compose up -d'
```
Expected: image pulls, `cobalt-api` container starts.

- [ ] **Step 7: Verify cobalt is up and returns a picker (run on VPS)**

```bash
export TEST_TT='https://www.tiktok.com/@USER/photo/ID'   # a real public TikTok photo-mode post
ssh vps "curl -sS --max-time 60 -X POST http://localhost:9009/ -H 'Accept: application/json' -H 'Content-Type: application/json' -d '$(printf '{\"url\":\"%s\"}' "$TEST_TT")' | jq '{status, n:(.picker|length), first:.picker[0].type}'"
```
Expected: `{"status":"picker","n":<N≥2>,"first":"photo"}`. If `status:"error"`, inspect `.error.code` (try another public photo URL).

- [ ] **Step 8: Confirm container health + cap**

```bash
ssh vps 'docker stats --no-stream --format "{{.Name}} {{.MemUsage}}" | grep cobalt; free -h | head -2'
```
Expected: `cobalt-api … / 512MiB`; box still has headroom.

- [ ] **Step 9: Commit**

```bash
cd ~/Documents/Projects/Hermes/cobalt
git add compose/docker-compose.yml deploy.sh .gitignore
git commit -m "feat: self-hosted cobalt container + deploy script"
```

---

## Task 2: `cobalt` skill

**Files:**
- Create: `~/Documents/Projects/Hermes/cobalt/skills/cobalt/bin/cobalt`
- Create: `~/Documents/Projects/Hermes/cobalt/skills/cobalt/SKILL.md`
- Test: `~/Documents/Projects/Hermes/cobalt/tests/test-cobalt.sh`

**Interfaces:**
- Consumes: cobalt API at `$COBALT_API_URL` (Task 1).
- Produces: `cobalt <url>` prints JSON `{source_url, host, type:"carousel"|"single", images:[abs paths], audio:path|null, count}` and leaves files in a temp dir.

- [ ] **Step 1: Write the integration test**

`tests/test-cobalt.sh`:
```bash
#!/usr/bin/env bash
# Run ON THE VPS. Requires: TEST_TT=<public tiktok photo url>
set -euo pipefail
: "${TEST_TT:?export TEST_TT to a public TikTok photo-mode URL}"
out=$(~/.agents/skills/cobalt/bin/cobalt "$TEST_TT")
echo "$out" | jq -e '.count >= 2 and (.images|length)==.count and .type=="carousel"' >/dev/null \
  && echo "PASS: carousel count=$(echo "$out" | jq .count)" || { echo "FAIL: $out"; exit 1; }
# every reported file exists and is non-empty
for f in $(echo "$out" | jq -r '.images[]'); do [ -s "$f" ] || { echo "FAIL: missing $f"; exit 1; }; done
echo "PASS: all image files present"
# bad host rejected
if ~/.agents/skills/cobalt/bin/cobalt "https://example.com/x" 2>/dev/null; then echo "FAIL: bad host accepted"; exit 1; else echo "PASS: bad host rejected"; fi
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
rsync -a ~/Documents/Projects/Hermes/cobalt/tests/ vps:cobalt-tests/
ssh vps 'TEST_TT="'"$TEST_TT"'" bash ~/cobalt-tests/test-cobalt.sh'
```
Expected: FAIL (skill not deployed yet: "No such file or directory").

- [ ] **Step 3: Write the `cobalt` skill bin**

`skills/cobalt/bin/cobalt`:
```bash
#!/usr/bin/env bash
# cobalt — download media (photos/slides/video) from a TikTok/Instagram/Twitter(X)
# link via the self-hosted cobalt instance. Prints JSON describing the download.
# Usage: cobalt <url> [--out <dir>]
set -euo pipefail
err(){ echo "cobalt: $*" >&2; exit 1; }

url="${1:-}"; [ -n "$url" ] || err "usage: cobalt <url> [--out <dir>]"; shift
outdir=""
while [ $# -gt 0 ]; do case "$1" in
  --out) outdir="${2:?}"; shift 2;;
  *) err "unknown arg: $1";;
esac; done

host=$(printf '%s' "$url" | sed -E 's#^https?://##; s#/.*##; s#^www\.##' | tr 'A-Z' 'a-z')
case "$host" in
  tiktok.com|vm.tiktok.com|vt.tiktok.com|*.tiktok.com) svc=tiktok;;
  instagram.com|*.instagram.com) svc=instagram;;
  twitter.com|x.com|mobile.twitter.com|*.twitter.com) svc=twitter;;
  *) err "unsupported host '$host' (tiktok / instagram / twitter|x only)";;
esac

api="${COBALT_API_URL:-}"
if [ -z "$api" ] && [ -r "$HOME/.hermes/.env" ]; then
  api=$(grep -E '^COBALT_API_URL=' "$HOME/.hermes/.env" | head -1 | cut -d= -f2-)
fi
api="${api:-http://localhost:9009/}"

resp=$(curl -sS --max-time 60 -X POST "$api" \
  -H 'Accept: application/json' -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u "$url" '{url:$u}')") || err "cobalt request failed"

status=$(printf '%s' "$resp" | jq -r '.status // "error"')
if [ "$status" = "error" ]; then
  err "cobalt error: $(printf '%s' "$resp" | jq -r '.error.code // "unknown"')"
fi
case "$status" in
  picker) mapfile -t media < <(printf '%s' "$resp" | jq -r '.picker[] | select(.type=="photo" or .type=="gif" or .type=="video") | .url');;
  tunnel|redirect) mapfile -t media < <(printf '%s' "$resp" | jq -r '.url');;
  *) err "unexpected status '$status'";;
esac
[ "${#media[@]}" -gt 0 ] || err "no media returned for $url"
audio_url=$(printf '%s' "$resp" | jq -r '.audio // empty')

outdir="${outdir:-$(mktemp -d /tmp/cobalt-XXXXXX)}"; mkdir -p "$outdir"
i=0; files=()
for m in "${media[@]}"; do
  i=$((i+1))
  ext=$(printf '%s' "$m" | sed -E 's/\?.*//; s/.*\.//' | grep -iE '^(jpe?g|png|webp|gif|mp4)$' || true)
  f=$(printf '%s/%02d.%s' "$outdir" "$i" "${ext:-jpg}")
  curl -sS --max-time 120 -L -o "$f" "$m" || err "download failed: $m"
  files+=("$f")
done
audio_path="null"
if [ -n "$audio_url" ]; then
  ap="$outdir/audio.mp3"
  if curl -sS --max-time 120 -L -o "$ap" "$audio_url"; then audio_path="$ap"; fi
fi
type=$([ "$status" = picker ] && echo carousel || echo single)
jq -nc --arg src "$url" --arg host "$svc" --arg type "$type" --arg audio "$audio_path" \
  --args "${files[@]}" \
  '{source_url:$src, host:$host, type:$type, images:$ARGS.positional,
    audio:(if $audio=="null" then null else $audio end), count:($ARGS.positional|length)}'
```

- [ ] **Step 4: Write SKILL.md**

`skills/cobalt/SKILL.md`:
```markdown
---
name: cobalt
description: Download photos, slides, or video from a TikTok, Instagram, or Twitter/X link. Use when the user shares such a link and you need its media files locally (e.g. to read carousel slides or archive a post).
---

# cobalt — fetch social media

Downloads media from one TikTok / Instagram / Twitter(X) URL via the self-hosted
cobalt instance and prints JSON describing what it saved.

## Usage

    cobalt <url> [--out <dir>]

## Output (stdout JSON)

    {"source_url":"…","host":"tiktok","type":"carousel","images":["/tmp/cobalt-…/01.jpg", …],"audio":null,"count":7}

- `type` is `carousel` (multiple slides) or `single`.
- `images` are absolute paths; read each one (vision) to extract content.
- Exits non-zero with `cobalt: <reason>` on unsupported host, cobalt error, or download failure.

## Notes

- Only tiktok / instagram / twitter|x hosts are accepted.
- Reads `COBALT_API_URL` from `~/.hermes/.env` (default `http://localhost:9009/`).
- Instagram and some X content need cookies in cobalt's `cookies.json`; until then they may fail (TikTok works without).
```

- [ ] **Step 5: Deploy + run the test to verify it passes**

```bash
~/Documents/Projects/Hermes/cobalt/deploy.sh
ssh vps 'TEST_TT="'"$TEST_TT"'" bash ~/cobalt-tests/test-cobalt.sh'
```
Expected: `PASS: carousel count=N`, `PASS: all image files present`, `PASS: bad host rejected`.

- [ ] **Step 6: Commit**

```bash
cd ~/Documents/Projects/Hermes/cobalt
git add skills/cobalt tests/test-cobalt.sh
git commit -m "feat: cobalt fetch skill"
```

---

## Task 3: `karakeep` skill — bookmark + note + list (no assets yet)

**Files:**
- Create: `~/Documents/Projects/Hermes/cobalt/skills/karakeep/bin/karakeep`
- Create: `~/Documents/Projects/Hermes/cobalt/skills/karakeep/SKILL.md`
- Test: `~/Documents/Projects/Hermes/cobalt/tests/test-karakeep.sh`

**Interfaces:**
- Consumes: `KARAKEEP_API_KEY` + `KARAKEEP_ADDR` from `~/.hermes/.env`.
- Produces: `karakeep save --url … [--title …] [--note @file] [--list NAME] [--asset PATH]… [--tag …]` prints `{bookmarkId, viewUrl}`. (`--asset` handling added in Task 4.)

- [ ] **Step 1: Write the integration test (bookmark + note + list)**

`tests/test-karakeep.sh`:
```bash
#!/usr/bin/env bash
# Run ON THE VPS. Creates a throwaway list, saves into it, verifies, cleans up.
set -euo pipefail
KK=~/.agents/skills/karakeep/bin/karakeep
key=$(grep -E '^KARAKEEP_API_KEY=' ~/.hermes/.env | cut -d= -f2-)
addr=$(grep -E '^KARAKEEP_ADDR=' ~/.hermes/.env | cut -d= -f2-); addr=${addr:-http://localhost:3000}
api="$addr/api/v1"; AUTH=(-H "Authorization: Bearer $key")
TL="zz-test-$$"

# create the throwaway list
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

# verify note set
note=$(curl -sS "${AUTH[@]}" "$api/bookmarks/$bid" | jq -r '.note')
echo "$note" | grep -q "item A" && echo "PASS: note saved" || { echo "FAIL: note missing"; exit 1; }
# verify it's in the list
inlist=$(curl -sS "${AUTH[@]}" "$api/lists/$lid/bookmarks" | jq --arg b "$bid" '[.bookmarks[]?.id] | index($b) != null')
[ "$inlist" = true ] && echo "PASS: bookmark in list" || { echo "FAIL: not in list"; exit 1; }
# ambiguous/missing list behaviour
"$KK" save --url https://example.com/x --list "definitely-not-a-list-$$" 2>/dev/null && { echo "FAIL: missing list accepted"; exit 1; } || echo "PASS: missing list rejected"

# cleanup
curl -sS "${AUTH[@]}" -X DELETE "$api/bookmarks/$bid" >/dev/null
curl -sS "${AUTH[@]}" -X DELETE "$api/lists/$lid" >/dev/null
echo "PASS: cleaned up"
```

- [ ] **Step 2: Deploy the test + run to verify it fails**

```bash
rsync -a ~/Documents/Projects/Hermes/cobalt/tests/ vps:cobalt-tests/
ssh vps 'bash ~/cobalt-tests/test-karakeep.sh'
```
Expected: FAIL (karakeep skill not deployed: "No such file or directory").

- [ ] **Step 3: Write the `karakeep` skill bin**

`skills/karakeep/bin/karakeep`:
```bash
#!/usr/bin/env bash
# karakeep — save a bookmark (link + optional images + note) to KaraKeep, into a folder.
# Usage: karakeep save --url <url> [--title <t>] [--note <text|@file>] [--list <name>] [--asset <path>]... [--tag <t>]...
set -euo pipefail
err(){ echo "karakeep: $*" >&2; exit 1; }

[ "${1:-}" = save ] || err "usage: karakeep save --url <url> [...]"; shift
url="" title="" note="" list=""; assets=(); tags=()
while [ $# -gt 0 ]; do case "$1" in
  --url) url="${2:?}"; shift 2;;
  --title) title="${2:?}"; shift 2;;
  --note) note="${2:?}"; shift 2;;
  --list) list="${2:?}"; shift 2;;
  --asset) assets+=("${2:?}"); shift 2;;
  --tag) tags+=("${2:?}"); shift 2;;
  *) err "unknown arg: $1";;
esac; done
[ -n "$url" ] || err "--url required"
if [ "${note:0:1}" = "@" ]; then nf="${note:1}"; [ -r "$nf" ] || err "note file unreadable: $nf"; note=$(cat "$nf"); fi

key="${KARAKEEP_API_KEY:-}"; addr="${KARAKEEP_ADDR:-}"
if [ -r "$HOME/.hermes/.env" ]; then
  [ -z "$key" ] && key=$(grep -E '^KARAKEEP_API_KEY=' "$HOME/.hermes/.env" | head -1 | cut -d= -f2-)
  [ -z "$addr" ] && addr=$(grep -E '^KARAKEEP_ADDR=' "$HOME/.hermes/.env" | head -1 | cut -d= -f2-)
fi
addr="${addr:-http://localhost:3000}"; [ -n "$key" ] || err "KARAKEEP_API_KEY not set"
api="$addr/api/v1"; AUTH=(-H "Authorization: Bearer $key")
kk(){ curl -sS --max-time 60 "${AUTH[@]}" "$@"; }

# resolve list name -> id (0 -> error, >1 -> ambiguous)
list_id=""
if [ -n "$list" ]; then
  matches=$(kk "$api/lists" | jq -r --arg n "$list" '.lists[] | select(.name==$n) | .id')
  cnt=$(printf '%s' "$matches" | grep -c . || true)
  [ "$cnt" -eq 0 ] && err "list '$list' not found"
  [ "$cnt" -gt 1 ] && err "list '$list' ambiguous ($cnt matches); disambiguate"
  list_id="$matches"
fi

bid=$(kk -X POST "$api/bookmarks" -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u "$url" '{type:"link", url:$u}')" | jq -r '.id // empty')
[ -n "$bid" ] || err "bookmark create failed"

if [ -n "$title" ] || [ -n "$note" ]; then
  kk -X PATCH "$api/bookmarks/$bid" -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg t "$title" --arg n "$note" \
      '{} + (if $t=="" then {} else {title:$t} end) + (if $n=="" then {} else {note:$n} end)')" >/dev/null \
    || err "bookmark update failed"
fi

# (assets handled in Task 4 — placeholder loop is a no-op when none passed)
for a in "${assets[@]:-}"; do [ -n "$a" ] || continue
  [ -r "$a" ] || err "asset unreadable: $a"
  aid=$(kk -X POST "$api/assets" -F "file=@$a" | jq -r '.assetId // empty')
  [ -n "$aid" ] || err "asset upload failed: $a"
  kk -X POST "$api/bookmarks/$bid/assets" -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg id "$aid" '{id:$id, assetType:"image"}')" >/dev/null || err "asset attach failed: $a"
done

if [ -n "$list_id" ]; then kk -X PUT "$api/lists/$list_id/bookmarks/$bid" >/dev/null || err "add-to-list failed"; fi

if [ "${#tags[@]}" -gt 0 ]; then
  tjson=$(printf '%s\n' "${tags[@]}" | jq -R . | jq -s '{tags: map({tagName: .})}')
  kk -X POST "$api/bookmarks/$bid/tags" -H 'Content-Type: application/json' -d "$tjson" >/dev/null || true
fi

pub="${KARAKEEP_PUBLIC_URL:-$addr}"
jq -nc --arg id "$bid" --arg v "$pub/dashboard/preview/$bid" '{bookmarkId:$id, viewUrl:$v}'
```

Note: the asset loop is already present (Task 4 only adds its test + display verification). The `${assets[@]:-}` guard makes it a safe no-op when no `--asset` is given.

- [ ] **Step 4: Write SKILL.md**

`skills/karakeep/SKILL.md`:
```markdown
---
name: karakeep
description: Save or bookmark a link (with optional images and a note) to KaraKeep, into a named folder. Use when the user wants to save, archive, or remember content to KaraKeep.
---

# karakeep — save to KaraKeep

Creates a link bookmark, optionally attaches images and sets a note/title, and files
it into a named list (folder). Prints `{bookmarkId, viewUrl}`.

## Usage

    karakeep save --url <url> [--title <t>] [--note <text|@file>] \
                  [--list "<folder name>"] [--asset <path>]... [--tag <t>]...

## Behaviour

- `--list` resolves the folder by exact name. If it does not exist, or the name is
  ambiguous (KaraKeep allows duplicate names), the command errors — ask the user
  which folder, or create it first.
- `--note @file` reads the note body from a file (use for multi-line markdown).
- `--asset` uploads the image and attaches it to the bookmark (assetType `image`).
- Reads `KARAKEEP_API_KEY` + `KARAKEEP_ADDR` from `~/.hermes/.env`.
```

- [ ] **Step 5: Deploy + run the test to verify it passes**

```bash
~/Documents/Projects/Hermes/cobalt/deploy.sh
ssh vps 'bash ~/cobalt-tests/test-karakeep.sh'
```
Expected: `PASS: created bookmark …`, `PASS: note saved`, `PASS: bookmark in list`, `PASS: missing list rejected`, `PASS: cleaned up`.

- [ ] **Step 6: Commit**

```bash
cd ~/Documents/Projects/Hermes/cobalt
git add skills/karakeep tests/test-karakeep.sh
git commit -m "feat: karakeep save skill (bookmark + note + list)"
```

---

## Task 4: `karakeep` skill — verify asset upload + display

The asset code already exists in the bin (Task 3). This task proves it works against the live API and confirms how the images render, the one item flagged "verify during implementation" in the spec.

**Files:**
- Modify (if display needs it): `~/Documents/Projects/Hermes/cobalt/skills/karakeep/bin/karakeep`
- Test: `~/Documents/Projects/Hermes/cobalt/tests/test-karakeep-assets.sh`

- [ ] **Step 1: Write the asset test**

`tests/test-karakeep-assets.sh`:
```bash
#!/usr/bin/env bash
# Run ON THE VPS. Saves a bookmark with 2 image assets, verifies they attach.
set -euo pipefail
KK=~/.agents/skills/karakeep/bin/karakeep
key=$(grep -E '^KARAKEEP_API_KEY=' ~/.hermes/.env | cut -d= -f2-)
addr=$(grep -E '^KARAKEEP_ADDR=' ~/.hermes/.env | cut -d= -f2-); addr=${addr:-http://localhost:3000}
api="$addr/api/v1"; AUTH=(-H "Authorization: Bearer $key")

# make 2 tiny test PNGs
d=$(mktemp -d); printf '%s' "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMCAQDXxxJ7AAAAAElFTkSuQmCC" | base64 -d > "$d/a.png"; cp "$d/a.png" "$d/b.png"

out=$("$KK" save --url "https://example.com/asset-test-$$" --title "asset test $$" \
  --note "two slides" --asset "$d/a.png" --asset "$d/b.png")
bid=$(echo "$out" | jq -r '.bookmarkId')
n=$(curl -sS "${AUTH[@]}" "$api/bookmarks/$bid" | jq '[.assets[]? | select(.assetType=="image")] | length')
[ "${n:-0}" -ge 2 ] && echo "PASS: $n image assets attached" || { echo "FAIL: assets=$n"; exit 1; }
curl -sS "${AUTH[@]}" -X DELETE "$api/bookmarks/$bid" >/dev/null
echo "PASS: cleaned up"
```

- [ ] **Step 2: Deploy test + run**

```bash
rsync -a ~/Documents/Projects/Hermes/cobalt/tests/ vps:cobalt-tests/
ssh vps 'bash ~/cobalt-tests/test-karakeep-assets.sh'
```
Expected: `PASS: 2 image assets attached`, `PASS: cleaned up`. If the bookmark JSON has no `assets` array, inspect `curl .../bookmarks/$bid | jq` to find where attached image assets live in this fork and adjust the verify (and, if needed, the attach `assetType`).

- [ ] **Step 3: Eyeball the render**

Open the bookmark in the KaraKeep UI (`https://<your-karakeep-subdomain>/dashboard/preview/<bid>` from a quick manual `karakeep save` into a test list) and confirm the slides are visible. If they only archive but don't show, switch the note to embed asset URLs inline as markdown images (`![](/api/v1/assets/<assetId>)`) and re-test. Record the chosen approach in the skill's SKILL.md.

- [ ] **Step 4: Commit**

```bash
cd ~/Documents/Projects/Hermes/cobalt
git add tests/test-karakeep-assets.sh skills/karakeep
git commit -m "test: karakeep image asset attach + display"
```

---

## Task 5: End-to-end through Yanto + README

**Files:**
- Create: `~/Documents/Projects/Hermes/cobalt/README.md`
- Modify (optional): `~/.hermes/memories/USER.md` (one-line capability pointer)

**Interfaces:**
- Consumes: deployed cobalt container + both skills.

- [ ] **Step 1: Restart the gateway so Yanto sees the new skills**

```bash
ssh vps 'sudo systemctl restart hermes-gateway && sleep 30 && systemctl is-active hermes-gateway'
```
Expected: `active`. (Skills load from `~/.agents/skills`; a restart guarantees Yanto re-reads them.)

- [ ] **Step 2: Optional — add a capability pointer to USER.md**

Only if you want to nudge reliability. Append under the capability section of `~/.hermes/memories/USER.md`:
```
- Saving a social post: when Abhip sends a TikTok/Instagram/X link to "save"/"simpan" to a KaraKeep folder, run `cobalt <url>`, read every downloaded image, then `karakeep save --url <url> --title <t> --note @<file> --asset <each image> --list "<folder>"`, and reply with the extracted list + the KaraKeep link.
```
Then session-reset/restart per the Hermes runbook. (Skip if you'd rather rely on the skill descriptions alone first.)

- [ ] **Step 3: Live end-to-end test via Yanto**

From your phone/desktop, DM Yanto:
```
cek ini dong to, save di karakeep folder Watch gua <TEST_TT>
```
Expected: Yanto fetches the slides, replies with the itemized list + a KaraKeep link, and the bookmark appears in the `Watch` folder with the slide images + note. Verify in the KaraKeep UI.

- [ ] **Step 4: Write the README**

`README.md`:
```markdown
# cobalt → KaraKeep (Yanto)

Send Yanto a TikTok / Instagram / Twitter(X) link to save its images + an extracted
note into a KaraKeep folder. TikTok is solid; IG/X are best-effort (cookies/proxy later).

## Pieces
- `compose/` — self-hosted cobalt container (VPS `~/cobalt/`, localhost:9009, mem 512m).
- `skills/cobalt/` — fetch media from a URL → temp dir + JSON.
- `skills/karakeep/` — save a bookmark (link + images + note) into a named folder.
- Yanto orchestrates: cobalt → read images (vision) → karakeep save → reply.

## Workflow
Edit here → `./deploy.sh` → test on the VPS (`bash ~/cobalt-tests/test-*.sh`).
Tests are integration-style and need a real public TikTok photo URL in `TEST_TT`.

## Config (VPS, never synced)
- `~/.hermes/.env`: `KARAKEEP_API_KEY`, `KARAKEEP_ADDR`, `COBALT_API_URL`.
- `~/cobalt/cookies.json`: add IG/X session cookies to extend reliability.

See `docs/specs/` for the design and `docs/plans/` for this plan.
```

- [ ] **Step 5: Commit**

```bash
cd ~/Documents/Projects/Hermes/cobalt
git add README.md
git commit -m "docs: cobalt→karakeep readme"
```

- [ ] **Step 6: Mirror to dotfiles**

```bash
~/.dotfiles/sync.sh
```
Expected: the two skills appear under dotfiles `vps/agents/skills/{cobalt,karakeep}/` (FROM-VPS mirror). `.env` stays VPS-only (scrubbed).

---

## Notes for the implementer

- **Run order matters:** Task 1 must finish (cobalt up + `COBALT_API_URL` set) before Task 2's test can pass; KaraKeep key is already live so Task 3 can run anytime after deploy.
- **Secrets:** never echo `KARAKEEP_API_KEY` or the X tokens in command output. They are already on the VPS.
- **VPS-side execution:** per the project rules, run the actual deploy/start/test on the VPS. The Mac side is authoring + `deploy.sh`.
- **Follow-ups (out of scope):** IG/X cobalt `cookies.json`; RSSHub-X rate-limit proxy; `sync.sh`/`deploy.sh` `Hermes-cron(s)`→`Hermes` rename (tracked separately).
- **RSSHub-first-for-X deferred:** v1 routes X straight to cobalt (the `cobalt` skill accepts twitter/x hosts and resolves a single tweet directly). The spec's RSSHub-first branch is not coded because RSSHub serves user timelines, not single tweets, and is rate-limited from the datacenter IP. Revisit only if a per-tweet RSSHub route proves viable; cobalt-for-X needs an X cookie for some content.
```
