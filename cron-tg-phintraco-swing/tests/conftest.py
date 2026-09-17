import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
sys.path.insert(0, str(ROOT.parent / "lib-swing-format" / "bin"))
sys.path.insert(0, str(ROOT.parent / "lib-telegram-resilience" / "bin"))


@pytest.fixture
def tmp_state(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    monkeypatch.setenv("IDX_SWING_WATCH_PHINTRACO_DAILY_STATE_PATH", str(path))
    return path
