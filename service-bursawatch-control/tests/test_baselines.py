from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from control_plane.baselines import BASELINE_FILES, BaselineSeedError, load_baselines, seed_baselines


ROOT = Path(__file__).resolve().parents[1]
BASELINES = ROOT / "baseline-configs"


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self.row: tuple[int | None] | tuple[int] | None = None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        normalized = " ".join(sql.split())
        if normalized.startswith("select current_revision"):
            assert params is not None
            watcher_id = str(params[0])
            if watcher_id not in self.connection.current_revisions:
                self.row = None
            else:
                self.row = (self.connection.current_revisions[watcher_id],)
        elif normalized.startswith("select count(*)"):
            assert params is not None
            self.row = (self.connection.revision_counts[str(params[0])],)
        elif normalized.startswith("insert into bursawatch_config_revisions"):
            assert params is not None
            watcher_id = str(params[0])
            self.connection.revision_counts[watcher_id] += 1
        elif normalized.startswith("update bursawatch_watchers"):
            assert params is not None
            self.connection.current_revisions[str(params[0])] = 1

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self) -> None:
        self.current_revisions = {watcher_id: None for watcher_id in BASELINE_FILES}
        self.revision_counts = {watcher_id: 0 for watcher_id in BASELINE_FILES}
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    @contextmanager
    def transaction(self):
        yield

    def close(self) -> None:
        self.closed = True


def test_checked_in_baselines_are_exactly_the_reviewed_watcher_set():
    baselines = load_baselines(BASELINES)

    assert [baseline.watcher_id for baseline in baselines] == sorted(BASELINE_FILES)
    assert len(baselines) == 9
    assert all(len(baseline.config_sha256) == 64 for baseline in baselines)


def test_baseline_loader_refuses_missing_or_extra_files(tmp_path: Path):
    missing = tmp_path / "missing"
    shutil.copytree(BASELINES, missing)
    (missing / BASELINE_FILES["bursawatch-x-account-watch"]).unlink()

    with pytest.raises(BaselineSeedError, match="do not match"):
        load_baselines(missing)

    extra = tmp_path / "extra"
    shutil.copytree(BASELINES, extra)
    (extra / "unreviewed.json").write_text('{"version": 1}', encoding="utf-8")

    with pytest.raises(BaselineSeedError, match="do not match"):
        load_baselines(extra)


def test_seed_baselines_never_overwrites_an_active_revision():
    connection = FakeConnection()

    first = seed_baselines(
        "postgresql://example",
        BASELINES,
        connect=lambda _dsn: connection,
        json_value=lambda value: value,
    )

    assert first == [f"seeded: {watcher_id}" for watcher_id in sorted(BASELINE_FILES)]
    assert connection.current_revisions == {watcher_id: 1 for watcher_id in BASELINE_FILES}
    assert connection.closed is True

    connection.closed = False
    second = seed_baselines(
        "postgresql://example",
        BASELINES,
        connect=lambda _dsn: connection,
        json_value=lambda value: value,
    )

    assert second == [f"already configured: {watcher_id}" for watcher_id in sorted(BASELINE_FILES)]
    assert connection.closed is True


def test_second_seed_keeps_existing_stockbit_operator_revision():
    connection = FakeConnection()
    stockbit = "bursawatch-stockbit-snips"
    seed_baselines(
        "postgresql://example",
        BASELINES,
        connect=lambda _dsn: connection,
        json_value=lambda value: value,
    )
    connection.current_revisions[stockbit] = 7
    connection.revision_counts[stockbit] = 7

    outcomes = seed_baselines(
        "postgresql://example",
        BASELINES,
        connect=lambda _dsn: connection,
        json_value=lambda value: value,
    )

    assert f"already configured: {stockbit}" in outcomes
    assert connection.current_revisions[stockbit] == 7
    assert connection.revision_counts[stockbit] == 7


