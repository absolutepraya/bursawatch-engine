from __future__ import annotations

from copy import deepcopy
import hashlib

from fastapi.testclient import TestClient

from control_plane.api import create_app
from control_plane.auth import StaticTokenAuth
from control_plane.source_catalog import MemoryCatalogStore, initial_config
from control_plane.source_inbox import InboxConflict, MemoryInboxStore
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


def kelas_envelope(provider: str):
    result = envelope(provider)
    result.update(endpoint_id="telegram:kelasinvestasiid", publisher_id="kelas-investasi")
    result["source_url"] = f"https://t.me/kelasinvestasiid/{provider}"
    return result


def x_envelope(provider="42"):
    result = envelope(provider)
    result.update(endpoint_id="x:writingtorch", publisher_id="x-writingtorch", platform="x", source_url=f"https://x.com/writingtorch/status/{provider}")
    return result


def test_x_subscriptions_share_one_frozen_route_group():
    catalog = MemoryCatalogStore()
    config = initial_config()
    config["endpoint_overrides"] = [
        {"endpoint_id": "x:writingtorch", "capability_id": capability, "enabled": True, "settings": {}}
        for capability in ("company_news", "macro_news", "swing_chart_context")
    ]
    catalog.put(1, config, "test")
    inbox = MemoryInboxStore(catalog)
    receipt = inbox.accept(x_envelope())
    assert len(receipt["work_keys"]) == 1
    work = inbox.claim(["x_post_route"], limit=10)
    assert len(work) == 1
    assert work[0]["capability_id"] == "x_post_route_group"
    assert work[0]["capability_version"] == 1
    assert work[0]["settings"] == {}
    assert work[0]["catalog_revision"] == 2
    assert work[0]["dispatch_context"] == {
        "dispatch_group": "x_post_route",
        "subscriptions": [
            {"capability_id": capability, "capability_version": 1, "settings": {}, "config_source": "endpoint_override"}
            for capability in ("company_news", "macro_news", "swing_chart_context")
        ],
    }
    config["endpoint_overrides"] = []
    catalog.put(2, config, "test")
    assert inbox.begin(work[0]["work_key"], work[0]["lease_token"]) is True
    inbox.settle(work[0]["work_key"], work[0]["lease_token"], success=True)
    corrected = x_envelope()
    corrected["content_hash"] = hashlib.sha256(b"updated").hexdigest()
    corrected["payload"] = {"text": "updated"}
    revision = inbox.revise(receipt["event_key"], corrected, "correction", "edit-1", "test", "edit")
    assert inbox.work[revision["work_keys"][0]]["dispatch_context"] == work[0]["dispatch_context"]
    tombstone = deepcopy(corrected)
    tombstone["payload"] = {}
    tombstone["content_hash"] = hashlib.sha256(b"deleted").hexdigest()
    deletion = inbox.revise(receipt["event_key"], tombstone, "tombstone", "delete-1", "test", "delete")
    assert inbox.work[deletion["work_keys"][0]]["dispatch_context"] == work[0]["dispatch_context"]


def test_one_enabled_x_capability_creates_one_group_work():
    catalog = MemoryCatalogStore()
    config = initial_config()
    config["publisher_defaults"] = [{"publisher_id": "x-writingtorch", "capability_id": "swing_chart_context", "enabled": True, "settings": {}}]
    catalog.put(1, config, "test")
    inbox = MemoryInboxStore(catalog)
    receipt = inbox.accept(x_envelope())
    assert len(receipt["work_keys"]) == 1
    item = inbox.claim(["x_post_route"])[0]
    assert item["dispatch_context"]["subscriptions"] == [{"capability_id": "swing_chart_context", "capability_version": 1, "settings": {}, "config_source": "publisher_default"}]
    assert item["config_source"] == "publisher_default"


