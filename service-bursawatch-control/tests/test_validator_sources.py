from __future__ import annotations

from pathlib import Path

from control_plane.baselines import BASELINE_FILES, load_baselines
from control_plane.validators import validators_from_directories


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_SOURCES = ROOT / "validator-sources"
SOURCE_FILES = {
    "bursawatch-dc-morning-brief": ["cron-dc-morning-brief/bin/morning_brief/config.py"],
    "bursawatch-x-account-watch": [
        "cron-x-account-watch/bin/config.py",
        "cron-x-account-watch/bin/models.py",
    ],
    "bursawatch-ig-account-watch": [
        "cron-ig-account-watch/bin/config.py",
        "cron-ig-account-watch/bin/models.py",
    ],
    "bursawatch-wa-channel-watch": [
        "cron-wa-channel-watch/bin/config.py",
        "cron-wa-channel-watch/bin/models.py",
    ],
    "bursawatch-tg-market-news": ["cron-tg-market-news/bin/config.py"],
    "bursawatch-dc-swing-board": ["cron-dc-swing-board/bin/config.py"],
    "bursawatch-tg-phintraco-swing": ["cron-tg-phintraco-swing/bin/config.py"],
    "bursawatch-tg-kelas-investasi-gtw": ["cron-tg-kelas-investasi-gtw/bin/config.py"],
    "bursawatch-stockbit-snips": [
        "cron-stockbit-snips/bin/config.py",
        "cron-stockbit-snips/bin/models.py",
    ],
}


def test_validator_source_bundle_is_exactly_the_reviewed_watcher_set():
    assert set(SOURCE_FILES) == set(BASELINE_FILES)
    assert {path.name for path in VALIDATOR_SOURCES.iterdir() if path.is_dir()} == set(SOURCE_FILES)


def test_validator_source_files_match_their_cron_source_exactly():
    for watcher_id, source_paths in SOURCE_FILES.items():
        for source_path in source_paths:
            source = ROOT.parent / source_path
            bundled = VALIDATOR_SOURCES / watcher_id / source.name
            assert bundled.read_bytes() == source.read_bytes()


def test_self_contained_validator_bundle_accepts_every_reviewed_baseline():
    validators = validators_from_directories(
        {watcher_id: VALIDATOR_SOURCES / watcher_id for watcher_id in sorted(SOURCE_FILES)}
    )

    for baseline in load_baselines(ROOT / "baseline-configs"):
        validators[baseline.watcher_id](baseline.config)
