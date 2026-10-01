# WhatsApp Channel archive and specialized forwarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Archive raw BRI, INS, and Samuel WhatsApp Channel posts safely, make BRI's new posts forwardable as bounded News Items, and provide a documented archive-inspection helper without replaying history.

**Architecture:** Profile configuration version 2 distinguishes archive-only observation from forwarding. The bridge sink writes immutable source evidence and the scanner requires that evidence before creating a BRI delivery record. Analysis produces ordered News Items, while the scanner owns per-item text, media, and Board-handoff checkpoints. The archive stays in VPS-owned state and is queried only through a bounded local helper.

**Tech Stack:** Python standard library, Node.js standard library, existing Baileys bridge patch, existing Discord REST helper, existing Swing Plan Board CLI, pytest, Node test runner.

**Spec:** `docs/superpowers/specs/2026-09-21-whatsapp-channel-archive-and-forwarding-design.md`

## Global Constraints

- Use the existing single Baileys connection. Never pair or create a second WhatsApp session.
- Raw Channel payloads, media paths, archive records, and credentials never reach Git, dotfiles, control-plane events, or Discord diagnostics.
- Runtime archive root is `~/.hermes/state/whatsapp-channel-watch/archive/`; archive directories use `0700` and files use `0600`.
- Retain raw records and copied supported media for 365 days. `prune` is dry-run by default and is never scheduled.
- BRI historical queue and outbox data are archive-only. Nothing prior to the explicit cutover cursor is deliverable.
- INS and Samuel are `observe` profiles. They must not create an outbox record, LLM wake, Discord post, or Board handoff.
- An exact leading, case-sensitive `#TechnicalReview` is the sole automatic Swing signal. A technical review needs one archived image. Only a single verified ticker can create Board `social` Chart context after All Swing succeeds.
- Run all tests with isolated paths and no-post controls. Tests must not contact the live bridge, WhatsApp, Discord, the Board forum, or the control plane.
- Do not commit, push, deploy, subscribe Channels, apply a BRI cutover, activate a Hermes job, or prune runtime data as part of this plan. Each is a later explicit approval.

## Review Focus

- A bridge archive write fails after queue intake: the scanner must withhold forwarding and preserve retryability. Covered in Task 4.
- A source media path is a symlink, outside the staging root, too large, or missing: the archive must record safe capture failure and never copy arbitrary files. Covered in Task 3.
- An `observe` profile has a new message: the scanner may archive it but must not initialize forwarding state, wake the LLM, or post. Covered in Task 4.
- A multi-item post has one source image: item text may route independently but the image must never be duplicated. Covered in Task 5.
- A technical review has multiple or no verifiable IDX tickers: All Swing remains the only delivery and no Board source event may be submitted. Covered in Task 6.
- A BRI stock pick, valuation, target, promotion, or call to action is finance-shaped but must remain filtered and archive-only. Covered in Task 5.

## File structure

- `cron-wa-channel-watch/bin/archive.py`: immutable record serialization, file permissions, checksum verification, bounded query/export, and cutover planning primitives.
- `cron-wa-channel-watch/bin/bursawatch-wa-channel-archive.sh`: archive helper wrapper that constrains runtime paths and invokes `archive.py`.
- `cron-wa-channel-watch/bin/models.py`, `config.py`: version-2 profile lifecycle and ordered analysis item value objects.
- `cron-wa-channel-watch/bin/channel_sink.mjs`: bridge-side archive capture, staging validation, and event-to-profile mapping.
- `cron-wa-channel-watch/bin/scan.py`, `agent_protocol.py`, `render.py`, `state.py`: archive gate, observation behavior, News Item protocol, per-item delivery checkpoints, and typed Board handoff.
- `cron-wa-channel-watch/bin/bursawatch-wa-channel-watch.sh`: archive-root runtime wiring and isolated no-post validation.
- `cron-wa-channel-watch/config/watches.json` and `service-bursawatch-control/baseline-configs/bursawatch-wa-channel-watch.json`: identical version-2 BRI, INS, and Samuel reviewed profiles.
- `service-bursawatch-control/validator-sources/bursawatch-wa-channel-watch/{config,models}.py`: byte-identical validator copies.
- `cron-wa-channel-watch/integrations/bridge-channel-sink.patch`: reviewed additive bridge import, archive-root wiring, and bounded media staging.
- `cron-wa-channel-watch/tests/*`, `service-bursawatch-control/tests/*`: isolated Python, Node, configuration, scanner, helper, and contract coverage.
- `cron-wa-channel-watch/AGENTS.md`, `cron-wa-channel-watch/SKILL.md`, `docs/adr/0027-profile-isolated-whatsapp-channel-archive.md`: durable operating contract and decision record.

