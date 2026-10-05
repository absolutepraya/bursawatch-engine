# Bursawatch morning brief implementation plan

Status: requested implementation plan, 5 October 2026. Behavior and presentation agreed; external capabilities remain validation gates. This document does not authorize implementation, paid API requests, production deployment, schedule activation, guild emoji creation or Discord posting.

Design authority: [morning brief spec](2026-09-27-bursawatch-morning-brief-design-spec.md), especially its consolidated presentation and latest confirmations. Source inspection used local main `9102eaf`. Recheck current main and child instructions before implementation; the design worktree is older and contains uncommitted research/scaffolding. No production-health assertion is made here.

## 1. Delivery target and first usable milestone

On verified IDX trading sessions, freeze evidence at 07:30 WIB, choose generated or facts-only output by 07:55, target 08:00 delivery and initiate no new attempts after 08:15. The publisher owns six frozen steps: IHSG text/image, sector text/image, konglo text/image. Recovery reuses the same inputs, bytes, operation keys and receipts.

The first milestone is an isolated local preview from fake transports and retained inputs: three texts, three branded images, immutable provenance/manifest and simulated delivery recovery. It must consume zero Sectors/Chart-IMG requests and make zero Discord calls. Synthetic data is an explicit preview mode, never a real-data fallback.

A production integration and a hackathon submission are separate destinations. The integration layout below targets Hermes packages. A competition entry must first satisfy onboarding and new eligible-period repository requirements; do not copy pre-existing private Hermes code into an entry or imply this older repository qualifies. Settle that repository boundary before implementing competition code. Host/service work remains outside competition reuse assumptions.

## 2. Ownership and proposed files

| Owner | Proposed source areas | Responsibility |
| --- | --- | --- |
| `lib-sectors` | `bin/sectors_client/{config,transport,models,cache,budget}.py`, tests, package contract | Provider transport, validation, shared retained pages, fetch leases, rate coordination and credit reservations |
| `lib-chart-img` | `bin/chart_img_client/{config,transport,models,cache}.py`, tests, package contract | Shared provider rendering transport, image validation, render cache and separate request accounting |
| `cron-dc-morning-brief` | `bin/morning_brief/{config,store,calendar,inputs,evidence,rotation,outlook,formatting,rendering,publication}.py`, wrapper, `AGENTS.md`, `SKILL.md`, tests | Frozen daily run, relevant evidence, global/calendar adapters, baskets, model writing, visuals and receipt-gated publication |
| Control Plane | `source_inbox.py`, `api.py`, `auth.py`, service API contract and tests | Least-privilege read-only capture of eligible immutable source versions |
| Delivery Owner/client | Both `models.py` contracts, service `api.py`, `store.py`, `worker.py`, client and tests | Optional operation attempt deadline; immutable identity and uncertain-result reconciliation |
| Existing emoji helper | `skill-profile-emoji` supplied-image path | One-time reviewed icon onboarding through Delivery Owner; existing green/red mappings |
| Repository wiring | Worktree preparation helper, `scripts/test-all`, CI, release manifest, package inventory | Explicit imports, test registration, provider env linkage and release dependencies |

These are planned modules and package names, not existing implementations. Use existing shared Control Plane, Source Media and Delivery clients. Do not add direct Discord REST, direct privileged Storage access, duplicate source intake or a provider daemon merely to share library imports. Global/calendar adapters initially belong to the morning owner behind small interfaces; extract further libraries only when a second consumer justifies them.

## 3. Local state, configuration and retained inputs

Implement explicit constructors and configuration loading. Importing a package must not load secrets, fetch data or write state. Keep provider keys in package-local ignored `lib-sectors/.env` and `lib-chart-img/.env`, using the canonical main-checkout files and non-conflicting worktree links. Keep layout ID/profile revision caller-owned. Load only the documented fields, never shell-source arbitrary files or unrelated service environments.

Use one explicitly configured private host-local Sectors coordination store across participating consumers. Separate that provider cache/ledger from the morning owner's run database. Local stores/artifacts are ignored project state; generated private previews remain outside Git. VPS package-scoped credentials and runtime state paths are separate later provisioning inputs, never automatically copied from this Mac.

Morning state needs:

