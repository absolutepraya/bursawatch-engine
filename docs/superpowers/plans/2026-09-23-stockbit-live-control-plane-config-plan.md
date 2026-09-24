# Stockbit Snips Live Control Plane Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Move Stockbit Snips operator settings into the live Bursawatch control plane and expose them through the authenticated web-config workspace without changing its active production cadence or state.

**Architecture:** The control-plane service owns the strict v1 config validator, seeded baseline, and desired schedule record. The Stockbit runtime reads one live snapshot per scheduled invocation, preserves lane state across pause and resume, and freezes prompt and destination settings on each article before asynchronous agent processing. The web app adds a typed editor and uses the existing schedule and revision flows.

**Tech Stack:** Python, pytest, PostgreSQL migrations, the shared lib-bursawatch-control client, TypeScript, React, Next.js, Vitest, Playwright smoke scripts, and the Bursawatch release manifest.

**Spec:** [docs/superpowers/specs/2026-09-23-stockbit-live-control-plane-config-design.md](../specs/2026-09-23-stockbit-live-control-plane-config-design.md)

## File Map

- cron-stockbit-snips/bin/config.py owns the v1 parser, live snapshot loader, system runtime values, and immutable typed settings.
- cron-stockbit-snips/bin/state.py owns the version 1 to version 2 local-state upgrade and validation.
- cron-stockbit-snips/bin/scan.py applies enabled lanes, records article snapshots, delivers by frozen destination, and reports safe run summaries.
- cron-stockbit-snips/bin/agent_protocol.py and cron-stockbit-snips/SKILL.md keep the hard agent contract separate from the additive operator instruction.
- service-bursawatch-control/validator-sources/bursawatch-stockbit-snips/ is the self-contained, source-parity parser bundle used by the API.
- service-bursawatch-control/bin/control_plane/validators.py registers that parser; baselines.py and baseline-configs/ register the source baseline; migrations/011_stockbit_snips_control_plane.sql adds the watcher and schedule catalog records.
- service-bursawatch-control/env.example, README.md, deployment/README.md, and AGENTS.md document the new trusted validator path. The real dedicated VPS environment remains outside local implementation.
- web-config/src/lib/watcher-fields.ts defines editor support and client-side validation; watcher-config-editor.tsx renders the editor; connected-workflow-summary.tsx describes the watcher in the real workspace.
- web-config/docs/CONTROL_PLANE.md, CONFIGURATION_COVERAGE.md, and AGENTS.md document all eight editors and the Stockbit controls.
- platform-bursawatch-release/release-manifest.json deploys lib-bursawatch-control before Stockbit. release_agent.py keeps release no-post state isolated while allowing the required config read and suppressing control-plane event writes.

## Global Constraints

- Use the managed worktree at /Users/absolutepraya/Documents/Projects/Hermes/.worktrees/stockbit-control-plane for all inspection, edits, tests, and Git commands.
- The complete Stockbit config has version 1, all four fixed feed IDs, two distinct Discord snowflakes, and an optional instruction capped at 800 characters.
- The source baseline has all four feeds enabled and a 900-second interval. The desired interval range is 300 to 3600 seconds in Asia/Jakarta.
- Initial destination IDs must match the values in the existing Stockbit runtime configuration. A read-only production check must confirm effective VPS values before any production cutover.
- There is no static config fallback in the scheduled runtime. A configured snapshot is required for new source intake and unbound article dispatch.
- The required system heartbeat, source URLs, feed IDs, route keys, credentials, request timeout, state path, state transitions, retry policy, parser, and agent output schema remain system-owned.
- A lane re-enabled after an observed pause must make an unconditional first fetch, advance its cursor without queueing paused history, and preserve existing queued work.
- Local state upgrade preserves all version 1 lane and article data. It must fail closed on malformed data rather than replacing the state file.
- Article prompt and destination values are frozen when the article is first dispatched. Later settings revisions do not alter already dispatched or pending delivery work.
- The API requires the deployed Stockbit validator path before it accepts dashboard config writes. Document the dedicated environment variable, but do not edit the live VPS environment or restart production services in this implementation.
- Local checks use synthetic snapshots, temporary state, and no-post controls. Do not read or write production config, run a live Hermes job, post a Discord message, deploy the web app, or alter a schedule.
- Do not commit, push, merge, deploy, or clean up the WT as part of this plan.

## Review Focus

1. A config with a missing lane, an unknown field, a non-boolean enabled flag, an invalid snowflake, duplicate destinations, or an 801-character instruction must fail in the service validator, watcher parser, and web draft validator. Pin with tests in Tasks 1, 3, and 6.
2. A lane disabled for several polls and then re-enabled must not send conditional headers or queue paused history, and its prior outbox must remain processable. Pin with tests in Task 4.
3. A control-plane read failure must prevent new intake and unbound dispatch while allowing records with frozen snapshots to finish; legacy unbound work waits. Pin with tests in Tasks 3 and 5.
4. A settings revision changed after agent dispatch must not change the operator instruction, route destination, or retry destination for that article, and operator text must not override hard instructions. Pin with tests in Task 5.
5. A valid version 1 state must upgrade without losing cursors, ETags, article phases, leases, rendered bodies, or delivery attempts; malformed version 1 state must be rejected without rewrite. Pin with tests in Task 4.

