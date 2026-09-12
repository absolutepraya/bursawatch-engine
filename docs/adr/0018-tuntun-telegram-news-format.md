---
status: accepted
---

# Tuntun Telegram news alert format

Tuntun alerts use a persisted LLM-generated ticker-prefixed sentence-case title, a plain validated news body, and an unconditional `*(Ringkasan)*` marker because every eligible item uses the LLM summary path. Their intake accepts both bundled company entries and issuer-specific standalone long-news posts with a ticker anywhere in a decorated headline. Their market block uses bold values for 1D, 1W, 1M, and 3M comparisons with dot-decimal percentages, while Phintraco keeps its existing layout. New formatting is future-only, and any already-persisted delivery payload is retried verbatim.

The title is part of the Tuntun classification contract so retries and delivery do not need another model call. The marker is rendered unconditionally because the validated body is always the LLM's summary, while the source text remains out of Discord. Four horizons use five, 22, and 66 earlier available daily observations for 1W, 1M, and 3M. Persisted pending payloads are not rewritten because changing them could alter an in-flight delivery's idempotent content after a formatter deployment.
