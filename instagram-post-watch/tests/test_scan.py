from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

import config
import media
import ocr
import scan
import state
import vision_gate
from models import DownloadedAsset, DownloadedPublication, FailedAsset, MediaKind, PublicationKind, SourceMedia, SourcePost


NOW = datetime(2026, 8, 25, 10, 0, tzinfo=scan.WIB)


class FakeBackend:
    engine_id = "fake"
    model_version = "fake-v1"


def _post(profile_id: str, publication_id: str, minute: int, *, caption: str = "A substantive market publication with enough context.", kind: PublicationKind = PublicationKind.POST, media: tuple[SourceMedia, ...] | None = None) -> SourcePost:
    if media is None:
        media = (SourceMedia(f"https://cdn.example/{publication_id}-0.jpg", MediaKind.IMAGE, 0),)
    return SourcePost(
        profile_id,
        publication_id,
        f"https://www.instagram.com/{'reel' if kind is PublicationKind.REEL else 'p'}/{publication_id}",
        NOW + timedelta(minutes=minute),
        caption,
        kind,
        media,
    )


def _asset(root: Path, source: SourceMedia, *, content_type: str | None = None) -> DownloadedAsset:
    root.mkdir(parents=True, exist_ok=True)
    suffix = ".mp4" if source.kind is MediaKind.VIDEO else ".jpg"
    path = root / f"{source.index}{suffix}"
    payload = f"asset-{source.index}-{source.kind.value}".encode()
    path.write_bytes(payload)
    return DownloadedAsset(
        source,
        path,
        hashlib.sha256(payload).hexdigest(),
        len(payload),
        content_type or ("video/mp4" if source.kind is MediaKind.VIDEO else "image/jpeg"),
    )


def _install_paths(monkeypatch, tmp_path: Path, config_path: Path) -> tuple[Path, Path]:
    storage = tmp_path / "state" / "state.json"
    media_root = tmp_path / "state" / "media"
    cache_root = tmp_path / "state" / "ocr-cache"
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_STATE_PATH", str(storage))
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_MEDIA_ROOT", str(media_root))
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_OCR_CACHE_PATH", str(cache_root))
    monkeypatch.setattr(scan, "state_path", lambda: storage)
    monkeypatch.setattr(scan, "config_path", lambda: config_path)
    monkeypatch.setattr(scan, "media_root_path", lambda: media_root)
    monkeypatch.setattr(scan, "ocr_cache_path", lambda: cache_root)
    return storage, media_root


def _initialize_cursor(storage: Path, profile, publication: SourcePost) -> None:
    value = state.new_state()
    state.observe_publications(value, profile, [publication], NOW, lambda _: pytest.fail("initial observation must not prepare"))
    state.save_state(storage, value)


def _install_download_and_ocr(monkeypatch, media_root: Path, *, ocr_failure_indexes: set[int] | None = None):
    ocr_failure_indexes = ocr_failure_indexes or set()
    calls: list[int] = []

    def download(post, root, _session, _limits, *, allow_partial=False):
        del allow_partial
        event_root = root / post.publication_id
        assets = tuple(_asset(event_root, source) for source in post.media)
        return DownloadedPublication(assets, event_root)

    def extract(asset, _cache_root, _backend, _languages):
        calls.append(asset.source.index)
        if asset.source.index in ocr_failure_indexes:
            return ocr.OCRResult(ocr.OCRStatus.ERROR, error="secret OCR text must not leak")
        return ocr.OCRResult(
            ocr.OCRStatus.SUCCESS,
            text=f"Asset {asset.source.index} contains a market thesis and supporting context",
            confidence=0.99,
            min_confidence=0.98,
            engine_id="fake",
            model_version="fake-v1",
            languages=("ind", "eng"),
        )

    monkeypatch.setattr(scan.media, "download_publication", download)
    monkeypatch.setattr(scan.ocr, "build_backend", lambda _engine=None: FakeBackend())
    monkeypatch.setattr(scan.ocr, "extract_cached", extract)
    return calls


def _queued_event(storage: Path, profile, post: SourcePost, prepared: dict, now: datetime = NOW) -> dict:
    value = state.load_state(storage)
    state.observe_publications(value, profile, [post], now, lambda _: prepared)
    event = value["outbox"][0]
    state.save_state(storage, value)
    return event


def _prepared(post: SourcePost, media_root: Path, *, image_count: int | None = None) -> dict:
    event_root = media_root / post.publication_id
    count = image_count if image_count is not None else len(post.media)
    assets = tuple(_asset(event_root, source) for source in post.media)
    ocr_assets = tuple(asset for asset in assets if asset.source.kind is MediaKind.IMAGE)
    results = tuple(
        ocr.OCRResult(
            ocr.OCRStatus.SUCCESS,
            text=f"Asset {index} has sufficient market context",
            confidence=0.99,
            min_confidence=0.98,
            engine_id="fake",
            model_version="fake-v1",
            languages=("ind", "eng"),
        )
        for index in range(count)
        if index < len(ocr_assets)
    )
    decision = vision_gate.VisionDecision(vision_gate.VisionMode.TEXT_ONLY, "text_sufficient", (), (), ())
    return {
        "post": post,
        "downloaded_publication": DownloadedPublication(assets, event_root),
        "ocr_results": results,
        "vision_decision": decision,
    }


