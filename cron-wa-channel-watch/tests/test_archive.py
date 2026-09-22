from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

import archive
from event_queue import enqueue
from models import ChannelEvent, ChannelMedia
import state as watcher_state


def event(*, text: str = "Source message") -> ChannelEvent:
    return ChannelEvent(
        channel_jid="120363405187024421@newsletter",
        message_id="ABC-001",
        published_at=datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc),
        text=text,
        links=("https://example.test/source",),
        media=(ChannelMedia(kind="image", index=0, mime="image/jpeg", path="/staging/chart.jpg"),),
        received_at=datetime(2026, 9, 21, 9, 31, tzinfo=timezone.utc),
    )


def test_ensure_is_atomic_idempotent_and_private(tmp_path):
    result = archive.ensure(tmp_path, "bri-danareksa-sekuritas", event(), None)

    assert result.created is True
    assert stat.S_IMODE(result.record_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(result.record_path.parent.stat().st_mode) == 0o700
    assert archive.ensure(tmp_path, "bri-danareksa-sekuritas", event(), None).created is False
    assert archive.verify(tmp_path)["invalid"] == 0


def test_ensure_deduplicates_the_same_source_when_receipt_time_changes(tmp_path):
    source = event()
    redelivered = ChannelEvent(
        channel_jid=source.channel_jid,
        message_id=source.message_id,
        published_at=source.published_at,
        text=source.text,
        links=source.links,
        media=source.media,
        received_at=datetime(2026, 9, 21, 10, 31, tzinfo=timezone.utc),
    )

    assert archive.ensure(tmp_path, "bri-danareksa-sekuritas", source, None).created is True
    assert archive.ensure(tmp_path, "bri-danareksa-sekuritas", redelivered, None).created is False
    stored = archive.query(tmp_path, event_key=source.event_key)[0]
    assert stored.data["received_at"] == "2026-09-21T09:31:00Z"


def test_query_writes_raw_export_only_to_explicit_private_path(tmp_path):
    archive.ensure(tmp_path, "ins", event(), None)
    export_path = tmp_path / "review.jsonl"

    result = archive.export(tmp_path, profile_id="ins", output=export_path, format="jsonl")

    assert result["exported"] == 1
    assert stat.S_IMODE(export_path.stat().st_mode) == 0o600
    assert json.loads(export_path.read_text(encoding="utf-8"))["text"] == "Source message"


def test_collision_is_rejected_and_prune_is_dry_run(tmp_path):
    archive.ensure(tmp_path, "ins", event(), None)

    with pytest.raises(ValueError, match="collision"):
        archive.ensure(tmp_path, "ins", event(text="changed source"), None)

    assert archive.prune(tmp_path, before=date(2025, 9, 21), apply=False)["deleted"] == 0
    assert archive.verify(tmp_path)["valid"] == 1


def test_rejects_invalid_ids_bounds_existing_exports_and_relative_apply_root(tmp_path):
    archive.ensure(tmp_path, "ins", event(), None)

    with pytest.raises(ValueError, match="profile ID"):
        archive.ensure(tmp_path, "not/a/profile", event(), None)
    with pytest.raises(ValueError, match="start"):
        archive.query(tmp_path, start=date(2026, 9, 22), end=date(2026, 9, 21))
    output = tmp_path / "exists.jsonl"
    output.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        archive.export(tmp_path, profile_id="ins", output=output, format="jsonl")
    with pytest.raises(ValueError, match="absolute"):
        archive.prune(Path("relative-archive"), before=date(2025, 9, 21), apply=True)


def test_query_and_export_support_bounded_layout_filters(tmp_path):
    source = event(text="*Morning note*\n\n- First point\n- Second point")
    archive.ensure(tmp_path, "ins", source, None)
    signature = archive.layout_signature_for_text(source.text)

    results = archive.query(
        tmp_path,
        profile_id="ins",
        start=date(2026, 9, 21),
        end=date(2026, 9, 21),
        event_key=source.event_key,
        layout_signature=signature,
        limit=1,
    )
    export_path = tmp_path / "filtered.md"
    exported = archive.export(
        tmp_path,
        profile_id="ins",
        output=export_path,
        format="markdown",
        layout_signature=signature,
        limit=1,
    )

    assert [record.event_key for record in results] == [source.event_key]
    assert exported == {"exported": 1}
    assert source.text in export_path.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="limit"):
        archive.query(tmp_path, limit=501)


