from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json

import config
import pytest
import scan
import state
from agent_protocol import analysis_payload
from bursawatch_discord_delivery import OperationReceipt
from models import Article, FeedLane, Route, StockbitFeedSetting, StockbitWatchConfig
from rss import FetchResult


def article(lane: FeedLane, *, day: int = 23, suffix: str = "new") -> Article:
    return Article(
        lane=lane,
        lane_label=next(feed.label for feed in config.FEEDS if feed.lane is lane),
        guid=f"{lane.value}-{suffix}",
        url=f"https://snips.stockbit.com/{lane.value}/{suffix}",
        source_title="Pemerintah bahas perkembangan pasar",
        source_text="Pemerintah membahas perkembangan pasar dan kebijakan ekonomi.",
        published_at=datetime(2026, 9, day, 6, 0, tzinfo=UTC),
    )


def watch_config(*disabled: FeedLane) -> StockbitWatchConfig:
    return StockbitWatchConfig(
        feeds=tuple(StockbitFeedSetting(feed.lane, feed.lane not in disabled) for feed in config.FEEDS),
        id_stocks_news_channel_id="123456789012345678",
        macro_news_channel_id="234567890123456789",
        additional_prompt_instruction="",
    )


def set_live_config(monkeypatch, *disabled: FeedLane) -> None:
    loaded = config.LoadedStockbitConfig(config=watch_config(*disabled), revision=7)
    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: loaded)


def delivered_receipt(content: str, channel_id: str, *, event_key: str, leg: str) -> OperationReceipt:
    operation, _nonce = scan.discord._operation(content, channel_id, event_key, leg)
    return OperationReceipt(
        id=f"receipt:{event_key}", key=operation.key, digest=operation.digest,
        status="delivered", receipt={"channel_id": channel_id, "message_id": "345678901234567890"},
    )


def suppress_run_reporting(monkeypatch) -> None:
    class NoopRun:
        @classmethod
        def begin(cls, *args, **kwargs):
            return cls()

        def event(self, *args, **kwargs):
            pass

        def finish(self, *args, **kwargs):
            pass

    monkeypatch.setattr(scan, "ControlPlaneRun", NoopRun)


