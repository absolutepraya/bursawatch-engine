from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import delivery
import config
import scan
from domain import CompanyCandidate, Destination, EventClass, Provider, SourceKind
from selection import SelectionCandidate
from state import (
    claim_oldest_pending_analysis,
    empty_state,
    enqueue_candidate,
    load_state,
    save_state,
)
from stock_status import format_stock_status, parse_stock_information


class FakeClient:
    def __init__(self) -> None:
        self.messages = {
            "phintraco": [
                SimpleNamespace(
                    id=101,
                    message="Notes: DEWA\nMaterial contract disclosed.",
                    date=datetime.fromisoformat("2026-07-14T03:00:00+00:00"),
                    photo=None,
                )
            ],
            "tuntun": [
                SimpleNamespace(
                    id=201,
                    message="CBRE: operational update.",
                    date=datetime.fromisoformat("2026-07-14T03:01:00+00:00"),
                    photo=None,
                    reply_to=SimpleNamespace(reply_to_top_id=3743),
                )
            ],
        }
        self.phintraco_error: Exception | None = None

    async def iter_messages(self, entity, min_id=0, reverse=False, limit=None):
        if entity == "phintraco" and self.phintraco_error is not None:
            raise self.phintraco_error
        messages = self.messages[entity]
        if limit is not None:
            messages = messages[:limit]
        for message in messages:
            if message.id > min_id:
                yield message


class FakeClients:
    def __init__(self) -> None:
        self.client = FakeClient()
        self.phintraco_entity = "phintraco"
        self.tuntun_entity = "tuntun"

    @property
    def phintraco_error(self):
        return self.client.phintraco_error

    @phintraco_error.setter
    def phintraco_error(self, value):
        self.client.phintraco_error = value


class FakeDeliveryOwner:
    def __init__(self, *, fail_first_news=False):
        self.operations = {}
        self.submissions = []
        self.fail_first_news = fail_first_news

    def status(self, operation_key):
        return self.operations.get(operation_key)

    def submit(self, operation):
        self.submissions.append(operation)
        if self.fail_first_news and "heartbeat-" not in operation.key:
            self.fail_first_news = False
            raise delivery.DeliveryClientError("timeout")
        receipt = delivery.OperationReceipt(
            id=f"owner-{len(self.submissions)}",
            key=operation.key,
            digest=operation.digest,
            status="delivered",
            receipt={
                "channel_id": operation.target["channel_id"],
                "message_id": str(6000 + len(self.submissions)),
            },
        )
        self.operations[operation.key] = receipt
        return receipt

    def wait(self, operation_key, timeout_seconds):
        assert timeout_seconds == delivery.DELIVERY_RECEIPT_WAIT_SECONDS
        return self.operations[operation_key]


def _install_delivery_owner(monkeypatch, *, fail_first_news=False):
    owner = FakeDeliveryOwner(fail_first_news=fail_first_news)
    monkeypatch.setattr(scan, "_dry_run", lambda: False)
    monkeypatch.setattr(scan, "delivery_client_from_environment", lambda: owner)
    return owner


def _bootstrapped_state(tmp_state):
    state = empty_state()
    for lane in state["providers"].values():
        lane["bootstrap_complete"] = True
    save_state(state, tmp_state)


class BackfillClient:
    def __init__(self, message):
        self.message = message
        self.calls = []

    async def get_messages(self, entity, ids):
        self.calls.append((entity, ids))
        return self.message


def _backfill_clients(message):
    client = BackfillClient(message)
    return SimpleNamespace(
        client=client,
        phintraco_entity="phintraco",
        tuntun_entity="tuntun",
    )


def test_no_post_resilience_uses_files_beside_isolated_watcher_state(tmp_path, monkeypatch):
    watcher_state_path = tmp_path / "state.json"
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(watcher_state_path))

    control = scan.resilience()

    assert control.state_path == tmp_path / "state.json.telegram-resilience.json"
    assert control.log_path == tmp_path / "state.json.telegram-resilience.jsonl"


def test_no_post_resilience_refuses_production_watcher_state(tmp_path, monkeypatch):
    monkeypatch.setattr(scan.Path, "home", lambda: tmp_path)
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    monkeypatch.setenv(
        "IDX_MARKET_NEWS_STATE_PATH",
        str(tmp_path / ".hermes" / "state" / "idx-market-news.json"),
    )

    with pytest.raises(RuntimeError, match="isolated IDX_MARKET_NEWS_STATE_PATH"):
        scan.resilience()


def test_message_topic_id_reads_the_forum_root_reply_message_id():
    message = SimpleNamespace(
        reply_to=SimpleNamespace(reply_to_msg_id=3743, reply_to_top_id=None, forum_topic=True)
    )

    assert scan._message_topic_id(message) == 3743


def test_pending_count_ignores_terminal_abandoned_candidates():
    state = empty_state()
    state["candidates"] = {
        "abandoned": {"phase": "abandoned"},
        "pending-analysis": {"phase": "pending_analysis"},
        "pending-delivery": {"phase": "pending_delivery"},
    }

    assert scan._pending_count(state) == 2


def test_delivery_route_uses_the_active_config_snapshot(candidate):
    item = SelectionCandidate(
        candidate=candidate,
        event_class=EventClass.CORPORATE_ACTION,
        ranking_band=1,
        material_facts=("DEWA mengungkapkan kontrak material.",),
        dedupe_facts=("DEWA kontrak material",),
        route=scan.Destination.ID_STOCKS_NEWS,
    )
    watch_config = config.load_watch_config_data(
        {
            "version": 1,
            "providers": {
                "phintraco": {"telegram_username": "phintracocp"},
                "tuntun": {"telegram_username": "tuntuncontrol"},
            },
            "destinations": {
                "id_stocks_news_discord_channel_id": "1525102508714889258",
                "macro_news_discord_channel_id": "1531655369884045383",
                "industry_news_discord_channel_id": "1549418098807930881",
                "heartbeat_discord_channel_id": "1505162000420835389",
            },
            "additional_prompt_instruction": "",
        }
    )

    with config.activate_watch_config(watch_config):
        assert scan._delivery_channel(item) == "1525102508714889258"


