from __future__ import annotations

import pytest

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib-bursawatch-control" / "bin"))


@pytest.fixture(autouse=True)
def isolated_news_quotes(monkeypatch):
    import render
    monkeypatch.setattr(render.news_format, "get_market_snapshot", lambda *args: None)
