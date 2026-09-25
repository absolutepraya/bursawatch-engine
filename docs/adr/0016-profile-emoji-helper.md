# Profile emoji helper

Status: accepted

> **Transport update:** The direct Discord client described below was
> superseded by [ADR 0030](0030-shared-discord-delivery-owner.md). The profile
> validation, image processing, and output decisions remain current.

## Context

X and Instagram watcher onboarding needs a consistent way to turn a public
profile picture into a Discord custom emoji. The bot token already belongs to
Yanto on the VPS, while the Mac agent should not receive Discord or Instagram
credentials. Discord emoji management is guild-scoped and must be idempotent
by name. The profile image is an onboarding snapshot, not a continuously
synchronized avatar.

## Decision

- Implement `profile-emoji` as a reusable VPS-local skill with a small SSH
  deployment script. The wrapper reads only `DISCORD_BOT_TOKEN` from the
  VPS-local Hermes environment.
- Accept only supported X and Instagram profile URLs or explicit handles. Use
  trusted profile metadata first, then the fixed local watcher source as a
  fallback. Reject arbitrary image URLs and fail closed when identity or image
  validation is incomplete.
- `prepare` resolves and circularly masks a static PNG without Discord access.
  `ensure` lists the explicit target guild and returns a matching emoji by
  name. It creates an absent emoji only with `--apply`.
- Existing emojis are permanent snapshots for this helper. An existing name
  is returned unchanged. The helper has no delete, recreate, refresh, or
  image-update operation. This matches Discord's emoji API, whose modify route
  changes emoji metadata but does not accept a new image. See the [Discord
  emoji resource documentation](https://docs.discord.com/developers/resources/emoji).
- The generated asset is a 128 by 128 static PNG with a transparent circular
  alpha mask and a 256 KiB maximum. Results expose `:name:`, `<:name:id>`, and
  the numeric ID. The actual CDN URL is never emitted; the result contains the
canonical profile URL and a redacted source host instead.
- The fetched page, source image, and generated PNG remain in VPS process
  memory only during normal onboarding. The helper has no image-file output
  option, so no `/tmp`, watcher state, cache, or Mac copy is used. The Discord
  custom emoji is the only durable image asset.
- The helper returns data only. X and Instagram watcher onboarding owns the
  complete profile proposal, user approval, config edit, future-only state
  initialization, deployment, and delivery verification.

## Consequences

- Agents can complete profile emoji onboarding through one VPS command without
  moving secrets to the Mac or asking the user to perform a Discord UI action.
- A dry `ensure` can detect an existing emoji and reports `would_create` for a
  missing one. `--apply` is a visible mutation boundary.
- Profile images can become stale after onboarding by design. A new snapshot
  requires a new emoji name and an explicit watcher configuration decision.
- The helper depends on public profile metadata or the existing VPS-local
  watcher source. Provider changes produce a blocked result instead of a
  guessed avatar.

## Verification

Run the focused `profile-emoji/tests` suite and the repository `bash
scripts/test-all` suite. Before any VPS write, compare the exact reviewed source
and contract files, obtain the required approval, deploy from a published clean
commit, compare checksums, and run only read-only or no-post verification.
