from __future__ import annotations

from datetime import UTC, datetime

import config
import publication_projection as projection
import scan
import state
from bursawatch_discord_delivery import OperationReceipt
from models import Article, FeedLane


NOW = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)


def _article() -> Article:
    return Article(
        lane=FeedLane.UNBOXING,
        lane_label="Unboxing",
        guid="stockbit-guid-1",
        url="https://snips.stockbit.com/article/1",
        source_title="DEWA secures a contract",
        source_text="DEWA secured a contract from a named customer.",
        published_at=datetime(2026, 9, 30, 7, 0, tzinfo=UTC),
    )


def _bound_state(route: str = "id_stocks_news"):
    article = _article()
    value = state.new_state(config.FEEDS)
    state.queue_article(value, article, NOW)
    record = value["articles"][article.key]
    record.update({
        "phase": "pending_delivery",
        "source_work": {"event_key": "a" * 64, "version": 1},
        "config_snapshot": {
            "revision": 4,
            "additional_prompt_instruction": "",
            "id_stocks_news_channel_id": "123456789012345678",
            "macro_news_channel_id": "234567890123456789",
        },
        "analysis": {
            "candidate_key": article.key,
            "ticker": "DEWA" if route == "id_stocks_news" else "",
            "title": "DEWA: Secures a contract" if route == "id_stocks_news" else "Contract activity in Indonesia",
            "summary": "DEWA secured a contract from a named customer.",
            "material_facts": ["contract secured"],
            "dedupe_facts": ["DEWA contract"],
            "eligible": route != "exclude",
            "route": route,
            "source_evidence": "The article reports the contract.",
        },
        "rendered": "<:stockbit:1552220036557578311> DEWA contract output",
    })
    channel = "123456789012345678" if route == "id_stocks_news" else "234567890123456789"
    operation, _nonce = scan.discord._operation(record["rendered"], channel, article.key, "news")
    receipt = OperationReceipt(
        id="delivery-op-1", key=operation.key, digest=operation.digest, status="delivered",
        receipt={"channel_id": channel, "message_id": "234567890123456789"},
    )
    record["delivery"] = {
        "message_id": "234567890123456789",
        "channel_id": channel,
        "delivered_at": NOW.isoformat(),
        "operation_key": operation.key,
        "operation_digest": operation.digest,
        "receipt": {
            "id": receipt.id, "key": receipt.key, "digest": receipt.digest,
            "status": receipt.status, "receipt": receipt.receipt,
        },
    }
    return value, article, operation, receipt


def test_confirmed_stockbit_routes_create_typed_snapshots():
    for route, expected_type, expected_ticker in (
        ("id_stocks_news", "idx_company_news", "DEWA"),
        ("macro_news", "macro_news", None),
    ):
        value, article, _operation, _receipt = _bound_state(route)
        snapshot = projection._snapshot(value, article.key, NOW)
        assert snapshot is not None
        assert (snapshot["type"], snapshot["route"], snapshot["ticker"]) == (
            expected_type, route, expected_ticker,
        )
        assert snapshot["source_event_key"] == "a" * 64
        assert snapshot["legs"][0]["text"] == value["articles"][article.key]["rendered"]
        assert snapshot["legs"][0]["receipt_operation_id"] == "delivery-op-1"


def test_excluded_or_unproven_article_has_no_publication():
    excluded, article, *_ = _bound_state("exclude")
    assert projection._snapshot(excluded, article.key, NOW) is None
    legacy, article, *_ = _bound_state()
    del legacy["articles"][article.key]["source_work"]
    assert projection._snapshot(legacy, article.key, NOW) is None
    paused, article, *_ = _bound_state()
    paused["feeds"][article.lane.value]["enabled"] = False
    assert projection._snapshot(paused, article.key, NOW) is None


def test_incomplete_or_mismatched_receipt_cannot_be_projected():
    value, article, _operation, _receipt = _bound_state()
    value["articles"][article.key]["delivery"]["receipt"]["receipt"]["message_id"] = "999999999999999999"
    try:
        projection._snapshot(value, article.key, NOW)
    except projection.IncompletePublication:
        pass
    else:
        raise AssertionError("mismatched receipt was accepted")


def test_confirmed_receipt_intent_is_saved_before_article_terminal_state(tmp_path, monkeypatch):
    monkeypatch.setenv("BURSAWATCH_STOCKBIT_SNIPS_PUBLICATION_ENABLED", "1")
    value, article, operation, receipt = _bound_state()
    record = value["articles"][article.key]
    record["delivery"] = None
    path = tmp_path / "state.json"
    runtime = config.RuntimeConfig(
        state_path=path, no_post=False, request_timeout=10,
        heartbeat_channel_id="987654321098765432",
        id_stocks_news_channel_id="123456789012345678",
        macro_news_channel_id="234567890123456789",
    )
    monkeypatch.setattr(
        scan.discord, "post_text",
        lambda *args, **kwargs: receipt,
    )
    saves = []
    save_state = state.save_state

    def record_save(save_path, current):
        current_record = current["articles"][article.key]
        saves.append((current_record["phase"], f"article:{article.key}" in current.get(state.PUBLICATION_LEDGER_KEY, {})))
        save_state(save_path, current)

    monkeypatch.setattr(state, "save_state", record_save)
    assert scan._drain_delivery(value, runtime, NOW) == 1
    assert saves == [("pending_delivery", True)]
    assert value["articles"][article.key]["phase"] == "delivered"


def test_projection_outage_retries_snapshot_without_reposting(tmp_path, monkeypatch):
    monkeypatch.setenv("BURSAWATCH_STOCKBIT_SNIPS_PUBLICATION_ENABLED", "1")
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(tmp_path / "state.json"))
    value, article, _operation, _receipt = _bound_state()
    snapshot = projection._snapshot(value, article.key, NOW)
    assert snapshot is not None
    state.record_publication_intent(value, snapshot)
    value["articles"][article.key]["phase"] = "delivered"
    path = tmp_path / "state.json"
    state.save_state(path, value)

    class Client:
        def __init__(self):
            self.submissions = []
            self.checkpoints = []

        def submit(self, saved_snapshot):
            self.submissions.append(saved_snapshot)
            if len(self.submissions) == 1:
                raise OSError("control plane offline")
            return {"publication_id": "b" * 64, "version": 1, "digest": "c" * 64}

        def checkpoint(self, comparison):
            self.checkpoints.append(comparison)
            return {"accepted": True}

    monkeypatch.setattr(scan.discord, "post_text", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("projection retried Discord")))
    client = Client()
    first = scan._drain_publications(value, path, NOW, client)
    second = scan._drain_publications(value, path, NOW, client)
    saved = state.load_state(path, config.FEEDS)

    assert first == {"accepted": 0, "pending": 1}
    assert second == {"accepted": 1, "pending": 0}
    assert client.submissions == [snapshot, snapshot]
    assert saved["articles"][article.key]["phase"] == "delivered"
    assert client.checkpoints[-1]["confirmed_through_at"] == client.checkpoints[-1]["accepted_through_at"]