---

### Task 1: Define and register the strict Stockbit config contract

**Files:**

- Modify: cron-stockbit-snips/bin/config.py
- Modify: cron-stockbit-snips/bin/models.py
- Modify: service-bursawatch-control/bin/control_plane/validators.py
- Modify: service-bursawatch-control/bin/control_plane/baselines.py
- Create: service-bursawatch-control/baseline-configs/bursawatch-stockbit-snips.json
- Create: service-bursawatch-control/validator-sources/bursawatch-stockbit-snips/config.py
- Create: service-bursawatch-control/validator-sources/bursawatch-stockbit-snips/models.py
- Modify: service-bursawatch-control/tests/test_validators.py
- Modify: service-bursawatch-control/tests/test_validator_sources.py
- Modify: service-bursawatch-control/tests/test_baselines.py
- Create: cron-stockbit-snips/tests/test_config.py

**Interfaces:**

- `cron-stockbit-snips/bin/models.py` defines frozen `StockbitFeedSetting` and `StockbitWatchConfig` dataclasses. `cron-stockbit-snips/bin/config.py` owns `load_watch_config_data(raw: object) -> StockbitWatchConfig`.
- The service validator calls load_watch_config_data from the isolated Stockbit validator source directory.
- The same config.py and models.py bytes in the service bundle must match the cron source bytes.

- [ ] **Step 1: Add failing parser tests**

Add a complete fixture with these exact lane IDs and routes. Test it with all lanes enabled, one lane disabled, and an empty instruction.

```python
def valid_config():
    return {
        "version": 1,
        "feeds": [
            {"id": "stockbit_commentary", "enabled": True},
            {"id": "unboxing", "enabled": True},
            {"id": "unboxing_ipo", "enabled": True},
            {"id": "ai_reports_stockbit", "enabled": True},
        ],
        "destinations": {
            "id_stocks_news_channel_id": "1525102508714889257",
            "macro_news_channel_id": "1531655369884045382",
        },
        "additional_prompt_instruction": "",
    }


def test_load_watch_config_data_accepts_complete_v1_config():
    parsed = config.load_watch_config_data(valid_config())
    assert len(parsed.feeds) == 4
    assert parsed.additional_prompt_instruction == ""
```

Add rejection cases for a missing lane, duplicate lane ID, unknown feed ID, missing route, duplicate route IDs, a non-snowflake destination, a non-boolean enabled value, an unknown root key, config version 2, and an 801-code-point instruction. Confirm 800 ASCII characters and 800 non-BMP Unicode code points are accepted, and 801 code points are rejected.

Run: mise exec -- python -m pytest -q cron-stockbit-snips/tests/test_config.py

Expected: FAIL because `load_watch_config_data` is not implemented yet.

- [ ] **Step 2: Implement the typed parser in the cron source**

Add frozen dataclasses to cron-stockbit-snips/bin/models.py and the parser to cron-stockbit-snips/bin/config.py. Define `_expect_object` to require an exact built-in dict and `_DISCORD_ID_RE = re.compile(r"\d{17,20}")`. Validate exact root, feed, destination, and instruction keys. Accept only the four FeedLane values, require each exactly once, validate snowflakes with the existing 17 to 20 digit policy, require different destination IDs, collapse whitespace with `" ".join(instruction.split())`, then enforce 800 Unicode code points.

```python
CONFIG_VERSION = 1
STOCKBIT_LANES = tuple(feed.lane for feed in FEEDS)


def load_watch_config_data(raw: object) -> StockbitWatchConfig:
    root = _expect_object(raw, "watch configuration")
    if set(root) != {
        "version",
        "feeds",
        "destinations",
        "additional_prompt_instruction",
    }:
        raise ValueError("watch configuration has an invalid shape")
    if type(root["version"]) is not int or root["version"] != CONFIG_VERSION:
        raise ValueError("watch configuration version must be 1")
    if type(root["feeds"]) is not list or len(root["feeds"]) != len(STOCKBIT_LANES):
        raise ValueError("watch configuration must contain all four Stockbit lanes")
    parsed_feeds = []
    for row in root["feeds"]:
        if type(row) is not dict or set(row) != {"id", "enabled"}:
            raise ValueError("each Stockbit feed must contain only id and enabled")
        lane_id = row["id"]
        if type(lane_id) is not str or lane_id not in {lane.value for lane in STOCKBIT_LANES}:
            raise ValueError("Stockbit feed ID is unsupported")
        if type(row["enabled"]) is not bool:
            raise ValueError("Stockbit feed enabled must be boolean")
        parsed_feeds.append(StockbitFeedSetting(FeedLane(lane_id), row["enabled"]))
    if {feed.lane for feed in parsed_feeds} != set(STOCKBIT_LANES):
        raise ValueError("Stockbit feed IDs must be unique and complete")
    destinations = root["destinations"]
    expected_destinations = {
        "id_stocks_news_channel_id",
        "macro_news_channel_id",
    }
    if type(destinations) is not dict or set(destinations) != expected_destinations:
        raise ValueError("Stockbit destinations have an invalid shape")
    for key in expected_destinations:
        value = destinations[key]
        if type(value) is not str or _DISCORD_ID_RE.fullmatch(value) is None:
            raise ValueError(f"{key} must be a Discord snowflake")
    issuer_channel = destinations["id_stocks_news_channel_id"]
    macro_channel = destinations["macro_news_channel_id"]
    if issuer_channel == macro_channel:
        raise ValueError("Stockbit destinations must differ")
    instruction = root["additional_prompt_instruction"]
    if type(instruction) is not str:
        raise ValueError("additional_prompt_instruction must be text")
    instruction = " ".join(instruction.split())
    if len(instruction) > 800:
        raise ValueError("additional_prompt_instruction must be at most 800 characters")
    return StockbitWatchConfig(
        feeds=tuple(parsed_feeds),
        id_stocks_news_channel_id=issuer_channel,
        macro_news_channel_id=macro_channel,
        additional_prompt_instruction=instruction,
    )
```

