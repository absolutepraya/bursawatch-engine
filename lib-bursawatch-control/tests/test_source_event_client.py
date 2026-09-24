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
