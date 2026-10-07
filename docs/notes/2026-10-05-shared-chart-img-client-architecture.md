# Shared Chart-IMG client architecture

Status: user-confirmed shared-library direction, 5 October 2026. Configuration scaffolding, design documentation and bounded private render validation only. No reusable rendering client, recurring job or production deployment has been introduced.

## Package and configuration

Own the provider integration in **`lib-chart-img`**, parallel to `lib-sectors`. The user explicitly wants it reusable by other crons and application parts. Planned source layout is `lib-chart-img/bin/chart_img_client/`, following the existing shared Python libraries and explicit consumer import-path convention.

The canonical local credential file is `/Users/absolutepraya/Documents/Projects/Hermes/lib-chart-img/.env`, mode `0600`, ignored by Git. The design worktree's package file is a link to it, and its `.env.example` lists blank field names. The task-created project-root Chart-IMG `.env` and template were moved here without printing or discarding any values. There were no unrelated root environment entries to retain. This supersedes the earlier project-root placement.

`CHART_IMG_API_KEY` belongs to the provider library. `CHART_IMG_LAYOUT_ID` is currently a private-validation input for the single IHSG sample, not a global layout default. The client must receive each caller's layout ID explicitly; future cron-specific layout IDs and rendering profiles belong to that cron's configuration. One shared provider key does not imply every consumer uses the same chart or studies. Do not load unrelated service/web environments or machine-wide secrets.

A future runtime credential may follow the package-scoped path `~/.agents/skills/lib-chart-img/.env`, with separate approved VPS provisioning. This is a proposal, not a verified live file or automatic copy target. The generic deployment helper copies library `bin/`, not package-root `.env`. Worktree helper linkage, CI registration, release-manifest unit and consumer dependencies remain implementation tasks.

## Library boundary

The library owns explicit authenticated transport to the fixed Chart-IMG HTTPS origin, advanced-chart and shared-layout operations, validated provider requests, bounded call deadlines, payload limits, safe error categories and provider rate coordination. Construction and imports must not read credentials, fetch images or mutate state implicitly. Do not follow credential-bearing redirects or log API keys, headers, response cookies or raw credential-bearing exceptions.

Return validated image bytes and render provenance, such as request identity, caller profile revision, provider endpoint, retrieval time, dimensions and payload digest. Validate content type, format, dimensions and payload size before a domain owner accepts the attachment. A requested symbol/date is not proof of what appears in the rendered chart; the output-verification method and supported temporal controls still need a sample.

Each caller owns symbol, interval, studies, shared layout ID, styling, desired window, freshness and evidence cutoff, fallback choice, text and publication. The morning owner supplies the dedicated free-account SMC/RSI layout and selects its agreed simple-chart fallback. The library does not choose an IHSG scenario, calculate rotation, edit TradingView layouts, schedule a job, send Discord REST, or acquire account sessions.

Rotation calculation/image generation remains separate: `lib-sectors` supplies numerical inputs, the domain calculates custom baskets, and a local renderer draws those rotation images. Chart-IMG renders the selected TradingView chart; chart pixels are not a numerical data feed.

## Sharing and accounting

Coordinate repeated identical render requests and provider-wide rate limits across opted-in consumers. Chart-IMG request accounting is separate from the Sectors 1,000-credit monthly envelope. The documented free Chart-IMG ceiling is 50 requests/day, with one request/second. Private requests already verified key access, shared-layout rendering and 800 by 600 PNG output. The saved/shared profile mismatch and public-distribution permission remain unresolved; successful requests do not prove a recurring allowance or publication license. A daemon is not necessary merely to share imported client code.

Cache keys include caller profile/layout revision and requested symbol/interval/window as supported. A mutable layout ID alone cannot identify immutable rendered content. Respect caller cutoffs and freshness; reuse accepted bytes for publication recovery rather than regenerate a chart after acceptance. Retain a frozen per-run payload separately from a mutable latest cache. Use atomic leases/reservations to avoid concurrent duplicate renders and conservatively account for uncertain provider outcomes.

## Existing architecture evidence

The main-checkout Discord Delivery and Source Media libraries use explicit client construction, validated credential paths and bounded byte handoff. Reuse those boundary principles; preserve the Delivery Owner as the only Discord REST path. The generic deployment helper and release manifest establish that a new folder is not automatically wired into runtime imports or deployment. No existing generic Chart-IMG backend library was found in the local source inventory.

## Follow-up gates

- Reconcile owner-saved and publicly shared layout state. The key and layout ID are already provided and private render access is verified.
- Verify the final two-study profile, three-month framing, regular-only divergence, hidden grids, ticker text and legibility after public state reflects the owner's settings. The inspected public view supports the latest completed session but does not create a generic render cutoff guarantee.
- Resolve Chart-IMG public-output rights before public Discord/demo integration; no provider contact occurred.
- Implement transport and validation against fake HTTP, then shared coordination and explicit consumer wiring after scope/competition eligibility is settled.
- Keep code release and VPS credential provisioning separate; no VPS write or production operation occurred here.

## Working private render, 5 October

The user-filled package key and shared layout `vQj9F2JC` successfully returned a valid 800 by 600 PNG for IDX:COMPOSITE/1D in one private request without session cookies. This validates the basic provider transport and shared access, not an implemented reusable client. The captured layout still includes a volume-error entry, broader-than-requested visible dates and hidden-divergence labels. Its settings must be saved in TradingView because the shared-layout API does not document study-list editing. The user now explicitly excludes Volume from every IHSG profile, including fallback; other callers remain free to request their own supported studies.
