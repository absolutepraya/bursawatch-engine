import base64
import hashlib
import importlib
import stat
import threading
import time

import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import bursawatch_source_media as media
from bursawatch_source_media import MediaDownload

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=")


def api():
    assert callable(getattr(media, "prepare_summary_images", None)), "optional preparation API is missing"
    return importlib.import_module("bursawatch_source_media.summary_images")


def image_ref(m, index=0, **overrides):
    values = dict(ref="opaque-ref-" + str(index), sha256=hashlib.sha256(PNG).hexdigest(), size_bytes=len(PNG), content_type="image/png", association="authored:post-1", index=index)
    values.update(overrides)
    return m.SummaryImageRef(**values)


class Reader:
    def download(self, ref, *, max_bytes=None, timeout_seconds=None):
        assert max_bytes >= len(PNG)
        assert 0 < timeout_seconds <= 8
        return MediaDownload(PNG, "image/png", "source.png", "image", hashlib.sha256(PNG).hexdigest())


def test_prepare_preserves_order_and_association(tmp_path):
    m = api()
    bundle = media.prepare_summary_images((image_ref(m, 2), image_ref(m, 0, association="quoted:post-2")), client=Reader(), root=tmp_path / "private", binding="event:1")
    assert bundle.status == "ready"
    assert [(a.index, a.association) for a in bundle.assets] == [(2, "authored:post-1"), (0, "quoted:post-2")]
    assert all(a.path.read_bytes() == PNG for a in bundle.assets)
    assert stat.S_IMODE(bundle.assets[0].path.stat().st_mode) == 0o600
    assert stat.S_IMODE(bundle.assets[0].path.parent.stat().st_mode) == 0o700


@pytest.mark.parametrize("overrides", [{"sha256": "a"*64}, {"size_bytes": 1}, {"content_type": "image/jpeg"}])
def test_digest_size_or_type_mismatch_is_unavailable(tmp_path, overrides):
    m = api()
    bundle = media.prepare_summary_images((image_ref(m, **overrides),), client=Reader(), root=tmp_path / "private", binding="event:1")
    assert bundle.status == "unavailable" and not bundle.assets
    assert not list(tmp_path.rglob("*.png"))


def test_preparation_budget_is_bounded(tmp_path):
    m = api()
    bundle = media.prepare_summary_images(tuple(image_ref(m, n) for n in range(6)), client=Reader(), root=tmp_path / "private", binding="event:1", limits=m.SummaryImageLimits(max_assets=2, total_bytes=len(PNG)*2))
    assert bundle.status == "partial" and len(bundle.assets) == 2 and bundle.unavailable_count == 4


def test_late_download_cannot_stage_files(tmp_path):
    m = api()
    release = threading.Event()
    class Stalled(Reader):
        def download(self, *args, **kwargs):
            release.wait(2)
            return super().download(*args, **kwargs)
    started = time.monotonic()
    try:
        bundle = media.prepare_summary_images((image_ref(m),), client=Stalled(), root=tmp_path / "private", binding="event:1", limits=m.SummaryImageLimits(preparation_seconds=0.03))
        assert time.monotonic() - started < 0.5
        assert not bundle.assets
    finally:
        release.set()
    time.sleep(0.02)
    assert not list(tmp_path.rglob("*.png"))


def test_private_assets_cannot_escape_root(tmp_path):
    m = api()
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "private"
    root.symlink_to(outside, target_is_directory=True)
    bundle = media.prepare_summary_images((image_ref(m),), client=Reader(), root=root, binding="../../elsewhere")
    assert not bundle.assets and not list(outside.iterdir())


def test_partial_failure_and_cleanup_are_optional(tmp_path):
    m = api()
    class Partial(Reader):
        def download(self, ref, **kwargs):
            if ref.endswith("1"):
                raise TimeoutError()
            return super().download(ref, **kwargs)
    root = tmp_path / "private"
    bundle = media.prepare_summary_images((image_ref(m), image_ref(m, 1)), client=Partial(), root=root, binding="event:1")
    assert bundle.status == "partial" and len(bundle.assets) == 1
    media.cleanup_summary_images(root, "event:1")
    assert not bundle.assets[0].path.exists()


def test_each_download_cannot_read_beyond_immutable_size(tmp_path):
    m = api()
    class SizeBounded(Reader):
        def download(self, ref, **kwargs):
            if kwargs["max_bytes"] != len(PNG):
                raise ValueError("request permits excess bytes")
            return super().download(ref, **kwargs)
    bundle = media.prepare_summary_images((image_ref(m),), client=SizeBounded(), root=tmp_path / "private", binding="event:1")
    assert bundle.status == "ready" and bundle.assets[0].path.read_bytes() == PNG