def test_x_group_keeps_each_setting_source_and_uses_override_precedence():
    catalog = MemoryCatalogStore()
    config = initial_config()
    config["publisher_defaults"] = [
        {"publisher_id": "x-writingtorch", "capability_id": capability, "enabled": True, "settings": {}}
        for capability in ("company_news", "macro_news")
    ]
    config["endpoint_overrides"] = [{"endpoint_id": "x:writingtorch", "capability_id": "company_news", "enabled": True, "settings": {}}]
    catalog.put(1, config, "test")
    inbox = MemoryInboxStore(catalog)
    receipt = inbox.accept(x_envelope("mixed"))
    assert len(receipt["work_keys"]) == 1
    item = inbox.claim(["x_post_route"])[0]
    assert item["config_source"] == "endpoint_override"
    assert [(sub["capability_id"], sub["config_source"]) for sub in item["dispatch_context"]["subscriptions"]] == [
        ("company_news", "endpoint_override"), ("macro_news", "publisher_default")
    ]


def test_unrelated_enabled_subscriptions_remain_independent():
    api, _, inbox = setup()
    receipt = inbox.accept(envelope("independent"))
    assert len(receipt["work_keys"]) == 2
    items = inbox.claim(["company_news", "macro_news"])
    assert {item["pipeline_id"] for item in items} == {"company_news", "macro_news"}
    assert all(item["dispatch_context"] == {} for item in items)


def test_legacy_x_work_remains_claimable_by_its_original_pipeline():
    catalog = MemoryCatalogStore()
    inbox = MemoryInboxStore(catalog)
    receipt = inbox.accept(x_envelope("legacy"))
    for capability in ("company_news", "macro_news"):
        inbox._create_work(receipt["event_key"], 1, {
            "capability_id": capability, "pipeline": capability, "capability_version": 1,
            "catalog_revision": 1, "settings": {}, "config_source": "publisher_default", "dispatch_context": {},
        })
    claimed = inbox.claim(["company_news", "macro_news"])
    assert {item["pipeline_id"] for item in claimed} == {"company_news", "macro_news"}


def setup_kelas():
    api, catalog, _inbox = setup()
    config = catalog.get()["config"]
    config["publisher_defaults"] = [
        {"publisher_id": "kelas-investasi", "capability_id": "swing_support", "enabled": True, "settings": {}}
    ]
    catalog.put(2, config, "admin")
    return api


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
    assert api.post(f"/v1/source-work/{claimed[1]['work_key']}/begin", headers=MACHINE, json={"lease_token": claimed[1]["lease_token"]}).json()["begun"] is True
    succeeded = api.post(f"/v1/source-work/{claimed[1]['work_key']}/settle", headers=MACHINE, json={"lease_token": claimed[1]["lease_token"], "success": True})
    assert succeeded.json()["status"] == "done"
    assert api.post("/v1/source-events", headers=MACHINE, json={"envelope": envelope("43")}).json()["work_keys"] == []
    assert api.get(f"/v1/source-events/{receipt['event_key']}", headers=MACHINE).status_code == 200


def test_kelas_claim_order_is_source_message_order_and_later_work_waits_on_retry():
    api = setup_kelas()
    later = api.post("/v1/source-events", headers=MACHINE, json={"envelope": kelas_envelope("103")}).json()
    earlier = api.post("/v1/source-events", headers=MACHINE, json={"envelope": kelas_envelope("101")}).json()

    first = api.post("/v1/source-work/claim?limit=20", headers=MACHINE, json={"pipeline_ids": ["swing_support"]}).json()
    assert len(first) == 1
    assert first[0]["event_key"] == earlier["event_key"]
    failed = api.post(
        f"/v1/source-work/{first[0]['work_key']}/settle",
        headers=MACHINE,
        json={"lease_token": first[0]["lease_token"], "success": False, "error_code": "handler_failed"},
    )
    assert failed.status_code == 200
    assert api.post("/v1/source-work/claim?limit=20", headers=MACHINE, json={"pipeline_ids": ["swing_support"]}).json() == []

    # An audited terminal suppression for the earlier event unblocks the next
    # source message without changing its publication identity.
    suppressed = api.post(
        f"/v1/source-work/{first[0]['work_key']}/suppress",
        headers=ADMIN,
        json={"reason": "synthetic ordering test"},
    )
    assert suppressed.status_code == 200
    second = api.post("/v1/source-work/claim?limit=20", headers=MACHINE, json={"pipeline_ids": ["swing_support"]}).json()
    assert [item["event_key"] for item in second] == [later["event_key"]]


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


