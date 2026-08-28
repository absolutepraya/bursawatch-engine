# X Post Watch Insider Tracker and Thread Settling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Watch new `@InsiderTrackX` threads and make every self-chain profile poll each minute, delivering an observed multi-post chain promptly while bounding a lone post's wait to 15 minutes.

**Architecture:** Keep the existing configuration-driven scanner and durable outbox. Reuse `ready_after` as the event's fixed maximum settling deadline: create it once for a lone self-chain post, preserve it on updates, and bring it forward to the current observation time when a chain resolves to two or more same-author posts. The Hermes job stays the scheduler and the scanner remains the only owner of RSSHub fetches, state, rendering, media, heartbeat, and Discord delivery.

**Tech Stack:** Python 3, pytest, JSON configuration, RSSHub, Hermes cron, Discord webhook helper.

**Spec:** [2026-08-14-x-post-watch-insider-tracker-thread-settling-design.md](../specs/2026-08-14-x-post-watch-insider-tracker-thread-settling-design.md)

## Global Constraints

- Edit source only in `x-post-watch/`; never edit VPS runtime state or the dotfiles mirror as source.
- `self_chain` holds at most 20 posts within four hours; only profiles explicitly configured with `self_chain` use the settling rule.
- A multi-post self-chain is ready immediately. A lone self-chain post has one 15-minute maximum deadline, and later continuations must not postpone it.
- `disabled` profiles remain immediately ready.
- The new Insider Tracker profile uses `<:insidertracker:1537444489134604448>`, the existing `macro`, `id_stock`, and `us_stock` channels, LLM relevance/title/summary/routing, and no historical backfill.
- Reschedule Hermes job `bc519bd9abc0` to `* * * * *` through `/home/praya/.local/bin/hermes cron edit`; do not hand-edit `jobs.json`.
- No smoke test may post to Discord or mutate live state. Use an isolated state file and `X_POST_WATCH_NO_POST=1`.
- Before the first VPS write, compare the exact local and remote files and obtain current-session approval. Deployment requires a clean published commit and post-copy SHA-256 parity.

---

## File Structure

- `x-post-watch/bin/config.py`: validates the supported `thread_handling.max_posts` range.
- `x-post-watch/bin/state.py`: owns durable thread candidate readiness and must preserve, rather than restart, the settling deadline.
- `x-post-watch/config/watches.json`: declares Insider Tracker and sets the two self-chain profiles to the 20-post cap.
- `x-post-watch/tests/test_config.py`: proves the configuration boundary and exact canonical profile contract.
- `x-post-watch/tests/test_state.py`: proves prompt multi-post readiness, the single deadline, chain update, and disabled-profile invariants.
- `x-post-watch/{README.md,SPEC.md,CONTEXT.md,PROFILE_CONFIGURATION.md}`: describes the minute cadence, 20-post cap, bounded-settling rule, and current no-backfill deployment procedure.

### Task 1: Raise and prove the thread-cap configuration boundary

**Files:**
- Modify: `x-post-watch/bin/config.py:83-99`
- Modify: `x-post-watch/tests/test_config.py:10-59`

**Interfaces:**
- Consumes: `thread_handling.max_posts` from a profile JSON object.
- Produces: `config._parse_thread_handling(value, label) -> ThreadHandling`, accepting integer values 1 through 20 and raising `ValueError` otherwise.

- [ ] **Step 1: Write the failing boundary tests**

Add these cases to `test_load_config_rejects_invalid_profile_fields` and add the acceptance test below:

```python
def test_load_config_accepts_twenty_post_self_chain(config_path, profile_payload):
    profile_payload["thread_handling"]["max_posts"] = 20
    write_config(config_path, {"version": 1, "profiles": [profile_payload]})

    profile = config_module.load_watch_config(config_path).profiles[0]

    assert profile.thread_handling.max_posts == 20


# Parameterized invalid case
("thread_handling", {"mode": "self_chain", "max_posts": 21, "max_age_minutes": 240, "settle_minutes": 60}, "1 to 20"),
```

- [ ] **Step 2: Run the focused test to verify the acceptance case fails**

Run: `cd x-post-watch && ../.venv/bin/python -m pytest -q tests/test_config.py::test_load_config_accepts_twenty_post_self_chain`

Expected: FAIL because `config._parse_thread_handling` rejects `max_posts: 20`.

- [ ] **Step 3: Change the validator and its error contract**

In `_parse_thread_handling`, replace the current `1 <= max_posts <= 10` boundary and error text with:

```python
if type(max_posts) is not int or not 1 <= max_posts <= 20:
    raise ValueError(f"{label}.max_posts must be an integer from 1 to 20")
```

