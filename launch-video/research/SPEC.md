# Reference frame study

Measured from frame-by-frame extraction (frame differencing for cuts, dense
contact sheets, cropped per-frame strips). Frame numbers are at the source
rate (refs 1 to 3: 60fps, ref 4: 30fps). Our film is 60fps, so ref 4 values
double.

The frames are the truth. Where these notes and the frames disagree, re-measure.

## Ref 1, Clay "Monitor leads signal" (7.6s, 1920x1080, light)

One continuous shot, no hard cuts (no frame-difference spike above 6x median).

### Card wall (0.0 to 3.7s)
- Social cards enter one by one from the **left**, travelling horizontally
  about 1 card width. Entry measured on one card: first faint frame at f12,
  settled at f24 (12 frames, 0.2s). Fast start, soft landing.
- Horizontal motion blur during travel, gone by the settle frame. Slight
  perspective skew while moving, flat at rest.
- Opacity rises from ~0 to 1 over the first ~5 frames of travel.
- Staggered arrivals: a new card roughly every 3 to 6 frames across the frame;
  rows build top band first, then bottom band, leaving a clear middle band for
  the headline.
- Cards: white, ~240x110 at 1080p, 6px radius, soft shadow; tiny unreadable
  text is fine (texture). A few have a highlighted blue link bar.

### Headline (0.28 to 3.7s)
- Monospace sans, ~60px at 1080p, near-black on off-white #F1F1EF.
- **Word-by-word mask rise**: each word rises from below its baseline inside a
  clip mask. Measured: "Your" 4 to 5 frames, "leads" 7 frames (f5 to f12),
  ease-out, slight vertical overshoot none.
- Word cadence is speech-like, not even: Your 0.28s, leads 0.37s, are 0.80s,
  everywhere 1.45s.
- Lines are laid out at their final centered positions from the start; a word
  appears in its final slot.
- Accent word in green (#1C8A5A), entering the same way.
- **Marker highlight** sweeps left to right behind the accent word starting
  ~0.35s after the word lands: 8 frames at 30fps (~0.27s), ease-out, pale
  yellow with a soft leading edge, then holds.

### Fade to doubt (3.7 to 5.2s)
- Headline and wall fade together over ~6 frames; the wall drops to ~15%
  opacity and blurs (ghost layer that stays).
- "You just don't know." enters word by word (same mask rise), holds 1.0s.

### Introducing (5.2 to 7.6s)
- Line fades with slight blur (~6 frames).
- Tiny mono label "Introducing" (~14px) appears above center first (f+6).
- Logo glyph pops (starts as a small dot, scales up), then "Claude" and "for"
  rise word by word; second line icon + "Monitor leads signal" in accent green
  rises with entry blur, ~0.3s after line 1.
- **Ripple rings**: thin accent-tinted concentric circles expand from the
  second-line icon, large radius (past frame edges), low opacity, 0.8s per
  ring, 2 to 3 rings staggered; the radar icon sweep keeps rotating.

## Ref 2, Overlay (24s, 1440x1440, light)

One headline + one card per idea; the card **morphs** between states.

- Morph (measured 1.7 to 2.7s): the previous object (black circle button)
  blurs out, then a rounded rect grows from it with heavy blur and grey fill,
  lightening to white and sharpening over ~10 frames at 30fps (0.33s).
- Headline swap: old line fades and blurs (~4 frames), new line enters blurred
  and slightly offset, sharpens over ~4 frames. It overlaps the card morph.
- Card contents (chips, rows) enter **staggered with blur-to-sharp**, ~8 frames
  apart, small upward drift.
- Cursor (macOS arrow) drives toggles and tabs; a toggle flips in ~6 frames
  with a spring.
- Holds are long (1.5 to 2.5s); only one thing changes at a time.
- Medium-weight sans headline (~34px at 1440 square), centered above the card.

## Ref 3, mtioon (15s, 1920x1080, light, bouncy)

Used only for the burst structure; its arcade palette and music are excluded.

- Center object (folder) **scales up from ~35% with a small overshoot**: f0 to
  f5 at 30fps (0.17s), settles by f7.
- Chips **pop out from behind the object's top edge**: each starts tiny and
  rotated, flies outward to its parking spot while scaling to 100% over ~6
  frames at 30fps (0.2s), ends tilted -8 to +8 degrees.
- Chip stagger ~6 to 7 frames at 30fps (~0.22s). The object squashes and
  rebounds slightly on each launch (reaction).
- Parked chips keep a slow drift.
- Exit: the object zooms toward camera with blur and fades (5 frames) as the
  next big headline scales down into place (zoom-through).

## Ref 4, opencode 2 (48s, 1280x720, dark)

- Feature captions bottom-left, ~6% from left edge, ~80% down. Monospace bold.
  First word in the accent colour (copper/orange), rest white.
- **Typed caption**: about 2 characters per frame at 15fps (~30 chars/s) with a
  copper block caret; caret keeps blinking on hold. A second caption line types
  under the first for the payoff ("steer it now. / or queue it for later.").
- Transition between features: the previous visual collapses into a thin
  copper line or block, which then expands into the next feature's UI.
- Product UI is real (TUI), dark, dense, with copper as the only accent.
- Features last 3 to 5s each; captions hold while the UI performs.

## What we keep and what we change

KEEP (timing and staging):
- Ref 1: card entries (12 frames, horizontal blur), word mask rise (5 to 7
  frames), speech-like word cadence, marker sweep (~16 frames at 60fps), wall
  ghosting to ~15%, small label then logo then two-line lockup, ripple rings.
- Ref 2: one question + one morphing card, blur-to-sharp morph (~20 frames at
  60fps), staggered contents, long holds, cursor-driven toggles.
- Ref 3: center pop with overshoot (~10 frames at 60fps), chips launched from
  behind with rotation, ~13 frame stagger, object squash reaction, zoom-through
  exit.
- Ref 4: bottom-left mono caption typing at ~30 chars/s with a copper caret,
  copper first word, real product UI performing above.

CHANGE (ours):
- Dark Bursawatch palette instead of light; copper #DEA777 replaces green,
  yellow, and orange accents. The ref 1 marker becomes a copper-tinted marker.
- Hanken Grotesk / Geist Mono instead of the references' fonts.
- Real Bursawatch Discord content, source logos, and charts.
- Casual Indonesian copy.