def test_phintraco_macro_route_uses_macro_channel():
    candidate = CompanyCandidate(
        provider=Provider.PHINTRACO,
        source_message_id=35378,
        ticker=None,
        source_kind=SourceKind.PHINTRACO_NOTE,
        published_at=datetime(2026, 9, 23, 2, 40, tzinfo=timezone.utc),
        source_text="Landbank Implications from Agrarian Reform.",
        direct_image=False,
    )
    item = SelectionCandidate(
        candidate=candidate,
        event_class=EventClass.LISTING_LEGAL_REGULATORY_OR_CREDIT,
        ranking_band=1,
        material_facts=("The policy affects several developers.",),
        dedupe_facts=("agrarian reform policy",),
        summary="Perubahan kebijakan dapat memengaruhi sejumlah pengembang.",
        route=Destination.MACRO_NEWS,
    )

    assert scan._delivery_channel(item) == scan.MACRO_CHANNEL_ID


def test_quick_note_backfill_queues_only_the_selected_message_without_advancing_cursor(
    tmp_state, monkeypatch
):
    _bootstrapped_state(tmp_state)
    state = load_state(tmp_state)
    scan.advance_provider_cursor(state, Provider.PHINTRACO, 35388)
    save_state(state, tmp_state)
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    message = SimpleNamespace(
        id=35376,
        message=(
            "PHINTAS Quick Notes | 23 September 2026\n"
            "POWR Berpotensi Catat Pertumbuhan Kinerja pada 2026\n"
            "Phintraco estimates FY26 revenue growth."
        ),
        date=datetime.fromisoformat("2026-09-23T03:00:00+00:00"),
        photo=None,
    )
    clients = _backfill_clients(message)
    now = datetime.fromisoformat("2026-09-23T12:00:00+07:00")
    cursor_before = scan.provider_cursor(load_state(tmp_state), Provider.PHINTRACO)

    result = asyncio.run(scan.backfill_phintraco_quick_note(35376, now, clients))

    state = load_state(tmp_state)
    assert result == {
        "candidate_key": "phintraco:35376:POWR",
        "message_id": 35376,
        "queued": True,
        "cursor_advanced": False,
    }
    assert clients.client.calls == [("phintraco", 35376)]
    assert scan.provider_cursor(state, Provider.PHINTRACO) == cursor_before
    assert state["candidates"]["phintraco:35376:POWR"]["phase"] == "pending_analysis"

    repeated = asyncio.run(scan.backfill_phintraco_quick_note(35376, now, clients))
    assert repeated["queued"] is False
    assert len(load_state(tmp_state)["candidates"]) == 1


def test_quick_note_backfill_rejects_other_formats_and_older_dates(tmp_state, monkeypatch):
    _bootstrapped_state(tmp_state)
    state = load_state(tmp_state)
    scan.advance_provider_cursor(state, Provider.PHINTRACO, 35388)
    save_state(state, tmp_state)
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    now = datetime.fromisoformat("2026-09-23T12:00:00+07:00")
    clients = _backfill_clients(
        SimpleNamespace(
            id=35381,
            message="Phintraco Sekuritas Company Update\nMEDC: Company outlook",
            date=datetime.fromisoformat("2026-09-23T03:00:00+00:00"),
            photo=None,
        )
    )

    with pytest.raises(ValueError, match="not exactly one supported"):
        asyncio.run(scan.backfill_phintraco_quick_note(35381, now, clients))

    clients.client.message.date = datetime.fromisoformat("2026-09-22T10:00:00+00:00")
    clients.client.message.id = 35376
    clients.client.message.message = "PHINTAS Quick Notes | 22 September 2026\nPOWR outlook"
    with pytest.raises(ValueError, match="published today"):
        asyncio.run(scan.backfill_phintraco_quick_note(35376, now, clients))

    clients.client.message.date = datetime.fromisoformat("2026-09-23T03:00:00+00:00")
    clients.client.message.id = 35389
    clients.client.message.message = "PHINTAS Quick Notes | 23 September 2026\nPOWR outlook"
    with pytest.raises(ValueError, match="at or behind the current Phintraco cursor"):
        asyncio.run(scan.backfill_phintraco_quick_note(35389, now, clients))

    assert load_state(tmp_state)["candidates"] == {}


def test_backfill_cli_accepts_the_single_message_command(monkeypatch, capsys):
    called = []

    async def backfill(message_id):
        called.append(message_id)
        return {"message_id": message_id, "queued": True, "cursor_advanced": False}

    monkeypatch.setattr(scan, "backfill_phintraco_quick_note", backfill)

    assert scan.main(["backfill-phintraco-quick-note", "--message-id", "35376"]) == 0
    assert called == [35376]
    assert json.loads(capsys.readouterr().out) == {
        "message_id": 35376,
        "queued": True,
        "cursor_advanced": False,
    }


def test_live_config_failure_stops_before_any_durable_state_mutation(tmp_state, monkeypatch):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))

    def unavailable():
        raise ValueError("control-plane is unavailable")

    monkeypatch.setattr(config, "load_watch_config_for_run", unavailable)

    with pytest.raises(ValueError, match="control-plane"):
        asyncio.run(scan.run(datetime.fromisoformat("2026-09-19T10:00:00+07:00"), FakeClients()))

    assert not tmp_state.exists()


