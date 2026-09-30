from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import sys
from urllib.error import HTTPError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from control_plane_client import ControlPlaneContractError, ControlPlaneUnavailable
from publication_client import PublicationClient, PublicationConflict


class Response:
    def __init__(self, body):
        self.body = BytesIO(json.dumps(body).encode())

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self):
        return self.body.read()


def snapshot():
    return {
        "api_version": 1,
        "owner_key": "news:provider:42",
        "version": 1,
        "supersedes_version": None,
        "type": "idx_company_news",
        "route": "id_stocks_news",
        "source_event_key": "a" * 64,
        "source_name": "Example source",
        "source_url": "https://example.com/news/42",
        "source_published_at": "2026-09-30T01:00:00Z",
        "market_data_as_of": None,
        "delivery_confirmed_at": "2026-09-30T01:01:00Z",
        "title": "Example title",
        "ticker": "BBCA",
        "broker_levels": None,
        "parent_publication_id": None,
        "board_episode_id": None,
        "config_revision": 1,
        "renderer_version": "news-1",
        "source_version": None,
        "required_operation_keys": ["operation-1"],
        "legs": [{
            "operation_key": "operation-1",
            "operation_digest": "b" * 64,
            "receipt_operation_id": "receipt-op-1",
            "destination": "12345678901234567",
            "receipt_id": "23456789012345678",
            "status": "delivered",
            "message_url": "https://discord.com/channels/1/12345678901234567/23456789012345678",
            "text": "Exact rendered output",
            "attachments": [],
        }],
    }


def ack(version=1):
    return {"publication_id": "c" * 64, "version": version, "digest": "d" * 64}


def test_timeout_retries_same_identity_and_digest():
    attempts = []

    def opener(request, timeout):
        attempts.append((request.data, request.get_header("Authorization"), timeout))
        if len(attempts) == 1:
            raise TimeoutError("slow")
        return Response(ack())

    client = PublicationClient("http://127.0.0.1:9120", "owner-secret", opener=opener, sleep=lambda _delay: None)
    assert client.submit(snapshot()) == ack()
    assert len(attempts) == 2
    assert attempts[0] == attempts[1]
    assert attempts[0][1] == "Bearer owner-secret"


def test_conflict_is_not_retried():
    requests = []

    def opener(request, timeout):
        requests.append(request.data)
        raise HTTPError(request.full_url, 409, "conflict", {}, None)

    client = PublicationClient("http://127.0.0.1:9120", "owner-secret", opener=opener, sleep=lambda _delay: None)
    with pytest.raises(PublicationConflict):
        client.submit(snapshot())
    assert len(requests) == 1


def test_transient_http_retries_identical_body():
    requests = []

    def opener(request, timeout):
        requests.append(request.data)
        if len(requests) == 1:
            raise HTTPError(request.full_url, 503, "busy", {}, None)
        return Response(ack())

    client = PublicationClient("http://127.0.0.1:9120", "owner-secret", opener=opener, sleep=lambda _delay: None)
    client.submit(snapshot())
    assert len(requests) == 2 and requests[0] == requests[1]


def test_error_redacts_token():
    token = "secret-owner-token"

    def opener(_request, timeout):
        raise OSError(f"connection failed with {token}")

    client = PublicationClient("http://127.0.0.1:9120", token, opener=opener, max_attempts=1)
    with pytest.raises(ControlPlaneUnavailable) as exc:
        client.submit(snapshot())
    assert token not in str(exc.value)


def test_malformed_acknowledgment_fails_closed():
    client = PublicationClient(
        "http://127.0.0.1:9120", "owner-secret", opener=lambda *_args, **_kwargs: Response({"ok": True})
    )
    with pytest.raises(ControlPlaneContractError):
        client.submit(snapshot())


def test_checkpoint_posts_owner_ledger_comparison():
    requests = []

    def opener(request, timeout):
        requests.append((request.full_url, json.loads(request.data)))
        return Response({"accepted": True})

    client = PublicationClient("http://127.0.0.1:9120", "owner-secret", opener=opener)
    comparison = {
        "comparison_at": "2026-09-30T01:02:00Z",
        "confirmed_boundary": "receipt-42",
        "accepted_boundary": "receipt-41",
        "outstanding_count": 1,
    }
    assert client.checkpoint(comparison) == {"accepted": True}
    assert requests == [("http://127.0.0.1:9120/v1/publications/checkpoints", comparison)]
