from dataclasses import replace
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import importlib
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import bursawatch_source_media as media

NOW = datetime(2026, 10, 3, tzinfo=timezone.utc)
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=")


def api():
    assert callable(getattr(media, "prepare_claim_context", None)), "claim-bound optional context is missing"
    return importlib.import_module("bursawatch_source_media.summary_context")


def context(m, tmp_path, **kwargs):
    ref = media.SummaryImageRef("ref", hashlib.sha256(PNG).hexdigest(), len(PNG), "image/png", "publication:one", 0)
    values = dict(owner_event_key="candidate:one", lease_until=(NOW+timedelta(minutes=2)).isoformat(), source_event_key="a"*64, source_version=1, content_hash="b"*64, source_text="Issuer disclosed a contract", refs=(ref,), root=tmp_path / "private")
    values.update(kwargs)
    return m.SummaryContextClaim(**values)


def request(m, claim, **kwargs):
    payload = dict(protocol="summary-images-v1", owner_event_key=claim.owner_event_key, claim_id=m.claim_id(claim), text_eligible=True, asset_indexes=[0])
    payload.update(kwargs)
    return payload


class Reader:
    def download(self, ref, **kwargs):
        return media.MediaDownload(PNG, "image/png", "one.png", "image", hashlib.sha256(PNG).hexdigest())


def test_context_requires_text_eligibility_and_current_claim(tmp_path):
    m = api(); claim = context(m, tmp_path)
    for changes in [{"text_eligible": False}, {"text_eligible": 1}, {"claim_id": "c"*64}, {"asset_indexes": [0,0]}, {"asset_indexes": [9]}, {"extra": "no"}]:
        result = m.prepare_claim_context(request(m,claim,**changes), resolve_claim=lambda _:claim, client_factory=Reader, now=NOW)
        assert result["status"] == "unavailable" and not result["assets"]
    for invalid in [replace(claim, source_text=""), replace(claim, lease_until=NOW.isoformat())]:
        assert not m.prepare_claim_context(request(m, invalid), resolve_claim=lambda _:invalid, client_factory=Reader, now=NOW)["assets"]


def test_source_version_race_returns_no_stale_images(tmp_path):
    m = api(); claim = context(m, tmp_path); current = [claim]
    class Racing(Reader):
        def download(self, ref, **kwargs):
            current[0] = replace(claim, source_version=2)
            return super().download(ref, **kwargs)
    result = m.prepare_claim_context(request(m, claim), resolve_claim=lambda _:current[0], client_factory=Racing, now=NOW)
    assert not result["assets"] and not list(tmp_path.rglob("*.png"))


def test_image_failure_returns_text_fallback(tmp_path):
    m = api(); claim = context(m, tmp_path)
    def failed(): raise TimeoutError()
    result = m.prepare_claim_context(request(m,claim), resolve_claim=lambda _:claim, client_factory=failed, now=NOW)
    assert result == {"protocol":"summary-images-v1", "status":"unavailable", "assets":[], "unavailable_count":1}


def test_ready_context_keeps_bound_association(tmp_path):
    m = api(); claim = context(m, tmp_path)
    result = m.prepare_claim_context(request(m,claim), resolve_claim=lambda _:claim, client_factory=Reader, now=NOW)
    assert result["status"] == "ready" and result["assets"][0]["association"] == "publication:one"
    instruction = m.context_instruction(claim, "owner prepare-summary-images --json")
    assert m.claim_id(claim) in instruction
    assert str(tmp_path) not in instruction and "inspect" in instruction.lower()
