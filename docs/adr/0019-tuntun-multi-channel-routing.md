---
status: accepted
---

# Tuntun multi-channel routing

Tuntun standalone news and bounded Midday or Evening Update segments use a closed LLM route of `id_stocks_news`, `macro_news`, or `exclude`, with the deterministic scanner enforcing the destination and per-update budget. An update may deliver its eligible lead plus at most two selected items from the combined `Macro & Global` and `Industry` sections, so Industry stays in `#macro-news` rather than creating a channel or multiplying alerts. Every delivered Tuntun card carries only a Markdown Telegram link, rather than a native Discord component.
