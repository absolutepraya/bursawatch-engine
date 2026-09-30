from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from control_plane.api import create_app
from control_plane.auth import Principal, StaticTokenAuth
from control_plane.operator_activity import get_endpoint_activity, get_pipeline_activity
from control_plane.source_catalog import MemoryCatalogStore, initial_config
from control_plane.source_inbox import MemoryInboxStore
from control_plane.store import InMemoryStore
from test_source_inbox import envelope


def inbox_with_news() -> tuple[MemoryCatalogStore, MemoryInboxStore]:
    catalog = MemoryCatalogStore()
    config = initial_config()
    config["publisher_defaults"] = [
        {"publisher_id": "phintraco", "capability_id": "company_news", "enabled": True, "settings": {}}
    ]
    catalog.put(1, config, "synthetic-admin")
    return catalog, MemoryInboxStore(catalog)


def test_endpoint_activity_uses_latest_accepted_event():
    _catalog, inbox = inbox_with_news()
    older = inbox.accept(envelope("synthetic-older"))["event_key"]
    newer = inbox.accept(envelope("synthetic-newer"))["event_key"]
    inbox.events[older]["created_at"] = "2026-09-29T07:00:00+00:00"
    inbox.events[newer]["created_at"] = "2026-09-29T07:01:00+00:00"
    result = get_endpoint_activity(inbox, "telegram:phintasprofits")
    assert result.accepted_at == "2026-09-29T07:01:00+00:00"


def test_missing_endpoint_activity_is_unknown():
    _catalog, inbox = inbox_with_news()
    result = get_endpoint_activity(inbox, "telegram:phintasprofits")
    assert result.accepted_at is None
    assert result.status == "unknown"


def test_old_input_is_stale_and_latest_suppressed_work_remains_work_only():
    _catalog, inbox = inbox_with_news()
    accepted = inbox.accept(envelope("synthetic-old"))
    event = inbox.events[accepted["event_key"]]
    event["created_at"] = "2026-09-28T07:00:00+00:00"
    work = inbox.work[accepted["work_keys"][0]]
    work["created_at"] = "2026-09-28T07:00:00+00:00"
    work["status"] = "suppressed"
    now = datetime(2026, 9, 30, 7, 0, tzinfo=timezone.utc)
    assert get_endpoint_activity(inbox, "telegram:phintasprofits", now=now).status == "stale"
    result = get_pipeline_activity(inbox, "company_news", now=now)
    assert (result.status, result.work_status, result.delivery_status) == (
        "stale", "suppressed", "not instrumented"
    )


def test_done_pipeline_work_is_not_delivered():
    catalog, inbox = inbox_with_news()
    accepted = inbox.accept(envelope("synthetic-done"))
    work = inbox.work[accepted["work_keys"][0]]
    work["status"] = "done"
    result = get_pipeline_activity(inbox, "company_news")
    assert result.work_status == "done"
    assert result.delivery_status == "not instrumented"

    client = TestClient(create_app(
        store=InMemoryStore(), catalog_store=catalog, inbox_store=inbox,
        auth=StaticTokenAuth(machine_token="synthetic-machine", admin_token="synthetic-admin"),
    ))
    response = client.get(
        "/v1/components/bursawatch-tg-market-news/activity",
        headers={"Authorization": "Bearer synthetic-admin"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["delivery_status"] == "not instrumented"
    assert any(row["pipeline_id"] == "company_news" and row["work_status"] == "done" for row in body["pipelines"])
    assert client.get(
        "/v1/components/bursawatch-tg-market-news/activity",
        headers={"Authorization": "Bearer synthetic-machine"},
    ).status_code == 403


class ViewerAuth:
    def authenticate(self, authorization: str | None) -> Principal:
        if authorization == "Bearer synthetic-viewer":
            return Principal(subject="synthetic-viewer", kind="viewer")
        return Principal(subject="synthetic-machine", kind="machine")


def test_viewer_can_read_source_activity_without_raw_payloads():
    catalog, inbox = inbox_with_news()
    inbox.accept(envelope("synthetic-source"))
    client = TestClient(create_app(
        store=InMemoryStore(), catalog_store=catalog, inbox_store=inbox, auth=ViewerAuth()
    ))
    response = client.get(
        "/v1/components/bursawatch-tg-source-ingest/activity",
        headers={"Authorization": "Bearer synthetic-viewer"},
    )
    assert response.status_code == 200
    body = response.json()
    assert any(row["endpoint_id"] == "telegram:phintasprofits" and row["accepted_at"] for row in body["endpoints"])
    assert "synthetic source" not in response.text
    assert "provider_event_id" not in response.text
    assert client.get(
        "/v1/components/not-a-real-component/activity",
        headers={"Authorization": "Bearer synthetic-viewer"},
    ).status_code == 404
