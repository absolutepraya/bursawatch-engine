from __future__ import annotations

from copy import deepcopy
import ast
import json
from pathlib import Path

from fastapi.testclient import TestClient

from control_plane.api import create_app
from control_plane.auth import Principal, StaticTokenAuth
from control_plane.source_catalog import MemoryCatalogStore, initial_config, registry
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
    assert body["can_edit"] is True
    endpoints = {x["id"]: x for x in body["endpoints"]}
    assert endpoints["telegram:phintraprofits"]["provider_id"] == "1444713822"
    assert ("telegram:phintasprofits", "trading_plans", None) in {
        (item["endpoint_id"], item["capability_id"], item["dispatch_group"])
        for item in body["compatibility"]
    }
    assert endpoints["telegram:kelasinvestasiid"]["publisher_id"] == "kelas-investasi"
    assert endpoints["whatsapp:0029VbAjdnb60eBhwVdJxj1c"]["publisher_id"] == "bri-danareksa"
    assert len([x for x in endpoints if x.startswith("rss:stockbit:")]) == 4
    assert {x["id"]: x["tier"] for x in body["institutions"]}["phintraco"] == 1
    assert {x["id"]: x["tier"] for x in body["people_org"]}["kelas-investasi"] == 2
    assert api.get("/v1/source-catalog", headers=MACHINE).status_code == 403
    effective = api.get("/v1/source-catalog/effective", headers=MACHINE)
    assert effective.status_code == 200
    bri = next(item for item in effective.json()["subscriptions"] if item["endpoint_id"] == "whatsapp:0029VbAjdnb60eBhwVdJxj1c")
    assert bri["address"] == "https://www.whatsapp.com/channel/0029VbAjdnb60eBhwVdJxj1c"
    assert bri["provider_id"] == "120363419226413141@newsletter"
    assert bri["credential_ref"] is None


def test_x_route_compatibility_is_grouped_and_disabled_until_configured():
    api, _, _ = client()
    catalog = api.get("/v1/source-catalog", headers=ADMIN).json()
    effective = api.get("/v1/source-catalog/effective", headers=MACHINE).json()
    x_ids = {item["id"] for item in catalog["endpoints"] if item["platform"] == "x"}
    assert len(x_ids) == 10
    grouped = [item for item in catalog["compatibility"] if item["endpoint_id"] in x_ids]
    assert {(item["endpoint_id"], item["capability_id"], item["dispatch_group"]) for item in grouped} == {
        (endpoint_id, capability, "x_post_route")
        for endpoint_id in x_ids
        for capability in ("company_news", "macro_news", "swing_chart_context")
    }
    assert all(item["dispatch_group"] is None for item in catalog["compatibility"] if item["endpoint_id"] not in x_ids)
    x_subs = [item for item in effective["subscriptions"] if item["endpoint_id"] in x_ids]
    assert len(x_subs) == 30
    assert all(item["dispatch_group"] == "x_post_route" and item["enabled"] is False and item["source"] == "unset" for item in x_subs)
    assert all(item["dispatch_group"] is None for item in effective["subscriptions"] if item["endpoint_id"] not in x_ids)


def test_bri_whatsapp_compatibility_preserves_news_and_swing_routes():
    api, _, _ = client()
    endpoint_id = "whatsapp:0029VbAjdnb60eBhwVdJxj1c"
    catalog = api.get("/v1/source-catalog", headers=ADMIN).json()
    effective = api.get("/v1/source-catalog/effective", headers=MACHINE).json()
    compatibility = [row for row in catalog["compatibility"] if row["endpoint_id"] == endpoint_id]
    assert {(row["capability_id"], row["dispatch_group"]) for row in compatibility} == {
        ("company_news", None),
        ("macro_news", None),
        ("swing_chart_context", None),
    }
    subscriptions = [row for row in effective["subscriptions"] if row["endpoint_id"] == endpoint_id]
    assert {row["capability_id"] for row in subscriptions} == {"company_news", "macro_news", "swing_chart_context"}
    assert all(row["enabled"] is False and row["source"] == "unset" for row in subscriptions)


