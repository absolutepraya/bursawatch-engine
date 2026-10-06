# Shared Sectors client and project-scoped configuration

Status: architecture investigation and design requirement, 4 October 2026. The user requested a client reusable by other crons and explicitly rejected machine-wide credential storage. This note records the source architecture inspected at local main `9102eaf`; it makes no current production-health claims. Local configuration scaffolding and design documentation were changed, and a three-request bounded account check was completed. The client implementation and VPS rollout remain future work.

## Confirmed direction and configuration prepared

Sectors is the selected provider for the next bounded check. Own its integration in a shared **`lib-sectors`** package, rather than in the morning cron, web app, or Control Plane. Other cron packages should import the same client and share its provider configuration instead of duplicating HTTP code or API keys.

The canonical local secret file is:

```text
/Users/absolutepraya/Documents/Projects/Hermes/lib-sectors/.env
```

The user has filled its `SECTORS_API_KEY` entry; the file has mode `0600`. Git ignores it. The design worktree's `lib-sectors/.env` is a symlink to that canonical project file, matching the existing Control Plane's local worktree-sharing pattern. The tracked `lib-sectors/.env.example` in the design worktree contains field names only. No machine-wide `.secrets` entry remains from this task. No secret is stored in a service's environment or the web packages.

Either linked local path edits the same file. Future managed worktrees should gain this narrowly scoped link through the existing preparation helper when `lib-sectors` is present. Preserve its refusal to replace a conflicting target. That helper was inspected but not modified here.

For a future VPS deployment, the corresponding proposed file is **`~/.agents/skills/lib-sectors/.env`**, mode `0600`: one runtime-package credential shared by explicitly opted-in cron consumers. It is neither a system-wide secret file nor one copy per cron. Provision it on the VPS separately after approved file comparison; never automatically copy the Mac file, include it in a source release, or capture it in a backup mirror. This VPS location is a proposal, not an existing live file verified in this investigation.

## Architecture inspected

| Existing component | Observed source contract | Implication |
| --- | --- | --- |
| [Control Plane configuration](../../../../service-bursawatch-control/env.example) and [package instructions](../../../../service-bursawatch-control/AGENTS.md) | Main-checkout `service-bursawatch-control/.env` holds API-specific local values; the VPS service has a dedicated environment | Its shared worktree file is not a general provider-key store |
| [Worktree preparation](../../../../scripts/prepare-control-plane-worktree.sh) | Links only the Control Plane's canonical local `.env`, when the package exists, and refuses conflicting targets | Reuse this linkage approach for the new library through a later reviewed helper change |
| [Telegram source wrapper](../../../../cron-tg-source-ingest/bin/bursawatch-tg-source-ingest.sh) | Imports an explicit allowlist from Hermes configuration and builds shared-library import paths; synthetic verification runs before credential loading | Adding a credential to some `.env` does not automatically make every cron use it; wiring must be explicit and preserve isolated verification |
| [Shared Telegram resilience](../../../../lib-telegram-resilience/README.md) | Shared library, coordinated host state and log, no separate scheduled job | A reusable client can have shared coordination without initially requiring a new daemon |
| [Source Media client](../../../../lib-bursawatch-source-media/README.md) and [Discord Delivery client](../../../../lib-bursawatch-discord-delivery/README.md) | Explicit client construction; private credential-file validation; clear owner boundaries | Keep provider credentials and HTTP calls behind an explicit client interface |
| [Generic deployment](../../../../deploy.sh) | Deploys cron/library `bin/` trees; does not deploy package-root `.env` | Library code releases and credential provisioning are separate inputs |
| [Release manifest](../../../../platform-bursawatch-release/release-manifest.json) | Runtime libraries have units and consumers declare dependencies | Future integration needs its own manifest unit and dependency entries, rather than assuming a new folder is deployed |
| [Web Sectors utility](../../../../web-config/src/lib/sectors.ts) and [web instructions](../../../../web-config/AGENTS.md) | Isolated TypeScript utility, synthetic fallback when no key; no reusable backend research contract | Do not treat this utility as the shared cron client or copy its silent synthetic fallback into real evidence |

