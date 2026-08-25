# Hermes Agent portfolio preview implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render a real-interface, eight-second Hermes Agent loop and integrate it into the Portfolio project with a static reduced-motion and error fallback.

**Architecture:** Remotion lives under the Portfolio repository as a dedicated source directory and renders two supplied real recordings plus still images into a single MP4 and WebP. The existing `ProjectBox` remains responsible for in-view playback, but gains an explicit poster, media-error fallback, and motion-preference branch. The Hermes project record is the only portfolio data entry that changes.

**Tech Stack:** Bun, TypeScript, React 18, Remotion (`remotion`, `@remotion/cli`, `@remotion/media`), Vite, Tailwind CSS, Biome.

## Global Constraints

- Canvas is exactly `1600 × 1120`, 30fps, 240 frames, and output is H.264 MP4 with `yuv420p`.
- Use only real dashboard and market-monitor recordings supplied by the user. Never simulate chat, metrics, cron names, or dashboard activity.
- Frame 0 and frame 239 must be visually identical poster states.
- Keep the Hermes tile, dashboard surface, and chart readable at 700px wide and at native card size.
- Preserve the existing portfolio video behavior: muted, looped, inline, and played only while in viewport.
- Render WebP frame 0 as the poster, reduced-motion fallback, and media-error fallback.
- Use `interpolate()` and `Easing.bezier(0.16, 1, 0.3, 1)` in Remotion. Do not use CSS transitions, animation classes, or bouncy springs.
- Do not alter Hermes dashboard behavior, cron schedules, delivery channels, or live state.
- Run `bun run check` and `bun run knip` after every edited implementation turn, per the Portfolio project rules.
- **Execution sequencing:** source captures are explicitly deferred until the user supplies them. Build the Remotion dependency setup and composition now, but do not render, add preview assets, or modify the portfolio card until the authentic inputs arrive.

---

## File map

| Path | Responsibility |
|---|---|
| `Portfolio/package.json` | Pins Remotion packages and exposes reproducible Studio, MP4, and still render commands. |
| `Portfolio/remotion/hermes-agent-preview/src/index.ts` | Registers the Remotion root. |
| `Portfolio/remotion/hermes-agent-preview/src/Root.tsx` | Registers the fixed Hermes composition. |
| `Portfolio/remotion/hermes-agent-preview/src/HermesAgentPreview.tsx` | Renders the poster state, authentic interface crops, timing, channel row, and restrained decorative motion. |
| `Portfolio/remotion/hermes-agent-preview/remotion.config.ts` | Sets `yuv420p` as the default render pixel format. |
| `Portfolio/remotion/hermes-agent-preview/public/` | Holds only user-supplied capture inputs and official channel marks used by Remotion. |
| `Portfolio/src/assets/projects/hermes-agent.mp4` | Rendered card preview imported by Vite. |
| `Portfolio/src/assets/projects/hermes-agent.webp` | Frame-0 poster imported by Vite. |
| `Portfolio/src/data/projects_data.ts` | Imports the rendered Hermes assets and declares its poster. |
| `Portfolio/src/components/Projects/ProjectBox.tsx` | Uses a project poster before metadata loads, for reduced motion, and on MP4 errors. |

## Task 1: Install the renderer and ingest authentic assets

**Files:**
- Modify: `Portfolio/package.json`
- Create: `Portfolio/remotion/hermes-agent-preview/public/dashboard-overview.mp4`
- Create: `Portfolio/remotion/hermes-agent-preview/public/market-monitor.mp4`
- Create: `Portfolio/remotion/hermes-agent-preview/public/dashboard-poster.webp`
- Create: `Portfolio/remotion/hermes-agent-preview/public/market-chart.webp`
- Create: `Portfolio/remotion/hermes-agent-preview/public/telegram.svg`
- Create: `Portfolio/remotion/hermes-agent-preview/public/discord.svg`
- Create: `Portfolio/remotion/hermes-agent-preview/public/whatsapp.svg`

**Interfaces:**
- Consumes: user-provided real clips, stills, and local SVG marks.
- Produces: static file names consumed by `HermesAgentPreview` in Task 2.

- [ ] **Step 1: Record and name the two real clips before copying them into the repository.**

Record at least 1440px wide, with browser chrome excluded:

