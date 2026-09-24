from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib-bursawatch-discord-delivery" / "bin"))

import discord
from bursawatch_discord_delivery import OperationIntent, OperationReceipt


class Owner:
    def __init__(self, receipt):
        self.receipt = receipt
        self.status_keys = []
        self.submitted = []

    def status(self, key):
        self.status_keys.append(key)
        return self.receipt

    def submit(self, operation):
        self.submitted.append(operation)
        raise AssertionError("the existing accepted operation must be recovered")

    def wait(self, key, timeout):
        raise AssertionError("a delivered operation must not need a wait")


def test_duplicate_stockbit_submission_recovers_existing_receipt_without_bot_token(monkeypatch):
    operation_key = "bursawatch-stockbit-snips:" + discord.nonce("event-1", "news")
    expected = OperationIntent(
        key=operation_key,
        kind="channel_message_create",
        ordering_key="channel:42",
        target={"channel_id": "42"},
        payload={"content": "Stockbit update", "allowed_mentions": {"parse": []}},
    )
    owner = Owner(
        OperationReceipt(
            id="op-1",
            key=expected.key,
            digest=expected.digest,
            status="delivered",
            receipt={"channel_id": "42", "message_id": "123456789012345678"},
        )
    )
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    message_id = discord.post_text(
        "Stockbit update",
        "42",
        dry_run=False,
        event_key="event-1",
        leg="news",
        client=owner,
    )

    assert message_id == "123456789012345678"
    assert owner.status_keys == [operation_key]
    assert owner.submitted == []


def test_handoff_uses_saved_live_destination_and_leaves_v1_state_unmigrated(tmp_path, monkeypatch):
    import json

    import config
    import delivery_handoff
    from datetime import datetime, timezone
    from models import Article, FeedLane

    article = Article(
        lane=FeedLane.STOCKBIT_COMMENTARY, lane_label="Stockbit Commentary",
        guid="guid-1", url="https://snips.stockbit.com/article/1", source_title="Source title",
        source_text="Source text", published_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
    )
    snapshot = {
        "revision": 41, "additional_prompt_instruction": "frozen for this article",
        "id_stocks_news_channel_id": "1551234567890123456",
        "macro_news_channel_id": "1551234567890123457",
    }
    source_state = {
        "version": 1,
        "feeds": {feed.lane.value: {
            "cursor": None, "etag": None, "last_modified": None,
            "last_poll_success": None, "last_error": None,
        } for feed in config.FEEDS},
        "articles": {article.key: {
            "article": article.to_payload(), "phase": "pending_delivery",
            "enqueued_at": "2026-09-20T00:00:00+00:00", "agent_lease_until": None,
            "analysis": {
                "candidate_key": article.key, "ticker": "BBCA", "title": "BBCA: Update",
                "summary": "Summary", "material_facts": ["fact"], "dedupe_facts": [],
                "eligible": True, "route": "id_stocks_news", "source_evidence": "source",
            },
            "rendered": "Frozen rendered content", "retry": {
                "attempts": 0, "next_attempt_at": None, "last_error": None,
            },
            "config_snapshot": snapshot,
        }},
    }
    state_path = tmp_path / "stockbit-state.json"
    state_path.write_text(json.dumps(source_state), encoding="utf-8")
    original = state_path.read_bytes()
    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: (_ for _ in ()).throw(AssertionError("handoff must use the article-frozen config")))
    adapter = delivery_handoff.StockbitSnipsHandoffAdapter(state_path, tmp_path / "handoff.json")

    handoff = adapter.build_handoff_snapshot()

    assert len(handoff.items) == 1
    operation = handoff.items[0].operation
    assert operation.target == {"channel_id": "1551234567890123456"}
    assert operation.payload["content"] == "Frozen rendered content"
    assert operation.reconcile_before_first_create is True
    assert operation.legacy_nonce == discord.nonce(article.key, "news")
    assert state_path.read_bytes() == original
    assert json.loads(state_path.read_text(encoding="utf-8"))["version"] == 1
