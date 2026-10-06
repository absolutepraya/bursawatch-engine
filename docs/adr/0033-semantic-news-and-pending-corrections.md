# ADR 0033: Semantic news judgment and pending source corrections

Status: Accepted, 2026-10-05.

The existing source-analysis LLM judges whether Telegram and Stockbit material
is advice, education, or substantive news. Retire lexical advice vetoes because
reported production targets, transactions, price changes, and attributed
research can contain the same words as trading instructions. Keep source
grounding, identity, routing, schema, and transport safeguards; do not add
another model call or turn headline style into a delivery gate.

A pending legacy X news event may append an optional-media correction when
images fail, retaining its original immutable version and frozen capabilities.
Already claimed or processed work stays unchanged. An atomic pending-version
precondition prevents a correction from racing a claim or settlement, while
the existing revision identity still reconciles a lost acknowledgement.
Unchanged legacy text does not establish an image baseline, and Swing,
image-only, or ambiguous Swing-capable events retain required media.

These boundaries favor text-supported news delivery over lexical rejection
and legacy media blocking, without authorizing historical Discord edits,
source replay, accepted-payload rewrites, or new delivery identities. The
[repair specification](../specs/2026-10-05-platform-news-audit-repairs.md)
records the compatibility and regression obligations.
