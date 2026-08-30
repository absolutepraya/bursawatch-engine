from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import delivery
import scan
from domain import CompanyCandidate, EventClass, Provider, SourceKind
from selection import SelectionCandidate
from state import claim_oldest_pending_analysis, empty_state, enqueue_candidate, load_state, save_state


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


def _bootstrapped_state(tmp_state):
    state = empty_state()
    for lane in state["providers"].values():
        lane["bootstrap_complete"] = True
    save_state(state, tmp_state)


def test_message_topic_id_reads_the_forum_root_reply_message_id():
    message = SimpleNamespace(
        reply_to=SimpleNamespace(reply_to_msg_id=3743, reply_to_top_id=None, forum_topic=True)
    )

    assert scan._message_topic_id(message) == 3743


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
            "summary": "The issuer disclosed a material contract. The disclosure identifies the agreement as material. The source names the disclosed contract value.",
        "material_facts": ["Contract value was disclosed."],
        "ranking_band": 1,
        "dedupe_facts": ["contract", "value"],
        "eligible": True,
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
    monkeypatch.setattr(
        scan,
        "post_hermes_text",
        lambda content, *_args: posted.append(content) or "discord-id",
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
    posts = []

    def post(content, channel_id, event_key, dry_run=False):
        posts.append((content, channel_id, event_key))
        return None if len(posts) == 1 else "discord-id"

    monkeypatch.setattr(delivery, "post_discord_text", post)
    first = asyncio.run(scan.run(datetime.fromisoformat("2026-07-14T16:29:00+07:00"), fake_clients))
    item = first["items"][0]
    payload = {
        "candidate_key": item["candidate_key"],
        "ticker": item["ticker"],
        "event_class": EventClass.MATERIAL_CONTRACT.value,
            "summary": "The issuer disclosed a material contract. The disclosure identifies the agreement as material. The source names the disclosed contract value.",
        "material_facts": ["Contract value was disclosed."],
        "ranking_band": 1,
        "dedupe_facts": ["contract", "value"],
        "eligible": True,
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
    assert len(posts) == 2
    assert scan.ALERT_CHANNEL_ID == "1525102508714889257"
    assert {channel_id for _, channel_id, _ in posts} == {scan.ALERT_CHANNEL_ID}


def test_failed_tier_two_delivery_retries_without_waiting_for_a_scheduled_window(tmp_state, monkeypatch):
    _bootstrapped_state(tmp_state)
    fake_clients = FakeClients()
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    posts = []

    def post(content, channel_id, event_key, dry_run=False):
        posts.append((content, channel_id, event_key))
        return None if len(posts) == 1 else "discord-id"

    monkeypatch.setattr(delivery, "post_discord_text", post)
    first = asyncio.run(scan.run(datetime.fromisoformat("2026-07-14T16:30:00+07:00"), fake_clients))
    item = first["items"][0]
    payload = {
        "candidate_key": item["candidate_key"],
        "ticker": item["ticker"],
        "event_class": EventClass.OTHER_COMPANY_OPERATION.value,
            "summary": "The issuer disclosed an operational update. The disclosure identifies the affected activity. The source provides the relevant operating detail.",
        "material_facts": ["Operational activity was disclosed."],
        "ranking_band": 1,
        "dedupe_facts": ["operations", "activity"],
        "eligible": True,
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
    assert len(posts) == 2
    assert {channel_id for _, channel_id, _ in posts} == {scan.ALERT_CHANNEL_ID}


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
                "summary": "The issuer disclosed an operational update. The disclosure identifies the affected activity. The source provides the relevant operating detail.",
                "material_facts": ["Operational activity was disclosed."],
                "ranking_band": 1,
                "dedupe_facts": ["operations", "activity"],
                "eligible": True,
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
            "summary": "The issuer disclosed a material contract. The disclosure identifies the agreement as material. The source names the disclosed contract value.",
        "material_facts": ["Contract value was disclosed."],
        "ranking_band": 1,
        "dedupe_facts": ["contract", "value"],
        "eligible": True,
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
            "summary": "The issuer disclosed a material contract. The disclosure identifies the agreement as material. The source names the disclosed contract value.",
        "material_facts": ["Contract value was disclosed."],
        "ranking_band": 1,
        "dedupe_facts": ["contract", "value"],
        "eligible": True,
        "source_evidence": "The provider message names the contract.",
    }
    scan.submit_agent_classification(state, candidate, payload, now)
    assert scan._route_pending(state) == 1
    item = scan._all_classified(state)[0]
    save_state(state, tmp_state)
    posts = []

    def post(content, channel_id, event_key, dry_run=False):
        posts.append((content, channel_id, event_key))
        return None if len(posts) == 1 else "discord-id"

    monkeypatch.setattr(delivery, "post_discord_text", post)
    assert not asyncio.run(
        delivery.deliver_event(state, item, scan.ALERT_CHANNEL_ID, now, dry_run=True)
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
    assert len(posts) == 2