### Task 1: Profile lifecycle version 2 and three reviewed source identities

**Files:**
- Modify: `cron-wa-channel-watch/bin/models.py:29-68`
- Modify: `cron-wa-channel-watch/bin/config.py:13-151`
- Modify: `cron-wa-channel-watch/config/watches.json`
- Modify: `service-bursawatch-control/baseline-configs/bursawatch-wa-channel-watch.json`
- Modify: `service-bursawatch-control/validator-sources/bursawatch-wa-channel-watch/models.py`
- Modify: `service-bursawatch-control/validator-sources/bursawatch-wa-channel-watch/config.py`
- Modify: `cron-wa-channel-watch/tests/test_config.py`
- Modify: `service-bursawatch-control/tests/test_baselines.py`

**Interfaces:**
- Produces: `ChannelProfile.mode: str`, `ChannelProfile.is_observing: bool`, and `WatchConfig.version == 2` for Tasks 3 to 6.
- Produces: the three canonical profile identities for bridge subscription and archive namespace selection.

- [ ] **Step 1: Write failing version-2 configuration tests**

```python
def test_observe_profile_needs_no_discord_presentation(tmp_path):
    observed = profile(
        id="ins", channel_jid="120363405187024421@newsletter",
        mode="observe", emoji=None, discord_channels=[],
        enable_llm_title=False, enable_llm_summary=False,
        enable_llm_routing=False, enable_llm_relevance_filter=False,
        forward_media=False,
    )
    loaded = config.load_data({"version": 2, "profiles": [observed]})
    assert loaded.profiles[0].is_observing is True

def test_forward_profile_requires_routes_and_presentation():
    with pytest.raises(ValueError, match="forward profile requires"):
        config.load_data({"version": 2, "profiles": [profile(mode="forward", emoji=None)]})
```

- [ ] **Step 2: Run the focused configuration tests and verify RED**

Run: `../.venv/bin/python -m pytest -q cron-wa-channel-watch/tests/test_config.py`

Expected: FAIL because version `2`, `mode`, and `is_observing` are not implemented.

- [ ] **Step 3: Add the minimal model and strict parser changes**

```python
@dataclass(frozen=True)
class ChannelProfile:
    id: str
    enabled: bool
    mode: str
    # existing source and forwarding fields stay unchanged

    @property
    def is_observing(self) -> bool:
        return self.enabled and self.mode == "observe"

    @property
    def is_forwarding(self) -> bool:
        return self.enabled and self.mode == "forward"
```

Accept exactly `"observe"` and `"forward"`; accept empty routes and `emoji: null` only for `observe`; require BRI's route and emoji fields for `forward`.

- [ ] **Step 4: Add the reviewed static and baseline profiles**

Use `version: 2`. Keep BRI as `mode: "forward"` with its existing three destinations. Add `ins` and `samuel-sekuritas-indonesia` with their resolved JIDs and public URLs, `mode: "observe"`, no routes, null presentation fields, no LLM flags, and `forward_media: false`. Copy the static JSON byte-for-byte into the control-plane baseline.

Set BRI's `additional_prompt_instruction` to its reviewed allowlist: include only material issuer events/disclosures, factual market or macro developments, coherent macro roundups, and exact technical reviews; exclude promotions, calls to action, analyst research, stock picks, watchlists, outlooks, valuations, targets, and untagged technical material.

- [ ] **Step 5: Synchronize validator sources and extend parity tests**

Copy the completed watcher `models.py` and `config.py` to the validator-source bundle. Add an assertion that the baseline lists all three profile IDs and validates under the source parser.

- [ ] **Step 6: Run focused configuration and control-plane tests and verify GREEN**

Run: `../.venv/bin/python -m pytest -q cron-wa-channel-watch/tests/test_config.py service-bursawatch-control/tests/test_baselines.py service-bursawatch-control/tests/test_validator_sources.py`

Expected: PASS.

### Task 2: Immutable archive records and local inspection helper