def test_prune_enforces_retention_and_collects_orphaned_archive_media(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    image = staging / "old-chart.jpg"
    image.write_bytes(b"old chart")
    source = ChannelEvent(
        channel_jid="120363405187024421@newsletter",
        message_id="OLD-001",
        published_at=datetime(2025, 9, 20, 9, 30, tzinfo=timezone.utc),
        text="Old source message",
        links=(),
        media=(ChannelMedia(kind="image", index=0, mime="image/jpeg", path=str(image)),),
        received_at=datetime(2025, 9, 20, 9, 31, tzinfo=timezone.utc),
    )
    archive.ensure(tmp_path, "ins", source, None, staging_root=staging)

    with pytest.raises(ValueError, match="retention"):
        archive.prune(tmp_path, before=date(2025, 9, 22), today=date(2026, 9, 21))
    dry_run = archive.prune(tmp_path, before=date(2025, 9, 21), today=date(2026, 9, 21))
    applied = archive.prune(tmp_path, before=date(2025, 9, 21), apply=True, today=date(2026, 9, 21))

    assert dry_run == {"candidates": 1, "deleted": 0, "media_candidates": 1, "media_deleted": 0}
    assert applied == {"candidates": 1, "deleted": 1, "media_candidates": 1, "media_deleted": 1}
    assert archive.verify(tmp_path) == {"checked": 0, "valid": 0, "invalid": 0}


def test_verify_detects_checksum_mismatch_and_record_never_retains_source_path(tmp_path):
    result = archive.ensure(tmp_path, "ins", event(), 7)
    record = json.loads(result.record_path.read_text(encoding="utf-8"))

    assert record["media"] == [
        {
            "archive_path": None,
            "bytes": None,
            "capture_status": "not_captured",
            "index": 0,
            "kind": "image",
            "mime": "image/jpeg",
            "sha256": None,
        }
    ]
    record["text"] = "tampered"
    result.record_path.write_text(json.dumps(record), encoding="utf-8")

    assert archive.verify(tmp_path)["invalid"] == 1


def test_ensure_captures_only_staged_media_and_can_complete_a_prior_record(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    image = staging / "chart.jpg"
    image.write_bytes(b"chart")
    source = ChannelEvent(
        channel_jid="120363405187024421@newsletter",
        message_id="CAPTURE-001",
        published_at=datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc),
        text="Source message",
        links=(),
        media=(ChannelMedia(kind="image", index=0, mime="image/jpeg", path=str(image)),),
        received_at=datetime(2026, 9, 21, 9, 31, tzinfo=timezone.utc),
    )

    initial = archive.ensure(tmp_path, "ins", source, None)
    assert json.loads(initial.record_path.read_text(encoding="utf-8"))["media"][0]["capture_status"] == "not_captured"

    completed = archive.ensure(tmp_path, "ins", source, None, staging_root=staging)
    record = json.loads(completed.record_path.read_text(encoding="utf-8"))

    assert completed.created is False
    assert record["media"][0]["capture_status"] == "captured"
    assert record["media"][0]["archive_path"] != str(image)
    assert not image.exists()
    assert archive.verify(tmp_path) == {"checked": 1, "valid": 1, "invalid": 0}


def test_ensure_marks_outside_staging_media_unavailable_without_reading_it(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"outside")
    source = ChannelEvent(
        channel_jid="120363405187024421@newsletter",
        message_id="CAPTURE-002",
        published_at=datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc),
        text="Source message",
        links=(),
        media=(ChannelMedia(kind="image", index=0, mime="image/jpeg", path=str(outside)),),
        received_at=datetime(2026, 9, 21, 9, 31, tzinfo=timezone.utc),
    )

    result = archive.ensure(tmp_path, "ins", source, None, staging_root=staging)
    record = json.loads(result.record_path.read_text(encoding="utf-8"))

    assert record["media"][0]["capture_status"] == "unavailable"
    assert record["media"][0]["archive_path"] is None


