from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cron-wa-source-ingest" / "bin"))
from adapter import endpoints, plan_legacy_cursor_seed, plan_migration_preflight, run_once
import migration_preflight

sys.path.insert(0, str(ROOT / "cron-wa-channel-watch" / "bin"))
from config import load
from event_queue import enqueue, event_filename
from models import ChannelEvent, ChannelMedia

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def test_legacy_cursor_seed_is_explicitly_blocked_for_queue_order_mismatch(tmp_path):
    source = tmp_path / "snapshot" / "wa.json"
    source.parent.mkdir()
    source.write_text(json.dumps({"profiles": {}, "outbox": []}))
    result = plan_legacy_cursor_seed(source, {"platform": "whatsapp", "endpoint_id": "whatsapp:0029VbAjdnb60eBhwVdJxj1c", "publisher_id": "bri-danareksa", "address": "https://whatsapp.com/channel/example", "provider_id": "0029VbAjdnb60eBhwVdJxj1c"}, 2)
    assert result["status"] == "blocked"
    assert "no proven order-preserving mapping" in result["reason"]
    assert result["legacy_state_sha256"]


def _receipt_key_sha256(event_key: str, leg: str) -> str:
    from discord import nonce, operation_key_for_nonce

    key = operation_key_for_nonce(nonce(event_key, leg))
    return hashlib.sha256(key.encode()).hexdigest()


def _synthetic_migration_metadata() -> dict:
    first_key = "120363419226413141@newsletter:synthetic-chart-1"
    second_key = "120363419226413141@newsletter:synthetic-news-2"
    snapshot_id = "synthetic-wa-snapshot-1"
    capture_boundary = "2026-01-02T00:00:00Z"

    def filename(event_key: str) -> str:
        return hashlib.sha256(event_key.encode()).hexdigest() + ".json"

    chart_sha256 = hashlib.sha256(b"synthetic chart bytes").hexdigest()
    watcher_source_sha256 = hashlib.sha256(b"synthetic watcher state bytes").hexdigest()
    expected_key = _receipt_key_sha256(first_key, "item:0:text:0")
    expected_payload = hashlib.sha256(b"synthetic rendered text operation").hexdigest()
    edit_key = "bursawatch-wa-channel-watch:edit:" + hashlib.sha256(b"synthetic board edit key").hexdigest()
    edit_key_sha256 = hashlib.sha256(edit_key.encode()).hexdigest()
    edit_payload_sha256 = hashlib.sha256(b"synthetic board edit payload").hexdigest()
    metadata = {
        "schema_version": 3,
        "profile_id": "bri-danareksa-sekuritas",
        "channel_jid": "120363419226413141@newsletter",
        "snapshot": {"id": snapshot_id, "capture_boundary": capture_boundary},
        "inventories": {
            "queue": {
                "snapshot_id": snapshot_id,
                "capture_boundary": capture_boundary,
                "record_count": 2,
                "canonical_sha256": "0" * 64,
                "records": [
                    {
                        "event_key": first_key,
                        "published_at": "2026-01-01T00:00:00Z",
                        "mtime_ns": 1_000,
                        "filename": filename(first_key),
                        "media": [{"index": 0, "kind": "image", "mime": "image/jpeg"}],
                        "exact_technical_review_marker": True,
                    },
                    {
                        "event_key": second_key,
                        "published_at": "2026-01-01T01:00:00Z",
                        "mtime_ns": 2_000,
                        "filename": filename(second_key),
                        "media": [],
                        "exact_technical_review_marker": False,
                    },
                ],
            },
            "archive": {
                "snapshot_id": snapshot_id,
                "capture_boundary": capture_boundary,
                "record_count": 2,
                "canonical_sha256": "0" * 64,
                "records": [
                    {
                        "event_key": first_key,
                        "published_at": "2026-01-01T00:00:00Z",
                        "record_checksum_verified": True,
                        "media": [{
                            "index": 0, "kind": "image", "mime": "image/jpeg",
                            "capture_status": "captured", "sha256": chart_sha256,
                            "bytes": 21, "integrity_verified": True,
                        }],
                    },
                    {
                        "event_key": second_key,
                        "published_at": "2026-01-01T01:00:00Z",
                        "record_checksum_verified": True,
                        "media": [],
                    },
                ],
            },
            "watcher_outbox": {
                "snapshot_id": snapshot_id,
                "capture_boundary": capture_boundary,
                "record_count": 1,
                "canonical_sha256": "0" * 64,
                "legacy_cursor": {"published_at": "2026-01-01T00:00:00Z", "event_key": first_key},
                "source_state_sha256": watcher_source_sha256,
                "delivery_plan": {
                    "schema_version": 1,
                    "source_sha256": watcher_source_sha256,
                    "operation_count": 2,
                    "operation_key_sha256": [expected_key, edit_key_sha256],
                    "payload_sha256": [expected_payload, edit_payload_sha256],
                    "operation_kinds": ["channel_message_create", "channel_message_edit"],
                },
                "records": [{
                    "event_key": first_key,
                    "profile_id": "bri-danareksa-sekuritas",
                    "routable": True,
                    "agent_phase": "delivered",
                    "media_delivery_status": "delivered",
                    "board_phase": "accepted",
                    "board_link_phase": "patched",
                    "text_message_count": 1,
                }],
            },
            "delivery_receipts": {
                "snapshot_id": snapshot_id,
                "capture_boundary": capture_boundary,
                "record_count": 2,
                "canonical_sha256": "0" * 64,
                "operation_namespace": "bursawatch-wa-channel-watch",
                "records": [
                    {
                        "operation_key_sha256": expected_key,
                        "payload_sha256": expected_payload,
                        "kind": "channel_message_create",
                        "status": "delivered",
                        "receipt_present": True,
                    },
                    {
                        "operation_key_sha256": edit_key_sha256,
                        "payload_sha256": edit_payload_sha256,
                        "kind": "channel_message_edit",
                        "status": "delivered",
                        "receipt_present": True,
                    },
                ],
            },
        },
    }
    _reseal_preflight_inventory_digests(metadata)
    return metadata