**Files:**
- Create: `cron-wa-channel-watch/bin/archive.py`
- Create: `cron-wa-channel-watch/bin/bursawatch-wa-channel-archive.sh`
- Create: `cron-wa-channel-watch/tests/test_archive.py`

**Interfaces:**
- Consumes: `ChannelEvent` and profile ID from Task 1.
- Produces: `archive.ensure(root, profile_id, event, config_revision) -> ArchiveResult`, `archive.verify(root) -> dict[str, int]`, `archive.query(...) -> list[ArchiveRecord]`, and `archive.main()` for Task 4 and the operator wrapper.

- [ ] **Step 1: Write failing archive persistence and permission tests**

```python
def test_ensure_is_atomic_idempotent_and_private(tmp_path):
    result = archive.ensure(tmp_path, "bri-danareksa-sekuritas", event(), None)
    assert result.created is True
    assert stat.S_IMODE(result.record_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(result.record_path.parent.stat().st_mode) == 0o700
    assert archive.ensure(tmp_path, "bri-danareksa-sekuritas", event(), None).created is False
    assert archive.verify(tmp_path)["invalid"] == 0

def test_query_writes_raw_export_only_to_explicit_private_path(tmp_path):
    archive.ensure(tmp_path, "ins", event(), None)
    export_path = tmp_path / "review.jsonl"
    result = archive.export(tmp_path, profile_id="ins", output=export_path, format="jsonl")
    assert result["exported"] == 1
    assert stat.S_IMODE(export_path.stat().st_mode) == 0o600
```

- [ ] **Step 2: Run archive tests and verify RED**

Run: `../.venv/bin/python -m pytest -q cron-wa-channel-watch/tests/test_archive.py`

Expected: FAIL because `archive` does not exist.

- [ ] **Step 3: Implement the archive module with only standard-library primitives**

```python
def ensure(root: Path, profile_id: str, event: ChannelEvent, config_revision: int | None) -> ArchiveResult:
    record = build_record(profile_id, event, config_revision)
    target = record_path(root, record)
    return atomic_write_or_compare(target, record)

def export(root: Path, *, profile_id: str, output: Path, format: str) -> dict[str, int]:
    records = query(root, profile_id=profile_id)
    write_private_export(output, records, format)
    return {"exported": len(records)}
```

Use a SHA-256 event-key filename, UTC date partitions, deterministic JSON, temporary `0600` files plus `fsync` and `os.replace`, and collision rejection when an existing record with the same identity differs. Store only archive-owned media references; media copying belongs to Task 3.

- [ ] **Step 4: Implement bounded helper commands**

`archive.py` accepts `verify`, `query`, `export`, and `prune`. `query` prints safe counts and event metadata; `export` requires `--output` and supports `--format jsonl|markdown`; `prune` only reports candidates unless `--apply` is supplied. The shell wrapper sets `WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT` to the VPS state default, reads no secrets, and invokes only this package's `archive.py`.

- [ ] **Step 5: Add failure and boundary tests**

```python
def test_collision_is_rejected_and_prune_is_dry_run(tmp_path):
    archive.ensure(tmp_path, "ins", event(), None)
    with pytest.raises(ValueError, match="collision"):
        archive.ensure(tmp_path, "ins", event(text="changed source"), None)
    assert archive.prune(tmp_path, before=date(2027, 1, 1), apply=False)["deleted"] == 0
```

Cover invalid profile IDs, invalid time bounds, an output path that already exists, a checksum mismatch, and `--apply` refusal unless the archive root is absolute.

- [ ] **Step 6: Run archive tests and verify GREEN**

Run: `../.venv/bin/python -m pytest -q cron-wa-channel-watch/tests/test_archive.py`

Expected: PASS.

### Task 3: Bridge-side archive intake and bounded media staging

**Files:**
- Modify: `cron-wa-channel-watch/bin/channel_sink.mjs`
- Modify: `cron-wa-channel-watch/integrations/bridge-channel-sink.patch`
- Modify: `cron-wa-channel-watch/tests/channel_sink.test.mjs`

**Interfaces:**
- Consumes: enabled profile JIDs from Task 1 and normalized bridge payloads.
- Produces: `archiveChannelEvent(payload, { archiveDir, profileId, stagingRoot }) -> boolean` and an archive-complete payload for Task 4.

- [ ] **Step 1: Write failing Node tests for archive writes and hostile media paths**

