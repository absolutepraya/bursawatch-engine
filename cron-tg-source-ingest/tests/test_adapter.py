from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib-bursawatch-control" / "bin"))
sys.path.insert(0, str(ROOT / "cron-tg-source-ingest" / "bin"))
from adapter import IntakeBlocked, endpoints, ingest_all as adapter_ingest_all, ingest_endpoint, plan_legacy_cursor_seed, envelope as telegram_envelope
from runner import AGENT_OWNERS, HEARTBEAT_CHANNEL_ID, PIPELINE_OWNERS, dispatch_agent, format_fatal, format_heartbeat, post_heartbeat, run_once
from runner import verify_synthetic


NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)
ENDPOINT = {"platform": "telegram", "endpoint_id": "telegram:phintraprofits", "publisher_id": "phintraco", "address": "phintraprofits", "provider_id": "1444713822", "catalog_revision": 7, "capabilities": {"trading_plans"}}
NEWS_ENDPOINT = {"platform": "telegram", "endpoint_id": "telegram:phintasprofits", "publisher_id": "phintraco", "address": "phintasprofits", "provider_id": None, "catalog_revision": 7, "capabilities": {"company_news"}}


def test_release_synthetic_verification_uses_only_in_memory_fixture(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert verify_synthetic() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["outcome"] == "synthetic-ok"
    assert result["network"] is False
    assert result["secrets"] is False
    assert result["writes"] is False
    assert result["events"] == 1
    assert len(result["content_hash"]) == 64
    assert list(tmp_path.iterdir()) == []


def test_runtime_wrapper_imports_source_media_read_token_path():
    wrapper = ROOT / "cron-tg-source-ingest" / "bin" / "bursawatch-tg-source-ingest.sh"
    assert "BURSAWATCH_SOURCE_MEDIA_READ_TOKEN_FILE=*" in wrapper.read_text()


class FakeInbox:
    def __init__(self):
        self.accepted = []
        self.fail = False

    def accept(self, envelope):
        if self.fail:
            raise OSError("inbox unavailable")
        self.accepted.append(envelope)
        identity = [envelope[key] for key in ("platform", "endpoint_id", "provider_event_id")]
        key = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
        return {"event_key": key, "version": 1, "duplicate": False, "work_keys": []}


class FakeTelegram:
    def __init__(self, messages, *, address="phintraprofits", entity_id=1444713822):
        self.messages = messages
        self.address = address
        self.entity_id = entity_id

    async def get_entity(self, address):
        assert address == self.address
        return SimpleNamespace(id=self.entity_id, username=self.address)

    async def get_messages(self, entity, limit):
        assert limit == 1
        return [self.messages[-1]] if self.messages else []

    async def iter_messages(self, entity, *, min_id, reverse, limit):
        assert reverse and limit <= 20
        for message in self.messages:
            if message.id > min_id:
                yield message

    async def download_media(self, message, *, file, progress_callback=None):
        data = b"\xff\xd8\xfftelegram-chart"
        Path(file).write_bytes(data)
        if progress_callback:
            progress_callback(len(data), len(data))
        return file


class FakeMediaStore:
    def __init__(self):
        self.uploads = []

    def upload(self, identity, data, *, kind, content_type, filename):
        ref = {"ref": "00000000-0000-4000-8000-000000000011", "sha256": hashlib.sha256(data).hexdigest(), "kind": kind, "content_type": content_type, "size_bytes": len(data), "filename": filename, "durable": True}
        self.uploads.append((identity, data, ref))
        return ref


def test_phintraco_legacy_seed_is_previewed_then_accepts_only_after_cursor(tmp_path, monkeypatch):
    legacy_path = tmp_path / "synthetic-snapshot" / "phin.json"
    legacy_path.parent.mkdir()
    legacy_path.write_text(json.dumps({"observed_message_id": 100, "outbox": {}}))
    state_root = tmp_path / "synthetic-snapshot" / "new"
    preview = plan_legacy_cursor_seed(legacy_path, state_root, ENDPOINT, 7)
    assert preview["status"] == "preview"
    assert not (state_root / "telegram-phintraprofits" / "cursor.json").exists()
    monkeypatch.setenv("BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY", "1")
    applied = plan_legacy_cursor_seed(legacy_path, state_root, ENDPOINT, 7, apply=True, expected_plan=preview)
    assert applied["status"] == "applied"
    client = FakeTelegram([message(99), message(100), message(101)])
    inbox = FakeInbox()
    result = asyncio.run(ingest_endpoint(client, ENDPOINT, state_root, inbox, NOW))
    assert result["accepted"] == 1
    assert [row["provider_event_id"] for row in inbox.accepted] == ["101"]
    cursor = json.loads((state_root / "telegram-phintraprofits" / "cursor.json").read_text())
    assert cursor["legacy_seed"]["legacy_state_sha256"] == applied["legacy_state_sha256"]


def test_telegram_seed_validates_endpoint_tuple_and_pins_catalog_revision(tmp_path, monkeypatch):
    legacy_path = tmp_path / "synthetic-snapshot" / "phin.json"
    legacy_path.parent.mkdir()
    legacy_path.write_text(json.dumps({"observed_message_id": 100, "outbox": {}}))
    state_root = tmp_path / "synthetic-snapshot" / "new"
    with pytest.raises(Exception, match="reviewed binding"):
        plan_legacy_cursor_seed(legacy_path, state_root, {**ENDPOINT, "publisher_id": "wrong"}, 7)
    preview = plan_legacy_cursor_seed(legacy_path, state_root, ENDPOINT, 7)
    monkeypatch.setenv("BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY", "1")
    plan_legacy_cursor_seed(legacy_path, state_root, ENDPOINT, 7, apply=True, expected_plan=preview)
    changed_snapshot = {"revision": 8, "subscriptions": [{"platform": "telegram", "endpoint_id": "telegram:phintraprofits", "publisher_id": "phintraco", "address": "phintraprofits", "provider_id": "1444713822", "capability_id": "trading_plans", "verification_status": "verified", "enabled": True}]}
    with pytest.raises(Exception, match="catalog revision changed"):
        asyncio.run(adapter_ingest_all(FakeTelegram([]), changed_snapshot, state_root, FakeInbox(), NOW))


def test_phintraco_news_cursor_seed_previews_market_news_provider_boundary(tmp_path):
    legacy_path = tmp_path / "synthetic-snapshot" / "market-news.json"
    legacy_path.parent.mkdir()
    legacy_path.write_text(json.dumps({
        "version": 1,
        "providers": {"phintraco": {"observed_message_id": 35377}},
        "candidates": {},
        "stats": {"stock_status_events": {}},
    }))
    state_root = tmp_path / "new"

    preview = plan_legacy_cursor_seed(legacy_path, state_root, NEWS_ENDPOINT, 7)

    assert preview["status"] == "preview"
    assert preview["proposed_anchor"] == "35377"
    assert preview["legacy_state_sha256"] == hashlib.sha256(legacy_path.read_bytes()).hexdigest()
    assert not (state_root / "telegram-phintasprofits" / "cursor.json").exists()


@pytest.mark.parametrize(
    ("candidate_phase", "status_phase", "message"),
    [
        ("pending_analysis", None, "pending Phintraco Market News candidates"),
        (None, "pending_delivery", "pending Phintraco stock-status deliveries"),
    ],
)
def test_phintraco_news_seed_blocks_unreconciled_domain_work(tmp_path, candidate_phase, status_phase, message):
    legacy_path = tmp_path / "synthetic-snapshot" / "market-news.json"
    legacy_path.parent.mkdir()
    candidates = {}
    if candidate_phase:
        candidates["phintraco:35378:ABCD"] = {
            "candidate": {"provider": "phintraco"},
            "phase": candidate_phase,
        }
    status_events = {"phintraco-stock-status:35379": {"phase": status_phase}} if status_phase else {}
    legacy_path.write_text(json.dumps({
        "version": 1,
        "providers": {"phintraco": {"observed_message_id": 35377}},
        "candidates": candidates,
        "stats": {"stock_status_events": status_events},
    }))

    with pytest.raises(Exception, match=message):
        plan_legacy_cursor_seed(legacy_path, tmp_path / "new", NEWS_ENDPOINT, 7)


def test_phintraco_news_seed_does_not_block_pending_tuntun_candidate(tmp_path):
    legacy_path = tmp_path / "synthetic-snapshot" / "market-news.json"
    legacy_path.parent.mkdir()
    legacy_path.write_text(json.dumps({
        "version": 1,
        "providers": {"phintraco": {"observed_message_id": 35377}},
        "candidates": {"tuntun:991:ABCD": {"candidate": {"provider": "tuntun"}, "phase": "pending_analysis"}},
        "stats": {"stock_status_events": {}},
    }))

    preview = plan_legacy_cursor_seed(legacy_path, tmp_path / "new", NEWS_ENDPOINT, 7)

    assert preview["status"] == "preview"


def test_telegram_ack_recovery_preserves_staged_published_at(tmp_path):
    from source_event_client import SourceEventHandoff

    state_root = tmp_path / "state"
    endpoint_root = state_root / "telegram-phintraprofits"
    endpoint_root.mkdir(parents=True)
    cursor_path = endpoint_root / "cursor.json"
    cursor_path.write_text(json.dumps({"cursor": 100}))
    event = telegram_envelope(ENDPOINT, message(101), NOW, previous_message_id=100)
    inbox = FakeInbox()
    handoff = SourceEventHandoff(endpoint_root / "handoff", inbox)
    handoff.stage(event)
    (endpoint_root / "pending-position.json").write_text(json.dumps({"envelope": event, "position": None}))
    result = asyncio.run(ingest_endpoint(FakeTelegram([message(101)]), ENDPOINT, state_root, inbox, NOW))
    assert result["cursor"] == 101
    assert json.loads(cursor_path.read_text())["boundary_published_at"] == event["published_at"]


def test_kelas_legacy_seed_preserves_bootstrap_and_predecessor(tmp_path, monkeypatch):
    async def check():
        legacy_path = tmp_path / "synthetic-snapshot" / "kelas.json"
        legacy_path.parent.mkdir()
        legacy_path.write_text(json.dumps({"cursor": 100, "pending": [], "outbox": []}))
        state_root = tmp_path / "synthetic-snapshot" / "new"
        endpoint = {"platform": "telegram", "endpoint_id": "telegram:kelasinvestasiid", "publisher_id": "kelas-investasi", "address": "kelasinvestasiid", "provider_id": "2142109618", "catalog_revision": 8, "capabilities": {"swing_support"}}
        preview = plan_legacy_cursor_seed(legacy_path, state_root, endpoint, 8)
        monkeypatch.setenv("BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY", "1")
        result = plan_legacy_cursor_seed(legacy_path, state_root, endpoint, 8, apply=True, expected_plan=preview)
        telegram = FakeTelegram([message(99), message(100), message(101)], address="kelasinvestasiid", entity_id=2142109618)
        inbox = FakeInbox()
        outcome = await ingest_endpoint(telegram, endpoint, state_root, inbox, NOW)
        assert outcome["accepted"] == 1
        assert inbox.accepted[0]["provider_event_id"] == "101"
        assert inbox.accepted[0]["payload"]["previous_provider_event_id"] == 100
        assert inbox.accepted[0]["payload"]["bootstrap_provider_event_id"] == 100
        assert result["legacy_state_sha256"] == json.loads((state_root / "telegram-kelasinvestasiid" / "cursor.json").read_text())["legacy_seed"]["legacy_state_sha256"]

    asyncio.run(check())


def message(mid, text="BUY", *, media=None):
    return SimpleNamespace(id=mid, raw_text=text, message=text, date=NOW, media=media, photo=media, reply_to_msg_id=None)


def test_future_only_cursor_and_ack_order(tmp_path):
    asyncio.run(_future_only_cursor_and_ack_order(tmp_path))


def test_kelas_event_carries_durable_predecessor_after_inbox_acceptance(tmp_path):
    async def check():
        endpoint = {"platform": "telegram", "endpoint_id": "telegram:kelasinvestasiid", "publisher_id": "kelas-investasi", "address": "kelasinvestasiid", "provider_id": "2142109618", "catalog_revision": 8, "capabilities": {"swing_support"}}
        telegram = FakeTelegram([message(100)], address="kelasinvestasiid", entity_id=2142109618)
        inbox = FakeInbox()
        await ingest_endpoint(telegram, endpoint, tmp_path, inbox, NOW)
        telegram.messages.extend((message(101, "Good to watch - CTRA #GTW"), message(103, "Buy area: 605-630")))
        await ingest_endpoint(telegram, endpoint, tmp_path, inbox, NOW)
        assert [event["payload"]["previous_provider_event_id"] for event in inbox.accepted] == [100, 101]
        assert [event["payload"]["bootstrap_provider_event_id"] for event in inbox.accepted] == [100, 100]
        assert json.loads((tmp_path / "telegram-kelasinvestasiid" / "cursor.json").read_text()) == {"cursor": 103, "bootstrap_cursor": 100}

    asyncio.run(check())


async def _future_only_cursor_and_ack_order(tmp_path):
    inbox = FakeInbox()
    client = FakeTelegram([message(10)])
    first = await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW)
    assert first == {"endpoint_id": ENDPOINT["endpoint_id"], "bootstrapped": True, "cursor": 10, "accepted": 0}
    client.messages.append(message(11))
    inbox.fail = True
    with pytest.raises(OSError):
        await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW)
    cursor = tmp_path / "telegram-phintraprofits" / "cursor.json"
    assert json.loads(cursor.read_text())["cursor"] == 10
    inbox.fail = False
    result = await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW)
    assert result["cursor"] == 11
    assert [item["provider_event_id"] for item in inbox.accepted] == ["11"]
    assert inbox.accepted[0]["published_at"] == NOW.isoformat()


