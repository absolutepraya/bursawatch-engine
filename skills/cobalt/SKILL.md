---
name: cobalt
description: Download photos, slides, or video from a TikTok, Instagram, or Twitter/X link. Use when the user shares such a link and you need its media files locally (e.g. to read carousel slides or archive a post).
---

# cobalt — fetch a social post's media

Downloads media from one TikTok / Instagram / Twitter(X) URL and prints JSON
describing what it saved. Routes by host:

- **TikTok** → tikwm.com API (handles photo-mode carousels + video; no auth).
- **Instagram / Twitter(X)** → the self-hosted cobalt instance (best-effort; needs
  cookies in cobalt's `cookies.json` for reliable IG/X access).

## Usage

    cobalt <url> [--out <dir>]

## Output (stdout JSON)

    {"source_url":"…","host":"tiktok","type":"carousel","caption":"…","images":["/tmp/cobalt-…/01.jpg", …],"audio":null,"count":6}

- `type` is `carousel` (multiple slides) or `single`.
- `caption` is the post caption when available (TikTok title) — useful for the note.
- `images` are absolute paths; read each one (vision) to extract content.
- Exits non-zero with `cobalt: <reason>` on unsupported host, API error, or download failure.

## Notes

- TikTok works without cookies. Instagram/X are best-effort until cookies are added to cobalt.
- Reads `COBALT_API_URL` from `~/.hermes/.env` (default `http://localhost:9009/`); TikTok uses `TIKWM_API` (default `https://www.tikwm.com/api/`).
