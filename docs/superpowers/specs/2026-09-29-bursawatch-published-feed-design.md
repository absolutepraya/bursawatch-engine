# Bursawatch Published Feed for the Operator Workspace

**Date:** 2026-09-29

**Status:** Approved; implementation, production rollout, and forward-only activation completed on 2026-09-30. See the production verification below and the active [Control Plane publication contract](../../../service-bursawatch-control/README.md#published-feed-projection-contract).

## Intent and success criteria

The signed-in `web-config` operator workspace should show every new Bursawatch item published to its news and swing destinations after a recorded cutover. Operators should be able to inspect what was published, its source and timing, and the confirmed Discord destination. A broker-authored plan must remain distinguishable from social chart context and from later Swing Board activity.

Success means that each eligible, confirmed delivery from every in-scope owner appears once in a read-only, paginated workspace feed, with any later published update linked to the original. An API or projection outage must not cause another Discord post, silently lose a published item, or make an incomplete feed appear complete. The feed starts forward-only; it does not claim to contain earlier publications.

## Scope and terminology

An **item** is a domain owner's logical news, notice, plan, or context output. A **publication** is the exact validated output accepted as delivered to one or more relevant Discord destinations, with a confirmed Delivery Owner receipt. One publication may have multiple delivery legs, such as swing text and chart. A later Board action is a separate publication linked to the same source item or swing episode. A **published record** is a read-only projection of an owner-controlled publication. A **projection checkpoint** is an owner's bounded comparison of confirmed publications with accepted read-model records.

The first release covers new eligible publications from all current owners and their corresponding routes:

| Owner | Included publication types |
| --- | --- |
| Telegram Market News | IDX company news, macro and industry news, and grouped stock-status notices when delivered to the scoped news routes |
| Stockbit Snips | IDX company and macro news |
| X Account Watch | IDX and US company news, macro news, and IDX swing context |
| Instagram Account Watch | IDX company and macro news |
| WhatsApp Channel Watch | IDX company, industry, and macro news, plus IDX swing context |
| Phintraco Swing | Complete broker-originated swing setups and published source updates |
| Kelas Investasi GTW | Delivered cash-swing bundles, labeled according to the validated source fields rather than assumed to be complete broker plans |
| Discord Swing Board | Published starters, replies, and lifecycle changes linked to their episode and source item |

The inclusion rule is the owner's validated route or domain publication type, not a hard-coded Discord channel ID or a guess from rendered text. The route set initially includes `id_stocks_news`, `id_industry_news`, `macro_news`, `us_stocks_news`, and `id_stocks_swing`, plus the Phintraco, GTW, and Board publication contracts. A future owner using one of these routes needs the same projection and coverage contract before the workspace can claim all-publisher coverage. Operational heartbeats, excluded candidates, unposted source events, failed delivery attempts, and private raw messages are outside this published feed.

The public type is more precise than the route: `idx_company_news`, `us_company_news`, `industry_news`, `macro_news`, `stock_status`, `broker_swing_plan`, `broker_swing_update`, `swing_context`, `swing_bundle`, or `swing_board_update`. X and WhatsApp swing posts are `swing_context` even when their text mentions levels; they do not become structured broker plans. A GTW bundle preserves its validated source fields and does not become a broker plan merely because it was sent to All Swing. Only the Phintraco owner may submit `broker_swing_plan` under its validated complete-setup contract. A Phintraco update is `broker_swing_update` only when its source update is linked to a known original publication; it carries no newly inferred complete plan levels. The original route is also retained, so the type does not erase the owner's routing decision.

This design is for the shared operator workspace. It does not create a public consumer API, a personal brokerage-preference API, a Sectors integration, or the independent Sectors hackathon submission. It does not change source eligibility, classification, delivery destinations, cadence, or the authority of the existing domain owners.

## Ownership and architecture

Each domain owner remains authoritative for parsing, classification, its durable item state, output content, and the decision to publish. The Discord Delivery Owner remains authoritative for transport, retry, and delivery receipts. The Swing Board remains authoritative for episode and lifecycle state. The Control Plane gains a bounded **published read model** in separate tables and versioned API routes; it does not become a source cursor, domain outbox, Board state writer, or Discord sender.

After the required delivery legs have confirmed receipts, the owner persists a projection intent in its own durable state and submits a versioned snapshot to the Control Plane. A retry sends the same stable key and digest. Equal repeats return the original acknowledgment; the same key with different content is a conflict. Owners never construct a new Discord delivery to repair a missing projection. Board activity is projected only after the Board owner's own publication is confirmed. For a source item that appears in All Swing and later on the Board, records share stable source and episode links while preserving separate publication acts.

The Control Plane stores the sanitized publication snapshot in its Postgres read model. The browser reads it through the existing same-origin `/api/control` proxy and user JWT. The proxy allowlists only the new GET routes. The browser has no access to owner files, raw source-event payloads, private media objects, machine credentials, or Sectors credentials.

## Publication record contract

Every accepted publication version contains:

- `publication_id`: stable, owner-scoped identity of a published act, independent of run IDs and Discord message IDs;
- `version`: positive immutable version of that act, with an optional `supersedes_version` for an explicitly published correction;
- `owner_id`, `source_event_key` when available, `source_name`, `source_url` when safe, `source_published_at` when known, and `route`;
- `type`, validated ticker or issuer identifier when applicable, and a bounded title or display summary;
- structured broker levels only when the owner validated a complete broker setup, preserving the source's entry, stop, targets, units, ranges, and attribution;
- `delivery_confirmed_at` and a list of required delivery legs with each leg's destination, receipt identity, status, message or thread link, exact rendered text when that leg sent text, and safe attachment metadata;
- `parent_publication_id` and Board episode reference when this is a published update or Board action;
- the source, config, renderer, and schema versions available at publication, plus separate market-data as-of time if the owner used dated market data.

Unknown or unavailable timestamps are nullable and must be labeled as such. `delivery_confirmed_at` is the time the owner verified a receipt; it must not be displayed as the source's publication time or a market-data as-of time. The API never invents missing plan levels, source links, proof of delivery, or media URLs. Private media references, credentials, raw source payloads, and arbitrary LLM diagnostics are excluded. A chart or other attachment may show safe metadata and its confirmed Discord link; browsing private bytes requires a separately designed authorized media path.

One logical publication can contain multiple required Discord legs with different content. It becomes visible as published only after every required leg for that act is confirmed. A later Board action is its own publication linked to the original plan or context record. Existing text or message edits are represented by an explicit new version after the edited output is confirmed; earlier versions remain available to operators. No API write from the browser can alter these records.

Each publication may retain up to 64 exact delivery legs. This accommodates X posts with up to 16 media operations plus split text messages. Owners must preserve every required operation and leave the projection pending if an act exceeds the contract bound; they cannot truncate or merge receipts.

## API and authorization

The Control Plane adds a versioned machine submission endpoint and authenticated human read endpoints under a `publications` resource. The initial contract is:

| Operation | Caller | Result |
| --- | --- | --- |
| `POST /v1/publications` | Scoped owner machine identity | Validate and idempotently accept one immutable publication version and its receipt evidence |
| `GET /v1/publications` | Signed-in viewer or admin | Newest-first, cursor-paginated summaries with type, route, date, source, and ticker filters |
| `GET /v1/publications/{publication_id}` | Signed-in viewer or admin | Exact versions, delivery legs, source references, and linked updates |
| `POST /v1/publications/checkpoints` | Scoped owner machine identity | Submit the owner's bounded projection comparison and outstanding count |
| `GET /v1/publications/coverage` | Signed-in viewer or admin | Cutover boundary and per-owner last check, lag, gap, or unknown state |

The service derives or verifies the owner identity from the machine credential; a caller cannot claim another owner's namespace. Owner permissions are limited to its own publications and checkpoints. Human authorization uses the existing viewer/admin JWT boundary, with no human publication write. The API validates enums, field lengths, source URLs, timestamps, receipt shapes, required legs, parent links, and per-type plan rules. It rejects conflicting versions and malformed evidence without replacing an accepted record.

Pagination uses an opaque cursor with deterministic ordering by `delivery_confirmed_at` and `publication_id`; filters are applied before advancing the cursor. Reads have explicit bounds and never fall back to raw source-event or run-event responses. Returned text and URLs follow the web's existing safe rendering rules. Errors do not include raw submitted content or credentials.

## Forward-only boundary, completeness, and repair

The rollout records one cutover instant and eligible owner set before any projection writer begins. Only publications whose required delivery is confirmed after that boundary enter the feed. Old owner state, source cursors, delivery receipts, and run history remain untouched. There is no replay, historical backfill, synthetic Discord post, or retrospective reconstruction from run logs. The workspace says “Published since <cutover time>” and offers no all-time total.

Each owner keeps a durable projection-pending state after delivery. A failed submission retries the same identity and digest independently of Discord delivery. The owner compares its confirmed post-cutover publication keys with Control Plane acknowledgments and reports a checkpoint containing comparison time, highest confirmed-delivery boundary, accepted boundary, and outstanding count. A checkpoint reflects only what that owner actually compared. A missing or stale checkpoint is `unknown`, not zero gaps; a nonzero outstanding count is `lagging`. The UI does not claim complete coverage beyond the last successful comparison. Repair may replay the same projection intent, never the source event or Discord send.

The all-publisher feed may be shown during rollout with explicit per-owner coverage, but it cannot claim complete all-publisher coverage until every in-scope owner has the projection contract, a recorded boundary, and a successful checkpoint. Paused owners remain listed as paused or unverified; their old latest run status is not interpreted as a current publication failure. New route-capable owners are added to the required owner set before their deliveries can be covered by a completeness claim.

## Workspace behavior

Add **Published** as a read-only destination beside Workflows and History. The list offers News and Swing groupings while retaining the precise public types above. Operators can filter by date, source, route/type, and ticker when applicable, open an item, follow its confirmed Discord and source links, and inspect the exact delivered snapshot. A swing detail distinguishes broker-authored fields from system observations and displays linked Board publications in chronological order. Chart context shows no invented plan fields.

The page displays source publication, delivery confirmation, and market-data as-of times separately. Its empty state explains the forward-only cutover. Partial API responses, missing owner checkpoints, or projection gaps show a coverage warning and the last verified time instead of an empty-success or completeness claim. The page never treats an execution run marked `ok` as publication proof. The current Workflows configuration and History run-event views retain their distinct purposes.

The companion operator-workspace spec covers configuration editors, the shared Jobs page, and the Overview, Sources, Workflows, and History evidence model. This feed spec leaves those screens to that plan while defining Published records and coverage. Overview may later link to confirmed publication evidence; a successful run remains insufficient proof of delivery.

## Delivery sequence and verification

1. Add the Control Plane schema, authorization, submission validation, read routes, and OpenAPI contract. Keep the new read model empty until a recorded cutover.
2. Add durable projection intents and exact receipt mapping to each in-scope owner, including all relevant news routes, broker/GTW swing output, and Board publications. Preserve each owner's existing delivery and retry behavior.
3. Exercise owner-to-API contract tests with fake confirmed receipts, partial multi-leg delivery, same-key retry, conflicting payload, correction version, Board linkage, and coverage gaps. Exercise API authorization, filtering, pagination, and bounded response projection.
4. Add the same-origin web proxy GET allowlist and Published UI. Test empty, partial, lagging, paused, unauthorized, and complete-since-checkpoint states with controlled fixtures. Do not use synthetic production messages.
5. Release the schema/API, then owner reporters, then the web UI through their existing separate reviewed release paths. Record the forward-only cutover and required owner set. Verify service health, one actual natural publication per active route as events occur, matching receipt and read-model identity, and owner checkpoints. Absence of a natural event is reported as unverified, not substituted with a test post.

Production service, scheduler, destination, credential, and release changes require their existing explicit review and approval. The production snapshot used while writing this design was taken at 2026-09-29 18:03 WIB: release `8f23d7137ce1c5b6af6304165326bfb9e7503b53`, `origin/main` `d88e0c196f274b41823da70a4ae96b0eecb7586a`, and seven of seven desired interval schedules matching the live registry. That snapshot does not verify runtime checksums or a natural source-to-delivery event.

## Production rollout verification (2026-09-30)

The Control Plane API and Published page shipped with PR #28; follow-up PRs #29 to #31 completed the reconciler and observer integration. The 2026-09-30 rollout SHA was `b1297c269bd42fb7d56624c362e0e0e1fe059144`, then-current `main`; it passed its exact CI gate and was released by the VPS release agent.

The authenticated Published page records its boundary as 30 September 2026, 14:15 WIB. At the latest production page check, it showed no confirmed publications since that boundary and marked publisher coverage incomplete or unverified. This is an honest empty read model, not evidence that no upstream delivery occurred. A supported publisher's record appears after its required Discord delivery receipts are confirmed and the owner submits the projection. The feed does not backfill earlier publications.

The active contracts are [`service-bursawatch-control/README.md`](../../../service-bursawatch-control/README.md#published-feed-projection-contract) and [`web-config/docs/CONTROL_PLANE.md`](../../../web-config/docs/CONTROL_PLANE.md).

## Source contracts informing this design

- `service-bursawatch-control/AGENTS.md` and `openapi/control-plane.v1.yaml` define the present configuration, source-event, and run-observability boundary.
- `web-config/docs/CONTROL_PLANE.md` and `CONFIGURATION_COVERAGE.md` describe the current authenticated workspace and its intentionally limited configuration editors.
- The `AGENTS.md` files for Market News, Stockbit, X, Instagram, WhatsApp, Phintraco Swing, Kelas Investasi GTW, and the Swing Board define the owner-specific publication and delivery contracts.
- The separately maintained Sectors Hackathon Track 2 working notes dated 2026-09-27 are draft research context, not an implementation contract for this feed.

## 2026-10-01 health and proof clarification

A signed-in Published feed or Jobs grid health note cannot prove a source
item reached a Discord room. A confirmed publication needs every required
Delivery Owner receipt. Source publication, owner acceptance, delivery
confirmation, publication projection, and room visibility remain distinct
evidence. A queued item may arrive after its source time; display both times.
Previously abandoned cutover candidates stay terminal.

CI should cover authenticated page/API behavior, receipt mapping, coverage
warnings, and honest empty states using synthetic fixtures. Read-only live
verification should correlate one source key across inbox, owner state,
stable delivery operation and frozen target, publication record, and the
configured Discord room. Lack of a fresh eligible post leaves that final
observation unverified without blocking work on other sources.
