# Cobalt instructions

This file supplements the repository root `AGENTS.md`.

## Scope

Cobalt is the media-download service. Its tracked deployment definition and lifecycle scripts live under `cobalt/`. The nested `cobalt/skills/media/SKILL.md` is the user-facing media skill and must remain consistent with the service contract.

## Safety

- Keep `cobalt/compose/cookies.json` machine-local. Never print, commit, mirror, or include its contents in documentation or diffs.
- Preserve the existing Cobalt API and host routing contract unless the user explicitly approves a change.
- Use the Cobalt-specific deployment guard in `cobalt/deploy.sh`, not a generic copy into the VPS runtime.
- Run the media tests and inspect the rendered service behavior before deployment.
- Do not broaden supported hosts, credential access, or download retention without a reviewed scope.

## Change loop

Read `README.md`, the compose definition, the media skill, and tests before changing behavior. Test TikTok, Instagram, and X paths with no sensitive output. Deploy only from a clean published commit, then verify the live service health and the exact changed-file checksums.