def test_live_run_reports_lifecycle_events_against_its_frozen_revision(tmp_state, monkeypatch):
    _bootstrapped_state(tmp_state)
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    loaded = config.LoadedWatchConfig(config.default_watch_config(), 12)
    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: loaded)

    class CapturedRun:
        started: list[tuple[object, ...]] = []
        events: list[str] = []
        finished: list[tuple[str, str | None]] = []

        @classmethod
        def begin(cls, *args, **kwargs):
            cls.started.append((*args, kwargs))
            return cls()

        def event(self, event_id, **_kwargs):
            type(self).events.append(event_id)

        def finish(self, status, error=None):
            type(self).finished.append((status, error))

    monkeypatch.setattr(scan, "ControlPlaneRun", CapturedRun)

    result = asyncio.run(
        scan.run(datetime.fromisoformat("2026-07-14T16:30:00+07:00"), FakeClients())
    )

    assert result["wakeAgent"] is True
    assert CapturedRun.started == [
        ("IDX_MARKET_NEWS", 12, {"scheduler_job_id": "bursawatch-tg-market-news"})
    ]
    assert CapturedRun.events == [
        "run-started",
        "source-poll-completed",
        "delivery-drain-completed",
        "agent-wake-requested",
        "run-completed",
    ]
    assert CapturedRun.finished == [("ok", None)]


def test_health_warning_ignores_retry_history_on_terminal_candidates():
    state = empty_state()
    state["candidates"] = {
        "delivered": {
            "phase": "delivered",
            "retry": {"attempts": 3},
        },
        "abandoned": {
            "phase": "abandoned",
            "retry": {"attempts": 2},
        },
    }

    assert scan._health_and_warning(state) == (False, False, False)


def test_route_pending_suppresses_same_provider_repost(tmp_state, monkeypatch):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    published_at = datetime.fromisoformat("2026-08-14T08:00:00+07:00")
    state = empty_state()

    def add_candidate(message_id, source_text, dedupe_facts):
        candidate = CompanyCandidate(
            provider=Provider.TUNTUN,
            source_message_id=message_id,
            ticker="INDY",
            source_kind=SourceKind.TUNTUN_STANDALONE,
            published_at=published_at,
            source_text=source_text,
            direct_image=False,
        )
        enqueue_candidate(state, candidate, published_at)
        record = state["candidates"][candidate.key]
        record["phase"] = "pending_selection"
        record["classification"] = EventClass.CORPORATE_ACTION.value
        record["selection"] = {
            "summary": source_text,
            "ranking_band": 1,
            "material_facts": [source_text],
            "dedupe_facts": dedupe_facts,
        }
        return candidate

    original = add_candidate(
        14395,
        "INDY mendirikan dua anak usaha baru di bidang logistik dan kepelabuhanan.",
        ["INDY mendirikan dua anak usaha baru"],
    )
    repost = add_candidate(
        14396,
        "INDY membentuk dua anak usaha baru, TRADE dan TRADA, di bidang logistik dan pelayanan kepelabuhanan.",
        ["INDY membentuk TRADE dan TRADA"],
    )
    save_state(state, tmp_state)

    assert scan._route_pending(state) == 2
    assert state["candidates"][original.key]["phase"] == "pending_delivery"
    assert state["candidates"][repost.key]["phase"] == "suppressed_duplicate"
    assert state["dedupe"] == {repost.key: original.key}


def test_completed_tuntun_update_keeps_its_lead_and_two_best_sections_per_channel(tmp_state, monkeypatch):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    now = datetime.fromisoformat("2026-09-11T12:35:30+07:00")
    state = empty_state()
    definitions = (
        ("lead", "BUMI", SourceKind.TUNTUN_UPDATE_LEAD, 1, "id_stocks_news"),
        ("macro-1", None, SourceKind.TUNTUN_UPDATE_SECTION, 2, "macro_news"),
        ("macro-2", None, SourceKind.TUNTUN_UPDATE_SECTION, 3, "macro_news"),
        ("macro-3", None, SourceKind.TUNTUN_UPDATE_SECTION, 1, "macro_news"),
        ("macro-4", None, SourceKind.TUNTUN_UPDATE_SECTION, 4, "exclude"),
        ("industry-1", None, SourceKind.TUNTUN_UPDATE_INDUSTRY, 2, "macro_news"),
        ("industry-2", None, SourceKind.TUNTUN_UPDATE_INDUSTRY, 1, "macro_news"),
        ("industry-3", None, SourceKind.TUNTUN_UPDATE_INDUSTRY, 3, "macro_news"),
    )
    candidates = []
    for candidate_id, ticker, source_kind, ranking_band, route in definitions:
        candidate = CompanyCandidate(
            provider=Provider.TUNTUN,
            source_message_id=14786,
            ticker=ticker,
            candidate_id=candidate_id,
            source_kind=source_kind,
            published_at=now,
            source_text=f"{candidate_id} source evidence.",
            direct_image=False,
        )
        candidates.append(candidate)
        enqueue_candidate(state, candidate, now)
        if candidate_id == "macro-4":
            continue
        record = state["candidates"][candidate.key]
        record["phase"] = "pending_selection"
        record["classification"] = EventClass.OTHER_COMPANY_OPERATION.value
        record["selection"] = {
            "summary": "Source evidence is material.",
            "ranking_band": ranking_band,
            "material_facts": [f"{candidate_id} fact"],
            "dedupe_facts": [f"{candidate_id} fact"],
            "title": f"{ticker}: Source evidence" if ticker else "Source evidence",
            "route": route,
        }

    assert scan._route_pending(state) == 0
    assert state["candidates"][candidates[0].key]["phase"] == "pending_selection"

    final = next(candidate for candidate in candidates if candidate.candidate_id == "macro-4")
    record = state["candidates"][final.key]
    record["phase"] = "pending_selection"
    record["classification"] = EventClass.NOT_ELIGIBLE.value
    record["selection"] = {
        "summary": "The item is not eligible.",
        "ranking_band": 4,
        "material_facts": ["macro-4 fact"],
        "dedupe_facts": ["macro-4 fact"],
        "title": "Macro item",
        "route": "exclude",
    }

    assert scan._route_pending(state) == 8
    phases = {candidate.candidate_id: state["candidates"][candidate.key]["phase"] for candidate in candidates}
    assert phases == {
        "lead": "pending_delivery",
        "macro-1": "pending_delivery",
        "macro-2": "suppressed_rank",
        "macro-3": "pending_delivery",
        "macro-4": "suppressed_ineligible",
        "industry-1": "pending_delivery",
        "industry-2": "pending_delivery",
        "industry-3": "suppressed_rank",
    }

    posted = []

    async def deliver(current_state, item, channel_id, *_args, **_kwargs):
        posted.append((item.candidate.candidate_id, channel_id))
        return True

    monkeypatch.setattr(scan, "deliver_event", deliver)
    assert asyncio.run(scan._drain_delivery(state, None, now, dry_run=True)) == 5
    assert posted == [
        ("industry-1", scan.INDUSTRY_CHANNEL_ID),
        ("industry-2", scan.INDUSTRY_CHANNEL_ID),
        ("lead", scan.ALERT_CHANNEL_ID),
        ("macro-1", scan.MACRO_CHANNEL_ID),
        ("macro-3", scan.MACRO_CHANNEL_ID),
    ]