def test_media_keeps_cursor_at_previous_ack(tmp_path):
    asyncio.run(_media_keeps_cursor_at_previous_ack(tmp_path))


async def _media_keeps_cursor_at_previous_ack(tmp_path):
    inbox = FakeInbox()
    client = FakeTelegram([message(10)])
    await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW)
    client.messages.extend((message(11), message(12, media=object()), message(13)))
    with pytest.raises(IntakeBlocked, match="Source Media Owner"):
        await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW)
    cursor = tmp_path / "telegram-phintraprofits" / "cursor.json"
    assert json.loads(cursor.read_text())["cursor"] == 11
    blocked = json.loads((cursor.parent / "blocked-media.json").read_text())
    assert blocked["message_id"] == 12
    assert [item["provider_event_id"] for item in inbox.accepted] == ["11"]


def test_durable_media_upload_precedes_source_acceptance_and_retry_reuses_handoff(tmp_path):
    asyncio.run(_durable_media_upload_precedes_source_acceptance_and_retry_reuses_handoff(tmp_path))


async def _durable_media_upload_precedes_source_acceptance_and_retry_reuses_handoff(tmp_path):
    inbox = FakeInbox()
    client = FakeTelegram([message(10)])
    media_store = FakeMediaStore()
    await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW)
    media_message = message(11, "chart plan", media=object())
    client.messages.append(media_message)
    inbox.fail = True
    with pytest.raises(OSError, match="inbox unavailable"):
        await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW, media_store=media_store)
    cursor = tmp_path / "telegram-phintraprofits" / "cursor.json"
    assert json.loads(cursor.read_text())["cursor"] == 10
    assert len(media_store.uploads) == 1
    inbox.fail = False
    result = await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW, media_store=media_store)
    assert result["cursor"] == 11
    assert len(media_store.uploads) == 1
    accepted = inbox.accepted[0]
    assert accepted["media_required"] is True
    assert accepted["media_refs"] == [media_store.uploads[0][2]]
    assert accepted["payload"]["media_ref_ids"] == [media_store.uploads[0][2]["ref"]]
    assert not (cursor.parent / "blocked-media.json").exists()