def test_correction_tombstone_and_durable_media_refs():
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
    media["media_refs"] = [{"ref": "00000000-0000-4000-8000-000000000001", "sha256": hashlib.sha256(b"chart").hexdigest(), "kind": "image", "content_type": "image/jpeg", "size_bytes": 5, "filename": "chart.jpg", "durable": True}]
    accepted = api.post("/v1/source-events", headers=MACHINE, json={"envelope": media})
    assert accepted.status_code == 200
    accepted_event = inbox.events[accepted.json()["event_key"]]["versions"][0]["envelope"]
    assert accepted_event["media_refs"] == media["media_refs"]

    too_large = envelope("too-large-media")
    too_large["media_refs"] = [{**media["media_refs"][0], "ref": "00000000-0000-4000-8000-000000000002", "size_bytes": 8 * 1024 * 1024 + 1}]
    assert api.post("/v1/source-events", headers=MACHINE, json={"envelope": too_large}).status_code == 422
    aggregate = envelope("aggregate-media")
    aggregate["media_refs"] = [{**media["media_refs"][0], "ref": f"00000000-0000-4000-8000-{number:012x}", "size_bytes": 8 * 1024 * 1024} for number in range(3, 7)]
    assert api.post("/v1/source-events", headers=MACHINE, json={"envelope": aggregate}).status_code == 422
    exposed_url = envelope("url-media")
    exposed_url["media_refs"] = [{**media["media_refs"][0], "ref": "00000000-0000-4000-8000-000000000007", "url": "https://storage.example/signed"}]
    assert api.post("/v1/source-events", headers=MACHINE, json={"envelope": exposed_url}).status_code == 422
    assert len(inbox.events) == 2


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
    blocked = api.post(path, headers=SOURCE, json=body)
    assert blocked.status_code == 409
    assert len(inbox.events[receipt["event_key"]]["versions"]) == 1
    assert api.post(f"/v1/source-work/{original['work_key']}/settle", headers=MACHINE, json={"lease_token": original["lease_token"], "success": False, "error_code": "handler_failed"}).json()["status"] == "pending"
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


def test_expired_lease_still_blocks_revision_until_reclaimed_and_settled():
    api, _catalog, inbox = setup()
    receipt = api.post("/v1/source-events", headers=SOURCE, json={"envelope": envelope()}).json()
    original = api.post("/v1/source-work/claim?limit=1", headers=MACHINE, json={"pipeline_ids": ["company_news"]}).json()[0]
    inbox.work[original["work_key"]]["lease_until"] = "2020-01-01T00:00:00+00:00"
    edited = envelope()
    edited["content_hash"] = hashlib.sha256(b"edit-expired").hexdigest()
    edited["payload"] = {"text": "new"}
    path = f"/v1/source-events/{receipt['event_key']}/versions"
    body = {"envelope": edited, "kind": "correction", "revision_id": "edit-expired", "reason": "edit"}
    assert api.post(path, headers=SOURCE, json=body).status_code == 409
    assert len(inbox.events[receipt["event_key"]]["versions"]) == 1
    reclaimed = api.post("/v1/source-work/claim?limit=1", headers=MACHINE, json={"pipeline_ids": ["company_news"]}).json()[0]
    assert reclaimed["lease_token"] != original["lease_token"]
    assert api.post(f"/v1/source-work/{reclaimed['work_key']}/settle", headers=MACHINE, json={"lease_token": reclaimed["lease_token"], "success": False, "error_code": "handler_failed"}).status_code == 200
    assert api.post(path, headers=SOURCE, json=body).json()["version"] == 2
    assert api.post(f"/v1/source-work/{original['work_key']}/settle", headers=MACHINE, json={"lease_token": original["lease_token"], "success": True}).status_code == 409


