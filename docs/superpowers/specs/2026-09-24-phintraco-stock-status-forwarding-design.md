# Phintraco Stock Information status forwarding

## Status and intent

This design adds a deterministic status alert path to the existing
`cron-tg-market-news` watcher. It forwards each newly published Phintraco
`Stock Information` post as one grouped Discord message in `#id-stocks-news`.
The alert summarizes the effective-date lists for UMA, suspension, and FCA
status so they are visible during the market open.

The two reference posts are Telegram messages 35326 and 35377 from
`@phintasprofits`. The first contains populated lists in all five categories.
The second uses `>-` for empty UMA, Suspend, and FCA In categories, and has
WAPO and NASI under Unsuspend plus UNSP under FCA Out.

The status path is deterministic. It does not call the agent classifier or
fetch Yahoo Finance quotes. Other supported Phintraco post types and Tuntun
news retain their current paths.

## Operator-visible message

The output order and labels are fixed:

1. UMA
2. Suspend In
3. Suspend Out
4. FCA In
5. FCA Out

Source labels map as follows: `Unusual Market Activity (UMA)` to UMA,
`Suspend` to Suspend In, and `Unsuspend` to Suspend Out. `FCA In` and `FCA Out`
keep their names. Every section is present in every message. A category with
no tickers renders as `(None)`. Ticker bullets retain their source order.

The header uses the post's effective date, with the English three-letter
weekday and `DD Mon YYYY` date. It uses the Phintraco custom emoji and the
existing Tuntun-style Markdown heading. There is no separate Phintraco
attribution line. The footer is a clickable Markdown link to the source
message. The existing text sender renders it as clickable text, not as a
native Discord button. There is exactly one empty line before the footer.

For message 35377, the complete Discord content is:

```text
### <:phintraco:1531272488645038091> Stock Status: Wed, 23 Sep 2026

**UMA:**
(None)

**Suspend In:**
(None)

**Suspend Out:**
- WAPO
- NASI

**FCA In:**
(None)

**FCA Out:**
- UNSP

[View in Telegram](<https://t.me/phintasprofits/35377>)
```

The weekday is derived from the effective date, not the poll time or Telegram
publication timestamp. The link uses the source channel and message ID.

## Source and parsing contract

Only a newly observed message from the `phintasprofits` source whose first
line is exactly `Stock Information` is handled by this path. It must contain
exactly one parseable `Effective date : D Month YYYY` line and exactly one
heading for each of these five source sections:

- `Unusual Market Activity (UMA)`
- `Suspend`
- `Unsuspend`
- `FCA In`
- `FCA Out`

The source examples use a colon after each heading, one `>ABCD` quoted line
per ticker, and `>-` for an empty category. The parser may normalize
surrounding whitespace and the spacing before a heading colon, but must not
infer categories or tickers from prose. It accepts the source's empty marker
or an otherwise empty body for a present category. It validates ticker lines
against the watcher's four-uppercase-letter IDX ticker convention and
deduplicates repeated tickers within a category while preserving first-seen
order. A ticker may occur in more than one category, as LIFE and GRPH do in
message 35326. Source section order may vary; Discord section order remains
fixed.

All five categories must parse before any Discord content is made. A missing
or duplicate expected heading, an unrecognized status heading, an invalid
effective date, or malformed category entry rejects the whole message. No
partial alert is sent. The known Phintraco research attribution and disclaimer
footer may be ignored after the status sections. An unknown category is not
silently omitted.

## Intake, delivery, and durable state

The watcher intercepts `Stock Information` messages before the existing path
creates one issuer candidate per ticker. It creates one status event keyed by
the Phintraco source message identity. A post with all five categories empty
still creates and sends an alert.

The event stores the parsed categories, source URL, and complete rendered
Discord payload in the existing watcher state before attempting delivery.
Delivery targets the existing `id_stocks_news_channel_id` route only. It uses
the watcher text-delivery path and idempotent Discord nonce. A transient
Discord failure retains the identical payload and event identity for retry
using the existing delivery retry behavior. Success marks the event
delivered. Re-reading the same Telegram message cannot create a second
Discord post.

Malformed or unsupported posts are recorded as rejected, withheld from
Discord, and make the run degraded. The rejection is persisted before the
input cursor advances, so the cursor can move without silently discarding the
failure. Posts above Discord's 2,000-character content limit are also
rejected and reported as degraded; they are not split or truncated. No raw
post body is added to operational heartbeat output.

The watcher processes new Telegram messages only. It does not watch edits,
backfill old messages, rewind the existing cursor, or add a manual replay
path for this feature. A malformed message remains rejected even if the
source later edits it.

## Schedule and production boundaries

The alert is delivered on the next invocation of the existing
`bursawatch-tg-market-news` schedule. Its package contract documents a
one-minute baseline, but an administrator can change or pause the live job.
Before implementation, inspect the effective live cadence read-only and use
it as found. This design does not authorize changing the schedule, route
configuration, or any production state.

The existing provider cursor remains the boundary between historical and new
messages. There is no launch-time history replay. Existing Tuntun delivery,
Phintraco news classifications, retry policy, heartbeat destination, and
other Discord routes remain unchanged.

Implementation and deployment remain separate from this design approval.
The implementation must follow the Bursawatch release contract: update the
package source and its operating documentation together, preserve existing
state, use the package's isolated no-post verification, and leave production
schedule changes, runtime writes, and test posts out of ordinary source
implementation.

## Out of scope

- Monitoring edited Telegram messages.
- Adding sources or accepting Stock Information posts from other channels.
- Forwarding this event to any channel other than `#id-stocks-news`.
- Per-ticker cards, AI classification, Yahoo Finance lookup, or company
  summaries.
- Adding new status categories automatically. An unrecognized category
  rejects the post until the parser contract is deliberately updated.
- Splitting or truncating a message that exceeds Discord's limit.
- Backfilling or replaying messages published before deployment.
- Changing the live schedule, channel configuration, or production state.

## Implementation acceptance criteria

- Messages 35326 and 35377 parse into the expected five categories and
  effective dates; message 35377 renders exactly in the format shown above.
- The renderer always emits the five sections in the specified order,
  renders empty values as `(None)`, and emits one bullet per distinct ticker
  per category in first-seen source order. A ticker present in multiple
  categories remains in each applicable section.
- Only new `Stock Information` messages from `phintasprofits` use this path.
  Other Phintraco types retain the existing classifier flow.
- A valid post sends one grouped alert to the existing ID stocks news route,
  including when every section is empty. No AI or quote lookup runs for it.
- Malformed, incomplete, duplicate-heading, duplicate-date,
  unknown-category, or oversized input sends nothing, records a rejection,
  and marks the run degraded.
- Event identity and persisted payload make repeated reads and retry attempts
  idempotent. Retries reuse the stored Discord content and nonce identity.
- The footer link points to the exact Telegram source post and has one empty
  line before it. Discord content is never split or truncated.
- Existing cursor state is preserved; no historical message is replayed and
  edits do not trigger alerts.
- Isolated no-post verification proves source parsing, exact rendering,
  routing selection, idempotency, retry persistence, and rejection behavior.
  It does not claim live Discord delivery or scheduler application.
