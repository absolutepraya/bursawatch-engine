# Bursawatch

<!-- impeccable:product-schema 1 -->

## Platform

Web configuration workspace. The separate public website lives in `../web-landing/`.

## Users

Indonesian stock-market followers who want to configure recurring checks rather than repeat them manually. The two-person team uses this frontend to evaluate the configuration experience before integrating Hermes.

## Product Purpose

Follow public research sources and securities firms, choose topics, and configure recurring market checks. Preferences cover X and Instagram profiles, WhatsApp Channels and Telegram channels. Each firm keeps its own horizon, price-summary, language, tone and instruction preferences. Keep source facts separate from analyst views. Sectors is the intended market-evidence integration; the workspace currently uses sample records.

## Capabilities and Constraints

The frontend offers public recommendations, fixed sample records, browser-local source, watch, delivery and bot preferences, and previews. Preferences are not sent to the live backend; delivery forms do not connect providers or send messages. The old worker and writable SQLite adapter are omitted. The teammate's separate backend owns automation. The current boundary is `docs/INTEGRATION.md`; provenance is in `docs/MIGRATION.md`.

## Brand Commitments

Bursawatch. Minimal, dark, restrained interface inspired by Sectors, with an independent identity. Plain, useful English; no eyebrow labels over headings, hype, guaranteed returns, fabricated proof, or generic AI imagery. Original compact vector logo, suitable for a bot avatar. The user's climbing-club logo is a reference for silhouette and character, not an asset to copy.

## Evidence on Hand

Existing working Next.js demo, configuration flow, illustrative activity, and the user's sketches. Sectors reference: https://hackathon.sectors.app/sectors-product/home-market-overview.png. No validated performance claims or customer testimonials.

## Product Principles

- Make conditions and consequences understandable before saving.
- Distinguish user settings from illustrative records.
- Keep source evidence and data freshness visible.
- Never imply message delivery or live monitoring without a verified integration.

## Open Decisions

Production authentication, tenancy, Hermes integration contract, and delivery setup are not finalized by this visual redesign. The teammate is planning shared database-backed cron configuration; that is not an available web API or permission for browser database access. This private web repository remains independently runnable while that backend work proceeds.

## Brokerage identity and configuration

Discover includes the lo-fi's authentic brokerage logos, leaders and office imagery beside public research profiles. Following links each chosen firm to `/app/configuration?firm=…`; its changes remain at `/app/logs`. Official identity assets have provenance in `public/brokers/PROVENANCE.md`. Browser-local brokerage preferences retain their own versioned adapter, separate from stock automations, research sources and shared bot defaults. Legacy securities routes remain available. Signal Fold refinement 02 is the approved production mark.

## Sources and navigation

The five primary destinations are Insights, Discover, Following, Workflows and Settings, on desktop and mobile. `/app/setup` establishes shared interests and brief language/style before discovery, with a skip option. `/app/discover` combines searchable people, publications, institutions and brokerages; a recommended account's Follow action saves it directly and shows a toast. `/app/following` owns source-specific edits and removal. Public account identities were expressly authorized; selection does not certify credentials or investment performance. Private delivery IDs, credentials and runtime state remain outside this demo.

Workflows contains Schedules (`/app/automations`) and Run history (`/app/activity`). Paused workflows have no next-run claim; elapsed timestamps are labeled past due. Settings contains Delivery, Bot and Account: WhatsApp, Telegram, Discord, Slack and email are validated local preferences only. Insights summarizes up to the latest 20 available run records in a 7/30-day WIB window, shows an accessible chart/table, dated stock-move evidence and five recent run links. It does not infer scheduler health from missing days, count previews as delivered, or forecast stock performance.