- Verified session calendar/version, membership version and cap snapshot identity.
- Run/session identity, freeze instant, phase, fallback reason and evidence manifest hash.
- Immutable source version references, selected publisher provenance, global quote timestamps and calendar snapshot.
- Eligible/excluded members, action decisions, coverage, weights, aligned closes and calculated coordinates.
- Frozen text/image digests and files, step dependencies, stable operation keys, acceptance state, matching receipts and explicit omissions.
- Model/prompt/profile versions, rendering/font/logo version and frozen A-to-P mapping.
- Publication projection checkpoint and safe run/heartbeat summaries.

Migrations must be restart-safe. Single-run leases prevent competing publishers for the same session. Reads and corrections must not rewrite previously frozen publication records.

Import the retained JSON cache at `lib-sectors/state/local-preview-2026-10-05/` without network calls. Validate dates, offsets, symbols, totals and response provenance before use. It contains 126 successful new historical pages, three complete September sessions, a partial 14 September and the reused complete 2 October session. These are not sufficient for the full 18-level rotation window. Do not count imported pages as newly purchased requests or assert that the local ledger reveals the current account balance.

## 4. Shared Sectors client and spending protection

Build against fake HTTP and temporary SQLite first. Implement fixed-origin HTTPS, explicit User-Agent, bounded timeouts/size, raw-key authorization, redirect refusal, typed safe failures, validated session/symbol/query identities and per-date pagination. Historical page totals and member ordering can change; never reuse an October offset to locate an April symbol.

Before starting a request, atomically reserve its conservative maximum credit cost against caller and host billing-window limits. A shared request key/lease prevents duplicate concurrent fetches. Persist each successful page immediately, then reuse/resume only missing eligible pages. A crash with unknown billing outcome retains its reservation until resolved; do not silently release it and repeat the request. Distinguish authentication failure, temporary throttle and exhausted allowance. Honor verified retry/cooldown hints and use bounded retry reservations; no assumed account-wide numeric rate limit.

Account budget is 1,000 credits per configured operating/billing window, with manual top-up. Conservative recurring estimate:

| Item | Credits |
| --- | ---: |
| 33 close pages + one IHSG close + one split-calendar request, for 23 sessions | 805 |
| Five weekly cap snapshots at five pages each | 25 |
| Core total | 830 |
| Retries, corrections, other evidence and reserve | 170 |

A normal core day is 35 credits, or 40 on cap-refresh day. Larger universes, pagination changes and endpoint cost changes require recalculation before spending; do not assume 33 pages forever. Shared participation cannot guarantee an account-wide ceiling when unrelated clients on another host use the same key. Use one authorized production fetch authority and no concurrent Mac paid probes by default.

The previously discussed 600-credit setup allowance is stopped, not automatically resumable. Finish local implementation without historical fetches. To gain usable live history, either accumulate missing sessions within the approved recurring budget or separately authorize a bounded import after showing exact remaining dates/pages and retained reuse. Preview regeneration never starts bootstrap.

Acceptance: concurrent identical requests cause one fetch; interrupted pagination resumes at the missing page; cache respects each caller's cutoff; retry exhaustion stops; quota denial makes no request; secret-bearing failures remain sanitized.

## 5. Membership, calendar and deterministic rotation

Import sector membership once, retain the official-first/Sectors IDX-IC fallback provenance and do not schedule membership refreshes. Preserve the supplied konglo CSV exactly as a versioned membership input: 34 groups, 188 unique tickers, overlapping group memberships intentional. Do not silently infer current ownership from that file.

Use an authoritative versioned IDX session calendar with amendment checks. Weekdays alone are insufficient. A scheduled run on a non-session produces a no-op heartbeat, not a synthetic market brief.

Refresh caps on the first trading session of each week. Label snapshot collection time and underlying effective date unverified. Allow the agreed one-extra-week collection-age fallback, then omit unsupported rotation. For a basket, require complete valid cap inputs, consistent eligible members across the entire window and at least 90 percent of original basket cap covered by eligible price history. Renormalize eligible weights to 100 percent, retain exclusions and coverage, and use the same fixed snapshot/member set across its trail.

Use compatible split-adjusted price returns, excluding dividends. Preserve the sampled DSSA adjustment fixture and exclude unresolved actions. Never apply a split twice or universally reconstruct shares from rounded cap/price ratios. Positive closes alone do not establish trading eligibility.

