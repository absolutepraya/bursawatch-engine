from datetime import datetime, timedelta, timezone
import importlib

import pytest


def owner():
    module = importlib.import_module("summary_context")
    assert callable(getattr(module, "prepare_summary_context", None))
    return module


def test_optional_images_require_eligible_active_claim():
    module = owner()
    request = {"protocol": "summary-images-v1", "owner_event_key": "missing", "claim_id": "a"*64, "text_eligible": False, "asset_indexes": [0]}
    assert module.prepare_summary_context(request, no_post=True)["assets"] == []


def test_missing_claim_is_optional():
    module = owner()
    request = {"protocol": "summary-images-v1", "owner_event_key": "missing", "claim_id": "a"*64, "text_eligible": True, "asset_indexes": [0]}
    assert module.prepare_summary_context(request, no_post=True)["status"] == "unavailable"


def test_active_owner_claim_prepares_only_requested_original(tmp_path, monkeypatch):
    import base64, hashlib
    import bursawatch_source_media as media
    from bursawatch_source_media.summary_context import claim_id
    m = owner()
    now = datetime(2026, 10, 3, tzinfo=timezone.utc)
    data = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=")
    ref = media.SummaryImageRef("opaque", hashlib.sha256(data).hexdigest(), len(data), "image/png", "same source story", 2)
    claim = media.SummaryContextClaim("one", (now+timedelta(minutes=10)).isoformat(), "a"*64, 1, "b"*64, "An issuer announced a contract", (ref,), tmp_path / "context")
    calls = []
    class Reader:
        def download(self, key, **kwargs):
            calls.append(key)
            return media.MediaDownload(data,"image/png","one.png","image",ref.sha256)
    monkeypatch.setattr(m,"_load_claim",lambda *args:claim)
    monkeypatch.setattr(m,"_client",Reader)
    request = {"protocol":"summary-images-v1","owner_event_key":"one","claim_id":claim_id(claim),"text_eligible":True,"asset_indexes":[2]}
    result = m.prepare_summary_context(request,now=now,no_post=True)
    assert result["status"] == "ready" and calls == ["opaque"]
    assert result["assets"][0]["index"] == 2
    request["asset_indexes"] = [0]
    assert m.prepare_summary_context(request,now=now,no_post=True)["assets"] == []
    assert calls == ["opaque"]


def test_native_whatsapp_record_keeps_source_text(tmp_path):
    from test_scan import event
    from event_queue import serialize_event
    now = datetime(2026,10,3,tzinfo=timezone.utc)
    source = event("one",now.isoformat(),"Issuer disclosed a contract")
    record = {"event_key":source.event_key,"event":serialize_event(source),"agent_phase":"awaiting_agent","agent_lease_until":(now+timedelta(minutes=10)).isoformat(),"source_event_key":"a"*64,"source_content_hash":"b"*64}
    claim = owner().claim_from_state({"outbox":[record]},source.event_key,tmp_path)
    assert claim is not None and claim.source_text == source.text and claim.source_version == 1


def staged_claim(tmp_path, monkeypatch, key):
    """A verified bundle's private path, isolated from required delivery media."""
    import hashlib
    module = owner()
    from bursawatch_source_media import SummaryContextClaim, claim_id
    claim = SummaryContextClaim(key, (datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(), "a"*64, 1, "b"*64, "Issuer disclosed results", (), tmp_path / "optional")
    directory = claim.root / hashlib.sha256(claim_id(claim).encode()).hexdigest()
    directory.mkdir(parents=True, mode=0o700)
    asset = directory / "analysis.png"
    asset.write_bytes(b"isolated analysis bytes")
    monkeypatch.setattr(module, "claim_from_state", lambda *args: claim)
    return asset