Other existing local configuration files were inventoried by path and file metadata only: main-checkout Control Plane `.env`, `web-config/.env.local`, and `web-landing/.env.local`. Their values were not printed or used. No project-root `.env` or pre-existing `lib-sectors/.env` existed before this task's scaffolding.

## Proposed library contract

Source layout: `lib-sectors/bin/sectors_client/`, with focused tests, a package contract, and the field-name template. Runtime imports follow the existing repo-local `bin/` first, installed library `bin/` second convention. Package-root `.env` holds the credential; code and test fixtures never do.

Initialization is explicit. A launcher passes the library credential-file path, or an isolated test passes a fake transport and test settings. Imports must not read secrets, make requests, or mutate state. An explicit configuration loader reads only documented Sectors fields from the selected package file; it does not source arbitrary shell text, scan every `.env`, or load unrelated service credentials. An explicitly injected key can support a controlled test; avoid ambiguous silent precedence between several credential sources.

The client owns:

- Fixed HTTPS provider origin, raw-key authorization-header construction, a stable explicit User-Agent, canonical symbol/date/query handling, pagination, and response validation.
- Bounded timeouts, payload limits, retry policy, safe typed errors, and rate-limit handling. Authentication/configuration failures do not trigger unbounded retries or substitute sample data.
- Persist completed pagination pages and resume only unfinished offsets. A 5 October coverage probe received HTTP 429 after 25 new pages despite one-second inter-call spacing. Coordinate rate reservations across consumers, honor provider cooldown headers when present, distinguish sanitized quota error codes from temporary throttling, and stop after a bounded retry budget. Do not hard-code an unverified numeric account rate limit.
- Treat each requested session's pagination total and member order independently. April samples report 956 results while October reports 962; a ticker's current offset is not a historical locator. Validate symbol/date identity after joining and retain omissions explicitly.
- Explicit response provenance: query identity, retrieval time, effective dates when supplied, missing fields, and freshness. A current market-cap response does not become dated merely because it was fetched today.
- The morning caller explicitly accepts collection-dated cap snapshots with underlying effective dates unverified. Preserve that distinction in cache metadata; the library must not invent an economic date to satisfy another caller's stricter requirements.
- A shared cache and host-level credit coordination for opted-in consumers. Repeated queries should reuse eligible cached responses, and concurrent consumers should coordinate one fetch instead of multiplying paid requests.

Each cron owns its source selection, evidence cutoff, relevance, basket construction, weighting, assessment, rendering, scheduling, and publication through the existing Delivery Owner. The library does not post to Discord, run an LLM, schedule a job, alter source state, or calculate the morning outlook.

## Shared cache and credit ownership

Sharing a key without sharing request accounting is insufficient: several crons could independently exhaust the same subscription. Proposed first implementation uses one host-local, private coordination store, with atomic request reservations and fetch leases keyed by canonical request and explicit credential profile. The design must account conservatively for a request whose billable outcome is unknown after interruption, and release stale fetch leases without blindly repeating the paid request.

A proposed runtime path is `~/.hermes/state/sectors-client.sqlite3`; local development uses ignored, project-local disposable state configured explicitly. Cache entries retain effective date and retrieval time separately. A caller's cutoff/freshness requirements determine whether a cached response is eligible; shared cache reuse must not inject later evidence into a frozen morning run. Safe logs contain counts, endpoint categories and sanitized error codes, never API keys, authorization headers or raw credential-bearing exceptions.

Set caller budgets and a host-wide ceiling before paid requests. Structured requests are the default; higher-cost natural-language queries require an explicit caller choice. A host-local ledger cannot enforce an account-wide ceiling across independent Mac/VPS processes or unrelated users of the same account. Account-level quota visibility or a single request authority would need separate design if that scope is required.

A new service is not required merely to share an importable client. Reconsider a provider-owner service only when credential isolation, multi-language access, cross-process policy enforcement, or coordination requirements justify that host operation. Preserve the existing Control Plane, Source Media, and Discord Delivery ownership boundaries.

## Implementation and rollout follow-up

