# Phintraco Weekly PDF Swing Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add deterministic PDF-only weekly Phintraco setup intake that delivers every validated ticker plan and matching chart to All Swing before the Board, while safely linking later updates.

**Architecture:** A bounded PyMuPDF helper extracts selectable text and embedded chart images by page geometry. The watcher stores the PDF batch and one immutable outbox event per ticker before advancing its Telegram cursor, then persists source media references before delivery. The Board owner verifies matched update identity, records explicit target changes in the current plan projection, and stores unmatched source material as context without changing plan state.

**Tech Stack:** Python, Telethon, PyMuPDF 1.28.2, existing Source Media and Discord Delivery clients, SQLite Board owner, pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-swing-board-phintraco-linkage-design.md`

## Global Constraints

- Read and deliver the Telegram PDF attachment only. Ignore the companion text post entirely.
- Accept only `PHINTAS Weekly Swing Trading Ideas_YYYYMMDD.pdf`, at most 8 MiB, with at most 12 pages and 24 complete plans.
- Use the PDF attachment Telegram timestamp converted to WIB for signal time. Keep the PDF printed report date as separate metadata.
- A stable child event key is `pdf:<telegram-message-id>:<ticker>`; preserve document section order for delivery.
- Persist the PDF and extracted charts before cursor advance. Use the private Source Media Owner for durable references. Never call Supabase directly.
- Deliver the ticker plan text and its matching chart to All Swing first. Submit the Board event only after both are acknowledged.
- Match reminders by reply lineage or one strict unique candidate. A reported single price matches an exact single level or a range explicitly present in the setup. Do not invent tolerances.
- A matched update carries the setup event key. The Board owner applies it only to that active setup. An unmatched update is context and cannot alter a plan or start a Primary episode.
- Do not rewind the live cursor, replay historical PDFs, change schedules, deploy, or post production messages in this implementation.
- Preserve existing version 1 to 3 watcher state through an atomic version 4 migration.
- Keep PyMuPDF pinned in the Phintraco runtime requirements. It needs separate host provisioning before production release because the current release agent does not install cron package dependencies.

## Review Focus

- A similarly named non-PDF message, malformed PDF, encrypted PDF, oversized PDF, or unsupported report date is held without reading companion text or moving past an unrecorded event.
- A missing, extra, repeated, or spatially ambiguous chart blocks that page; valid pages from the same PDF remain independently deliverable.
- A plan with duplicate tickers, missing levels, duplicate target ordinals, ambiguous ranges, or unsupported notation is not guessed into a Board event.
- Two same-ticker plans in one or successive PDFs retain separate stable identities and deterministic source order.
- A source-media outage, process restart, or duplicate PDF fetch cannot lose a ticker, duplicate a successful All leg, or send a Board event before the chart.
- An update with zero or multiple matching plans is visible only as labeled source context and cannot mutate the active plan, target ladder, tags, or staleness timer.

---

### Task 1: Deterministic weekly PDF parser

**Files:**
- Create: `cron-tg-phintraco-swing/bin/weekly_pdf.py`
- Create: `cron-tg-phintraco-swing/tests/test_weekly_pdf.py`
- Create: `cron-tg-phintraco-swing/requirements.txt`

**Interfaces:**
- Produces `parse_weekly_pdf(filename: str, pdf_bytes: bytes) -> WeeklyPdfResult`.
- `WeeklyPdfResult` contains `report_date`, ordered `setups`, and `quarantined_pages`.
- Each `WeeklySetup` contains `ticker`, `descriptor`, `trend`, `ma_indicator`, `potential_upside`, `potential_downside`, `entry`, `stop_loss`, ordered numbered `targets`, `page_number`, `section_number`, and JPEG `chart_bytes`.
- Each `QuarantinedPage` contains `page_number` and a sanitized `reason` string. A document-level filename, size, encryption, page-count, or report-date failure raises `WeeklyPdfError`.

Before Step 1, install the pinned parser into this plan's ignored test-only package directory, leaving the shared project environment unchanged:

```bash
../../.venv/bin/python -m pip install --disable-pip-version-check --target .superpowers/sdd/2026-09-28-swing-board-phintraco-pdf-intake/site-packages PyMuPDF==1.28.2
```

- [x] **Step 1: Write synthetic PDF tests first**

Create three-page PDFs in memory with PyMuPDF. Put two numbered setup sections in each page's left column and one 2:1 JPEG chart aligned with each section in the right column. Test a full parse, the combined `Target Price 1: 1000 ; SL <900` line, unnumbered target ranges such as `6900-7000`, report-date extraction, and original chart bytes.

Add rejection tests for a wrong filename, zero or more than 12 pages, a PDF larger than 8 MiB, an encrypted PDF, duplicate ticker sections, missing entry/stop/target, duplicate target numbers, and a page where a chart is absent or has no unique section match. Assert malformed input raises `WeeklyPdfError` or marks only the affected page quarantined, as appropriate.

- [x] **Step 2: Run the focused parser tests and verify they fail**

Run: `PYTHONPATH=.superpowers/sdd/2026-09-28-swing-board-phintraco-pdf-intake/site-packages ../../.venv/bin/python -m pytest -q cron-tg-phintraco-swing/tests/test_weekly_pdf.py`
Expected: FAIL because `weekly_pdf` and its result types do not exist.

- [x] **Step 3: Implement bounded geometry extraction and source parsing**

Add exact dependency pin `PyMuPDF==1.28.2`. Open bytes with `pymupdf.open(stream=pdf_bytes, filetype="pdf")`; reject encrypted or unsupported documents. Read text blocks and embedded image blocks with their page bounding boxes. Recognize only the fixed numbered ticker heading and explicit `ACTION : Buy` sections. Parse entry, stop-loss, targets, trend, MA indicator, potential ranges, and printed date without numeric interpretation. Accept chart images only when their dimensions and right-column geometry match the established chart shape, then assign by section vertical bounds. Require exactly one chart for every setup on a page and quarantine that page if any section or image association is ambiguous.

- [x] **Step 4: Run focused parser tests and both supplied sample PDFs**

Run: `PYTHONPATH=.superpowers/sdd/2026-09-28-swing-board-phintraco-pdf-intake/site-packages ../../.venv/bin/python -m pytest -q cron-tg-phintraco-swing/tests/test_weekly_pdf.py`
Run the same helper against `/Users/absolutepraya/Downloads/PHINTAS Weekly Swing Trading Ideas_20260921.pdf` and `/Users/absolutepraya/Downloads/PHINTAS Weekly Swing Trading Ideas_20260928.pdf` in a temporary no-output script. Assert six ordered plans, six distinct JPEG charts, and the exact ticker and level values seen in the PDFs. Do not add either source PDF to Git.
Expected: tests pass; the two supplied files each yield six validated plans.

- [x] **Step 5: Commit the parser task**

```bash
git add cron-tg-phintraco-swing/bin/weekly_pdf.py cron-tg-phintraco-swing/tests/test_weekly_pdf.py cron-tg-phintraco-swing/requirements.txt
git commit -m "feat(phintraco): parse weekly swing PDFs"
```

### Task 2: Versioned state and PDF batch ingestion

**Files:**
- Modify: `cron-tg-phintraco-swing/bin/scan.py`
- Modify: `cron-tg-phintraco-swing/tests/test_scan.py`

**Interfaces:**
- Consumes `parse_weekly_pdf` from Task 1.
- `enqueue_call(state, call, now, *, event_key=None, delivery_order=0, pdf_batch_id=None)` creates legacy numeric events or per-ticker PDF events.
- State version 4 adds `pdf_batches`, `source_plans`, and `quarantined_documents` maps.
- A PDF outbox event stores its stable `event_key`, source message ID, delivery order, PDF batch ID, page and section, PDF digest/path, and chart path.
- Each source-plan index record stores immutable event key, ticker, levels, source timestamp, document message ID, page, and section.

- [x] **Step 1: Add failing state migration and multi-plan ingestion tests**

Add a version 2 fixture with one legacy numeric outbox event. Assert `load_state` migrates it to version 4, preserves its phase, delivery key, retry count and chart path, and supplies empty new maps.

Add an ingestion test using a fake Telegram document with a PDF filename, `application/pdf`, and a published timestamp. Stub only `parse_weekly_pdf` to return two ticker plans. Assert the cursor advances only after durable batch and child records exist, child keys are `pdf:35448:AADI` and `pdf:35448:ITMG`, order is stable, and both signal timestamps equal the document timestamp in WIB. Include an adjacent plain text message and assert its content is never parsed as a plan.

Add a quarantined-page test: valid-page plans are enqueued, the failed page reason is durably stored, the document is marked degraded, and retries do not duplicate any child.

- [x] **Step 2: Run the focused state and ingestion tests and verify they fail**

Run: `PYTHONPATH=.superpowers/sdd/2026-09-28-swing-board-phintraco-pdf-intake/site-packages ../../.venv/bin/python -m pytest -q cron-tg-phintraco-swing/tests/test_scan.py -k 'pdf_batch or weekly_pdf or state_v2_migration'`
Expected: FAIL because state remains version 2 and PDF messages are not recognized.

- [x] **Step 3: Add a backward-compatible version 4 migration**

Extend `_migrate_state` to migrate v1 to v2 using the existing rules, then migrate supported v2 and v3 state to v4 by preserving every existing event and adding the new event defaults. Add validators for document batches, source-plan records, quarantine records, and composite PDF keys. Sort pending events by `(source_message_id, delivery_order, event_key)` so ordinary numeric events retain their order.

- [x] **Step 4: Recognize and ingest only qualifying PDF attachment messages**

Inspect `message.document.mime_type` and the Telegram filename. Download bytes only for the exact weekly PDF pattern. Atomically persist the PDF and every accepted chart under the private media directory, compute the PDF digest, build one `SwingCall` per accepted plan with the Telegram published timestamp, and persist all batch, source-plan and outbox records before setting and saving the observed cursor. Save page quarantines and increment malformed/degraded counts. Companion text is not passed to the parser.

- [x] **Step 5: Run focused state and ingestion tests**

Run: `PYTHONPATH=.superpowers/sdd/2026-09-28-swing-board-phintraco-pdf-intake/site-packages ../../.venv/bin/python -m pytest -q cron-tg-phintraco-swing/tests/test_scan.py -k 'pdf_batch or weekly_pdf or state_v2_migration'`
Expected: all added tests pass and prior state fixtures remain valid.

- [x] **Step 6: Commit the state and ingestion task**

```bash
git add cron-tg-phintraco-swing/bin/scan.py cron-tg-phintraco-swing/tests/test_scan.py
git commit -m "feat(phintraco): persist weekly PDF events"
```

### Task 3: Durable media, ordered All delivery, and strict update matching

**Files:**
- Modify: `cron-tg-phintraco-swing/bin/scan.py`
- Modify: `cron-tg-phintraco-swing/bin/bursawatch-tg-phintraco-swing.sh`
- Modify: `cron-tg-phintraco-swing/tests/test_scan.py`
- Modify: `cron-tg-phintraco-swing/tests/test_wrapper.py`

**Interfaces:**
- Adds outbox phase `pending_source_media` for PDF plans.
- `match_source_plan(call: SwingCall, state: dict, reply_parent_id: int | None) -> str | None` returns exactly one matched source-plan key or `None`.
- PDF Board event keys are `phintraco:<channel-id>:weekly:<document-message-id>:<ticker>`.
- A matched update includes `matched_setup_event_key`; an unmatched status or reminder becomes Board `context` with no plan reference.

- [x] **Step 1: Add failing media, ordering, and plan-match tests**

Test a fake Source Media client that records uploads and returns durable references. Assert the PDF is uploaded once under a stable document key, each chart uses its own stable ticker key, retries reuse the same keys and bytes, and no All text is sent until both required references are durable. Assert All text then matching chart then Board submission, with Board event keys unique per ticker and PDF.

Test exact range matching, exact single-value matching, wrong ticker, wrong target ordinal, mismatched supplied entry or stop, stale chronology, and ambiguous identical source plans. Test a direct PDF reply selects only that document's same-ticker plan. Assert unmatched updates have no matched setup key and are rendered as context.

- [x] **Step 2: Run the focused tests and verify they fail**

Run: `PYTHONPATH=.superpowers/sdd/2026-09-28-swing-board-phintraco-pdf-intake/site-packages ../../.venv/bin/python -m pytest -q cron-tg-phintraco-swing/tests/test_scan.py -k 'source_media_pdf or weekly_pdf_order or matched_setup or strict_range_match'`
Expected: FAIL because there is no PDF source-media phase or strict plan index matcher.

- [x] **Step 3: Upload idempotent source media before All delivery**

Load `SourceMediaClient` through the shared client package. Read upload URL and token-file path from the established `BURSAWATCH_SOURCE_MEDIA_URL` and `BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE` variables. Upload the document once per batch with kind `document`, content type `application/pdf`, and stable idempotency key `telegram:channel:<channel-id>:message:<message-id>:weekly-pdf`. Upload each chart as kind `image` and content type `image/jpeg` with a key ending in `weekly-chart:<ticker>`. Persist service references and digests before advancing the event to `pending_text`.

- [x] **Step 4: Render and drain ticker events in source order**

Build one source-faithful Swing message per ticker with the shared formatter, descriptor and report context in the reasons field, the PDF Telegram link, and the attachment published time. Store chart bytes on disk until Board acknowledgement. Keep each event's All text and chart adjacent. Submit to the Board only after both legs succeed. Update `board_event_payload` to use the per-ticker stable event key and include the matched setup event key when verified.

- [x] **Step 5: Implement strict unique update matching**

When a reminder or status replies to a PDF message, resolve only a source-plan record with that parent message ID and ticker. Otherwise compare ticker, published chronology, each supplied entry/stop/target value, and any explicitly achieved target ordinal/value against indexed plans. A reported value matches an explicit source range only when it falls within that range; a single source value requires exact equality. Ignore a target amendment as a match anchor only when it is exactly the next target ordinal. Return a plan key only for one unique candidate. Convert zero or multiple matches to source context, preserving source text and attribution while preventing Board plan mutation.

- [x] **Step 6: Run focused watcher and wrapper tests**

Run: `PYTHONPATH=.superpowers/sdd/2026-09-28-swing-board-phintraco-pdf-intake/site-packages ../../.venv/bin/python -m pytest -q cron-tg-phintraco-swing/tests/test_scan.py cron-tg-phintraco-swing/tests/test_wrapper.py`
Expected: all tests pass, with existing individual-photo delivery and Board retries unchanged.

- [x] **Step 7: Commit the watcher delivery task**

```bash
git add cron-tg-phintraco-swing/bin/scan.py cron-tg-phintraco-swing/bin/bursawatch-tg-phintraco-swing.sh cron-tg-phintraco-swing/tests/test_scan.py cron-tg-phintraco-swing/tests/test_wrapper.py
git commit -m "feat(phintraco): deliver weekly PDF plans"
```

### Task 4: Board owner target updates and no-mutation context

**Files:**
- Modify: `cron-dc-swing-board/bin/models.py`
- Modify: `cron-dc-swing-board/bin/engine.py`
- Modify: `cron-dc-swing-board/bin/store.py`
- Modify: `cron-dc-swing-board/tests/test_models.py`
- Modify: `cron-dc-swing-board/tests/test_engine.py`
- Modify: `cron-dc-swing-board/tests/test_store.py`

**Interfaces:**
- `SourceEvent` accepts optional `matched_setup_event_key` and the new `context` kind.
- `BoardStoreTransaction.update_plan_targets(episode_id: int, targets: tuple[str, ...])` updates only the active plan projection. The immutable source event remains unchanged.
- Context events attach as source replies to an existing or matching historical episode. With no episode, they are persisted and marked processed without creating a new Primary episode.

- [x] **Step 1: Add failing Board contract and lifecycle tests**

Test that a `context` event is accepted, a context event with no episode creates no episode or thread, and a context event with an open episode creates one source reply without changing lifecycle, tier/status tags, plan values, or `latest_material_at`.

Test a KETR setup event with targets `1000` and `1050`, followed by a matched reminder with source status `First target 1000 achieved; Target 3: 1100`. Assert target 3 is added to the current active plan, TP1 remains the market state, the event retains the setup event key, and the original setup `source_events` payload still has only its original two targets. Test that a different or absent match key cannot amend targets.

- [x] **Step 2: Run focused Board tests and verify they fail**

Run: `../../.venv/bin/python -m pytest -q cron-dc-swing-board/tests/test_models.py cron-dc-swing-board/tests/test_engine.py cron-dc-swing-board/tests/test_store.py -k 'context_event or matched_target_update or setup_reference'`
Expected: FAIL because `context` and setup references are not accepted and plan targets are not amendable.

- [x] **Step 3: Extend the immutable Board event contract and migrate storage**

Add optional `matched_setup_event_key` to `SourceEvent`, accept `context`, and store the match key with the source event. Increment the SQLite schema version and add a nullable column with an idempotent migration. Preserve compatibility for existing source producers that omit the optional field.

- [x] **Step 4: Persist target amendments in the current plan projection**

Parse only explicit `Target 1` to `Target 6` amendments from a Phintraco reminder. Accept an update only for the active plan whose immutable source event key equals `matched_setup_event_key`. Permit replacing an existing target or appending the next contiguous target, then validate the complete levels with `parse_plan_levels`. Update `plans.targets_json` while retaining the original `source_events` payload and recording the immutable reminder event.

- [x] **Step 5: Route unmatched context without plan effects**

For `context`, enqueue a source reply only when an open episode exists; route pre-resolution events to existing historical episode logic. When no episode exists, persist and mark the context event processed without opening a new episode. A reminder with a nonmatching setup reference follows this context path and cannot update market milestone, status, tag, timer, or target ladder.

- [x] **Step 6: Run focused Board tests**

Run: `../../.venv/bin/python -m pytest -q cron-dc-swing-board/tests/test_models.py cron-dc-swing-board/tests/test_engine.py cron-dc-swing-board/tests/test_store.py`
Expected: all tests pass, including existing source event compatibility and schema migration coverage.

- [x] **Step 7: Commit the Board owner task**

```bash
git add cron-dc-swing-board/bin/models.py cron-dc-swing-board/bin/engine.py cron-dc-swing-board/bin/store.py cron-dc-swing-board/tests/test_models.py cron-dc-swing-board/tests/test_engine.py cron-dc-swing-board/tests/test_store.py
git commit -m "feat(swing-board): verify and apply target updates"
```

### Task 5: Contracts, dependency boundary, and full local verification

**Files:**
- Modify: `cron-tg-phintraco-swing/AGENTS.md`
- Modify: `cron-tg-phintraco-swing/CRON.md`
- Modify: `cron-dc-swing-board/AGENTS.md`
- Modify: `cron-dc-swing-board/CRON.md`
- Modify: `platform-bursawatch-release/release-manifest.json`
- Modify: `platform-bursawatch-release/tests/test_release_agent.py`
- Modify: `docs/superpowers/specs/2026-09-28-swing-board-phintraco-linkage-design.md`

**Interfaces:**
- The Phintraco runtime contract identifies the PDF dependency and exact one-time host provisioning prerequisite. The current release agent does not install this requirement file.
- The Board contract documents `context` and setup-linked target amendments.
- The release manifest routes the new Phintraco `requirements.txt` to its metadata unit so manifest path accounting remains complete.

- [x] **Step 1: Add failing release-manifest ownership coverage**

Add a manifest test that asserts `cron-tg-phintraco-swing/requirements.txt` maps to exactly one metadata unit and is not mistaken for a runtime deployment input. Run the focused release-manifest test and confirm it fails before changing the manifest.

- [x] **Step 2: Update runtime and Board contracts**

Replace the Phintraco weekly PDF exclusion with the PDF-only contract, timestamp and event identity rules, per-page quarantine, source-media ordering, strict update matching, and no-replay boundary. Document Board context semantics, linked target amendment behavior, and immutable source event retention. State that production release requires PyMuPDF to be installed in the Phintraco runtime first.

- [x] **Step 3: Add the dependency requirement to release path ownership**

Add `cron-tg-phintraco-swing/requirements.txt` to the existing Phintraco metadata unit in `release-manifest.json`. Do not extend the release agent or make it modify the shared Yahoo Finance Python environment.

- [x] **Step 4: Run all package and repository checks**

Run: `PYTHONPATH=.superpowers/sdd/2026-09-28-swing-board-phintraco-pdf-intake/site-packages ../../.venv/bin/python -m pytest -q cron-tg-phintraco-swing/tests`
Run: `../../.venv/bin/python -m pytest -q cron-dc-swing-board/tests`
Run: `PYTHONPATH="$(git rev-parse --show-toplevel)/.superpowers/sdd/2026-09-28-swing-board-phintraco-pdf-intake/site-packages" bash ../../scripts/test-all`
Run: `git diff --check`
Expected: all local suites pass; neither supplied PDF appears in `git status` or the diff.

- [x] **Step 5: Commit the contracts and release metadata**

```bash
git add cron-tg-phintraco-swing/AGENTS.md cron-tg-phintraco-swing/CRON.md cron-dc-swing-board/AGENTS.md cron-dc-swing-board/CRON.md platform-bursawatch-release/release-manifest.json platform-bursawatch-release/tests/test_release_agent.py docs/superpowers/specs/2026-09-28-swing-board-phintraco-linkage-design.md docs/superpowers/plans/2026-09-28-swing-board-phintraco-pdf-intake.md
git commit -m "docs(phintraco): define weekly PDF intake contract"
```

## Final Acceptance

- Both supplied PDFs each parse into six ordered setups and six matching chart JPEGs.
- A new PDF creates one independently retryable ticker event per setup, with stable idempotency across restart.
- The original PDF and each chart receive durable Source Media refs before All delivery.
- Each ticker's All plan and chart succeed before its Board event is submitted.
- KETR's setup from PDF message `35448` can be uniquely linked to its matching reminder and target 3 amendment, while TP1 remains recorded and the original PDF event remains unchanged.
- Unmatched status or reminder content is retained as context and cannot start or mutate a Primary episode.
- Local tests pass. No VPS, Control Plane, Discord, schedule, cursor, or production state changed.