def _reseal_preflight_inventory_digests(metadata: dict, *names: str) -> None:
    names = names or tuple(metadata["inventories"])
    for name in names:
        inventory = metadata["inventories"][name]
        inventory["record_count"] = len(inventory["records"])
        inventory["canonical_sha256"] = migration_preflight._canonical_digest(
            migration_preflight._inventory_payload(name, inventory)
        )


def test_synthetic_migration_preflight_reconciles_a_bundle_without_claiming_readiness():
    metadata = _synthetic_migration_metadata()
    before = json.dumps(metadata, sort_keys=True)

    result = plan_migration_preflight(metadata)

    assert result["status"] == "blocked"
    assert result["readiness"] == "blocked"
    assert result["apply"] is False
    assert result["cursor_written"] is False
    assert result["production_cutover_authorized"] is False
    assert result["snapshot"]["bundle_integrity"] == "valid"
    assert result["snapshot"]["inventory_completeness"] == "unproven"
    assert result["snapshot"]["freshness"] == "unproven"
    assert result["cursor_crosswalk"]["status"] == "unproven"
    assert result["cursor_crosswalk"]["supplied_records_consistent"] is True
    assert result["cursor_crosswalk"]["candidate_position"] is None
    assert result["cursor_crosswalk"]["observed_anchor_position"] == {
        "mtime_ns": 1_000,
        "filename": hashlib.sha256(b"120363419226413141@newsletter:synthetic-chart-1").hexdigest() + ".json",
        "position": "00000000000000001000:" + hashlib.sha256(b"120363419226413141@newsletter:synthetic-chart-1").hexdigest() + ".json",
    }
    assert result["cursor_crosswalk"]["order_preserved_in_supplied_records"] is True
    assert result["reconciliation"]["queue_archive"]["matched_events"] == 2
    assert result["reconciliation"]["media"]["technical_review_image_eligible"] == 1
    assert result["reconciliation"]["watcher_outbox"]["matched_events"] == 1
    assert result["receipt_reconciliation"]["status"] == "matched_within_supplied_bundle"
    assert result["receipt_reconciliation"]["expected_leg_set_bound"] is True
    assert result["receipt_reconciliation"]["missing_expected_legs"] == 0
    assert result["receipt_reconciliation"]["inventory_completeness"] == "unproven"
    assert "inventory_completeness_unproven" in result["blockers"]
    assert "snapshot_freshness_unproven" in result["blockers"]
    assert json.dumps(metadata, sort_keys=True) == before