def test_run_delivers_every_eligible_event_immediately_as_standalone_news(tmp_state, monkeypatch):
    _bootstrapped_state(tmp_state)
    fake_clients = FakeClients()
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")

    first = asyncio.run(scan.run(now=datetime.fromisoformat("2026-07-14T16:30:00+07:00"), clients=fake_clients))
    assert first["wakeAgent"] is True
    item = first["items"][0]
    payload = {
        "candidate_key": item["candidate_key"],
        "ticker": item["ticker"],
        "event_class": EventClass.MATERIAL_CONTRACT.value,
        **(
            {"title": f"{item['ticker']}: Material contract disclosed"}
            if item["provider"] == Provider.TUNTUN.value
            else {}
        ),
            "summary": "The issuer disclosed a material contract. The disclosure identifies the agreement as material. The source names the disclosed contract value.",
        "material_facts": ["Contract value was disclosed."],
        "ranking_band": 1,
        "dedupe_facts": ["contract", "value"],
        "eligible": True,
        "route": "id_stocks_news",
        "source_evidence": "The provider message names the contract.",
    }
    submit_result = asyncio.run(
        scan.submit_classification_payload(payload, datetime.fromisoformat("2026-07-14T16:30:00+07:00"), clients=fake_clients)
    )
    assert submit_result["news_delivered"] == 1
    second = asyncio.run(scan.run(now=datetime.fromisoformat("2026-07-14T16:30:00+07:00"), clients=fake_clients))
    second_item = second["items"][0]
    second_payload = {
        **payload,
        "candidate_key": second_item["candidate_key"],
        "ticker": second_item["ticker"],
        "event_class": EventClass.OTHER_COMPANY_OPERATION.value,
        **(
            {"title": f"{second_item['ticker']}: Operational update"}
            if second_item["provider"] == Provider.TUNTUN.value
            else {}
        ),
    }
    second_result = asyncio.run(
        scan.submit_classification_payload(
            second_payload, datetime.fromisoformat("2026-07-14T16:30:00+07:00"), clients=fake_clients
        )
    )
    assert second_result["news_delivered"] == 1
    delivered = load_state()["stats"]["delivery_payloads"]
    assert all(not any(label in record["content"] for label in ("PRE-MARKET", "POST-MARKET", "INTRA-DAY")) for record in delivered.values())


def test_one_provider_failure_does_not_block_other_provider(tmp_state, monkeypatch):
    _bootstrapped_state(tmp_state)
    fake_clients = FakeClients()
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    fake_clients.phintraco_error = RuntimeError("channel unavailable")

    result = asyncio.run(scan.run(now=datetime.fromisoformat("2026-07-14T08:30:00+07:00"), clients=fake_clients))

    assert result["providers"][Provider.PHINTRACO.value]["healthy"] is False
    assert result["providers"][Provider.TUNTUN.value]["healthy"] is True


def test_run_preserves_news_state_when_shared_telegram_probe_times_out(
    tmp_state, tmp_path, monkeypatch
):
    from telegram_resilience import PolyCopResilience

    class UnavailableClient:
        async def connect(self):
            raise TimeoutError("network unavailable")

        async def disconnect(self):
            return None

    resilience = PolyCopResilience.for_paths(
        tmp_path / "resilience.json", tmp_path / "resilience.jsonl"
    )
    posted = []
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setattr(scan, "resilience", lambda: resilience)
    monkeypatch.setattr(scan, "_make_client", UnavailableClient)
    monkeypatch.setattr(scan, "delivery_client_from_environment", lambda: object())
    monkeypatch.setattr(
        scan,
        "post_hermes_text",
        lambda content, *_args, **_kwargs: posted.append(content) or "discord-id",
    )

    assert asyncio.run(
        scan.run(now=datetime.fromisoformat("2026-08-10T15:15:00+07:00"))
    ) == {"wakeAgent": False, "_telegram_resilience_handled": True}
    assert not tmp_state.exists()
    assert posted == [
        "❌ telegram-polycop · 15:15 WIB · transport unavailable; "
        "affected=idx-market-news"
    ]


