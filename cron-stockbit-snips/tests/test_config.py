from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

import config
import control_plane_client
import models


def valid_config() -> dict[str, object]:
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

    assert isinstance(parsed, models.StockbitWatchConfig)
    assert parsed.feeds == tuple(models.StockbitFeedSetting(lane, True) for lane in models.FeedLane)
    assert parsed.id_stocks_news_channel_id == "1525102508714889257"
    assert parsed.macro_news_channel_id == "1531655369884045382"
    assert parsed.additional_prompt_instruction == ""


def test_load_watch_config_data_accepts_disabled_lane_and_normalizes_instruction():
    raw = valid_config()
    raw["feeds"][1]["enabled"] = False
    raw["additional_prompt_instruction"] = "  Focus\n\t on  the thesis.  "

    parsed = config.load_watch_config_data(raw)

    assert parsed.feeds[1] == models.StockbitFeedSetting(models.FeedLane.UNBOXING, False)
    assert parsed.additional_prompt_instruction == "Focus on the thesis."


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda raw: raw["feeds"].pop(), "all four Stockbit lanes"),
        (lambda raw: raw["feeds"][1].update(id="stockbit_commentary"), "unique and complete"),
        (lambda raw: raw["feeds"][1].update(id="unknown"), "unsupported"),
        (lambda raw: raw["feeds"][1].update(enabled=1), "must be boolean"),
        (lambda raw: raw["feeds"][1].update(extra=True), "only id and enabled"),
        (lambda raw: raw["destinations"].pop("macro_news_channel_id"), "invalid shape"),
        (
            lambda raw: raw["destinations"].update(macro_news_channel_id="1525102508714889257"),
            "must differ",
        ),
        (
            lambda raw: raw["destinations"].update(macro_news_channel_id="not-a-snowflake"),
            "Discord snowflake",
        ),
        (
            lambda raw: raw["destinations"].update(macro_news_channel_id="١٢٣٤٥٦٧٨٩٠١٢٣٤٥٦٧٨"),
            "Discord snowflake",
        ),
        (
            lambda raw: raw["destinations"].update(macro_news_channel_id="１２３４５６７８９０１２３４５６７８"),
            "Discord snowflake",
        ),
        (lambda raw: raw.update(extra=True), "invalid shape"),
        (lambda raw: raw.update(version=2), "version must be 1"),
        (lambda raw: raw.update(additional_prompt_instruction="x" * 801), "at most 800"),
    ],
)
def test_load_watch_config_data_rejects_invalid_shapes(change, message):
    raw = deepcopy(valid_config())
    change(raw)

    with pytest.raises(ValueError, match=message):
        config.load_watch_config_data(raw)


@pytest.mark.parametrize("instruction", ["x" * 800, "\U0001f600" * 800])
def test_load_watch_config_data_accepts_800_code_points(instruction):
    raw = valid_config()
    raw["additional_prompt_instruction"] = instruction

    assert config.load_watch_config_data(raw).additional_prompt_instruction == instruction


def test_load_watch_config_data_rejects_801_non_bmp_code_points():
    raw = valid_config()
    raw["additional_prompt_instruction"] = "\U0001f600" * 801

    with pytest.raises(ValueError, match="at most 800"):
        config.load_watch_config_data(raw)


@pytest.fixture
def live_settings(monkeypatch):
    monkeypatch.setenv("STOCKBIT_SNIPS_CONTROL_PLANE_URL", "https://control.test")
    monkeypatch.setenv("STOCKBIT_SNIPS_CONTROL_PLANE_TOKEN", "synthetic-token")
    monkeypatch.setenv("STOCKBIT_SNIPS_CONTROL_PLANE_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("STOCKBIT_SNIPS_CONTROL_PLANE_WATCHER_ID", "bursawatch-stockbit-snips")


def live_snapshot(**changes):
    values = {
        "watcher_id": "bursawatch-stockbit-snips",
        "revision": 7,
        "config_version": 1,
        "config": valid_config(),
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_load_watch_config_for_run_returns_one_live_revision(live_settings, monkeypatch):
    calls = []
    live_config = valid_config()
    live_config["feeds"][1]["enabled"] = False
    live_config["additional_prompt_instruction"] = "Focus on the thesis."
    snapshot = live_snapshot(config=live_config)

    def fake_fetch(base_url, watcher_id, token, *, timeout):
        calls.append((base_url, watcher_id, token, timeout))
        return snapshot

    monkeypatch.setattr(control_plane_client, "fetch_config", fake_fetch)
    loaded = config.load_watch_config_for_run()

    assert calls == [("https://control.test", "bursawatch-stockbit-snips", "synthetic-token", 9.0)]
    assert isinstance(loaded, config.LoadedStockbitConfig)
    assert loaded.revision == 7
    assert isinstance(loaded.config, models.StockbitWatchConfig)
    assert loaded.config.feeds[1] == models.StockbitFeedSetting(models.FeedLane.UNBOXING, False)
    assert loaded.config.additional_prompt_instruction == "Focus on the thesis."


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("STOCKBIT_SNIPS_CONTROL_PLANE_URL", None),
        ("STOCKBIT_SNIPS_CONTROL_PLANE_TOKEN", ""),
        ("STOCKBIT_SNIPS_CONTROL_PLANE_WATCHER_ID", "another-watcher"),
    ],
)
def test_load_watch_config_for_run_requires_all_live_settings(
    live_settings, monkeypatch, name, value
):
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    calls = []
    monkeypatch.setattr(control_plane_client, "fetch_config", lambda *args, **kwargs: calls.append(True))

    with pytest.raises(ValueError, match="Stockbit live configuration"):
        config.load_watch_config_for_run()

    assert calls == []


@pytest.mark.parametrize(
    "snapshot",
    [
        live_snapshot(watcher_id="another-watcher"),
        live_snapshot(config_version=2),
        live_snapshot(revision=0),
        live_snapshot(config={"version": 1}),
    ],
)
def test_load_watch_config_for_run_rejects_invalid_snapshot(live_settings, monkeypatch, snapshot):
    calls = []

    def fake_fetch(*args, **kwargs):
        calls.append(True)
        return snapshot

    monkeypatch.setattr(control_plane_client, "fetch_config", fake_fetch)

    with pytest.raises(ValueError, match="Stockbit live configuration"):
        config.load_watch_config_for_run()

    assert calls == [True]


def test_load_watch_config_for_run_sanitizes_api_failure(live_settings, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic-token was included in transport diagnostics")

    monkeypatch.setattr(control_plane_client, "fetch_config", unavailable)

    with pytest.raises(ValueError, match="Stockbit live configuration") as error:
        config.load_watch_config_for_run()

    assert "synthetic-token" not in str(error.value)