```javascript
test('writes one private archived source record for a configured profile', async () => {
  const archiveDir = await mkdtemp(path.join(tmpdir(), 'wa-archive-'));
  assert.equal(archiveChannelEvent(payload, {archiveDir, profileId: 'ins', stagingRoot: archiveDir}), true);
  assert.equal(archiveChannelEvent(payload, {archiveDir, profileId: 'ins', stagingRoot: archiveDir}), false);
});

test('never copies a symlink or a path outside media staging', async () => {
  assert.throws(() => archiveChannelEvent(mediaPayload, {archiveDir, profileId: 'bri', stagingRoot}), /staging root/);
});
```

- [ ] **Step 2: Run Node sink tests and verify RED**

Run: `node --test cron-wa-channel-watch/tests/channel_sink.test.mjs`

Expected: FAIL because `archiveChannelEvent` is not exported.

- [ ] **Step 3: Implement Node archive capture without changing normal message handling**

Use the existing SHA-256 identity and atomic temporary-file pattern. Add `archiveChannelEvent` beside `enqueueChannelEvent`, create only `0700` directories and `0600` files, and preserve full source text/caption, links, timestamps, media descriptors, capture status, and profile ID. Add `copyStagedMedia` that resolves a regular non-symlink file below a supplied absolute staging root, rejects files above the documented limit, copies it to a content-addressed archive-owned path, and records its digest. A capture failure becomes a structured unavailable status, not a raw path.

The Node record uses the exact `archive.py` schema version, event-key filename, UTC partition layout, and deterministic JSON field set from Task 2. Add a Python archive fixture representing that Node record and assert `archive.verify` and `archive.query` accept it, so a bridge-side schema drift cannot silently make captured records unreadable.

- [ ] **Step 4: Update the retained bridge patch**

Extend the reviewed patch so the existing `@newsletter` intake path resolves the enabled JID to a configured profile, invokes archive capture before queue processing, supplies explicit queue/archive/staging roots, and logs only sanitized archive failure reasons. It must keep the current local-only history and explicit-follow behavior unchanged. Do not apply the patch to a VPS during development.

- [ ] **Step 5: Run Node sink tests and verify GREEN**

Run: `node --test cron-wa-channel-watch/tests/channel_sink.test.mjs`

Expected: PASS.

### Task 4: Scanner archive gate, observation mode, and no-replay cutover planning

**Files:**
- Modify: `cron-wa-channel-watch/bin/scan.py:39-321,426-452`
- Modify: `cron-wa-channel-watch/bin/bursawatch-wa-channel-watch.sh`
- Modify: `cron-wa-channel-watch/bin/state.py`
- Modify: `cron-wa-channel-watch/tests/test_scan.py`
- Modify: `cron-wa-channel-watch/tests/test_subscriptions.py`

**Interfaces:**
- Consumes: `archive.ensure` from Task 2 and `ChannelProfile.is_observing/is_forwarding` from Task 1.
- Produces: a queue run that archives every configured source, creates records only for forwarding profiles, and records an archive-complete event marker for Tasks 5 and 6.

- [ ] **Step 1: Write failing observation and archive-gate tests**

```python
def test_observation_profile_archives_but_never_wakes_or_changes_forward_cursor(tmp_path):
    result = scan.run(config_path=observe_config(tmp_path), state_path=tmp_path / "state.json", queue_dir=queue(tmp_path), archive_dir=tmp_path / "archive", no_post=True)
    assert result["archived"] == 1
    assert result["wakeAgent"] is False
    assert state.load(tmp_path / "state.json")["profiles"] == {}

def test_forwarding_waits_for_archive_before_claiming(tmp_path, monkeypatch):
    monkeypatch.setattr(scan.archive, "ensure", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")))
    result = scan.run(config_path=forward_config(tmp_path), state_path=tmp_path / "state.json", queue_dir=queue(tmp_path), archive_dir=tmp_path / "archive", no_post=True)
    assert result["wakeAgent"] is False
    assert "disk full" in result["errors"][0]
```

- [ ] **Step 2: Run scanner tests and verify RED**

Run: `../.venv/bin/python -m pytest -q cron-wa-channel-watch/tests/test_scan.py cron-wa-channel-watch/tests/test_subscriptions.py`

Expected: FAIL because `archive_dir`, `archived`, and profile modes do not exist.

- [ ] **Step 3: Add archive-root wiring and profile-mode scan behavior**