def test_oversized_telegram_media_stops_during_download_before_upload(tmp_path):
    asyncio.run(_oversized_telegram_media_stops_during_download_before_upload(tmp_path))


async def _oversized_telegram_media_stops_during_download_before_upload(tmp_path):
    inbox = FakeInbox()
    client = FakeTelegram([message(10)])
    await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW)

    class OversizedTelegram(FakeTelegram):
        async def download_media(self, message, *, file, progress_callback=None):
            Path(file).write_bytes(b"partial")
            assert progress_callback is not None
            progress_callback(8 * 1024 * 1024 + 1, 8 * 1024 * 1024 + 1)
            raise AssertionError("oversized transfer was not stopped")

    oversized = OversizedTelegram([message(11, "chart", media=object())])
    media_store = FakeMediaStore()
    with pytest.raises(IntakeBlocked, match="exceeds the 8 MiB"):
        await ingest_endpoint(oversized, ENDPOINT, tmp_path, inbox, NOW, media_store=media_store)

    cursor = tmp_path / "telegram-phintraprofits" / "cursor.json"
    assert json.loads(cursor.read_text())["cursor"] == 10
    assert media_store.uploads == []
    assert json.loads((cursor.parent / "blocked-media.json").read_text())["message_id"] == 11


def test_effective_catalog_rejects_unknown_enabled_endpoint():
    row = {"platform": "telegram", "enabled": True, "endpoint_id": "telegram:phintraprofits", "capability_id": "trading_plans", "verification_status": "verified", "provider_id": "1444713822", "publisher_id": "phintraco", "address": "phintraprofits"}
    assert endpoints({"revision": 5, "subscriptions": [row]})["telegram:phintraprofits"]["capabilities"] == {"trading_plans"}
    with pytest.raises(IntakeBlocked, match="not onboarded"):
        endpoints({"revision": 5, "subscriptions": [{**row, "endpoint_id": "telegram:unknown"}]})
    with pytest.raises(IntakeBlocked, match="identity is not verified"):
        endpoints({"revision": 5, "subscriptions": [{**row, "publisher_id": "kelas-investasi"}]})
    with pytest.raises(IntakeBlocked, match="identity is not verified"):
        endpoints({"revision": 5, "subscriptions": [{**row, "endpoint_id": "telegram:tuntunsekuritas", "address": "tuntunsekuritas", "capability_id": "company_news", "provider_id": None, "publisher_id": "phintraco"}]})
    tuntun = {**row, "endpoint_id": "telegram:tuntunsekuritas", "address": "tuntunsekuritas", "capability_id": "company_news", "provider_id": None, "publisher_id": "tuntun"}
    assert endpoints({"revision": 5, "subscriptions": [tuntun]}) == {}
    with pytest.raises(IntakeBlocked, match="identity is not verified"):
        endpoints({"revision": 5, "subscriptions": [{**tuntun, "verification_status": "pending"}]})
    with pytest.raises(IntakeBlocked, match="not onboarded"):
        endpoints({"revision": 5, "subscriptions": [{**tuntun, "capability_id": "trading_plans"}]})


