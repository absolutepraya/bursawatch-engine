from __future__ import annotations

import pytest

import activate_publication_feed
from control_plane.publication_model import OWNER_ROUTES
from control_plane.publication_store import MemoryPublicationStore, PublicationConflict


def test_activation_is_immutable_and_uses_fixed_owner_set():
    store = MemoryPublicationStore()
    boundary = "2026-09-29T07:01:00+00:00"
    store.activate(boundary, tuple(OWNER_ROUTES))
    assert set(store.cutover()["owner_ids"]) == set(OWNER_ROUTES)
    with pytest.raises(PublicationConflict, match="already"):
        store.activate(boundary, tuple(OWNER_ROUTES))


def test_activation_cli_rejects_missing_database_and_invalid_boundary(monkeypatch):
    with pytest.raises(ValueError, match="DATABASE_URL"):
        activate_publication_feed.activate("2026-09-29T07:01:00+00:00", "")
    class FakeStore:
        def __init__(self, dsn):
            assert dsn == "synthetic-dsn"

        def activate(self, boundary, owner_ids):
            assert owner_ids == tuple(OWNER_ROUTES)
            assert boundary == "2026-09-29T07:01:00+00:00"

    monkeypatch.setattr(activate_publication_feed, "PostgresPublicationStore", FakeStore)
    activate_publication_feed.activate("2026-09-29T07:01:00+00:00", "synthetic-dsn")
