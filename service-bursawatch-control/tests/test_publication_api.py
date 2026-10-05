from __future__ import annotations

from fastapi.testclient import TestClient

from control_plane.api import create_app
from control_plane.auth import Principal, StaticTokenAuth
from control_plane.publication_store import MemoryPublicationStore
from control_plane.store import InMemoryStore
from test_publication_model import OWNER, publication


BOUNDARY = "2026-09-29T07:01:00+00:00"
OWNER_TOKEN = "p" * 32
ADMIN_TOKEN = "a" * 32


class PublicationAuth(StaticTokenAuth):
    def authenticate(self, authorization: str | None) -> Principal:
        if authorization == "Bearer viewer-token":
            return Principal(subject="synthetic-viewer", kind="viewer")
        return super().authenticate(authorization)


def client() -> TestClient:
    store = MemoryPublicationStore()
    store.activate(BOUNDARY, (OWNER, "bursawatch-stockbit-snips"))
    return TestClient(create_app(
        store=InMemoryStore(), publication_store=store,
        auth=PublicationAuth(
            machine_token="m" * 32, admin_token=ADMIN_TOKEN,
            publication_owner_tokens={OWNER: OWNER_TOKEN, "bursawatch-stockbit-snips": "s" * 32},
        ),
    ))


def test_owner_namespace_and_human_write_are_denied():
    app = client()
    value = publication()
    assert app.post("/v1/publications", json=value, headers={"Authorization": "Bearer viewer-token"}).status_code == 403
    assert app.post("/v1/publications", json=value, headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}).status_code == 403
    response = app.post("/v1/publications", json=value, headers={"Authorization": "Bearer " + "s" * 32})
    assert response.status_code == 202
    assert response.json()["publication_id"] != ""
    assert app.get("/v1/publications", headers={"Authorization": f"Bearer {OWNER_TOKEN}"}).status_code == 403


def test_cursor_filters_ties_and_conflicts():
    app = client()
    for number in range(5):
        value = publication(owner_key=f"source:synthetic:{number}")
        if number % 2:
            value["type"] = "macro_news"
            value["route"] = "macro_news"
        response = app.post("/v1/publications", json=value, headers={"Authorization": f"Bearer {OWNER_TOKEN}"})
        assert response.status_code == 202, response.text
    headers = {"Authorization": "Bearer viewer-token"}
    first = app.get("/v1/publications?limit=2", headers=headers).json()
    second = app.get("/v1/publications", params={"limit": 2, "cursor": first["next_cursor"]}, headers=headers).json()
    third = app.get("/v1/publications", params={"limit": 2, "cursor": second["next_cursor"]}, headers=headers).json()
    ids = [item["publication_id"] for item in first["items"] + second["items"] + third["items"]]
    assert len(ids) == len(set(ids)) == 5
    detail = app.get(f"/v1/publications/{ids[0]}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["versions"][0]["publication_id"] == ids[0]
    assert app.get("/v1/publications", params={"cursor": first["next_cursor"], "type": "macro_news"}, headers=headers).status_code == 422
    assert app.get("/v1/publications", params={"limit": 101}, headers=headers).status_code == 422
    assert app.get("/v1/publications/nope", headers=headers).status_code == 404
    changed = publication()
    changed["legs"][0]["text"] = "A changed output"
    assert app.post("/v1/publications", json=changed, headers={"Authorization": f"Bearer {OWNER_TOKEN}"}).status_code == 409


def test_malformed_or_pre_cutover_publication_is_not_accepted():
    app = client()
    value = publication(delivery_confirmed_at=BOUNDARY)
    assert app.post("/v1/publications", json=value, headers={"Authorization": f"Bearer {OWNER_TOKEN}"}).status_code == 422
    value = publication()
    value["legs"][0]["status"] = "pending"
    assert app.post("/v1/publications", json=value, headers={"Authorization": f"Bearer {OWNER_TOKEN}"}).status_code == 422
