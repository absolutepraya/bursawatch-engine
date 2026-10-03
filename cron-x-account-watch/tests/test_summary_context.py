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


def test_native_x_ledger_resolves_active_bound_source(tmp_path, monkeypatch):
    import state, pipeline_owner
    from test_pipeline_owner import _profile, _post, _work, NOW
    from bursawatch_source_media.summary_context import claim_id
    m = owner(); profile = _profile(); storage = tmp_path / "x.json"
    monkeypatch.setenv("X_POST_WATCH_STATE_PATH",str(storage))
    pipeline_owner.accept_source_work(_work(profile,[_post(profile,101,"A source disclosure")]),profiles=(profile,),no_post=True,now=NOW)
    value = state.load_state(storage)
    event = state.claim_oldest_agent(value,{profile.id:profile},NOW+timedelta(hours=1))
    state.save_state(storage,value)
    claim = m._load_claim(f'{event["profile_id"]}:{event["post_id"]}',NOW,True)
    assert claim.source_text == "A source disclosure" and claim.source_version == 1
    assert claim.owner_event_key == f'{event["profile_id"]}:{event["post_id"]}'
    event["agent_phase"] = "ready"; event["agent_lease_until"] = None
    # Lookup is read-only and ignores inactive owner records.
    assert m.claim_from_state(value,f'{event["profile_id"]}:{event["post_id"]}',tmp_path) is None
