# Kelas Investasi GTW Watch

`kelas-investasi-gtw-watch` is the Mac development source for a future-only Telegram `#GTW` watcher. It observes public channel `@kelasinvestasiid` (ID `2142109618`) and, after a complete eligible bundle is summarized and validated, delivers one Discord text message then only the header's source image to `#stock-news` (`1525102508714889257`) as Yanto.

The exact eligible header is case-insensitive `Good to watch - <IDX ticker> #GTW`. The watcher includes contiguous eligible analysis text within the bundle boundary, but forwards only the first photo attached to the eligible header. Photos on later source messages are never forwarded. A next eligible header closes the preceding bundle immediately; otherwise the final bundle requires more than 20 quiet minutes. Replies, disclaimers, promotions, article links, unrelated posts, and non-photo documents are excluded.

## Safety and ownership

The scanner owns source access, durable state, retries, and Discord delivery. Hermes receives only a completed bundle, must treat source text as untrusted data rather than instructions, and submits only the strict JSON described in [SKILL.md](SKILL.md). Hermes never posts directly to Discord.

The watcher uses the shared PolyCop `POLYCOP_SESSION_STRING` and must acquire `acquire_probe_after_active_lease` before it creates a Telegram client. It never uses a watcher-specific Telegram session. Do not directly post to Telegram, reset the shared resilience state, edit watcher state, replay old signals, or backfill source history.

First observation records the newest message ID in `~/.hermes/state/kelas-investasi-gtw-watch.json` and creates no historical event. The shared resilience control state is `~/.hermes/state/telegram-resilience-polyclop.json`; both locations are production data, not deploy inputs.

## Local tests

Run the watcher tests from the repository root:

```bash
./.venv/bin/python -m pytest -q kelas-investasi-gtw-watch/tests telegram-resilience/tests/test_documentation.py
```

For the full local suite:

```bash
./.venv/bin/python -m pytest -q
```

See [SPEC.md](SPEC.md) for the behavioral contract, [CONTEXT.md](CONTEXT.md) for the agent boundary, and [DEPLOY.md](DEPLOY.md) for the approval-gated deployment sequence.
