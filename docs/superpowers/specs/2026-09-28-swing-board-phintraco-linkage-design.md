# Swing Board Phintraco Setup and Update Linkage

**Date:** 2026-09-28

**Status:** Implemented and verified locally. Production dependency provisioning, deployment, and historical intake remain separate operations.

## Goal

Keep complete Phintraco plans and later source updates in the correct ticker episode. Preserve source facts, images, timestamps, and order. Never attach an update to a plan by ticker alone.

## Source evidence

The weekly source is the Telegram PDF attachment itself. Its companion text message is a separate post and is excluded completely from plan parsing and delivery. The PDF contains both the full plan text and its chart images.

The two user-provided PDFs are the same files as the Telegram attachments, by filename and byte size. Both have three pages and six complete `ACTION: Buy` plans. `pdftotext -layout` exposes the plan text as selectable text. Each page has two separate stock-chart JPEGs, visibly aligned with its two ticker plans. This supports a bounded, source-specific parser and image extractor.

Telegram document arrival is not at a fixed time. Recent attachment events in the source channel arrived at:

| PDF report date | Telegram PDF message | Published time in WIB |
|---|---:|---:|
| 2026-08-24 | 34707 | 05:43:54 |
| 2026-08-31 | 34827 | 05:46:48 |
| 2026-09-07 | 35009 | 05:21:57 |
| 2026-09-14 | 35186 | 05:50:59 |
| 2026-09-21 | 35322 | 07:27:50 |
| 2026-09-28 | 35448 | 06:05:33 |

For September 21, the separate text post arrived at 05:49:16 WIB, 1 hour 38 minutes before the PDF. For September 28, it arrived four seconds before the PDF. The watcher must detect the PDF attachment by its own message event and must not wait for or depend on the companion text.

On September 28, the KETR reminder (`35461`) replies to companion text message `35447`; the PDF is message `35448`. The reminder reports TP1 at 1000 and an explicit target 3 update to 1100. Since companion text is excluded, this reminder may update a PDF-derived episode only through the approved strict unique-plan matcher. If no single PDF plan matches the ticker, target ordinal/value, chronology, and all supplied plan levels, retain source context without changing the plan.

## User-approved rules

1. A standalone Phintraco `On support` message qualifies as a Primary setup when it identifies one ticker and contains a complete entry, stop-loss, at least one target, and a source-published timestamp. Distinguish it from a reminder by its complete standalone structure.
2. Every complete Phintraco `ACTION: Buy` plan in an accepted weekly PDF is a level 1 Primary setup. Send each plan with its matching chart. Ignore the separate companion text post entirely.
3. For the PDF event timestamp, use the Telegram published time of the PDF attachment, converted to WIB. The PDF report date is retained as source metadata. Do not use the companion text timestamp or cron processing time.
4. Each ticker setup extracted from one PDF is a distinct immutable event. Use the PDF Telegram message ID plus normalized ticker as its stable identity. A retry must not duplicate any ticker plan from that document.
5. Deliver each generated plan and its chart to All Swing first. Only after that pair succeeds may the watcher submit that plan to the Board owner. Preserve the PDF's page and reading order, along with the existing per-event text/chart adjacency and retry guarantees.
6. Link status and reminder events through reply lineage when the parent is an indexed PDF event. If the reply points to the excluded companion text or no direct PDF parent is available, use only the strict unique-plan fallback. Match the reported target ordinal/value and all other supplied fields. Use ranges only when the source explicitly states a range. Do not use ticker-only matching or invented tolerances.
7. A complete linked Phintraco status or reminder can update the plan and milestone in the same episode. Explicit target amendments update the current ladder while the original PDF source event remains immutable. Target milestones never regress. The KETR reminder therefore preserves TP1 reached and changes target 3 to 1100 in its existing episode. The update carries the matched setup event key, and the Board owner applies it only when that key names the active plan.
8. A distinct newer Phintraco BUY supersedes an open Primary episode; exact duplicate source identity is deduplicated. Existing episode close, stale, market-position, tag, and archival rules remain in force.

## PDF intake behavior

### Recognition and extraction

Read Telegram attachment messages from the configured Phintraco channel. Accept only a PDF document with the expected `PHINTAS Weekly Swing Trading Ideas_YYYYMMDD.pdf` source identity. Do not inspect, parse, render, use as a fallback, or forward the adjacent companion text message.