def test_preflight_cli_reads_only_the_supplied_metadata_and_writes_no_plan_file(tmp_path, capsys):
    metadata_path = tmp_path / "sanitized.json"
    raw = json.dumps(_synthetic_migration_metadata(), sort_keys=True).encode()
    metadata_path.write_bytes(raw)

    assert migration_preflight.main(["--metadata", str(metadata_path)]) == 0

    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "blocked"
    assert printed["apply"] is False
    assert metadata_path.read_bytes() == raw
    assert {path.name for path in tmp_path.iterdir()} == {"sanitized.json"}


def test_preflight_cli_reports_invalid_metadata_as_json_without_traceback(tmp_path, capsys):
    metadata_path = tmp_path / "invalid.json"
    metadata_path.write_text('{"schema_version": 999}', encoding="utf-8")

    assert migration_preflight.main(["--metadata", str(metadata_path)]) == 2

    captured = capsys.readouterr()
    assert json.loads(captured.err)["status"] == "invalid_metadata"
    assert "Traceback" not in captured.err


def test_preflight_rejects_arrival_order_mismatch_in_the_supplied_bundle():
    metadata = _synthetic_migration_metadata()
    metadata["inventories"]["queue"]["records"][1]["mtime_ns"] = 500
    _reseal_preflight_inventory_digests(metadata, "queue")

    result = plan_migration_preflight(metadata)

    assert result["cursor_crosswalk"]["status"] == "unproven"
    assert result["cursor_crosswalk"]["supplied_records_consistent"] is False
    assert result["cursor_crosswalk"]["candidate_position"] is None
    assert "queue_arrival_order_differs_from_legacy_cursor_order" in result["blockers"]
    assert result["apply"] is False


def test_preflight_blocks_invalid_technical_image_and_active_outbox():
    metadata = _synthetic_migration_metadata()
    metadata["inventories"]["archive"]["records"][0]["media"][0].update({
        "capture_status": "unavailable", "sha256": None, "bytes": None, "integrity_verified": False,
    })
    metadata["inventories"]["watcher_outbox"]["records"][0]["agent_phase"] = "ready"
    _reseal_preflight_inventory_digests(metadata, "archive", "watcher_outbox")

    result = plan_migration_preflight(metadata)

    assert result["status"] == "blocked"
    assert "technical_review_requires_one_verified_archived_image" in result["blockers"]
    assert "active_routable_watcher_outbox" in result["blockers"]


def test_synthetic_migration_preflight_rejects_unsanitized_payload_fields():
    metadata = _synthetic_migration_metadata()
    metadata["inventories"]["queue"]["records"][0]["path"] = "/private/staging/image.jpg"

    with pytest.raises(ValueError, match="sanitized metadata shape"):
        plan_migration_preflight(metadata)


def test_preflight_detects_tampered_count_and_digest_metadata():
    metadata = _synthetic_migration_metadata()
    metadata["inventories"]["queue"]["records"][0]["mtime_ns"] += 5
    metadata["inventories"]["queue"]["record_count"] += 1
    metadata["inventories"]["archive"]["canonical_sha256"] = "f" * 64

    result = plan_migration_preflight(metadata)

    assert result["snapshot"]["bundle_integrity"] == "invalid"
    assert "queue_record_count_mismatch" in result["blockers"]
    assert "queue_canonical_digest_mismatch" in result["blockers"]
    assert "archive_canonical_digest_mismatch" in result["blockers"]
    assert result["readiness"] == "blocked"


def test_preflight_detects_omitted_inventory_record_when_manifest_is_stale():
    metadata = _synthetic_migration_metadata()
    metadata["inventories"]["archive"]["records"].pop()

    result = plan_migration_preflight(metadata)

    assert result["snapshot"]["bundle_integrity"] == "invalid"
    assert "archive_record_count_mismatch" in result["blockers"]
    assert "archive_canonical_digest_mismatch" in result["blockers"]


