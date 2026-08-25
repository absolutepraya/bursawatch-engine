# Hermes Agent portfolio preview design

## Decision

Create a short looping video for the Hermes Agent portfolio card, not a static image.

The portfolio preview area is 10:7 and videos autoplay muted when their card enters view. A compact, composed loop can show Hermes as continuously operating while remaining understandable from any single frame. The fallback frame must work as a static poster.

The selected creative direction is **Command Center Pulse**: one central Hermes agent, backed by a real dashboard overview and a real market-monitor surface. Telegram, Discord, and WhatsApp are small supporting endpoints.

## Objectives

A recruiter or technical collaborator should understand, within one second:

1. Hermes is a single personal AI agent.
2. It operates across Telegram, Discord, and WhatsApp.
3. It runs useful scheduled financial workflows continuously.
4. It has a real operational dashboard.
5. Its actions are controlled, without making the asset look like a security infographic.

The preview must feel premium, calm, operational, and personal. It must remain legible around 700px wide and substantially smaller.

## Why video wins

A static image could combine a dashboard crop, chart, and channel marks, but it would struggle to express ongoing operation without becoming a dense collage. The card already plays muted looping video only while visible, so an eight-second loop is appropriate.

The video is not a product tour or screen recording. It is a composed systems portrait assembled from two authentic, brief screen recordings and clean stills. Frame 0 is also the fallback poster, so the concept survives autoplay failure, motion reduction, and a brief glance.

## Creative directions explored

### 1. Command Center Pulse, selected

**Metaphor:** a centered personal agent sits inside an operating command center. Real dashboard and market-monitor surfaces form an asymmetric two-plane composition around it.

**First second:** a central Hermes `H` tile, a large real dashboard overview, and a readable market-chart crop are already present. The channel row is visible but subordinate.

**Representation:**

- Telegram, Discord, WhatsApp: a small aligned endpoint row, using normalized official marks.
- Dashboard: large authentic overview crop, at the upper-left through center.
- Cron activity: three abstract timeline ticks and one restrained activity pulse. No fixed schedule or cron-name text in the card.
- Market intelligence: a real Hermes-generated or Hermes-consumed chart, cropped to price action, EMA 50, EMA 200, and volume.
- Trust and controlled action: Hermes remains visually bounded by the dashboard surface. The design does not use locks, shields, or security-copy overlays.

**Small-card risk:** the dashboard and chart can compete. The dashboard remains largest, and the chart is shown only as one secondary surface.

### 2. Conversation Orbit

**Metaphor:** messenger channels orbit a personal agent, with market intelligence appearing as one of the agent's outputs.

**First second:** an `H` mark with three surrounding channel marks.

**Representation:** the dashboard becomes a small background layer, and market intelligence appears as a compact output card.

**Small-card risk:** this can look like a generic chat assistant or messenger aggregation product before it reads as operational automation.

### 3. Cron Ribbon

**Metaphor:** a precise schedule runs through the frame, showing Hermes as a financial-automation system.

**First second:** a schedule ribbon with visible activity ticks and a smaller dashboard.

**Representation:** scheduled work is primary, with the Hermes mark and channels supporting it.

**Small-card risk:** it communicates automation well but weakens the personal multi-channel agent story.

## Chosen format

### Composition and output

- Canvas: `1600 × 1120`, exact 10:7, so the portfolio card requires no `object-cover` crop.
- Duration: 8 seconds, 240 frames at 30fps.
- Output: optimized H.264 MP4, muted, `yuv420p`.
- Fallback: frame 0 exported as a WebP poster.
- The opening and final frames use the same composed poster state for a seamless repeat.

### 8-second storyboard

| Time | Visual | Purpose |
|---|---|---|
| 0.0 to 0.7s | Stable poster frame: Hermes tile centered, dashboard overview upper-left through center, market chart lower-right, channel row lower-left. | Immediate comprehension. |
| 0.7 to 1.8s | Dashboard clip activates inside its rounded mask. It receives a slow 1.02 scale and no more than 10px drift. One faint blurple activity line resolves toward Hermes. | Establish that the dashboard is real and live. |
| 1.8 to 3.0s | Telegram, Discord, and WhatsApp marks individually rise 6px into their resting row and receive one soft pulse. | Establish multi-channel availability without simulating conversation. |
| 3.0 to 4.9s | Market-monitor clip becomes the focus. The chart rises slightly in its own reserved space and receives one scan-line pass. Three abstract timeline ticks briefly resolve behind Hermes. | Establish scheduled financial intelligence. |
| 4.9 to 6.3s | Chart returns to secondary scale. Dashboard becomes slightly more prominent again. Hermes stays central and visually inside the operational dashboard boundary. | Imply controlled operation without security decoration. |
| 6.3 to 8.0s | Channel marks dim to resting opacity. Both clips resolve to their source stills. The activity line fades. | Return exactly to the poster frame. |

## Visual hierarchy

### Must be large and immediately readable

1. Central Hermes tile, using a simple `H` monogram if no established Hermes mark is provided.
2. Real dashboard overview, the largest external surface.
3. Real market-chart shape, not small surrounding UI text.

### Secondary

1. A single market-monitor card containing the chart and one contextual status region.
2. Telegram, Discord, WhatsApp marks, same size and in one row.
3. Three abstract activity ticks.

### Omit

- Chat transcript UI and fabricated messages.
- Terminal walls, source code, MCP tool inventories, or fake metrics.
- Visible cron names and hard-coded schedules.
- Network diagrams, floating nodes, robots, brains, cyberpunk treatment, locks, or security badges.
- Excess dashboard text, headline copy, and feature lists.