Use a focused Python extraction helper for this fixed source format. Extract selectable text and embedded chart images with page geometry. Associate each ticker plan with exactly one matching chart from its page using spatial position and reading order. Do not infer a chart from an adjacent Telegram message, generate a chart, or send the entire PDF as every ticker's chart.

A publishable plan must have exactly one recognized IDX ticker, an explicit `ACTION: Buy`, one entry, one stop-loss, and at least one target. Preserve source ranges, inequalities, target ordinals, descriptor, and report date. Validate all extracted tickers and normalized levels before creating delivery work. On a changed or ambiguous page layout, ambiguous chart association, malformed plan, duplicate ticker section, or unsupported PDF, durably hold the affected item and report degraded health. Never guess. A page can proceed only when each accepted plan has one complete plan block and one uniquely associated chart.

No autonomous LLM agent is needed for the observed PDFs: the text layer and separate per-stock images are extractable with deterministic tools. Keep the helper bounded to PDF parsing and image extraction. If a later PDF layout cannot be read deterministically, fail closed first; a future, separately reviewed multimodal extraction step may propose structured candidates, but code must still validate source fields and image association before delivery.

### Durable event and media handling

Treat one PDF message as a batch containing one event per valid ticker plan. Store the original PDF digest and Telegram provenance and persist each plan's parsed record and chart media before advancing delivery progress. Use the existing private Source Media Owner for durable PDF and chart objects, with opaque refs and stable idempotency keys. Never call Supabase Storage directly from the watcher.

A valid PDF batch must survive restart and retry without re-downloading or duplicating completed messages. Track per-ticker parse, All delivery, and Board handoff outcomes. If only one page or ticker is ambiguous, retain its durable blocked record while other independently validated ticker events may proceed; mark the run degraded until the blocked item is resolved.

### Time and presentation

The Telegram message that carries the PDF is the source event. Use its `published_at` for the episode title, signal date, ordering, and stale-age calculations, converted to WIB. Keep the date printed inside the PDF as report metadata. The adjacent text message and PDF file creation time do not replace the Telegram attachment event time.

Render one source-faithful plan per ticker through the shared Swing formatter, include the corresponding extracted chart, and link to the Telegram PDF attachment message. The Board owner remains the only Board state writer and Discord forum client. After successful All delivery of that plan and chart, submit its normalized event to the Board owner and retain existing receipt and retry semantics.

### Updates and unmatched events

The watcher owns Telegram reads and parses status/reminder updates. It does not search Discord. A reminder that replies to the companion text does not cause the text to be read as plan data. The watcher attempts an exact unique match against stored PDF-derived plan events using the approved ticker, target ordinal/value, supplied plan levels, and chronology rules. Zero or multiple matches, conflicting levels, or a resolved/expired candidate cannot mutate a plan. Keep such events as attributed source context under the Board rules. A context event may add a reply to an existing episode, but it must not create a Primary episode, alter plan levels, tags, milestone, or inactivity timers. If there is no episode to attach it to, retain it in the Board event ledger without opening a thread.

For the September 28 KETR case, extract and deliver the KETR plan and chart from PDF message `35448`, then apply reminder `35461` only after matching it uniquely to that plan. Do not include other companion-text content. Other complete Buy plans in the same PDF are independent setup events and are included under rule 2.

## Scope boundaries

- Ignore companion text posts completely for plan content and All Swing output.
- Do not forward the original multi-ticker PDF as an individual ticker alert.
- Do not add OCR/LLM judgment, market data enrichment, technical analysis, generated charts, or trading recommendations.
- Do not weaken numeric, chronology, event deduplication, Board routing, or lifecycle rules.
- Do not rewind the live Telegram cursor or replay the September 28 PDF automatically. A one-time intake of an already-observed PDF is a separate reviewed operation.
- No runtime, schedule, Discord, database, or media-service changes are authorized by this design document.

## Implementation boundary

The implementation plan is `docs/superpowers/plans/2026-09-28-swing-board-phintraco-pdf-intake.md`. The local implementation covers deterministic extraction, durable per-ticker events, media storage, All-before-Board ordering, strict KETR matching, the Board target-amendment contract, documentation, and regression coverage. PyMuPDF requires a separate host provisioning step before release because the current release agent does not install cron package dependencies. Production dependency installation, historical event intake, scheduler changes, and deployment remain distinct operations.
