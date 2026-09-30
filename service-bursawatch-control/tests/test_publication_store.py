from __future__ import annotations

from copy import deepcopy

import pytest

from control_plane.publication_store import MemoryPublicationStore, PublicationConflict
from test_publication_model import OWNER, publication


BOUNDARY = "2026-09-29T07:01:00+00:00"


def active_store() -> MemoryPublicationStore:
    store = MemoryPublicationStore()
    store.activate(BOUNDARY, (OWNER, "bursawatch-stockbit-snips"))
    return store


def test_same_key_same_digest_is_idempotent_and_changed_digest_conflicts():
    store = active_store()
    value = publication()
    first = store.accept(OWNER, value)
    assert store.accept(OWNER, deepcopy(value)) == first
    changed = deepcopy(value)
    changed["legs"][0]["text"] = "Changed output under the same key"
    with pytest.raises(PublicationConflict, match="digest"):
        store.accept(OWNER, changed)
    assert store.get(first["publication_id"])["versions"][0]["legs"][0]["text"] == "Exact synthetic rendered text"


def test_cutover_is_immutable_and_pre_boundary_delivery_is_rejected():
    store = MemoryPublicationStore()
    with pytest.raises(PublicationConflict, match="cutover"):
        store.accept(OWNER, publication())
    store.activate(BOUNDARY, (OWNER,))
    with pytest.raises(PublicationConflict, match="already"):
        store.activate(BOUNDARY, (OWNER,))
    with pytest.raises(ValueError, match="cutover"):
        store.accept(OWNER, publication(delivery_confirmed_at=BOUNDARY))
    with pytest.raises(ValueError, match="owner"):
        store.accept("bursawatch-stockbit-snips", publication())


def test_versions_require_contiguous_confirmed_edits():
    store = active_store()
    second = publication(version=2, supersedes_version=1)
    with pytest.raises(PublicationConflict, match="previous version"):
        store.accept(OWNER, second)
    first_ack = store.accept(OWNER, publication())
    second["legs"][0]["text"] = "Edited text confirmed by another receipt"
    second["legs"][0]["receipt_id"] = "987654321098765433"
    store.accept(OWNER, second)
    detail = store.get(first_ack["publication_id"])
    assert [row["version"] for row in detail["versions"]] == [1, 2]


def test_cursor_keeps_tied_delivery_timestamps_and_filters_before_advance():
    store = active_store()
    for number in range(5):
        value = publication(owner_key=f"synthetic:{number}")
        value["type"] = "macro_news" if number % 2 else "idx_company_news"
        value["route"] = "macro_news" if number % 2 else "id_stocks_news"
        store.accept(OWNER, value)
    expected = [row["publication_id"] for row in store.list_page(limit=10)["items"]]
    first = store.list_page(limit=2)
    second = store.list_page(limit=2, cursor=first["next_cursor"])
    third = store.list_page(limit=2, cursor=second["next_cursor"])
    assert [row["publication_id"] for row in first["items"] + second["items"] + third["items"]] == expected
    filtered = store.list_page(limit=1, filters={"type": "macro_news"})
    later = store.list_page(limit=1, filters={"type": "macro_news"}, cursor=filtered["next_cursor"])
    assert [row["type"] for row in filtered["items"] + later["items"]] == ["macro_news", "macro_news"]
    with pytest.raises(ValueError, match="cursor"):
        store.list_page(limit=1, filters={"type": "idx_company_news"}, cursor=filtered["next_cursor"])