@pytest.mark.parametrize("failing", ["news", "board"])
def test_board_and_synthetic_news_settle_independently(tmp_path, monkeypatch, failing):
    # Load the real Phintraco owner into this isolated package test. Its domain
    # handoff is no-post and uses an isolated ledger, while the News work is a
    # synthetic independent item. Production does not register a News handler.
    for package in ("cron-tg-phintraco-swing", "lib-swing-format", "lib-bursawatch-discord-delivery", "lib-telegram-resilience"):
        sys.path.insert(0, str(ROOT / package / "bin"))
    import scan as swing_scan
    spec = importlib.util.spec_from_file_location("phintraco_pipeline_owner_for_test", ROOT / "cron-tg-phintraco-swing" / "bin" / "pipeline_owner.py")
    assert spec and spec.loader
    swing_owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(swing_owner)
    monkeypatch.setenv("IDX_SWING_WATCH_PHINTRACO_DAILY_STATE_PATH", str(tmp_path / "swing.json"))
    configured = swing_scan.config.WatchConfig(1444713822, "phintraprofits", "1525102458253217803", "1505162000420835388")
    monkeypatch.setattr(swing_scan.config, "load_watch_config_for_run", lambda: swing_scan.config.LoadedWatchConfig(configured, 5))
    monkeypatch.setattr(swing_scan, "post_discord_text", lambda *args: "dry-text-11")
    board_events = []
    monkeypatch.setattr(swing_scan, "submit_board_event", lambda payload, chart, dry_run: board_events.append((payload.copy(), chart, dry_run)) or failing != "board")

    class WorkInbox(FakeInbox):
        def __init__(self):
            super().__init__()
            self.work = []
            self.settlements = []

        def accept(self, envelope):
            receipt = super().accept(envelope)
            event_key = receipt["event_key"]
            for pipeline, capability in (("swing_plan", "trading_plans"), ("company_news", "company_news")):
                effect = hashlib.sha256(f"{event_key}:1:{capability}".encode()).hexdigest()
                self.work.append({"work_key": effect, "effect_key": effect, "event_key": event_key, "version": 1, "capability_id": capability, "lease_token": pipeline, "pipeline_id": pipeline, "envelope": envelope})
            return receipt

        def claim(self, pipeline_ids, limit):
            selected = [item for item in self.work if item["pipeline_id"] in pipeline_ids][:limit]
            self.work = [item for item in self.work if item not in selected]
            return selected

        def begin(self, work_key, lease_token):
            return True

        def settle(self, work_key, lease_token, success, error_code=None):
            self.settlements.append((lease_token, success))
            return {"work_key": work_key, "status": "done" if success else "pending"}

    inbox = WorkInbox()
    telegram = FakeTelegram([message(10)])
    snapshot = {"revision": 5, "subscriptions": [{"platform": "telegram", "enabled": True, "endpoint_id": "telegram:phintraprofits", "capability_id": "trading_plans", "verification_status": "verified", "provider_id": "1444713822", "publisher_id": "phintraco", "address": "phintraprofits"}]}
    assert PIPELINE_OWNERS["company_news"] == "cron-tg-market-news"
    asyncio.run(run_once(telegram, snapshot, tmp_path, inbox, NOW, handlers={"swing_plan": lambda item: None}))
    text = (ROOT / "cron-tg-phintraco-swing" / "tests" / "fixtures" / "trading_buy.txt").read_text()
    telegram.messages.append(message(11, text))

    def failing_news(item):
        if failing == "news":
            raise RuntimeError("synthetic classifier failure")

    result = asyncio.run(run_once(telegram, snapshot, tmp_path, inbox, NOW, handlers={"company_news": failing_news, "swing_plan": lambda item: swing_owner.submit(item, no_post=True)}))
    assert result["source"][0]["accepted"] == 1
    assert {item["status"] for item in result["work"]} == {"done", "retry"}
    assert inbox.settlements == [("swing_plan", failing != "board"), ("company_news", failing != "news")]
    assert len(board_events) == 1
    assert board_events[0][0]["event_key"] == "phintraco:1444713822:11"
    assert board_events[0][0]["source"] == "phintraco"
    assert board_events[0][0]["kind"] == "buy"
    assert board_events[0][0]["plan"] == {"entry": "208 to 212", "stop_loss": "<200", "targets": ["230"]}
    assert board_events[0][0]["source_status"] == "New setup"
    assert board_events[0][2] is True
    assert len(inbox.accepted) == 1