For basket daily returns from fixed weights, compound the latest ten sessions. Calculate `X(t) = 100 * (R_b,10(t) - R_i,10(t))`, then `Y(t) = X(t) - X(t-3)`. Five plotted daily positions require 18 aligned closing levels. Do not forward-fill missing session prices. Exact-zero axes are Neutral, not one of the four quadrants. Current-cap historical illustrations are not unbiased backtests.

Konglo selection: changed quadrant since the preceding session first, descending `abs(Y)`, alphabetical name, then take at most 18 qualifying groups. Table ordering is separate: Leading, Improving, Weakening, Lagging, descending X, descending Y, alphabetical name. Neutral is explicitly labeled and placed after four-quadrant rows if present; it remains in qualifying-group counts. Assign unselected letter codes alphabetically and freeze the mapping. With 34 qualifying groups this is A to P.

Acceptance: analytical return fixtures independently verify compounding, windows, signs, neutrality and thresholds; shuffled provider rows do not change output; overlaps remain valid; missing sessions/actions produce exclusions; selection and table sort are deterministic.

## 6. Global markets and Indonesian economic calendar

Initial global watchlist is KOSPI, Nikkei and QQQ, maximum three rows. Yahoo/yfinance is the proposed free-access adapter, not a guaranteed unlimited feed. Validate bounded access and appropriate data usage before production. Capture regular-session price, prior regular close, timestamp, timezone and delayed/live status. Asia uses the snapshot available by 07:30 WIB; QQQ uses the latest completed US regular session. Do not mix after-hours moves into the default comparison. Preserve USD units for QQQ and point units for the indices.

Format one row per market, using the requested custom-icon/status shape. The local Markdown has explicit hard line breaks. Real Discord payloads use actual `<:name:id>` markup. Use existing green/red mappings, a neutral Unicode marker for exact flat, and unavailable/stale labeling rather than fabricated zero. Missing market data must not cause a paid substitute or suppress independently valid IHSG facts.

Build calendar adapters for BPS national Rencana Terbit and official BI RDG/release schedules. A public page is not proof of a stable API. First validate extraction using saved/synthetic page fixtures, including dynamic empty pages, amended dates and missing time. Only publish verified future events. Show the next three distinct relevant releases after the freeze across dates, sorted chronologically; include event, reference period, date/time WIB and source. Deduplicate two-day meetings and joint briefings, distinguish decision day from meeting start, and label an unknown time. Show fewer when fewer are verified. Do not generate dates from monthly habits or invent consensus estimates.

Keep immutable source snapshots with retrieval/verification times; cache unchanged calendars across daily runs. The research note lists exact primary URLs and remaining extraction gaps. The private preview's dates are placeholders, not three verified upcoming events.

Acceptance: timezone/daylight-saving and holiday fixtures, closed/open market cases, stale quotes, percentage denominator/units, amended/duplicate calendar entries, unknown times and chronological three-event selection.

## 7. Source evidence capture and bounded outlook writing

Extend the Control Plane through its existing ownership/auth contracts. Add a least-privilege read-only source-window capture and bounded immutable-version reads. Do not claim pipeline work or use Published Feed as the full research corpus.

Capture eligible source version identities under one consistent database snapshot at the freeze; return a bounded deterministic manifest with capture time, accepted/published/observed timestamps, provenance and overflow state. Persist the manifest in owner state before selecting evidence. If payloads require further pages, read explicit immutable versions from that manifest, not a changing timestamp query. Later commits, corrections and tombstones must not alter the captured set. A late capture cannot claim to reproduce an exact earlier committed-state snapshot; record the gap and degrade accordingly.

Use `(previous verified session cutoff, current cutoff]` to cover weekends/holidays. Retention must support that lookback plus run recovery; unavailable history is incomplete evidence, not an invitation to replay sources. Cap final evidence at 30 deduplicated items and three per available publisher across routes/lanes. Use verified original publisher when present, otherwise canonical collecting publisher, preserving unknown origin. Copied stories do not count as independent opinions.