def test_main_hides_handled_telegram_failure_from_hermes_response(monkeypatch, capsys):
    async def handled_run(*_args, **_kwargs):
        return {"wakeAgent": False, "_telegram_resilience_handled": True}

    monkeypatch.setattr(scan, "run", handled_run)

    assert scan.main([]) == 0
    assert json.loads(capsys.readouterr().out) == {"wakeAgent": False}


def test_expired_lease_is_retried_before_runtime_claims_the_next_oldest_due_candidate(
    tmp_state, monkeypatch, candidate, later_candidate
):
    state = empty_state()
    for lane in state["providers"].values():
        lane["bootstrap_complete"] = True
        lane["observed_message_id"] = 1000
    initial = datetime.fromisoformat("2026-07-14T08:00:00+07:00")
    enqueue_candidate(state, candidate, initial)
    assert claim_oldest_pending_analysis(state, initial) == candidate
    enqueue_candidate(state, later_candidate, datetime.fromisoformat("2026-07-14T08:01:00+07:00"))
    save_state(state, tmp_state)
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")

    result = asyncio.run(
        scan.run(now=datetime.fromisoformat("2026-07-14T08:03:00+07:00"), clients=FakeClients())
    )

    assert result["wakeAgent"] is True
    assert result["items"][0]["candidate_key"] == later_candidate.key


def test_cutover_suppresses_existing_queued_work_without_replaying_it(tmp_state, monkeypatch, candidate):
    now = datetime.fromisoformat("2026-07-31T12:30:00+07:00")
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    state = empty_state()
    state["stats"].pop("immediate_delivery_contract_v1")
    for lane in state["providers"].values():
        lane["bootstrap_complete"] = True
        lane["observed_message_id"] = 1000
    enqueue_candidate(state, candidate, now)
    state["candidates"][candidate.key]["phase"] = "pending_delivery"
    save_state(state, tmp_state)
    clients = FakeClients()
    clients.client.messages = {"phintraco": [], "tuntun": []}

    result = asyncio.run(scan.run(now, clients))

    migrated = load_state()
    assert result["news_delivered"] == 0
    assert migrated["candidates"][candidate.key]["phase"] == "abandoned"
    assert migrated["stats"]["immediate_delivery_contract_v1"]["abandoned"] == 1


def test_news_delivery_failure_stays_delivery_work_and_retries_once(tmp_state, monkeypatch):
    _bootstrapped_state(tmp_state)
    fake_clients = FakeClients()
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    owner = _install_delivery_owner(monkeypatch, fail_first_news=True)
    first = asyncio.run(scan.run(datetime.fromisoformat("2026-07-14T16:29:00+07:00"), fake_clients))
    item = first["items"][0]
    payload = {
        "candidate_key": item["candidate_key"],
        "ticker": item["ticker"],
        "event_class": EventClass.MATERIAL_CONTRACT.value,
        **(
            {"title": f"{item['ticker']}: Material contract disclosed"}
            if item["provider"] == Provider.TUNTUN.value
            else {}
        ),
            "summary": "The issuer disclosed a material contract. The disclosure identifies the agreement as material. The source names the disclosed contract value.",
        "material_facts": ["Contract value was disclosed."],
        "ranking_band": 1,
        "dedupe_facts": ["contract", "value"],
        "eligible": True,
        "route": "id_stocks_news",
        "source_evidence": "The provider message names the contract.",
    }
    failed = asyncio.run(scan.submit_classification_payload(payload, datetime.fromisoformat("2026-07-14T16:29:00+07:00"), fake_clients))
    persisted = load_state()
    record = persisted["candidates"][item["candidate_key"]]
    assert failed["news_delivered"] == 0
    assert record["phase"] == "pending_delivery"
    assert record["retry"]["attempts"] == 1
    assert item["candidate_key"] in persisted["stats"]["delivery_payloads"]

    retried = asyncio.run(scan.run(datetime.fromisoformat("2026-07-14T16:30:00+07:00"), fake_clients))

    assert retried["news_delivered"] == 1
    assert load_state()["candidates"][item["candidate_key"]]["phase"] == "delivered"
    news_operations = [operation for operation in owner.submissions if "heartbeat-" not in operation.key]
    assert len(news_operations) == 2
    assert news_operations[0].key == news_operations[1].key
    assert scan.ALERT_CHANNEL_ID == "1525102508714889257"
    assert {operation.target["channel_id"] for operation in news_operations} == {scan.ALERT_CHANNEL_ID}


def test_failed_tier_two_delivery_retries_without_waiting_for_a_scheduled_window(tmp_state, monkeypatch):
    _bootstrapped_state(tmp_state)
    fake_clients = FakeClients()
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    owner = _install_delivery_owner(monkeypatch, fail_first_news=True)
    first = asyncio.run(scan.run(datetime.fromisoformat("2026-07-14T16:30:00+07:00"), fake_clients))
    item = first["items"][0]
    payload = {
        "candidate_key": item["candidate_key"],
        "ticker": item["ticker"],
        "event_class": EventClass.OTHER_COMPANY_OPERATION.value,
        **(
            {"title": f"{item['ticker']}: Operational update"}
            if item["provider"] == Provider.TUNTUN.value
            else {}
        ),
            "summary": "The issuer disclosed an operational update. The disclosure identifies the affected activity. The source provides the relevant operating detail.",
        "material_facts": ["Operational activity was disclosed."],
        "ranking_band": 1,
        "dedupe_facts": ["operations", "activity"],
        "eligible": True,
        "route": "id_stocks_news",
        "source_evidence": "The provider message names the operational update.",
    }
    failed = asyncio.run(
        scan.submit_classification_payload(payload, datetime.fromisoformat("2026-07-14T16:30:00.001000+07:00"), fake_clients)
    )
    persisted = load_state()
    record = persisted["candidates"][item["candidate_key"]]
    assert failed["news_delivered"] == 0
    assert record["phase"] == "pending_delivery"
    assert persisted["digest_windows"] == {}

    retried = asyncio.run(scan.run(datetime.fromisoformat("2026-07-14T16:31:00.001000+07:00"), fake_clients))

    assert retried["news_delivered"] == 1
    assert load_state()["candidates"][item["candidate_key"]]["phase"] == "delivered"
    news_operations = [operation for operation in owner.submissions if "heartbeat-" not in operation.key]
    assert len(news_operations) == 2
    assert news_operations[0].key == news_operations[1].key
    assert {operation.target["channel_id"] for operation in news_operations} == {scan.ALERT_CHANNEL_ID}


