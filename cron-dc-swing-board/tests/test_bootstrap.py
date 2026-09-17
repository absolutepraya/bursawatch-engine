from datetime import datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace

import bootstrap
import board


WIB = bootstrap.WIB


def _call(
    ticker: str,
    kind: str,
    *,
    chart: bool = False,
    status: str | None = None,
    outcomes: tuple[str, ...] = (),
    targets: tuple[str, ...] = ("230", "240"),
):
    return SimpleNamespace(
        ticker=ticker,
        event_kind=kind,
        has_source_chart=chart,
        status=status,
        outcomes=outcomes,
        targets=targets,
    )


def _event(message_id: int, when: datetime, call) -> bootstrap.ParsedHistoryEvent:
    return bootstrap.ParsedHistoryEvent(message_id, when, call)


def test_build_candidates_reports_primary_and_orphan_status() -> None:
    when = datetime(2026, 9, 15, 9, 0, tzinfo=WIB)
    candidates = bootstrap.build_candidates(
        [
            _event(100, when, _call("SCMA", "BUY", chart=True)),
            _event(101, when + timedelta(hours=1), _call("SCMA", "STATUS", status="HOLD")),
            _event(200, when, _call("BBRI", "STATUS", status="HOLD")),
        ]
    )

    assert [candidate.ticker for candidate in candidates] == ["BBRI", "SCMA"]
    orphan, primary = candidates
    assert orphan.original_buy_message_id is None
    assert orphan.status_message_ids == (200,)
    assert orphan.missing_setup_reason == "original complete BUY setup not found in lookback"
    assert orphan.intended_forum_operation == "create historical source-only item"
    assert primary.original_buy_message_id == 100
    assert primary.status_message_ids == (101,)
    assert primary.chart_available is True
    assert primary.intended_forum_operation == "create Primary plan"


def test_build_candidates_skips_source_resolved_plan() -> None:
    when = datetime(2026, 9, 15, 9, 0, tzinfo=WIB)
    candidates = bootstrap.build_candidates(
        [
            _event(100, when, _call("SCMA", "BUY", targets=("230", "240"))),
            _event(
                101,
                when + timedelta(hours=1),
                _call("SCMA", "REMINDER", outcomes=("All targets achieved",)),
            ),
        ]
    )

    assert candidates[0].intended_forum_operation == "skip source-resolved plan"


def test_build_candidates_treats_sixth_target_as_terminal_for_six_target_plan() -> None:
    when = datetime(2026, 9, 15, 9, 0, tzinfo=WIB)
    candidates = bootstrap.build_candidates(
        [
            _event(100, when, _call("SCMA", "BUY", targets=("1", "2", "3", "4", "5", "6"))),
            _event(
                101,
                when + timedelta(hours=1),
                _call("SCMA", "REMINDER", outcomes=("Sixth target 6 achieved",), targets=()),
            ),
        ]
    )

    assert candidates[0].intended_forum_operation == "skip source-resolved plan"


def test_build_candidates_does_not_treat_target_price_as_target_number() -> None:
    when = datetime(2026, 9, 15, 9, 0, tzinfo=WIB)
    candidates = bootstrap.build_candidates(
        [
            _event(100, when, _call("SCMA", "BUY", targets=("3270", "3400"))),
            _event(
                101,
                when + timedelta(hours=1),
                _call("SCMA", "REMINDER", outcomes=("First target 3270 achieved",), targets=()),
            ),
        ]
    )

    assert candidates[0].intended_forum_operation == "create Primary plan"


def test_build_candidates_resolves_exact_final_target_value() -> None:
    when = datetime(2026, 9, 15, 9, 0, tzinfo=WIB)
    candidates = bootstrap.build_candidates(
        [
            _event(100, when, _call("SCMA", "BUY", targets=("3270", "3400"))),
            _event(
                101,
                when + timedelta(hours=1),
                _call("SCMA", "REMINDER", outcomes=("Target 3400 achieved",), targets=()),
            ),
        ]
    )

    assert candidates[0].intended_forum_operation == "skip source-resolved plan"


def test_primary_history_events_select_only_allowlisted_buy_and_later_statuses() -> None:
    when = datetime(2026, 9, 15, 9, 0, tzinfo=WIB)
    candidates = bootstrap.build_candidates(
        [
            _event(100, when, _call("SCMA", "BUY")),
            _event(101, when + timedelta(hours=1), _call("SCMA", "STATUS", status="HOLD")),
            _event(200, when, _call("BBRI", "STATUS", status="HOLD")),
        ]
    )

    selected = bootstrap._primary_history_events(candidates, [
        _event(100, when, _call("SCMA", "BUY")),
        _event(101, when + timedelta(hours=1), _call("SCMA", "STATUS", status="HOLD")),
        _event(200, when, _call("BBRI", "STATUS", status="HOLD")),
    ])

    assert [event.message_id for event in selected] == [100, 101]