A bounded generative writer receives only the frozen bundle. Deterministic code owns calculations, source eligibility, cutoff, keys and delivery. Require evidence-backed claims and inline source attribution. No fabricated catalysts, level derivations or calibrated probabilities. SMC/RSI overlays are context, not sufficient evidence for an asserted direction. If writing times out or the outlook is unsupported, choose concise facts-only text by 07:55; preserve the frozen valid global/calendar facts where available.

Acceptance: late commit, correction, tombstone, missing publisher, cross-lane cap, copied story, truncated corpus, model timeout, unsupported claim and facts-only fallback fixtures. No source mutation or live model/network call is needed for these tests.

## 8. Shared Chart-IMG and approved local rendering

Implement the shared client against fake HTTP first. Validate image MIME, decoded dimensions, actual format, byte limits and digest; reject HTML/error bodies and credential-bearing redirects. Cache by immutable caller profile revision, symbol, interval, supported time range and layout revision, with one coordinated fetch. Layout ID alone is not immutable content. Separate provider allowance accounting from Sectors.

Primary IHSG: `IDX:COMPOSITE`, daily candles, three months, light/no grid/ticker text, saved layout `vQj9F2JC`, SMC and RSI regular divergence, no Volume. Reconcile saved/public layout and demonstrate final output before accepting the primary profile. A requested cutoff or matching close alone does not prove the chart's last-bar date. Establish a supported window/as-of verification method; if it cannot verify a primary output, use the approved ordinary-RSI fallback or omit the image. Any new provider validation requests require explicit authorization.

Render a matching dark branded wrapper without altering provider chart data or removing attribution. Title left, smaller B plus wordmark right, date below title, slightly rounded provider panel and direct gold border.

Replace the temporary plotting script with a maintainable local renderer and packaged licensed font/logo assets. Rotation images follow the accepted landscape layout: square plot left, distribution/table right, rounded gold perimeter directly on the square, blue Improving and the agreed other colors. Keep actual numerical trail positions intact. Preview smoothing may illustrate the design; production must not introduce artificial market turns or horizontal segments to fit text. Full names belong to 18 highlighted konglo dots; secondary letters map to the two-column legend below the table. Sector table includes all qualifying sectors. Store cap/source/coverage provenance in the artifact manifest and expose freshness/exclusions when material without restoring the rejected boilerplate.

Acceptance: controlled SVG/PNG fixture composition, square geometry, date/header placement, table/legend bounds, actual glyph/font availability, status colors, invalid images, cache revision changes and immutable image reuse. Visually inspect normal Discord display size; a native-resolution image alone does not prove readability.

## 9. Text formatting and emoji configuration

Preserve the approved message titles, concise Indonesian outlook and up to three rotation highlights. New global/calendar subsection names have no decorative emoji. Keep the explicitly requested market-logo/status markers on separate rows. Use actual supporting source URLs. Count final text including headings, links and real custom-emoji IDs, not the shorter preview placeholders. Trim optional prose/highlights deterministically to fit 2,000 characters, retaining the required factual identity, timestamps and sources; never truncate a URL or split within an emoji token.

Index icons need verified/supplied logo assets. Use the existing helper's local-image circular preparation; do not ask its X/Instagram profile resolver to resolve an index ticker. Guild asset creation is a separately approved onboarding operation through Delivery Owner, never a daily cron step. Unknown icon IDs fall back to readable names. No guild mutation occurs during local tests.

Acceptance: final markup length boundary, hard line breaks, absent icon, duplicate names, source-link preservation, six-block local Markdown and attachment captions/titles understandable when unrelated posts interleave.

## 10. Service-owned delivery deadline and frozen publisher

Add an optional timezone-aware attempt deadline to shared intent validation, canonical digest, API/store serialization and worker policy. Preserve unchanged behavior and compatible digests for callers that omit it. Expired operations may not initiate new sends, including retries. Attempts started earlier retain receipts and bounded reconciliation after expiry. Reconciliation itself does not recreate an expired message.

Review the exact terminal expiry/reconciliation state contract before implementation: ambiguous earlier sends must not be labeled absent or safely rejected merely because time expired. Test persisted records across restart/migration and existing consumers without a deadline. Keep the Delivery Owner as the sole Discord REST path.