def test_self_consistent_cross_inventory_omission_cannot_prove_completeness():
    metadata = _synthetic_migration_metadata()
    for source in ("queue", "archive", "watcher_outbox", "delivery_receipts"):
        metadata["inventories"][source]["records"].pop()
    watcher = metadata["inventories"]["watcher_outbox"]
    watcher["source_state_sha256"] = hashlib.sha256(b"omitted synthetic watcher state").hexdigest()
    watcher["delivery_plan"].update({
        "source_sha256": watcher["source_state_sha256"],
        "operation_count": 0,
        "operation_key_sha256": [],
        "payload_sha256": [],
        "operation_kinds": [],
    })
    _reseal_preflight_inventory_digests(metadata)

    result = plan_migration_preflight(metadata)

    assert result["snapshot"]["bundle_integrity"] == "valid"
    assert result["snapshot"]["inventory_completeness"] == "unproven"
    assert result["reconciliation"]["queue_archive"]["matched_events"] == 1
    assert result["cursor_crosswalk"]["supplied_records_consistent"] is True
    assert result["cursor_crosswalk"]["candidate_position"] is None
    assert "inventory_completeness_unproven" in result["blockers"]
    assert result["readiness"] == "blocked"


def test_preflight_blocks_inventories_with_mismatched_snapshot_identity_or_boundary():
    metadata = _synthetic_migration_metadata()
    metadata["inventories"]["archive"]["snapshot_id"] = "different-snapshot"
    metadata["inventories"]["delivery_receipts"]["capture_boundary"] = "2026-01-03T00:00:00Z"
    _reseal_preflight_inventory_digests(metadata, "archive", "delivery_receipts")

    result = plan_migration_preflight(metadata)

    assert result["snapshot"]["bundle_integrity"] == "invalid"
    assert result["snapshot"]["inventory_identity_mismatches"] == 1
    assert result["snapshot"]["capture_boundary_mismatches"] == 1
    assert "inventory_snapshot_identity_mismatch" in result["blockers"]
    assert "inventory_capture_boundary_mismatch" in result["blockers"]


def test_preflight_blocks_an_omitted_expected_receipt_leg():
    metadata = _synthetic_migration_metadata()
    metadata["inventories"]["delivery_receipts"]["records"].clear()
    _reseal_preflight_inventory_digests(metadata, "delivery_receipts")

    result = plan_migration_preflight(metadata)

    assert result["receipt_reconciliation"]["status"] == "blocked"
    assert result["receipt_reconciliation"]["expected_legs"] == 2
    assert result["receipt_reconciliation"]["missing_expected_legs"] == 2
    assert "delivery_receipt_expected_leg_missing" in result["blockers"]


def test_preflight_blocks_a_receipt_with_an_unexpected_operation_key():
    metadata = _synthetic_migration_metadata()
    metadata["inventories"]["delivery_receipts"]["records"][0]["operation_key_sha256"] = hashlib.sha256(
        b"wrong operation key"
    ).hexdigest()
    _reseal_preflight_inventory_digests(metadata, "delivery_receipts")

    result = plan_migration_preflight(metadata)

    assert result["receipt_reconciliation"]["status"] == "blocked"
    assert result["receipt_reconciliation"]["missing_expected_legs"] == 1
    assert result["receipt_reconciliation"]["unexpected_receipts"] == 1
    assert "delivery_receipt_expected_leg_missing" in result["blockers"]
    assert "unexpected_delivery_receipt_operation" in result["blockers"]


def test_preflight_blocks_duplicate_mismatched_and_unresolved_receipt_rows():
    metadata = _synthetic_migration_metadata()
    receipts = metadata["inventories"]["delivery_receipts"]["records"]
    receipts.append(dict(receipts[0]))
    receipts[0]["payload_sha256"] = "e" * 64
    receipts[1]["payload_sha256"] = "e" * 64
    receipts[1]["status"] = "pending_reconciliation"
    receipts[1]["receipt_present"] = False
    _reseal_preflight_inventory_digests(metadata, "delivery_receipts")

    result = plan_migration_preflight(metadata)

    assert result["receipt_reconciliation"]["duplicate_receipt_legs"] == 1
    assert result["receipt_reconciliation"]["payload_mismatches"] == 1
    assert result["receipt_reconciliation"]["unresolved_receipts"] == 1
    assert "duplicate_delivery_receipt_operation" in result["blockers"]
    assert "delivery_receipt_payload_mismatch" in result["blockers"]
    assert "delivery_receipt_unresolved" in result["blockers"]