def test_agent_dispatch_claims_one_oldest_ready_owner(tmp_path):
    calls = []
    statuses = {
        ("cron-tg-market-news", "agent-status"): {
            "ready": True,
            "event_key": "a" * 64,
            "published_at": "2026-09-24T06:00:00+00:00",
        },
        ("cron-tg-kelas-investasi-gtw", "--agent-status"): {
            "ready": True,
            "pipeline_id": "swing_support",
            "event_key": "event-kelas",
            "published_at": "2026-09-24T07:00:00+00:00",
        },
    }

    def owner_command(package, *arguments):
        calls.append((package, arguments))
        if arguments[0] in {"agent-status", "--agent-status"}:
            return statuses[(package, arguments[0])]
        assert (package, arguments) == ("cron-tg-market-news", ("claim-agent",))
        return {"wakeAgent": True, "items": [{"candidate_key": "phintraco:42", "instruction": "trusted owner prompt"}]}

    result = dispatch_agent(tmp_path, owner_command=owner_command)

    assert result == {
        "wakeAgent": True,
        "agent_target": "market_news",
        "items": [{"candidate_key": "phintraco:42", "instruction": "trusted owner prompt"}],
    }
    assert calls[-1] == ("cron-tg-market-news", ("claim-agent",))
    assert json.loads((tmp_path / "agent-dispatch.json").read_text()) == {"version": 1, "last_owner": "market_news"}