def test_claim_pipeline_filter_and_source_machine_authorization():
    api, _catalog, _inbox = setup()
    assert api.get("/v1/watchers/bursawatch-tg-market-news/config", headers=SOURCE).status_code == 403
    assert api.put("/v1/watchers/bursawatch-tg-market-news/config", headers=SOURCE, json={"config_version": 1, "config": {"version": 1}}).status_code == 403
    assert api.post("/v1/runs", headers=SOURCE, json={"watcher_id": "bursawatch-tg-market-news", "config_revision": 1}).status_code == 403
    wrong = envelope()
    wrong["endpoint_id"] = "telegram:phintraprofits"
    assert api.post("/v1/source-events", headers=SOURCE, json={"envelope": wrong}).status_code == 403
    receipt = api.post("/v1/source-events", headers=SOURCE, json={"envelope": envelope()}).json()
    assert api.post("/v1/source-work/claim", headers=SOURCE, json={"pipeline_ids": ["company_news"]}).status_code == 403
    assert api.post("/v1/source-work/claim", headers=MACHINE, json={"pipeline_ids": []}).status_code == 422
    assert api.post("/v1/source-work/claim", headers=MACHINE, json={"pipeline_ids": ["stockbit_snips"]}).json() == []
    claimed = api.post("/v1/source-work/claim", headers=MACHINE, json={"pipeline_ids": ["macro_news"]}).json()
    assert len(claimed) == 1 and claimed[0]["pipeline_id"] == "macro_news"
    assert api.post(f"/v1/source-work/{claimed[0]['work_key']}/begin", headers=MACHINE, json={"lease_token": claimed[0]["lease_token"]}).json()["begun"] is True
    assert api.post(f"/v1/source-work/{claimed[0]['work_key']}/settle", headers=MACHINE, json={"lease_token": claimed[0]["lease_token"], "success": True}).status_code == 200
    edited = envelope()
    edited["payload"] = {"text": "edited"}
    edited["content_hash"] = hashlib.sha256(b"edited").hexdigest()
    wrong_endpoint = deepcopy(edited)
    wrong_endpoint["endpoint_id"] = "telegram:phintraprofits"
    path = f"/v1/source-events/{receipt['event_key']}/versions"
    assert api.post(path, headers=SOURCE, json={"envelope": wrong_endpoint, "kind": "correction", "revision_id": "edit-2", "reason": "edit"}).status_code == 403
    assert api.post(path, headers=MACHINE, json={"envelope": edited, "kind": "correction", "revision_id": "edit-2", "reason": "edit"}).status_code == 403
    assert api.post(path, headers=SOURCE, json={"envelope": edited, "kind": "correction", "revision_id": "edit-2", "reason": "edit"}).status_code == 200