def test_user_added_x_endpoint_gets_group_compatibility_but_stays_pending():
    api, _, _ = client()
    config = initial_config()
    config["people_org"] = [{"id": "new-analyst", "name": "New Analyst", "kind": "person", "asset_ref": None}]
    config["endpoints"] = [{"id": "new-analyst-x", "publisher_id": "new-analyst", "platform": "x", "address": "new_analyst", "credential_ref": None}]
    assert put(api, config).status_code == 200
    catalog = api.get("/v1/source-catalog", headers=ADMIN).json()
    compatibility = [item for item in catalog["compatibility"] if item["endpoint_id"] == "new-analyst-x"]
    assert {(item["capability_id"], item["dispatch_group"]) for item in compatibility} == {
        (capability, "x_post_route") for capability in ("company_news", "macro_news", "swing_chart_context")
    }
    subscriptions = [item for item in api.get("/v1/source-catalog/effective", headers=MACHINE).json()["subscriptions"] if item["endpoint_id"] == "new-analyst-x"]
    assert all(item["dispatch_group"] == "x_post_route" and item["enabled"] is False and item["verification_status"] == "pending" for item in subscriptions)


def test_catalog_edit_permission_comes_from_authenticated_backend_principal():
    class ViewerAuth:
        def authenticate(self, authorization):
            assert authorization == "Bearer viewer-token"
            return Principal(subject="viewer-user", kind="viewer")

    api = TestClient(create_app(store=InMemoryStore(), catalog_store=MemoryCatalogStore(), auth=ViewerAuth()))
    response = api.get("/v1/source-catalog", headers={"Authorization": "Bearer viewer-token"})
    assert response.status_code == 200
    assert response.json()["can_edit"] is False
    assert api.put("/v1/source-catalog/config", headers={"Authorization": "Bearer viewer-token"}, json={"expected_revision": 1, "config": initial_config()}).status_code == 403


def test_every_seeded_endpoint_matches_checked_in_source_identity_and_provider_id():
    root = Path(__file__).resolve().parents[2]
    actual_registry = registry()
    actual = {row["id"]: row for row in actual_registry["endpoints"]}
    publishers = {row["id"]: row for row in actual_registry["institutions"] + actual_registry["people_org"]}
    expected = {}

    for platform, package in (("x", "cron-x-account-watch"), ("instagram", "cron-ig-account-watch")):
        profiles = json.loads((root / package / "config/watches.json").read_text())["profiles"]
        for profile in profiles:
            endpoint_id = f"{platform}:{profile['handle'].lower()}"
            publisher_id = f"{'x' if platform == 'x' else 'instagram'}-{profile['id']}"
            expected[endpoint_id] = (publisher_id, profile["handle"], None)
            assert publishers[publisher_id]["name"] == profile["display_name"]

    wa_profiles = json.loads((root / "cron-wa-channel-watch/config/watches.json").read_text())["profiles"]
    wa_publishers = {"bri-danareksa-sekuritas": "bri-danareksa", "ins": "whatsapp-ins", "samuel-sekuritas-indonesia": "samuel-sekuritas"}
    for profile in wa_profiles:
        endpoint_id = "whatsapp:" + profile["channel_url"].split("/")[-1]
        publisher_id = wa_publishers[profile["id"]]
        expected[endpoint_id] = (publisher_id, profile["channel_url"], profile["channel_jid"])
        assert publishers[publisher_id]["name"] == profile["display_name"]
        assert profile["channel_jid"].endswith("@newsletter")
        assert profile["channel_jid"] not in profile["channel_url"]
    assert "by_channel.get(profile.channel_jid" in (root / "cron-wa-channel-watch/bin/scan.py").read_text()
    assert '"jid": target["channel_jid"]' in (root / "cron-wa-channel-watch/bin/subscriptions.py").read_text()

    for package, publisher_id in (("cron-tg-phintraco-swing", "phintraco"), ("cron-tg-kelas-investasi-gtw", "kelas-investasi")):
        source = json.loads((root / "service-bursawatch-control/baseline-configs" / f"bursawatch-{package[5:]}.json").read_text())["source"]
        expected[f"telegram:{source['telegram_username']}"] = (publisher_id, source["telegram_username"], str(source["telegram_channel_id"]))
        source_code = (root / package / "bin/config.py").read_text()
        assert str(source["telegram_channel_id"]) in source_code
        assert source["telegram_username"] in source_code

    expected["telegram:phintraprofits"] = ("phintraco", "phintraprofits", "1444713822")

    providers = json.loads((root / "service-bursawatch-control/baseline-configs/bursawatch-tg-market-news.json").read_text())["providers"]
    for publisher_id, source in providers.items():
        expected[f"telegram:{source['telegram_username']}"] = (publisher_id, source["telegram_username"], None)
        assert source["telegram_username"] in (root / "cron-tg-market-news/bin/config.py").read_text()

    model_tree = ast.parse((root / "cron-stockbit-snips/bin/models.py").read_text())
    lanes = {}
    for node in model_tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "FeedLane":
            lanes = {assignment.targets[0].id: assignment.value.value for assignment in node.body if isinstance(assignment, ast.Assign) and isinstance(assignment.value, ast.Constant)}
    feed_tree = ast.parse((root / "cron-stockbit-snips/bin/config.py").read_text())
    feed_assignment = next(node for node in feed_tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "FEEDS" for target in node.targets))
    source_feeds = [(lanes[feed.args[0].attr], feed.args[2].value) for feed in feed_assignment.value.elts]
    source_lanes = [lane for lane, _url in source_feeds]
    configured_lanes = [feed["id"] for feed in json.loads((root / "service-bursawatch-control/baseline-configs/bursawatch-stockbit-snips.json").read_text())["feeds"]]
    assert source_lanes == configured_lanes
    for lane, url in source_feeds:
        expected[f"rss:stockbit:{lane}"] = ("stockbit", url, lane)

    assert set(actual) == set(expected)
    migration = (root / "service-bursawatch-control/migrations/013_source_catalog.sql").read_text()
    for endpoint_id, (publisher_id, address, provider_id) in expected.items():
        row = actual[endpoint_id]
        assert (row["publisher_id"], row["address"], row["provider_id"]) == (publisher_id, address, provider_id)
        literal_provider_id = f"'{provider_id}'" if provider_id is not None else "null"
        assert f"values ('{endpoint_id}', '{publisher_id}', '{row['platform']}', '{address}', {literal_provider_id});" in migration


