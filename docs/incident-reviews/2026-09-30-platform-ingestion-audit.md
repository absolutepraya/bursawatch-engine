# Platform ingestion audit and debugging handoff

**Observed:** 2026-09-30, approximately 16:20 to 17:40 WIB

**Scope:** Telegram, X, Stockbit RSS, and the Bursawatch WhatsApp Channel watcher
**Mode:** Read-only production investigation. This is a time-bounded evidence record, not an operating contract.

**Worktree:** `.worktrees/bug-squashing`, branch `absolutepraya/bug-squashing`, based on `origin/main` at `680cc4520db6e0102dbcd55bfc62e7ee73de7cea`.

## Workstream authorization

**Recorded 2026-10-01:** The user has authorized agents working on this
Bursawatch ingestion bug-squashing effort to carry out the actions reasonably
needed to complete it without requesting separate approval for each action.
This includes opening and merging pull requests, pausing and resuming the
existing affected jobs through the supported scheduler interface, deploying
reviewed fixes, and applying reviewed production state changes.

This authorization remains subject to repository and package release gates and
the reviewed plan's preconditions. The user's forward-only requirement remains
in force: do not replay or backfill historical items or send stale news.

Recheck live state before acting. The original source-state observations were collected mainly between 16:20 and 17:03 WIB. Adjacent-service checks ran between 17:35 and 17:40 WIB. Read-only production snapshots ran at 17:22:56 and 17:40:17 WIB. Runtime state may have changed since then.

## Follow-up: temporary schedule control

- A production snapshot at 00:35:38 WIB on 2026-10-01 showed both source writers active and all eight desired schedules matching. A direct systemd read found `bursawatch-schedule-reconciler.timer` enabled and active, last triggered at 00:35:23 WIB, with its one-shot service inactive and `Result=success`.
- A Hermes CLI pause alone did not remain in effect because the desired Control Plane schedules still had `enabled=true`. The reconciler resumes an allowlisted job when its live enabled state differs from that desired value. Both jobs were active again in the refreshed snapshot. Temporary maintenance pauses must be recorded as disabled desired revisions at the same interval, then restored to enabled through the authenticated schedule interface and verified after natural reconciliation.
- The catalog transition plan now pauses through desired schedule revisions, verifies no run is in flight, and archives reader state only after both writers are quiescent.
- At 00:53 WIB on 2026-10-01, desired revisions 2 and 6 were applied for Telegram and Stockbit, respectively. Both jobs are paused at their existing one-minute and fifteen-minute intervals. A fresh production snapshot showed 6 active and 7 paused jobs, all eight desired schedules matching, and the release agent still blocked on pending CI. No source-reader process was present. The paused-state read found 212 Telegram inbox work rows, all done with no active lease, and no RSS work rows.
- Complete Telegram and RSS reader-state archives with SHA-256 inventories were verified under `~/backup/hermes/runtime-cutovers/2026-10-01/`. Their directories are private and the archives are retained for at least 30 days. No catalog marker or transition journal has been changed; application remains gated on the exact-main release.

## Follow-up: catalog transition recovery and natural runs

**Verified:** 2026-10-01, 09:15 to 10:09 WIB

