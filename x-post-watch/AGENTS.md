# X Post Watch instructions

This file supplements the repository root `AGENTS.md`. Read it before changing this watcher.

## Authoritative files

- `config/watches.json` is the canonical watched-account configuration.
- `bin/` contains the deterministic scanner, source adapters, state transitions, rendering, media delivery, and wrapper.
- `SKILL.md` describes the runtime Hermes agent contract.
- `SPEC.md` describes the complete runtime behavior and delivery contract.
- `PROFILE_CONFIGURATION.md` describes every profile field and the safe configuration workflow.
- `tests/` contains behavioral regressions for the watcher.

Do not edit VPS runtime state, live cursors, outboxes, or the dotfiles mirror as source. The development source is this directory. The VPS runtime is deployed separately through the repository workflow.

## Adding a watched X account

When the user asks to watch a new X account:

1. Inspect the account and representative recent posts before proposing configuration.
2. Check the available source paths, RSSHub and direct X, including feed completeness, threads, media, and source errors.
3. Suggest every configuration field not explicitly specified by the user:
   - source, including whether RSSHub or direct X is more reliable for this account
   - display name and Discord emoji
   - Discord destinations and routing keys
   - title generation and Indonesian summaries
   - relevance classification
   - normal, quote, reply, repost, and media forwarding
   - thread handling
   - promotion and exclusion rules
   - polling limit
4. Explain recommendations using observed account behavior. If the user has not specified any fields, propose a complete configuration rather than silently choosing one.
5. Ask the user when a setting is ambiguous, could change delivery behavior, or requires an unavailable Discord destination or emoji.
6. Do not backfill historical posts, reset cursors, replay alerts, or send test messages unless the user explicitly approves it.

The usual starting proposal is title plus Indonesian summary, relevance filtering, media forwarding, normal posts enabled, replies and reposts disabled, and routing enabled only when the user requests multiple destinations or the account clearly spans configured categories. Thread handling must follow observed account behavior, not an automatic default.

## Classification and promotion boundaries

The classifier must distinguish substantive macro, business, capital-markets, investing, and direct stock analysis from advertisements, paid research, product promotion, engagement bait, and unrelated posts.

When an account promotes paid or member-only research, subscription access, signal services, premium content, referral programs, or clickbait profit claims, encode the exclusion in both the profile-specific instruction and a deterministic scanner guard when the pattern is strong enough to identify reliably. Do not reject ordinary substantive analysis merely because it links to the account's own site.

Promotional filtering takes precedence over direct-market relevance guards. A promotional post mentioning a ticker, revenue, buybacks, a contract address, or other financial language must still be discarded. Add a regression for every new promotion pattern and preserve tests proving that ordinary analysis with a site link remains eligible.

For routed profiles, classify the central thesis rather than named entities. Use only configured route keys. Resolve an unknown or ambiguous ticker before routing, and fall back to `macro` when the lookup is inconclusive. Never duplicate one post across routes.

## Required change and deployment loop

1. Read the current source adapter, scanner, wrapper, state model, renderer, tests, and live behavior affected by the change.
2. Add behavioral tests for new profile fields, source or thread boundaries, classifier decisions, promotion suppression, routing, rendering, media, and failure handling as applicable.
3. Run the focused tests first, then the complete suite from this directory:

   ```bash
   ../.venv/bin/python -m pytest -q
   ```

4. Commit and push the reviewed scope before deployment. Only a clean published commit is deployable.
5. Deploy executable changes with `./deploy.sh x-post-watch`.
6. Synchronize reviewed config and documentation files separately to the matching VPS runtime paths. Compare exact files before copying and verify SHA-256 parity afterward.
7. Run the documented isolated no-post smoke test. It must exercise the real source, classifier, rendering, media, and heartbeat paths without sending external messages.
8. Verify the Hermes job remains enabled, scheduled, and healthy. Confirm the changed runtime source is eligible for the next dotfiles capture; do not use the dotfiles mirror as a deployment target.

Adding a profile observes the newest source cursor on its first successful run. It does not create a historical backfill. State changes require separate explicit approval.
