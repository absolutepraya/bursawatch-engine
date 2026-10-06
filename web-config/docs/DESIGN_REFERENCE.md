---
name: Bursawatch
description: A restrained dark workspace for configurable IDX stock watches.
colors:
  bg: "#141615"
  surface: "#1c1f1d"
  surface-soft: "#242825"
  surface-hover: "#2b302c"
  ink: "#edf0eb"
  muted: "#a9b0a9"
  subtle: "#8b958d"
  accent: "#dea777"
  accent-soft: "#32291f"
  positive: "#a7cfb3"
  positive-soft: "#24372b"
  info: "#a8c6dc"
  info-soft: "#25323c"
  warning: "#e3bd88"
  warning-soft: "#352e22"
  danger: "#eeaaaa"
  danger-soft: "#3b2929"
  border: "#383e38"
  border-soft: "#2b302c"
  control-border: "#657065"
  focus: "#edc69f"
typography:
  display:
    fontFamily: "Hanken Grotesk Variable, sans-serif"
    fontSize: "clamp(2.5rem, 4.4vw, 3.625rem)"
    fontWeight: 500
    lineHeight: 1.08
    letterSpacing: "-0.04em"
  headline:
    fontFamily: "Hanken Grotesk Variable, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 550
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Hanken Grotesk Variable, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Hanken Grotesk Variable, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Hanken Grotesk Variable, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
rounded:
  control: "6px"
  surface: "10px"
spacing:
  tight: "8px"
  inline: "12px"
  compact: "16px"
  section: "24px"
  wide: "32px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.bg}"
    rounded: "{rounded.control}"
    padding: "10px 17px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 17px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.control}"
    padding: "10px 17px"
  text-input:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "11px 12px"
  navigation-link:
    textColor: "{colors.muted}"
    rounded: "{rounded.control}"
    padding: "10px 14px"
  status-positive:
    backgroundColor: "{colors.positive-soft}"
    textColor: "{colors.positive}"
    rounded: "5px"
    padding: "4px 8px"
  surface-panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.surface}"
  selected-symbol:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
---

# Bursawatch design reference

## Overview

**Creative North Star: "The Quiet Market Desk"**

Bursawatch is a minimal, dark workspace for market-source workflows. Its restraint comes from charcoal surfaces, clear rows, compact headings, and generous separation between tasks. The approved copper Signal Fold mark supplies identity.

### Authenticated workspace

