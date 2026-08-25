# Social-post → KaraKeep (via Cobalt) — Design

**Date:** 2026-06-25
**Status:** Approved design, ready for implementation plan
**Owner:** Abhip / Yanto (Hermes agent on the VPS)

> **Implementation note (2026-06-25):** During build, cobalt's TikTok module turned out to
> be broken (fails for every TikTok URL from any IP). The fetch skill (named `media`, not a
> separate orchestrator) therefore routes **TikTok -> tikwm.com** and **Instagram/X -> cobalt**.
> Verified working: TikTok (tikwm) and Instagram (cobalt, no cookies). X stays best-effort. The
> cobalt container (now on port 9009, since cap-minio holds 9000/9001) is kept for IG/X.

## Goal

Let Abhip send Yanto a TikTok / Instagram / Twitter(X) post link in chat and have
Yanto fetch the post's images, read them, extract the useful content, and save it
to a named KaraKeep folder, then reply with the extracted list.

Driving use case: TikTok photo carousels of perfume / watch recommendations (text
baked into each slide). Example prompt (verbatim, Indonesian/English mix):

> "cek ini dong to, ada jam2 kesukaan gua. save di karakeep folder watchlist watch gua \<tiktok link\>"

Yanto must: detect the link + target folder ("Watch"), fetch all slides, read them,
write a faithful list, save a KaraKeep bookmark (URL + images + note) into that
folder, and reply.

## Why this shape

- **Cobalt is the only reliable tool for TikTok photo mode.** `gallery-dl` / `yt-dlp`
  currently fail on TikTok slideshows; cobalt returns a `picker` array of the slide
  image URLs (+ optional background audio) natively.
- **Cobalt's public instance is not usable programmatically** (Cloudflare Turnstile +
  short-lived JWT, "not intended for other projects"). We self-host.
- **Vision beats OCR.** Yanto (gpt-5.5, vision-capable) reading the slides understands
  names/prices/context, not just raw text. So extraction is Yanto's job, not a
  bundled OCR engine.
- **Skills over MCP** for the building blocks: zero idle RAM (CLI invoked on demand),
  matches the existing `chart` / `cf-dns` pattern. The box is RAM-tight (8 GB).

## Architecture

```
Abhip DMs Yanto a tiktok/ig/x link + target folder (Telegram/Discord/WhatsApp)
        │
        ▼  Yanto orchestrates conversationally (NO orchestrator skill)
  1. FETCH by host:
       tiktok / instagram  ── cobalt skill ──►  cobalt container (127.0.0.1:9009)
       twitter / x         ── try local RSSHub (127.0.0.1:1200) ─► on fail ─► cobalt
                                 (RSSHub is feed/timeline-only + rate-limited from the
                                  datacenter IP, so cobalt is the de-facto X path for
                                  a single tweet link)
  2. READ every downloaded image (gpt-5.5 vision) — exhaustive, no slide skipped
  3. EXTRACT a faithful markdown note (summary + itemized list)
  4. SAVE  ── karakeep skill ──►  karakeep container (127.0.0.1:3000, /api/v1)
                 create link bookmark + upload & attach images + set note + add to folder
  5. REPLY in chat: the list + the KaraKeep link + slide count
```

Four pieces: one container, two model-invoked skills, and Yanto's own reasoning as
the glue. There is intentionally **no `save-carousel` orchestrator skill** — Yanto is
the orchestrator.

## Component 1 — Cobalt container (self-hosted)

- Image: `ghcr.io/imputnet/cobalt` (pin the latest stable tag at build time).
- Bind **localhost only**: `127.0.0.1:9009:9000`. No nginx, no DNS, no public route.
  UFW already blocks external ports. Only Yanto on the box calls it.
- Env: `API_URL=http://localhost:9009/`; **no** Turnstile / JWT / API key (trusted local).
- `COOKIE_PATH=/cookies.json` mounting an initially-minimal `cookies.json`, so IG/X
  cookies can be dropped in later without rework.
- `mem_limit: 512m`, `restart: unless-stopped`. (Image use case has no ffmpeg remux, so
  it idles small; cap protects the tight box.)
- Lives on the VPS at `~/cobalt/` (compose + cookies.json).

## Component 2 — `cobalt` skill (fetch building block, model-invoked)

- Call: `cobalt <url> [--out <dir>]`
- Steps:
  1. Validate host ∈ {tiktok, instagram, twitter/x}; reject others with a clear error.
  2. Self-source `COBALT_API_URL` from `~/.hermes/.env` (default `http://localhost:9009/`)
     — subprocess env caveat: skills must read `.env` themselves.
  3. `POST` `{ "url": "<url>" }` (Accept: application/json) to cobalt.
  4. Parse response: `picker` → many `{type,url}` items (+ optional `audio`); `tunnel` /
     `redirect` → single media; `error` → exit non-zero surfacing cobalt's error code.
  5. Download each item into `/tmp/cobalt-<id>/` as ordered `01.jpg, 02.jpg, …`.
  6. Print JSON: `{ source_url, host, type, images:[paths], audio, count }`.
- **Completion criterion (exhaustive):** every media item in cobalt's response is on disk
  and `count` matches. Not "some slides."
- Description (model-facing, leads with the verb):
  *"Download photos / slides / video from a TikTok, Instagram, or Twitter/X link. Use
  when the user shares such a link to fetch its media locally."*

## Component 3 — `karakeep` skill (save building block, model-invoked)