def test_preflight_matches_board_link_edit_receipt_legs():
    metadata = _synthetic_migration_metadata()
    result = plan_migration_preflight(metadata)

    assert result["receipt_reconciliation"]["status"] == "matched_within_supplied_bundle"
    assert result["receipt_reconciliation"]["patched_board_link_events"] == 1
    assert result["receipt_reconciliation"]["expected_board_link_edit_legs"] == 1
    assert result["receipt_reconciliation"]["planned_board_link_edit_legs"] == 1
    assert result["receipt_reconciliation"]["matched_board_link_edit_legs"] == 1
    assert "board_link_edit_operation_count_mismatch" not in result["blockers"]


def test_preflight_blocks_a_board_edit_receipt_omitted_from_the_handoff_plan():
    metadata = _synthetic_migration_metadata()
    plan = metadata["inventories"]["watcher_outbox"]["delivery_plan"]
    plan["operation_count"] -= 1
    plan["operation_key_sha256"].pop()
    plan["payload_sha256"].pop()
    plan["operation_kinds"].pop()
    _reseal_preflight_inventory_digests(metadata, "watcher_outbox")

    result = plan_migration_preflight(metadata)

    assert result["receipt_reconciliation"]["status"] == "blocked"
    assert result["receipt_reconciliation"]["expected_board_link_edit_legs"] == 1
    assert result["receipt_reconciliation"]["planned_board_link_edit_legs"] == 0
    assert "board_link_edit_operation_count_mismatch" in result["blockers"]
    assert "unexpected_delivery_receipt_operation" in result["blockers"]


def test_preflight_blocks_patched_board_link_without_accepted_board_handoff():
    metadata = _synthetic_migration_metadata()
    outbox = metadata["inventories"]["watcher_outbox"]["records"][0]
    outbox["board_phase"] = "not_eligible"
    _reseal_preflight_inventory_digests(metadata, "watcher_outbox")

    result = plan_migration_preflight(metadata)

    assert "board_link_state_inconsistent" in result["blockers"]
    assert result["receipt_reconciliation"]["status"] == "blocked"


def test_preflight_does_not_write_supplied_metadata_or_derived_artifacts(tmp_path, capsys):
    metadata = _synthetic_migration_metadata()
    metadata_path = tmp_path / "metadata.json"
    metadata_bytes = json.dumps(metadata, sort_keys=True).encode()
    metadata_path.write_bytes(metadata_bytes)
    before_names = {path.name for path in tmp_path.iterdir()}

    result = plan_migration_preflight(metadata)
    cli_status = migration_preflight.main(["--metadata", str(metadata_path)])
    capsys.readouterr()

    assert result["cursor_written"] is False
    assert result["apply"] is False
    assert cli_status == 0
    assert metadata_path.read_bytes() == metadata_bytes
    assert {path.name for path in tmp_path.iterdir()} == before_names


class Inbox:
    def __init__(self):
        self.events = []

    def accept(self, event):
        self.events.append(event)
        identity = [event[key] for key in ("platform", "endpoint_id", "provider_event_id")]
        return {"event_key": hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest(), "version": 1, "duplicate": False, "work_keys": []}


class IdempotentMediaStore:
    def __init__(self, order):
        self.order = order
        self.uploads = {}

    def upload(self, key, data, *, kind, content_type, filename):
        self.order.append("upload")
        value = self.uploads.get(key)
        if value is None:
            value = {
                "ref": str(uuid.uuid5(uuid.NAMESPACE_URL, key)),
                "sha256": hashlib.sha256(data).hexdigest(),
                "kind": kind,
                "content_type": content_type,
                "size_bytes": len(data),
                "filename": filename,
                "durable": True,
            }
            self.uploads[key] = (data, value)
        else:
            assert value[0] == data
        return self.uploads[key][1]


class OrderedInbox(Inbox):
    def __init__(self, order):
        super().__init__()
        self.order = order
        self.fail = False

    def accept(self, event):
        self.order.append("accept")
        if self.fail:
            raise OSError("inbox unavailable")
        return super().accept(event)


