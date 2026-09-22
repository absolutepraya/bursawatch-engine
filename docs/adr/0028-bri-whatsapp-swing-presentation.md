---
status: accepted
---

# Render BRI WhatsApp technical reviews as Swing context

BRI Danareksa Sekuritas posts with the exact leading, case-sensitive
`#TechnicalReview` marker are deterministic `id_stocks_swing` items. The LLM
must return exactly one item with an IDX ticker when the source establishes one,
a concise one-paragraph `summary` used as **Reasons**, and a `sentiment` equal
to `Bullish`, `Bearish`, or `Sideways`. The renderer does not infer a new
sentiment from generic positive or negative wording. A legacy explicit source
stance may only be used as a delivery fallback while an already-leased record
is drained.

The All Swing message follows the Phintraco shell, adapted for BRI:

```text
### <:bridanareksa:1551797903927025797> TICKER: title
-# BRI Danareksa Sekuritas

**Sentiment:** Bearish <:down:1531285063986053200>
**Sentiment date:** 22 Sep 2026 11:26 WIB

**Reasons:** one concise source-grounded paragraph

**Last updated:** 22 Sep 2026 11:26 WIB
**Board:** <#1548273399069933720>

[View on WhatsApp](<https://www.whatsapp.com/channel/0029VbAjdnb60eBhwVdJxj1c>)
```

`Sentiment date` and `Last updated` use the immutable WhatsApp publication
timestamp rendered in WIB. They are not delivery time and are not a status
field. Macro and issuer-news routes keep their compact source footer and never
emit Sentiment, Sentiment date, or Last updated as a swing status block. The
Board marker is patched in place to the direct forum-topic URL only after the
Board owner returns a materialized topic.

The delivery sequence is text, then the archive-owned image, then the typed
Board handoff. The Board payload remains `source: "whatsapp"`, `kind:
"social"`, and `plan: null`, which the Board maps to `Chart context`. The
Board owner copies the image into its private media root. The watcher retains
the content-addressed archive image for 365 days for source research, gives
Discord a real MIME-derived filename such as `bri-chart-0.jpg`, and removes
only the transient bridge staging copy after successful archive capture.

Already-delivered BRI Swing messages are repaired through the guarded
`bursawatch-wa-channel-backfill.py` helper. `discover` and `plan` are
read-only. `apply --apply` additionally requires
`WHATSAPP_CHANNEL_WATCH_ALLOW_BACKEDIT=1`, checks the operator-supplied
message-content hash and archive event, reconciles the Board event, and edits
the existing Discord message ID in place. It never replays the WhatsApp queue,
posts a replacement All message, or stores media in logs or the control-plane
database.

## Consequences

- Technical review formatting is deterministic at the source boundary while
  sentiment remains a bounded LLM classification field.
- Board handoff is retry-safe: a missing topic or failed content patch leaves a
  ready record for a later drain rather than marking the delivery complete.
- Media filenames are presentation metadata only. Archive paths remain
  content-addressed and extensionless, so changing Discord upload names does
  not alter archive identity or retention.
- Back-editing requires an explicit manifest because old outbox records did not
  persist Discord message IDs. Message IDs and content hashes make the repair
  auditable and prevent edits after an operator-visible content change.