- GitHub Actions run `36796468228` for `925b894968a93005d3458167c38143c463877338` completed successfully in 97 seconds. All three jobs passed: `validate`, `Deterministic package suites`, and `WhatsApp Channel Watch`. Both Vercel status checks passed. This is separate from the `bursawatch/release` commit status. The production snapshot's label `Release CI state` refers to that release-agent status, which had been pending on three operator-owned release groups; after the reviewed manual release operation it reports success, with 11 eligible units released and the three manual groups skipped.
- Read-only production snapshots at 09:15:21, 09:39:26, 10:09:16, and 10:23:44 WIB confirmed `origin/main` and last successful release both at `925b894968a93005d3458167c38143c463877338`, no blocked release agent, no transient release error, a running Hermes gateway, and 8/8 desired interval schedules matching. Telegram and Stockbit are active at their original one-minute and fifteen-minute cadences. The latest snapshot again reports 13 Hermes jobs, 8 active and 5 paused.
- A further read-only production snapshot at 10:57:03 WIB confirmed the same main and release SHA, successful release status, no blocked release agent, a running Hermes gateway, 13 jobs with 8 active and 5 paused, and 8/8 interval schedules matching. Telegram source-ingest is active at one minute; the legacy Market News reader and watchdog remain paused. This snapshot does not verify runtime checksums or prove source-to-delivery completion.
- Telegram and RSS reader markers are now revision 7. Their package-owned transition chains were applied edge by edge while writers were paused. Telegram resumed and naturally accepted source events. A database aggregate at 09:15:43 WIB showed post-resume work counts: `company_news` 11 done / 75 pending; `macro_news` 12 done / 74 pending; `stock_status` 37 done / 1 leased / 25 pending; `swing_plan` 20 done / 11 leased / 32 pending; `swing_support` 5 done / 95 pending. These rows prove source-work acceptance and partial handler progress, not delivery. Whether this backlog drains under natural runs remains for a separate owner/pipeline diagnosis; runner order was not changed.
- The earlier `agent-status` counts of 43 at 09:23 and 63 at 09:42 described a package-local Market News state file read by direct source-runner subprocesses, not the canonical state selected by the Market News wrapper. At 09:51, the package-local file held 69 source-provenance candidates: 68 `pending_analysis` and 1 `awaiting_agent`, with no selection or delivery records. The canonical `~/.hermes/state/idx-market-news.json` held 688 candidates, 30 `pending_analysis`, 1 `awaiting_agent`, and zero source-work provenance records. The two files shared 31 candidate keys with identical candidate payloads but differing phases; 38 package-local candidates had no canonical counterpart. The package-local file had an active lease and retry history through attempt 20; the canonical file had not changed since 2026-09-29 04:08 WIB.
- This is a confirmed state-root split. `cron-tg-source-ingest/bin/runner.py` launches Market News `pipeline_owner.py` directly, while the runner environment omitted `IDX_MARKET_NEWS_STATE_PATH`; `state.py` therefore used `~/.agents/skills/bursawatch-tg-market-news/state.json`. Hermes receives that claimed item and submits through `bursawatch-tg-market-news.sh`, which selects `~/.hermes/state/idx-market-news.json`. The latest 12 source-run outputs all requested one Market News item without a dispatch warning. A sanitized owner-log tail contained candidate-not-in-durable-state and candidate-not-awaiting rejections, consistent with the split. Other validation and Delivery Owner errors also appeared in the untimestamped log tail, so those counts are not attributed to this root cause.
- A worktree-only fix now passes the canonical state path to both Market News source-work and agent-status/claim subprocesses, preserving any explicit environment override. The focused regression tests passed (6), the `cron-tg-source-ingest` package suite passed (50), and `bash scripts/test-all` passed with one skipped test and existing deprecation warnings. The fix is not published or deployed; neither live state file has been edited, copied, or removed. The [separate state-root reconciliation plan](../superpowers/plans/2026-10-01-market-news-state-root-reconciliation.md) accounts for the 69 accepted candidates before the active owner path changes.
- A preliminary state comparison made while source-ingest was active also found four package-local stock-status events, all already present in canonical state. The rejected outcomes matched. Two locally pending events were already canonically delivered with Delivery Owner receipts. The approved merge therefore preserves canonical outcomes and receipts, adding only matching source-event provenance missing from canonical records. These counts and hashes still require a fresh preview after the writer is paused.
- The natural Stockbit run started at 09:09:05 WIB and completed. It created one `stockbit_snips` source-work item at 09:08:58 WIB, now `done`, proving that the RSS catalog gate passed and the owner accepted the work. The Stockbit article-owner submission finished `degraded` from 09:09:29 to 09:09:33 WIB, with one error and zero locally confirmed deliveries. A read-only Delivery Owner lookup and active-ledger inspection later showed the stable operation is `delivered`; its stored target and digest match the frozen route destination. Its receipt contains `message_id` but omits `channel_id`. The shared [gateway](../../service-bursawatch-discord-delivery/bin/discord_delivery/discord_gateway.py:207) intentionally returns only `message_id` for a channel-message create, and the shared [receipt validator](../../service-bursawatch-discord-delivery/bin/discord_delivery/models.py:230) permits that field to be absent. Stockbit's [delivery drain](../../cron-stockbit-snips/bin/scan.py:268) requires `channel_id`, so it records a local retry while the Delivery Owner has already delivered the operation. This is a receipt-shape contract mismatch, not evidence of a wrong-channel send. The local article remains `pending_delivery` after one retry and needs a separate safe reconciliation; do not replay or create a new operation.
- A follow-up code trace on 2026-10-01 confirmed the Stockbit shared sender checks the stable operation key and digest, and the digest includes the operation target. A normal retry looks up that same operation before submitting. The separate `stockbit-receipt-ack` worktree fix accepts a missing `channel_id` only with a valid `message_id` and matching stable delivered operation, while continuing to reject an explicit channel mismatch. The local destination comes from the article's frozen configuration snapshot. Its focused regression passed (2 tests), the Stockbit package suite passed (114 tests), and the repository suite passed with one skipped test and existing deprecation warnings. The fix is not yet in `main` or deployed. Re-read the live article and owner operation before rollout; do not replay it or create a replacement operation.
- The initial catalog blockers are repaired at the reader boundary, and natural runs passed both catalog gates. Telegram's Market News state-root split and Stockbit's local receipt mismatch remain separate unresolved work. The Phintas route gap, WhatsApp archive-capture failure, and Torch RSSHub omission from the original audit also remain open.

## Follow-up: Telegram Market News source-to-channel gap

