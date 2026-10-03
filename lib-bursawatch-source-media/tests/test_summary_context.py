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


def test_finished_context_removes_only_its_binding(tmp_path):
    m = api(); claim = context(m, tmp_path)
    other = replace(claim, owner_event_key="other")
    first = m.prepare_claim_context(request(m, claim), resolve_claim=lambda _: claim, client_factory=Reader, now=NOW)
    second = m.prepare_claim_context(request(m, other), resolve_claim=lambda _: other, client_factory=Reader, now=NOW)
    m.cleanup_claim_context(claim)
    assert not Path(first["assets"][0]["path"]).exists()
    assert Path(second["assets"][0]["path"]).is_file()


def test_abandoned_context_expires_without_removing_active_bundle(tmp_path):
    m = api(); claim = context(m, tmp_path)
    result = m.prepare_claim_context(request(m, claim), resolve_claim=lambda _: claim, client_factory=Reader, now=NOW)
    staged = Path(result["assets"][0]["path"])
    m.expire_claim_context(claim.root, now=NOW + timedelta(minutes=1))
    assert staged.is_file()
    next_claim = replace(claim, owner_event_key="next", lease_until=(NOW + timedelta(minutes=5)).isoformat())
    next_bundle = m.prepare_claim_context(request(m, next_claim), resolve_claim=lambda _: next_claim, client_factory=Reader, now=NOW + timedelta(minutes=3))
    assert not staged.exists()
    assert Path(next_bundle["assets"][0]["path"]).is_file()


def test_expiry_cleanup_preserves_external_and_unmanaged_paths(tmp_path):
    m = api(); root = tmp_path / "private"; root.mkdir(mode=0o700)
    outside = tmp_path / "outside"; outside.mkdir()
    (outside / ".expires-at").write_text("0")
    (outside / "image.png").write_bytes(PNG)
    (root / ("c" * 64)).symlink_to(outside, target_is_directory=True)
    unmanaged = root / "required-delivery-media"; unmanaged.mkdir()
    (unmanaged / ".expires-at").write_text("0")
    m.expire_claim_context(root, now=NOW)
    assert (outside / "image.png").is_file() and unmanaged.is_dir()
