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
SOURCE = {"Authorization": "Bearer " + "s" * 32}


def setup():
    catalog = MemoryCatalogStore()
    config = initial_config()
    config["publisher_defaults"] = [
        {"publisher_id": "phintraco", "capability_id": capability, "enabled": True, "settings": {}}
        for capability in ("company_news", "macro_news")
    ]
    catalog.put(1, config, "admin")
    inbox = MemoryInboxStore(catalog)
    api = TestClient(create_app(store=InMemoryStore(), catalog_store=catalog, inbox_store=inbox, auth=StaticTokenAuth(machine_token="machine-token", admin_token="admin-token", source_endpoint_tokens={"telegram:phintasprofits": "s" * 32})))
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
    claimed = api.post("/v1/source-work/claim?limit=2", headers=MACHINE, json={"pipeline_ids": ["company_news", "macro_news"]}).json()
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
    claimed = api.post("/v1/source-work/claim?limit=2", headers=MACHINE, json={"pipeline_ids": ["company_news", "macro_news"]}).json()
    item = next(x for x in claimed if x["work_key"] == wid)
    inbox.work[wid]["lease_until"] = "2020-01-01T00:00:00+00:00"
    renewed = api.post("/v1/source-work/claim?limit=2", headers=MACHINE, json={"pipeline_ids": ["company_news", "macro_news"]}).json()
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
    response = api.post(f"/v1/source-events/{receipt['event_key']}/versions", headers=ADMIN, json={"envelope": corrected, "kind": "correction", "revision_id": "edit-1", "reason": "provider edit"})
    assert response.status_code == 200 and len(response.json()["work_keys"]) == 2
    assert all(inbox.work[k]["catalog_revision"] == 2 for k in response.json()["work_keys"])
    tombstone = deepcopy(corrected)
    tombstone["payload"] = {}
    tombstone["content_hash"] = hashlib.sha256(b"deleted").hexdigest()
    assert api.post(f"/v1/source-events/{receipt['event_key']}/versions", headers=MACHINE, json={"envelope": tombstone, "kind": "tombstone", "revision_id": "delete-1", "reason": "deleted"}).status_code == 403
    assert api.post(f"/v1/source-events/{receipt['event_key']}/versions", headers=SOURCE, json={"envelope": tombstone, "kind": "tombstone", "revision_id": "delete-1", "reason": "deleted"}).json()["version"] == 3
    tombstone_reread = deepcopy(tombstone)
    tombstone_reread["observed_at"] = "2026-09-24T09:00:00+07:00"
    assert api.post(f"/v1/source-events/{receipt['event_key']}/versions", headers=SOURCE, json={"envelope": tombstone_reread, "kind": "tombstone", "revision_id": "delete-1", "reason": "retry"}).json()["duplicate"] is True
    assert api.post(f"/v1/source-events/{receipt['event_key']}/versions", headers=ADMIN, json={"envelope": corrected, "kind": "correction", "revision_id": "edit-1", "reason": "retry"}).json()["duplicate"] is True
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
        claimed = api.post("/v1/source-work/claim?limit=1", headers=MACHINE, json={"pipeline_ids": ["company_news"]}).json()[0]
        settled = api.post(f"/v1/source-work/{wid[0]}/settle", headers=MACHINE, json={"lease_token": claimed["lease_token"], "success": False, "error_code": "handler_failed"}).json()
        if attempt < 4:
            inbox.work[wid[0]]["available_at"] = "2020-01-01T00:00:00+00:00"
    assert settled["status"] == "dead_letter" and settled["attempts"] == 5
    assert api.get("/v1/source-work?status=dead_letter", headers=MACHINE).json()[0]["work_key"] == wid[0]


def test_revision_retry_identity_fences_old_work_and_rejects_conflicts():
    api, _catalog, inbox = setup()
    receipt = api.post("/v1/source-events", headers=SOURCE, json={"envelope": envelope()}).json()
    original = api.post("/v1/source-work/claim?limit=1", headers=MACHINE, json={"pipeline_ids": ["company_news"]}).json()[0]
    fence = f"/v1/source-work/{original['work_key']}/fence"
    assert api.post(fence, headers=MACHINE, json={"lease_token": original["lease_token"]}).json()["current"] is True
    edited = envelope()
    edited["content_hash"] = hashlib.sha256(b"edit-1").hexdigest()
    edited["payload"] = {"text": "edited"}
    path = f"/v1/source-events/{receipt['event_key']}/versions"
    body = {"envelope": edited, "kind": "correction", "revision_id": "provider-edit-17", "reason": "provider edit"}
    first = api.post(path, headers=SOURCE, json=body).json()
    assert first["version"] == 2 and first["duplicate"] is False
    reread = deepcopy(body)
    reread["envelope"]["observed_at"] = "2026-09-24T08:00:00+07:00"
    second = api.post(path, headers=SOURCE, json=reread).json()
    assert (second["version"], second["duplicate"], second["work_keys"]) == (2, True, first["work_keys"])
    assert len(inbox.events[receipt["event_key"]]["versions"]) == 2
    assert inbox.work[original["work_key"]]["status"] == "superseded"
    assert api.post(fence, headers=MACHINE, json={"lease_token": original["lease_token"]}).json()["current"] is False
    assert api.post(f"/v1/source-work/{original['work_key']}/settle", headers=MACHINE, json={"lease_token": original["lease_token"], "success": True}).status_code == 409
    assert api.post("/v1/source-work/claim", headers=MACHINE, json={"pipeline_ids": ["company_news"]}).json()[0]["version"] == 2
    conflict = deepcopy(body)
    conflict["envelope"]["content_hash"] = hashlib.sha256(b"different").hexdigest()
    assert api.post(path, headers=SOURCE, json=conflict).status_code == 409


def test_claim_pipeline_filter_and_source_machine_authorization():
    api, _catalog, _inbox = setup()
    wrong = envelope()
    wrong["endpoint_id"] = "telegram:phintraprofits"
    assert api.post("/v1/source-events", headers=SOURCE, json={"envelope": wrong}).status_code == 403
    receipt = api.post("/v1/source-events", headers=SOURCE, json={"envelope": envelope()}).json()
    assert api.post("/v1/source-work/claim", headers=SOURCE, json={"pipeline_ids": ["company_news"]}).status_code == 403
    assert api.post("/v1/source-work/claim", headers=MACHINE, json={"pipeline_ids": []}).status_code == 422
    assert api.post("/v1/source-work/claim", headers=MACHINE, json={"pipeline_ids": ["stockbit_snips"]}).json() == []
    claimed = api.post("/v1/source-work/claim", headers=MACHINE, json={"pipeline_ids": ["macro_news"]}).json()
    assert len(claimed) == 1 and claimed[0]["pipeline_id"] == "macro_news"
    edited = envelope()
    edited["payload"] = {"text": "edited"}
    edited["content_hash"] = hashlib.sha256(b"edited").hexdigest()
    wrong_endpoint = deepcopy(edited)
    wrong_endpoint["endpoint_id"] = "telegram:phintraprofits"
    path = f"/v1/source-events/{receipt['event_key']}/versions"
    assert api.post(path, headers=SOURCE, json={"envelope": wrong_endpoint, "kind": "correction", "revision_id": "edit-2", "reason": "edit"}).status_code == 403
    assert api.post(path, headers=MACHINE, json={"envelope": edited, "kind": "correction", "revision_id": "edit-2", "reason": "edit"}).status_code == 403
    assert api.post(path, headers=SOURCE, json={"envelope": edited, "kind": "correction", "revision_id": "edit-2", "reason": "edit"}).status_code == 200