Define StockbitFeedSetting and StockbitWatchConfig as frozen dataclasses before the parser. Keep parser imports available in a fresh subprocess with no runtime credentials. Re-run the focused parser command and expect PASS.

- [ ] **Step 3: Add the source-parity validator bundle and registry**

Copy config.py and models.py into service-bursawatch-control/validator-sources/bursawatch-stockbit-snips/. Add the matching watcher ID, loader name load_watch_config_data, and environment key CONTROL_PLANE_STOCKBIT_CONFIG_VALIDATOR_DIR to validators.py. Extend SOURCE_FILES in test_validator_sources.py and prove both files match the cron copies byte for byte.

Run from service-bursawatch-control: mise exec -- uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' pytest -q tests/test_validators.py tests/test_validator_sources.py

Expected: the Stockbit baseline passes through the isolated validator, malformed configs fail, and source bundle parity passes.

- [ ] **Step 4: Register the source baseline and prove seed safety**

Add the Stockbit filename to BASELINE_FILES and add its complete version 1 JSON using the source defaults shown in cron-stockbit-snips/bin/config.py. The initial values are all four feeds enabled, channel IDs 1525102508714889257 and 1531655369884045382, and an empty instruction. Add tests that the baseline loads and passes the validator and that a second baseline seed leaves an existing operator revision unchanged.

Run from service-bursawatch-control: mise exec -- uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' pytest -q tests/test_baselines.py tests/test_validator_sources.py

Expected: all eight baselines load in stable watcher ID order; the second seed reports already configured.

### Task 2: Add the desired Stockbit schedule without touching Hermes

**Files:**

- Create: service-bursawatch-control/migrations/011_stockbit_snips_control_plane.sql
- Modify: service-bursawatch-control/tests/test_migrations.py
- Modify: web-config/src/lib/watcher-fields.test.ts

**Interfaces:**

- Produces scheduler job ID bursawatch-stockbit-snips, watcher ID bursawatch-stockbit-snips, runtime key bursawatch-stockbit-snips, schedule kind interval, lower bound 300 seconds, upper bound 3600 seconds, and baseline revision 1 at 900 seconds in Asia/Jakarta.
- The schedule checksum is sha256 over canonical JSON for enabled true, interval_seconds 900, and timezone Asia/Jakarta. Its expected value is 7287c1843e09696920a9a9fe00f911173640134e6fabf39c7e5e08d3f94c57f9.

- [ ] **Step 1: Add a failing migration contract test**

Assert migration 011 has the manual header, inserts the Stockbit watcher before the schedule foreign key, registers the exact job and bounds, seeds only revision 1, uses the canonical checksum, and leaves an existing current schedule revision untouched.

```python
def test_stockbit_schedule_migration_registers_existing_15_minute_job():
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations/011_stockbit_snips_control_plane.sql"
    ).read_text(encoding="utf-8")
    checksum = schedule_checksum(True, 900, "Asia/Jakarta")
    assert migration.startswith("-- bursawatch-release: manual\n")
    assert "bursawatch-stockbit-snips" in migration
    assert "'bursawatch-stockbit-snips', 'bursawatch-stockbit-snips'" in migration
    assert "'interval', 300, 3600" in migration
    assert f"'Asia/Jakarta', '{checksum}'" in migration
    assert "and current_schedule_revision is null;" in migration
```

Run from service-bursawatch-control: mise exec -- uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' pytest -q tests/test_migrations.py

Expected: FAIL because migration 011 does not exist.

- [ ] **Step 2: Add the additive manual migration**

Insert the watcher catalog record with validator key bursawatch-stockbit-snips. Add the interval job with 300 to 3600 second bounds. Insert enabled revision 1 at 900 seconds in Asia/Jakarta using the checksum above, then set it as current only when no current schedule revision exists. Do not edit migrations 001 to 010 and do not call Hermes commands.