def test_tier_two_delivery_does_not_wait_for_a_market_window(tmp_state, monkeypatch):
    _bootstrapped_state(tmp_state)
    fake_clients = FakeClients()
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")

    first = asyncio.run(scan.run(datetime.fromisoformat("2026-07-14T16:30:00+07:00"), fake_clients))
    item = first["items"][0]
    resumed = asyncio.run(scan.run(datetime.fromisoformat("2026-07-14T16:34:00+07:00"), fake_clients))
    item = resumed["items"][0]
    result = asyncio.run(
        scan.submit_classification_payload(
            {
                "candidate_key": item["candidate_key"],
                "ticker": item["ticker"],
                "event_class": EventClass.OTHER_COMPANY_OPERATION.value,
                **(
                    {"title": f"{item['ticker']}: Operational update"}
                    if item["provider"] == Provider.TUNTUN.value
                    else {}
                ),
                "summary": "The issuer disclosed an operational update. The disclosure identifies the affected activity. The source provides the relevant operating detail.",
                "material_facts": ["Operational activity was disclosed."],
                "ranking_band": 1,
                "dedupe_facts": ["operations", "activity"],
                "eligible": True,
                "route": "id_stocks_news",
                "source_evidence": "The provider message names the operational update.",
            },
            datetime.fromisoformat("2026-07-14T16:35:00+07:00"),
            fake_clients,
        )
    )

    assert result["news_delivered"] == 1
    record = load_state()["stats"]["delivery_payloads"][item["candidate_key"]]
    assert all(label not in record["content"] for label in ("PRE-MARKET", "POST-MARKET", "INTRA-DAY"))