```text
Dashboard overview clip, 5 to 7 seconds:
Open Hermes overview with agent health and scheduled job or cron activity visible.
Make at most one intentional scroll or navigation move.

Market monitor clip, 5 to 7 seconds:
Open a real Hermes market-monitor surface or Hermes-produced chart.
Keep the chart large. Do not type, select text, or hunt with the cursor.
```

Capture `dashboard-poster.webp` from the clean overview state and `market-chart.webp` from the clean chart state. Do not include credentials, API keys, session IDs, or unrelated personal conversation content.

- [ ] **Step 2: Verify both input clips before installing or writing rendering code.**

Run:

```bash
cd ~/Documents/Projects/Portfolio
for asset in \
  remotion/hermes-agent-preview/public/dashboard-overview.mp4 \
  remotion/hermes-agent-preview/public/market-monitor.mp4; do
  ffprobe -v error \
    -show_entries stream=codec_type,width,height \
    -show_entries format=duration \
    -of default=noprint_wrappers=1 \
    "$asset"
done
```

Expected: each file reports a `video` stream, width of at least 1440px, and duration from 5.0 through 7.0 seconds. If either fails, replace the capture rather than stretching, looping, or fabricating it.

- [ ] **Step 3: Add matched Remotion dependencies and scripts.**

Run:

```bash
bun add -d remotion @remotion/cli @remotion/media
```

Add the following scripts to `package.json`:

```json
{
  "remotion:studio": "remotion studio remotion/hermes-agent-preview/src/index.ts",
  "remotion:render-hermes": "remotion render remotion/hermes-agent-preview/src/index.ts HermesAgentPreview src/assets/projects/hermes-agent.mp4 --codec=h264 --pixel-format=yuv420p",
  "remotion:still-hermes": "remotion still remotion/hermes-agent-preview/src/index.ts HermesAgentPreview src/assets/projects/hermes-agent.webp --frame=0 --image-format=webp"
}
```

- [ ] **Step 4: Confirm the renderer can discover its entry point after Task 2 adds it.**

Run:

```bash
bunx remotion compositions remotion/hermes-agent-preview/src/index.ts
```

Expected after Task 2: exactly one composition named `HermesAgentPreview`, at `1600x1120`, 30fps, 240 frames.

- [ ] **Step 5: Commit the setup and authentic source assets.**

```bash
git add package.json bun.lock remotion/hermes-agent-preview/public
git commit -m "build: add Hermes preview render inputs"
```

## Task 2: Build the deterministic Remotion composition

**Files:**
- Create: `Portfolio/remotion/hermes-agent-preview/src/index.ts`
- Create: `Portfolio/remotion/hermes-agent-preview/src/Root.tsx`
- Create: `Portfolio/remotion/hermes-agent-preview/src/HermesAgentPreview.tsx`
- Create: `Portfolio/remotion/hermes-agent-preview/remotion.config.ts`

**Interfaces:**
- Consumes: the eight exact public asset names from Task 1 via `staticFile()`.
- Produces: `HermesAgentPreview`, a Remotion component registered with ID `HermesAgentPreview`.

- [ ] **Step 1: Add the entry point and root registration.**

Create `src/index.ts`:

```tsx
import {registerRoot} from 'remotion';
import {RemotionRoot} from './Root';

registerRoot(RemotionRoot);
```

Create `src/Root.tsx`:

```tsx
import {Composition} from 'remotion';
import {HermesAgentPreview} from './HermesAgentPreview';

export const RemotionRoot = () => (
  <Composition
    id="HermesAgentPreview"
    component={HermesAgentPreview}
    durationInFrames={240}
    fps={30}
    width={1600}
    height={1120}
  />
);
```

Create `remotion.config.ts`:

```ts
import {Config} from '@remotion/cli/config';

Config.setPixelFormat('yuv420p');
```

- [ ] **Step 2: Add the composition with fixed layout slots and authentic media.**

Create `src/HermesAgentPreview.tsx` with these imports and constants:

