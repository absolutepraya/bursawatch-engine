# Instagram Market Noise Boundary

Status: superseded by [ADR-0013](0013-llm-owned-content-relevance.md)

Instagram watcher publications are forwarded only when their central thesis is substantive stock-market, issuer, or macro analysis. Generic trading and investing education, mindset or psychology advice, and actionable trade setups are treated as noise even when they mention a ticker; a target derived from earnings, fundamentals, or valuation remains substantive analysis. These are model-owned relevance rules. OCR is supplied as context to the LLM and must not be used as a pre-LLM word-co-occurrence filter, because image text can contain factual terms such as ownership percentages inside substantive issuer analysis.

## Consequences

The Instagram watcher may forward fewer posts than the X watcher because Instagram has a stricter model-level boundary against trading calls and technical setups. The LLM sees every OCR-prepared publication before making that relevance decision. The canonical routing vocabulary is shared with X through `macro_news` and `id_stocks_news`; the older `macro` and `id_stock` values remain accepted only as submission aliases for compatibility. The shared cross-watcher policy is now recorded in ADR-0013.
