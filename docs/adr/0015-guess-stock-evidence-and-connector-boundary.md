---
status: accepted
---

# Guess Stock evidence and connector boundary

## Context

The `guess-stock` skill was a VPS-local custom skill with a compact prompt but
no tracked source, no bundled fingerprint script, and an assumed TradingView
scanner. A month of user examples showed several distinct inputs: chart-only
images, screenshots with missing indicators, semantic clues, HSC/KSEI screens,
social posts, key-stats images, and combinations of those inputs. Wrong answers
most often came from using the answer-time market snapshot, accepting a visual
lookalike, or treating a search result as semantic proof.

The VPS currently has Yahoo Finance and Brave Search MCP servers that pass
connection tests. Serper is configured and enabled, but its unconstrained
`serper-mcp-server` dependency resolves MCP 2.x while the package uses the MCP
1.x decorator API. A read-only test therefore fails during startup. The
TradingView Indonesia scanner endpoint is reachable from the VPS and returns
the requested IDX columns, but no Hermes MCP connector currently exposes it.

## Decision

1. The canonical development source is `guess-stock/` in the Hermes repository.
   The runtime copy remains under
   `~/.hermes/skills/research/guess-stock/`. Raw WhatsApp transcripts and
   attachments remain outside Git. Sanitized evidence manifests and expected
   outcomes form the initial regression corpus under `guess-stock/tests/`.
2. Every request is classified into chart, keystats, clue, transaction, social,
   or hybrid evidence. Visible fields retain source and as-of metadata. Hidden
   or missing fields are not inferred.
3. The rightmost populated candle visible in a supplied chart is the temporal
   anchor. The answer-time latest candle is not a substitute. A material date
   mismatch rejects a candidate.
4. Candidate ranking is deterministic and chronology-first. MACD, volume,
   price, pivots, and RSI are scored only when visible. Normalized trace math is
   shortlist evidence, never proof. A user correction is a hard rejection for
   the current puzzle and resets only when a new puzzle starts.
5. Serper is the primary discovery provider and Brave is the fallback. Search
   results nominate sources only. Official IDX, KSEI, issuer, or filing pages
   support claims that require primary authority. The Serper runtime repair is
   to constrain the existing package to `mcp<2`, followed by a real Hermes MCP
   handshake test.
6. A read-only `idx-scanner` adapter owns the TradingView Indonesia HTTP edge.
   Its deterministic core returns requested columns, query range, provider URL,
   and fetch time. An MCP wrapper may expose that core to Hermes, but the core
   remains independently testable and no market action is in scope.
7. `chart-img` remains a renderer for no more than three finalists. It does not
   provide scanner evidence. Yahoo Finance remains the independent source for
   paced OHLCV and financial-data verification.
8. `Confirmed` requires exact as-of alignment, at least two material evidence
   categories, no material chronology or indicator mismatch, and an independent
   source. Clue-only and one-field key-stats matches cannot confirm a ticker.
   The workflow may ask one targeted clarification when missing time context
   would change the result, then fails closed.

## Consequences

- The prompt stays compact while parsing, scoring, and connector behavior are
  covered by ordinary Python tests.
- Existing VPS behavior is not changed by this repository-only decision. The
  Serper constraint and runtime skill copy require a separately reviewed VPS
  diff and approval before the first write.
- The benchmark measures false-confirmed results first, followed by top-three
  recall and top-one accuracy. A plausible lookalike is not counted as a win.
- The scanner depends on a public provider endpoint that can change. Response
  shape, freshness, and provider failures are surfaced instead of silently
  treated as empty matches.
