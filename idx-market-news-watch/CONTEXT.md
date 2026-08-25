# idx-market-news-watch context

- **Company Candidate**: One issuer-specific, ticker-bound record extracted from one allowed provider message. A Corporate or Stock Information source message can create more than one candidate, but each candidate retains that original provider, message ID, publication time, source URL, text, and direct-image eligibility.
- **Source Event Identity**: The durable identity of a candidate, formed from its provider, source message ID, and ticker. It prevents the same issuer extraction from being reintroduced while allowing distinct issuer candidates from one message.
- **Standalone Delivery**: Every eligible classification posts as one text-only Discord message after deterministic validation and cross-provider deduplication.
- **Direct Source Image**: A photo retrieved from an exact Telegram source message. This delivery path is disabled by the text-only delivery contract.
- **Cross-provider Duplicate**: Two candidates from different providers with the same ticker and event class, at least two normalized material facts in common, and publication times within 24 hours. Uncertain matches and distinct developments remain separate.

## Agreed delivery and presentation contract (2026-07-23)

- **Market-data timing**: Every delivered entry uses Yahoo Finance data for the IDX trading session. During the regular IDX session it uses the current regular-session price; outside it uses the latest official close. Render it as `*Harga terakhir (IDR):* X`, then `<:green:...>1D: +X (+X,XX%)`, then `<:red:...>1W: -X (-X,XX%)`. Positive changes use `:green:`, negative changes use `:red:`, and zero changes use `:grey:`; emoji markers have no following space.
- **Price resilience**: A missing, invalid, or stale Yahoo quote must not suppress valid news. Omit only that entry's market-data line and emit a degraded `#hermes` heartbeat.
- **Canonical issuer name**: Resolve the company name from Yahoo's canonical name, with the source wording as a fallback.
- **Entry heading**: Do not show a `COMPANY NEWS` or tier header. The entry begins `### :tuntun: ADMR (Name of The Company)` or `### :phintraco: ADMR (Name of The Company)`, rendered with the matching Discord custom emoji.
- **Entry body**: Render an Indonesian paragraph of one to five complete factual sentences, using only as many sentences as the source needs, with normal punctuation rather than bullet points.
- **Entry source link**: The replacement emoji-based format omits the original-message link.
- **Entry separator**: Place `┈┈┈┈┈┈┈┈┈┈┈┈┈` between the summary paragraph and market-data block.
- **Timestamps**: Do not show a per-entry source timestamp or price-snapshot timestamp.
- **Standalone layout**: Each eligible ticker posts immediately as its own Discord message, beginning directly with the agreed issuer heading. Do not prepend a market-session heading or batch it with any other ticker.
- **Text-only delivery**: Every standalone delivery is text-only. Do not retrieve or post a follow-up source image, even when the originating Telegram message contains one.
- **Delivery retry**: If Discord delivery fails, retain that one item and retry it with its durable payload. Do not mix it with any other item.
- **Decision status**: The presentation and delivery contract above is agreed. Raise further questions only when they materially affect delivery, reliability, or news coverage.