def test_begin_blocks_revision_and_reclaim_even_after_lease_deadline_until_audited_recovery():
    api, _catalog, inbox = setup()
    receipt = api.post("/v1/source-events", headers=SOURCE, json={"envelope": envelope()}).json()
    claimed = api.post("/v1/source-work/claim", headers=MACHINE, json={"pipeline_ids": ["company_news"]}).json()[0]
    wid, token = claimed["work_key"], claimed["lease_token"]
    assert api.post(f"/v1/source-work/{wid}/begin", headers=MACHINE, json={"lease_token": token}).json()["begun"] is True
    inbox.work[wid]["lease_until"] = "2020-01-01T00:00:00+00:00"
    assert api.post("/v1/source-work/claim", headers=MACHINE, json={"pipeline_ids": ["company_news"]}).json() == []
    assert api.get("/v1/source-work?status=executing", headers=MACHINE).json()[0]["work_key"] == wid
    edited = envelope()
    edited["content_hash"] = hashlib.sha256(b"executing-edit").hexdigest()
    edited["payload"] = {"text": "edited"}
    path = f"/v1/source-events/{receipt['event_key']}/versions"
    revision = {"envelope": edited, "kind": "correction", "revision_id": "exec-edit", "reason": "provider edit"}
    assert api.post(path, headers=SOURCE, json=revision).status_code == 409
    assert len(inbox.events[receipt["event_key"]]["versions"]) == 1
    assert api.post(f"/v1/source-work/{wid}/recover", headers=MACHINE, json={"reason": "process stopped", "worker_stopped": True}).status_code == 403
    assert api.post(f"/v1/source-work/{wid}/recover", headers=ADMIN, json={"reason": "process stopped", "worker_stopped": False}).status_code == 422
    recovered = api.post(f"/v1/source-work/{wid}/recover", headers=ADMIN, json={"reason": "worker process terminated and verified", "worker_stopped": True})
    assert recovered.json()["status"] == "dead_letter"
    assert inbox.audit[-1]["action"] == "recover"
    assert api.post(path, headers=SOURCE, json=revision).json()["version"] == 2
    assert api.post(f"/v1/source-work/{wid}/settle", headers=MACHINE, json={"lease_token": token, "success": True}).status_code == 409


def test_expired_lease_cannot_begin_then_revision_waits_for_claim_settlement():
    api, _catalog, inbox = setup()
    receipt = api.post("/v1/source-events", headers=SOURCE, json={"envelope": envelope()}).json()
    claimed = api.post("/v1/source-work/claim", headers=MACHINE, json={"pipeline_ids": ["company_news"]}).json()[0]
    inbox.work[claimed["work_key"]]["lease_until"] = "2020-01-01T00:00:00+00:00"
    assert api.post(f"/v1/source-work/{claimed['work_key']}/begin", headers=MACHINE, json={"lease_token": claimed["lease_token"]}).json()["begun"] is False
    edited = envelope()
    edited["content_hash"] = hashlib.sha256(b"expired-edit").hexdigest()
    edited["payload"] = {"text": "edited"}
    path = f"/v1/source-events/{receipt['event_key']}/versions"
    revision = {"envelope": edited, "kind": "correction", "revision_id": "expired-edit", "reason": "edit"}
    assert api.post(path, headers=SOURCE, json=revision).status_code == 409
    reclaimed = api.post("/v1/source-work/claim", headers=MACHINE, json={"pipeline_ids": ["company_news"]}).json()[0]
    assert api.post(f"/v1/source-work/{reclaimed['work_key']}/settle", headers=MACHINE, json={"lease_token": reclaimed["lease_token"], "success": False, "error_code": "handler_skipped"}).status_code == 200
    assert api.post(path, headers=SOURCE, json=revision).json()["version"] == 2


def test_begin_and_revision_race_cannot_commit_both():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    _api, _catalog, inbox = setup()
    receipt = inbox.accept(envelope())
    claimed = inbox.claim(["company_news"], 1)[0]
    edited = envelope()
    edited["content_hash"] = hashlib.sha256(b"concurrent-edit").hexdigest()
    edited["payload"] = {"text": "edited"}
    barrier = Barrier(3)

    def begin():
        barrier.wait()
        return inbox.begin(claimed["work_key"], claimed["lease_token"])

    def revise():
        barrier.wait()
        try:
            inbox.revise(receipt["event_key"], edited, "correction", "concurrent-edit", "source-actor", "provider edit")
        except InboxConflict as exc:
            return exc
        return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        begun = pool.submit(begin)
        revision = pool.submit(revise)
        barrier.wait()
        assert begun.result() is True
        assert "source revision waits for leased work" in str(revision.result())
    assert len(inbox.events[receipt["event_key"]]["versions"]) == 1
    assert inbox.work[claimed["work_key"]]["status"] == "executing"
