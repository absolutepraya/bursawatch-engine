"""Task 4 source-work entry into the existing Phintraco owner ledger."""
from __future__ import annotations

import hashlib
import asyncio
import json
import os
import re
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
    refs = envelope.get("media_refs", [])
    if type(refs) is not list or any(type(ref) is not dict for ref in refs):
        raise ValueError("Phintraco source media mapping is invalid")
    documents = [ref for ref in refs if ref.get("kind") == "document"]
    if len(documents) > 1:
        raise ValueError("Phintraco source event has multiple documents")
    document = None
    file = None
    if documents:
        reference = documents[0]
        filename = reference.get("filename")
        if type(filename) is not str:
            raise ValueError("Phintraco source document filename is invalid")
        match = re.fullmatch(r"PHINTAS_Weekly_Swing_Trading_Ideas_(\d{8})\.pdf", filename)
        if match:
            filename = f"PHINTAS Weekly Swing Trading Ideas_{match.group(1)}.pdf"
        document = SimpleNamespace(
            mime_type=reference.get("content_type"),
            attributes=(SimpleNamespace(file_name=filename),),
            source_media_ref=reference,
        )
        file = SimpleNamespace(name=filename)
    return SimpleNamespace(
        id=int(envelope["provider_event_id"]),
        message=body["text"],
        date=datetime.fromisoformat(envelope["published_at"]),
        photo=object() if media_ref_ids else None,
        document=document,
        file=file,
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


def _download_source_pdf(envelope: dict[str, Any], media_store: Any = None) -> bytes:
    refs = envelope.get("media_refs", [])
    if type(refs) is not list:
        raise ValueError("Phintraco source document reference is invalid")
    matches = [
        ref for ref in refs
        if type(ref) is dict and ref.get("kind") == "document"
        and ref.get("content_type") == "application/pdf"
    ]
    if len(matches) != 1:
        raise ValueError("Phintraco weekly PDF requires exactly one durable document ref")
    reference = matches[0]
    downloaded = (media_store or _source_media_client()).download(reference["ref"])
    data = getattr(downloaded, "data", None)
    if (
        type(data) is not bytes or not data
        or len(data) > scan.MAX_WEEKLY_PDF_BYTES
        or hashlib.sha256(data).hexdigest() != reference.get("sha256")
        or len(data) != reference.get("size_bytes")
        or getattr(downloaded, "kind", None) != "document"
        or getattr(downloaded, "content_type", None) != "application/pdf"
        or getattr(downloaded, "filename", None) != reference.get("filename")
    ):
        raise OwnerPending("Source Media Owner returned a PDF that failed integrity checks")
    return data


class _StoredPdfClient:
    def __init__(self, envelope: dict[str, Any], media_store: Any = None) -> None:
        self.envelope = envelope
        self.media_store = media_store

    async def download_media(self, _message: Any, output: Any) -> bytes:
        if output is not bytes:
            raise ValueError("weekly PDF owner requested an unsupported media output")
        return _download_source_pdf(self.envelope, self.media_store)


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
    version = work.get("version")
    if (
        work["pipeline_id"] != "swing_plan"
        or work["capability_id"] != "trading_plans"
        or type(version) is not int or version < 1
        or envelope["endpoint_id"] != "telegram:phintraprofits"
        or envelope["publisher_id"] != "phintraco"
    ):
        raise ValueError("unsupported Phintraco source work")
    expected = hashlib.sha256(f'{work["event_key"]}:{version}:trading_plans'.encode()).hexdigest()
    if work["effect_key"] != expected or work["work_key"] != expected or (envelope["media_required"] and not envelope["media_refs"]):
        raise ValueError("Phintraco work identity or media contract is invalid")
    message = _source_message(envelope)
    call = scan.parse_source_event(message)
    if call is None and message.document is not None:
        now = datetime.now(scan.WIB)
        with scan.run_lock() as acquired:
            if not acquired:
                raise OwnerPending("Phintraco owner ledger is busy")
            receipt_path = _receipt_path(work["effect_key"])
            if receipt_path.exists():
                if json.loads(receipt_path.read_text()) != {"effect_key": work["effect_key"], "event_key": work["event_key"], "version": version}:
                    raise ValueError("Phintraco effect receipt is invalid")
                return "accepted"
            state = scan.load_state()
            handled, _created, _quarantined = asyncio.run(
                scan._ingest_weekly_pdf_document(
                    _StoredPdfClient(envelope, media_store), message, state, now
                )
            )
            if not handled:
                return "irrelevant"
            scan.save_state(state)
            scan.drain_outbox(state, now, dry_run=no_post)
            if not no_post and any(
                event.get("pdf_batch_id") == str(message.id)
                and event.get("phase") != scan.PHASE_DELIVERED
                for event in state["outbox"].values()
            ):
                raise OwnerPending("Phintraco weekly PDF deliveries remain pending")
            _acknowledge_effect(receipt_path, work)
        return "accepted"
    if call is None and envelope["payload"].get("reply_parent"):
        parent = envelope["payload"]["reply_parent"]
        if type(parent) is not dict or set(parent) != {"message_id", "text", "published_at", "has_photo"}:
            raise ValueError("Phintraco reply parent is invalid")
        parent_message = SimpleNamespace(id=parent["message_id"], message=parent["text"], date=datetime.fromisoformat(parent["published_at"]), photo=object() if parent["has_photo"] else None)
        call = scan.parse_reply_status(message.id, message.message, False, message.date, scan.parse_source_event(parent_message))
    if call is None:
        if scan.looks_like_swing_call(message.message):
            raise ValueError("malformed Phintraco plan")
        return "irrelevant"
    now = datetime.now(scan.WIB)
    with scan.run_lock() as acquired:
        if not acquired:
            raise OwnerPending("Phintraco owner ledger is busy")
        receipt_path = _receipt_path(work["effect_key"])
        if receipt_path.exists():
            if json.loads(receipt_path.read_text()) != {"effect_key": work["effect_key"], "event_key": work["event_key"], "version": version}:
                raise ValueError("Phintraco effect receipt is invalid")
            return "accepted"
        state = scan.load_state()
        event = scan.enqueue_call(state, call, now)
        if call.event_kind in {"STATUS", "REMINDER"}:
            parent_id = envelope["payload"].get("reply_to_message_id")
            if type(parent_id) is not int:
                parent_id = None
            matched_key = scan.match_source_plan(call, state, parent_id)
            if matched_key is not None:
                event["matched_setup_event_key"] = matched_key
                event["board_kind_override"] = None
            elif scan._update_references_pdf_plan(call, state, parent_id):
                event["matched_setup_event_key"] = None
                event["board_kind_override"] = "context"
        if call.has_source_chart and scan._cached_media_path(event) is None:
            chart = _download_source_chart(envelope, media_store)
            media_path = scan.media_dir() / f"phintraco-{call.source_message_id}.jpg"
            scan._ensure_durable_directory(media_path.parent)
            scan._write_durable_media(media_path, chart)
            event["media_path"] = str(media_path)
            event["chart_status"] = "captured"
            event["phase"] = scan.PHASE_PENDING_TEXT
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