**Verified:** 2026-10-01, 11:45 to 11:57 WIB. Read-only source, state, and
channel inspection. No replay or post was performed.

- Discord history since Sep 25 returned 62 `#id-stocks-news` messages, latest
  at 10:44 WIB on Oct 1, and 8 `#id-industry-news` messages, latest at 14:21
  WIB on Sep 29. The requested history window fit within the 100-message read
  cap for both channels.
- Telegram remained active. Tuntun published through message 15058 on Oct 1;
  its newest messages were daily/promotion material outside the Market News
  parser contract. Its Sep 30 evening update, message 15053, produced three
  Industry candidates that remain `pending_analysis`. The Sep 30 Corporate
  message 15054 produced four candidates, but the BRIS entry was omitted
  because the legal-name parentheses are nested and the current ticker-line
  expression rejects that shape.
- Phintraco published Stock Information message 35549 at 08:21 WIB on Oct 1.
  Its effective date was `01 Oktober 2026`; the parser's English-only month
  conversion rejected it, and the owner ledger records `invalid_status`.
  Messages 35484 and 35522 (effective Sep 29 and Sep 30) were delivered to
  `#id-stocks-news` at about 10:43 WIB on Oct 1, confirming the late status
  symptom. The new Oct 1 status was not delivered.
- The source cursors were already at Tuntun 15058 and Phintraco 35552. The
  package-local owner file had 69 source-provenance candidates, all 69 keys
  also present in the canonical owner ledger. Two overlapping keys had phase
  differences. Canonical state had 83 active candidates, all published before
  Oct 1: 82 `pending_analysis` and one `awaiting_agent`, spanning Sep 28 to
  Sep 30. No candidate was in `pending_delivery` at this read.
- The state-root cause is confirmed: the source runner's direct Market News
  subprocess and the classification wrapper selected different owner files.
  Source-work retries and expired leases therefore accumulated while the
  scheduled job and source cursors continued moving. The open `bug-squashing`
  change passes the canonical path to direct owner subprocesses.
- The existing state-reconciliation plan would otherwise leave old candidates
  eligible after the path correction. Because the user explicitly requires
  forward-only delivery with no stale sends, the plan now abandons pre-cutover
  active candidates before resume and blocks unresolved Delivery Owner work.
  This state operation has not been applied.
- Worktree fixes also extend status parsing to Indonesian month names and allow
  nested parentheses in Tuntun Corporate entries. Neither change replays the
  inspected messages; future source messages use the corrected parsers after
  the release. The focused changed-path checks passed 112 tests, the Market
  News package suite passed 310 tests, and `bash scripts/test-all` passed all
  repository checks with one existing skip and deprecation warnings. These
  tests verify local contracts, not a live natural delivery.
- A production snapshot at 11:57:06 WIB showed `origin/main` and last
  successful release both at `925b894`, all 8 desired schedules matching,
  the Telegram source-ingest job active, and the legacy Market News reader and
  watchdog paused. It does not prove a natural source-to-delivery event.

The X/RSSHub omission, WhatsApp archive-capture gap, and Phintas route question
remain open and separate from this Telegram news-path diagnosis. Stockbit's
receipt mismatch is handled by the separate worktree fix above; it is not yet
published or deployed.

## Follow-up: Telegram repair merged, production reconciliation pending

**Verified:** 2026-10-01, 13:14 WIB.

- PR #33 merged at 13:13 WIB as `3ae575c48ceac79cc95e5625f92b0b19dc38bb44`.
  Its branch checks passed before merge. The post-merge production snapshot
  showed `origin/main` at that SHA and the last successful production release
  still at `925b894968a93005d3458167c38143c463877338`. The release-agent status
  was pending, with no blocked release or transient error.
- The snapshot showed a running Hermes gateway, 13 jobs (8 active and 5
  paused), and all 8 desired interval schedules matching. Telegram
  source-ingest remained active at one minute. The legacy Market News reader
  and watchdog remained paused. These checks do not prove deployed runtime
  checksums or a new source-to-delivery event.
- The approved Market News state reconciliation has not been applied. Wait for
  the merged code to pass its exact-main release gate, then verify the deployed
  source-runner path and isolated no-post result before following the approved
  pause, archive, fresh preview, apply, and resume sequence.

## Executive summary

The four reported symptoms do not share one cause. Confirmed current issues at the time of inspection were:

1. Telegram source intake failed its catalog revision guard for every enabled endpoint. The Phintas swing update also has a separate route and parent-reply handling gap relative to the expected behavior.
2. Telegram Market News had 32 due owner candidates, including an expired agent lease. The cause of this backlog is not established.
3. Stockbit RSS intake stopped before fetching because its saved catalog revision was stale. The scheduled job ran and its heartbeat deliveries succeeded, so `0 fetched / 1 error` did not indicate a scheduler or heartbeat delivery outage.
4. One WhatsApp image event was blocked because the immutable archive had no captured media bytes.
5. The Torch X post was absent before Source Inbox acceptance. The latest X poll and watcher queue were otherwise clear. The exact source-side reason remains unknown.