def test_agent_dispatch_rotates_equal_time_ties(tmp_path):
    (tmp_path / "agent-dispatch.json").write_text(json.dumps({"version": 1, "last_owner": "market_news"}))
    calls = []
    timestamp = "2026-09-24T07:00:00+00:00"

    def owner_command(package, *arguments):
        calls.append((package, arguments))
        if arguments[0] in {"agent-status", "--agent-status"}:
            return {
                "ready": True,
                "pipeline_id": "swing_support" if package.startswith("cron-tg-kelas") else None,
                "event_key": f"event:{package}",
                "published_at": timestamp,
            }
        assert (package, arguments) == ("cron-tg-kelas-investasi-gtw", ("--claim-agent",))
        return {"wakeAgent": True, "item": {"event_key": "event:kelas", "instruction": "trusted owner prompt"}}

    result = dispatch_agent(tmp_path, owner_command=owner_command)

    assert result["agent_target"] == "kelas_investasi"
    assert "item" in result and "items" not in result
    assert calls[-1] == ("cron-tg-kelas-investasi-gtw", ("--claim-agent",))
    assert json.loads((tmp_path / "agent-dispatch.json").read_text())["last_owner"] == "kelas_investasi"


def test_agent_dispatch_keeps_other_owner_available_when_one_status_fails(tmp_path):
    def owner_command(package, *arguments):
        if package == "cron-tg-market-news":
            raise RuntimeError("private owner failure")
        if arguments == ("--agent-status",):
            return {"ready": True, "pipeline_id": "swing_support", "event_key": "kelas-1", "published_at": NOW.isoformat()}
        return {"wakeAgent": True, "item": {"event_key": "kelas-1", "instruction": "trusted owner prompt"}}

    result = dispatch_agent(tmp_path, owner_command=owner_command)

    assert result["wakeAgent"] is True
    assert result["agent_target"] == "kelas_investasi"
    assert result["agent_dispatch_warning"] is True


