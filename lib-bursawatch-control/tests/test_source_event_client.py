from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from control_plane_client import ControlPlaneContractError, ControlPlaneUnavailable
from source_event_client import SourceEventClient, SourceEventHandoff


class Response:
    def __init__(self, body):
        self.body = BytesIO(json.dumps(body).encode())
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return None
    def read(self):
        return self.body.read()


def test_handoff_retains_event_until_durable_receipt(tmp_path):
    attempts = []
    identity = {"platform": "telegram", "endpoint_id": "telegram:phintasprofits", "provider_event_id": "42"}
    expected = hashlib.sha256(json.dumps([identity["platform"], identity["endpoint_id"], identity["provider_event_id"]], separators=(",", ":")).encode()).hexdigest()
    def opener(request, timeout):
        attempts.append(json.loads(request.data))
        if len(attempts) == 1:
            raise OSError("offline")
        if len(attempts) == 2:
            return Response({"event_key": "a" * 64, "version": 1, "duplicate": False, "work_keys": []})
        return Response({"event_key": expected, "version": 1, "duplicate": False, "work_keys": []})
    handoff = SourceEventHandoff(tmp_path, SourceEventClient("http://127.0.0.1:9119", "machine", opener=opener))
    handoff.stage(identity)
    with pytest.raises(ControlPlaneUnavailable):
        handoff.flush()
    assert len(handoff.spool.pending()) == 1
    with pytest.raises(ControlPlaneContractError):
        handoff.flush()
    assert len(handoff.spool.pending()) == 1
    assert handoff.flush()[0]["event_key"] == expected
    assert handoff.spool.pending() == []
    assert attempts[0] == attempts[1] == attempts[2]


def test_revision_handoff_retains_lease_conflict_until_retry(tmp_path):
    identity = {"platform": "telegram", "endpoint_id": "telegram:phintasprofits", "provider_event_id": "42"}
    key = hashlib.sha256(json.dumps([identity["platform"], identity["endpoint_id"], identity["provider_event_id"]], separators=(",", ":")).encode()).hexdigest()
    class Client:
        def __init__(self):
            self.calls = 0
        def revise(self, event_key, envelope, kind, revision_id, reason):
            self.calls += 1
            assert (event_key, kind, revision_id) == (key, "correction", "edit-1")
            if self.calls == 1:
                raise ControlPlaneUnavailable("source inbox returned HTTP 409")
            return {"event_key": key, "version": 2, "duplicate": False, "work_keys": []}
    client = Client()
    handoff = SourceEventHandoff(tmp_path, client)
    handoff.stage_revision(key, identity, "correction", "edit-1", "provider edit")
    with pytest.raises(ControlPlaneUnavailable):
        handoff.flush()
    assert len(handoff.spool.pending()) == 1
    assert handoff.flush()[0]["version"] == 2
    assert handoff.spool.pending() == []
