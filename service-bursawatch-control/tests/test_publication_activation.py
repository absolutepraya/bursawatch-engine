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


def test_add_owner_cli_requires_a_database_and_passes_the_reviewed_owner_and_boundary(monkeypatch):
    import add_publication_owner
    with pytest.raises(ValueError, match="DATABASE_URL"):
        add_publication_owner.add_owner("bursawatch-dc-morning-brief", "2026-10-08T00:00:00+00:00", "")
    seen = []
    class FakeStore:
        def __init__(self, dsn): assert dsn == "synthetic-dsn"
        def add_owner(self, owner_id, boundary): seen.append((owner_id, boundary))
    monkeypatch.setattr(add_publication_owner, "PostgresPublicationStore", FakeStore)
    add_publication_owner.add_owner("bursawatch-dc-morning-brief", "2026-10-08T00:00:00+00:00", "synthetic-dsn")
    assert seen == [("bursawatch-dc-morning-brief", "2026-10-08T00:00:00+00:00")]
    monkeypatch.setenv("DATABASE_URL", "")
    assert add_publication_owner.main(["--owner", "bursawatch-dc-morning-brief", "--boundary", "2026-10-08T00:00:00+00:00"]) == 1