## Style system

### Palette

- Base: portfolio near-black `#03020F`.
- Accent: portfolio blurple `#3643FC`.
- Highlight: muted lavender-blue around `#AAB2FF`.
- Surface colors: sampled from the actual Hermes dashboard capture.
- Market colors: preserve the real chart. Do not add a generic red-green trading palette.

### Typography

- Inter for the minimal Hermes label.
- JetBrains Mono for any small operational labels.
- No Instrument Serif in the video. This is a technical operational surface, not editorial content.

### Compositing and depth

- Two real-interface cards at different depth planes, with thin cool borders, restrained shadows, and a diffuse blurple bloom behind the Hermes tile.
- Use normal layout slots for readable content. Absolute positioning is reserved for background glow, masks, and minor decorative layers.
- Real clips are cropped inside rounded masks. Animate the masks and camera position rather than faking interaction or screen recording behavior.

### Motion

- Use `interpolate()` with `Easing.bezier(0.16, 1, 0.3, 1)` for entrances and exits.
- No CSS transitions or animation classes in Remotion.
- No bouncy springs.
- Background motion stays below 12px. Card-layer scale changes remain around 1.00 to 1.02.
- The design uses only one focal change at a time.

### Chart treatment

Prefer a real Hermes chart with `EMA:50,EMA:200,Volume`, within the chart service's three-study cap. EMA 50 and EMA 200 support the DCA monitoring story at small size more directly than an RSI pane. Preserve the actual candle and volume data. The only added movement is a single low-opacity scan-line or focus pass.

## Current VPS grounding

This design is grounded in the deployed VPS runtime checked on 2026-07-17 at 14:08 WIB:

- Deployed skills include `chart`, `us-etf-dca-watch`, `idx-ca-watch`, `polymarket-signal-watch`, `idx-swing-watch-phintraco-daily`, and `idx-ssf-watch-phintraco-weekly`.
- The live schedule registry lists six enabled jobs. At inspection, all recorded `last_status: ok`.
- Market operations include US ETF DCA monitoring, hourly IDX corporate-action monitoring, five-minute Polymarket monitoring, minutely IDX daily swing monitoring, and 30-minute IDX SSF monitoring.
- The live ETF watcher directly produces chart-backed alerts using the deployed chart skill.
- The chart skill supports exchange-aware symbols, daily and intraday intervals, and at most three studies.

Do not place these exact frequencies or job names in the card. They may change. The preview should show an abstract living schedule and use the real dashboard capture as proof.

## Required inputs

| Asset | Requirement |
|---|---|
| `hermes-dashboard-overview.mp4` | 5 to 7 seconds, dashboard overview with agent health and scheduled-job or cron activity visible. Record at least 1440px wide, with browser chrome excluded. One intentional scroll or navigation movement maximum. |
| `hermes-market-monitor.mp4` | 5 to 7 seconds, real Hermes market monitor or genuine Hermes chart surface. Keep chart large. No typing, selection, or cursor hunting. |
| `hermes-dashboard-poster.webp` | Clean still from the dashboard clip for frame 0, video poster, and fallback. |
| `hermes-market-chart.webp` | Clean still from the market clip, cropped to chart and one contextual status region. |
| Telegram, Discord, WhatsApp marks | Local official or established SVG marks. Normalize all three to the same small endpoint treatment. |
| Hermes mark, optional | Existing mark if available. Otherwise create the simple `H` monogram for the central tile. |

The user has said full dashboard cleanup is unnecessary. The capture must nevertheless exclude credentials, API keys, session IDs, and unrelated personal conversation content. This is a recording boundary, not a request to fabricate or sanitize product behavior.

## Remotion production structure

```text
Portfolio/
  remotion/hermes-agent-preview/     # Remotion composition, scene components, source captures
  src/assets/projects/
    hermes-agent.mp4                 # rendered looping preview
    hermes-agent.webp                # poster and reduced-motion fallback
```

The card's Hermes project record receives the MP4 as its preview and enables video playback. The card component gains an explicit static fallback path for its `poster`, reduced-motion behavior, and media-load failure handling.

## Production behavior and failure handling

- Portfolio card: video remains muted, loops, and uses `playsInline`, consistent with current project cards.
- Before playback: show the WebP poster.
- Reduced motion: do not start playback. Keep the WebP poster visible.
- Video load failure: retain the same WebP rather than showing an empty or fake substitute.
- If an input clip is unavailable or unusable: block the render and request the real replacement asset. Do not simulate the missing surface.

## Verification

1. Render frame 0, frame 30, the market-focus frame, and frame 239. Frame 0 and frame 239 must compose as the same poster state.
2. Inspect the card preview around 700px wide and at the actual portfolio-card size. The Hermes tile, dashboard, and chart must be identifiable without reading tiny text.
3. In the portfolio browser path, verify that entering the viewport starts muted playback and leaving pauses it.
4. Verify that the WebP poster displays before metadata loads, with reduced motion, and after a media error.
5. Run `bun run check` and `bun run knip` in the Portfolio repository after implementation.

## Scope boundaries

In scope: one polished Hermes preview loop, its static fallback, the minimal portfolio-card integration required to render both correctly, and real capture guidance.

Out of scope: redesigning Hermes, creating a Hermes logo system, changing dashboard behavior, adding live data fetching to the portfolio, or altering existing Hermes cron schedules and delivery behavior.