def test_agent_dispatch_does_not_claim_when_no_owner_is_ready(tmp_path):
    calls = []

    def owner_command(package, *arguments):
        calls.append((package, arguments))
        return {"ready": False}

    assert dispatch_agent(tmp_path, owner_command=owner_command) == {"wakeAgent": False}
    assert len(calls) == len(AGENT_OWNERS)


def test_heartbeat_is_compact_sanitized_and_uses_shared_delivery_owner():
    class FakeDelivery:
        def __init__(self):
            self.operation = None
            self.waited = []

        def status(self, key):
            return None

        def submit(self, operation):
            self.operation = operation
            return SimpleNamespace(key=operation.key, digest=operation.digest, status="pending")

        def wait(self, key, timeout):
            self.waited.append((key, timeout))
            return SimpleNamespace(key=key, digest=self.operation.digest, status="delivered")

    now = datetime(2026, 9, 24, 0, 15, tzinfo=timezone.utc)
    result = {
        "source": [{"endpoint_id": "telegram:phintraprofits", "accepted": 2}],
        "work": [{"status": "done"}, {"status": "retry"}],
        "wakeAgent": True,
        "agent_target": "kelas_investasi",
    }
    client = FakeDelivery()
    content = format_heartbeat(now, result)

    post_heartbeat(content, now, delivery_client=client)

    assert content == "🫀 bursawatch-tg-source-ingest · 07:15 WIB · endpoints=1 accepted=2 work=2 pending=1 agent=kelas_investasi ⚠️"
    assert client.operation.kind == "channel_message_create"
    assert client.operation.target == {"channel_id": HEARTBEAT_CHANNEL_ID}
    assert client.operation.payload["content"] == content
    assert client.operation.payload["allowed_mentions"] == {"parse": []}
    assert client.waited == [(client.operation.key, 0)]
    assert format_fatal(now) == "❌ bursawatch-tg-source-ingest · 07:15 WIB · failed: source processing failed"


def test_heartbeat_warns_when_endpoint_is_blocked():
    now = datetime(2026, 9, 24, 0, 15, tzinfo=timezone.utc)
    result = {"source": [{"endpoint_id": "telegram:phintraprofits", "status": "blocked"}], "work": []}

    assert format_heartbeat(now, result) == (
        "🫀 bursawatch-tg-source-ingest · 07:15 WIB · "
        "endpoints=1 accepted=0 work=0 pending=0 agent=none ⚠️"
    )


def test_heartbeat_counts_dead_letter_as_pending_attention():
    now = datetime(2026, 9, 24, 0, 15, tzinfo=timezone.utc)
    result = {"source": [], "work": [{"status": "dead_letter"}]}

    assert format_heartbeat(now, result) == (
        "🫀 bursawatch-tg-source-ingest · 07:15 WIB · "
        "endpoints=0 accepted=0 work=1 pending=1 agent=none ⚠️"
    )


def test_runtime_skill_routes_only_to_the_two_fixed_analysis_owners():
    package = ROOT / "cron-tg-source-ingest"
    skill = (package / "SKILL.md").read_text()

    assert (package / "AGENTS.md").is_file()
    assert not (package / "CRON.md").exists()
    assert "agent_target: market_news" in skill and "agent_target: kelas_investasi" in skill
    assert 'bursawatch-tg-market-news.sh" submit-classification' in skill
    assert 'bursawatch-tg-kelas-investasi-gtw.sh" --submit-analysis' in skill
    assert "post to Discord directly" in skill