The adjacent boundary pass found the Control Plane at revision 7, Source Media healthy, the Discord Delivery queue empty, and RSSHub plus its dependencies healthy. This points debugging toward the catalog transition, WhatsApp bridge archive capture, and account-specific RSSHub/X visibility instead of a broad shared-service outage. Health endpoints and recent heartbeat receipts do not prove a complete natural source-to-delivery path.

## Telegram

### Catalog gate blocks all enabled endpoints

- Effective Source Catalog revision: **7**.
- Telegram source-ingest state revision: **5**, last changed 2026-09-29 06:49 WIB.
- The only deployed transition artifact found was `compatible-4-to-5.json`; no 5-to-7 transition exists.
- `ingest_all` binds the catalog revision before endpoint iteration. The adapter therefore stops before polling any enabled endpoint. The runner masks the underlying block as `RuntimeError: source processing failed`.
- The current enabled and verified endpoints are:
  - `kelasinvestasiid:swing_support`
  - `phintasprofits:company_news`, `macro_news`, and `stock_status`
  - `phintraprofits:trading_plans`
  - `tuntunsekuritas:company_news` and `macro_news`
- All four endpoint cursors exist, but are stale: Kelas 10787, Phintas 35483, Phintraprofits 35483, and Tuntun 15031. Pending handoff files were zero and no current Telegram `blocked-media.json` markers were found.
- The log had 1,698 generic fatal records after its latest normal JSON result. That earlier result showed the endpoints as `ok`, with zero accepted events and unchanged cursors. The repeated fatal records are consistent with the revision guard, though the log itself does not preserve the inner exception.

Relevant code paths: [catalog revision binding](../../lib-bursawatch-source-ingest/bin/source_ingest.py:144), [Telegram adapter](../../cron-tg-source-ingest/bin/adapter.py:555), and [generic error wrapper](../../cron-tg-source-ingest/bin/runner.py:354).

### Phintas swing update has a separate route gap