Morning owner persists the six-step manifest and attachment bytes before submission. Match immutable operation key/digest/receipt before acknowledging a step. Queue ordering is not a success prerequisite. Advance only from matching confirmed receipts or an explicit image-unavailable omission recorded before submission. A rejected text anchor cannot release its dependent image. Pending/ambiguous operations stay unresolved; never convert them to omissions or replacement creates.

Freeze text and accepted images, including global/calendar facts, on first publication selection. Retry the same stable key and bytes. Keep image bytes until durable acceptance; do not assume a caller-facing staged-media-ref API or automatic service media TTL. Retain original messages and input record under later market/source corrections. Use shared receipt waiting and its actual deadline semantics.

Only after all required/available steps have matching receipts, submit the confirmed output projection through the shared Control Plane client. Projection retry never reissues a Discord operation. If the closing review later consumes the morning anchor, expose its frozen text receipt and scenario, not a mutable latest text.

Acceptance: response lost after acceptance, crash before receipt persistence, payload conflict, text rejection, unavailable image, pending image, expired retry, send crossing expiry, uncertain result after expiry, missing/corrupt staged bytes and projection outage. All use fake gateway/service transports and temporary state/media.

## 11. Integration, observability and staged verification

Register new suites/dependencies in `scripts/test-all` and CI. Extend narrowly scoped worktree env linking without replacing conflicting paths. Add library and consumer units/dependencies to the release manifest only after reading its current contract; manifest registration alone is not deployment. Document proposed package/runtime identity, model invocation and separate credential provisioning in one root `SKILL.md` plus child `AGENTS.md`.

The proposed runtime name is `bursawatch-dc-morning-brief`. Emit a heartbeat on every run, including no-session/no-data/degraded runs, to the repository-mandated heartbeat destination. Record run phase, cache hit/miss, reserved/spent/uncertain credits, date/coverage gaps, selected fallback, image omissions and matching receipt outcome without secrets or raw sensitive evidence. Capture the target brief destination as a reviewed deployment input; do not choose or change a live channel implicitly.

Run focused tests per changed package, then package suites and `bash scripts/test-all`. Verify a full fake/local dry run and restart/recovery scenario, plus visual review of final-size artifacts. Broaden tests only for new changes or unresolved failures. Inspect completed CI when needed; never poll/wait for it and never wait for CodeRabbit as a merge gate.

Suggested review slices: (1) shared provider/cache libraries, (2) source-read and deadline contracts, (3) numerical/input owner, (4) renderer/formatting, (5) frozen publication integration. No automatic PR, merge or deployment follows this plan.

## 12. Production acceptance and separately approved rollout

Before requesting rollout approval, complete reviewable code, required tests and a concrete deployment diff. Validate account-specific data/render permissions, session-calendar amendments, source retention, global/calendar extraction and chart as-of handling. Use only a separately approved bounded provider probe, displaying expected credit cost before requesting it. Reuse retained responses throughout.

For actual deployment, verify the current release contract, run the required production snapshot before writing current operational claims, and compare exact live files before the first VPS write. Keep code publication, library/service release, source-reader credential, provider secrets, emoji assets, destination configuration and schedule activation as distinct inputs. New service bootstrap/configuration and scheduler changes remain explicit approval boundaries. Never move or reset existing production state as source.

Stage disabled/no-post first, then activate the approved desired schedule at the existing agreed cadence through its supported owner/reconciler contract. Verify applied revision and the first natural market-session run: source snapshot, immutable run state, all matching receipts and visible six-step output. Green health or schedule parity alone is insufficient. Do not post synthetic smoke-test messages or broadly replay historical briefs.

On failure, disable only the newly approved morning job through desired state, preserve its run/provider/delivery ledgers and uncertain operations, and retain rollback artifacts under the repository's VPS backup contract. Do not reset shared caches or modify unrelated jobs. Report capability, scheduler state and visible delivery separately.

## Completion criteria

The local implementation is ready for deployment review when all fake/no-post tests pass, real-input gaps fail explicitly, the agreed visuals/text fit Discord, caches and spending limits survive interruption/concurrency, and the six-step publisher proves duplicate-safe receipt/deadline behavior. Production completion additionally requires separate deployment approval and independently observed natural delivery. Neither dummy preview approval nor this plan establishes those outcomes.
