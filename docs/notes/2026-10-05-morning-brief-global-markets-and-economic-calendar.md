# Morning brief: global markets and Indonesian economic calendar

Design research checked 5 October 2026. No Sectors or Chart-IMG quote call, Discord mutation or production operation occurred. Public-source research only. The preview continues with synthetic quote values and explicit event-date placeholders.

## Source findings

| Input | Public source | What was verified | Remaining acceptance check |
| --- | --- | --- | --- |
| KOSPI, Nikkei, QQQ | [Yahoo KOSPI](https://finance.yahoo.com/quote/%5EKS11/), [Yahoo Nikkei](https://finance.yahoo.com/quote/%5EN225/), [Yahoo QQQ](https://finance.yahoo.com/quote/QQQ/) | Public indexed quote pages identify the symbols and show dated values; KOSPI/Nikkei pages identify delayed quotes. Direct native fetches of those two pages failed. | Bounded automated snapshot access, quote timestamp, regular-session reference close and consumer-appropriate data permissions. No guaranteed free/unlimited feed is established. |
| QQQ instrument identity | [Invesco QQQ](https://www.invesco.com/qqq-etf/en/about.html) | QQQ is an ETF tracking Nasdaq-100. | Display ETF price moves in USD, not index points; never relabel QQQ as the Nasdaq index itself. |
| BI policy meeting | [Official 2026 RDG schedule](https://www.bi.go.id/id/publikasi/ruang-media/news-release/Pages/sp_2730825.aspx) | Direct page lists the October meeting on 20 and 21 October and says policy decisions are discussed on the second day. | Check amendments; the exact announcement time was not established. The 21 October decision date is inferred from the published meeting structure. |
| BPS release dates | [BPS Rencana Terbit](https://www.bps.go.id/id/arc) | Direct page explicitly identifies a schedule of BRS and publication releases. | Dynamic event rows did not appear in native extraction. Actual upcoming national release dates, time and automated extraction remain unverified. Do not substitute the past-release archive for a verified future calendar. |
| Additional BI releases | [BI calendar](https://www.bi.go.id/id/publikasi/kalender/default.aspx), [BI statistics](https://www.bi.go.id/id/statistik/default.aspx) | Official calendar is linked from the retrieved RDG page and search; direct calendar fetch timed out. | Future reserve and other release dates need verification from the published schedule. |

Context7 resolved `/ranaroussi/yfinance` and supplied current primary-project documentation. It confirms public Yahoo data access through an unofficial research/education client and an explicit rate-limit error. Cache shared quote snapshots and keep requests bounded; neither yfinance nor Yahoo is established as unlimited or a guaranteed public redistribution feed. No authenticated quote probe was made. The repository's existing VPS Yahoo integration is not proof of a working or approved morning-global snapshot adapter.

## Proposed compact global block

The user's examples are KOSPI, Nikkei and QQQ, with a circular logo emoji, signed absolute and percentage change, then the existing green/red status emoji. Recommend three lines maximum, with those three as the initial watchlist pending user confirmation. A fourth market may replace a line for a material event instead of growing an unbounded list. The user requested only a few relevant markets, not a claim that their causal influence has been statistically measured.

Use the frozen 07:30 WIB evidence window. For an Asian market open at the freeze, report a timestamped regular-session snapshot against the verified prior regular close, labeling delayed data as such. For the US instrument, use the latest completed regular session and label its session date. Exclude pre/post-market from the default daily comparison. Do not label different market sessions as a single simultaneous close. Green/red follows the signed change; exact flat uses a neutral Unicode marker. Missing/stale inputs are unavailable, not a fabricated zero.

## Existing emoji helper

Read-only source inspection of canonical `skill-profile-emoji/AGENTS.md` and `bin/profile_emoji.py` confirms center-square crop, circular transparent mask, static PNG output and a supplied-local-image `ensure-image` path. The profile resolver handles X/Instagram profiles, not arbitrary index symbols or brand URLs. Index/ETF icons need supplied or verified logo assets and the local-image path. Circular preparation can reuse the helper's transformation; guild onboarding requires the existing shared Delivery Owner operation. No emoji was created or changed during this research.

`lib-news-format/bin/news_format.py` already defines `green` and `red` custom emoji markup. Runtime messages must use real `<:name:id>` markup returned by the owner, not bare `:name:` strings or guessed IDs. The private Markdown intentionally uses shorthand placeholders until index-logo IDs are provisioned. If custom emoji is unavailable, retain the readable instrument name and a Unicode direction marker.

## Upcoming Indonesian events

Use BI for RDG/BI-Rate and other BI release schedules, BPS national advance release calendar for CPI/inflation, trade, GDP and labor releases. Public web schedules can supply event dates without consuming Sectors credits; a free combined economic-calendar API has not been verified. Consensus estimates are optional and absent unless an attributable source is available.

Recommend the next three **distinct relevant future releases**, sorted chronologically after the morning freeze, from a watchlist of BI-Rate, inflation, trade balance, GDP, foreign-exchange reserves and labor/unemployment. Deduplicate a joint BPS briefing and the two-day RDG into their economic release event, rather than consuming multiple slots for one announcement. Include event name, reference period, date/time WIB and source. A published date with no verified time remains `jam belum diumumkan`. If fewer than three are verified, show fewer; do not create dates from monthly patterns. National Indonesian events only by default, not provincial statistics or every routine publication.

Whether three refers to the next three events across dates or only today/this week, and the final fixed/global watchlist, are the remaining user decisions. The proposed interpretation is across dates, including today when the event is still ahead of the freeze.