- [ ] **Step 4: Run the focused configuration suite**

Run: `cd x-post-watch && ../.venv/bin/python -m pytest -q tests/test_config.py`

Expected: PASS, including acceptance of 20 and rejection of 21.

- [ ] **Step 5: Commit the independently tested boundary change**

```bash
git add x-post-watch/bin/config.py x-post-watch/tests/test_config.py
git commit -m "feat: allow twenty-post x threads"
```

### Task 2: Make self-chain settling bounded and prompt

**Files:**
- Modify: `x-post-watch/bin/state.py:107-167`
- Modify: `x-post-watch/tests/test_state.py:45-77`

**Interfaces:**
- Consumes: `_event_for_thread(state, profile, thread, now, settle_minutes)` and the ordered `thread` tuple built by `observe_posts`.
- Produces: exactly one outbox event per `thread_root_id`, whose `ready_after` is either the first-observation deadline for a lone post or an immediate timestamp for a resolved multi-post chain.

- [ ] **Step 1: Replace the reset-based regression with bounded-settling tests**

Replace `test_self_quote_chain_waits_for_quiet_period_and_resets_when_a_continuation_arrives` with these assertions, using the existing `root` and self-quoted `child` fixtures:

```python
def test_lone_self_chain_keeps_one_deadline_then_child_is_ready_immediately(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    started = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    root = SourcePost(...)
    child = SourcePost(..., related_url="https://x.com/Kutekians/status/101")
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "100"}

    state.observe_posts(value, profile, [root], lambda post: post.kind is PostKind.NORMAL, lambda post: post.related_url is not None, started)
    assert state.is_ready(value["outbox"][0], started + timedelta(minutes=14)) is False

    state.observe_posts(value, profile, [root, child], lambda post: post.kind is PostKind.NORMAL, lambda post: post.related_url is not None, started + timedelta(minutes=1))
    event = value["outbox"][0]
    assert [post["post_id"] for post in event["thread_posts"]] == ["101", "102"]
    assert state.is_ready(event, started + timedelta(minutes=1)) is True
```

Extend `test_same_poll_root_and_continuation_use_the_newest_complete_thread` with `assert state.is_ready(event, now) is True`, and keep the existing disabled-profile test unchanged.

- [ ] **Step 2: Run the focused state tests to verify the new readiness assertions fail**

Run: `cd x-post-watch && ../.venv/bin/python -m pytest -q tests/test_state.py`

Expected: FAIL because the existing implementation schedules every self-chain event after `settle_minutes` and resets the timestamp on child observation.

- [ ] **Step 3: Preserve the deadline and accelerate only an observed chain**

In `_event_for_thread`, calculate readiness once per update:

```python
is_multi_post_chain = len(thread) > 1
immediate = now.isoformat()
deadline = (now + timedelta(minutes=settle_minutes)).isoformat()
```

For a new event, store `ready_after=immediate` when `is_multi_post_chain` is true; otherwise store `deadline`. For an existing event, keep the current `ready_after` when it remains a lone post. When `is_multi_post_chain` is true, update it to the earlier of the existing parsed `ready_after` and `now`, serialized with `isoformat()`. Do not change `agent_phase`, `agent_lease_until`, text legs, or media legs; the existing guard for non-pending agent events remains intact.

Use a small local helper inside `_event_for_thread` to parse a valid existing ISO timestamp, falling back to `now` if a legacy value is absent or invalid. This keeps existing outbox events safe and prevents a state-schema migration.

- [ ] **Step 4: Run focused state and complete watcher tests**

Run: `cd x-post-watch && ../.venv/bin/python -m pytest -q tests/test_state.py`

Expected: PASS, proving a lone post waits once, a same-poll or later-joined multi-post chain is ready immediately, root-to-latest order survives, and disabled profiles remain immediate.

Run: `cd x-post-watch && ../.venv/bin/python -m pytest -q`

Expected: PASS for the complete watcher suite.

- [ ] **Step 5: Commit the state-machine change**

```bash
git add x-post-watch/bin/state.py x-post-watch/tests/test_state.py
git commit -m "feat: bound x post thread settling"
```

### Task 3: Configure Insider Tracker and align the operational documentation

**Files:**
- Modify: `x-post-watch/config/watches.json`
- Modify: `x-post-watch/tests/test_config.py`
- Modify: `x-post-watch/README.md`
- Modify: `x-post-watch/SPEC.md`
- Modify: `x-post-watch/CONTEXT.md`
- Modify: `x-post-watch/PROFILE_CONFIGURATION.md`