def test_submit_classification_cli_is_text_only_even_when_source_has_image(
    tmp_state, monkeypatch, candidate
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    now = datetime.now(scan.WIB).replace(microsecond=0)
    direct_image = replace(candidate, direct_image=True, published_at=now)
    state = empty_state()
    enqueue_candidate(state, direct_image, now)
    assert claim_oldest_pending_analysis(state, now) == direct_image
    save_state(state, tmp_state)

    class ImageRuntime:
        def __init__(self):
            self.connected = False
            self.disconnected = False
            self.message_requests = []

        async def connect(self):
            self.connected = True

        async def disconnect(self):
            self.disconnected = True

        async def get_entity(self, entity):
            return entity

        async def get_messages(self, entity, ids):
            self.message_requests.append((entity, ids))
            return SimpleNamespace(id=ids, photo=object())

        async def download_media(self, message, file):
            return b"source-photo"

    runtime = ImageRuntime()
    monkeypatch.setattr(scan, "_make_client", lambda: runtime)
    payload = {
        "candidate_key": direct_image.key,
        "ticker": direct_image.ticker,
        "event_class": EventClass.MATERIAL_CONTRACT.value,
        "title": f"{direct_image.ticker}: Material contract disclosed",
            "summary": "The issuer disclosed a material contract. The disclosure identifies the agreement as material. The source names the disclosed contract value.",
        "material_facts": ["Contract value was disclosed."],
        "ranking_band": 1,
        "dedupe_facts": ["contract", "value"],
        "eligible": True,
        "route": "id_stocks_news",
        "source_evidence": "The provider message names the contract.",
    }

    assert scan.main(["submit-classification", "--json", json.dumps(payload)]) == 0

    delivery_record = load_state()["stats"]["delivery_payloads"][direct_image.key]
    assert not runtime.connected and not runtime.disconnected
    assert runtime.message_requests == []
    assert delivery_record["image_discord_id"] is None


def test_reloaded_failed_delivery_retries_once_without_a_hermes_wake(
    tmp_state, monkeypatch, candidate
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    now = datetime.fromisoformat("2026-07-14T16:00:00+07:00")
    state = empty_state()
    for lane in state["providers"].values():
        lane["bootstrap_complete"] = True
        lane["observed_message_id"] = 1000
    enqueue_candidate(state, candidate, now)
    assert claim_oldest_pending_analysis(state, now) == candidate
    payload = {
        "candidate_key": candidate.key,
        "ticker": candidate.ticker,
        "event_class": EventClass.MATERIAL_CONTRACT.value,
        "title": f"{candidate.ticker}: Material contract disclosed",
            "summary": "The issuer disclosed a material contract. The disclosure identifies the agreement as material. The source names the disclosed contract value.",
        "material_facts": ["Contract value was disclosed."],
        "ranking_band": 1,
        "dedupe_facts": ["contract", "value"],
        "eligible": True,
        "route": "id_stocks_news",
        "source_evidence": "The provider message names the contract.",
    }
    scan.submit_agent_classification(state, candidate, payload, now)
    assert scan._route_pending(state) == 1
    item = scan._all_classified(state)[0]
    save_state(state, tmp_state)
    owner = _install_delivery_owner(monkeypatch, fail_first_news=True)
    assert not asyncio.run(
        delivery.deliver_event(
            state,
            item,
            scan.ALERT_CHANNEL_ID,
            now,
            dry_run=False,
            delivery_client=owner,
        )
    )
    reloaded = load_state()
    assert reloaded["candidates"][candidate.key]["phase"] == "pending_delivery"
    assert candidate.key in reloaded["stats"]["delivery_payloads"]

    runtime = FakeClients()
    runtime.client.messages = {"phintraco": [], "tuntun": []}
    retried = asyncio.run(scan.run(now + timedelta(minutes=1), runtime))

    assert retried["news_delivered"] == 1
    assert retried["wakeAgent"] is False
    assert load_state()["candidates"][candidate.key]["phase"] == "delivered"
    news_operations = [operation for operation in owner.submissions if "heartbeat-" not in operation.key]
    assert len(news_operations) == 2
    assert news_operations[0].key == news_operations[1].key


def _status_source_message(message_id, text):
    return SimpleNamespace(
        id=message_id,
        message=text,
        date=datetime.fromisoformat("2026-09-23T01:27:27+00:00"),
        photo=None,
    )


def test_status_post_sends_one_grouped_message_without_agent_wake(
    tmp_state, monkeypatch, load_fixture
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    _bootstrapped_state(tmp_state)
    monkeypatch.setattr(
        delivery,
        "get_market_snapshot",
        lambda *_args: pytest.fail("status-only run requested a market quote"),
    )
    clients = FakeClients()
    clients.client.messages["tuntun"] = []
    body = load_fixture("phintraco-stock-status-35377.txt")
    clients.client.messages["phintraco"] = [_status_source_message(35377, body)]
    posts = []

    def post(content, channel_id, event_key, dry_run=False):
        posts.append((content, channel_id, event_key, dry_run))
        return "discord-message-42"

    monkeypatch.setattr(delivery, "post_discord_text", post)

    result = asyncio.run(
        scan.run(datetime.fromisoformat("2026-09-23T08:30:00+07:00"), clients)
    )

    assert result["wakeAgent"] is False
    assert result["items"] == []
    assert result["stock_status_delivered"] == 1
    assert result["stock_status_rejected"] == 0
    assert load_state()["candidates"] == {}
    assert load_state()["providers"]["phintraco"]["observed_message_id"] == 35377
    assert len(posts) == 1
    assert posts[0][0] == format_stock_status(
        parse_stock_information(35377, body),
        "https://t.me/phintasprofits/35377",
    )
    assert posts[0][1] == config.default_watch_config().id_stocks_news_channel_id
    assert posts[0][2] == "phintraco-stock-status:35377"
    assert posts[0][3] is True


def test_status_post_with_all_empty_categories_still_sends_complete_message(
    tmp_state, monkeypatch, load_fixture
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    _bootstrapped_state(tmp_state)
    body = load_fixture("phintraco-stock-status-35377.txt")
    empty_body = body.replace(">WAPO\n>NASI", ">-").replace(">UNSP", ">-")
    clients = FakeClients()
    clients.client.messages["tuntun"] = []
    clients.client.messages["phintraco"] = [_status_source_message(35377, empty_body)]
    posts = []
    monkeypatch.setattr(
        delivery,
        "post_discord_text",
        lambda content, channel_id, event_key, dry_run=False: posts.append(
            (content, channel_id, event_key)
        ) or "discord-message-42",
    )

    result = asyncio.run(
        scan.run(datetime.fromisoformat("2026-09-23T08:30:00+07:00"), clients)
    )

    assert result["stock_status_delivered"] == 1
    assert len(posts) == 1
    assert posts[0][0].count("(None)") == 5
    assert "- WAPO" not in posts[0][0] and "- NASI" not in posts[0][0]
    assert "- UNSP" not in posts[0][0]


def test_status_duplicate_read_does_not_post_twice(tmp_state, monkeypatch, load_fixture):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    _bootstrapped_state(tmp_state)
    clients = FakeClients()
    clients.client.messages["tuntun"] = []
    clients.client.messages["phintraco"] = [
        _status_source_message(35377, load_fixture("phintraco-stock-status-35377.txt"))
    ]
    posts = []
    monkeypatch.setattr(
        delivery,
        "post_discord_text",
        lambda content, channel_id, event_key, dry_run=False: posts.append(
            (content, channel_id, event_key)
        ) or "discord-message-42",
    )
    now = datetime.fromisoformat("2026-09-23T08:30:00+07:00")

    first = asyncio.run(scan.run(now, clients))
    second = asyncio.run(scan.run(now + timedelta(minutes=1), clients))

    assert first["stock_status_delivered"] == 1
    assert second["stock_status_delivered"] == 0
    assert len(posts) == 1


def test_status_retry_reuses_frozen_payload_route_and_event_identity(
    tmp_state, monkeypatch, load_fixture
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    _bootstrapped_state(tmp_state)
    clients = FakeClients()
    clients.client.messages["tuntun"] = []
    clients.client.messages["phintraco"] = [
        _status_source_message(35377, load_fixture("phintraco-stock-status-35377.txt"))
    ]
    posts = []

    def post(content, channel_id, event_key, dry_run=False):
        posts.append((content, channel_id, event_key))
        return None if len(posts) == 1 else "discord-message-42"

    monkeypatch.setattr(delivery, "post_discord_text", post)
    now = datetime.fromisoformat("2026-09-23T08:30:00+07:00")
    first = asyncio.run(scan.run(now, clients))
    failed_state = load_state(tmp_state)
    clients.client.messages["phintraco"] = []
    second = asyncio.run(scan.run(now + timedelta(minutes=1), clients))

    assert first["stock_status_delivered"] == 0
    assert scan._pending_count(failed_state) == 1
    # No-post mode keeps the event pending but does not count a failed live delivery attempt.
    assert scan._health_and_warning(failed_state) == (False, False, True)
    assert second["stock_status_delivered"] == 1
    assert len(posts) == 2
    assert posts[0] == posts[1]
    assert posts[0][1] == config.default_watch_config().id_stocks_news_channel_id
    assert posts[0][2] == "phintraco-stock-status:35377"


def test_malformed_status_is_persisted_before_cursor_advance_and_degrades_run(
    tmp_state, monkeypatch, load_fixture, capsys
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    _bootstrapped_state(tmp_state)
    body = load_fixture("phintraco-stock-status-35377.txt") + "\nNew Status:\n>ABCD\n"
    clients = FakeClients()
    clients.client.messages["tuntun"] = []
    clients.client.messages["phintraco"] = [_status_source_message(35377, body)]
    cursor_advances = []
    original_advance = scan.advance_provider_cursor

    def checked_advance(state, provider, message_id):
        if provider is Provider.PHINTRACO:
            event = state["stats"]["stock_status_events"][
                "phintraco-stock-status:35377"
            ]
            assert event["phase"] == "rejected"
            assert event["rejection_code"] == "invalid_status"
            cursor_advances.append(message_id)
        return original_advance(state, provider, message_id)

    monkeypatch.setattr(scan, "advance_provider_cursor", checked_advance)
    operational_posts = []
    status_posts = []
    monkeypatch.setattr(
        scan,
        "post_hermes_text",
        lambda content, *_args, **_kwargs: operational_posts.append(content) or "heartbeat-id",
    )
    monkeypatch.setattr(
        delivery,
        "post_discord_text",
        lambda *args, **kwargs: status_posts.append((args, kwargs)) or "unexpected-id",
    )

    class CapturedRun:
        events = []
        finished = []

        @classmethod
        def begin(cls, *_args, **_kwargs):
            return cls()

        def event(self, event_id, **kwargs):
            self.events.append((event_id, kwargs))

        def finish(self, outcome, error=None):
            self.finished.append((outcome, error))

    monkeypatch.setattr(scan, "ControlPlaneRun", CapturedRun)
    result = asyncio.run(
        scan.run(datetime.fromisoformat("2026-09-23T08:30:00+07:00"), clients)
    )

    persisted = load_state(tmp_state)
    event = persisted["stats"]["stock_status_events"]["phintraco-stock-status:35377"]
    assert event["phase"] == "rejected"
    assert event["rejection_code"] == "invalid_status"
    assert persisted["providers"]["phintraco"]["observed_message_id"] == 35377
    assert cursor_advances == [35377]
    assert result["stock_status_rejected"] == 1
    assert result["stock_status_delivered"] == 0
    assert CapturedRun.finished == [("degraded", None)]
    attributes = json.dumps(CapturedRun.events)
    assert '"stock_status_rejected": 1' in attributes
    assert "WAPO" not in attributes and "New Status" not in attributes
    captured_output = capsys.readouterr()
    assert body not in captured_output.out + captured_output.err
    assert status_posts == []
    assert "⚠️" in operational_posts[0]


def test_persisted_status_rejection_ignores_later_edit_and_recovers_cursor(
    tmp_state, monkeypatch, load_fixture
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    _bootstrapped_state(tmp_state)
    malformed = load_fixture("phintraco-stock-status-35377.txt") + "\nNew Status:\n>ABCD\n"
    valid_edit = load_fixture("phintraco-stock-status-35377.txt")
    clients = FakeClients()
    clients.client.messages["tuntun"] = []
    clients.client.messages["phintraco"] = [_status_source_message(35377, malformed)]
    original_advance = scan.advance_provider_cursor
    fail_once = True

    def interrupt_after_status_persist(state, provider, message_id):
        nonlocal fail_once
        if provider is Provider.PHINTRACO and fail_once:
            fail_once = False
            assert state["stats"]["stock_status_events"][
                "phintraco-stock-status:35377"
            ]["phase"] == "rejected"
            raise OSError("simulated cursor persistence interruption")
        return original_advance(state, provider, message_id)

    monkeypatch.setattr(scan, "advance_provider_cursor", interrupt_after_status_persist)
    monkeypatch.setattr(delivery, "post_discord_text", lambda *_args, **_kwargs: "unexpected")
    now = datetime.fromisoformat("2026-09-23T08:30:00+07:00")

    first = asyncio.run(scan.run(now, clients))
    clients.client.messages["phintraco"] = [
        _status_source_message(35377, valid_edit),
        _status_source_message(35378, "Company Flash: PTBA reports higher coal sales volume."),
    ]
    second = asyncio.run(scan.run(now + timedelta(minutes=1), clients))

    persisted = load_state(tmp_state)
    assert first["providers"]["phintraco"]["healthy"] is False
    assert second["providers"]["phintraco"]["healthy"] is True
    assert persisted["providers"]["phintraco"]["observed_message_id"] == 35378
    assert persisted["stats"]["stock_status_events"]["phintraco-stock-status:35377"][
        "phase"
    ] == "rejected"
    assert persisted["stats"]["stock_status_events"]["phintraco-stock-status:35377"][
        "rejection_code"
    ] == "invalid_status"
    assert "phintraco:35378:PTBA" in persisted["candidates"]
    assert second["stock_status_events"] == 0


def test_regular_phintraco_company_flash_and_tuntun_paths_still_ingest(
    tmp_state, monkeypatch
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    _bootstrapped_state(tmp_state)
    clients = FakeClients()
    clients.client.messages["phintraco"] = [
        _status_source_message(500, "Company Flash: PTBA reports higher coal sales volume.")
    ]
    result = asyncio.run(
        scan.run(datetime.fromisoformat("2026-09-23T08:30:00+07:00"), clients)
    )

    persisted = load_state(tmp_state)
    assert result["source_candidates"] == 2
    assert result["stock_status_events"] == 0
    assert "phintraco:500:PTBA" in persisted["candidates"]
    assert "tuntun:201:CBRE" in persisted["candidates"]
