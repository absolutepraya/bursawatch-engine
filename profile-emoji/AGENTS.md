# Profile emoji helper instructions

This file supplements the repository root `AGENTS.md`. `profile-emoji` is a
reusable agent skill, not a scheduled Hermes cron.

## Contract

- `bin/profile-emoji` runs on the VPS and loads Yanto's local
  `DISCORD_BOT_TOKEN` from `~/.hermes/.env`. The token and the Instagram
  cookie never move to the Mac, enter source control, or appear in output.
- The helper accepts an X or Instagram profile URL, or a handle together with
  an explicit platform. It resolves a trusted profile image, center-crops it
  to a square, applies a circular transparent mask, and emits a static PNG
  suitable for a Discord custom emoji.
- `prepare` resolves and transforms the image without contacting Discord.
  `ensure` performs a read-only guild lookup by default and creates the emoji
  only when `--apply` is supplied. An existing name is returned unchanged.
- The helper never deletes, recreates, or refreshes an existing emoji. It has
  no option for that behavior and keeps no profile-image state or manifest.
- The default guild is the reviewed target guild `940285152335110204`. A
  caller may provide an explicit guild ID, but the helper never guesses a
  guild from the bot's guild list.

The result includes the shorthand `:emoji_name:`, the full Discord markup
`<:emoji_name:emoji_id>` when an ID exists, and the numeric emoji ID. Watcher
configuration stores the full markup, not the shorthand.

## Resolution and privacy boundary

Only supported X and Instagram profile URLs are accepted. The resolver uses
the public profile page metadata first, then the fixed VPS-local watcher
sources when available. It rejects arbitrary image URLs, non-public remote
hosts, animated images, and a profile page whose declared identity does not
match the requested account. The actual image CDN URL is transient and is
never included in the result. `source_url` means the canonical profile page;
`image_source_host` is the redacted image host.

The normal path keeps the fetched page, source image, and generated circular
PNG in VPS process memory only. The helper has no image-file output option, so
it does not use `/tmp`, watcher state, or a cache, and it does not copy an
asset to the Mac. The Discord custom emoji is the only durable image asset
produced by this helper.

Instagram's authenticated RSSHub cookie remains owned by the VPS-local
`rsshub-instagram` service. The helper must not read, print, or receive
`IG_COOKIE`.

## Development and deployment

- Keep source in this directory. The deployed runtime is
  `~/.agents/skills/profile-emoji/` and the wrapper is
  `~/.agents/skills/profile-emoji/bin/profile-emoji`.
- Add behavioral tests under `tests/` and run the focused suite with the
  repository shared environment. `bash scripts/test-all` is the complete
  repository verification command.
- Publish a clean reviewed commit before deployment. Run `./deploy.sh` only
  after comparing the exact local and VPS files and receiving approval for the
  first VPS write in the conversation. Compare checksums after deployment.
- Do not edit the VPS runtime or the dotfiles mirror as source, and do not
  create or modify watcher state while onboarding an account.
