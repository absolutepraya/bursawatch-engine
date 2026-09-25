# Profile emoji helper instructions

This file supplements the repository root `AGENTS.md`. `skill-profile-emoji` is a
reusable agent skill, not a scheduled Hermes cron.

## Contract

- `bin/profile-emoji` runs on the VPS and uses the shared Delivery Owner client
  token file for guild reads and receipt polling. Creation loads a separate
  mode-0600 emoji token file at `~/.hermes/secrets/bursawatch-discord-delivery-emoji-token`
  only when needed. Only the Delivery Owner reads the Discord bot token. No
  token or Instagram cookie moves to the Mac or appears in output.
- The helper accepts an X or Instagram profile URL, or a handle together with
  an explicit platform. Its `ensure-image` command also accepts an explicitly
  supplied local image for approved custom-asset onboarding. It center-crops
  the image to a square, applies a circular transparent mask, and emits a
  static PNG suitable for a Discord custom emoji.
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

The normal path keeps the fetched page and source image in VPS process memory.
The `ensure-image` path reads the supplied local file only for that invocation.
For an approved create, the Delivery Owner stages the circular PNG in its
private media directory and keeps only its digest and metadata in SQLite.
The helper does not copy the image to the Mac or watcher state and has no
image-file output option.

Instagram's authenticated RSSHub cookie remains owned by the VPS-local
universal `rsshub` service. The helper must not read, print, or receive
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
  first VPS write in the conversation. Confirm the shared client library and
  compatible Delivery Owner service release are already in place; their
  dependencies are listed in the release manifest. Compare checksums after
  deployment.
- Do not edit the VPS runtime or the dotfiles mirror as source, and do not
  create or modify watcher state while onboarding an account.