Add `--archive-dir` and `WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT` with default `$HOME/.hermes/state/whatsapp-channel-watch/archive`. Require an absolute archive path whenever `WHATSAPP_CHANNEL_WATCH_NO_POST=1`. For every enabled profile event, call `archive.ensure`. For `observe`, stop after archival. For `forward`, retain the existing future-only initialization but never advance past an event whose archive write failed. Add aggregate archive counts to the heartbeat and sanitized control-plane attributes only.

- [ ] **Step 4: Add read-only cutover planning**

Implement `archive.py cutover-plan --queue-dir --state --profile bri-danareksa-sekuritas` to report event count, earliest/latest identity, existing outbox count, proposed new cursor, and no mutations. Add `cutover-apply` behind both `--apply` and a production-only environment guard, but test only its isolated temporary-state behavior. It archives old records, writes an atomic manifest, and sets no delivery-ready record.

- [ ] **Step 5: Add regression tests for future-only and subscription targets**

Assert that subscription dry-run includes BRI, INS, and Samuel because each is enabled. Assert that a BRI baseline queue is archived and becomes the cutover cursor rather than an outbox item, and a post added after the cursor becomes the sole claimable event.

- [ ] **Step 6: Run scanner and subscription tests and verify GREEN**

Run: `../.venv/bin/python -m pytest -q cron-wa-channel-watch/tests/test_scan.py cron-wa-channel-watch/tests/test_subscriptions.py`

Expected: PASS.

### Task 5: Ordered News Items, concise macro rendering, and media checkpoints

**Files:**
- Modify: `cron-wa-channel-watch/bin/agent_protocol.py`
- Modify: `cron-wa-channel-watch/bin/scan.py:65-128,323-425`
- Modify: `cron-wa-channel-watch/bin/render.py`
- Modify: `cron-wa-channel-watch/bin/state.py`
- Modify: `cron-wa-channel-watch/tests/test_agent_protocol.py`
- Modify: `cron-wa-channel-watch/tests/test_render.py`
- Modify: `cron-wa-channel-watch/tests/test_scan.py`

**Interfaces:**
- Consumes: forward profile and archive-complete event from Tasks 1 and 4.
- Produces: validated `items: list[NewsItem]`, per-item text/media checkpoints, and an ordered rendered delivery for Task 6.

- [ ] **Step 1: Write failing protocol tests for one, many, and forbidden item shapes**

```python
def test_macro_roundup_is_one_item_without_category_prefix():
    result = agent_protocol.validate_submission(profile(), {
        "event_key": "12345@newsletter:macro",
        "is_relevant": True,
        "items": [{"title": "Menkeu Baru dan Revisi HPM Nikel", "summary": "*(Ringkasan)* Ringkasan kebijakan.", "route": "macro_news"}],
    })
    assert result["items"][0]["route"] == "macro_news"

def test_many_items_cannot_reuse_one_source_image():
    assert agent_protocol.media_delivery_indexes(item_count=2, media_count=1) == ()

def test_bri_prompt_excludes_recommendation_and_promotional_material():
    instruction = agent_protocol.instruction_for(profile())
    assert "stock picks" in instruction
    assert "product activation" in instruction
```

- [ ] **Step 2: Run protocol, rendering, and scanner tests and verify RED**

Run: `../.venv/bin/python -m pytest -q cron-wa-channel-watch/tests/test_agent_protocol.py cron-wa-channel-watch/tests/test_render.py cron-wa-channel-watch/tests/test_scan.py`

Expected: FAIL because analysis currently accepts only one title, summary, and route.

- [ ] **Step 3: Replace event-level analysis with bounded ordered items**

```python
@dataclass(frozen=True)
class NewsItem:
    title: str
    summary: str
    route: str
    ticker: str | None = None

def validate_submission(profile: ChannelProfile, payload: object) -> dict[str, object]:
    # irrelevant keeps {event_key, is_relevant: false}; relevant requires 1..8 items
```

Require one to eight items, non-empty validated title, summary, and configured route fields, one or two summary paragraphs, and no category-prefix synthesis. `ticker` is either `null` or an uppercase ticker token that occurs in the raw Source Post. Keep the exact technical override but require it to validate as exactly one `id_stocks_swing` item; a technical item may use `ticker: null` when the source has no single unambiguous ticker, which makes it Board-ineligible.

