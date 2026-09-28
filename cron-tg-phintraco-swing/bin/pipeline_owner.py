"""Task 4 source-work entry into the existing Phintraco owner ledger."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import scan


class OwnerPending(RuntimeError):
    """The existing durable owner has not acknowledged every delivery leg."""


def _receipt_path(effect_key: str) -> Path:
    return scan.state_path().parent / "pipeline-receipts" / f"{effect_key}.json"


def _acknowledge_effect(path: Path, work: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".effect-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"effect_key": work["effect_key"], "event_key": work["event_key"], "version": work["version"]}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _source_message(envelope: dict[str, Any]) -> SimpleNamespace:
    body = envelope["payload"]
    media_ref_ids = body.get("media_ref_ids", [])
    if type(media_ref_ids) is not list or any(type(ref) is not str for ref in media_ref_ids):
        raise ValueError("Phintraco source media mapping is invalid")
    return SimpleNamespace(
        id=int(envelope["provider_event_id"]),
        message=body["text"],
        date=datetime.fromisoformat(envelope["published_at"]),
        photo=object() if media_ref_ids else None,
    )


def _source_media_client():
    base_url = os.environ.get("BURSAWATCH_SOURCE_MEDIA_URL")
    token_file = os.environ.get("BURSAWATCH_SOURCE_MEDIA_READ_TOKEN_FILE")
    if not base_url or not token_file:
        raise OwnerPending("Source Media Owner read credentials are unavailable")
    local = Path(__file__).resolve().parents[2] / "lib-bursawatch-source-media" / "bin"
    if not local.exists():
        local = Path.home() / ".agents" / "skills" / "lib-bursawatch-source-media" / "bin"
    if str(local) not in sys.path:
        sys.path.insert(0, str(local))
    from bursawatch_source_media import SourceMediaClient
    return SourceMediaClient(base_url, Path(token_file))


def _download_source_chart(envelope: dict[str, Any], media_store: Any = None) -> bytes:
    ids = envelope["payload"].get("media_ref_ids", [])
    refs = envelope.get("media_refs", [])
    if type(ids) is not list or type(refs) is not list:
        raise ValueError("Phintraco source chart reference is invalid")
    matches = [ref for ref in refs if type(ref) is dict and ref.get("ref") in ids and ref.get("kind") == "image"]
    if len(matches) != 1:
        raise ValueError("Phintraco source chart must have exactly one durable image ref")
    reference = matches[0]
    if reference.get("content_type") != "image/jpeg":
        raise ValueError("Phintraco source chart must be JPEG")
    downloaded = (media_store or _source_media_client()).download(reference["ref"])
    data = getattr(downloaded, "data", None)
    if (type(data) is not bytes or not data or len(data) > 8 * 1024 * 1024
            or hashlib.sha256(data).hexdigest() != reference.get("sha256")
            or len(data) != reference.get("size_bytes")):
        raise OwnerPending("Source Media Owner returned a chart that failed integrity checks")
    return data


def _document_refs(envelope: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    refs = envelope.get("media_refs", [])
    if type(refs) is not list or any(type(ref) is not dict for ref in refs):
        raise ValueError("Phintraco source media mapping is invalid")
    return refs, [ref for ref in refs if ref.get("kind") == "document"]


def _validate_pdf_ref(reference: dict[str, Any]) -> None:
    digest = reference.get("sha256")
    size = reference.get("size_bytes")
    if (
        reference.get("durable") is not True
        or type(reference.get("ref")) is not str
        or not reference["ref"]
        or type(digest) is not str
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
        or type(size) is not int
        or size < 0
        or type(reference.get("filename")) is not str
        or not reference["filename"]
        or type(reference.get("content_type")) is not str
        or not reference["content_type"]
    ):
        raise ValueError("Phintraco weekly PDF reference is invalid")


def _download_source_pdf(reference: dict[str, Any], media_store: Any = None) -> bytes:
    _validate_pdf_ref(reference)
    if reference["content_type"].casefold() != "application/pdf":
        raise ValueError("Phintraco weekly attachment is not a PDF")
    if reference["size_bytes"] > scan.MAX_WEEKLY_PDF_BYTES:
        raise ValueError("Phintraco weekly PDF exceeds the supported size")
    downloaded = (media_store or _source_media_client()).download(reference["ref"])
    data = getattr(downloaded, "data", None)
    if (
        type(data) is not bytes
        or not data
        or len(data) != reference["size_bytes"]
        or len(data) > scan.MAX_WEEKLY_PDF_BYTES
        or hashlib.sha256(data).hexdigest() != reference["sha256"]
    ):
        raise OwnerPending("Source Media Owner returned a PDF that failed integrity checks")
    downloaded_type = getattr(downloaded, "content_type", reference["content_type"])
    downloaded_name = getattr(downloaded, "filename", reference["filename"])
    if downloaded_type != reference["content_type"] or downloaded_name != reference["filename"]:
        raise OwnerPending("Source Media Owner returned mismatched PDF metadata")
    return data


def _source_pdf_message(envelope: dict[str, Any], reference: dict[str, Any]) -> SimpleNamespace:
    try:
        message_id = int(envelope["provider_event_id"])
        published_at = datetime.fromisoformat(envelope["published_at"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Phintraco PDF source identity is invalid") from error
    if published_at.tzinfo is None or published_at.utcoffset() is None:
        raise ValueError("Phintraco PDF source timestamp is invalid")
    return SimpleNamespace(
        id=message_id,
        message="",
        date=published_at,
        document=SimpleNamespace(mime_type=reference["content_type"], attributes=()),
        file=SimpleNamespace(name=reference["filename"]),
        photo=None,
    )


def _reply_parent_call(
    envelope: dict[str, Any], message: SimpleNamespace, state: dict[str, Any]
) -> scan.SwingCall | None:
    body = envelope["payload"]
    reply_id = body.get("reply_to_message_id")
    parent = body.get("reply_parent")
    if type(reply_id) is not int or type(parent) is not dict:
        return None
    if set(parent) != {"message_id", "text", "published_at", "has_photo"} or parent["message_id"] != reply_id:
        raise ValueError("Phintraco reply parent is invalid")
    if str(reply_id) in state.get("pdf_batches", {}) or str(reply_id) in state.get("quarantined_documents", {}):
        reply = scan.REPLY_STATUS_RE.match(scan.normalize_text(message.message or ""))
        if reply is None:
            return None
        matches = [
            plan
            for plan in state.get("source_plans", {}).values()
            if type(plan) is dict
            and plan.get("document_message_id") == reply_id
            and plan.get("ticker") == reply.group("ticker").upper()
        ]
        return scan.source_plan_call(matches[0]) if len(matches) == 1 else None
    try:
        parent_date = datetime.fromisoformat(parent["published_at"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Phintraco reply parent timestamp is invalid") from error
    parent_message = SimpleNamespace(
        id=reply_id,
        message=parent["text"],
        date=parent_date,
        photo=object() if parent["has_photo"] else None,
    )
    return scan.parse_source_event(parent_message)


def submit(work: dict[str, Any], *, no_post: bool = False, media_store: Any = None) -> str:
    loaded = scan.config.load_watch_config_for_run()
    if loaded.revision is None:
        raise ValueError("Phintraco pipeline requires an effective live watch config")
    if (loaded.config.telegram_channel_id, loaded.config.telegram_username) != (1444713822, "phintraprofits"):
        raise ValueError("Phintraco pipeline source does not match canonical endpoint")
    with scan.config.activate_watch_config(loaded.config):
        return _submit_with_config(work, no_post=no_post, media_store=media_store)


def _submit_with_config(work: dict[str, Any], *, no_post: bool, media_store: Any = None) -> str:
    if no_post:
        isolated = os.environ.get("IDX_SWING_WATCH_PHINTRACO_DAILY_STATE_PATH")
        if not isolated or Path(isolated).expanduser().resolve().is_relative_to((Path.home() / ".hermes" / "state").resolve()):
            raise ValueError("no-post owner work requires isolated state")
    envelope = work["envelope"]
    if (work["pipeline_id"], work["capability_id"], work["version"], envelope["endpoint_id"], envelope["publisher_id"]) != ("swing_plan", "trading_plans", 1, "telegram:phintraprofits", "phintraco"):
        raise ValueError("unsupported Phintraco source work")
    expected = hashlib.sha256(f'{work["event_key"]}:1:trading_plans'.encode()).hexdigest()
    if work["effect_key"] != expected or work["work_key"] != expected or (envelope["media_required"] and not envelope["media_refs"]):
        raise ValueError("Phintraco work identity or media contract is invalid")
    message = _source_message(envelope)
    now = datetime.now(scan.WIB)
    with scan.run_lock() as acquired:
        if not acquired:
            raise OwnerPending("Phintraco owner ledger is busy")
        receipt_path = _receipt_path(work["effect_key"])
        if receipt_path.exists():
            if json.loads(receipt_path.read_text()) != {"effect_key": work["effect_key"], "event_key": work["event_key"], "version": work["version"]}:
                raise ValueError("Phintraco effect receipt is invalid")
            return "accepted"
        state = scan.load_state()

        media_refs, document_refs = _document_refs(envelope)
        if document_refs:
            if len(document_refs) != 1 or len(media_refs) != 1:
                raise ValueError("Phintraco weekly attachment media mapping is ambiguous")
            reference = document_refs[0]
            _validate_pdf_ref(reference)
            filename = reference["filename"]
            if not filename.startswith(scan.WEEKLY_PDF_PREFIX):
                return "irrelevant"
            message_id = int(envelope["provider_event_id"])
            already_recorded = (
                str(message_id) in state["pdf_batches"]
                or str(message_id) in state["quarantined_documents"]
            )
            content = None
            if (
                not already_recorded
                and reference["content_type"].casefold() == "application/pdf"
                and reference["size_bytes"] <= scan.MAX_WEEKLY_PDF_BYTES
            ):
                content = _download_source_pdf(reference, media_store)
            pdf_message = _source_pdf_message(envelope, reference)
            handled, _, _ = scan.ingest_weekly_pdf_bytes(
                pdf_message,
                state,
                now,
                content,
                filename=filename,
                mime_type=reference["content_type"],
                size_hint=reference["size_bytes"],
            )
            if not handled:
                return "irrelevant"
            scan.save_state(state)
            scan.drain_outbox(state, now, dry_run=no_post)
            batch = state["pdf_batches"].get(str(message_id))
            pending_keys = [
                key for key in (batch or {}).get("event_keys", [])
                if key in state["outbox"]
            ]
            if (
                str(message_id) in state["quarantined_documents"]
                or batch is None
                or batch["status"] == "degraded"
                or pending_keys
            ):
                raise OwnerPending("Phintraco weekly PDF work remains held or pending")
            _acknowledge_effect(receipt_path, work)
            return "accepted"

        if media_refs and not envelope["payload"].get("media_ref_ids"):
            return "irrelevant"

        call = scan.parse_source_event(message)
        reply_parent_id = envelope["payload"].get("reply_to_message_id")
        if call is None and envelope["payload"].get("reply_parent"):
            parent_call = _reply_parent_call(envelope, message, state)
            call = scan.parse_reply_status(
                message.id,
                message.message,
                message.photo is not None,
                message.date,
                parent_call,
            )
        if call is None:
            if scan.looks_like_swing_call(message.message):
                raise ValueError("malformed Phintraco plan")
            return "irrelevant"

        event = scan.enqueue_call(state, call, now)
        if call.has_source_chart and scan._cached_media_path(event) is None:
            chart = _download_source_chart(envelope, media_store)
            media_path = scan.media_dir() / f"phintraco-{call.source_message_id}.jpg"
            scan._ensure_durable_directory(media_path.parent)
            scan._write_durable_media(media_path, chart)
            event["media_path"] = str(media_path)
            event["chart_status"] = "captured"
            event["phase"] = scan.PHASE_PENDING_TEXT
        if type(reply_parent_id) is not int:
            reply_parent_id = None
        matched_setup_event_key = scan.match_source_plan(
            call, state, reply_parent_id
        )
        if matched_setup_event_key is not None:
            event["matched_setup_event_key"] = matched_setup_event_key
        elif scan._update_references_pdf_plan(call, state, reply_parent_id):
            event["board_kind_override"] = "context"
        scan.save_state(state)
        scan.drain_outbox(state, now, dry_run=no_post)
        if str(call.source_message_id) in state["outbox"]:
            raise OwnerPending("Phintraco owner delivery remains pending")
        _acknowledge_effect(receipt_path, work)
    return "accepted"


def main() -> int:
    import os
    import sys
    work = json.load(sys.stdin)
    result = submit(work, no_post=os.environ.get("BURSAWATCH_TG_SOURCE_NO_POST") == "1")
    print(json.dumps({"outcome": result}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
