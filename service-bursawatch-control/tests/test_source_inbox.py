from __future__ import annotations

from copy import deepcopy
import hashlib

from fastapi.testclient import TestClient

from control_plane.api import create_app
from control_plane.auth import StaticTokenAuth
from control_plane.source_catalog import MemoryCatalogStore, initial_config
from control_plane.source_inbox import MemoryInboxStore
from control_plane.store import InMemoryStore

MACHINE = {"Authorization": "Bearer machine-token"}
ADMIN = {"Authorization": "Bearer admin-token"}


def setup():
    catalog = MemoryCatalogStore()
    config = initial_config()
    config["publisher_defaults"] = [
        {"publisher_id": "phintraco", "capability_id": capability, "enabled": True, "settings": {}}
        for capability in ("company_news", "macro_news")
    ]
    catalog.put(1, config, "admin")
    inbox = MemoryInboxStore(catalog)
    api = TestClient(create_app(store=InMemoryStore(), catalog_store=catalog, inbox_store=inbox, auth=StaticTokenAuth(machine_token="machine-token", admin_token="admin-token")))
    return api, catalog, inbox


def envelope(provider="42"):
    return {"version": 1, "endpoint_id": "telegram:phintasprofits", "publisher_id": "phintraco", "platform": "telegram", "provider_event_id": provider, "published_at": "2026-09-24T07:00:00+07:00", "observed_at": "2026-09-24T07:01:00+07:00", "source_url": "https://t.me/phintasprofits/42", "parser_version": "parser-1", "content_hash": hashlib.sha256(b"content").hexdigest(), "payload": {"text": "source"}, "media_refs": [], "media_required": False}


def test_atomic_acceptance_duplicate_and_independent_work_with_snapshot_retry():
    api, catalog, inbox = setup()
    first = api.post("/v1/source-events", headers=MACHINE, json={"envelope": envelope()})
    assert first.status_code == 200
    receipt = first.json()
    assert len(receipt["work_keys"]) == 2
    assert api.post("/v1/source-events", headers=MACHINE, json={"envelope": envelope()}).json()["duplicate"] is True
    reread = envelope()
    reread["observed_at"] = "2026-09-24T07:05:00+07:00"
    assert api.post("/v1/source-events", headers=MACHINE, json={"envelope": reread}).json()["duplicate"] is True
    assert len(inbox.work) == 2
    claimed = api.post("/v1/source-work/claim?limit=2", headers=MACHINE).json()
    assert len(claimed) == 2
    assert all(x["catalog_revision"] == 2 and x["capability_version"] == 1 for x in claimed)
    assert claimed[0]["effect_key"] == claimed[0]["work_key"]
    changed = initial_config()
    catalog.put(2, changed, "admin")
    failed = api.post(f"/v1/source-work/{claimed[0]['work_key']}/settle", headers=MACHINE, json={"lease_token": claimed[0]["lease_token"], "success": False, "error_code": "handler_failed"})
    assert failed.status_code == 200 and failed.json()["status"] == "pending"
    assert failed.json()["catalog_revision"] == 2
    succeeded = api.post(f"/v1/source-work/{claimed[1]['work_key']}/settle", headers=MACHINE, json={"lease_token": claimed[1]["lease_token"], "success": True})
    assert succeeded.json()["status"] == "done"
    assert api.post("/v1/source-events", headers=MACHINE, json={"envelope": envelope("43")}).json()["work_keys"] == []
    assert api.get(f"/v1/source-events/{receipt['event_key']}", headers=MACHINE).status_code == 200