def context():
    profiles = load(ROOT / "cron-wa-channel-watch" / "config" / "watches.json").profiles
    bri = profiles[0]
    row = {"platform": "whatsapp", "endpoint_id": "whatsapp:0029VbAjdnb60eBhwVdJxj1c", "publisher_id": "bri-danareksa", "address": bri.channel_url, "provider_id": bri.channel_jid, "capability_id": "swing_chart_context", "verification_status": "verified", "enabled": True}
    return profiles, bri, {"revision": 4, "subscriptions": [row]}, row["endpoint_id"]


def queue_event(queue_dir: Path, event: ChannelEvent, position_ns: int) -> Path:
    assert enqueue(queue_dir, event)
    path = queue_dir / event_filename(event)
    os.utime(path, ns=(position_ns, position_ns))
    return path


def cursor(state_root: Path, endpoint_id: str) -> dict:
    return json.loads((state_root / endpoint_id.replace(":", "-") / "cursor.json").read_text())


def test_forward_binding_skips_observe_profiles_and_empty_bootstrap(tmp_path):
    profiles, _bri, snapshot, endpoint_id = context()
    selected, _ = endpoints(snapshot, profiles)
    assert set(selected) == {endpoint_id}
    queue_dir = tmp_path / "queue"
    state_root = tmp_path / "state"
    result = run_once(snapshot, profiles, queue_dir, state_root, Inbox(), NOW)
    assert result == [{"endpoint_id": endpoint_id, "status": "bootstrapped_empty", "accepted": 0}]
    assert cursor(state_root, endpoint_id)["initialized"] is True
    assert not queue_dir.exists()


def test_delayed_published_at_is_accepted_after_later_queue_arrival(tmp_path):
    profiles, bri, snapshot, endpoint_id = context()
    queue_dir = tmp_path / "queue"
    state_root = tmp_path / "state"
    old = ChannelEvent(bri.channel_jid, "old", NOW, "old", (), (), NOW)
    queue_event(queue_dir, old, 1_000_000_000_000_000_000)
    inbox = Inbox()
    assert run_once(snapshot, profiles, queue_dir, state_root, inbox, NOW)[0]["status"] == "bootstrapped_empty"
    delayed = ChannelEvent(bri.channel_jid, "delayed", NOW - timedelta(days=1), "late arrival", (), (), NOW)
    queue_event(queue_dir, delayed, 2_000_000_000_000_000_000)
    result = run_once(snapshot, profiles, queue_dir, state_root, inbox, NOW)
    assert result[0]["accepted"] == 1
    assert inbox.events[0]["provider_event_id"] == "delayed"
    assert inbox.events[0]["published_at"] == delayed.published_at.isoformat()
    assert cursor(state_root, endpoint_id)["anchor"] == "delayed"


def test_bri_media_queue_item_is_durably_blocked_without_queue_mutation(tmp_path):
    profiles, bri, snapshot, endpoint_id = context()
    queue_dir = tmp_path / "queue"
    state_root = tmp_path / "state"
    old = ChannelEvent(bri.channel_jid, "old", NOW, "old", (), (), NOW)
    old_path = queue_event(queue_dir, old, 1_000_000_000_000_000_000)
    before = old_path.read_bytes()
    assert run_once(snapshot, profiles, queue_dir, state_root, Inbox(), NOW)[0]["status"] == "bootstrapped_empty"
    new = ChannelEvent(bri.channel_jid, "new", NOW + timedelta(minutes=1), "new text", (), (ChannelMedia("image", 0, "image/jpeg", "/private/image"),), NOW)
    new_path = queue_event(queue_dir, new, 2_000_000_000_000_000_000)
    result = run_once(snapshot, profiles, queue_dir, state_root, Inbox(), NOW)
    assert result[0]["reason"] == "media_blocked"
    marker = json.loads((state_root / endpoint_id.replace(":", "-") / "blocked-media.json").read_text())
    assert marker["payload"]["text"] == "new text"
    assert "/private/image" not in json.dumps(marker)
    assert old_path.read_bytes() == before and new_path.exists()
    assert cursor(state_root, endpoint_id)["anchor"] is None


