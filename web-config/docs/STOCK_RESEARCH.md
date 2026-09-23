# Research integration decision (pending)

The teammate's backend at `96b83fdbca6e9383183d3ded5d42f23a8c73fc8a`
exposes no market-data or stock-research API. Existing watcher records do not
establish that reusable price history or fundamentals are available to the web.
The tracked market-news and swing-board price helpers use Yahoo Finance;
the `sectorsapp` Instagram source is not a Sectors API integration. This review
does not establish whether the separate VPS has an untracked MCP integration.

The user declined direct Sectors API use and credit consumption. Do not add a
web provider key or make paid market-data requests for this feature.

Investigate whether the teammate already has cached research data that can be
shared through an approved read-only interface, or whether an authorized free
embed can provide the requested view. Confirm availability, permitted use,
source dates and coverage before choosing an approach. Do not copy backend
credentials, access its database directly or substitute sample figures for
missing market data.

No stock-research route, provider integration or live-data verification is
claimed by this note. The implementation decision remains pending.
