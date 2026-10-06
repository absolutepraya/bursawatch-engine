from __future__ import annotations

from fastapi.testclient import TestClient

from control_plane.api import create_app
from control_plane.auth import AuthenticationError, Principal, StaticTokenAuth
from control_plane.operator_inventory import component_view, list_components
from control_plane.source_catalog import MemoryCatalogStore
from control_plane.store import InMemoryStore


EXISTING_OR_PLANNED_JOB_IDS = {
    "bursawatch-tg-source-ingest",
    "bursawatch-tg-market-news",
    "bursawatch-tg-phintraco-swing",
    "bursawatch-tg-kelas-investasi-gtw",
    "bursawatch-x-account-watch-source",
    "bursawatch-x-account-watch-queue-worker",
    "bursawatch-ig-account-watch-source",
    "bursawatch-wa-channel-watch",
    "bursawatch-stockbit-snips",
    "bursawatch-dc-swing-board-close",
    "bursawatch-dc-swing-board-retry",
    "bursawatch-dc-swing-board-lifecycle",
}


class ViewerAuth:
    def authenticate(self, authorization: str | None) -> Principal:
        if authorization == "Bearer viewer-token":
            return Principal(subject="viewer-user", kind="viewer")
        if authorization == "Bearer machine-token":
            return Principal(subject="source-job", kind="machine")
        raise AuthenticationError("invalid bearer credential")


def test_inventory_has_all_migrated_owners():
    components = list_components()
    domain_owners = [component for component in components if component.kind == "domain_owner"]

    assert len(domain_owners) == 9
    assert {item.component_id for item in components if item.kind == "source_adapter"} == {
        "bursawatch-tg-source-ingest",
        "bursawatch-x-source-ingest",
        "bursawatch-ig-source-ingest",
        "bursawatch-wa-source-ingest",
        "bursawatch-rss-source-ingest",
    }
    assert [item.component_id for item in components if item.kind == "delivery_service"] == [
        "bursawatch-discord-delivery"
    ]


def test_shared_telegram_job_has_three_owners():
    components = list_components()
    expected_ids = {
        "bursawatch-tg-market-news",
        "bursawatch-tg-phintraco-swing",
        "bursawatch-tg-kelas-investasi-gtw",
    }
    related_owner_ids = {
        item.component_id
        for item in components
        if item.kind == "domain_owner" and "bursawatch-tg-source-ingest" in item.job_ids
    }

    assert related_owner_ids == expected_ids


def test_five_adapters_include_unscheduled_instagram_and_stable_ids():
    components = list_components()
    by_id = {item.component_id: item for item in components}

    assert len([item for item in components if item.kind == "source_adapter"]) == 5
    assert by_id["bursawatch-ig-source-ingest"].job_ids == ()
    assert by_id["bursawatch-rss-source-ingest"].related_component_ids == ("bursawatch-stockbit-snips",)
    assert len(by_id) == len(components)
    assert component_view("bursawatch-tg-source-ingest")["inventory_version"] == 1


def test_every_declared_job_id_is_existing_or_planned():
    declared = {job_id for component in list_components() for job_id in component.job_ids}

    assert declared <= EXISTING_OR_PLANNED_JOB_IDS
    assert "bursawatch-x-account-watch-queue-worker" in declared
    assert "bursawatch-x-account-watch-source" in declared


class RevisionChangingCatalog(MemoryCatalogStore):
    def __init__(self):
        super().__init__()
        self.read_count = 0

    def get(self):
        self.read_count += 1
        snapshot = super().get()
        snapshot["revision"] = self.read_count
        return snapshot


def test_component_list_uses_one_source_catalog_revision():
    catalog = RevisionChangingCatalog()
    client = TestClient(
        create_app(
            store=InMemoryStore(),
            auth=ViewerAuth(),
            validators={},
            catalog_store=catalog,
        )
    )

    response = client.get("/v1/components", headers={"Authorization": "Bearer viewer-token"})
    revisions = {
        component["source_gate"]["catalog_revision"]
        for component in response.json()["components"]
        if "source_gate" in component
    }

    assert revisions == {1}
    assert catalog.read_count == 1


def test_machine_cannot_read_human_inventory():
    client = TestClient(
        create_app(
            store=InMemoryStore(),
            auth=ViewerAuth(),
            validators={},
        )
    )

    assert client.get("/v1/components", headers={"Authorization": "Bearer machine-token"}).status_code == 403


def test_viewer_can_read_component_list_and_detail():
    client = TestClient(
        create_app(
            store=InMemoryStore(),
            auth=ViewerAuth(),
            validators={},
        )
    )
    headers = {"Authorization": "Bearer viewer-token"}

    response = client.get("/v1/components", headers=headers)
    detail = client.get("/v1/components/bursawatch-tg-source-ingest", headers=headers)

    assert response.status_code == 200
    assert response.json()["inventory_version"] == 1
    assert detail.status_code == 200
    assert detail.json()["component_id"] == "bursawatch-tg-source-ingest"
    assert client.get("/v1/components/not-a-component", headers=headers).status_code == 404
