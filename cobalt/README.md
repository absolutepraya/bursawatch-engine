# Cobalt media service (Yanto)

Cobalt supports Yanto's social-media extraction workflow. TikTok and Instagram work out of
the box; X is best-effort. The independent shared `karakeep` skill can consume extracted
media when a user asks to save it as a bookmark.

## Pieces
- `compose/` - self-hosted cobalt container (VPS `~/cobalt/`, `localhost:9009`, mem 512m). Serves Instagram + X.
- `skills/media/` - fetch a post's media: TikTok via tikwm.com, Instagram/X via cobalt. Prints JSON (image paths + caption).
- The shared `karakeep` skill lives under `~/.agents/skills/karakeep` on each machine, not in this Cobalt project.
- Yanto can orchestrate: `media <url>` -> read images (vision) -> `karakeep save` -> reply.

## Why two fetch backends
cobalt's TikTok module is currently broken (fails for every TikTok URL, from any IP); tikwm.com
handles TikTok photo mode reliably with no auth. cobalt still serves Instagram + X. If cobalt
fixes TikTok upstream, point the `media` skill's TikTok branch back at it.

## Platform status
- **TikTok** - solid (tikwm.com).
- **Instagram** - works for public posts via cobalt, no cookies needed (verified). Add cookies if some posts fail.
- **Twitter/X** - best-effort; add an X cookie to cobalt's `cookies.json`, or a residential proxy, to firm it up.

## Workflow
Edit here -> `./deploy.sh` -> test on the VPS (`bash ~/cobalt-tests/test-media.sh`).
Tests are integration-style; the TikTok test needs a public TikTok photo URL in `TEST_TT`.

## Config (VPS, never synced)
- `~/.hermes/.env`: `COBALT_API_URL`.
- `~/cobalt/cookies.json`: add IG/X session cookies to improve reliability.

See `docs/specs/` for the design and `docs/plans/` for the implementation plan.