- Call: `karakeep save --url <url> [--title <t>] [--note @<file>|<text>] [--asset <path> …] [--list "<name>"] [--tag <t> …]`
- Steps:
  1. Self-source `KARAKEEP_API_KEY` + `KARAKEEP_ADDR` (default `http://localhost:3000`)
     from `~/.hermes/.env`. Auth: `Authorization: Bearer ak2_…`.
  2. `POST /api/v1/bookmarks` `{type:"link", url}` → `bookmarkId`.
  3. For each `--asset`: `POST /api/v1/assets` (multipart) → `assetId`, then attach to the
     bookmark.
  4. `PATCH /api/v1/bookmarks/{id}` `{note, title}`.
  5. If `--list`: resolve name → id via `GET /api/v1/lists`, then add the bookmark to it.
  6. Print `{ bookmarkId, viewUrl }`.
- **List name resolution (matters — there are 208 lists with duplicate names):**
  - exactly one match → use it.
  - zero matches → exit with "list not found" (Yanto asks before creating; never save into
    a typo'd folder).
  - multiple matches → exit listing the candidates (Yanto disambiguates / asks).
  - (`Watch` and `Perfume` are unique, so the canonical use cases resolve cleanly.)
- **Completion criterion:** bookmark created; all assets uploaded + attached (count matches);
  note + title set; added to the requested list; viewUrl printed.
- Description: *"Save / bookmark / archive a link with optional images and a note to
  KaraKeep, into a named folder. Use when the user wants to save or remember content."*

### Verify during implementation (not assumptions)

- **Asset display:** exactly how attached image assets render on a `link` bookmark vs
  embedding asset URLs inline in the note markdown. Both archive the images; pick whichever
  shows the slides best in this KaraKeep fork.
- **List add endpoint:** confirm the exact verb/path for adding an existing bookmark to a
  list (e.g. `PUT /api/v1/lists/{listId}/bookmarks/{bookmarkId}`) against the fork's OpenAPI.

## Component 4 — Yanto orchestration (no skill)

Yanto handles the conversational flow using the two skills + its vision. The note format
(default, adjustable):

```
<one-line summary of what this carousel is>

- **<item name>** — <key details: price / notes as shown on the slide>
- **<item name>** — …

_Source caption: <original post caption if cobalt returns it>_
```

Faithful to the slides; no invented items. KaraKeep's own AI tagging adds tags. If the flow
ever proves unreliable (e.g. Yanto skips slides or forgets to save), revisit adding a thin
orchestrator skill — out of scope for v1.

## Platform scope (v1)

| Link | Path | v1 reliability |
|---|---|---|
| TikTok | cobalt | Solid (primary use case) |
| Instagram | cobalt (best-effort) | Best-effort; needs `cookies.json` for reliable access from the VPS — deferred |
| Twitter/X | RSSHub-first → cobalt fallback | Best-effort; see below |

**Twitter/X reality:** RSSHub-X auth was fixed this session (2 burner tokens in
`~/rsshub/.env`, multi-token rotation; was 401, now 200) but X rate-limits the datacenter IP
(200 with `429` body, thin/empty feeds), and RSSHub only serves user *timelines*, not single
tweets. So for a single tweet link, **cobalt is the de-facto path**; the RSSHub-first branch
is a self-healing nicety. Levers to make X solid later: residential proxy for RSSHub, or an
X `cookies.json` for cobalt.

## Configuration / secrets (all on the VPS, never synced)

- `~/.hermes/.env`: `KARAKEEP_API_KEY` (validated), `KARAKEEP_ADDR=http://localhost:3000`,
  `COBALT_API_URL=http://localhost:9009/`. Skills self-source these.
- `~/rsshub/.env`: `TWITTER_AUTH_TOKEN` (2 tokens, comma-separated) — done this session.
- `~/cobalt/cookies.json`: minimal/empty initially; add IG/X cookies later.

## Error handling

- Fetch yields 0 images (private / region-locked / age-gated) → Yanto reports it could not
  grab the post; does **not** save an empty bookmark.
- `--list` not found / ambiguous → Yanto asks before proceeding.
- Asset upload failure → report which slide failed; bookmark + note still saved.
- RSSHub timeout / non-200 / no media → fall through to cobalt automatically.

## Testing (integration-style, against live services)

- `cobalt` skill: known public TikTok carousel (expect N images on disk); single TikTok video
  (1 file); bad host (clean error).
- `karakeep` skill: create a bookmark + attach an asset + add to a **throwaway test list**
  (avoid polluting real folders); verify in the UI; then delete the test bookmark/list.
- End-to-end: one real run through Yanto with a TikTok carousel into the `Watch` folder;
  confirm images + note land in the right folder and the chat reply is correct.

## Where the code lives

- **Dev home (Mac):** `~/Documents/Projects/Hermes/cobalt/` (this spec is under `docs/specs/`).
  Holds the cobalt compose, the two skill sources, and a deploy script.
- **VPS (runtime):** cobalt at `~/cobalt/`; skills at `~/.agents/skills/{cobalt,karakeep}/`.
  Per the VPS-runtime rule, the build/deploy is done VPS-side; skill sources mirror into
  dotfiles `vps/agents/skills/` on `sync.sh`.

## Out of scope / follow-ups

- IG and X `cookies.json` for cobalt (deferred; wiring is ready via `COOKIE_PATH`).
- RSSHub-X rate-limit mitigation (residential proxy) — inherent to datacenter IP.
- A thin orchestrator skill, only if conversational orchestration proves unreliable.
- `sync.sh` update for the `Hermes-cron(s)` → `Hermes` dev-dir rename (tracked separately).
- Extending to other carousel sources later reuses the same two building-block skills.
```