class _FakeIterator:
    def __init__(self, messages):
        self.messages = iter(messages)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.messages)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _FakeClient:
    def __init__(self, messages):
        self.messages = messages

    def iter_messages(self, _entity, *, reverse):
        assert reverse is False
        return _FakeIterator(self.messages)


class _FakeWatcher:
    @staticmethod
    async def resolve_source(_client):
        return "phintraco"

    @staticmethod
    def parse_source_event(message):
        return getattr(message, "call", None)

    @staticmethod
    async def parse_reply_status_event(_client, _entity, _message):
        return None


class _ApplyWatcher(_FakeWatcher):
    @staticmethod
    def format_swing_alert(call, *, include_board=True):
        return f"formatted {call.ticker}; include_board={include_board}"

    @staticmethod
    def source_message_url(message_id):
        return f"https://t.me/phintraprofits/{message_id}"


class _ApplyEngine:
    def __init__(self):
        self.events = []

    def submit(self, event, _now):
        self.events.append(event)
        return "board_submitted"

    def drain(self, *, now, limit):
        assert now is not None
        assert limit == 100
        return 0


def _rich_call(ticker: str, kind: str, *, status: str | None = None):
    return SimpleNamespace(
        ticker=ticker,
        event_kind=kind,
        has_source_chart=False,
        status=status,
        outcomes=(),
        targets=(SimpleNamespace(value="230"), SimpleNamespace(value="240")),
        entry="208 to 212",
        stop_loss="<200",
        call_subtype="Trading Buy",
        signal_datetime=datetime(2026, 9, 15, 9, 0, tzinfo=WIB),
    )


def test_apply_primary_candidates_reuses_board_event_contract_without_source_only_items(tmp_path, monkeypatch) -> None:
    when = datetime(2026, 9, 15, 9, 0, tzinfo=WIB)
    messages = [
        SimpleNamespace(id=100, date=when, call=_rich_call("SCMA", "BUY")),
        SimpleNamespace(id=101, date=when + timedelta(hours=1), call=_rich_call("SCMA", "STATUS", status="HOLD")),
        SimpleNamespace(id=200, date=when, call=_rich_call("BBRI", "STATUS", status="HOLD")),
    ]
    engine = _ApplyEngine()
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_MEDIA_ROOT", str(tmp_path / "media"))

    import asyncio

    report = asyncio.run(
        bootstrap.apply_primary_candidates(
            now=when + timedelta(days=1),
            lookback_sessions=20,
            engine=engine,
            client=_FakeClient(messages),
            watcher_module=_ApplyWatcher,
        )
    )

    assert report["allowlist_count"] == 1
    assert report["selected_event_count"] == 2
    assert [event.kind for event in engine.events] == ["buy", "status"]
    assert [event.ticker for event in engine.events] == ["SCMA", "SCMA"]
    assert all(event.all_content.endswith("include_board=False") for event in engine.events)


def test_collect_report_reads_only_window_and_does_not_need_board_state() -> None:
    now = datetime(2026, 9, 19, 16, 0, tzinfo=WIB)
    messages = [
        SimpleNamespace(id=3, date=datetime(2026, 9, 19, 8, 0, tzinfo=WIB), call=_call("SCMA", "STATUS", status="HOLD")),
        SimpleNamespace(id=2, date=datetime(2026, 9, 18, 8, 0, tzinfo=WIB), call=_call("SCMA", "BUY")),
        SimpleNamespace(id=1, date=datetime(2026, 8, 1, 8, 0, tzinfo=WIB), call=_call("OLD", "BUY")),
    ]

    import asyncio

    report = asyncio.run(
        bootstrap.collect_report(
            now=now,
            lookback_sessions=1,
            client=_FakeClient(messages),
            watcher_module=_FakeWatcher,
        )
    )

    assert report["messages_scanned"] == 2
    assert report["parsed_events"] == 2
    assert report["candidate_count"] == 1
    assert report["candidates"][0]["original_buy_message_id"] == 2


def test_cli_bootstrap_dry_run_does_not_initialize_board_store(tmp_path, monkeypatch, capsys) -> None:
    state = tmp_path / "board.sqlite3"
    report = {
        "source_channel_id": 1444713822,
        "lookback_sessions": 20,
        "window_start": "2026-08-20T00:00:00+07:00",
        "window_end": "2026-09-19T16:00:00+07:00",
        "messages_scanned": 0,
        "parsed_events": 0,
        "candidate_count": 0,
        "candidates": [],
    }
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_STATE_PATH", str(state))
    async def fake_collect_report(**_):
        return report

    monkeypatch.setattr("bootstrap.collect_report", fake_collect_report)
    monkeypatch.setattr(board, "BoardStore", lambda *_: (_ for _ in ()).throw(AssertionError("state must not open")))

    assert board.main(["bootstrap", "--dry-run"]) == 0
    assert "IDX Swing board bootstrap dry-run" in capsys.readouterr().out
    assert not state.exists()


