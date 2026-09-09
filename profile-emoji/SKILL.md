# Profile emoji helper

Use this reusable skill when onboarding an X or Instagram account that needs a
profile-picture emoji for a watcher configuration.

## Workflow

1. Normalize the account URL or handle and choose a stable emoji name. Use the
   reviewed watcher profile ID for a known watcher account. Otherwise use
   `x_<handle>` or `ig_<handle>`, unless the user supplies `--emoji-name`.
2. Prepare the image on the VPS without mutation:

   ```bash
   ssh vps '~/.agents/skills/profile-emoji/bin/profile-emoji prepare --platform x --account https://x.com/example --profile-id example --json'
   ```

   Use `instagram` for Instagram accounts. The helper uses the VPS-local
   source path and never brings Yanto's token or Instagram cookie to the Mac.
   The downloaded image and generated PNG stay in VPS process memory. The
   helper has no image-file output option and does not write to `/tmp` or
   watcher state.
3. During watcher research, run `ensure` without `--apply` if the guild result
   is needed. It reports an existing emoji or `would_create` for an absent one
   and performs no Discord mutation.
4. Draft the complete watcher profile and show the user the exact JSON. Do not
   invent an ID. If the emoji is absent, keep its field unresolved until the
   user approves the complete profile and the emoji creation step.
5. After that approval, create an absent emoji with the explicit apply flag:

   ```bash
   ssh vps '~/.agents/skills/profile-emoji/bin/profile-emoji ensure --platform x --account https://x.com/example --profile-id example --apply --json'
   ```

   Copy the returned full `<:name:id>` markup into the watcher config. If the
   name already exists, use the returned markup unchanged. Never delete or
   recreate it to match a newer profile image.
6. Continue with the watcher's own configuration approval, future-only state
   initialization, tests, published commit, deployment, and live verification.

The helper is idempotent by emoji name. `:name:` is only a shorthand label;
Discord watcher fields require `<:name:id>`. A successful `ensure` result
contains both forms and the numeric ID. `prepare` returns no Discord ID.

## Safety

- `prepare` never contacts Discord. `ensure` is read-only unless `--apply` is
  present.
- The wrapper reads only `DISCORD_BOT_TOKEN` from the VPS-local Hermes env.
- Source URLs are limited to trusted profile pages and fixed local watcher
  routes. Do not pass arbitrary CDN URLs or credentials to the helper.
- If the profile image cannot be tied to the requested account, stop and
  report the blocked account. Do not guess an avatar.