Component references are [shadcn's sidebar](https://ui.shadcn.com/docs/components/base/sidebar)
and [accessible field composition](https://ui.shadcn.com/docs/components/radix/field),
[Efferd's dashboard blocks](https://efferd.com/blocks), and the user's approved
sample workspace. Use their restrained grouping and consistent control rhythm;
do not import a template's palette, paid assets or unsupported product features.
The implementation retains Bursawatch's native controls and semantic CSS tokens;
it does not claim a shadcn or Efferd package installation.

`/workspace` uses the same restrained visual language with seven live destinations: Overview, Sources, Workflows, Jobs, History, Published and Account. Desktop sidebar and mobile bottom navigation expose identical destinations. Overview visualizes recorded runs with explicit coverage. Sources separates visual references from live settings. Each of the eight supported workflow kinds explains its input, processing and output above the complete task-grouped editor, with linked shared-job identity and observed state alongside configuration. Schedule status distinguishes saved intent from confirmed application. Only the authenticated control API supplies current configuration and activity.

The Sources destination sits below Overview. Securities uses a two-column thumbnail grid and People a three-column profile grid where space permits; both collapse to readable single-column layouts on narrow screens. Dated public brokerage photographs, illustrative thumbnails, brand plates, social avatars and identity descriptions remain references. Search and platform filters help browse them; settings links appear only for watcher IDs returned by the API. Added/to-add preview styling never establishes saved membership, a configured, enabled or healthy source. BRI Danareksa can open WhatsApp settings; Phintraco has separate swing and market-news settings. Configuration rows require admin access and use reviewed public avatars only after consistent platform and canonical URL/handle matching. Separately, the selected workflow's Source profiles panel loads real engine metadata on demand for signed-in users. Admins can edit automatic/manual photos or explicitly request a refresh, with uncertain writes blocked until a fresh metadata read. A refresh request is not proof of completion. Unknown or failed images retain initials. Catalog provenance remains in `public/brokers/PROVENANCE.md` and `public/sources/PROVENANCE.md`.

### Sample workspace

`/app` mirrors the authenticated workspace's seven destinations, labels, components and layout. It is visibly labelled Sample workspace and uses synthetic in-memory data through a fixture-backed request function. It does not load Auth state or call `/api/control`. Sample-only presentation and notices stay under `src/app/app/`.

Sources uses the same Securities, Institutions and People & Org tabs, with public catalog identities and logos. Published uses public Bursawatch examples from the landing page and labels every item as a sample record. The Bursawatch Pagi example keeps the `BURSAWATCH PAGI`, `ROTASI SEKTOR` and `ROTASI KONGLO` structure, labels its figures as dummy data and does not look like a delivery receipt. Synthetic Jobs and History records remain read-only and do not imply live schedules, runs, source connections or deliveries.

Controls feel direct and measured. Data, source context, and the consequence of a condition carry the visual interest; illustrative records remain distinct from a user's saved settings.

**Key Characteristics:**

- Charcoal layers with warm white primary controls.
- One variable sans-serif family, compact workspace hierarchy.
- Copper identity and selection; semantic color for state.
- Rows, thin dividers, and purposeful panels.
- Quiet sample context and visible source evidence.

## Colors

The palette combines warm charcoal neutrals with copper identity and muted semantic colors. The frontmatter owns exact values.

### Primary

Copper (`accent`) appears in the brand, selected navigation icons, and native choice controls. Its dark companion (`accent-soft`) supports the mobile navigation selection. Warm white (`ink`) provides primary action fill and main text.

### Secondary

Positive green, information blue, warning amber, and failure rose pair with their respective soft backgrounds. They communicate status or financial movement, with a readable label alongside color.

### Neutral

Canvas, surface, soft surface, and hover surface form the tonal stack. Muted and subtle text support the main ink. Borders separate content; the stronger control border identifies editable and secondary interactive elements. Focus uses a pale copper outline.

**The Accent Restraint Rule.** Copper identifies the product and selection; primary actions use warm white.

## Typography

**Display and Body Font:** Hanken Grotesk Variable, with sans-serif fallback. Monospace is reserved for technical identifiers in activity details.

Headlines use modest negative tracking and medium weight. The public website in `../../web-landing/` owns its separate landing display; it does not carry into this workspace. Page titles use the headline role; section headings use the title role. Body inheritance is (16px), while most workspace prose is (14px), supporting detail (13px), and metadata (12px). Paragraph line height is usually (1.6). Times and market changes use tabular numerals.

At the mobile breakpoint, page titles become (26px). Visible field labels remain separate from placeholders.

**The Heading First Rule.** Start a section with its useful heading; do not add eyebrow labels above it.

## Layout

The authenticated workspace uses a fixed (224px) sidebar and content capped at (1392px), with (44px) horizontal gutters, reduced to (28px) below (1200px). At (800px) and below, the brand and sign-out move to the header, seven labeled destinations form an adaptive grid in the bottom bar, and content gutters become (20px). At 375px the bar uses two rows at normal text size and reduces its column count as text grows, keeping labels whole and all destinations visible. Reserve the bar's actual measured height, including safe areas and additional rows at enlarged text sizes. Public source rows and brokerage photographs reflow without narrowing editable fields.

The sample `/app` uses the same fixed (224px) desktop navigation and content capped at (1392px), with (44px) horizontal gutters as `/workspace`. At (800px) and below, the seven labeled destinations form the same adaptive bottom grid. At 375px the bar uses two rows at normal text size and reduces its column count as text grows, keeping all destinations visible. Reserve its measured height, including safe areas and extra rows at enlarged text sizes.

In the sample, each destination uses the shared workspace content width and task-grouped components. Source rows separate identity, useful context and action; use divided rows and selective panels, with readable form and prose measures. Landing layout belongs to the independent `web-landing` package.

Sample-only notices explain which real workspace changes the schemas support. Do not add sample controls for an evening digest, adding a People & Org identity directly to a watcher, changing the fixed morning brief time or setting a weekly interval. Common gaps use the recorded spacing steps without forcing every layout onto one rigid scale.

## Elevation & Depth

Changes in surface tone and borders distinguish navigation, panels, rows, and controls. Only the sticky bulk-selection tray has a restrained shadow to separate it from scrolling content. The brokerage message preview uses the neutral surface token; semantic green is reserved for price/status values.

**The Flat Surface Rule.** Express hierarchy through tone, spacing, and dividers; preserve the flat surface language.

## Shapes

Panels use softly rounded corners from the surface token; buttons, fields, and navigation use the tighter control token. Small badges have compact corners. Circles belong to step markers and public-profile avatars, not general containers. Institution logos retain their proportions on neutral white plates. The message preview has an asymmetric speech-bubble corner. Use the approved Signal Fold vector logo and SVG icons. Preserve its three source inlets and fold gaps; do not add an eye, arrow or bird detail.

## Components

### Buttons

Warm white primary buttons have dark text. Secondary buttons use a surface fill and stronger control border; ghost buttons use muted text on transparent backgrounds. Buttons have a minimum height of (44px), medium-bold (14px) text, and the recorded padding. Hover changes fill or text; pressed buttons darken; disabled buttons use (0.45) opacity.

### Inputs / Fields

Fields use the canvas fill, control border, and visible label. Hover strengthens the border; an invalid field uses danger color plus error text. Native checks and radios use copper. All keyboard focus indicators use a (2px) pale copper outline with (4px) offset.

### Navigation

Desktop links pair small SVG icons with text and a minimum (44px) hit area. Active links use a brighter surface and copper icon. Both live and sample desktop and mobile navigation expose Overview, Sources, Workflows, Jobs, History, Published and Account in that order. Mobile links retain labels and copper selection, with a minimum (54px) height and an adaptive grid. Global schedule controls live only in Jobs. Workflow catalog rows show configuration and Configure; runtime evidence belongs in Overview and selected workflow details. Expose current location with `aria-current`.

### Chips

Status badges combine a semantic soft background and text label. Selected stock chips include a (44px) remove control. The sample navigation and each view carry a clear Sample workspace label and a short notice about its example data. The authenticated workspace identifies current API state and dates its public reference catalog.

### Cards / Containers

Use bordered surface panels for forms, source details, grouped watches, and settings. Use open rows and dividers for activity and stock summaries. Panel padding follows content density, commonly (20–26px), and tightens on mobile.

### Watch and Message Previews

The sample Bursawatch Pagi card shows the public landing example and labels its figures as dummy data. Published detail labels source material as sample content and hides destination identifiers and receipt claims. The authenticated workspace's input, processing and output summary describes supported workflow capabilities, not a delivery preview or proof of execution. The public website owns its own example interactions.

State colors use (160ms ease-out). The motion budget allows one (180ms) page-entry opacity fade plus primary-button press feedback. Reduced-motion preferences remove animations and transitions and disable smooth scrolling. Loading indicators must only communicate actual pending work, never decorate an idle page.

## Do's and Don'ts

### Do:

- **Do** use warm white controls, copper identity, and semantic status labels.
- **Do** retain visible labels, keyboard focus, and at least 44px control targets.
- **Do** show source context and distinguish sample records from saved settings.
- **Do** reflow dense rows and detail columns before their text becomes cramped.

### Don't:

- **Don't** add eyebrow labels, decorative blur, gradients, or generic AI imagery.
- **Don't** return to the retired white/petrol palette or Familjen/Plex font pairing.
- **Don't** repeat global demo warnings throughout the workspace.
- **Don't** imply live monitoring, delivery, or validated performance from illustrative records.
