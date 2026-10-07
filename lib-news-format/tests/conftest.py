import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))


import pytest


@pytest.fixture(autouse=True)
def isolated_sectors(monkeypatch, tmp_path):
    """Tests never read a real Sectors key or touch the host coordination store."""
    import news_format

    news_format._sectors_library()  # puts the sibling client on sys.path
    empty = tmp_path / "lib-sectors"
    empty.mkdir()
    monkeypatch.setattr(news_format, "_sectors_library", lambda: empty)
    monkeypatch.setattr(news_format, "SECTORS_KEY_FILE", tmp_path / "missing-sectors.env")
    monkeypatch.setattr(news_format, "SECTORS_STORE_PATH", tmp_path / "store.sqlite3")
