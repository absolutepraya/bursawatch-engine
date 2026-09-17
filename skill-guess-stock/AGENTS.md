# Guess Stock skill instructions

`skill-guess-stock` is a reusable, read-only Hermes skill for identifying an IDX
ticker from incomplete chart, key-stats, clue, and market-source evidence. Its
development source lives in this repository. The current VPS runtime target is
`~/.hermes/skills/research/guess-stock/`.

## Domain glossary

- **Puzzle**: one user request and its follow-up corrections. A new puzzle
  resets the rejection list; `/resume` keeps the same puzzle.
- **Evidence item**: one supplied or fetched artifact, such as a chart image,
  key-stats image, HSC/KSEI screen, clue text, or official page.
- **Evidence field**: one visible fact with its source, as-of date, and
  visibility state. Missing or hidden values remain unknown.
- **Fingerprint**: the normalized set of visible price, chronology, volume,
  indicator, fundamental, and clue features used for comparison.
- **Candidate**: an IDX ticker proposed by a scanner or clue resolver. A
  candidate is not a confirmed identity or a trade recommendation.
- **Confirmed**: a result that passes the exact as-of, evidence, and
  independent-source gates. It is not a prediction of future price.
- **Lookalike**: a candidate with partial visual or numeric similarity that
  fails a material gate.
- **Hard rejection**: a candidate excluded because of a material mismatch or
  an explicit user correction during the current puzzle.
- **Connector**: a read-only provider adapter that returns structured data and
  source metadata. A renderer, such as `chart-img`, is not a scanner.

## Boundaries

- Do not post messages, place orders, or mutate market state.
- Do not use a search result that merely repeats the user's clue as proof.
- Do not invent hidden chart values, dates, indicators, or financial fields.
- Keep raw WhatsApp transcripts and attachments outside Git. Regression
  fixtures must be sanitized and contain only the evidence needed for tests.
- Keep the runtime skill compact. Deterministic parsing, scoring, and source
  adapters belong in `bin/` and remain independently testable.
- Serper is the preferred discovery provider and Brave is the fallback. An
  official IDX, KSEI, or issuer page is required when a claim depends on that
  authority. Yahoo Finance supplies market history and financial data.
- TradingView scanner access is read-only and must return source, timestamp,
  requested columns, and the exact query window.

## Verification

Run the focused suite from this directory with `../.venv/bin/python -m pytest
-q`, or run the complete repository suite with `bash scripts/test-all` from the
repository root. Network verification of the scanner and any VPS runtime
change requires a separate reviewed step.