def test_first_observation_initializes_cursor_without_backfill(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, _media_root = _install_paths(monkeypatch, tmp_path, config_path)
    posts = [_post(profile.id, "older", 1), _post(profile.id, "newest", 2)]
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", lambda *_args, **_kwargs: posts)
    monkeypatch.setattr(scan.ocr, "build_backend", lambda *_args: pytest.fail("first observation must not build OCR"))

    result = scan.run(now=NOW, dry_run=True)

    saved = state.load_state(storage)
    assert result == {"wakeAgent": False, "item": None}
    assert saved["profiles"][profile.id]["cursor"] == "newest"
    assert saved["outbox"] == []


def test_first_observation_uses_complete_feed_before_poll_cap(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, _media_root = _install_paths(monkeypatch, tmp_path, config_path)
    posts = [_post(profile.id, f"publication-{index:03d}", index) for index in range(profile.max_items_per_poll + 3)]
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", lambda *_args, **_kwargs: posts)
    monkeypatch.setattr(scan.ocr, "build_backend", lambda *_args: pytest.fail("first observation must not build OCR"))

    scan.run(now=NOW, dry_run=True)

    saved = state.load_state(storage)
    assert saved["profiles"][profile.id]["cursor"] == posts[-1].publication_id
    assert saved["outbox"] == []


def test_cursor_rollover_filters_before_poll_cap_when_cursor_is_missing_from_page(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, media_root = _install_paths(monkeypatch, tmp_path, config_path)
    baseline = _post(profile.id, "baseline", 0)
    _initialize_cursor(storage, profile, baseline)
    fresh = [_post(profile.id, f"fresh-{index:03d}", index + 1) for index in range(profile.max_items_per_poll + 2)]
    feed = [baseline, *fresh]
    _install_download_and_ocr(monkeypatch, media_root)
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", lambda *_args, **_kwargs: feed)

    scan.run(now=NOW + timedelta(minutes=1), dry_run=True)
    first = state.load_state(storage)
    assert len(first["outbox"]) == profile.max_items_per_poll
    assert first["profiles"][profile.id]["cursor"] == fresh[profile.max_items_per_poll - 1].publication_id

    scan.run(now=NOW + timedelta(minutes=2), dry_run=True)
    second = state.load_state(storage)
    assert len(second["outbox"]) == profile.max_items_per_poll + 2
    assert second["profiles"][profile.id]["cursor"] == fresh[-1].publication_id


def test_source_failure_keeps_cursor_and_has_no_discord_side_effect(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, _media_root = _install_paths(monkeypatch, tmp_path, config_path)
    _initialize_cursor(storage, profile, _post(profile.id, "baseline", 0))
    calls: list[object] = []
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", lambda *_args, **_kwargs: (_ for _ in ()).throw(scan.rsshub.SourceFetchError("provider body with token=secret")))
    monkeypatch.setattr(scan.discord, "post_text", lambda *args: calls.append(args))

    scan.run(now=NOW + timedelta(minutes=1), dry_run=True)

    saved = state.load_state(storage)
    assert saved["profiles"][profile.id]["cursor"] == "baseline"
    assert saved["outbox"] == []
    assert calls == []


def test_partial_source_failure_queues_event_ocr_and_keeps_successful_assets(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, media_root = _install_paths(monkeypatch, tmp_path, config_path)
    _initialize_cursor(storage, profile, _post(profile.id, "baseline", 0))
    post = _post(
        profile.id,
        "asset-failure",
        1,
        media=(
            SourceMedia("https://cdn.example/failed.jpg", MediaKind.IMAGE, 0),
            SourceMedia("https://cdn.example/success.jpg", MediaKind.IMAGE, 1),
        ),
    )
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", lambda *_args, **_kwargs: [post])

    def download(current_post, root, *_args, **_kwargs):
        event_root = root / current_post.publication_id
        return DownloadedPublication(
            (_asset(event_root, current_post.media[1]),),
            event_root,
            (FailedAsset(current_post.media[0], "download_failed"),),
        )

    monkeypatch.setattr(scan.media, "download_publication", download)
    monkeypatch.setattr(scan.ocr, "build_backend", lambda *_args: FakeBackend())
    ocr_calls: list[int] = []

    def extract(asset, *_args):
        ocr_calls.append(asset.source.index)
        return ocr.OCRResult(
            ocr.OCRStatus.SUCCESS,
            text="The successful slide contains enough market context for analysis.",
            confidence=0.99,
            min_confidence=0.98,
            engine_id="fake",
            model_version="fake-v1",
            languages=("ind", "eng"),
        )

    monkeypatch.setattr(scan.ocr, "extract_cached", extract)

    scan.run(now=NOW + timedelta(minutes=1), dry_run=True)

    saved = state.load_state(storage)
    event = saved["outbox"][0]
    assert saved["profiles"][profile.id]["cursor"] == "asset-failure"
    assert [asset["source"]["index"] for asset in event["downloaded_publication"]["assets"]] == [1]
    assert [asset["source"]["index"] for asset in event["downloaded_publication"]["failed_assets"]] == [0]
    assert ocr_calls == [1]
    decision = state.deserialize_vision_decision(event["vision_decision"])
    assert decision.mode is vision_gate.VisionMode.VISION_PARTIAL


def test_retried_event_owns_media_before_stale_cleanup_runs(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, media_root = _install_paths(monkeypatch, tmp_path, config_path)
    baseline = _post(profile.id, "baseline", 0)
    post = _post(profile.id, "retried", 1)
    value = state.new_state()
    state.observe_publications(value, profile, [baseline], NOW, lambda _: {})
    state.queue_media_cleanup(
        value,
        f"{profile.id}:{post.publication_id}",
        profile.id,
        post.publication_id,
        str(media_root / post.publication_id),
    )
    state.observe_publications(value, profile, [post], NOW + timedelta(minutes=1), lambda item: _prepared(item, media_root))
    state.save_state(storage, value)
    cleaned: list[tuple[Path, str]] = []
    monkeypatch.setattr(scan.media, "cleanup_event_media", lambda root, event_id: cleaned.append((root, event_id)))

    stats = scan.RunStats()
    scan._retry_media_cleanup(value, storage, stats, no_post=False)

    assert cleaned == []
    assert [item["event_key"] for item in state.load_state(storage)["cleanup"]] == [f"{profile.id}:{post.publication_id}"]
    assert state.load_state(storage)["outbox"][0]["event_key"] == f"{profile.id}:{post.publication_id}"


def test_carousel_is_one_event_and_every_image_is_ocrd(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, media_root = _install_paths(monkeypatch, tmp_path, config_path)
    _initialize_cursor(storage, profile, _post(profile.id, "baseline", 0))
    carousel = _post(
        profile.id,
        "carousel",
        1,
        media=(
            SourceMedia("https://cdn.example/carousel-0.jpg", MediaKind.IMAGE, 0),
            SourceMedia("https://cdn.example/carousel-1.jpg", MediaKind.IMAGE, 1),
        ),
    )
    calls = _install_download_and_ocr(monkeypatch, media_root)
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", lambda *_args, **_kwargs: [carousel])

    result = scan.run(now=NOW + timedelta(minutes=1), dry_run=True)

    saved = state.load_state(storage)
    event = saved["outbox"][0]
    assert result["wakeAgent"] is False
    assert len(saved["outbox"]) == 1
    assert calls == [0, 1]
    assert len(event["downloaded_publication"]["assets"]) == 2
    assert len(event["ocr_results"]) == 2


@pytest.mark.parametrize(
    ("caption", "ocr_text"),
    [
        (
            "The Járngreipr SURI-HALO.",
            "Investor ownership percentage, earnings, and valuation analysis.",
        ),
        (
            "A caption with investing context.",
            "Cara berinvestasi di saham dengan mindset dan disiplin yang benar.",
        ),
    ],
)
def test_ocr_context_reaches_llm_relevance_decision(
    tmp_path,
    monkeypatch,
    config_path,
    caption,
    ocr_text,
):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, media_root = _install_paths(monkeypatch, tmp_path, config_path)
    _initialize_cursor(storage, profile, _post(profile.id, "baseline", 0))
    post = _post(
        profile.id,
        "education",
        1,
        caption=caption,
        media=(
            SourceMedia("https://cdn.example/education-0.jpg", MediaKind.IMAGE, 0),
            SourceMedia("https://cdn.example/education-1.jpg", MediaKind.IMAGE, 1),
        ),
    )
    ocr_calls = _install_download_and_ocr(monkeypatch, media_root)

    def educational_extract(asset, *_args):
        ocr_calls.append(asset.source.index)
        return ocr.OCRResult(
            ocr.OCRStatus.SUCCESS,
            text=ocr_text,
            confidence=0.99,
            min_confidence=0.98,
            engine_id="fake",
            model_version="fake-v1",
            languages=("ind", "eng"),
        )

    monkeypatch.setattr(scan.ocr, "extract_cached", educational_extract)
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", lambda *_args, **_kwargs: [post])
    heartbeats: list[str] = []
    monkeypatch.setattr(scan.discord, "post_text", lambda content, *_args: heartbeats.append(content) or "heartbeat")

    result = scan.run(now=NOW + timedelta(minutes=1), dry_run=False)

    saved = state.load_state(storage)
    assert result["wakeAgent"] is True
    assert result["item"]["event_key"].endswith(":education")
    assert len(saved["outbox"]) == 1
    assert ocr_calls == [0, 1]
    assert len(heartbeats) == 1
    assert "1 queued" in heartbeats[0]
    assert "filters:" not in heartbeats[0]


def test_ocr_failure_chooses_partial_vision_and_sparse_text_chooses_full(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, media_root = _install_paths(monkeypatch, tmp_path, config_path)
    _initialize_cursor(storage, profile, _post(profile.id, "baseline", 0))
    partial = _post(
        profile.id,
        "partial",
        1,
        media=(
            SourceMedia("https://cdn.example/partial-0.jpg", MediaKind.IMAGE, 0),
            SourceMedia("https://cdn.example/partial-1.jpg", MediaKind.IMAGE, 1),
        ),
    )
    _install_download_and_ocr(monkeypatch, media_root, ocr_failure_indexes={1})
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", lambda *_args, **_kwargs: [partial])

    scan.run(now=NOW + timedelta(minutes=1), dry_run=True)
    saved = state.load_state(storage)
    decision = state.deserialize_vision_decision(saved["outbox"][0]["vision_decision"])
    assert decision.mode is vision_gate.VisionMode.VISION_PARTIAL
    assert decision.asset_ids == (1,)

    storage2, media_root2 = _install_paths(monkeypatch, tmp_path / "sparse", config_path)
    _initialize_cursor(storage2, profile, _post(profile.id, "baseline2", 0))
    sparse = _post(profile.id, "sparse", 1, caption="", media=(SourceMedia("https://cdn.example/sparse.jpg", MediaKind.IMAGE, 0),))
    _install_download_and_ocr(monkeypatch, media_root2)
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", lambda *_args, **_kwargs: [sparse])

    scan.run(now=NOW + timedelta(minutes=1), dry_run=True)
    sparse_state = state.load_state(storage2)
    sparse_decision = state.deserialize_vision_decision(sparse_state["outbox"][0]["vision_decision"])
    assert sparse_decision.mode is vision_gate.VisionMode.VISION_FULL
    assert sparse_decision.asset_ids == (0,)


def test_reel_frames_are_ocrd_and_persisted_for_analysis(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, media_root = _install_paths(monkeypatch, tmp_path, config_path)
    _initialize_cursor(storage, profile, _post(profile.id, "baseline", 0))
    reel = _post(
        profile.id,
        "reel",
        1,
        kind=PublicationKind.REEL,
        media=(
            SourceMedia("https://cdn.example/reel.mp4", MediaKind.VIDEO, 0),
            SourceMedia("https://cdn.example/reel-cover.jpg", MediaKind.IMAGE, 1),
        ),
    )
    ocr_calls = _install_download_and_ocr(monkeypatch, media_root)

    def sampled(video_path, cover_path, root, max_frames):
        assert video_path.name == "0.mp4"
        assert cover_path.name == "1.jpg"
        frame_path = root / "reel-frames" / "1.jpg"
        frame = _asset(root / "reel-frames", SourceMedia(frame_path.as_uri(), MediaKind.IMAGE, 1))
        cover = DownloadedAsset(SourceMedia(cover_path.as_uri(), MediaKind.IMAGE, 0), cover_path, "b" * 64, 1, "image/jpeg")
        return (cover, frame), ()

    monkeypatch.setattr(scan.media, "sample_reel_frames_observed", sampled)
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", lambda *_args, **_kwargs: [reel])

    scan.run(now=NOW + timedelta(minutes=1), dry_run=True)

    saved = state.load_state(storage)
    event = saved["outbox"][0]
    assert ocr_calls == [1, 2]
    assert [item["source"]["kind"] for item in event["downloaded_publication"]["assets"]] == ["video", "image", "image"]
    assert [item["source"]["index"] for item in event["downloaded_publication"]["assets"]] == [0, 1, 2]


def test_reel_delivery_sends_only_first_image_not_sampled_frames(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, media_root = _install_paths(monkeypatch, tmp_path, config_path)
    _initialize_cursor(storage, profile, _post(profile.id, "baseline", 0))
    reel = _post(
        profile.id,
        "deliver-reel",
        1,
        kind=PublicationKind.REEL,
        media=(
            SourceMedia("https://cdn.example/reel.mp4", MediaKind.VIDEO, 0),
            SourceMedia("https://cdn.example/reel-cover.jpg", MediaKind.IMAGE, 1),
        ),
    )
    prepared = _prepared(reel, media_root)
    event = _queued_event(storage, profile, reel, prepared, NOW + timedelta(minutes=1))
    value = state.load_state(storage)
    claimed = state.claim_oldest_agent(value, {profile.id: profile}, datetime.now(scan.WIB))
    assert claimed is not None
    state.save_state(storage, value)
    legs: list[tuple[str, str]] = []
    monkeypatch.setattr(scan.discord, "post_text", lambda *_args: legs.append(("text", "text")) or "text-id")
    monkeypatch.setattr(scan.discord, "post_media", lambda path, *_args: legs.append(("media", path.name)) or f"media-{path.name}")
    monkeypatch.setattr(scan.media, "cleanup_event_media", lambda *_args: None)

    result = scan.submit_analysis_payload({
        "event_key": event["event_key"],
        "is_relevant": True,
        "title": "Macro: Reel",
        "summary": "*(Ringkasan)* Reel",
        "route": "macro_news",
    })

    assert result == {"submitted": True, "ignored": False, "delivered": 1}
    assert [value for kind, value in legs if kind == "media"] == ["1.jpg"]


def test_delivery_media_falls_back_to_first_asset_when_no_image_exists(tmp_path, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    reel = _post(
        profile.id,
        "video-only-reel",
        1,
        kind=PublicationKind.REEL,
        media=(SourceMedia("https://cdn.example/reel.mp4", MediaKind.VIDEO, 0),),
    )
    media_root = tmp_path / reel.publication_id
    downloaded = DownloadedPublication((_asset(media_root, reel.media[0]),), media_root)

    selected = scan._delivery_media(reel, downloaded)

    assert [asset.path.name for asset in selected] == ["0.mp4"]


def test_delivery_rejects_swapped_source_locator_identity(tmp_path, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    post = _post(
        profile.id,
        "swapped-delivery",
        1,
        media=(
            SourceMedia("https://cdn.example/first.jpg?token=first", MediaKind.IMAGE, 0),
            SourceMedia("https://cdn.example/second.jpg?token=second", MediaKind.IMAGE, 1),
        ),
    )
    media_root = tmp_path / post.publication_id
    first = _asset(media_root, post.media[0])
    second = _asset(media_root, post.media[1])
    swapped = DownloadedPublication(
        (
            DownloadedAsset(
                SourceMedia(post.media[1].url, MediaKind.IMAGE, 0),
                first.path,
                first.sha256,
                first.size_bytes,
                first.content_type,
            ),
            DownloadedAsset(
                SourceMedia(post.media[0].url, MediaKind.IMAGE, 1),
                second.path,
                second.sha256,
                second.size_bytes,
                second.content_type,
            ),
        ),
        media_root,
    )

    with pytest.raises(ValueError, match="state is invalid"):
        scan._source_media_by_index(post, swapped)


def test_no_post_does_not_send_heartbeat_or_claim_agent(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, media_root = _install_paths(monkeypatch, tmp_path, config_path)
    _initialize_cursor(storage, profile, _post(profile.id, "baseline", 0))
    _install_download_and_ocr(monkeypatch, media_root)
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_NO_POST", "1")
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", lambda *_args, **_kwargs: [_post(profile.id, "new", 1)])
    calls: list[object] = []
    monkeypatch.setattr(scan.discord, "post_text", lambda *args: calls.append(args))
    claimed: list[object] = []
    monkeypatch.setattr(scan.state, "claim_oldest_agent", lambda *args: claimed.append(args) or pytest.fail("NO_POST must not claim an agent"))

    result = scan.run(now=NOW + timedelta(minutes=1), dry_run=True)

    assert result == {"wakeAgent": False, "item": None}
    assert calls == []
    assert claimed == []


def test_no_post_requires_isolated_paths_before_creating_lock_or_media(tmp_path, monkeypatch, config_path):
    for name in (
        "INSTAGRAM_POST_WATCH_NO_POST",
        "INSTAGRAM_POST_WATCH_STATE_PATH",
        "INSTAGRAM_POST_WATCH_MEDIA_ROOT",
        "INSTAGRAM_POST_WATCH_OCR_CACHE_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(scan, "config_path", lambda: config_path)

    with pytest.raises(ValueError, match="explicit isolated state and media paths"):
        scan.run(now=NOW, dry_run=True)

    assert not (tmp_path / "state").exists()


def test_batch_preparation_failure_persists_cleanup_for_every_attempted_root(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, media_root = _install_paths(monkeypatch, tmp_path, config_path)
    _initialize_cursor(storage, profile, _post(profile.id, "baseline", 0))
    posts = [_post(profile.id, "prepared", 1), _post(profile.id, "failed-later", 2)]
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", lambda *_args, **_kwargs: posts)
    _install_download_and_ocr(monkeypatch, media_root)

    def download(post, root, _session, _limits, *, allow_partial=False):
        del allow_partial
        if post.publication_id == "failed-later":
            raise RuntimeError("provider body token=secret")
        event_root = root / post.publication_id
        return DownloadedPublication(tuple(_asset(event_root, source) for source in post.media), event_root)

    monkeypatch.setattr(scan.media, "download_publication", download)

    scan.run(now=NOW + timedelta(minutes=1), dry_run=True)

    saved = state.load_state(storage)
    assert {item["event_key"] for item in saved["cleanup"]} == {
        f"{profile.id}:prepared",
        f"{profile.id}:failed-later",
    }
    assert all(item["media_root"] == str(media_root / item["publication_id"]) for item in saved["cleanup"])
    assert saved["outbox"] == []


def test_cleanup_failure_remains_retryable(tmp_path, monkeypatch, config_path):
    storage, media_root = _install_paths(monkeypatch, tmp_path, config_path)
    value = state.new_state()
    state.queue_media_cleanup(value, "profile:publication", "profile", "publication", str(media_root / "publication"))
    state.save_state(storage, value)
    monkeypatch.setattr(scan.media, "cleanup_event_media", lambda *_args: (_ for _ in ()).throw(RuntimeError("cannot remove")))

    stats = scan.RunStats()
    scan._retry_media_cleanup(value, storage, stats, no_post=False)

    saved = state.load_state(storage)
    assert saved["cleanup"][0]["attempts"] == 1
    assert saved["cleanup"][0]["last_error"] == "media cleanup failed"
    assert stats.degraded is True


def test_heartbeat_and_fatal_never_expose_urls_paths_or_secrets():
    stats = scan.RunStats()
    stats.note_error("provider https://cdn.example/image.jpg?token=secret /Users/praya/private.jpg")

    heartbeat = scan.format_heartbeat(NOW, stats)
    fatal = scan.format_fatal(NOW, "token=secret /home/praya/.env https://rss.example/body")

    for value in (heartbeat, fatal):
        assert "https://" not in value
        assert "secret" not in value
        assert "/Users/" not in value
        assert "/home/" not in value
    assert heartbeat.endswith(f"{scan.OWNER_MENTION} ⚠️")
    assert fatal.endswith(scan.OWNER_MENTION)


def test_discord_nonce_fits_discord_limit():
    value = scan.discord.nonce("heartbeat", "202608261035")

    assert len(value) == 24
    assert len(value) <= 25
    assert value == hashlib.sha256(b"instagram-post-watch:heartbeat:202608261035").hexdigest()[:24]


def test_filtered_submission_cleans_owned_media(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, media_root = _install_paths(monkeypatch, tmp_path, config_path)
    baseline = _post(profile.id, "baseline", 0)
    _initialize_cursor(storage, profile, baseline)
    post = _post(profile.id, "filtered", 1)
    prepared = _prepared(post, media_root)
    event = _queued_event(storage, profile, post, prepared, NOW + timedelta(minutes=1))
    value = state.load_state(storage)
    claimed = state.claim_oldest_agent(value, {profile.id: profile}, datetime.now(scan.WIB))
    assert claimed["event_key"] == event["event_key"]
    state.save_state(storage, value)
    cleaned: list[tuple[Path, str]] = []
    monkeypatch.setattr(scan.media, "cleanup_event_media", lambda root, event_id: cleaned.append((root, event_id)))

    result = scan.submit_analysis_payload({"event_key": event["event_key"], "is_relevant": False})

    saved = state.load_state(storage)
    assert result == {"submitted": True, "ignored": True, "delivered": 0}
    assert saved["outbox"] == []
    assert saved["filtered_since_last_heartbeat"] == 1
    assert cleaned == [(media_root, post.publication_id)]


def test_valid_submission_sends_text_before_first_carousel_image_without_promotion_guard(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, media_root = _install_paths(monkeypatch, tmp_path, config_path)
    _initialize_cursor(storage, profile, _post(profile.id, "baseline", 0))
    post = _post(
        profile.id,
        "delivery",
        1,
        caption="Premium research subscription is live",
        media=(
            SourceMedia("https://cdn.example/first.jpg", MediaKind.IMAGE, 0),
            SourceMedia("https://cdn.example/second.jpg", MediaKind.IMAGE, 1),
        ),
    )
    prepared = _prepared(post, media_root)
    event = _queued_event(storage, profile, post, prepared, NOW + timedelta(minutes=1))
    value = state.load_state(storage)
    state.claim_oldest_agent(value, {profile.id: profile}, datetime.now(scan.WIB))
    state.save_state(storage, value)
    legs: list[tuple[str, object]] = []
    monkeypatch.setattr(scan.discord, "post_text", lambda content, *_args: legs.append(("text", content)) or "text-id")
    monkeypatch.setattr(scan.discord, "post_media", lambda path, *_args: legs.append(("media", path.name)) or f"media-{path.name}")
    monkeypatch.setattr(scan.media, "cleanup_event_media", lambda *_args: None)
    payload = {
        "event_key": event["event_key"],
        "is_relevant": True,
        "title": "Macro: Market conditions",
        "summary": "*(Ringkasan)* Market conditions remain important",
        "route": "macro_news",
    }

    result = scan.submit_analysis_payload(payload)

    saved = state.load_state(storage)
    assert result == {"submitted": True, "ignored": False, "delivered": 1}
    assert [kind for kind, _value in legs] == ["text", "media"]
    assert [value for kind, value in legs if kind == "media"] == ["0.jpg"]
    assert saved["outbox"] == []
    assert saved["deliveries"][0]["text_message_ids"] == ["text-id"]
    assert saved["deliveries"][0]["media_message_ids"] == ["media-0.jpg"]


def test_delivery_retry_keeps_failed_leg_and_retries_independently(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, media_root = _install_paths(monkeypatch, tmp_path, config_path)
    _initialize_cursor(storage, profile, _post(profile.id, "baseline", 0))
    post = _post(profile.id, "retry", 1)
    prepared = _prepared(post, media_root)
    event = _queued_event(storage, profile, post, prepared, NOW + timedelta(minutes=1))
    value = state.load_state(storage)
    state.claim_oldest_agent(value, {profile.id: profile}, datetime.now(scan.WIB))
    state.submit_analysis(value, event["event_key"], {"title": "Macro: Retry", "summary": "*(Ringkasan)* Retry", "route": "macro", "is_relevant": True}, datetime.now(scan.WIB))
    state.save_state(storage, value)
    failures = iter([True, False])
    text_calls = []

    def post_text(*args):
        text_calls.append(args[0])
        if next(failures):
            raise RuntimeError("provider body")
        return "text-id"

    monkeypatch.setattr(scan.discord, "post_text", post_text)
    stats = scan.RunStats()
    profiles = {profile.id: profile}
    current = state.load_state(storage)
    assert scan._deliver(current, profiles, 0, False, storage, stats, NOW + timedelta(minutes=3)) is False
    assert current["outbox"][0]["text_index"] == 0
    assert scan._deliver(current, profiles, 0, False, storage, stats, NOW + timedelta(minutes=3)) is True
    assert current["outbox"][0]["text_index"] == 1
    assert text_calls == [text_calls[0], text_calls[0]]


def test_expired_agent_lease_is_reclaimed_by_next_non_no_post_run(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, media_root = _install_paths(monkeypatch, tmp_path, config_path)
    _initialize_cursor(storage, profile, _post(profile.id, "baseline", 0))
    post = _post(profile.id, "leased", 1)
    prepared = _prepared(post, media_root)
    event = _queued_event(storage, profile, post, prepared, NOW + timedelta(minutes=1))
    value = state.load_state(storage)
    claimed = state.claim_oldest_agent(value, {profile.id: profile}, NOW - timedelta(minutes=20))
    assert claimed is not None
    state.save_state(storage, value)
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", lambda *_args, **_kwargs: [])
    heartbeats: list[str] = []
    monkeypatch.setattr(scan.discord, "post_text", lambda content, *_args: heartbeats.append(content) or "heartbeat")
    monkeypatch.setattr(scan.agent_protocol, "agent_item", lambda _profile, _event: {
        "event_key": event["event_key"],
        "profile_handle": profile.handle,
        "profile_name": profile.display_name,
        "post_url": post.url,
        "post_kind": "post",
        "caption_text": "",
        "post_text": "source",
        "ocr_assets": [],
        "ocr_min_confidence": profile.ocr_min_confidence,
        "vision_mode": "text_only",
        "vision_asset_root": str(media_root / post.publication_id),
        "vision_asset_ids": [],
        "vision_asset_path_ids": [],
        "vision_asset_paths": [],
        "media_count": 1,
        "title_required": True,
        "summary_required": True,
        "route_required": True,
        "relevance_required": True,
        "relevance_guard_required": False,
        "instruction": "trusted",
    })
    monkeypatch.setattr(scan.agent_protocol, "build_wake_payload", lambda item: {"wakeAgent": item is not None, "item": item})

    result = scan.run(now=NOW, dry_run=False)

    assert result["wakeAgent"] is True
    renewed = state.load_state(storage)["outbox"][0]
    assert renewed["agent_phase"] == "awaiting_agent"
    assert renewed["agent_lease_until"] != claimed["agent_lease_until"]
    assert any("reclaimed 1 expired agent lease(s)" in content and "⚠️" in content for content in heartbeats)


def test_direct_market_disclosure_cannot_be_marked_irrelevant(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, media_root = _install_paths(monkeypatch, tmp_path, config_path)
    _initialize_cursor(storage, profile, _post(profile.id, "baseline", 0))
    post = _post(profile.id, "disclosure", 1, caption="Revenue increased and the issuer announced a buyback.")
    event = _queued_event(storage, profile, post, _prepared(post, media_root), NOW + timedelta(minutes=1))
    value = state.load_state(storage)
    state.claim_oldest_agent(value, {profile.id: profile}, datetime.now(scan.WIB))
    state.save_state(storage, value)
    heartbeats: list[str] = []
    monkeypatch.setattr(scan.discord, "post_text", lambda content, *_args: heartbeats.append(content) or "heartbeat")

    with pytest.raises(ValueError, match="direct market disclosure"):
        scan.submit_analysis_payload({"event_key": event["event_key"], "is_relevant": False})

    saved = state.load_state(storage)
    assert saved["outbox"][0]["agent_phase"] == "awaiting_agent"
    assert saved["outbox"][0]["last_error"] == "analysis submission failed"
    assert len(heartbeats) == 1
    assert heartbeats[0].startswith("🫀 instagram-post")


def test_invalid_submission_heartbeat_redacts_provider_details_and_preserves_error(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, media_root = _install_paths(monkeypatch, tmp_path, config_path)
    _initialize_cursor(storage, profile, _post(profile.id, "baseline", 0))
    post = _post(profile.id, "invalid-submission", 1)
    event = _queued_event(storage, profile, post, _prepared(post, media_root), NOW + timedelta(minutes=1))
    value = state.load_state(storage)
    state.claim_oldest_agent(value, {profile.id: profile}, NOW)
    state.save_state(storage, value)
    monkeypatch.setattr(
        scan.agent_protocol,
        "validate_submission",
        lambda *_args: (_ for _ in ()).throw(ValueError("provider token=secret https://provider.example/body")),
    )
    heartbeats: list[str] = []
    monkeypatch.setattr(scan.discord, "post_text", lambda content, *_args: heartbeats.append(content) or "heartbeat")

    with pytest.raises(ValueError, match="provider token=secret"):
        scan.submit_analysis_payload({"event_key": event["event_key"], "is_relevant": True})

    saved = state.load_state(storage)
    assert saved["outbox"][0]["last_error"] == "analysis submission failed"
    assert len(heartbeats) == 1
    assert "secret" not in heartbeats[0]
    assert "https://" not in heartbeats[0]


def test_discord_delivery_failure_is_heartbeat_visible_and_keeps_event_error(tmp_path, monkeypatch, config_path):
    profile = config.load_watch_config(config_path).profiles[0]
    storage, media_root = _install_paths(monkeypatch, tmp_path, config_path)
    _initialize_cursor(storage, profile, _post(profile.id, "baseline", 0))
    post = _post(profile.id, "delivery-failure", 1)
    event = _queued_event(storage, profile, post, _prepared(post, media_root), NOW + timedelta(minutes=1))
    value = state.load_state(storage)
    state.claim_oldest_agent(value, {profile.id: profile}, NOW)
    state.submit_analysis(
        value,
        event["event_key"],
        {"title": "Macro: failure", "summary": "*(Ringkasan)* failure", "route": "macro", "is_relevant": True},
        NOW,
    )
    state.save_state(storage, value)
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", lambda *_args, **_kwargs: [])
    heartbeats: list[str] = []

    def post_text(content, *_args):
        if content.startswith("🫀"):
            heartbeats.append(content)
            return "heartbeat"
        raise RuntimeError("Discord provider token=secret")

    monkeypatch.setattr(scan.discord, "post_text", post_text)

    scan.run(now=NOW + timedelta(minutes=1), dry_run=False)

    saved = state.load_state(storage)
    assert saved["outbox"][0]["last_error"] == "Discord delivery failed"
    assert len(heartbeats) == 1
    assert "Discord delivery failed" in heartbeats[0]
    assert "secret" not in heartbeats[0]


def test_delivery_drain_caps_legs_and_marks_remaining_backlog(tmp_path, config_path, monkeypatch):
    profile = config.load_watch_config(config_path).profiles[0]
    value = {
        "outbox": [
            {
                "profile_id": profile.id,
                "event_key": f"{profile.id}:publication-{index}",
                "ready_after": None,
                "agent_phase": "ready",
            }
            for index in range(scan.MAX_DELIVERY_LEGS_PER_INVOCATION + 1)
        ]
    }
    calls: list[int] = []

    def deliver(current, _profiles, event_index, _dry_run, _storage, stats, _now):
        calls.append(event_index)
        stats.delivery_legs += 1
        current["outbox"].pop(event_index)
        return True

    monkeypatch.setattr(scan, "_deliver", deliver)
    stats = scan.RunStats()
    scan._drain_deliveries(value, {profile.id: profile}, tmp_path / "state.json", stats, NOW)

    assert len(calls) == scan.MAX_DELIVERY_LEGS_PER_INVOCATION
    assert len(value["outbox"]) == 1
    assert stats.degraded is True
    assert stats.needs_attention is True
    assert any("delivery backlog remains" in reason for reason in stats.reasons)


def test_wrapper_preserves_submit_arguments_and_exit_status(tmp_path):
    home = tmp_path / "home"
    fake_python = tmp_path / "fake-python"
    capture = tmp_path / "capture.txt"
    fake_python.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CAPTURE\"\nexit 7\n", encoding="utf-8")
    fake_python.chmod(0o755)
    scanner = home / ".agents" / "skills" / "instagram-post-watch" / "bin" / "scan.py"
    scanner.parent.mkdir(parents=True)
    scanner.write_text("# fake scanner\n", encoding="utf-8")
    env_file = home / ".hermes" / ".env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("DISCORD_BOT_TOKEN=not-for-output\nOTHER=ignored\n", encoding="utf-8")

    completed = subprocess.run(
        [
            str(Path(__file__).resolve().parent.parent / "bin" / "instagram-post-watch.sh"),
            "submit-analysis",
            "--json",
            '{"event_key":"profile:publication"}',
        ],
        env={**os_environ(), "HOME": str(home), "INSTAGRAM_POST_WATCH_PY": str(fake_python), "CAPTURE": str(capture)},
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 7
    assert capture.read_text(encoding="utf-8").splitlines() == [str(scanner), "submit-analysis", "--json", '{"event_key":"profile:publication"}']
    assert "not-for-output" not in completed.stdout
    assert "not-for-output" not in completed.stderr


def test_wrapper_rejects_no_post_without_isolated_paths(tmp_path):
    fake_python = tmp_path / "fake-python"
    fake_python.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
    fake_python.chmod(0o755)

    completed = subprocess.run(
        [str(Path(__file__).resolve().parent.parent / "bin" / "instagram-post-watch.sh")],
        env={
            **os_environ(),
            "HOME": str(tmp_path / "home"),
            "INSTAGRAM_POST_WATCH_PY": str(fake_python),
            "INSTAGRAM_POST_WATCH_NO_POST": "1",
        },
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "requires an absolute INSTAGRAM_POST_WATCH_STATE_PATH" in completed.stderr


def os_environ() -> dict[str, str]:
    import os

    return dict(os.environ)
