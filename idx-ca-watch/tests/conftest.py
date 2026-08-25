import sys
from pathlib import Path
import pytest

BIN = Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))


@pytest.fixture
def tmp_state(tmp_path, monkeypatch):
    p = tmp_path / "state.json"
    monkeypatch.setenv("IDX_CA_STATE_PATH", str(p))
    return p