Extend the BRI profile instruction with the reviewed allowlist. The LLM relevance branch must return the existing minimal irrelevant payload for promotions, calls to action, analyst research, stock picks, watchlists, outlooks, valuations, targets, and untagged technical material. Material issuer disclosures and factual macro developments remain source-grounded relevant items.

- [ ] **Step 4: Persist and deliver item checkpoints**

Represent each ready outbox record with `items`, `item_index`, `text_index`, `media_index`, and `board_phase`. Deliver each item text to its selected route. If `len(items) == 1`, post source media after that item's text. If `len(items) > 1`, do not post source media. Preserve existing retry semantics so a completed text leg is never repeated.

- [ ] **Step 5: Add macro and multi-item no-duplication regressions**

Use the BRI macro headline `Menkeu Baru dan Revisi HPM Nikel` in a one-item test with an image and assert one macro text plus one media dry-run line. Add two independent derived items with one image and assert two text routes plus zero media lines.

- [ ] **Step 6: Run focused watcher tests and verify GREEN**

Run: `../.venv/bin/python -m pytest -q cron-wa-channel-watch/tests/test_agent_protocol.py cron-wa-channel-watch/tests/test_render.py cron-wa-channel-watch/tests/test_scan.py`

Expected: PASS.

### Task 6: BRI technical review Board handoff after All Swing delivery

**Files:**
- Modify: `cron-wa-channel-watch/bin/scan.py`
- Create: `cron-wa-channel-watch/bin/swing_board.py`
- Modify: `cron-wa-channel-watch/tests/test_scan.py`
- Create: `cron-wa-channel-watch/tests/test_swing_board.py`

**Interfaces:**
- Consumes: one completed BRI technical News Item and its archive-owned media path from Task 5.
- Produces: `submit_chart_context(event, item, all_content, archived_image) -> BoardSubmission` with Board `social` input only.

- [ ] **Step 1: Write failing Board payload and eligibility tests**

```python
def test_single_ticker_technical_review_submits_social_chart_context(tmp_path, monkeypatch):
    submission = swing_board.submit_chart_context(technical_event(), technical_item("TINS"), "All Swing text", archived_image(tmp_path), run=recording_run)
    assert submission.accepted is True
    assert recording_run.payload["kind"] == "social"
    assert recording_run.payload["ticker"] == "TINS"
    assert recording_run.payload["plan"] is None

def test_multiple_tickers_or_missing_image_never_submits_board():
    assert swing_board.is_eligible(technical_event(), technical_item("TINS"), None) is False
```

- [ ] **Step 2: Run Board-handoff tests and verify RED**

Run: `../.venv/bin/python -m pytest -q cron-wa-channel-watch/tests/test_swing_board.py cron-wa-channel-watch/tests/test_scan.py`

Expected: FAIL because `swing_board` does not exist.

- [ ] **Step 3: Implement a typed subprocess adapter**

Build the exact Board `SourceEvent` JSON with `source: "whatsapp"`, `kind: "social"`, validated ticker, source time, public Channel URL, completed All content, source title/status, `plan: null`, archive-owned `media_path`, and empty `media_urls`. Invoke the deployed Board wrapper as an argument list ending in `submit-source-event --stdin`; never use a shell. Parse only the documented acknowledgement fields `accepted`, `board_url`, and `board_pending`.

- [ ] **Step 4: Add scanner ordering and retry checkpoints**

Call the adapter only after the BRI technical text and image checkpoints are complete. Persist `board_phase: pending|accepted` and acknowledgment data in the watcher outbox. Leave Board submission pending on retryable command failure. For multiple tickers, ambiguous ticker, or missing archived image, record Board as `not_eligible` without an adapter call and leave the All Swing delivery intact.

- [ ] **Step 5: Run Board-handoff and scanner tests and verify GREEN**

Run: `../.venv/bin/python -m pytest -q cron-wa-channel-watch/tests/test_swing_board.py cron-wa-channel-watch/tests/test_scan.py cron-dc-swing-board/tests/test_board_cli.py cron-dc-swing-board/tests/test_models.py`

Expected: PASS.

### Task 7: Operating documentation, deployment boundaries, and complete verification

**Files:**
- Modify: `cron-wa-channel-watch/AGENTS.md`
- Modify: `cron-wa-channel-watch/SKILL.md`
- Modify: `docs/adr/0027-profile-isolated-whatsapp-channel-archive.md`
- Modify: `docs/superpowers/specs/2026-09-21-whatsapp-channel-archive-and-forwarding-design.md`
- Modify: `service-bursawatch-control/tests/test_deployment_assets.py`
- Modify: `cron-wa-channel-watch/tests/test_config.py`