def test_stockbit_baseline_matches_source_defaults_and_validates():
    baseline_path = BASELINES / "bursawatch-stockbit-snips.json"
    config_source = ROOT.parent / "cron-stockbit-snips/bin"
    source = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import config, json; print(json.dumps({'version': config.CONFIG_VERSION, 'feeds': [{'id': feed.lane.value, 'enabled': True} for feed in config.FEEDS], 'destinations': {'id_stocks_news_channel_id': config.ID_STOCKS_NEWS_CHANNEL_ID, 'macro_news_channel_id': config.MACRO_NEWS_CHANNEL_ID}, 'additional_prompt_instruction': ''}, sort_keys=True))",
        ],
        cwd=config_source,
        text=True,
    )

    assert json.loads(source) == json.loads(baseline_path.read_text(encoding="utf-8"))
    _validate_with_source(config_source, baseline_path, "load_watch_config_data")


def test_seed_baselines_refuses_inconsistent_history():
    connection = FakeConnection()
    connection.revision_counts["bursawatch-x-account-watch"] = 1

    with pytest.raises(BaselineSeedError, match="configuration history"):
        seed_baselines(
            "postgresql://example",
            BASELINES,
            connect=lambda _dsn: connection,
            json_value=lambda value: value,
        )


@pytest.mark.parametrize(
    ("file_name", "package", "default_attribute", "validator"),
    [
        ("bursawatch-tg-market-news.json", "cron-tg-market-news", "_DEFAULT", "load_watch_config_data"),
        ("bursawatch-tg-phintraco-swing.json", "cron-tg-phintraco-swing", "_DEFAULT_CONFIG_DATA", "load_watch_config_data"),
        ("bursawatch-tg-kelas-investasi-gtw.json", "cron-tg-kelas-investasi-gtw", "_DEFAULT_CONFIG_DATA", "load_watch_config_data"),
        ("bursawatch-dc-swing-board.json", "cron-dc-swing-board", "_DEFAULT_CONFIG_DATA", "load_board_config_data"),
    ],
)
def test_default_baselines_match_and_validate_against_their_source(
    file_name: str, package: str, default_attribute: str, validator: str
):
    config_source = ROOT.parent / package / "bin"
    source = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import config, json, sys; print(json.dumps(getattr(config, sys.argv[1]), sort_keys=True))",
            default_attribute,
        ],
        cwd=config_source,
        text=True,
    )

    assert json.loads(source) == json.loads((BASELINES / file_name).read_text(encoding="utf-8"))
    _validate_with_source(config_source, BASELINES / file_name, validator)


@pytest.mark.parametrize(
    ("file_name", "source_path", "package", "validator"),
    [
        ("bursawatch-x-account-watch.json", "cron-x-account-watch/config/watches.json", "cron-x-account-watch", "load_watch_config_data"),
        ("bursawatch-ig-account-watch.json", "cron-ig-account-watch/config/watches.json", "cron-ig-account-watch", "load_watch_config_data"),
        ("bursawatch-wa-channel-watch.json", "cron-wa-channel-watch/config/watches.json", "cron-wa-channel-watch", "load_data"),
    ],
)
def test_static_json_baselines_match_their_source(
    file_name: str, source_path: str, package: str, validator: str
):
    assert json.loads((BASELINES / file_name).read_text(encoding="utf-8")) == json.loads(
        (ROOT.parent / source_path).read_text(encoding="utf-8")
    )
    _validate_with_source(ROOT.parent / package / "bin", BASELINES / file_name, validator)


def test_whatsapp_channel_baseline_lists_the_reviewed_profile_lifecycle():
    payload = json.loads(
        (BASELINES / "bursawatch-wa-channel-watch.json").read_text(encoding="utf-8")
    )

    assert payload["version"] == 2
    assert [(profile["id"], profile["mode"]) for profile in payload["profiles"]] == [
        ("bri-danareksa-sekuritas", "forward"),
        ("ins", "observe"),
        ("samuel-sekuritas-indonesia", "observe"),
    ]


def _validate_with_source(config_source: Path, baseline_path: Path, validator: str) -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import config, json, sys; from pathlib import Path; getattr(config, sys.argv[2])(json.loads(Path(sys.argv[1]).read_text()))",
            str(baseline_path),
            validator,
        ],
        cwd=config_source,
        check=True,
    )
