# Bursawatch launch video

A 60-second, 1920x1080, 60 fps launch film built with HyperFrames. The creative
contract lives in `BRIEF.md` (intent and beat sheet), `frame.md` (visual rules
and palette), and `STORYBOARD.md` (locked frame-by-frame timings).

## Requirements

- Node with `npx`. Prefix with `mise exec --` if `npx` is not found.
- Python 3. The build tools use the standard library only.
- The HyperFrames CLI is pinned to `0.8.104`. Ignore the CLI's update notice.

Run every command from this `launch-video/` directory. Running from the
repository root fails with "No composition found".

## Preview in Studio

```bash
npx --yes hyperframes@0.8.104 preview --background   # start Studio
npx --yes hyperframes@0.8.104 preview --status       # show its URL
npx --yes hyperframes@0.8.104 preview --stop         # stop it
```

Studio rewrites the project HTML while it runs (it adds `data-hf-id` and
lowercases SVG tags such as `feGaussianBlur`, which breaks the blur and
gradients). Never commit those rewrites. After a Studio session, restore the
generated files with either:

```bash
git restore .
python3 tools/build_scenes.py && python3 tools/sfx_plan.py
```

## Edit, build, check

The scene sources are `scenes-src/*.html.tpl`. Studio ignores `.tpl`, so the
sources stay intact. `compositions/*.html` are generated; do not edit them.

```bash
python3 tools/build_scenes.py      # scenes-src -> compositions
python3 tools/sfx_plan.py          # writes the SFX block into index.html
python3 tools/storyboard_sheet.py  # regenerates storyboard.html
npx --yes hyperframes@0.8.104 check
npx --yes hyperframes@0.8.104 snapshot --at 12.5 --no-end
```

`check` runs lint, runtime, layout, motion, and contrast audits. The remaining
contrast warnings on `#s5-vt0` and `#s5-vt1` are transient hidden ticker words.

## Render

```bash
npx --yes hyperframes@0.8.104 render
```

Output goes to `renders/`, which is ignored by Git.

## Layout

| Path | Contents |
|---|---|
| `index.html` | Root timeline, scene order, music bed, and generated SFX block |
| `scenes-src/` | Scene sources s1 to s7 (edit these) |
| `compositions/` | Generated scenes (do not edit) |
| `tools/` | Build scripts and the realistic post components (`social.py`) |
| `assets/` | Fonts, brand, music, SFX, and the real screenshots used on screen |
| `research/` | Reference study, IHSG, TRUE, and KETR price series, and the music beat grid |

The music bed is `assets/music/bgm-60.m4a`, cut to exactly 60 s at about
-14 LUFS. The drop lands at 16.22 s and the last kick at 57.29 s; scene timings
are locked to that beat grid (`research/audiomap-v1.json`).

## Local-only material

These stay out of Git and are not needed to build or render the film:

- `assets/discord-media/` and `assets/discord-ref/`: raw Discord pulls and
  reference screenshots. `storyboard.html` shows some of them, so the
  storyboard sheet renders with gaps without them.
- `research/h-*.json`: raw Discord message exports.
- `renders/`, `snapshots/`, and the HyperFrames caches.