def test_manifest_selection_preserves_each_same_ticker_source_event() -> None:
    when = datetime(2026, 9, 15, 9, 0, tzinfo=WIB)
    manifest = (
        bootstrap.BootstrapManifestEvent(35149, "STATUS", "social", "all-1"),
        bootstrap.BootstrapManifestEvent(35172, "STATUS", "social", "all-2"),
    )
    selected = bootstrap._manifest_history_events(
        manifest,
        (
            _event(35149, when, _call("DSSA", "STATUS", status="On support")),
            _event(35172, when + timedelta(days=1), _call("DSSA", "STATUS", status="On track")),
        ),
    )

    assert [(item.source_message_id, event.message_id) for item, event in selected] == [
        (35149, 35149),
        (35172, 35172),
    ]


def test_manifest_source_only_conversion_never_invents_a_primary_plan() -> None:
    event = _event(
        35149,
        datetime(2026, 9, 15, 9, 0, tzinfo=WIB),
        _rich_call("DSSA", "STATUS", status="On support"),
    )
    item = bootstrap.BootstrapManifestEvent(35149, "STATUS", "social", "all-1")

    source_event = bootstrap._source_event_for_manifest(item, event, _ApplyWatcher)

    assert (source_event.kind, source_event.plan, source_event.ticker) == ("social", None, "DSSA")


def test_apply_manifest_submits_only_reviewed_events_without_ticker_collapsing(
    tmp_path, monkeypatch
) -> None:
    when = datetime(2026, 9, 15, 9, 0, tzinfo=WIB)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "source_channel_id": bootstrap.SOURCE_CHANNEL_ID,
                "events": [
                    {
                        "source_message_id": 35149,
                        "source_event_kind": "STATUS",
                        "board_kind": "social",
                        "target_all_message_id": "1547508884439306340",
                    },
                    {
                        "source_message_id": 35172,
                        "source_event_kind": "STATUS",
                        "board_kind": "social",
                        "target_all_message_id": "1547804915806511197",
                    },
                ],
            }
        )
    )
    messages = [
        SimpleNamespace(id=35149, date=when, call=_rich_call("DSSA", "STATUS", status="On support")),
        SimpleNamespace(id=35172, date=when + timedelta(days=1), call=_rich_call("DSSA", "STATUS", status="On track")),
        SimpleNamespace(id=35999, date=when + timedelta(days=1), call=_rich_call("OTHER", "STATUS", status="On support")),
    ]
    engine = _ApplyEngine()
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_MEDIA_ROOT", str(tmp_path / "media"))

    import asyncio

    report = asyncio.run(
        bootstrap.apply_manifest(
            now=when + timedelta(days=2),
            lookback_sessions=20,
            manifest_path=manifest_path,
            engine=engine,
            client=_FakeClient(messages),
            watcher_module=_ApplyWatcher,
        )
    )

    assert report["selected_event_count"] == 2
    assert [event.event_key for event in engine.events] == [
        "phintraco:1444713822:35149",
        "phintraco:1444713822:35172",
    ]
    assert [event.kind for event in engine.events] == ["social", "social"]
    assert [item["target_all_message_id"] for item in report["applied"]] == [
        "1547508884439306340",
        "1547804915806511197",
    ]


def test_manifest_dry_run_does_not_initialize_board_store(tmp_path, monkeypatch, capsys) -> None:
    state = tmp_path / "board.sqlite3"
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_STATE_PATH", str(state))

    async def fake_collect_manifest_report(**_):
        return {"manifest_events": [], "source_channel_id": 1444713822}

    monkeypatch.setattr("bootstrap.collect_manifest_report", fake_collect_manifest_report)
    monkeypatch.setattr(
        board,
        "BoardStore",
        lambda *_: (_ for _ in ()).throw(AssertionError("state must not open")),
    )

    assert board.main(["bootstrap", "--dry-run", "--manifest", str(manifest)]) == 0
    assert json.loads(capsys.readouterr().out)["source_channel_id"] == 1444713822
    assert not state.exists()


def test_reviewed_generic_link_manifest_preserves_all_target_messages() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "backfills"
        / "2026-09-17-generic-board-links-phintraco.json"
    )

    entries = bootstrap.load_manifest(path)

    assert [entry.source_message_id for entry in entries] == [
        34460,
        35095,
        35101,
        34499,
        35105,
        35134,
        35138,
        34800,
        35140,
        35149,
        35172,
        35197,
    ]
    assert entries[-1].board_kind == "social"
    assert [entry.target_all_message_id for entry in entries if entry.target_all_message_id] == [
        "1547070401920761879",
        "1547105477492482079",
        "1547136473281597450",
        "1547429179119640580",
        "1547432971814830130",
        "1547445575270531232",
        "1547508884439306340",
        "1547804915806511197",
        "1548881848602460171",
    ]