Run from service-bursawatch-control: mise exec -- uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' pytest -q tests/test_migrations.py

Expected: PASS for the new migration contract and all existing migration immutability checks.

- [ ] **Step 3: Pin generic web interval-bound handling**

Add a schedule utility test proving the existing generic validator accepts 5 and 60 minutes and rejects 4 and 61 when job metadata supplies 300 and 3600 second bounds.

```typescript
it("uses schedule metadata for Stockbit bounds", () => {
  expect(validateScheduleMinutes("5", 300, 3600)).toBeNull();
  expect(validateScheduleMinutes("60", 300, 3600)).toBeNull();
  expect(validateScheduleMinutes("4", 300, 3600)).not.toBeNull();
  expect(validateScheduleMinutes("61", 300, 3600)).not.toBeNull();
});
```

Run from web-config: mise exec -- npm run test -- src/lib/watcher-fields.test.ts

Expected: PASS without adding a Stockbit-specific schedule implementation.

### Task 3: Load one live Stockbit config snapshot per invocation

**Files:**

- Modify: cron-stockbit-snips/bin/config.py
- Modify: cron-stockbit-snips/tests/test_config.py
- Modify: cron-stockbit-snips/tests/conftest.py only if shared Python path setup is needed

**Interfaces:**

- Produces LoadedStockbitConfig(config: StockbitWatchConfig, revision: int).
- load_watch_config_for_run() calls `live_config_settings("STOCKBIT_SNIPS")` and `fetch_config` from lib-bursawatch-control's control_plane_client using STOCKBIT_SNIPS_CONTROL_PLANE_URL, STOCKBIT_SNIPS_CONTROL_PLANE_TOKEN, STOCKBIT_SNIPS_CONTROL_PLANE_TIMEOUT_SECONDS, and STOCKBIT_SNIPS_CONTROL_PLANE_WATCHER_ID.
- The requested watcher ID must be bursawatch-stockbit-snips. No local file or environment-only config is a fallback.

- [ ] **Step 1: Add failing live-load tests**

Stub the shared client response with a valid ConfigSnapshot and assert the loader returns its revision and parsed config. Add tests for absent URL, empty token, wrong watcher ID, malformed config, and API unavailability. The loader must not read a file or use a default config in any failure case.

```python
def test_load_watch_config_for_run_returns_live_revision(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("STOCKBIT_SNIPS_CONTROL_PLANE_URL", "https://control.test")
    monkeypatch.setenv("STOCKBIT_SNIPS_CONTROL_PLANE_TOKEN", "synthetic-token")
    monkeypatch.setenv(
        "STOCKBIT_SNIPS_CONTROL_PLANE_WATCHER_ID",
        "bursawatch-stockbit-snips",
    )
    snapshot = SimpleNamespace(
        watcher_id="bursawatch-stockbit-snips",
        revision=7,
        config_version=1,
        config=valid_config(),
    )
    monkeypatch.setattr(config, "_fetch_live_config", lambda: snapshot)
    loaded = config.load_watch_config_for_run()
    assert loaded.revision == 7
    assert loaded.config.additional_prompt_instruction == ""
```

Run: mise exec -- python -m pytest -q cron-stockbit-snips/tests/test_config.py

Expected: FAIL because the live snapshot loader is not implemented.

- [ ] **Step 2: Implement the mandatory live loader**

Load the shared client dynamically inside the fetch function so the validator parser stays isolated. Verify the returned watcher ID, parse its config with load_watch_config_data, and return the exact snapshot revision. Raise a sanitized configuration error on missing settings, transport errors, or contract errors. Do not add static fallback behavior.

Run: mise exec -- python -m pytest -q cron-stockbit-snips/tests/test_config.py

Expected: PASS, including the no-fallback cases.

### Task 4: Upgrade state and implement future-only lane pause and resume

**Files:**

- Modify: cron-stockbit-snips/bin/state.py
- Modify: cron-stockbit-snips/bin/scan.py
- Modify: cron-stockbit-snips/tests/test_scan.py

**Interfaces:**

- State version becomes 2. Each feed record keeps its existing cursor, ETag, Last-Modified, timestamps, and error, plus a boolean enabled value.
- Each article record may have a config_snapshot object containing revision, additional_prompt_instruction, id_stocks_news_channel_id, and macro_news_channel_id.
- load_state(path, feeds) upgrades valid version 1 state in memory while preserving all existing values. Version 2 validation rejects a missing feed, invalid enabled value, malformed snapshot, or invalid article record.

- [ ] **Step 1: Add failing version 1 preservation and rejection tests**

Build a version 1 fixture with all four lane records and an article in pending_delivery, including ETags, cursor, lease, analysis, rendered content, attempts, and last error. Assert load_state upgrades to version 2 while preserving every field. Separately corrupt the version or article container and assert load_state raises without changing the file bytes.