1. Continue data checks only with a fresh stated budget. The 4 October check completed three structured request attempts: one HTTP 403 and two HTTP 200 responses after setting an explicit User-Agent. The same original query then worked, indicating likely request filtering rather than a key or screener-entitlement problem. BBCA, BBRI and TLKM returned numeric caps, sectors and subsectors, but no cap-effective date was established. Actual quota decrement and stock/IHSG history remain unverified. The [account-check record](2026-10-04-morning-brief-provider-coverage-and-rights-research.md#authenticated-bounded-check-4-october-2026) contains sanitized parameters and remaining evidence gates. No reusable client implementation exists yet.
2. Implement the library against fake HTTP and temporary state, including pagination, missing fields, stale data, auth failure, rate limits, concurrent cache reuse and interrupted request accounting. Preserve the documented lack of IHSG OHLC rather than fabricating candles.
3. Integrate the intended cron through explicit imports/configuration only after its child contract is read. Add library/consumer CI coverage, release dependencies, and narrowly scoped worktree `.env` linking in the same implementation change.
4. Review code deployment and package-root credential provisioning separately. No VPS writes, service restarts, cron changes or synthetic production posts occurred here.
5. Keep hackathon eligibility separate. A reusable Bursawatch package does not automatically authorize importing prior-project code into the required new competition repository; resolve the submission boundary before reuse.

The earlier chart-provider boundary remains a design issue under Sectors-only direction: a shared client cannot add fields that Sectors does not provide. That data-coverage issue is separate from credential placement and package ownership.

## Bulk price sharing approved 5 October

The user selected the Sectors full-universe daily-close endpoint for ongoing sector and conglomerate rotation prices. The shared client/cache should coordinate one completed-session fetch across consumers, validate pagination and dates, store session history, and expose reusable closes with source provenance. Each domain owner retains its calculation and frozen-cutoff rules. Sectors IHSG closing history is the separate benchmark request. The sampled classified universe contains 962 stocks, including all 188 distinct conglomerate CSV members, so no additional daily conglomerate pull is needed.

The documented-rate estimate is 33 stock-close pages plus one IHSG call per session, subject to actual feed coverage. Initial history, effective dated caps, weekly weight updates, split handling and account allowance remain separate verification tasks. Membership is imported once and changes only on explicit user request. This approval records a design choice; no recurring task, DB implementation, client code or production operation was created.

## Design checkpoint, 5 October

The morning spec's behavior frontier is now agreed, including chart-only technical overlays, immutable published records after provider corrections, and omission of unsupported prior-session images. These rules reinforce shared-cache provenance: retain the exact frozen input identity and any later correction separately, and never silently replace a run's published inputs. Finalized design choices do not establish provider split-adjustment semantics, effective cap dates, account quota, or deployment readiness. No implementation was introduced.

## Credit allocation and local render configuration, 5 October

The user selected a monthly operating envelope of 1,000 Sectors credits with manual top-ups. The parent spec allocates 782 to session closes/IHSG, 25 to weekly cap metadata, 23 to a filtered split calendar, 70 to retries/corrections, 50 to other evidence and 50 reserve. Shared caller accounting should enforce the declared ceiling and use cached inputs rather than independently multiply the same daily requests. Historical initialization has its own separately bounded allocation; no full initialization or implementation occurred. Cheap dated cap export remains a validation gate, not a guaranteed five-page contract.

For the separate private Chart-IMG validation, a canonical ignored project-root `.env` (0600) and worktree link hold blank `CHART_IMG_API_KEY` and `CHART_IMG_LAYOUT_ID` placeholders. The field-name `.env.example` is prepared in the design worktree. The selected primary free TradingView layout uses SMC and built-in RSI divergence, omitting Volume. These local probe inputs do not relocate the confirmed `lib-sectors/.env` credential or provision any VPS environment.

## Separate Chart-IMG ownership, confirmed 5 October

The user requested `lib-chart-img` for reusable chart transport and render coordination. Its local probe environment was moved from the project root into that package. This is separate from the numerical-data `lib-sectors` provider and its 1,000-credit monthly envelope. See the [Chart-IMG architecture note](2026-10-05-shared-chart-img-client-architecture.md); earlier root-path descriptions are superseded. No provider client implementation was introduced.