```tsx
import {Img, AbsoluteFill, Easing, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {Video} from '@remotion/media';

const easeOut = Easing.bezier(0.16, 1, 0.3, 1);
const dashboardVideo = staticFile('dashboard-overview.mp4');
const marketVideo = staticFile('market-monitor.mp4');
const dashboardPoster = staticFile('dashboard-poster.webp');
const marketPoster = staticFile('market-chart.webp');
const channels = [
  {name: 'Telegram', src: staticFile('telegram.svg')},
  {name: 'Discord', src: staticFile('discord.svg')},
  {name: 'WhatsApp', src: staticFile('whatsapp.svg')},
] as const;

const transition = (frame: number, start: number, end: number) =>
  interpolate(frame, [start, end], [0, 1], {
    easing: easeOut,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
```

Use this poster-first structure. Each `<Video>` must sit above its matching `<Img>`, have no audio, and fade to zero before the last frame. The image therefore owns frame 0 and frame 239:

```tsx
const frame = useCurrentFrame();
const dashboardActivity = interpolate(frame, [21, 35, 54, 189, 207], [0, 1, 1, 1, 0], {
  easing: easeOut,
  extrapolateLeft: 'clamp',
  extrapolateRight: 'clamp',
});
const marketActivity = interpolate(frame, [90, 104, 147, 171, 189], [0, 1, 1, 1, 0], {
  easing: easeOut,
  extrapolateLeft: 'clamp',
  extrapolateRight: 'clamp',
});

const mediaFillStyle = {
  position: 'absolute' as const,
  inset: 0,
  width: '100%',
  height: '100%',
  objectFit: 'cover' as const,
};
const dashboardCardStyle = {
  position: 'absolute' as const,
  left: 110,
  top: 105,
  width: 910,
  height: 540,
  overflow: 'hidden' as const,
  borderRadius: 44,
  border: '1px solid rgba(170, 178, 255, 0.24)',
  background: '#11121a',
};
const marketCardStyle = {
  position: 'absolute' as const,
  right: 105,
  bottom: 100,
  width: 635,
  height: 390,
  overflow: 'hidden' as const,
  borderRadius: 44,
  border: '1px solid rgba(170, 178, 255, 0.24)',
  background: '#11121a',
};

<div style={dashboardCardStyle}>
  <Img src={dashboardPoster} style={mediaFillStyle} />
  <Video
    src={dashboardVideo}
    style={{
      ...mediaFillStyle,
      opacity: dashboardActivity,
      scale: 1 + dashboardActivity * 0.02,
      translate: `${dashboardActivity * -10}px ${dashboardActivity * 6}px`,
    }}
  />
</div>
<div style={marketCardStyle}>
  <Img src={marketPoster} style={mediaFillStyle} />
  <Video
    src={marketVideo}
    style={{
      ...mediaFillStyle,
      opacity: marketActivity,
      scale: 1 + marketActivity * 0.018,
      translate: `${marketActivity * 8}px ${marketActivity * -5}px`,
    }}
  />
</div>

- [ ] **Step 3: Add the central agent, channel row, and activity details without fabricated product data.**

Use a central rounded tile with only `H`, not a robot, chat transcript, count, or claim:

```tsx
<div
  style={{
    position: 'absolute',
    left: 800,
    top: 560,
    width: 190,
    height: 190,
    marginLeft: -95,
    marginTop: -95,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 52,
    color: '#ffffff',
    fontFamily: 'Inter, sans-serif',
    fontSize: 76,
    fontWeight: 700,
    background: 'linear-gradient(145deg, #6576ff, #3643fc)',
    boxShadow: '0 28px 90px rgba(54, 67, 252, 0.45), inset 0 1px rgba(255,255,255,0.38)',
  }}
>
  H