```python
before = path.read_bytes()
with pytest.raises(RuntimeError, match="unsupported version|invalid"):
    state.load_state(path, config.FEEDS)
assert path.read_bytes() == before
```

Run: mise exec -- python -m pytest -q cron-stockbit-snips/tests/test_scan.py -k "state_upgrade or malformed_state"

Expected: FAIL because the state loader currently accepts only version 1 and has no migration.

- [ ] **Step 2: Implement the lossless state upgrade**

For valid version 1 files, set version to 2, initialize each lane's last-observed enabled value to true, and add no config snapshot to historical articles. Preserve all other keys byte-for-value in the parsed object. Keep the same four feed keys so state validation never derives its required lanes from the operator's enabled subset.

Run: mise exec -- python -m pytest -q cron-stockbit-snips/tests/test_scan.py -k "state_upgrade or malformed_state"

Expected: PASS with no cursor, article, or delivery reset.

- [ ] **Step 3: Add failing disabled-lane and re-enable tests**

With a cursor and ETag already stored, configure one lane disabled and assert fetch_feed is not called for it and the cursor, validators, and queued articles remain unchanged. Re-enable it and assert the first successful request has etag=None and last_modified=None, updates the cursor to the current newest item, and queues none of the paused items.

```python
assert resumed_fetch["etag"] is None
assert resumed_fetch["last_modified"] is None
assert stats["queued"] == 0
assert saved["feeds"]["unboxing"]["cursor"]["guid"] == "current-newest"
```

Also assert a fetch failure leaves the lane marked paused for the next unconditional attempt, and already queued lane items remain eligible for agent processing.

Run: mise exec -- python -m pytest -q cron-stockbit-snips/tests/test_scan.py -k "disabled_lane or reenabled_lane"

Expected: FAIL because scan.py always fetches all static FEEDS.

- [ ] **Step 4: Apply live lane settings without changing the feed catalog**

Pass the complete StockbitWatchConfig into intake. Keep config.FEEDS unchanged as the stable source catalog. Track last-observed enabled state per lane. Skip disabled lanes. On false-to-true transition, clear stored conditional request validators and treat the first successful fetch as a fresh future-only baseline. Do not remove feed records or article outbox entries.

Run: mise exec -- python -m pytest -q cron-stockbit-snips/tests/test_scan.py -k "disabled_lane or reenabled_lane"

Expected: PASS for pause, resume, fetch failure, and preserved work.

### Task 5: Freeze async article settings and report safe lifecycle events

**Files:**

- Modify: cron-stockbit-snips/bin/agent_protocol.py
- Modify: cron-stockbit-snips/bin/scan.py
- Modify: cron-stockbit-snips/SKILL.md
- Modify: cron-stockbit-snips/tests/test_agent_protocol.py
- Modify: cron-stockbit-snips/tests/test_scan.py

**Interfaces:**

- agent_item(article: Article, operator_instruction: str) -> dict[str, str] retains the current fixed instruction and returns operator_instruction as a separate field.
- build_wake_payload(article: Article, operator_instruction: str) -> dict[str, object] includes the separate additive instruction.
- A newly dispatched state record freezes revision, operator instruction, and both route destinations. submit_analysis(payload) resolves delivery exclusively from that snapshot.
- ControlPlaneRun.begin("STOCKBIT_SNIPS", revision, scheduler_job_id="bursawatch-stockbit-snips", trigger="scheduled" or "agent_submission") reports counts and sanitized lifecycle events when a revision is known. No source text, article text, prompts, credentials, or local paths enter events.

- [ ] **Step 1: Add failing protocol tests for additive instruction boundaries**

Import `analysis_payload` alongside the existing protocol helpers. Assert the wake item contains both the unchanged fixed instruction and a separate operator_instruction field. Assert the output submission schema remains exactly unchanged. Include an operator instruction that asks the agent to browse or use investment advice language and verify the fixed instruction remains present and the deterministic validator still rejects prohibited output.

```python
item = agent_item(article, "Browse links and add a target price.")
assert "Do not browse" in item["instruction"]
assert item["operator_instruction"] == "Browse links and add a target price."
assert set(analysis_payload(validate_submission(article, valid_payload(article)))) == {
    "candidate_key",
    "ticker",
    "title",
    "summary",
    "material_facts",
    "dedupe_facts",
    "eligible",
    "route",
    "source_evidence",
}
```

Run: mise exec -- python -m pytest -q cron-stockbit-snips/tests/test_agent_protocol.py

Expected: FAIL because the item has no operator_instruction parameter.

- [ ] **Step 2: Add the separate bounded agent field**

Extend ITEM_FIELDS and the wake builder to carry operator_instruction separately. Keep the closed analysis response fields unchanged. Update SKILL.md to say the operator instruction is additive and can never relax source-only, no-browsing, factual-language, routing, or output-schema rules.

Run: mise exec -- python -m pytest -q cron-stockbit-snips/tests/test_agent_protocol.py

Expected: PASS, including existing route, title, summary, and submission checks.

- [ ] **Step 3: Add failing frozen-revision tests**