def test_archive_helper_accepts_explicit_local_runtime_overrides():
    package = Path(__file__).resolve().parents[1]
    environment = os.environ | {
        "WHATSAPP_CHANNEL_WATCH_PY": sys.executable,
        "WHATSAPP_CHANNEL_WATCH_ARCHIVE_SCRIPT": str(package / "bin" / "archive.py"),
    }

    result = subprocess.run(
        [str(package / "bin" / "bursawatch-wa-channel-archive.sh"), "--help"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Inspect immutable WhatsApp Channel source archives" in result.stdout


def test_verifier_accepts_the_node_bridge_archive_record_shape(tmp_path):
    event_key = "12345@newsletter:ABC-001"
    media_bytes = b"Node bridge fixture"
    media_digest = hashlib.sha256(media_bytes).hexdigest()
    record = {
        "schema_version": 1,
        "event_key": event_key,
        "profile_id": "ins",
        "channel_jid": "12345@newsletter",
        "message_id": "ABC-001",
        "published_at": "2025-08-24T01:46:40.000Z",
        "received_at": "2026-09-21T09:31:00.000Z",
        "text": "BBCA mencatat laba bersih naik",
        "links": [],
        "media": [
            {
                "kind": "image",
                "index": 0,
                "mime": "image/jpeg",
                "capture_status": "captured",
                "archive_path": f"media/{media_digest}",
                "sha256": media_digest,
                "bytes": len(media_bytes),
            }
        ],
        "config_revision": None,
    }
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    record["checksum"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    record_path = tmp_path / "ins" / "2025" / "08" / "24" / f"{hashlib.sha256(event_key.encode()).hexdigest()}.json"
    record_path.parent.mkdir(parents=True)
    record_path.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    media_path = tmp_path / "media" / media_digest
    media_path.parent.mkdir()
    media_path.write_bytes(media_bytes)

    assert archive.verify(tmp_path) == {"checked": 1, "valid": 1, "invalid": 0}
    assert [item.event_key for item in archive.query(tmp_path, profile_id="ins")] == [event_key]


def test_verifier_requires_captured_media_to_be_archive_owned_and_intact(tmp_path):
    event_key = "12345@newsletter:ABC-009"
    media_bytes = b"verified chart image"
    media_digest = hashlib.sha256(media_bytes).hexdigest()
    record = {
        "schema_version": 1,
        "event_key": event_key,
        "profile_id": "ins",
        "channel_jid": "12345@newsletter",
        "message_id": "ABC-009",
        "published_at": "2025-08-24T01:46:40.000Z",
        "received_at": "2026-09-21T09:31:00.000Z",
        "text": "BBCA mencatat laba bersih naik",
        "links": [],
        "media": [{
            "kind": "image", "index": 0, "mime": "image/jpeg", "capture_status": "captured",
            "archive_path": f"media/{media_digest}", "sha256": media_digest, "bytes": len(media_bytes),
        }],
        "config_revision": None,
    }
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    record["checksum"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    record_path = tmp_path / "ins" / "2025" / "08" / "24" / f"{hashlib.sha256(event_key.encode()).hexdigest()}.json"
    record_path.parent.mkdir(parents=True)
    record_path.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    media_path = tmp_path / "media" / media_digest
    media_path.parent.mkdir()
    media_path.write_bytes(media_bytes)

    assert archive.verify(tmp_path)["valid"] == 1
    media_path.write_bytes(b"tampered")
    assert archive.verify(tmp_path)["invalid"] == 1


def test_cutover_plan_is_read_only_and_apply_sets_only_the_future_cursor(tmp_path, monkeypatch):
    queue_dir = tmp_path / "queue"
    state_path = tmp_path / "state.json"
    archive_root = tmp_path / "archive"
    enqueue(queue_dir, event(text="first source https://example.test/source"))
    enqueue(
        queue_dir,
        ChannelEvent(
            channel_jid="120363405187024421@newsletter",
            message_id="ABC-002",
            published_at=datetime(2026, 9, 21, 10, 30, tzinfo=timezone.utc),
            text="second source",
            links=(),
            media=(),
            received_at=datetime(2026, 9, 21, 10, 31, tzinfo=timezone.utc),
        ),
    )
    original_state = {
        "version": 1,
        "profiles": {},
        "outbox": [{"event_key": "old-outbox", "profile_id": "ins", "agent_phase": "ready"}],
    }
    watcher_state.save(state_path, original_state)

    plan = archive.cutover_plan(
        queue_dir,
        state_path,
        profile_id="ins",
        channel_jid="120363405187024421@newsletter",
    )

    assert plan["event_count"] == 2
    assert plan["proposed_cursor"]["event_key"].endswith(":ABC-002")
    assert plan["existing_outbox_count"] == 1
    assert watcher_state.load(state_path) == original_state
    with pytest.raises(PermissionError, match="ALLOW_CUTOVER_APPLY"):
        archive.cutover_apply(
            archive_root,
            queue_dir,
            state_path,
            profile_id="ins",
            channel_jid="120363405187024421@newsletter",
        )

    monkeypatch.setenv("WHATSAPP_CHANNEL_WATCH_ALLOW_CUTOVER_APPLY", "1")
    applied = archive.cutover_apply(
        archive_root,
        queue_dir,
        state_path,
        profile_id="ins",
        channel_jid="120363405187024421@newsletter",
    )

    assert applied["archived"] == 2
    assert watcher_state.load(state_path)["profiles"]["ins"]["cursor"] == plan["proposed_cursor"]
    assert watcher_state.load(state_path)["outbox"] == original_state["outbox"]
    assert archive.verify(archive_root) == {"checked": 2, "valid": 2, "invalid": 0}
    assert [record.event_key for record in archive.query(archive_root)] == [
        "120363405187024421@newsletter:ABC-001",
        "120363405187024421@newsletter:ABC-002",
    ]
    assert (archive_root / "cutovers" / "ins" / "state-before.json").exists()


def test_quarantine_outbox_is_guarded_reversible_and_cutover_bounded(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    archive_root = tmp_path / "archive"
    channel_jid = "120363419226413141@newsletter"
    cutoff = {"published_at": "2026-09-22T01:29:39Z", "event_key": f"{channel_jid}:cutover"}

    def record(message_id, published_at, phase="pending", routable=True):
        return {
            "event_key": f"{channel_jid}:{message_id}",
            "profile_id": "bri-danareksa-sekuritas",
            "event": {
                "channel_jid": channel_jid,
                "message_id": message_id,
                "event_key": f"{channel_jid}:{message_id}",
                "published_at": published_at,
            },
            "agent_phase": phase,
            "routable": routable,
        }

    original_state = {
        "version": 1,
        "profiles": {
            "bri-danareksa-sekuritas": {
                "cursor": cutoff,
                "cutover_complete": True,
            }
        },
        "outbox": [
            record("old-ready", "2026-09-15T06:39:03Z", phase="ready"),
            record("old-pending", "2026-09-16T06:00:00Z"),
            record("future", "2026-09-22T01:30:00Z"),
            record("old-delivered", "2026-09-15T05:00:00Z", phase="delivered"),
            record("legacy-no-flag", "2026-09-15T04:00:00Z", routable=None),
        ],
    }
    watcher_state.save(state_path, original_state)

    plan = archive.quarantine_outbox(
        archive_root,
        state_path,
        profile_id="bri-danareksa-sekuritas",
        channel_jid=channel_jid,
    )

    assert plan["candidate_count"] == 2
    assert plan["applied"] is False
    assert watcher_state.load(state_path) == original_state
    assert not archive_root.exists()
    with pytest.raises(PermissionError, match="ALLOW_OUTBOX_QUARANTINE"):
        archive.quarantine_outbox(
            archive_root,
            state_path,
            profile_id="bri-danareksa-sekuritas",
            channel_jid=channel_jid,
            apply=True,
        )

    monkeypatch.setenv("WHATSAPP_CHANNEL_WATCH_ALLOW_OUTBOX_QUARANTINE", "1")
    applied = archive.quarantine_outbox(
        archive_root,
        state_path,
        profile_id="bri-danareksa-sekuritas",
        channel_jid=channel_jid,
        apply=True,
        now=datetime(2026, 9, 22, 2, 0, tzinfo=timezone.utc),
    )

    assert applied["quarantined"] == 2
    updated = watcher_state.load(state_path)
    outbox = {record["event_key"]: record for record in updated["outbox"]}
    assert outbox[f"{channel_jid}:old-ready"]["routable"] is False
    assert outbox[f"{channel_jid}:old-pending"]["routable"] is False
    assert outbox[f"{channel_jid}:future"]["routable"] is True
    assert outbox[f"{channel_jid}:old-delivered"]["routable"] is True
    assert outbox[f"{channel_jid}:legacy-no-flag"]["routable"] is None
    backup_dir = Path(str(applied["backup_dir"]))
    assert (backup_dir / "state-before.json").exists()
    assert (backup_dir / "manifest.json").exists()
    assert json.loads((backup_dir / "state-before.json").read_text()) == original_state
    assert archive.verify(archive_root) == {"checked": 0, "valid": 0, "invalid": 0}

    repeat = archive.quarantine_outbox(
        archive_root,
        state_path,
        profile_id="bri-danareksa-sekuritas",
        channel_jid=channel_jid,
        apply=True,
    )
    assert repeat["candidate_count"] == 0
    assert repeat["applied"] is True


def test_ensure_accepts_a_verified_bridge_record_for_the_same_source(tmp_path):
    source = ChannelEvent(
        channel_jid="120363405187024421@newsletter",
        message_id="BRIDGE-001",
        published_at=datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc),
        text="Bridge source",
        links=(),
        media=(ChannelMedia(kind="image", index=0, mime="image/jpeg"),),
        received_at=datetime(2026, 9, 21, 9, 31, tzinfo=timezone.utc),
    )
    initial = archive.ensure(tmp_path, "ins", source, None)
    record = json.loads(initial.record_path.read_text(encoding="utf-8"))
    media_bytes = b"bridge image"
    media_digest = hashlib.sha256(media_bytes).hexdigest()
    media_path = tmp_path / "media" / media_digest
    media_path.parent.mkdir()
    media_path.write_bytes(media_bytes)
    record["published_at"] = "2026-09-21T09:30:00.000Z"
    record["received_at"] = "2026-09-21T09:31:00.000Z"
    record["media"] = [{
        "kind": "image", "index": 0, "mime": "image/jpeg", "capture_status": "captured",
        "archive_path": f"media/{media_digest}", "sha256": media_digest, "bytes": len(media_bytes),
    }]
    body = {key: value for key, value in record.items() if key != "checksum"}
    record["checksum"] = hashlib.sha256(
        (json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    ).hexdigest()
    initial.record_path.write_text(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    assert archive.ensure(tmp_path, "ins", source, 4).created is False
