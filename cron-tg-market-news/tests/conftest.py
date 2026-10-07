from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest



BIN_DIRECTORY = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN_DIRECTORY))
sys.path.insert(0, str(BIN_DIRECTORY.parent.parent / "lib-telegram-resilience" / "bin"))
from domain import CompanyCandidate, Provider, SourceKind


@pytest.fixture(autouse=True)
def no_network_market_data(monkeypatch):
    import delivery

    monkeypatch.setattr(delivery, "get_market_snapshot", lambda ticker, source_text: None)
    monkeypatch.setattr(delivery, "get_company_context", lambda ticker, route: None)

@pytest.fixture
def load_fixture():
    fixtures_directory = Path(__file__).resolve().parent / "fixtures"

    def load(name: str) -> str:
        return (fixtures_directory / name).read_text(encoding="utf-8")

    return load

@pytest.fixture
def tmp_state(tmp_path):
    return tmp_path / "state.json"


@pytest.fixture
def candidate():
    return CompanyCandidate(
        provider=Provider.TUNTUN,
        source_message_id=13597,
        ticker="DEWA",
        source_kind=SourceKind.CORPORATE_ENTRY,
        published_at=datetime(2026, 7, 14, 1, 0, tzinfo=timezone.utc),
        source_text="DEWA (Darma Henwa): kontrak Rp22 triliun.",
        direct_image=False,
    )


@pytest.fixture
def later_candidate():
    return CompanyCandidate(
        provider=Provider.PHINTRACO,
        source_message_id=13598,
        ticker="INCO",
        source_kind=SourceKind.PHINTRACO_NOTE,
        published_at=datetime(2026, 7, 14, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=1),
        source_text="INCO: operational update.",
        direct_image=False,
    )