def test_archive_media_upload_precedes_acceptance_and_survives_retry(tmp_path):
    profiles, bri, snapshot, endpoint_id = context()
    queue_dir = tmp_path / "queue"
    state_root = tmp_path / "state"
    archive_root = tmp_path / "archive"
    old = ChannelEvent(bri.channel_jid, "old", NOW, "old", (), (), NOW)
    old_path = queue_event(queue_dir, old, 1_000_000_000_000_000_000)
    inbox_order = []
    inbox = OrderedInbox(inbox_order)
    assert run_once(snapshot, profiles, queue_dir, state_root, inbox, NOW)[0]["status"] == "bootstrapped_empty"
    bootstrap_cursor = cursor(state_root, endpoint_id)
    assert bootstrap_cursor["anchor"] is None
    assert bootstrap_cursor["position"].endswith(old_path.name)

    staging = tmp_path / "staging"
    staging.mkdir()
    staged_media = staging / "private-source.jpg"
    staged_media.write_bytes(b"\xff\xd8\xffdurable-channel-image")
    new = ChannelEvent(
        bri.channel_jid,
        "with-media",
        NOW + timedelta(minutes=1),
        "chart update",
        (),
        (ChannelMedia("image", 0, "image/jpeg", str(staged_media)),),
        NOW,
    )
    import archive
    archive.ensure(archive_root, bri.id, new, 4, staging_root=staging)
    queue_path = queue_event(queue_dir, new, 2_000_000_000_000_000_000)
    assert not staged_media.exists(), "the bridge staging copy is disposable after archive capture"

    media_store = IdempotentMediaStore(inbox_order)
    inbox.fail = True
    failed = run_once(snapshot, profiles, queue_dir, state_root, inbox, NOW, archive_root=archive_root, media_store=media_store)
    assert failed[0]["status"] == "blocked"
    assert cursor(state_root, endpoint_id) == bootstrap_cursor
    assert queue_path.exists()
    assert inbox_order == ["upload", "accept"]

    inbox.fail = False
    recovered = run_once(snapshot, profiles, queue_dir, state_root, inbox, NOW, archive_root=archive_root, media_store=media_store)
    assert cursor(state_root, endpoint_id)["anchor"] == "with-media"
    assert len(inbox.events) == 1
    assert inbox_order == ["upload", "accept", "accept"]
    assert list(media_store.uploads) == [f"{endpoint_id}:with-media:attachment:0"]
    event = inbox.events[0]
    assert event["media_required"] is True
    assert event["media_refs"] == [media_store.uploads[next(iter(media_store.uploads))][1]]
    assert event["payload"]["media_ref_ids"] == [event["media_refs"][0]["ref"]]
    assert event["payload"]["media_manifest"] == [{"index": 0, "kind": "image", "mime": "image/jpeg", "ref_id": event["media_refs"][0]["ref"]}]
    assert event["payload"]["owner_config_revision"] is None
    serialized = json.dumps(event)
    assert str(staged_media) not in serialized
    assert "archive_path" not in serialized and "media/" not in serialized
    assert "durable-channel-image" not in serialized


def test_retained_history_over_500_files_is_not_parsed_on_new_arrival(tmp_path):
    profiles, bri, snapshot, endpoint_id = context()
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    for index in range(501):
        path = queue_dir / f"old-{index:04d}.json"
        path.write_text("invalid retained payload")
        stamp = 1_000_000_000_000_000_000 + index
        os.utime(path, ns=(stamp, stamp))
    state_root = tmp_path / "state"
    inbox = Inbox()
    assert run_once(snapshot, profiles, queue_dir, state_root, inbox, NOW)[0]["status"] == "bootstrapped_empty"
    new = ChannelEvent(bri.channel_jid, "fresh", NOW, "new source", (), (), NOW)
    queue_event(queue_dir, new, 2_000_000_000_000_000_000)
    assert run_once(snapshot, profiles, queue_dir, state_root, inbox, NOW)[0]["accepted"] == 1
    assert inbox.events[0]["provider_event_id"] == "fresh"
    assert cursor(state_root, endpoint_id)["anchor"] == "fresh"
    assert (queue_dir / "old-0000.json").read_text() == "invalid retained payload"