- [Reported post 35530](https://t.me/phintasprofits/35530) was published 2026-09-30 at about 13:46 WIB. It says the first INDF target at 6900 was achieved and replies to post 35447, a Phintas weekly swing idea with INDF entry and targets.
- The post was absent from Source Inbox (`telegram:phintasprofits:35530` lookup returned 404). The Phintas cursor remained at 35483.
- The current Phintas catalog rows include `company_news`, `macro_news`, and `stock_status`. `trading_plans` and parent-reply resolution are wired for `phintraprofits`, not `phintasprofits`.
- This is a separate routing/capability question from the global revision block. Confirm the intended Phintas behavior before changing its catalog or adapter mapping.

### Market News owner backlog and model rate limits

- At about 17:03 WIB, Market News state showed **31 `pending_analysis` candidates and 1 `awaiting_agent` candidate**. The agent lease was expired and all retry deadlines were due. That read noted 2026-09-29 at 08:11 WIB as “last changed,” but did not preserve whether this was a filesystem mtime or an internal timestamp.
- At 17:38:55 WIB, a second read of the canonical `/home/praya/.hermes/state/idx-market-news.json` showed **30 due `pending_analysis` candidates and 1 expired `awaiting_agent` candidate**. Its filesystem mtime was 2026-09-29 04:08:08 WIB. One regular file was found under `~/.hermes/state`, with no symlink and no `IDX_MARKET_NEWS_STATE_PATH` override found in `.env` or the SSH process environment. Inline Hermes job environment was not inspected. The 31-to-30 count difference remains unexplained; recheck before recovery.
- One Stock Status item was `rejected`; its reason was not inspected.
- Phintraco Swing had no outbox or pending Board work. Kelas had no pending bundle or outbox work.
- Six model API HTTP 429 records were found for `bursawatch-tg-source-ingest`; the latest was 2026-09-30 at **10:30 WIB**. A prior read misconverted the naive local timestamp as 17:30; 10:30 WIB is the corrected time. The 429s predate the 16:20 revision failure. No causal link between them and the Market News backlog was proven.
- The Telegram runner [calls `ingest_all()` before `_process_pending()`](../../cron-tg-source-ingest/bin/runner.py:293). A revision mismatch raises before `PipelineRuntime` or agent dispatch runs, so the current catalog gate prevents accepted inbox work and expired Market News leases from being processed on that invocation. This can sustain the backlog, but does not prove it caused the initial accumulation or the 429s.

Historical Telegram log entries included nine `upload_media` / `IntakeBlocked` observations each for Phintas and Phintraprofits, five Phintraprofits `resolve_entity` / `ValueError` observations, and eight blocked observations without a recorded stage or error type. These are historical records with no current matching media block; they are not confirmed live failures.

One focused synthetic check of the catalog revision guard passed: 1 passed, 20 deselected. It validates the expected fail-closed behavior only, not production recovery.

## X

- The missed [Torch post](https://x.com/writingtorch/status/2105187407926809029?s=20) has ID `2105187407926809029`. The earlier [forwarded post](https://x.com/writingtorch/status/2105119182325252507) is in the accepted-event index as a normal single-post thread.
- The effective X config was revision 9. Torch was enabled through RSSHub; normal posts and quotes were enabled, replies to other accounts and reposts were disabled. Thread policy was `self_chain`, with 20 maximum posts, 240-minute maximum age, and a 15-minute settle window.
- The source cursor had advanced to `2105222314002677829`, timestamped about 16:04 WIB. The missed post was absent from the accepted-event index and watcher delivery state. The RSSHub user feed read around 16:35 returned the newer item and the earlier forwarded item, but omitted the missed post. The direct X page returned 403, so the missed post's type and reply relationship could not be confirmed.
- The latest source summary around 17:00 showed all eight enabled profiles accepted, without blocked endpoints. The watcher outbox was empty; the latest recorded delivery was 16:31 WIB. Watcher state recorded 1,057 deliveries and 114 source-event ledger entries (67 accepted, 47 irrelevant). There was no current X delivery backlog.
- The missed post failed before inbox acceptance. The [X source adapter](../../cron-x-source-ingest/bin/adapter.py:271) passes returned feed posts to Source Inbox and does not apply reply-forwardability filtering there. The [reply policy](../../cron-x-account-watch/bin/rsshub.py:209) is checked later by the watcher, after inbox acceptance. Therefore that policy does not explain this post's absence from the feed and accepted-event index. The remaining evidence points upstream to RSSHub or X timeline visibility; the exact account-specific cause remains unknown. Thread settings may still affect eventual forwarding if a separately recovered post proves to be an external reply.
- The numeric cursor has passed the missed post ID. Normal future-only polling will not recover it if the feed later exposes it. The watcher has a separately gated `recover-missing` path for one to ten explicit status URLs. Its preview checks enabled-account ownership, age, settle period, cursor position, duplicates, and eligibility. Replies require separate review. This path was not run.
- Cumulative X logs contained 43 blocked observations: 34 `handoff_or_fetch_failed` observations for `insidertrackx` and `wavetiga`, both disabled in the current config, and 9 `correction_handoff_failed` observations for active profiles (Aldo 4, Arvin 1, Kutekians 2, Torch 2). Their timestamps are absent; the latest 15 run summaries were clean.
- Three generic `RuntimeError: source processing failed` tracebacks occur before more than 200 later run summaries. Their inner exceptions and timestamps are unavailable. They are historical and unattributed, not confirmed current failures.

## Stockbit RSS

- Effective Source Catalog revision: **7**. RSS source-state marker: **4**. All four Stockbit feed endpoints were enabled and verified.
- Production runs require the legacy cursor seed. The revision mismatch blocks before feed fetching and is reported as `migration_cursor_handoff_invalid`, explaining `0 fetched` and one source error. See the [RSS runner gate](../../cron-rss-source-ingest/bin/runner.py:68).
- The active 15-minute job had 27 completed executions and zero scheduler execution errors in the last 24 hours. Heartbeat operation receipts at 16:20, 16:36, and 16:52 WIB were all delivered. A completed job and delivered heartbeat do not mean that RSS items were fetched.
- The old `bursawatch-stockbit-snips.log` was last modified on 2026-09-28. Its 454 records include 178 heartbeat delivery failures, 10 Stockbit delivery failures, and one feed timeout. The active RSS wrapper has no persistent run log; these old direct-scanner errors are not evidence of current runner or heartbeat failure.
- A refreshed read-only check at 20:32 WIB confirmed the RSS source-state marker remained at revision 4 while the effective catalog was revision 7. Code review found that `require_legacy_cursor_seed()` requires both the state marker and each cursor's `legacy_seed.catalog_revision` to equal the effective catalog revision. Advancing only the marker would therefore leave polling blocked even though the four Stockbit catalog rows are unchanged. A later-revision transition must preserve and validate the original seed provenance while proving the compatible revision path, or use another separately reviewed provenance design.

## WhatsApp Channel

This heartbeat belongs to Bursawatch's Baileys-backed Channel watcher and bridge queue. It is separate from Yanto's WhatsApp Cloud API adapter.

- The 16:22 WIB heartbeat reported `accepted=0 work=0 pending=0 claimed=0 delivered=0 blocked=1`.
- A `blocked-media.json` marker refreshed around 16:28 WIB pointed to one image/jpeg queue event published at 07:47 WIB. Its immutable archive record had `capture_status=unavailable` and no bytes. The cursor remained before that event, at the earlier 05:36 WIB boundary.
- `blocked=1` counts a blocked source result for the endpoint on that run; it is not a count of all blocked queue events. The evidence supports one currently stuck media event. Disposable queue staging was not read. See the [WhatsApp media block path](../../cron-wa-source-ingest/bin/adapter.py:290).
- The adjacent capture owner is [Channel sink `copyStagedMedia` / `archiveMedia`](../../cron-wa-channel-watch/bin/channel_sink.mjs:226). It records `capture_status=unavailable` if bridge staging bytes are missing or copying fails. The source adapter [uploads archive media later](../../cron-wa-source-ingest/bin/adapter.py:219) and requires captured archive bytes first. The failure is therefore before Source Media; the exact staging-path cause was not inspected.
- Across canonical archive metadata for 2026-09-23 to 2026-09-30, 210 records included 164 captured media objects and 2 unavailable objects: this BRI image and an unrelated INS video. This suggests rare item-level capture misses rather than a broad capture failure.

## Shared delivery and scheduler context

- At 17:38 to 17:40 WIB, the Control Plane, Source Media, and Discord Delivery services were active, with `/healthz` returning HTTP 200 on ports 9120, 9130, and 9140. Control Plane's effective catalog was revision 7, updated 2026-09-29 08:17 WIB, with 60 subscriptions, 7 enabled and verified Telegram rows, and 4 RSS rows. This is evidence against a Control Plane availability failure, not proof that the reader state was transitioned.
- The Discord Delivery `/healthz` endpoint reported `pending=0`, `blocked=0`, and `ambiguous=0`. A sanitized seven-day ledger query found 12,505 operations, all delivered, and no warning-or-higher journal entries. Source Media had 174 successful uploads in its seven-day ledger and no warning-or-higher journal entries. Its ledger contains successes only, so transient upload failures cannot be ruled out.
- RSSHub returned HTTP 200 and 10 Torch item IDs at 17:35 to 17:38 WIB, but omitted the missed post while returning the later cursor item and earlier forwarded item. RSSHub, its MCP instance, Redis, Browserless, and real-browser containers were healthy with zero restarts. This rules out a broad service outage at check time, not account-specific provider visibility, route, cache, or timeline gaps. RSSHub implementation, cookies, proxy configuration, and runtime data are VPS-owned; this repository has documentation only in [`service-rsshub/README.md`](../../service-rsshub/README.md).
- The repository's read-only production snapshot at **17:40:17 WIB** again reported 13 Hermes jobs total, 8 active and 5 paused, with all 8 desired interval schedules matching the live registry. Telegram source ingest, WhatsApp channel watch, X account watch, and Stockbit RSS were active. Separate Telegram Market News, Phintraco Swing, and Kelas jobs were paused as expected by package contracts.
- The same snapshot reported `origin/main` at `680cc4520db6e0102dbcd55bfc62e7ee73de7cea`, last successful release `b1297c269bd42fb7d56624c362e0e0e1fe059144`, release CI pending, release agent blocked, and Hermes gateway running. A scheduler record of `last=ok` is not a source-to-delivery proof.

## Adjacent debugging boundaries

These components are directly on the affected paths and are the next useful places to inspect. The checks above found no evidence that their shared service health is the primary fault; they identify where the unresolved behavior lives.

### Source Catalog history and transition ownership

- The Control Plane returned revision 7 successfully and exposes versioned catalog history plus audit metadata. The effective revision was updated 2026-09-29 at 08:17 WIB; it had 60 total subscriptions, 7 enabled and verified Telegram rows, and 4 RSS rows. Telegram state remains at revision 5 and RSS at revision 4. Telegram transition journals are complete only through 2-to-3, 3-to-4, and 4-to-5. The runtime evidence supports a missing reader-state transition, not a broken Control Plane endpoint.
- A refreshed read-only history comparison at 20:32 WIB found identical owned projections at catalog revisions 5, 6, and 7: the same seven enabled verified Telegram endpoint-capability rows, the same four enabled verified Stockbit RSS lanes, and an empty `selected_securities` list. Catalog hashes differed, so configuration outside those projections changed.
- A follow-up read-only comparison at 21:10 WIB found the four enabled, verified Stockbit RSS rows and empty `selected_securities` unchanged across revisions 4 and 5. The enabled Telegram projection was also unchanged across that edge. The RSS cutover receipt and all four lane seed records confirm revision 4 as the immutable origin. This closes the history comparison needed to consider adjacent RSS transitions from 4 to 7; live state and catalog history must still be refreshed before any apply.
- The shared low-level [cursor planner](../../lib-bursawatch-source-ingest/bin/legacy_cursor_seed.py:277) accepts a reviewed forward transition across multiple revisions, but requires its caller to prove the catalog diff is safe and writers are paused. The Telegram [compatible wrapper](../../cron-tg-source-ingest/bin/compatible_catalog_transition.py:181) requires exactly one consecutive revision and unchanged enabled Telegram projection; the current identical projections can use that existing wrapper one edge at a time. Its News transition tool is scoped to a paired activation. RSS documents its legacy seed handoff and has no generic later-revision transition command; its current seed validator also pins legacy-seed provenance to the current effective catalog revision. Design an RSS package-owned transition that addresses this constraint while preserving the original cursor boundary and proving each revision edge. Do not hand-edit markers.
- `service-bursawatch-control/bin/control_plane/source_catalog.py` retains revision snapshots and audit rows. Comparing the sanitized revision diffs and change metadata is the adjacent evidence needed to identify what advanced the catalog and whether a transition was expected.

### Telegram owner pipeline

- The due Market News candidates and expired lease are downstream of the source catalog gate. `run_once()` awaits source ingestion before `_process_pending()`, so the mismatch prevents `PipelineRuntime` and agent dispatch for that run. This coupling can keep work waiting even when the owner service itself is healthy.
- The pending count discrepancy and timestamp fields are unresolved. Re-read the canonical state path and job environment before drawing a conclusion about backlog size or deciding how an expired lease should recover. The six model 429s are a separate lead until a sanitized request record can be tied to a candidate or phase transition.

### WhatsApp bridge archive capture

- The relevant adjacent code is the Channel sink's bridge-staging-to-immutable-archive copy, before the source adapter and before Source Media. Review the media descriptor and copy preconditions using sanitized metadata. Do not inspect disposable staging or media bytes.
- The unavailable capture count is low, but includes one unrelated INS video. Check whether both records share a missing staging path, event timing race, or descriptor shape before concluding the failure is BRI-specific.

### X source gap

- RSSHub process health is good, but its Torch feed omits the post ID. Debug the live Twitter route's account-specific upstream visibility, cache, and provider/auth state. Keep VPS credentials and runtime configuration out of this repository.
- If the post is to be recovered, first verify its author, relation type, thread completeness, and eligibility. Use only the X watcher's [explicit bounded `recover-missing` contract](../../cron-x-account-watch/AGENTS.md:234); do not rewind the source cursor or resend directly to Discord.

### Shared delivery services

- Current Delivery Owner counters and the seven-day ledger show no shared Discord queue failure. Current Source Media health and warning logs show no broad outage; its success-only ledger leaves transient upload failures unproven. These services are lower-priority suspects for the present symptoms than the catalog transition, WhatsApp archive capture, and RSSHub feed coverage.

## Safe continuation checklist from the initial audit

The catalog transition work in item 1 was completed and verified in the
2026-10-01 follow-ups above. The remaining items preserve the original audit
leads; recheck current state before acting.

1. Re-read current effective catalog, revisions 5 to 7, and exact deployed state markers. Identify and review package-owner future-only transition plans for Telegram 5 to 7 and RSS 4 to 7. Never hand-edit revision markers, reset cursors, or replay historical posts.
2. Decide whether Phintas should receive `trading_plans` and parent-reply resolution. If yes, make that a separately reviewed catalog and adapter change after the catalog transition is understood.
3. Inspect Market News retry and lease state with payloads redacted. Determine whether the 32 due candidates are still present, how the expired lease should recover, and whether any of the six earlier 429s correspond to these candidates.
4. Trace the WhatsApp bridge queue media descriptor and staging-to-archive copy for the identified event using sanitized metadata. Do not inspect disposable staging or move the cursor manually.
5. Determine the Torch post author and relation type from a permitted source view, then inspect RSSHub route/provider visibility. If recovery is warranted, use its bounded preview contract after reviewing eligibility; do not rewind the cursor or post directly.
6. Recheck recent X and Stockbit logs after the stale records. Keep historical log counts separate from current queue or delivery state.

No production state, schedules, destinations, or services were changed during this audit. No replay, manual schedule run, synthetic message, or test post was performed.

## 2026-10-01 follow-up: Telegram recovery and Phintas reminder

A read-only production snapshot at 14:09 WIB showed `origin/main` and the last
successful release at `3ae575c48ceac79cc95e5625f92b0b19dc38bb44`, release CI
successful, the Telegram source reader active at its existing one-minute
cadence, and all eight desired interval schedules matching the Hermes
registry. The source catalog and reader state were both at revision 7. This is
the state after catalog recovery. The separate Market News state-root
reconciliation was still pending; this snapshot does not prove a new News
delivery.

The Phintas finding is corrected by later evidence:

- Telegram resolves `@phintasprofits` to channel ID `1444713822`; resolving the
  old `@phintraprofits` username returned an error. The Source Catalog still had
  `trading_plans` enabled on `telegram:phintraprofits`, whose verified provider
  ID is the same numeric channel ID. Its adapter resolves that endpoint from
  authenticated dialogs by ID. The Phintas-named endpoint had only the three
  News capabilities. This is a stale alias and duplicate-cursor issue, not a
  capability failure for message `35530`.
- The source event existed under `telegram:phintraprofits`, with `swing_plan`
  work marked `done` and a durable owner effect receipt. Its Delivery Owner
  operation was `delivered` to `#id-stocks-swing` at 09:25 WIB on October 1,
  roughly 20 hours after the source timestamp. This was stale work drained
  after intake resumed, not a timely forwarding success.
- The late All-channel message was deleted and its removal verified. The
  Swing Board owner had also recorded the reply as dated `Source context` in
  the existing INDF topic. That Board history remains with its owner; it is
  not a current alert.
- At the 14:09 WIB read, both Phintas endpoint cursor files were already at
  `35556`, and Source Inbox had zero pending, leased, or executing work. The
  future canonical-handle transition must preserve the already initialized
  Phintas cursor. It must not seed or replay a cursor, or resend `35530`.
- The event replied to companion post `35447`. The source adapter carried its
  reply ID, and the Board received the item as source context. For future
  replies, the Swing owner can link a reply only when the referenced plan is
  already known in its state; otherwise the Board's context behavior remains
  the source-faithful outcome.

The completed future-only canonical route work is documented in
[`Phintas Swing route design`](../superpowers/specs/2026-10-01-phintas-swing-route-design.md)
and [`implementation plan`](../superpowers/plans/2026-10-01-phintas-swing-route.md).
Other findings from this audit remain separate workstreams; do not treat the
Telegram recovery as proof of X, RSS, WhatsApp, or Stockbit delivery.

## 2026-10-01 follow-up: Phintas transition and Market News reconciliation gate

A read-only production snapshot at 16:08 WIB showed `origin/main` and the
successful release at `c955b7a8da6f6d4f439035270dd0b2f1b9588261`, release agent
unblocked, Hermes gateway running, and all eight desired interval schedules
matching the live registry. Seven of 13 Hermes jobs were active and six were
paused. The shared Telegram source reader was paused at desired and applied
revision 8 with its original one-minute interval. The snapshot reports
scheduler and release state only, not runtime checksums or an exercised source
to delivery event. The X account job still reported `last=error`; WhatsApp and
Stockbit jobs reported `last=ok`.

The Phintas route transition completed after PR #35 merged and released. The
catalog moved from revision 7 to 8, the Swing owner config moved from revision
1 to 2, and the existing Phintas cursor was preserved. Natural heartbeats
followed the transition, but no new post-boundary Phintas source-to-Discord
delivery has been observed. Message `35530` was not replayed.

The current Market News state-root operation remains before archive and apply.
After the reader pause, checks found no matching source or owner process, no
active Market News agent lease, and both state locks available. The supported
Hermes job configuration has no `IDX_MARKET_NEWS_STATE_PATH` override. Neither
state file has been changed or archived, and the source schedule remains
paused.

The released reconciliation command stopped safely on canonical
`pending_delivery` candidates. Read-only Delivery Owner lookups found:

- Phintraco message `35557` has a persisted exact payload and accepted
  handoff. Its deterministic operation is `delivered`, and the owner digest
  matches the saved payload.
- Tuntun message `15063` has no saved delivery payload or handoff. Its
  deterministic owner operation lookup returned `not_found`. This means there
  is no current owner operation to preserve, but it does not explain why the
  candidate entered `pending_delivery` before the payload was persisted.
- Two package-local Stock Information events overlap canonical events whose
  delivery operations are already delivered with matching digests. The
  canonical event records and receipts remain authoritative.

A local reconciliation update now fingerprints status-only checks for
canonical pending candidates. It permits only a matching delivered operation
or `not_found` with no local accepted handoff or Discord message ID, repeats
the checks during apply, and never submits or waits on Delivery Owner work.
Accepted legacy handoffs are reconstructed with their persisted nonce and
`reconcile_before_first_create` operation setting. A confirmed local Discord
message ID must match the owner's delivered receipt. Canonical pending
stock-status deliveries remain blocking. This code and its tests are not yet
published or released. The Tuntun candidate's interruption point remains a
separate diagnosis; no cause is inferred from the missing payload.

The next state-cutover steps are to publish and release this guarded change,
then collect a fresh snapshot, archive and checksum both unchanged state
files, create and review a new package-owned preview, apply it while the
reader remains paused, and resume through the supported schedule interface.
Do not replay or backfill any historical news. Natural runs after resume must
prove future owner progress, and only confirmed Delivery Owner receipts prove
delivery.

### Adjacent RSS crash-recovery review

A review flagged that an interrupted atomic journal write could leave a
temporary file in `catalog-transitions/` and block retry of the same plan.
Inspection of the repository state at `c955b7a` found that the shared planner
already recognizes only its owner-owned, regular, mode-`0600`, exact-pattern
temporary files, excludes them from the journal comparison, and removes them
before resuming apply. The existing regression covers leftovers in both the
state root and transition directory, and rejects malformed or unexpected
entries. The focused check passed 4 tests with 32 deselected. This review item
is closed against that code state and does not require a separate RSS change;
it is not evidence of a production RSS run.