def test_lease_expiry_suppression_replay_and_authorization():
    api, _catalog, inbox = setup()
    wid = api.post("/v1/source-events", headers=MACHINE, json={"envelope": envelope()}).json()["work_keys"][0]
    claimed = api.post("/v1/source-work/claim?limit=2", headers=MACHINE).json()
    item = next(x for x in claimed if x["work_key"] == wid)
    inbox.work[wid]["lease_until"] = "2020-01-01T00:00:00+00:00"
    renewed = api.post("/v1/source-work/claim?limit=2", headers=MACHINE).json()
    new_item = next(x for x in renewed if x["work_key"] == wid)
    assert new_item["lease_token"] != item["lease_token"]
    assert api.post(f"/v1/source-work/{wid}/settle", headers=MACHINE, json={"lease_token": item["lease_token"], "success": True}).status_code == 409
    inbox.work[wid].update(status="dead_letter", lease_token=None, lease_until=None)
    assert api.post(f"/v1/source-work/{wid}/replay", headers=MACHINE, json={"reason": "reviewed"}).status_code == 403
    assert api.post(f"/v1/source-work/{wid}/replay", headers=ADMIN, json={"reason": "reviewed"}).json()["status"] == "pending"
    assert api.post(f"/v1/source-work/{wid}/suppress", headers=ADMIN, json={"reason": "operator decision"}).json()["status"] == "suppressed"
    assert [entry["action"] for entry in inbox.audit] == ["replay", "suppress"]


def test_correction_tombstone_and_media_fail_closed():
    api, catalog, inbox = setup()
    receipt = api.post("/v1/source-events", headers=MACHINE, json={"envelope": envelope()}).json()
    catalog.put(2, initial_config(), "admin")
    corrected = envelope()
    corrected["content_hash"] = hashlib.sha256(b"corrected").hexdigest()
    corrected["payload"] = {"text": "corrected"}
    response = api.post(f"/v1/source-events/{receipt['event_key']}/versions", headers=ADMIN, json={"envelope": corrected, "kind": "correction", "reason": "provider edit"})
    assert response.status_code == 200 and len(response.json()["work_keys"]) == 2
    assert all(inbox.work[k]["catalog_revision"] == 2 for k in response.json()["work_keys"])
    tombstone = deepcopy(corrected)
    tombstone["payload"] = {}
    tombstone["content_hash"] = hashlib.sha256(b"deleted").hexdigest()
    assert api.post(f"/v1/source-events/{receipt['event_key']}/versions", headers=MACHINE, json={"envelope": tombstone, "kind": "tombstone", "reason": "deleted"}).status_code == 403
    assert api.post(f"/v1/source-events/{receipt['event_key']}/versions", headers=ADMIN, json={"envelope": tombstone, "kind": "tombstone", "reason": "deleted"}).json()["version"] == 3
    assert api.post(f"/v1/source-events/{receipt['event_key']}/versions", headers=ADMIN, json={"envelope": corrected, "kind": "correction", "reason": "restore"}).status_code == 409
    media = envelope("media")
    media["media_required"] = True
    assert api.post("/v1/source-events", headers=MACHINE, json={"envelope": media}).status_code == 422
    assert len(inbox.events) == 1


def test_override_resolution_and_bounded_dead_letter():
    api, catalog, inbox = setup()
    config = deepcopy(catalog.get()["config"])
    config["endpoint_overrides"] = [{"endpoint_id": "telegram:phintasprofits", "capability_id": "macro_news", "enabled": False, "settings": {}}]
    catalog.put(2, config, "admin")
    wid = api.post("/v1/source-events", headers=MACHINE, json={"envelope": envelope()}).json()["work_keys"]
    assert len(wid) == 1
    item = inbox.work[wid[0]]
    assert item["catalog_revision"] == 3 and item["config_source"] == "publisher_default"
    assert api.get("/v1/source-work?status=pending", headers=MACHINE).json()[0]["work_key"] == wid[0]
    for attempt in range(5):
        claimed = api.post("/v1/source-work/claim?limit=1", headers=MACHINE).json()[0]
        settled = api.post(f"/v1/source-work/{wid[0]}/settle", headers=MACHINE, json={"lease_token": claimed["lease_token"], "success": False, "error_code": "handler_failed"}).json()
        if attempt < 4:
            inbox.work[wid[0]]["available_at"] = "2020-01-01T00:00:00+00:00"
    assert settled["status"] == "dead_letter" and settled["attempts"] == 5
    assert api.get("/v1/source-work?status=dead_letter", headers=MACHINE).json()[0]["work_key"] == wid[0]