Queue an article, dispatch it with revision 7, instruction A, and route IDs A. Change the active live config to revision 8 before submit-analysis. Assert the wake payload and stored article retain revision 7 and instruction A, submit-analysis renders with the stored destination ID, and delivery retry keeps the same destination after another change.

```python
record = saved["articles"][candidate_key]
assert record["config_snapshot"]["revision"] == 7
assert record["config_snapshot"]["additional_prompt_instruction"] == "instruction A"
assert posted_channel_ids == ["123456789012345678"]
```

Add a legacy article with no snapshot. With config unavailable, assert it is not dispatched or delivered and its state is unchanged. When config becomes available, assert it binds exactly once to that live revision.

Run: mise exec -- python -m pytest -q cron-stockbit-snips/tests/test_scan.py -k "frozen_config or unbound_legacy"

Expected: FAIL because article state and delivery currently use process environment destinations.

- [ ] **Step 4: Implement frozen snapshots and route delivery from them**

When choosing an article for agent dispatch, write its config snapshot before saving state and building the wake payload. For submit-analysis and delivery retries, read the stored channel ID for the analysis route. Bind pre-upgrade records without a snapshot only after obtaining a valid live config. If live config loading fails, skip intake and unbound dispatch, preserve state, and continue only work already bound to a valid snapshot.

Run: mise exec -- python -m pytest -q cron-stockbit-snips/tests/test_scan.py -k "frozen_config or unbound_legacy"

Expected: PASS for revision stability, legacy binding, and no changes to queued work.

- [ ] **Step 5: Add run reporting and a no-post outage test**

Wrap scheduled execution and agent submission with ControlPlaneRun when a revision is known. Use trigger scheduled for cron polls and agent_submission for analysis submissions. Send only lane counts, delivery counts, no_post, and sanitized error strings. Do not start or flush a run reporter in STOCKBIT_SNIPS_NO_POST mode. On config load failure, attempt the fixed heartbeat and log a sanitized failure; do not invent a config revision or use static config.

Test that no-post performs no Discord call and no control-plane event write, and that an API failure still attempts the system heartbeat while a frozen pending delivery continues.

Run: mise exec -- python -m pytest -q cron-stockbit-snips/tests/test_scan.py

Expected: PASS with all Stockbit scanner tests using temporary state and stubbed config, RSS, market data, Discord, and reporter dependencies.

### Task 6: Add Stockbit to the authenticated web-config editor

**Files:**

- Modify: web-config/src/lib/watcher-fields.ts
- Modify: web-config/src/lib/watcher-fields.test.ts
- Modify: web-config/src/components/watcher-config-editor.tsx
- Modify: web-config/src/components/connected-workflow-summary.tsx
- Modify: web-config/scripts/control-workspace-smoke.mjs
- Modify: web-config/docs/CONFIGURATION_COVERAGE.md
- Modify: web-config/docs/CONTROL_PLANE.md
- Modify: web-config/AGENTS.md

**Interfaces:**

- watcherNames includes bursawatch-stockbit-snips and supportsWatcherConfig accepts config version 1.
- validateWatcherConfig(watcherId, config) checks the four unique fixed feed IDs, enabled booleans, the two distinct Discord snowflakes, and the 800-character instruction limit.
- StockbitFields renders all four feed switches, two route IDs, and the additive instruction. It does not render source URLs, heartbeat, credentials, parser controls, or agent hard rules.
- The generic schedule editor consumes job bounds from the API. Do not add a separate Stockbit scheduler or browser write path.

- [ ] **Step 1: Add failing client validation tests**

Add a valid config using the Stockbit shape from Task 1 and synthetic destination IDs. Assert it has no errors. Mutate one field at a time to cover a missing lane, duplicate ID, invalid enabled value, malformed or duplicate route ID, unknown root field, and an 801-code-point instruction. Verify 800 ASCII characters and 800 non-BMP Unicode code points are accepted.

```typescript
const stockbitWatcherId = "bursawatch-stockbit-snips";
const validStockbitConfig = () => ({
  version: 1,
  feeds: [
    { id: "stockbit_commentary", enabled: true },
    { id: "unboxing", enabled: true },
    { id: "unboxing_ipo", enabled: true },
    { id: "ai_reports_stockbit", enabled: true },
  ],
  destinations: {
    id_stocks_news_channel_id: "123456789012345678",
    macro_news_channel_id: "234567890123456789",
  },
  additional_prompt_instruction: "",
});

it("validates the complete Stockbit config shape", () => {
  expect(validateWatcherConfig(stockbitWatcherId, validStockbitConfig())).toEqual({});
  expect(
    validateWatcherConfig(stockbitWatcherId, { ...validStockbitConfig(), extra: true }),
  ).toHaveProperty("extra");
});
```

Run from web-config: mise exec -- npm run test -- src/lib/watcher-fields.test.ts

Expected: FAIL because Stockbit is not a supported watcher editor yet.

- [ ] **Step 2: Implement watcher registration and strict client validation**