**Interfaces:**
- Consumes: all completed runtime interfaces.
- Produces: an operationally complete, non-live handoff with documented helper commands and verification evidence.

- [ ] **Step 1: Write failing documentation and deployment-asset assertions**

```python
def test_archive_wrapper_is_a_deployed_runtime_asset():
    wrapper = ROOT.parent / "cron-wa-channel-watch/bin/bursawatch-wa-channel-archive.sh"
    assert wrapper.exists()
    assert "WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT" in wrapper.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the deployment-asset test and verify RED**

Run: `../.venv/bin/python -m pytest -q service-bursawatch-control/tests/test_deployment_assets.py`

Expected: FAIL until the test's target file and contract are both implemented.

- [ ] **Step 3: Document the exact archive and lifecycle contract**

In `AGENTS.md`, document `observe` versus `forward`, the three Profiles, archive location and 365-day policy, the four archive helper commands, private export path requirement, no-schedule prune policy, BRI cutover plan/apply gate, media and Board eligibility, and the separate review required before any VPS write. In `SKILL.md`, revise the model prompt for ordered News Items, shared-headline macro rendering, exact technical eligibility, and source data distrust. Keep ADR and specification aligned with the shipped interface.

- [ ] **Step 4: Run focused suites and the repository gate**

Run: `../.venv/bin/python -m pytest -q cron-wa-channel-watch/tests service-bursawatch-control/tests cron-dc-swing-board/tests && node --test cron-wa-channel-watch/tests/channel_sink.test.mjs && bash scripts/test-all`

Expected: every suite passes with no live network, WhatsApp, Discord, Board, or control-plane operation.

- [ ] **Step 5: Perform source-only release readiness checks**

Run: `git diff --check && git status --short && rg -n 'WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT|bursawatch-wa-channel-archive|mode.*observe|mode.*forward' cron-wa-channel-watch service-bursawatch-control`

Expected: no whitespace errors; only intended source, tests, documentation, and control-plane parity files changed; helper references are discoverable.

- [ ] **Step 6: Leave the worktree uncommitted for explicit handoff approval**

Do not stage, commit, push, create a pull request, deploy, follow a Channel, apply cutover, or activate the watcher. Report the exact verification evidence and request the user's separately authorized release workflow.

## Plan self-review

- Spec coverage: Tasks 1 through 7 cover all profile lifecycle, archive, helper, media, source-to-Item, BRI routing, Board, cutover, documentation, and test requirements.
- Placeholder scan: no unresolved implementation placeholders or unspecified interfaces remain.
- Type consistency: Task 1 provides `ChannelProfile.mode`; Task 2 provides `archive.ensure`; Task 5 provides `NewsItem`; Task 6 consumes a completed `NewsItem` and archive-owned image path.
- Review focus coverage: each listed failure mode has a concrete owning task and test step.

## Execution handoff

This plan is intentionally source-only. Before any implementation starts, the executor must preserve the existing worktree isolation, use test-driven development for each task, and leave all production actions for a separately approved release phase.

## 2026-10-01 missing-image follow-up

The linked design spec now permits text-only All Swing delivery with
`Source chart unavailable` for an exact BRI `#TechnicalReview` when
immutable archive capture is unavailable. Earlier strict-image steps
describe the original implementation, not this new behavior.

- [ ] Trace the blocked event through bridge staging, immutable archive,
  source adapter, owner state, and existing delivery operations using
  sanitized metadata. Do not assume an anti-bot cause.
- [ ] Allow the adapter to accept an event with a verified archive record
  and an explicit unavailable-media result. Keep missing archive records
  and ambiguous identities blocked. Preserve original publication time,
  cursor order, and stable event key.
- [ ] Deliver ordinary news text with an unavailable-image note. For an
  exact technical review, deliver All Swing text with
  `Source chart unavailable`, but no image or chart-dependent Board event.
  Never repeat already delivered text.
- [ ] Cover both routes, natural late queue draining, retryable Discord
  failures, and no-Board behavior in isolated tests. Run focused suites and
  `bash scripts/test-all`.
- [ ] Review the exact live diff before release; verify source, owner,
  receipt, and Discord room evidence on a natural eligible event.