def test_phintas_swing_compatibility_is_migration_backed_and_not_enabled_by_default():
    root = Path(__file__).resolve().parents[1]
    compatible = {(item["endpoint_id"], item["capability_id"]) for item in registry()["compatibility"]}
    assert ("telegram:phintasprofits", "trading_plans") in compatible
    migration = (root / "migrations/021_phintas_swing_compatibility.sql").read_text()
    assert migration.splitlines()[0] == "-- bursawatch-release: automatic"
    assert "values ('telegram:phintasprofits', 'trading_plans');" in migration

    api, _, _ = client()
    effective = api.get("/v1/source-catalog/effective", headers=MACHINE).json()
    swing = next(item for item in effective["subscriptions"]
                 if item["endpoint_id"] == "telegram:phintasprofits" and item["capability_id"] == "trading_plans")
    assert (swing["enabled"], swing["verification_status"], swing["source"]) == (False, "verified", "unset")


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
    assert (chosen["address"], chosen["provider_id"], chosen["credential_ref"]) == ("phintasprofits", None, None)
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
    assert (item["address"], item["provider_id"], item["credential_ref"]) == ("analyst_a", None, "credential:x-reader")
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


def test_x_route_migration_preserves_existing_subscription_intent_and_work():
    sql = (Path(__file__).resolve().parents[1] / "migrations/017_x_swing_route_groups.sql").read_text()
    assert sql.startswith("-- bursawatch-release: automatic\n")
    assert "add column dispatch_group text" in sql
    assert "add column dispatch_context jsonb not null default '{}'::jsonb" in sql
    assert "where platform = 'x'" in sql
    assert "compatibility.capability_id in ('company_news', 'macro_news', 'swing_chart_context')" in sql
    assert "publisher_defaults" not in sql and "endpoint_overrides" not in sql
    assert "delete from" not in sql and "truncate " not in sql and "drop " not in sql