Add the Stockbit label and v1 support. Add a dedicated validation branch before the generic Telegram watcher branch. Use the existing Discord snowflake validator and prompt helper; count normalized instruction length with `Array.from(instruction).length` so browser and Python limits both count Unicode code points.

Run from web-config: mise exec -- npm run test -- src/lib/watcher-fields.test.ts

Expected: PASS, including all existing watcher validation tests.

- [ ] **Step 3: Render the Stockbit form and workspace summary**

Add a StockbitFields component in watcher-config-editor.tsx. Use checkbox fields at feeds.<index>.enabled, text fields at destinations.id_stocks_news_channel_id and destinations.macro_news_channel_id, and a multiline field at additional_prompt_instruction. Add the Stockbit input, processing, and Discord output summary. Keep /app sample preferences separate.

Add a browser fixture to control-workspace-smoke.mjs with a synthetic Stockbit watcher, config using non-production snowflakes 123456789012345678 and 234567890123456789, and a 15-minute schedule. At desktop and 375-pixel widths, verify the settings page loads all controls, save sends a complete v1 config, stale-save behavior remains unchanged, and the schedule view displays pending or applied state from backend data.

Run from web-config: mise exec -- npm run test:browser

Expected: PASS using intercepted synthetic API responses and no live credentials or messages.

- [ ] **Step 4: Update web coverage and operator guidance**

Change the coverage from seven to eight watcher editors. Document the Stockbit fields, fixed sources and heartbeat boundary, future-only lane behavior, live revision semantics, and generic schedule application status. Update web-config/AGENTS.md from seven editors to eight and describe the new config contract without putting production values in public fixtures.

Run from web-config: mise exec -- npm run check

Expected: format, lint, typecheck, Vitest, and production build pass.

### Task 7: Wire runtime release, validator environment, and no-post verification

**Files:**

- Modify: cron-stockbit-snips/bin/bursawatch-stockbit-snips.sh
- Modify: cron-stockbit-snips/AGENTS.md
- Modify: cron-stockbit-snips/SKILL.md
- Create: cron-stockbit-snips/tests/test_wrapper.py
- Modify: service-bursawatch-control/env.example
- Modify: service-bursawatch-control/README.md
- Modify: service-bursawatch-control/deployment/README.md
- Modify: service-bursawatch-control/AGENTS.md
- Modify: service-bursawatch-control/tests/test_deployment_assets.py
- Modify: platform-bursawatch-release/release-manifest.json
- Modify: platform-bursawatch-release/bin/release_agent.py
- Modify: platform-bursawatch-release/tests/test_release_agent.py

**Interfaces:**

- The Stockbit wrapper exports the existing per-watcher control-plane URL, watcher ID, token, and timeout keys from the Hermes environment without printing values, including in release no-post so its mandatory config GET can succeed. It does not export a control-plane spool path. It prepends lib-bursawatch-control/bin to PYTHONPATH when deployed.
- The runtime unit depends on lib-bursawatch-control in release-manifest.json.
- Release no-post uses a fresh temporary state path, allows the config GET required by the mandatory live runtime, suppresses Discord and control-plane event writes, and does not submit agent analysis.
- The dedicated API setting is CONTROL_PLANE_STOCKBIT_CONFIG_VALIDATOR_DIR pointing to /home/praya/.hermes/bursawatch-control-plane/validator-sources/bursawatch-stockbit-snips. Only templates and docs change locally; the live environment and service are not changed here.

- [ ] **Step 1: Add failing release and wrapper boundary tests**

Assert the Stockbit runtime unit depends on lib-bursawatch-control. Assert the no-post specification uses a unique temporary state file, enables STOCKBIT_SNIPS_NO_POST, and sets no event spool or reporter override. Add the wrapper test from Step 2 and assert captured logs contain none of the synthetic URL or token values.

```python
manifest_data = json.loads(
    (ROOT / "release-manifest.json").read_text(encoding="utf-8")
)
stockbit_runtime_unit = next(
    unit for unit in manifest_data["units"]
    if unit["id"] == "cron-stockbit-snips"
)
spec = release_agent._no_post_specification("stockbit-snips-no-post", tmp_path)
try:
    assert spec.environment["STOCKBIT_SNIPS_NO_POST"] == "1"
    assert spec.environment["STOCKBIT_SNIPS_STATE_PATH"] == str(
        spec.temporary_path / "state.json"
    )
    assert "lib-bursawatch-control" in stockbit_runtime_unit.get("depends_on", [])
finally:
    shutil.rmtree(spec.temporary_path, ignore_errors=True)
```

Run: mise exec -- python -m pytest -q platform-bursawatch-release/tests/test_release_agent.py

Expected: FAIL because the Stockbit release unit has no shared-library dependency and the wrapper does not yet load the required control-plane settings.

- [ ] **Step 2: Add wrapper control-plane environment support**

