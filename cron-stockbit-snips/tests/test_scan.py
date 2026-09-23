from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

import config
import scan
import state
from agent_protocol import analysis_payload
from models import Article, FeedLane, Route
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


def test_run_bootstraps_all_lanes_without_queue(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("STOCKBIT_SNIPS_NO_POST", "1")
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(scan, "_heartbeat", lambda *args: None)

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
    monkeypatch.setenv("STOCKBIT_SNIPS_NO_POST", "1")
    monkeypatch.setenv("STOCKBIT_SNIPS_STATE_PATH", str(path))
    monkeypatch.setattr(scan, "_heartbeat", lambda *args: None)
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