def test_state_upgrade_preserves_all_v1_values(tmp_path) -> None:
    path = tmp_path / "state.json"
    original = state.new_state(config.FEEDS)
    original["version"] = 1
    for feed in config.FEEDS:
        lane = original["feeds"][feed.lane.value]
        del lane["enabled"]
        lane.update({
            "cursor": {"guid": "old", "published_at": "2026-09-01T06:00:00+00:00"},
            "etag": f"etag-{feed.lane.value}",
            "last_modified": "Wed, 02 Sep 2026 06:00:00 GMT",
            "last_poll_success": "2026-09-02T06:00:00+00:00",
            "last_error": "previous timeout",
        })
    item = article(FeedLane.UNBOXING, suffix="queued")
    state.queue_article(original, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    queued = original["articles"][item.key]
    queued.update({
        "phase": "pending_delivery",
        "agent_lease_until": "2026-09-23T06:02:00+00:00",
        "analysis": {"candidate_key": item.key, "route": "macro_news", "title": "Existing"},
        "rendered": "Existing rendered content",
        "retry": {"attempts": 3, "next_attempt_at": "2026-09-23T07:00:00+00:00", "last_error": "rate limited"},
        "delivery": {"message_id": "existing-message"},
    })
    original["last_run"] = "2026-09-23T06:00:00+00:00"
    original["last_heartbeat"] = "2026-09-23T06:01:00+00:00"
    before = deepcopy(original)
    state.save_state(path, original)
    on_disk = path.read_bytes()

    upgraded = state.load_state(path, config.FEEDS)

    assert upgraded["version"] == 2
    for feed in config.FEEDS:
        assert upgraded["feeds"][feed.lane.value].pop("enabled") is True
    upgraded["version"] = 1
    assert upgraded == before
    assert "config_snapshot" not in upgraded["articles"][item.key]
    assert path.read_bytes() == on_disk


@pytest.mark.parametrize("corruption", ["version", "articles", "v1_article", "feed", "enabled", "missing_enabled", "article_record", "snapshot"])
def test_malformed_state_is_rejected_without_rewrite(tmp_path, corruption: str) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    item = article(FeedLane.UNBOXING)
    state.queue_article(value, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    if corruption == "version":
        value["version"] = 3
    elif corruption == "articles":
        value["articles"] = []
    elif corruption == "v1_article":
        value["version"] = 1
        for feed in config.FEEDS:
            del value["feeds"][feed.lane.value]["enabled"]
        value["articles"][item.key]["article"] = {"guid": "broken"}
    elif corruption == "feed":
        del value["feeds"][FeedLane.UNBOXING.value]
    elif corruption == "enabled":
        value["feeds"][FeedLane.UNBOXING.value]["enabled"] = "false"
    elif corruption == "missing_enabled":
        del value["feeds"][FeedLane.UNBOXING.value]["enabled"]
    elif corruption == "article_record":
        value["articles"][item.key]["article"] = {"guid": "broken"}
    else:
        value["articles"][item.key]["config_snapshot"] = {"revision": 7}
    state.save_state(path, value)
    before = path.read_bytes()

    with pytest.raises(RuntimeError, match="unsupported version|invalid|do not match"):
        state.load_state(path, config.FEEDS)
    assert path.read_bytes() == before


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize(
    "retry",
    [
        None,
        {},
        {"attempts": -1, "next_attempt_at": None, "last_error": None},
        {"attempts": True, "next_attempt_at": None, "last_error": None},
        {"attempts": "1", "next_attempt_at": None, "last_error": None},
        {"attempts": 1, "next_attempt_at": "2026-09-25T07:00:00", "last_error": None},
        {"attempts": 1, "next_attempt_at": 5, "last_error": None},
        {"attempts": 1, "next_attempt_at": None, "last_error": 5},
        {"attempts": 1, "next_attempt_at": None, "last_error": None, "extra": True},
    ],
    ids=["missing", "empty", "negative-attempts", "boolean-attempts", "text-attempts", "naive-time", "numeric-time", "numeric-error", "extra-key"],
)
def test_malformed_retry_is_rejected_before_state_use(tmp_path, retry, version) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    value["version"] = version
    if version == 1:
        for feed in config.FEEDS:
            del value["feeds"][feed.lane.value]["enabled"]
    item = article(FeedLane.UNBOXING_IPO)
    state.queue_article(value, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    record = value["articles"][item.key]
    if retry is None:
        del record["retry"]
    else:
        record["retry"] = retry
    state.save_state(path, value)
    before = path.read_bytes()

    with pytest.raises(RuntimeError, match="retry.*invalid"):
        state.load_state(path, config.FEEDS)

    assert path.read_bytes() == before


def test_future_retry_with_invalid_attempts_does_not_rewrite_v1_state_on_run(monkeypatch, tmp_path) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    value["version"] = 1
    for feed in config.FEEDS:
        del value["feeds"][feed.lane.value]["enabled"]
    item = article(FeedLane.UNBOXING_IPO)
    state.queue_article(value, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    record = value["articles"][item.key]
    record["retry"] = {
        "attempts": -1,
        "next_attempt_at": "2026-09-25T07:00:00+00:00",
        "last_error": "previous failure",
    }
    state.save_state(path, value)
    before = path.read_bytes()
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    monkeypatch.delenv("STOCKBIT_SNIPS_NO_POST", raising=False)
    set_live_config(monkeypatch)
    monkeypatch.setattr(scan, "fetch_feed", lambda *args, **kwargs: pytest.fail("invalid state polled RSS"))
    suppress_run_reporting(monkeypatch)

    with pytest.raises(RuntimeError, match="retry.*invalid"):
        scan.run()

    assert path.read_bytes() == before


def test_state_accepts_valid_article_snapshot(tmp_path) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    item = article(FeedLane.UNBOXING)
    state.queue_article(value, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    snapshot = {
        "revision": 7,
        "additional_prompt_instruction": "Focus on the supplied source",
        "id_stocks_news_channel_id": "123456789012345678",
        "macro_news_channel_id": "234567890123456789",
    }
    value["articles"][item.key]["config_snapshot"] = snapshot
    state.save_state(path, value)

    assert state.load_state(path, config.FEEDS)["articles"][item.key]["config_snapshot"] == snapshot


def test_disabled_lane_retains_cursor_validators_and_queued_work(monkeypatch, tmp_path) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    lane = value["feeds"][FeedLane.UNBOXING.value]
    lane.update({
        "cursor": {"guid": "before-pause", "published_at": "2026-09-01T06:00:00+00:00"},
        "etag": "old-etag",
        "last_modified": "old-modified",
    })
    queued = article(FeedLane.UNBOXING, suffix="already-queued")
    state.queue_article(value, queued, datetime(2026, 9, 22, 6, 0, tzinfo=UTC))
    state.save_state(path, value)
    monkeypatch.delenv("STOCKBIT_SNIPS_NO_POST", raising=False)
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    set_live_config(monkeypatch, FeedLane.UNBOXING)
    monkeypatch.setattr(scan, "_heartbeat", lambda *args: None)
    suppress_run_reporting(monkeypatch)
    fetched = []

    def fake_fetch(feed, **kwargs):
        fetched.append(feed.lane)
        return FetchResult(feed, (article(feed.lane),), "new-etag", None, False)

    monkeypatch.setattr(scan, "fetch_feed", fake_fetch)

    result = scan.run()
    saved = state.load_state(path, config.FEEDS)

    assert FeedLane.UNBOXING not in fetched
    assert len(fetched) == 3
    assert saved["feeds"][FeedLane.UNBOXING.value] == {**lane, "enabled": False}
    assert queued.key in saved["articles"]
    assert result["wakeAgent"] is True
    assert result["items"][0]["candidate_key"] == queued.key


def test_reenabled_lane_uses_unconditional_future_only_baseline(monkeypatch) -> None:
    value = state.new_state(config.FEEDS)
    lane = value["feeds"][FeedLane.UNBOXING.value]
    lane.update({
        "cursor": {"guid": "before-pause", "published_at": "2026-09-01T06:00:00+00:00"},
        "etag": "old-etag",
        "last_modified": "old-modified",
    })
    queued = article(FeedLane.UNBOXING, suffix="already-queued")
    state.queue_article(value, queued, datetime(2026, 9, 22, 6, 0, tzinfo=UTC))
    runtime = config.runtime()
    now = datetime(2026, 9, 23, 7, 0, tzinfo=UTC)
    calls = []

    def fake_fetch(feed, **kwargs):
        calls.append((feed.lane, kwargs))
        return FetchResult(feed, (article(feed.lane, suffix="paused"), article(feed.lane, day=24, suffix="current-newest")), "fresh-etag", "fresh-modified", False)

    monkeypatch.setattr(scan, "fetch_feed", fake_fetch)
    scan._fetch_into_state(value, runtime, now, watch_config(FeedLane.UNBOXING))
    assert value["feeds"][FeedLane.UNBOXING.value]["enabled"] is False
    assert value["feeds"][FeedLane.UNBOXING.value]["etag"] == "old-etag"
    stats = scan._fetch_into_state(value, runtime, now, watch_config())

    resumed_fetch = next(kwargs for fetched_lane, kwargs in calls if fetched_lane is FeedLane.UNBOXING)
    assert resumed_fetch["etag"] is None
    assert resumed_fetch["last_modified"] is None
    assert stats["queued"] == 0
    assert value["feeds"][FeedLane.UNBOXING.value]["cursor"]["guid"] == "unboxing-current-newest"
    assert value["feeds"][FeedLane.UNBOXING.value]["enabled"] is True
    assert value["feeds"][FeedLane.UNBOXING.value]["etag"] == "fresh-etag"
    assert list(value["articles"]) == [queued.key]


def test_reenabled_lane_failed_fetch_retries_unconditionally(monkeypatch) -> None:
    value = state.new_state(config.FEEDS)
    lane = value["feeds"][FeedLane.UNBOXING.value]
    lane.update({
        "enabled": False,
        "cursor": {"guid": "before-pause", "published_at": "2026-09-01T06:00:00+00:00"},
        "etag": "old-etag",
        "last_modified": "old-modified",
    })
    calls = []
    failed = True

    def fake_fetch(feed, **kwargs):
        nonlocal failed
        if feed.lane is FeedLane.UNBOXING:
            calls.append(kwargs)
            if failed:
                failed = False
                raise TimeoutError("temporary source failure")
        return FetchResult(feed, (article(feed.lane, suffix="current"),), "new-etag", "new-modified", False)

    monkeypatch.setattr(scan, "fetch_feed", fake_fetch)
    now = datetime(2026, 9, 23, 7, 0, tzinfo=UTC)
    first = scan._fetch_into_state(value, config.runtime(), now, watch_config())
    assert first["errors"]
    assert lane["enabled"] is False
    assert lane["cursor"]["guid"] == "before-pause"
    assert lane["etag"] is None
    assert lane["last_modified"] is None

    second = scan._fetch_into_state(value, config.runtime(), now, watch_config())
    assert calls[0]["etag"] is None and calls[0]["last_modified"] is None
    assert calls[1]["etag"] is None and calls[1]["last_modified"] is None
    assert second["queued"] == 0
    assert lane["enabled"] is True
    assert lane["cursor"]["guid"] == "unboxing-current"


def test_run_bootstraps_all_lanes_without_queue(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("STOCKBIT_SNIPS_NO_POST", "1")
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(scan, "_heartbeat", lambda *args: None)
    set_live_config(monkeypatch)

    def fake_fetch(feed, **kwargs):
        return FetchResult(feed, (article(feed.lane, suffix="bootstrap"),), "etag", None, False)

    monkeypatch.setattr(scan, "fetch_feed", fake_fetch)
    result = scan.run()

    assert result["wakeAgent"] is False
    assert result["stats"]["bootstrapped"] == 4
    value = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert value["articles"] == {}
    assert all(record["cursor"] for record in value["feeds"].values())


def test_run_queues_new_article_and_wakes_one_agent(monkeypatch, tmp_path) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    old = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
    for feed in config.FEEDS:
        value["feeds"][feed.lane.value]["cursor"] = {
            "published_at": old.isoformat(),
            "guid": "old",
        }
    state.save_state(path, value)
    monkeypatch.delenv("STOCKBIT_SNIPS_NO_POST", raising=False)
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    monkeypatch.setattr(scan, "_heartbeat", lambda *args: None)
    suppress_run_reporting(monkeypatch)
    set_live_config(monkeypatch)
    monkeypatch.setattr(
        scan,
        "fetch_feed",
        lambda feed, **kwargs: FetchResult(feed, (article(feed.lane),), "etag", None, False),
    )

    result = scan.run()

    assert result["wakeAgent"] is True
    assert len(result["items"]) == 1
    assert result["stats"]["queued"] == 4


def test_submit_analysis_persists_dash_render_without_post(monkeypatch, tmp_path) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    item = article(FeedLane.UNBOXING_IPO, suffix="ipo")
    state.queue_article(value, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    state.save_state(path, value)
    monkeypatch.setenv("STOCKBIT_SNIPS_NO_POST", "1")
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    monkeypatch.setattr(scan, "_heartbeat", lambda *args: None)
    monkeypatch.setattr(scan, "get_market_snapshot", lambda ticker: None)
    set_live_config(monkeypatch)

    payload = {
        "candidate_key": item.key,
        "ticker": "SWAP",
        "title": "SWAP: profil bisnis produk kesehatan",
        "summary": "SWAP memproduksi produk kesehatan dan berencana melakukan penawaran umum.",
        "material_facts": ["SWAP memproduksi produk kesehatan."],
        "dedupe_facts": ["SWAP IPO"],
        "eligible": True,
        "route": "id_stocks_news",
        "source_evidence": "Supplied Stockbit article.",
    }

    result = scan.submit_analysis(payload)
    saved = json.loads(path.read_text(encoding="utf-8"))
    record = saved["articles"][item.key]

    assert result["accepted"] is True
    assert result["no_post"] is True
    assert "Harga terakhir (IDR): **-**" in record["rendered"]
    assert record["rendered"].count("<:grey:1531279158913536182>") == 4
    assert record["phase"] == "pending_delivery"


def _issuer_payload(item: Article) -> dict[str, object]:
    return {
        "candidate_key": item.key,
        "ticker": "SWAP",
        "title": "SWAP: profil bisnis produk kesehatan",
        "summary": "SWAP memproduksi produk kesehatan.",
        "material_facts": ["SWAP memproduksi produk kesehatan."],
        "dedupe_facts": ["SWAP IPO"],
        "eligible": True,
        "route": "id_stocks_news",
        "source_evidence": "Supplied Stockbit article.",
    }


def test_frozen_config_survives_submission_and_delivery_retry(monkeypatch, tmp_path) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    item = article(FeedLane.UNBOXING_IPO)
    state.queue_article(value, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    state.save_state(path, value)
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    monkeypatch.delenv("STOCKBIT_SNIPS_NO_POST", raising=False)
    monkeypatch.setattr(scan, "_heartbeat", lambda *args: None)
    suppress_run_reporting(monkeypatch)
    loaded = config.LoadedStockbitConfig(replace(watch_config(), additional_prompt_instruction="instruction A"), 7)
    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: loaded)
    monkeypatch.setattr(scan, "fetch_feed", lambda feed, **kwargs: FetchResult(feed, (), None, None, True))
    monkeypatch.setattr(scan, "get_market_snapshot", lambda ticker: None)
    monkeypatch.setattr(scan.discord, "post_text", lambda *args, **kwargs: pytest.fail("no-post contacted Discord"))
    clock = [datetime(2026, 9, 23, 7, 0, tzinfo=UTC)]
    monkeypatch.setattr(scan, "_now", lambda: clock[0])

    wake = scan.run()
    saved = state.load_state(path, config.FEEDS)
    record = saved["articles"][item.key]
    assert wake["items"][0]["operator_instruction"] == "instruction A"
    assert record["config_snapshot"] == {
        "revision": 7,
        "additional_prompt_instruction": "instruction A",
        "id_stocks_news_channel_id": "123456789012345678",
        "macro_news_channel_id": "234567890123456789",
    }

    monkeypatch.delenv("STOCKBIT_SNIPS_NO_POST", raising=False)
    loaded = config.LoadedStockbitConfig(
        replace(watch_config(), id_stocks_news_channel_id="345678901234567890", additional_prompt_instruction="instruction B"), 8
    )
    posted_channel_ids = []

    def post_then_retry(content, channel_id, **kwargs):
        posted_channel_ids.append(channel_id)
        if len(posted_channel_ids) == 1:
            raise RuntimeError("temporary delivery failure")
        return delivered_receipt(content, channel_id, event_key=kwargs["event_key"], leg=kwargs["leg"])

    monkeypatch.setattr(scan.discord, "post_text", post_then_retry)
    scan.submit_analysis(_issuer_payload(item))
    pending = state.load_state(path, config.FEEDS)["articles"][item.key]
    assert pending["phase"] == "pending_delivery"
    assert pending["config_snapshot"]["revision"] == 7
    assert pending["rendered"]

    loaded = config.LoadedStockbitConfig(
        replace(watch_config(), id_stocks_news_channel_id="456789012345678901", additional_prompt_instruction="instruction C"), 9
    )
    clock[0] += timedelta(minutes=2)
    scan.run()
    delivered = state.load_state(path, config.FEEDS)["articles"][item.key]
    assert delivered["phase"] == "delivered"
    assert delivered["delivery"]["channel_id"] == "123456789012345678"
    assert posted_channel_ids[0] == "123456789012345678"
    assert posted_channel_ids[1] == "123456789012345678"


def test_unbound_legacy_waits_for_config_then_binds_once(monkeypatch, tmp_path) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    item = article(FeedLane.UNBOXING)
    state.queue_article(value, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    state.save_state(path, value)
    before = path.read_bytes()
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    monkeypatch.setenv("STOCKBIT_SNIPS_NO_POST", "1")
    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: (_ for _ in ()).throw(ValueError("unavailable")))
    monkeypatch.setattr(scan, "fetch_feed", lambda *args, **kwargs: pytest.fail("config failure polled RSS"))
    monkeypatch.setattr(scan.discord, "post_text", lambda *args, **kwargs: pytest.fail("no-post contacted Discord"))

    blocked = scan.run()
    assert blocked["wakeAgent"] is False
    assert path.read_bytes() == before

    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: config.LoadedStockbitConfig(
        replace(watch_config(), additional_prompt_instruction="legacy A"), 7
    ))
    monkeypatch.delenv("STOCKBIT_SNIPS_NO_POST")
    monkeypatch.setattr(scan, "_heartbeat", lambda *args: None)
    suppress_run_reporting(monkeypatch)
    monkeypatch.setattr(scan, "fetch_feed", lambda feed, **kwargs: FetchResult(feed, (), None, None, True))
    wake = scan.run()
    assert wake["items"][0]["operator_instruction"] == "legacy A"
    assert state.load_state(path, config.FEEDS)["articles"][item.key]["config_snapshot"]["revision"] == 7

    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: config.LoadedStockbitConfig(
        replace(watch_config(), additional_prompt_instruction="legacy B"), 8
    ))
    second = scan.run()
    assert second["items"] == []
    assert state.load_state(path, config.FEEDS)["articles"][item.key]["config_snapshot"]["additional_prompt_instruction"] == "legacy A"


def test_run_reporting_uses_only_safe_lifecycle_fields(monkeypatch, tmp_path) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    item = article(FeedLane.UNBOXING_IPO)
    state.queue_article(value, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    state.save_state(path, value)
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    loaded = config.LoadedStockbitConfig(replace(watch_config(), additional_prompt_instruction="SECRET PROMPT"), 7)
    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: loaded)
    monkeypatch.setattr(scan, "fetch_feed", lambda feed, **kwargs: FetchResult(feed, (), None, None, True))
    monkeypatch.setattr(scan, "get_market_snapshot", lambda ticker: None)
    monkeypatch.setattr(scan.discord, "post_text", lambda content, channel_id, **kwargs: delivered_receipt(content, channel_id, event_key=kwargs["event_key"], leg=kwargs["leg"]))
    calls = []

    class RecordedRun:
        @classmethod
        def begin(cls, *args, **kwargs):
            calls.append(("begin", args, kwargs))
            return cls()

        def event(self, *args, **kwargs):
            calls.append(("event", args, kwargs))

        def finish(self, *args, **kwargs):
            calls.append(("finish", args, kwargs))

    monkeypatch.setattr(scan, "ControlPlaneRun", RecordedRun, raising=False)
    scan.run()
    scan.submit_analysis(_issuer_payload(item))

    begins = [entry for entry in calls if entry[0] == "begin"]
    assert [(entry[1][0], entry[1][1], entry[2]["trigger"]) for entry in begins] == [
        ("STOCKBIT_SNIPS", 7, "scheduled"),
        ("STOCKBIT_SNIPS", 7, "agent_submission"),
    ]
    assert all(entry[2]["scheduler_job_id"] == "bursawatch-stockbit-snips" for entry in begins)
    assert len([entry for entry in calls if entry[0] == "finish"]) == 2
    events = [entry for entry in calls if entry[0] == "event"]
    assert events
    for entry in events:
        text = repr(entry)
        assert "SECRET PROMPT" not in text
        assert item.source_title not in text
        assert item.source_text not in text
        assert str(path) not in text
        assert set(entry[2].get("attributes", {})) <= {
            "fetched", "queued", "bootstrapped", "not_modified", "pending", "delivered", "no_post", "errors",
        }


def test_no_post_reads_live_config_without_discord_or_run_reporting(monkeypatch, tmp_path) -> None:
    path = tmp_path / "state.json"
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    monkeypatch.setenv("STOCKBIT_SNIPS_NO_POST", "1")
    reads = []
    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: reads.append(1) or config.LoadedStockbitConfig(watch_config(), 7))
    monkeypatch.setattr(scan, "fetch_feed", lambda feed, **kwargs: FetchResult(feed, (article(feed.lane),), None, None, False))
    monkeypatch.setattr(scan.discord, "post_text", lambda *args, **kwargs: pytest.fail("no-post contacted Discord"))

    class ForbiddenRun:
        @classmethod
        def begin(cls, *args, **kwargs):
            pytest.fail("no-post began run reporting")

    monkeypatch.setattr(scan, "ControlPlaneRun", ForbiddenRun, raising=False)
    scan.run()
    assert reads == [1]


def test_no_post_preserves_queued_article_without_claim_or_wake(monkeypatch, tmp_path) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    item = article(FeedLane.UNBOXING_IPO)
    state.queue_article(value, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    queued = deepcopy(value["articles"][item.key])
    state.save_state(path, value)
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    monkeypatch.setenv("STOCKBIT_SNIPS_NO_POST", "1")
    reads = []
    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: reads.append(1) or config.LoadedStockbitConfig(watch_config(), 7))
    monkeypatch.setattr(scan, "fetch_feed", lambda feed, **kwargs: FetchResult(feed, (), None, None, True))
    monkeypatch.setattr(scan.discord, "post_text", lambda *args, **kwargs: pytest.fail("no-post contacted Discord"))

    class ForbiddenRun:
        @classmethod
        def begin(cls, *args, **kwargs):
            pytest.fail("no-post began run reporting")

    monkeypatch.setattr(scan, "ControlPlaneRun", ForbiddenRun)
    result = scan.run()

    assert reads == [1]
    assert result["wakeAgent"] is False
    assert result["items"] == []
    assert state.load_state(path, config.FEEDS)["articles"][item.key] == queued


def test_config_outage_drains_bound_delivery_and_attempts_fixed_heartbeat(monkeypatch, tmp_path) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    item = article(FeedLane.UNBOXING_IPO)
    state.queue_article(value, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    record = value["articles"][item.key]
    record["phase"] = "pending_delivery"
    record["analysis"] = _issuer_payload(item)
    record["rendered"] = "Previously rendered content"
    record["config_snapshot"] = {
        "revision": 7, "additional_prompt_instruction": "instruction A",
        "id_stocks_news_channel_id": "123456789012345678",
        "macro_news_channel_id": "234567890123456789",
    }
    state.save_state(path, value)
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    monkeypatch.delenv("STOCKBIT_SNIPS_NO_POST", raising=False)
    monkeypatch.setenv("STOCKBIT_SNIPS_HEARTBEAT_CHANNEL_ID", "987654321098765432")
    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: (_ for _ in ()).throw(ValueError("secret /local/path")))
    monkeypatch.setattr(scan, "fetch_feed", lambda *args, **kwargs: pytest.fail("outage polled source"))
    calls = []
    monkeypatch.setattr(scan.discord, "post_text", lambda content, channel_id, **kwargs: calls.append((content, channel_id)) or delivered_receipt(content, channel_id, event_key=kwargs["event_key"], leg=kwargs["leg"]))

    class ForbiddenRun:
        @classmethod
        def begin(cls, *args, **kwargs):
            pytest.fail("unknown live revision began reporting")

    monkeypatch.setattr(scan, "ControlPlaneRun", ForbiddenRun, raising=False)
    result = scan.run()
    saved = state.load_state(path, config.FEEDS)
    assert saved["articles"][item.key]["phase"] == "delivered"
    assert calls[0] == ("Previously rendered content", "123456789012345678")
    assert calls[1][1] == config.HEARTBEAT_CHANNEL_ID
    assert "secret" not in repr(result)
    assert "/local/path" not in repr(result)


def test_owner_accepted_pending_delivery_does_not_start_local_retry_clock(monkeypatch, tmp_path) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    item = article(FeedLane.UNBOXING_IPO)
    now = datetime(2026, 9, 24, 0, 0, tzinfo=UTC)
    state.queue_article(value, item, now)
    record = value["articles"][item.key]
    record["phase"] = "pending_delivery"
    record["analysis"] = _issuer_payload(item)
    record["rendered"] = "Previously rendered content"
    record["config_snapshot"] = {
        "revision": 7, "additional_prompt_instruction": "instruction A",
        "id_stocks_news_channel_id": "123456789012345678",
        "macro_news_channel_id": "234567890123456789",
    }
    runtime = config.RuntimeConfig(
        state_path=path, no_post=False, request_timeout=20,
        heartbeat_channel_id=config.HEARTBEAT_CHANNEL_ID,
        id_stocks_news_channel_id=config.ID_STOCKS_NEWS_CHANNEL_ID,
        macro_news_channel_id=config.MACRO_NEWS_CHANNEL_ID,
    )
    monkeypatch.setattr(
        scan.discord,
        "post_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(scan.discord.DeliveryOwnerPending("accepted")),
    )

    assert scan._drain_delivery(value, runtime, now) == 0

    saved = value["articles"][item.key]
    assert saved["phase"] == "pending_delivery"
    assert saved["retry"] == {"attempts": 0, "next_attempt_at": None, "last_error": None}


@pytest.mark.parametrize(
    ("receipt_channel", "expected_delivered"),
    [(None, True), ("999999999999999999", False)],
)
def test_delivery_receipt_channel_is_optional_but_mismatch_is_rejected(
    monkeypatch, tmp_path, receipt_channel: str | None, expected_delivered: bool,
) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    item = article(FeedLane.UNBOXING_IPO, suffix=f"receipt-{receipt_channel or 'omitted'}")
    now = datetime(2026, 9, 24, 0, 0, tzinfo=UTC)
    state.queue_article(value, item, now)
    record = value["articles"][item.key]
    record["phase"] = "pending_delivery"
    record["analysis"] = _issuer_payload(item)
    record["rendered"] = "Previously rendered content"
    channel_id = "123456789012345678"
    record["config_snapshot"] = {
        "revision": 7, "additional_prompt_instruction": "instruction A",
        "id_stocks_news_channel_id": channel_id,
        "macro_news_channel_id": "234567890123456789",
    }
    runtime = config.RuntimeConfig(
        state_path=path, no_post=False, request_timeout=20,
        heartbeat_channel_id=config.HEARTBEAT_CHANNEL_ID,
        id_stocks_news_channel_id=config.ID_STOCKS_NEWS_CHANNEL_ID,
        macro_news_channel_id=config.MACRO_NEWS_CHANNEL_ID,
    )
    operation, _nonce = scan.discord._operation(record["rendered"], channel_id, item.key, "news")
    receipt_value = {"message_id": "345678901234567890"}
    if receipt_channel is not None:
        receipt_value["channel_id"] = receipt_channel
    receipt = OperationReceipt(
        id="existing-delivered-operation",
        key=operation.key,
        digest=operation.digest,
        status="delivered",
        receipt=receipt_value,
    )

    class Owner:
        def __init__(self) -> None:
            self.status_keys: list[str] = []
            self.submitted = []

        def status(self, operation_key: str) -> OperationReceipt:
            self.status_keys.append(operation_key)
            return receipt

        def submit(self, submitted_operation) -> OperationReceipt:
            self.submitted.append(submitted_operation)
            return receipt

    owner = Owner()
    monkeypatch.setattr(scan.discord, "delivery_client_from_environment", lambda: owner)

    delivered = scan._drain_delivery(value, runtime, now)

    saved = value["articles"][item.key]
    assert owner.status_keys == [operation.key]
    assert owner.submitted == []
    if expected_delivered:
        assert delivered == 1
        assert saved["phase"] == "delivered"
        assert saved["delivery"]["channel_id"] == channel_id
        assert saved["delivery"]["receipt"]["receipt"] == {"message_id": "345678901234567890"}
    else:
        assert delivered == 0
        assert saved["phase"] == "pending_delivery"


def test_unbound_legacy_delivery_waits_for_config_then_uses_first_revision(monkeypatch, tmp_path) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    item = article(FeedLane.UNBOXING_IPO)
    state.queue_article(value, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    record = value["articles"][item.key]
    record["phase"] = "pending_delivery"
    record["analysis"] = _issuer_payload(item)
    record["rendered"] = "Previously rendered content"
    state.save_state(path, value)
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    monkeypatch.setenv("STOCKBIT_SNIPS_NO_POST", "1")
    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: (_ for _ in ()).throw(ValueError("unavailable")))
    monkeypatch.setattr(scan, "fetch_feed", lambda *args, **kwargs: pytest.fail("outage polled source"))
    monkeypatch.setattr(scan.discord, "post_text", lambda *args, **kwargs: pytest.fail("no-post contacted Discord"))
    before = path.read_bytes()

    scan.run()
    assert path.read_bytes() == before

    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: config.LoadedStockbitConfig(watch_config(), 7))
    monkeypatch.setattr(scan, "fetch_feed", lambda feed, **kwargs: FetchResult(feed, (), None, None, True))
    scan.run()
    bound = state.load_state(path, config.FEEDS)["articles"][item.key]
    assert bound["phase"] == "pending_delivery"
    assert bound["config_snapshot"]["revision"] == 7


@pytest.mark.parametrize(
    "failure",
    [scan.discord.DiscordRateLimited(2.5), RuntimeError("credential /private/path")],
    ids=["rate-limited", "ordinary-error"],
)
def test_scheduled_delivery_failure_degrades_run_without_exposing_error(monkeypatch, tmp_path, failure) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    item = article(FeedLane.UNBOXING_IPO)
    state.queue_article(value, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    record = value["articles"][item.key]
    record["phase"] = "pending_delivery"
    record["analysis"] = _issuer_payload(item)
    record["rendered"] = "Previously rendered content"
    record["config_snapshot"] = scan._snapshot(config.LoadedStockbitConfig(watch_config(), 7))
    state.save_state(path, value)
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    monkeypatch.delenv("STOCKBIT_SNIPS_NO_POST", raising=False)
    set_live_config(monkeypatch)
    monkeypatch.setattr(scan, "fetch_feed", lambda feed, **kwargs: FetchResult(feed, (), None, None, True))
    monkeypatch.setattr(scan, "_heartbeat", lambda *args: None)
    monkeypatch.setattr(scan.discord, "post_text", lambda *args, **kwargs: (_ for _ in ()).throw(failure))
    calls = []

    class RecordedRun:
        @classmethod
        def begin(cls, *args, **kwargs):
            return cls()

        def event(self, *args, **kwargs):
            calls.append(("event", args, kwargs))

        def finish(self, *args, **kwargs):
            calls.append(("finish", args, kwargs))

    monkeypatch.setattr(scan, "ControlPlaneRun", RecordedRun)
    result = scan.run()

    assert result["stats"]["delivered"] == 0
    assert result["stats"]["degraded"] is True
    assert result["stats"]["errors"] == ["Stockbit delivery failed"]
    assert calls[-1] == ("finish", ("degraded",), {})
    assert "credential" not in repr(calls)
    assert "/private/path" not in repr(calls)
    assert state.load_state(path, config.FEEDS)["articles"][item.key]["retry"]["attempts"] == 1


def test_legacy_delivery_snapshot_is_durable_before_first_send(monkeypatch, tmp_path) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    item = article(FeedLane.UNBOXING_IPO)
    state.queue_article(value, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    record = value["articles"][item.key]
    record["phase"] = "pending_delivery"
    record["analysis"] = _issuer_payload(item)
    record["rendered"] = "Previously rendered content"
    state.save_state(path, value)
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    monkeypatch.delenv("STOCKBIT_SNIPS_NO_POST", raising=False)
    live = [config.LoadedStockbitConfig(watch_config(), 7)]
    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: live[0])
    monkeypatch.setattr(scan, "fetch_feed", lambda feed, **kwargs: FetchResult(feed, (), None, None, True))
    monkeypatch.setattr(scan, "_heartbeat", lambda *args: None)
    suppress_run_reporting(monkeypatch)
    clock = [datetime(2026, 9, 23, 7, 0, tzinfo=UTC)]
    monkeypatch.setattr(scan, "_now", lambda: clock[0])
    at_send = []

    def fail_first_send(content, channel_id, **kwargs):
        at_send.append(state.load_state(path, config.FEEDS)["articles"][item.key].get("config_snapshot"))
        raise RuntimeError("first send failed")

    monkeypatch.setattr(scan.discord, "post_text", fail_first_send)
    scan.run()
    assert at_send == [scan._snapshot(live[0])]
    assert state.load_state(path, config.FEEDS)["articles"][item.key]["config_snapshot"]["revision"] == 7

    live[0] = config.LoadedStockbitConfig(
        replace(watch_config(), id_stocks_news_channel_id="345678901234567890"), 8
    )
    clock[0] += timedelta(minutes=2)
    channels = []
    monkeypatch.setattr(scan.discord, "post_text", lambda content, channel_id, **kwargs: channels.append(channel_id) or delivered_receipt(content, channel_id, event_key=kwargs["event_key"], leg=kwargs["leg"]))
    scan.run()
    assert channels == ["123456789012345678"]
    assert state.load_state(path, config.FEEDS)["articles"][item.key]["config_snapshot"]["revision"] == 7


@pytest.mark.parametrize("malformed_bound", [False, True], ids=["legacy-malformed", "already-bound-malformed"])
def test_malformed_due_delivery_does_not_persist_new_legacy_bindings(monkeypatch, tmp_path, malformed_bound) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    value["version"] = 1
    for feed in config.FEEDS:
        del value["feeds"][feed.lane.value]["enabled"]
    valid = article(FeedLane.UNBOXING_IPO, suffix="legacy-valid")
    malformed = article(FeedLane.UNBOXING_IPO, suffix="legacy-malformed")
    for item in (valid, malformed):
        state.queue_article(value, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
        record = value["articles"][item.key]
        record["phase"] = "pending_delivery"
        record["rendered"] = "Previously rendered content"
    value["articles"][valid.key]["analysis"] = _issuer_payload(valid)
    broken = value["articles"][malformed.key]
    broken["analysis"] = {"route": "id_stocks_news"}
    if malformed_bound:
        broken["config_snapshot"] = scan._snapshot(config.LoadedStockbitConfig(watch_config(), 6))
    state.save_state(path, value)
    before = path.read_bytes()
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    monkeypatch.delenv("STOCKBIT_SNIPS_NO_POST", raising=False)
    set_live_config(monkeypatch)
    monkeypatch.setattr(scan, "fetch_feed", lambda feed, **kwargs: FetchResult(feed, (), None, None, True))
    monkeypatch.setattr(scan.discord, "post_text", lambda *args, **kwargs: pytest.fail("malformed state contacted Discord"))
    suppress_run_reporting(monkeypatch)

    with pytest.raises(RuntimeError, match="analysis is malformed"):
        scan.run()

    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "entry",
    ["scheduled-binding", "config-outage", "no-post-run", "agent-submission", "agent-exclusion"],
)
def test_malformed_future_retry_cannot_be_saved_by_other_work(monkeypatch, tmp_path, entry) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    value["version"] = 1
    for feed in config.FEEDS:
        del value["feeds"][feed.lane.value]["enabled"]
    broken = article(FeedLane.UNBOXING_IPO, day=22, suffix="future-malformed")
    other = article(FeedLane.UNBOXING_IPO, day=23, suffix="other-work")
    for item in (broken, other):
        state.queue_article(value, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    broken_record = value["articles"][broken.key]
    broken_record["phase"] = "pending_delivery"
    broken_record["analysis"] = {"route": "id_stocks_news"}
    broken_record["retry"]["next_attempt_at"] = "2026-09-25T07:00:00+00:00"
    if entry == "scheduled-binding":
        other_record = value["articles"][other.key]
        other_record["phase"] = "pending_delivery"
        other_record["analysis"] = _issuer_payload(other)
        other_record["rendered"] = "Previously rendered content"
    else:
        snapshot = scan._snapshot(config.LoadedStockbitConfig(watch_config(), 7))
        broken_record["config_snapshot"] = snapshot.copy()
        value["articles"][other.key]["config_snapshot"] = snapshot.copy()
    state.save_state(path, value)
    before = path.read_bytes()
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    monkeypatch.delenv("STOCKBIT_SNIPS_NO_POST", raising=False)
    if entry == "no-post-run":
        monkeypatch.setenv("STOCKBIT_SNIPS_NO_POST", "1")
    monkeypatch.setattr(scan, "_heartbeat", lambda *args: None)
    monkeypatch.setattr(scan, "fetch_feed", lambda feed, **kwargs: FetchResult(feed, (), None, None, True))
    monkeypatch.setattr(scan, "get_market_snapshot", lambda ticker: None)
    monkeypatch.setattr(scan.discord, "post_text", lambda *args, **kwargs: "message-id")
    suppress_run_reporting(monkeypatch)
    if entry == "config-outage":
        monkeypatch.setattr(config, "load_watch_config_for_run", lambda: (_ for _ in ()).throw(ValueError("unavailable")))
    else:
        set_live_config(monkeypatch)

    with pytest.raises(RuntimeError, match="analysis is malformed"):
        if entry in {"agent-submission", "agent-exclusion"}:
            payload = _issuer_payload(other)
            if entry == "agent-exclusion":
                payload.update({"ticker": "", "eligible": False, "route": "exclude", "title": "Artikel sumber dikecualikan"})
            scan.submit_analysis(payload)
        else:
            scan.run()

    assert path.read_bytes() == before


def test_no_post_submission_reads_live_config_without_discord_or_reporting(monkeypatch, tmp_path) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    item = article(FeedLane.UNBOXING_IPO)
    state.queue_article(value, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    value["articles"][item.key]["config_snapshot"] = {
        "revision": 7, "additional_prompt_instruction": "instruction A",
        "id_stocks_news_channel_id": "123456789012345678",
        "macro_news_channel_id": "234567890123456789",
    }
    state.save_state(path, value)
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    monkeypatch.setenv("STOCKBIT_SNIPS_NO_POST", "1")
    reads = []
    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: reads.append(1) or config.LoadedStockbitConfig(watch_config(), 8))
    monkeypatch.setattr(scan, "get_market_snapshot", lambda ticker: None)
    monkeypatch.setattr(scan.discord, "post_text", lambda *args, **kwargs: pytest.fail("no-post contacted Discord"))

    class ForbiddenRun:
        @classmethod
        def begin(cls, *args, **kwargs):
            pytest.fail("no-post began run reporting")

    monkeypatch.setattr(scan, "ControlPlaneRun", ForbiddenRun)
    result = scan.submit_analysis(_issuer_payload(item))
    assert result["no_post"] is True
    assert reads == [1]
    assert state.load_state(path, config.FEEDS)["articles"][item.key]["config_snapshot"]["revision"] == 7


def test_failed_submission_delivery_reports_degraded_without_error_detail(monkeypatch, tmp_path) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    item = article(FeedLane.UNBOXING_IPO)
    state.queue_article(value, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    value["articles"][item.key]["config_snapshot"] = {
        "revision": 7, "additional_prompt_instruction": "instruction A",
        "id_stocks_news_channel_id": "123456789012345678",
        "macro_news_channel_id": "234567890123456789",
    }
    state.save_state(path, value)
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    monkeypatch.delenv("STOCKBIT_SNIPS_NO_POST", raising=False)
    monkeypatch.setattr(scan, "get_market_snapshot", lambda ticker: None)
    monkeypatch.setattr(scan.discord, "post_text", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("credential /private/path")))
    calls = []

    class RecordedRun:
        @classmethod
        def begin(cls, *args, **kwargs):
            calls.append(("begin", args, kwargs))
            return cls()

        def event(self, *args, **kwargs):
            calls.append(("event", args, kwargs))

        def finish(self, *args, **kwargs):
            calls.append(("finish", args, kwargs))

    monkeypatch.setattr(scan, "ControlPlaneRun", RecordedRun)
    result = scan.submit_analysis(_issuer_payload(item))
    assert result["delivered"] == 0
    assert calls[-1] == ("finish", ("degraded",), {})
    assert "credential" not in repr(calls)
    assert "/private/path" not in repr(calls)


def test_submission_degrades_when_another_due_delivery_fails(monkeypatch, tmp_path) -> None:
    path = tmp_path / "state.json"
    value = state.new_state(config.FEEDS)
    due = article(FeedLane.UNBOXING_IPO, day=22, suffix="due")
    submitted = article(FeedLane.UNBOXING_IPO, day=23, suffix="submitted")
    snapshot = scan._snapshot(config.LoadedStockbitConfig(watch_config(), 7))
    for item in (due, submitted):
        state.queue_article(value, item, datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
        value["articles"][item.key]["config_snapshot"] = snapshot.copy()
    due_record = value["articles"][due.key]
    due_record["phase"] = "pending_delivery"
    due_record["analysis"] = _issuer_payload(due)
    due_record["rendered"] = "Previously rendered content"
    state.save_state(path, value)
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    monkeypatch.delenv("STOCKBIT_SNIPS_NO_POST", raising=False)
    monkeypatch.setattr(scan, "get_market_snapshot", lambda ticker: None)
    sent = []

    def post_text(content, channel_id, *, event_key, **kwargs):
        sent.append(event_key)
        if event_key == due.key:
            raise RuntimeError("credential /private/path")
        return delivered_receipt(content, channel_id, event_key=event_key, leg=kwargs["leg"])

    monkeypatch.setattr(scan.discord, "post_text", post_text)
    calls = []

    class RecordedRun:
        @classmethod
        def begin(cls, *args, **kwargs):
            return cls()

        def event(self, *args, **kwargs):
            calls.append(("event", args, kwargs))

        def finish(self, *args, **kwargs):
            calls.append(("finish", args, kwargs))

    monkeypatch.setattr(scan, "ControlPlaneRun", RecordedRun)
    result = scan.submit_analysis(_issuer_payload(submitted))
    saved = state.load_state(path, config.FEEDS)["articles"]

    assert sent == [due.key, submitted.key]
    assert result["delivered"] == 1
    assert saved[submitted.key]["phase"] == "delivered"
    assert saved[due.key]["phase"] == "pending_delivery"
    assert saved[due.key]["retry"]["attempts"] == 1
    assert calls[-1] == ("finish", ("degraded",), {})
    completed = [entry for entry in calls if entry[0] == "event" and entry[2]["event_type"] == "submission.completed"]
    assert completed[0][2]["attributes"]["errors"] == ["Stockbit delivery failed"]
    assert "credential" not in repr(calls)
    assert "/private/path" not in repr(calls)


def test_split_stockbit_items_resume_without_changing_quotes_or_source(tmp_path,monkeypatch):
    source=article(FeedLane.STOCKBIT_COMMENTARY)
    value=state.new_state(config.FEEDS);state.queue_article(value,source,source.published_at)
    record=value['articles'][source.key]
    record['config_snapshot']={'revision':7,'additional_prompt_instruction':'','id_stocks_news_channel_id':'123456789012345678','macro_news_channel_id':'234567890123456789'}
    record['source_work']={'event_key':'a'*64,'version':1}
    from agent_protocol import validate_submissions
    def item(ticker):
        return {'ticker':ticker,'title':ticker+': Pembagian dividen','summary':ticker+' akan membagikan dividen.','material_facts':[ticker+' dividen'],'dedupe_facts':[ticker+' dividen'],'eligible':True,'route':'id_stocks_news','source_evidence':'Sumber menyebut dividen '+ticker+'.'}
    analyses=validate_submissions(source,{'candidate_key':source.key,'items':[item('DADA'),item('NICL')]})
    quotes=[]
    monkeypatch.setattr(scan,'get_market_snapshot',lambda ticker:quotes.append(ticker))
    calls=[]
    def send(content,channel_id,*,dry_run,event_key,leg,return_receipt):
        saved=state.load_state(runtime.state_path,config.FEEDS)
        assert all(saved['articles'][key]['rendered'] for key in saved['articles'][source.key]['news_item_keys'])
        calls.append((content,channel_id,event_key,leg))
        if len(calls)==2:
            raise scan.discord.DeliveryOwnerPending('pending')
        return delivered_receipt(content,channel_id,event_key=event_key,leg=leg)
    runtime=config.RuntimeConfig(state_path=tmp_path/'state.json',no_post=False,request_timeout=10,heartbeat_channel_id='987654321098765432',id_stocks_news_channel_id='123456789012345678',macro_news_channel_id='234567890123456789')
    monkeypatch.setattr(scan.discord,'post_text',send)
    result=scan._submit_split_analysis(value,record,source,analyses,runtime,source.published_at,[])
    assert result['delivered']==1 and quotes==['DADA','NICL']
    saved=state.load_state(runtime.state_path,config.FEEDS)
    keys=saved['articles'][source.key]['news_item_keys']
    assert saved['articles'][keys[0]]['phase']=='delivered'
    assert saved['articles'][keys[1]]['phase']=='pending_delivery'
    monkeypatch.setattr(scan,'get_market_snapshot',lambda *args:pytest.fail('retry fetched quotes'))
    assert scan._drain_delivery(saved,runtime,source.published_at)==1
    assert calls[1]==calls[2] and calls[0][2]!=calls[1][2]
    for key in keys:
        child=saved['articles'][key]
        assert child['article']['url']==source.url
        assert child['article']['published_at']==source.published_at.isoformat()
        assert child['source_work']['event_key']=='a'*64
        assert child['rendered'].count('Harga terakhir')==1
