---
version: 1
name: Bursawatch launch film, frame layer
description: >
  Video-first design spec for the Bursawatch 60s launch film (1920x1080, 60fps).
  Atoms come from the approved Signal Fold identity (web-config/public/brand/
  bursawatch-signal-fold-v2-board.svg): near-black ground, one copper accent,
  Hanken Grotesk. Discord surfaces are rebuilt from the user's real Discord
  (AMOLED black theme) and keep Discord's own colours inside their frame only.
unit: the frame, 1920x1080
principle: one copper accent · one typeface (Hanken Grotesk, as web-config) · product is real

colors:
  ground: "#111311"            # film background, tinted toward the brand dark
  ground-raised: "#1C1F1D"     # brand plate, cards on ground
  hairline: "#2A2E2B"
  text: "#EEEAE3"              # warm off-white, never pure white
  text-muted: "#9C978E"
  text-hint: "#5F5B55"
  copper: "#DEA777"            # the only accent (brand mark colour)
  copper-strong: "#F0BE91"
  copper-soft: "#32291F"       # marker and tint fills
  # Discord recreation only (inside a Discord frame, never on the film ground)
  discord-bg: "#000000"
  discord-panel: "#0E0F11"
  discord-card: "#121316"
  discord-text: "#DBDEE1"
  discord-muted: "#949BA4"
  discord-link: "#4A9BF5"
  discord-blurple: "#5865F2"
  discord-mention-bg: "#24264A"
  discord-bot-name: "#E4892F"  # the Bursawatch role colour in the screenshots
  price-up: "#2EE65F"
  price-down: "#F23F43"
  price-flat: "#B5B9BF"

typography:
  # narrator voice (refs 1 and 4): Hanken Grotesk, matching web-config (its only typeface)
  voice-xl:  { fontFamily: "Hanken Grotesk", px: 76, weight: 500, lineHeight: 1.15, tracking: "-0.02em" }
  voice-lg:  { fontFamily: "Hanken Grotesk", px: 60, weight: 500, lineHeight: 1.2, tracking: "-0.02em" }
  caption:   { fontFamily: "Hanken Grotesk", px: 34, weight: 700, lineHeight: 1.35 }
  label:     { fontFamily: "Hanken Grotesk", px: 20, weight: 500, tracking: "0.08em" }
  # brand and payoff: Hanken Grotesk (from the identity board)
  wordmark:  { fontFamily: "Hanken Grotesk", px: 132, weight: 700, tracking: "-0.035em" }
  display:   { fontFamily: "Hanken Grotesk", px: 120, weight: 900, lineHeight: 0.95, tracking: "-0.04em" }
  headline:  { fontFamily: "Hanken Grotesk", px: 64, weight: 700, lineHeight: 1.1, tracking: "-0.03em" }
  stat:      { fontFamily: "Hanken Grotesk", px: 56, weight: 800, tracking: "-0.03em", features: "tnum" }
  # Discord UI substitute (gg sans is not embeddable)
  ui-title:  { fontFamily: "Figtree", weight: 800 }
  ui-body:   { fontFamily: "Figtree", weight: 400 }
  ui-strong: { fontFamily: "Figtree", weight: 700 }

fonts:
  - assets/fonts/HankenGrotesk-*.woff2 (OFL, Google Fonts)
  - assets/fonts/Figtree-*.woff2 (OFL, Google Fonts)

spacing:
  pad-x: 120px
  pad-y: 96px
  caption-x: 116px      # ref 4 caption anchor, ~6% from left
  caption-y: 862px      # ref 4 caption baseline zone, ~80% down
  gap-lg: 64px
  gap-md: 32px
  gap-sm: 16px

radii:
  card: 14px
  chip: 999px
  discord-embed: 8px
  media: 12px

components:
  source-card:
    surface: "{colors.discord-card} with 1px {colors.hairline}"
    content: "real source avatar (emoji) 40px + name + title line + 2 lines of summary + optional price block"
    rule: "only title, source, and price block need to read; summary is texture"
  avatar-badge:
    size: "30% of avatar, bottom-right, 2px {colors.ground} ring"
    x: "X logo (assets/sources/emoji/twitter.png)"
    instagram: "Instagram glyph (assets/sources/emoji/instagram.png) on dummy AI faces"
  price-block:
    label: "Harga terakhir (IDR): **N**"
    rows: "1D / 1W / 1M / 3M with green/red/grey dot emoji, bold values"
    source: "Tuntun format in #id-stocks-news; applied to every news card in the film"
  channel-chip:
    shape: "pill, {colors.ground-raised}, 2px {colors.hairline}, '#' in {colors.copper}"
    typography: "{typography.headline} at 40px, weight 700"
  caption-rail:
    placement: "{spacing.caption-x}, {spacing.caption-y}"
    typography: "{typography.caption}; first word {colors.copper}, rest {colors.text}"
    caret: "copper block, blinks on hold"
  marker:
    fill: "{colors.copper} at 28% opacity behind the word, word itself {colors.copper-strong}"
  bisa-stamp:
    typography: "{typography.display} 'BISA.' in {colors.copper}"

## Overview

The film is a narrator (calm, a little cheeky) talking over real product.
Dark, quiet ground; the copper accent appears once per frame on the focal
element. Discord content sits on true black inside its own frame so it reads
as the real app.

## Do

- Real Discord messages, real source logos, real charts (assets/discord-media).
- One focal point per frame; copper marks it.
- Hanken Grotesk for everything we say (web-config uses it as its only
  typeface): medium weight for the narrator, heavy weights for the brand,
  BISA, stats, and the verdict. Figtree appears only inside Discord frames.
- Every news card carries the price block.

## Don't

- No gradients across the ground (banding); use flat ground plus a local
  radial copper glow at 12 to 18% when a scene needs depth.
- No glow on text, no particle bursts, no everything-fades-in.
- No pure #000 on the film ground (only inside Discord frames) and no pure #fff.
- No em dashes in copy.
- No fake Bursawatch UI: Discord frames are rebuilt from the real messages.
