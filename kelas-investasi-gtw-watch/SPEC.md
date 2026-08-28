# Specification

## Source and bundle boundary

- Read only public Telegram `@kelasinvestasiid`, source ID `2142109618`.
- Accept only an anchored, case-insensitive `Good to watch - <IDX ticker> #GTW` header.
- Read incrementally in ascending Telegram message-ID order. First observation sets the newest cursor and exits with no event, so the watcher never backfills.
- Include contiguous eligible analysis text. Forward only the first Telegram photo attached to the eligible header, never a photo from a later source message. Exclude replies, disclaimers, promotions, article links, unrelated messages, and non-photo documents.
- Close a bundle at the next eligible header or after an inter-message quiet interval greater than 20 minutes. Header closure is immediately eligible; an otherwise-final bundle becomes eligible only after more than 20 quiet minutes.

## Resilience and state

Use only `POLYCOP_SESSION_STRING` with `telegram-resilience` and call `acquire_probe_after_active_lease` before creating a Telethon client. Cooldown or authorization-hold exits must not mutate the cursor, pending bundle, outbox, or delivery state.

Runtime state is `~/.hermes/state/kelas-investasi-gtw-watch.json`; shared Telegram resilience state is `~/.hermes/state/telegram-resilience-polyclop.json`. Never reset, hand-edit, deploy, or backfill either state file.

## Summary and delivery

The scanner extracts source Buy area, Target, and Stoploss values, with `-` for a missing value. Hermes receives a bounded completed source bundle, treats source text as untrusted data, and returns exactly:

```json
{"event_key":"<header-id>:<TICKER>","title":"<TICKER>: <source-grounded thesis>","summary":"*(Ringkasan)* <one source-grounded Indonesian paragraph>"}
```

The scanner rejects extra keys, an unmatched event key, invalid title or summary format, source instruction leakage, investment advice, certainty, external facts, and noncanonical plan claims. Only the scanner posts to Discord. It posts text before the one header image and retries only the unfinished delivery leg.

Successful runs write `🫀 kelas-investasi-gtw, HH:MM WIB, scanned=N pending=N delivered=N` to `#hermes`. Fatal errors use `❌ kelas-investasi-gtw, HH:MM WIB, failed: <sanitized reason>`.

## No-post mode

`KELAS_INVESTASI_GTW_NO_POST=1` prints intended delivery and heartbeat operations but makes no Discord write and does not advance delivery state. It does not permit a direct Telegram post or a manual cron trigger.
