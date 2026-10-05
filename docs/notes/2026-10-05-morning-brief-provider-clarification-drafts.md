# Morning brief provider clarification drafts

Prepared for review only. No email, support ticket or external message was sent. These questions seek the provider's applicable permission and technical contract, not a legal interpretation of generic terms. No account identifiers, keys or credentials are included.

## Sectors

Recipient lead: help@sectors.app, listed on the [official API page](https://sectors.app/api). Verify the recipient before any authorized send.

Subject: Financial API caching and derived morning-brief charts

We are designing a noncommercial Indonesian market morning brief using an existing Sectors API account. We plan to cache daily stock closes and IHSG closes privately, import sector membership once, and collect market-cap snapshots weekly. Derived sector and custom conglomerate rotation charts would be posted with source attribution in Discord and may appear in a hackathon demonstration. We would not distribute a raw-data download or API credentials.

Could you confirm which account or API terms apply, whether private persistent caching and publicly shared derived charts are permitted, and any attribution, retention or plan requirements? The general terms restrict systematic compilation and automation, while the API documentation describes programmatic data retrieval; we want to follow the API-specific permissions.

Could you also confirm whether the structured companies screener's market_cap and last_close_price use the same trading session, whether a bulk cap-effective date is available, and whether the daily and full-universe close endpoints consistently return split-adjusted, dividend-unadjusted prices? We observed matching DSSA historical closes across both endpoints around its 9 April 2026 split. Finally, what account request-rate window applies, and should clients expect Retry-After or a structured code distinguishing temporary throttling from quota exhaustion?

## Chart-IMG

Recipient lead: support@chart-img.com, listed on the [official site](https://chart-img.com/). Verify the recipient before any authorized send.

Subject: BASIC plan permission for daily Discord chart snapshots

We are designing a noncommercial daily Indonesian market morning brief. On a BASIC account, we would render one IDX Composite daily chart from a public shared TradingView layout containing public LuxAlgo Smart Money Concepts and RSI divergence. We would retain TradingView, LuxAlgo and Chart-IMG identification and post the PNG as a Discord attachment, with possible use in a hackathon demonstration. The shared-layout render would use the non-storage endpoint and no private TradingView session cookies.

Could you confirm whether this distribution is permitted on BASIC, whether written consent or a different plan is required, and what attachment-retention and attribution rules apply? The API documentation describes worldwide publication through storage endpoints, while the terms describe personal/free restrictions. We would appreciate clarification of the applicable permission for this specific use, including the difference, if any, between public-storage URLs and externally attached PNGs.
