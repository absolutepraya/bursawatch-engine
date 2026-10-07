from __future__ import annotations

import sys
from pathlib import Path


BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

CONTROL_PLANE_BIN = Path(__file__).resolve().parents[2] / "lib-bursawatch-control" / "bin"
if str(CONTROL_PLANE_BIN) not in sys.path:
    sys.path.insert(0, str(CONTROL_PLANE_BIN))


import pytest


@pytest.fixture(autouse=True)
def no_network_company_context(monkeypatch):
    import scan

    monkeypatch.setattr(scan, "get_company_context", lambda ticker, route: None)