**Interfaces:**
- Consumes: the existing `macro`, `id_stock`, and `us_stock` `discord_channels` entries and the validated 20-post thread cap.
- Produces: canonical `profiles["insidertracker"]` configuration and documentation that matches the scanner and Hermes scheduling contract.

- [ ] **Step 1: Write the failing canonical-profile test**

Add a test using the canonical config:

```python
def test_canonical_insider_tracker_profile_is_threaded_and_routed():
    canonical_config = Path(__file__).resolve().parents[1] / "config" / "watches.json"
    profile = {item.id: item for item in config_module.load_watch_config(canonical_config).profiles}["insidertracker"]

    assert profile.handle == "InsiderTrackX"
    assert profile.emoji == "<:insidertracker:1537444489134604448>"
    assert [channel.key for channel in profile.discord_channels] == ["macro", "id_stock", "us_stock"]
    assert profile.enable_llm_title is True
    assert profile.enable_llm_summary is True
    assert profile.enable_llm_routing is True
    assert profile.enable_llm_relevance_filter is True
    assert (profile.thread_handling.mode, profile.thread_handling.max_posts, profile.thread_handling.max_age_minutes, profile.thread_handling.settle_minutes) == ("self_chain", 20, 240, 15)
```

- [ ] **Step 2: Run the new test to verify it fails before configuration exists**

Run: `cd x-post-watch && ../.venv/bin/python -m pytest -q tests/test_config.py::test_canonical_insider_tracker_profile_is_threaded_and_routed`

Expected: FAIL with a missing `insidertracker` profile.

- [ ] **Step 3: Add the profile and update the existing threaded profile cap**

Append this profile object to `config/watches.json` and change `writingtorch.thread_handling.max_posts` from `10` to `20`:

```json
{
  "id": "insidertracker",
  "enabled": true,
  "profile_url": "https://x.com/InsiderTrackX",
  "handle": "InsiderTrackX",
  "display_name": "Insider Tracker",
  "twitter_emoji": "<:twitter:1531672630602498129>",
  "emoji": "<:insidertracker:1537444489134604448>",
  "discord_channels": [
    {"key": "macro", "channel_id": "1531655369884045382", "description": "Broad economic, business, market, sector, and cross-asset analysis."},
    {"key": "id_stock", "channel_id": "1525102508714889257", "description": "Direct IDX-listed company or ticker thesis."},
    {"key": "us_stock", "channel_id": "1532266331737686199", "description": "Direct NYSE- or Nasdaq-listed security thesis, including ADRs."}
  ],
  "forward_normal_post": true,
  "forward_quote_post": true,
  "forward_reply": false,
  "forward_repost": false,
  "forward_media": true,
  "enable_llm_title": true,
  "enable_llm_summary": true,
  "enable_llm_routing": true,
  "enable_llm_relevance_filter": true,
  "additional_prompt_instruction": "",
  "max_items_per_poll": 50,
  "thread_handling": {"mode": "self_chain", "max_posts": 20, "max_age_minutes": 240, "settle_minutes": 15}
}
```

- [ ] **Step 4: Update the documentation to the final contract**

Make these exact content changes:

- `README.md`: replace the four-hour, ten-post, reset-on-continuation wording with the 20-post bounded-settling rule, and say that observed multi-post chains proceed immediately.
- `SPEC.md`: change polling from every five minutes to every minute; describe one fixed 15-minute maximum deadline for a lone post, immediate multi-post readiness, and the 20-post cap.
- `CONTEXT.md`: change the stale hourly source-retry wording to the next scheduled minute; retain the approved bounded-settling glossary entry.
- `PROFILE_CONFIGURATION.md`: change all copyable `self_chain` examples and the field table to a 20-post cap and non-resetting maximum deadline; change the final scheduler verification wording from hourly to every minute.

- [ ] **Step 5: Validate the exact config and run all watcher tests**

Run:

```bash
cd x-post-watch
PYTHONPATH=bin ../.venv/bin/python -c 'import config; from pathlib import Path; watch_config=config.load_watch_config(Path("config/watches.json")); print(",".join(profile.id for profile in watch_config.profiles))'
../.venv/bin/python -m pytest -q
```

Expected: the printed IDs include `insidertracker`, and every test passes.

- [ ] **Step 6: Commit the profile and documentation contract**

```bash
git add x-post-watch/config/watches.json x-post-watch/tests/test_config.py x-post-watch/README.md x-post-watch/SPEC.md x-post-watch/CONTEXT.md x-post-watch/PROFILE_CONFIGURATION.md
git commit -m "feat: watch Insider Tracker threads"
```

### Task 4: Publish, deploy, reschedule, and verify without posting

