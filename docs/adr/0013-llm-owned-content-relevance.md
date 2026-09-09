# LLM-owned content relevance for X and Instagram watchers

Status: accepted

## Context

Hermes has two agent-backed publication watchers, `x-post-watch` and `instagram-post-watch`. Both need deterministic source handling for polling, publication-type eligibility, cursors, deduplication, leases, rendering, delivery, and failure recovery. They also need to keep out generic investing education, mindset advice, actionable trade setups, promotions, unrelated posts, and profile-specific noise.

The previous boundary mixed those responsibilities. Regexes and profile-specific branches could discard a publication before the model saw the complete source context. This was especially risky for Instagram, where OCR may expose factual market terms from a chart or an issuer disclosure without revealing the publication's central thesis.

## Decision

Use one shared relevance vocabulary and policy for both watchers:

- **Source eligibility** is deterministic structural intake. It covers enabled profiles, allowed publication types, configured forwarding flags, source parsing, cursor position, thread and quote structure, deduplication, and durable state transitions.
- **Content relevance** is whether an eligible publication's central thesis is worth forwarding under the profile's configured scope.
- **LLM relevance decision** is the model-owned boolean `is_relevant` produced for one bounded event. The LLM decides both positive relevance and negative content noise after receiving the available source evidence.
- **Positive disclosure safeguard** is a deterministic recall safeguard. When the scanner detects a clear scope-relevant disclosure, it sets `relevance_guard_required` and rejects no publication. The agent must not return `is_relevant:false` for that event.

The LLM relevance boundary excludes generic trading or investing education, tips, techniques, mindset or psychology advice, actionable trade setups, advertisements and product promotions, paid research, generic engagement, greetings, personal updates, event invitations, and unrelated content. Profile-specific negative exceptions remain prompt guidance in `additional_prompt_instruction`; they are not scanner discard branches. Ambiguous content remains with the LLM and is not rejected by word-co-occurrence logic.

Instagram runs OCR on every downloaded image and sampled reel frame. OCR is evidence supplied to the LLM and may contribute to the positive disclosure safeguard, but it is not a deterministic content classifier. No OCR-derived negative reason code or promotion verdict is emitted.

For X, authored quote reposts remain structurally eligible when `forward_quote_post` is true. Native reposts remain separately controlled by `forward_repost` and are disabled in the current profiles. Replies to other accounts remain controlled by `forward_reply`; same-author thread continuation remains a state and source-structure rule. Quote reposts are not native reposts and do not inherit the native repost setting.

All current LLM-enabled profiles in both watchers keep `enable_llm_relevance_filter:true`. Future profiles may opt out through the existing configuration flag. This change is future-only: it does not reset state, replay previously discarded events, or backfill historical publications.

## Consequences

- Every structurally eligible, OCR-prepared Instagram publication reaches the normal bounded LLM decision, including promotions and content that may later be judged irrelevant.
- X and Instagram now share one ownership boundary, while their source evidence remains watcher-specific: X supplies post, quote, and thread text; Instagram supplies caption, OCR, and selected local vision paths.
- LLM usage increases for events that deterministic negative filters formerly removed. The bounded one-event wake and existing lease limit remain unchanged.
- Removing deterministic negative branches avoids false negatives from incomplete text, OCR context, or profile-specific heuristics. The tradeoff is that model prompt quality and monitoring become more important.
- Existing live state and delivery history remain untouched. Historical false positives or false negatives are not replayed as part of this rollout.

## Follow-up

Monitor accepted versus irrelevant LLM decisions and delivery quality after deployment. If a new boundary is needed, add it to the shared prompt policy and the relevant profile guidance with a behavioral regression test. Do not add a deterministic negative classifier unless the ownership decision is revisited explicitly.
