from __future__ import annotations

from pathlib import Path
import os
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = ROOT / "bin"
sys.path.insert(0, str(BIN_DIR))
sys.path.insert(0, str(ROOT.parent / "telegram-resilience" / "bin"))


@pytest.fixture
def tmp_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("IDX_SSF_WATCH_PHINTRACO_WEEKLY_STATE_PATH", os.fspath(state_path))
    return state_path