</div>
```

For each channel, calculate `arrival = transition(frame, 54 + index * 5, 72 + index * 5)` and render it in one aligned lower-left row. Use `opacity: 0.6 + arrival * 0.4` and `translate: '0px ' + (6 - arrival * 6) + 'px'`; do not animate marks around Hermes.

Render exactly three 10px timeline ticks behind the agent from frames 90 through 147. They may fade and glow, but cannot contain text, cron names, or intervals. Render one 2px blurple activity line from dashboard to Hermes between frames 21 and 54. Do not draw a network diagram.

- [ ] **Step 4: Render representative stills and correct layout before producing the MP4.**

Run:

```bash
bunx remotion still remotion/hermes-agent-preview/src/index.ts HermesAgentPreview /tmp/hermes-frame-0.webp --frame=0 --image-format=webp
bunx remotion still remotion/hermes-agent-preview/src/index.ts HermesAgentPreview /tmp/hermes-frame-30.webp --frame=30 --image-format=webp
bunx remotion still remotion/hermes-agent-preview/src/index.ts HermesAgentPreview /tmp/hermes-frame-120.webp --frame=120 --image-format=webp
bunx remotion still remotion/hermes-agent-preview/src/index.ts HermesAgentPreview /tmp/hermes-frame-239.webp --frame=239 --image-format=webp
```

Inspect each still at 700px wide. Frame 0 and frame 239 must share the same poster state. If they do not, change only the timing interpolations until the video overlays, channel arrivals, timeline ticks, and activity line all resolve back to the resting state at frame 239.

- [ ] **Step 5: Commit the composition.**

```bash
git add remotion/hermes-agent-preview/src remotion/hermes-agent-preview/remotion.config.ts
git commit -m "feat: compose Hermes agent preview"
```

## Task 3: Render distributable video and poster assets

**Files:**
- Create: `Portfolio/src/assets/projects/hermes-agent.mp4`
- Create: `Portfolio/src/assets/projects/hermes-agent.webp`

**Interfaces:**
- Consumes: `HermesAgentPreview` from Task 2.
- Produces: Vite-importable card assets used in Task 4.

- [ ] **Step 1: Render the WebP poster from frame 0.**

Run:

```bash
bun run remotion:still-hermes
```

Expected: `src/assets/projects/hermes-agent.webp` exists and matches the reviewed frame-0 composition.

- [ ] **Step 2: Render the H.264 loop.**

Run:

```bash
bun run remotion:render-hermes
```

Expected: `src/assets/projects/hermes-agent.mp4` exists, is 1600×1120, runs for 8.0 seconds at 30fps, and uses `yuv420p`.

- [ ] **Step 3: Verify encoded media properties.**

Run:

```bash
ffprobe -v error \
  -show_entries stream=codec_name,width,height,pix_fmt,r_frame_rate \
  -show_entries format=duration \
  -of default=noprint_wrappers=1 \
  src/assets/projects/hermes-agent.mp4
```

Expected: `codec_name=h264`, `width=1600`, `height=1120`, `pix_fmt=yuv420p`, `r_frame_rate=30/1`, and duration close to `8.000000`.

- [ ] **Step 4: Commit rendered deliverables.**

```bash
git add src/assets/projects/hermes-agent.mp4 src/assets/projects/hermes-agent.webp
git commit -m "feat: add Hermes portfolio preview assets"
```

## Task 4: Integrate video playback and static fallback in the portfolio card

**Files:**
- Modify: `Portfolio/src/data/projects_data.ts`
- Modify: `Portfolio/src/components/Projects/ProjectBox.tsx`
- Modify: `Portfolio/src/components/Projects/Projects.tsx`

**Interfaces:**
- Consumes: `HermesPreviewVideo` and `HermesPreviewPoster` imported from `src/assets/projects/`.
- Produces: a Hermes `Project` entry with `preview`, `poster`, and `isVideo: true`; a `ProjectBox` that preserves poster fallback for all video projects.

- [ ] **Step 1: Extend project and card props with a poster field.**

In `projects_data.ts`, add to `Project`:

```ts
poster?: string | null;
```

In `ProjectBox.tsx`, add to `ProjectBoxProps`:

```ts
poster?: string | null;
```

Destructure it with the existing preview props:

```ts
preview = null,
poster = null,
isVideo = false,
```

Pass the data field in `Projects.tsx` alongside the current video props:

```tsx
poster={project.poster}
```

- [ ] **Step 2: Make `ProjectBox` poster-first and motion-aware.**

Add state and effect after the existing video ref:

```tsx
const [videoFailed, setVideoFailed] = useState(false);
const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);

useEffect(() => {
  const media = window.matchMedia('(prefers-reduced-motion: reduce)');
  const updatePreference = () => setPrefersReducedMotion(media.matches);
  updatePreference();
  media.addEventListener('change', updatePreference);
  return () => media.removeEventListener('change', updatePreference);
}, []);
```

Change the preview branch so a video renders only when it is usable. All other paths render the poster, then current preview, then `NoImage`:

```tsx
const fallbackPreview = poster ?? preview ?? NoImage;
const shouldRenderVideo = isVideo && !prefersReducedMotion && !videoFailed;