Follow the existing watcher wrapper pattern. Read only STOCKBIT_SNIPS_CONTROL_PLANE_URL, STOCKBIT_SNIPS_CONTROL_PLANE_WATCHER_ID, STOCKBIT_SNIPS_CONTROL_PLANE_TOKEN, and STOCKBIT_SNIPS_CONTROL_PLANE_TIMEOUT_SECONDS from ~/.hermes/.env, including in release no-post. Never print values or load a spool path. Add lib-bursawatch-control/bin to PYTHONPATH when present and fail clearly if the required shared library is absent.

In cron-stockbit-snips/tests/test_wrapper.py, run the Bash wrapper with a temporary HOME containing a synthetic `.hermes/.env`, a stub Python executable that records only its received environment into a temporary capture file, a synthetic runtime script, and a temporary `~/.agents/skills/lib-bursawatch-control/bin/control_plane_client.py` sentinel. Set `STOCKBIT_SNIPS_NO_POST=1`, `STOCKBIT_SNIPS_STATE_PATH` under the temporary directory, and `BURSAWATCH_RELEASE_NO_POST_TEMP` under the temporary directory. Assert the child receives the four allowed settings, PYTHONPATH includes the shared client directory, state and log paths stay temporary, and captured logs contain none of the synthetic URL or token values. Add a second case without the shared client sentinel and assert the wrapper exits nonzero with a sanitized missing-library message before starting the Python child. The test must not invoke installed production binaries or state.

Run from the repository root: mise exec -- python -m pytest -q cron-stockbit-snips/tests/test_wrapper.py

Expected: PASS with the synthetic environment and temporary paths; missing shared-library setup fails before the Python child starts.

- [ ] **Step 3: Make release no-post safe for mandatory DB config**

Add lib-bursawatch-control to the Stockbit runtime manifest dependency. In the scanner, no-post mode must not start ControlPlaneRun, emit control-plane events, or create a spool. Keep the required read-only config fetch and isolated RSS state for the release agent check. Extend release-agent tests to verify that the Stockbit no-post path does not set a fake static config, does not enable a reporter, and uses only temporary local state.

Run from the repository root: mise exec -- python -m pytest -q platform-bursawatch-release/tests/test_release_agent.py cron-stockbit-snips/tests/test_scan.py cron-stockbit-snips/tests/test_wrapper.py

Expected: PASS, with no Discord sends or API event writes from no-post execution.

- [ ] **Step 4: Document the trusted validator path and operational gate**

Add CONTROL_PLANE_STOCKBIT_CONFIG_VALIDATOR_DIR to env.example. Update the service README, deployment README, and service AGENTS.md to name the isolated Stockbit validator bundle path and state that config PUTs remain unavailable until the reviewed path is configured. Update the Stockbit package AGENTS.md and SKILL.md for live config requirements, frozen settings, state version 2, and operator-instruction boundaries.

Update test_deployment_assets.py to assert the tracked template and docs contain the new validator key and point to validator-sources, not the live cron directory. Do not inspect or change the ignored local service .env or the dedicated VPS environment.

Run from service-bursawatch-control: mise exec -- uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' pytest -q tests/test_deployment_assets.py tests/test_validators.py tests/test_validator_sources.py

Expected: PASS; production environment changes remain absent.

### Task 8: Run full local integration verification

**Files:**

- No additional implementation files. Resolve failures only in the owning files and tests listed above.

**Interfaces:**

- The full local system has eight config validators and eight typed editors.
- Local integration verification uses test fixtures and an isolated no-post path. It performs no production DB writes, service restarts, schedule changes, deployments, or Discord posts.

- [ ] **Step 1: Run the Stockbit package suite**

Run from the repository root: mise exec -- python -m pytest -q cron-stockbit-snips/tests

Expected: PASS, including parser, live-load, state-upgrade, lane-pause, frozen-snapshot, submit-analysis, and no-post cases.

- [ ] **Step 2: Run service and release suites**

Run from service-bursawatch-control: mise exec -- uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' pytest -q tests

Run from platform-bursawatch-release: mise exec -- python -m pytest -q tests

Expected: PASS for all eight validator baselines, manual migration contract, manifest dependencies, release no-post isolation, API auth, and service deployment asset rules.

- [ ] **Step 3: Run the web-config checks and browser smoke**

Run from web-config: mise exec -- npm ci

Run from web-config: mise exec -- npm run check

Run from web-config: mise exec -- npm run test:browser

Expected: PASS for formatter, linter, type checking, unit tests, build, and intercepted workspace browser flows at desktop and 375px mobile widths.

- [ ] **Step 4: Run repository validation**

Run from the repository root: bash scripts/test-all

Expected: PASS for the existing cron, library, service, platform, repository-policy, and release-agent suites. Leave the WT uncommitted and report any separate production release prerequisites.

## Execution boundary after this plan

This plan ends after local source and test validation. Production work remains a separate reviewed operation. Before any release, inspect the live Stockbit schedule and effective destination IDs read-only; review the manual migration; show the exact dedicated API environment change and required service restart; seed the baseline only when config history is absent; confirm reconciliation against the existing 15-minute Hermes job; then review the runtime and web release paths separately. Do not change the Hermes job as part of initial registration.