**Files:**
- Deploy: `x-post-watch/bin/config.py`, `x-post-watch/bin/state.py`
- Synchronize: `x-post-watch/config/watches.json`, `x-post-watch/{SKILL.md,README.md,SPEC.md,CONTEXT.md,PROFILE_CONFIGURATION.md}`
- Inspect only: `vps:~/.agents/skills/x-post-watch/state/state.json`, `vps:~/.hermes/cron/jobs.json`, `~/dotfiles`

**Interfaces:**
- Consumes: a clean published `main` commit containing Tasks 1 through 3 and the active Hermes job `bc519bd9abc0`.
- Produces: checksum-identical VPS runtime source and config, active one-minute Hermes schedule, isolated no-post proof, and a verified dotfiles capture or an explicit pending-capture handoff.

- [ ] **Step 1: Prove the source is ready to deploy**

Run:

```bash
git status --short
git log -1 --oneline
git push origin main
git status --short
```

Expected: the working tree is clean before and after the push, and the intended commit is reachable from `origin/main`.

- [ ] **Step 2: Compare every VPS target before the first write and request approval**

Run read-only diffs for `bin/config.py`, `bin/state.py`, `config/watches.json`, `README.md`, `SPEC.md`, `CONTEXT.md`, and `PROFILE_CONFIGURATION.md` against `vps:~/.agents/skills/x-post-watch/`. Present the exact changed-file list and diff summary, then obtain current-session approval before copying or changing the schedule.

- [ ] **Step 3: Deploy reviewed source and documentation**

Run from the Hermes repository after approval:

```bash
./deploy.sh x-post-watch
rsync -a x-post-watch/config/watches.json vps:.agents/skills/x-post-watch/config/watches.json
rsync -a x-post-watch/{SKILL.md,README.md,SPEC.md,CONTEXT.md,PROFILE_CONFIGURATION.md} vps:.agents/skills/x-post-watch/
```

Then compare SHA-256 hashes for every changed `bin/` file, config file, and documentation file on the Mac and VPS. Do not copy or reset `state/`.

- [ ] **Step 4: Change only the registered Hermes schedule**

From a VPS-local agent, run:

```bash
/home/praya/.local/bin/hermes cron edit bc519bd9abc0 --schedule '* * * * *'
/home/praya/.local/bin/hermes cron list
```

Expected: `x-post-watch` is active with schedule `* * * * *`, delivery remains `local`, attached skill remains `x-post-watch`, and the wrapper/workdir are unchanged.

- [ ] **Step 5: Exercise the deployed path without Discord or live-state effects**

On the VPS, create an isolated directory with `mktemp -d`, run the wrapper with `X_POST_WATCH_NO_POST=1` and `X_POST_WATCH_STATE_PATH=<temporary>/state.json`, inspect the output for only dry-run operations and the heartbeat, then remove that exact temporary directory. The current Insider Tracker feed is valid but empty, so record it as source health rather than a delivery result.

- [ ] **Step 6: Verify scheduler and dotfiles capture evidence**

After the next natural one-minute run, inspect the saved Hermes execution record and the watcher state/outbox without editing either. Confirm the job is enabled, its execution is `completed`, and the heartbeat has the expected one-minute cadence.

Run `~/.hermes/scripts/dotfiles-sync.sh --check` on the VPS. Let job `804f44f0be6e` perform its normal capture unless an immediate run is explicitly approved. After capture, verify saved output contains `mac=ok vps=ok` plus `git=push` or `git=noop`, `~/dotfiles` is clean and equal to `origin/config`, and the changed runtime files exist under `vps/agents/skills/x-post-watch/` with matching hashes.

- [ ] **Step 7: Commit no deployment artifacts**

Do not stage state, logs, temporary smoke directories, generated media, or dotfiles runtime snapshots. Report the test count, published commit, per-file checksum evidence, schedule evidence, no-post output, first natural execution evidence, and dotfiles capture status.

## Plan Self-Review

- **Spec coverage:** Task 1 implements the 20-post cap; Task 2 implements prompt multi-post readiness and non-resetting maximum settlement; Task 3 adds the exact Insider Tracker profile and documentation; Task 4 covers the one-minute Hermes schedule, source publication, no-post verification, natural-run evidence, and dotfiles capture.
- **Placeholder scan:** The plan contains no unresolved placeholders, deferred implementation instruction, or unspecified test. Each code task names exact functions, assertions, commands, and commit scope.
- **Type consistency:** `ThreadHandling.max_posts`, `ready_after`, `_event_for_thread`, `observe_posts`, `Profile`, and `WatchConfig` use their existing names and data shapes throughout.
