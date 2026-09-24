from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient

from control_plane.api import create_app
from control_plane.auth import StaticTokenAuth
from control_plane.source_catalog import MemoryCatalogStore, initial_config
from control_plane.store import InMemoryStore


ADMIN = {"Authorization": "Bearer admin-token"}
MACHINE = {"Authorization": "Bearer machine-token"}


def client():
    watchers = InMemoryStore()
    watchers.seed_config("bursawatch-tg-market-news", 1, {"version": 1})
    catalog = MemoryCatalogStore()
    app = create_app(store=watchers, catalog_store=catalog, auth=StaticTokenAuth(machine_token="machine-token", admin_token="admin-token"))
    return TestClient(app), watchers, catalog


def put(client, config, revision=1):
    return client.put("/v1/source-catalog/config", headers=ADMIN, json={"expected_revision": revision, "config": config})


def test_registry_lists_canonical_ids_and_engine_owned_capabilities_without_claiming_securities():
    api, _, _ = client()
    response = api.get("/v1/source-catalog", headers=ADMIN)
    assert response.status_code == 200
    body = response.json()
    assert body["securities"] == []
    endpoints = {x["id"]: x for x in body["endpoints"]}
    assert endpoints["telegram:phintraprofits"]["provider_id"] == "1444713822"
    assert endpoints["telegram:kelasinvestasiid"]["publisher_id"] == "kelas-investasi"
    assert endpoints["whatsapp:0029VbAjdnb60eBhwVdJxj1c"]["publisher_id"] == "bri-danareksa"
    assert len([x for x in endpoints if x.startswith("rss:stockbit:")]) == 4
    assert {x["id"]: x["tier"] for x in body["institutions"]}["phintraco"] == 1
    assert {x["id"]: x["tier"] for x in body["people_org"]}["kelas-investasi"] == 2
    assert api.get("/v1/source-catalog", headers=MACHINE).status_code == 403
    assert api.get("/v1/source-catalog/effective", headers=MACHINE).status_code == 200


def test_optimistic_write_audits_and_resolves_default_then_override_without_watcher_change():
    api, watchers, catalog = client()
    original = watchers.get_config("bursawatch-tg-market-news")
    config = initial_config()
    config["publisher_defaults"] = [{"publisher_id": "phintraco", "capability_id": "company_news", "enabled": True, "settings": {}}]
    config["endpoint_overrides"] = [{"endpoint_id": "telegram:phintasprofits", "capability_id": "company_news", "enabled": False, "settings": {}}]
    response = put(api, config)
    assert response.status_code == 200
    assert response.json()["revision"] == 2
    assert catalog.audit[0]["actor_id"]
    effective = api.get("/v1/source-catalog/effective", headers=MACHINE).json()
    chosen = next(x for x in effective["subscriptions"] if x["endpoint_id"] == "telegram:phintasprofits" and x["capability_id"] == "company_news")
    assert (chosen["enabled"], chosen["source"]) == (False, "endpoint_override")
    assert watchers.get_config("bursawatch-tg-market-news") == original
    assert put(api, config).status_code == 409
    assert catalog.get()["revision"] == 2


def test_rejects_arbitrary_security_and_unsupported_pair_without_mutation():
    api, _, catalog = client()
    config = initial_config()
    config["selected_securities"] = ["BBRI"]
    assert put(api, config).status_code == 422
    config = initial_config()
    config["endpoint_overrides"] = [{"endpoint_id": "telegram:phintraprofits", "capability_id": "stockbit_snips", "enabled": True, "settings": {}}]
    assert put(api, config).status_code == 422
    assert catalog.get()["revision"] == 1
    assert catalog.audit == []


def test_new_people_endpoint_is_pending_and_cannot_activate_an_unsupported_pipeline():
    api, _, _ = client()
    config = initial_config()
    config["people_org"] = [{"id": "analyst-a", "name": "Analyst A", "kind": "person", "asset_ref": {"url": "https://images.example.test/a.png", "kind": "profile_picture"}}]
    config["endpoints"] = [{"id": "analyst-a-x", "publisher_id": "analyst-a", "platform": "x", "address": "analyst_a", "credential_ref": "credential:x-reader"}]
    config["publisher_defaults"] = [{"publisher_id": "analyst-a", "capability_id": "company_news", "enabled": True, "settings": {}}]
    assert put(api, config).status_code == 200
    effective = api.get("/v1/source-catalog/effective", headers=MACHINE).json()
    item = next(x for x in effective["subscriptions"] if x["endpoint_id"] == "analyst-a-x" and x["capability_id"] == "company_news")
    assert item["verification_status"] == "pending"
    assert item["enabled"] is False
    bad = deepcopy(config)
    bad["endpoint_overrides"] = [{"endpoint_id": "analyst-a-x", "capability_id": "trading_plans", "enabled": True, "settings": {}}]
    assert put(api, bad, 2).status_code == 422
    bad = deepcopy(config)
    bad["endpoints"][0]["platform"] = "rss"
    assert put(api, bad, 2).status_code == 422
    bad = deepcopy(config)
    bad["endpoints"][0]["address"] = "https://x.com/analyst_a"
    assert put(api, bad, 2).status_code == 422


def test_malformed_nested_identity_is_a_validation_error_without_a_revision():
    api, _, catalog = client()
    config = initial_config()
    config["people_org"] = [{"id": [], "name": "Bad", "kind": "person", "asset_ref": None}]
    assert put(api, config).status_code == 422
    assert catalog.get()["revision"] == 1


def test_catalog_migration_is_additive_and_private():
    sql = (Path(__file__).resolve().parents[1] / "migrations/013_source_catalog.sql").read_text()
    assert sql.startswith("-- bursawatch-release: automatic\n")
    assert "bursawatch_config_revisions" not in sql
    assert "bursawatch_source_catalog_revisions" in sql
    assert "bursawatch_source_asset_refs" in sql
    for table in ("supported_securities", "source_publishers", "source_endpoints", "source_capabilities", "source_compatibility", "source_catalog_revisions", "source_selections", "source_people_org_revisions", "source_endpoint_revisions", "source_publisher_defaults", "source_endpoint_overrides", "source_catalog_audit", "source_asset_refs"):
        assert f"alter table bursawatch_{table} enable row level security;" in sql
        assert f"revoke all privileges on table bursawatch_{table} from public;" in sql