{shouldRenderVideo ? (
  <video
    ref={videoRef}
    src={preview ?? undefined}
    poster={fallbackPreview}
    className='h-full w-full object-cover'
    muted
    loop
    playsInline
    preload='metadata'
    onError={() => setVideoFailed(true)}
  />
) : (
  <img
    src={fallbackPreview}
    className='h-full w-full object-cover'
    alt={`${title} preview`}
  />
)}
```

Update the existing IntersectionObserver effect guard to return if `prefersReducedMotion` or `videoFailed` is true, and add both values to its dependency array. This prevents `play()` from being requested once the image fallback has taken ownership of the preview.

- [ ] **Step 3: Attach the rendered Hermes asset pair to the existing Hermes record.**

At the import section of `projects_data.ts`, add:

```ts
import HermesPreviewPoster from '../assets/projects/hermes-agent.webp';
import HermesPreviewVideo from '../assets/projects/hermes-agent.mp4';
```

At the Hermes Agent object, add exactly:

```ts
preview: HermesPreviewVideo,
poster: HermesPreviewPoster,
isVideo: true,
```

Keep its title, date, subtitle, stacks, tags, URL, and GitHub fields unchanged.

- [ ] **Step 4: Verify the behavioral contract in the browser.**

Run:

```bash
bun run dev
```

At the Hermes card, verify all four states:

```text
Normal motion: poster is visible before metadata, then the MP4 plays muted once the card enters the viewport.
Leave viewport: playback pauses.
Reduced motion: the WebP remains visible and no play request occurs.
Broken MP4 test: temporarily point Hermes `preview` to a missing local MP4, load the card, then restore the correct import. The WebP remains visible after the error.
```

- [ ] **Step 5: Run the required repository validation and commit.**

Run:

```bash
bun run check
bun run knip
bun run build
```

Expected: each exits successfully. Then commit:

```bash
git add src/data/projects_data.ts src/components/Projects/ProjectBox.tsx src/components/Projects/Projects.tsx
git commit -m "feat: add Hermes project preview loop"
```

## Task 5: Review the actual product surface

**Files:**
- Verify only: `Portfolio/src/assets/projects/hermes-agent.mp4`
- Verify only: `Portfolio/src/assets/projects/hermes-agent.webp`
- Verify only: Hermes project card in the running portfolio.

**Interfaces:**
- Consumes: rendered assets and completed card fallback behavior.
- Produces: evidence that the card communicates the approved story at real display size.

- [ ] **Step 1: Check the first-second comprehension test at three sizes.**

Inspect the portfolio card at native desktop size, 700px preview width, and the narrowest responsive project-card width. Confirm all statements are true:

```text
The central H tile is readable first.
The dashboard is clearly a real operating surface.
The chart reads as financial intelligence without requiring small text.
Telegram, Discord, and WhatsApp read as a single supporting endpoint row.
No cursor, browser chrome, fake chat, fake metric, cron name, security badge, terminal wall, robot, or network-node composition appears.
```

- [ ] **Step 2: Check loop continuity.**

Watch at least three full cycles. Confirm the 8.0-second transition from frame 239 to frame 0 has no flash, card jump, opacity pop, or sudden replay of a source recording.

- [ ] **Step 3: Run final checks and commit any only required correction.**

Run:

```bash
bun run check
bun run knip
bun run build
```

If a correction is needed, modify only the responsible timing, crop, or fallback path, rerun all three commands, and commit with a focused message. If no correction is needed, do not create a no-op commit.

## Plan self-review

- **Spec coverage:** Task 1 enforces authentic input; Task 2 implements Command Center Pulse and the complete loop; Task 3 produces the required MP4 and WebP; Task 4 integrates in-view playback, reduced motion, and error fallback; Task 5 verifies comprehension and loop continuity.
- **No placeholders:** every capture, file path, component ID, asset name, command, timing range, and fallback behavior is explicit.
- **Interface consistency:** Task 2 creates `HermesAgentPreview`, which Task 3 renders. Task 4 imports `hermes-agent.mp4` and `hermes-agent.webp`, which Task 3 creates. The `poster` property is added to both project data and `ProjectBox` props before it is passed from `Projects.tsx`.
