"""Durable normalized source events and separately leased subscription work."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import threading
import uuid
from typing import Any
from urllib.parse import urlparse

from .source_catalog import catalog_view, effective_snapshot


MAX_ATTEMPTS = 5
LEASE_SECONDS = 120
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._/@-]{0,255}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_PIPELINE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


class InboxConflict(ValueError):
    pass


def _utc(value: object) -> str:
    if type(value) is not str:
        raise ValueError("timestamp must be an ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _reject_embedded_media(value: object) -> None:
    if type(value) is dict:
        for key, child in value.items():
            if type(key) is not str or re.search(r"(?:^|_)(?:base64|bytes|blob|media_data|image_data)(?:$|_)", key, re.I):
                raise ValueError("payload cannot contain media bytes")
            _reject_embedded_media(child)
    elif type(value) is list:
        for child in value:
            _reject_embedded_media(child)
    elif type(value) is str and value.startswith("data:"):
        raise ValueError("payload cannot contain data URIs")


def validate_envelope(value: object) -> dict[str, Any]:
    required = {"version", "endpoint_id", "publisher_id", "platform", "provider_event_id", "published_at", "observed_at", "source_url", "parser_version", "content_hash", "payload", "media_refs", "media_required"}
    if type(value) is not dict or set(value) != required or value["version"] != 1:
        raise ValueError("unsupported source event envelope")
    for key in ("endpoint_id", "publisher_id", "platform", "provider_event_id", "parser_version"):
        if type(value[key]) is not str or not _ID.fullmatch(value[key]):
            raise ValueError(f"invalid {key}")
    if value["platform"] not in {"telegram", "x", "instagram", "whatsapp", "rss"}:
        raise ValueError("unsupported platform")
    if type(value["content_hash"]) is not str or not _HEX.fullmatch(value["content_hash"]):
        raise ValueError("content_hash must be lowercase SHA-256")
    if type(value["source_url"]) is not str or len(value["source_url"]) > 2048:
        raise ValueError("invalid source_url")
    url = urlparse(value["source_url"])
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise ValueError("source_url must be a public HTTPS URL")
    if type(value["payload"]) is not dict or type(value["media_refs"]) is not list or len(value["media_refs"]) > 16 or type(value["media_required"]) is not bool:
        raise ValueError("invalid payload or media refs")
    try:
        if len(json.dumps(value["payload"], ensure_ascii=False, allow_nan=False).encode()) > 65_536:
            raise ValueError("payload exceeds 64 KiB")
    except (TypeError, ValueError) as exc:
        raise ValueError("payload must be bounded finite JSON") from exc
    _reject_embedded_media(value["payload"])
    for ref in value["media_refs"]:
        if type(ref) is not dict or set(ref) != {"url", "sha256", "kind", "durable"} or ref["durable"] is not True or type(ref["sha256"]) is not str or not _HEX.fullmatch(ref["sha256"]) or ref["kind"] not in {"image", "video", "document", "audio"}:
            raise ValueError("media refs require verified durable metadata")
        url = urlparse(ref["url"] if type(ref["url"]) is str else "")
        if url.scheme != "https" or not url.hostname or url.username or url.password or len(ref["url"]) > 2048:
            raise ValueError("media ref must be an HTTPS URL")
    if value["media_refs"]:
        raise ValueError("durable media storage is not configured")
    if value["media_required"] and not value["media_refs"]:
        raise ValueError("media-dependent processing requires durable media refs")
    result = deepcopy(value)
    result["published_at"] = _utc(value["published_at"])
    result["observed_at"] = _utc(value["observed_at"])
    return result


def event_key(envelope: dict[str, Any]) -> str:
    identity = json.dumps([envelope["platform"], envelope["endpoint_id"], envelope["provider_event_id"]], separators=(",", ":"))
    return hashlib.sha256(identity.encode()).hexdigest()


def work_key(key: str, version: int, capability: str) -> str:
    return hashlib.sha256(f"{key}:{version}:{capability}".encode()).hexdigest()


def _pipeline_filter(values: object) -> tuple[str, ...]:
    if type(values) is not list or not 1 <= len(values) <= 32 or any(type(value) is not str or not _PIPELINE.fullmatch(value) for value in values) or len(set(values)) != len(values):
        raise ValueError("pipeline claim requires unique supported pipeline IDs")
    return tuple(values)


def _revision_identity(value: object) -> str:
    if type(value) is not str or not _ID.fullmatch(value) or len(value) > 128:
        raise ValueError("revision_id must be a bounded stable provider revision identity")
    return value


def _same_revision(existing: dict[str, Any], envelope: dict[str, Any], kind: str) -> bool:
    return existing["kind"] == kind and existing["envelope"]["content_hash"] == envelope["content_hash"] and existing["envelope"]["publisher_id"] == envelope["publisher_id"]


def _subscriptions(catalog: dict[str, Any], registry: dict[str, Any], envelope: dict[str, Any]) -> list[dict[str, Any]]:
    view = catalog_view(catalog["config"], registry)
    endpoints = {row["id"]: row for row in view["endpoints"]}
    endpoint = endpoints.get(envelope["endpoint_id"])
    if endpoint is None or (endpoint["publisher_id"], endpoint["platform"]) != (envelope["publisher_id"], envelope["platform"]):
        raise ValueError("source endpoint identity does not match catalog")
    effective = effective_snapshot(catalog["config"], view, catalog["revision"], catalog["updated_at"])
    capabilities = {row["id"]: row for row in registry["capabilities"]}
    result = []
    for row in effective["subscriptions"]:
        if row["endpoint_id"] == envelope["endpoint_id"] and row["enabled"]:
            capability = capabilities[row["capability_id"]]
            result.append({"capability_id": row["capability_id"], "pipeline": row["pipeline"], "capability_version": capability["version"], "catalog_revision": catalog["revision"], "settings": deepcopy(row["settings"]), "config_source": row["source"]})
    return result


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryInboxStore:
    """Contract model for local exploration; never a production fallback."""
    def __init__(self, catalog_store):
        self.catalog = catalog_store
        self.events: dict[str, dict[str, Any]] = {}
        self.work: dict[str, dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.lock = threading.RLock()

    def accept(self, raw: object) -> dict[str, Any]:
        envelope = validate_envelope(raw)
        key = event_key(envelope)
        with self.lock:
            old = self.events.get(key)
            if old:
                if old["versions"][0]["envelope"]["content_hash"] != envelope["content_hash"]:
                    raise InboxConflict("provider identity already accepted with different content; use correction")
                return {"event_key": key, "version": 1, "duplicate": True, "work_keys": [k for k, w in self.work.items() if w["event_key"] == key and w["version"] == 1]}
            subs = _subscriptions(self.catalog.get(), self.catalog.registry(), envelope)
            self.events[key] = {"event_key": key, "versions": [{"version": 1, "envelope": envelope, "kind": "original"}]}
            keys = []
            for sub in subs:
                item = self._create_work(key, 1, sub)
                keys.append(item["work_key"])
            return {"event_key": key, "version": 1, "duplicate": False, "work_keys": keys}

    def _create_work(self, key: str, version: int, sub: dict[str, Any]) -> dict[str, Any]:
        wid = work_key(key, version, sub["capability_id"])
        item = {"work_key": wid, "event_key": key, "version": version, **deepcopy(sub), "pipeline_id": sub["pipeline"], "effect_key": wid, "status": "pending", "attempts": 0, "available_at": _now().isoformat(), "lease_token": None, "lease_until": None, "error_code": None}
        self.work[wid] = item
        return item

    def claim(self, pipeline_ids: list[str], limit: int = 10) -> list[dict[str, Any]]:
        pipelines = _pipeline_filter(pipeline_ids)
        if not 1 <= limit <= 100:
            raise ValueError("claim limit out of range")
        result = []
        with self.lock:
            now = _now()
            for item in self.work.values():
                if len(result) >= limit:
                    break
                if item["pipeline_id"] not in pipelines or item["version"] != len(self.events[item["event_key"]]["versions"]) or item["status"] not in {"pending", "leased"} or (item["status"] == "pending" and datetime.fromisoformat(item["available_at"]) > now) or (item["status"] == "leased" and datetime.fromisoformat(item["lease_until"]) > now):
                    continue
                if item["attempts"] >= MAX_ATTEMPTS:
                    item.update(status="dead_letter", lease_token=None, lease_until=None, error_code="attempts_exhausted")
                    continue
                item.update(status="leased", attempts=item["attempts"] + 1, lease_token=str(uuid.uuid4()), lease_until=(now + timedelta(seconds=LEASE_SECONDS)).isoformat())
                version = self.events[item["event_key"]]["versions"][item["version"] - 1]
                result.append({**deepcopy(item), "event_kind": version["kind"], "envelope": deepcopy(version["envelope"])})
        return result

    def settle(self, wid: str, token: str, *, success: bool, error_code: str | None = None) -> dict[str, Any]:
        with self.lock:
            item = self.work.get(wid)
            if not item or item["status"] != "leased" or item["lease_token"] != token or datetime.fromisoformat(item["lease_until"]) <= _now():
                raise InboxConflict("work lease is missing or expired")
            if success:
                item.update(status="done", error_code=None)
            else:
                if type(error_code) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error_code):
                    raise ValueError("error_code must be sanitized")
                item.update(status="dead_letter" if item["attempts"] >= MAX_ATTEMPTS else "pending", error_code=error_code, available_at=(_now() + timedelta(seconds=min(3600, 2 ** item["attempts"] * 30))).isoformat())
            item.update(lease_token=None, lease_until=None)
            return deepcopy(item)

    def fence(self, wid: str, token: str) -> bool:
        with self.lock:
            item = self.work.get(wid)
            return bool(item and item["status"] == "leased" and item["lease_token"] == token and datetime.fromisoformat(item["lease_until"]) > _now() and item["version"] == len(self.events[item["event_key"]]["versions"]))

    def inspect(self, key: str) -> dict[str, Any]:
        with self.lock:
            if key not in self.events:
                raise KeyError(key)
            return {"event": deepcopy(self.events[key]), "work": [deepcopy(w) for w in self.work.values() if w["event_key"] == key]}

    def list_work(self, status: str, limit: int = 100) -> list[dict[str, Any]]:
        if status not in {"pending", "leased", "done", "dead_letter", "suppressed", "superseded"} or not 1 <= limit <= 100:
            raise ValueError("invalid work filter")
        with self.lock:
            return [deepcopy(w) for w in self.work.values() if w["status"] == status][:limit]

    def suppress(self, wid: str, actor: str, reason: str) -> dict[str, Any]:
        with self.lock:
            item = self.work.get(wid)
            if not item or item["status"] not in {"pending", "dead_letter"}:
                raise InboxConflict("only idle work can be suppressed")
            self._audit("suppress", wid, actor, reason)
            item.update(status="suppressed", lease_token=None, lease_until=None)
            return deepcopy(item)

    def replay(self, wid: str, actor: str, reason: str) -> dict[str, Any]:
        with self.lock:
            item = self.work.get(wid)
            if not item or item["status"] not in {"dead_letter", "suppressed"}:
                raise InboxConflict("only dead-letter or suppressed work can be replayed")
            self._audit("replay", wid, actor, reason)
            item.update(status="pending", attempts=0, available_at=_now().isoformat(), lease_token=None, lease_until=None, error_code=None)
            return deepcopy(item)

    def revise(self, key: str, raw: object, kind: str, revision_id: str, actor: str, reason: str) -> dict[str, Any]:
        if kind not in {"correction", "tombstone"}:
            raise ValueError("invalid revision kind")
        revision_id = _revision_identity(revision_id)
        envelope = validate_envelope(raw)
        if event_key(envelope) != key:
            raise ValueError("correction must retain provider identity")
        with self.lock:
            event = self.events.get(key)
            if not event:
                raise KeyError(key)
            original_envelope = event["versions"][0]["envelope"]
            if envelope["publisher_id"] != original_envelope["publisher_id"]:
                raise ValueError("correction must retain publisher identity")
            for existing in event["versions"][1:]:
                if existing["revision_id"] == revision_id:
                    if not _same_revision(existing, envelope, kind):
                        raise InboxConflict("revision identity already accepted with different content")
                    version = existing["version"]
                    return {"event_key": key, "version": version, "duplicate": True, "work_keys": [wid for wid, item in self.work.items() if item["event_key"] == key and item["version"] == version]}
            previous = event["versions"][-1]
            if previous["kind"] == "tombstone":
                raise InboxConflict("tombstoned source event cannot be revised")
            if kind == "tombstone" and envelope["payload"]:
                raise ValueError("tombstone payload must be empty")
            if previous["envelope"] == envelope and previous["kind"] == kind:
                raise InboxConflict("duplicate correction")
            version = len(event["versions"]) + 1
            self._audit(kind, key, actor, reason, before=previous["envelope"]["content_hash"], after=envelope["content_hash"])
            event["versions"].append({"version": version, "kind": kind, "revision_id": revision_id, "envelope": envelope})
            for item in self.work.values():
                if item["event_key"] == key and item["version"] < version and item["status"] != "done":
                    item.update(status="superseded", lease_token=None, lease_until=None)
            subs = [
                {field: item[field] for field in ("capability_id", "pipeline", "capability_version", "catalog_revision", "settings", "config_source")}
                for item in self.work.values() if item["event_key"] == key and item["version"] == 1
            ]
            return {"event_key": key, "version": version, "duplicate": False, "work_keys": [self._create_work(key, version, sub)["work_key"] for sub in subs]}

    def _audit(self, action: str, target: str, actor: str, reason: str, **extra) -> None:
        if not actor or type(reason) is not str or not 1 <= len(reason.strip()) <= 500:
            raise ValueError("actor and bounded reason required")
        self.audit.append({"action": action, "target": target, "actor_id": actor, "reason": reason, "at": _now().isoformat(), **extra})


class PostgresInboxStore:
    def __init__(self, dsn: str, catalog_store):
        self.dsn = dsn
        self.catalog = catalog_store

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn, row_factory=dict_row)

    @staticmethod
    def _work(row):
        result = dict(row)
        for field in ("available_at", "lease_until"):
            if result.get(field) is not None:
                result[field] = result[field].isoformat()
        return result

    def accept(self, raw: object) -> dict[str, Any]:
        envelope = validate_envelope(raw)
        key = event_key(envelope)
        with self._connect() as conn:
            conn.execute("select pg_advisory_xact_lock(71938142)")
            old = conn.execute("select envelope from bursawatch_source_event_versions where event_key=%s and version=1", (key,)).fetchone()
            if old:
                if old["envelope"]["content_hash"] != envelope["content_hash"]:
                    raise InboxConflict("provider identity already accepted with different content; use correction")
                rows = conn.execute("select work_key from bursawatch_source_work where event_key=%s and version=1 order by work_key", (key,)).fetchall()
                return {"event_key": key, "version": 1, "duplicate": True, "work_keys": [r["work_key"] for r in rows]}
            subs = _subscriptions(self.catalog.get(), self.catalog.registry(), envelope)
            conn.execute("insert into bursawatch_source_events (event_key, endpoint_id, publisher_id, platform, provider_event_id) values (%s,%s,%s,%s,%s)", (key, envelope["endpoint_id"], envelope["publisher_id"], envelope["platform"], envelope["provider_event_id"]))
            conn.execute("insert into bursawatch_source_event_versions (event_key, version, kind, envelope, content_hash) values (%s,1,'original',%s::jsonb,%s)", (key, json.dumps(envelope), envelope["content_hash"]))
            keys = [self._insert_work(conn, key, 1, sub) for sub in subs]
            return {"event_key": key, "version": 1, "duplicate": False, "work_keys": keys}

    def _insert_work(self, conn, key, version, sub):
        wid = work_key(key, version, sub["capability_id"])
        conn.execute("insert into bursawatch_source_work (work_key,event_key,version,capability_id,pipeline_id,capability_version,catalog_revision,settings,config_source,effect_key) values (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)", (wid, key, version, sub["capability_id"], sub["pipeline"], sub["capability_version"], sub["catalog_revision"], json.dumps(sub["settings"]), sub["config_source"], wid))
        return wid

    def claim(self, pipeline_ids: list[str], limit: int = 10) -> list[dict[str, Any]]:
        pipelines = _pipeline_filter(pipeline_ids)
        if not 1 <= limit <= 100:
            raise ValueError("claim limit out of range")
        with self._connect() as conn:
            rows = conn.execute("select w.work_key, w.attempts from bursawatch_source_work w where w.pipeline_id = any(%s) and not exists (select 1 from bursawatch_source_event_versions newer where newer.event_key=w.event_key and newer.version>w.version) and ((w.status='pending' and w.available_at <= now()) or (w.status='leased' and w.lease_until <= now())) order by w.available_at, w.work_key for update of w skip locked limit %s", (list(pipelines), limit)).fetchall()
            result = []
            for row in rows:
                wid = row["work_key"]
                if row["attempts"] >= MAX_ATTEMPTS:
                    conn.execute("update bursawatch_source_work set status='dead_letter', lease_token=null, lease_until=null, error_code='attempts_exhausted' where work_key=%s", (wid,))
                    continue
                token = str(uuid.uuid4())
                item = conn.execute("update bursawatch_source_work set status='leased', attempts=attempts+1, lease_token=%s, lease_until=now()+interval '120 seconds' where work_key=%s returning *", (token, wid)).fetchone()
                version = conn.execute("select kind,envelope from bursawatch_source_event_versions where event_key=%s and version=%s", (item["event_key"], item["version"])).fetchone()
                result.append({**self._work(item), "event_kind": version["kind"], "envelope": version["envelope"]})
            return result

    def settle(self, wid: str, token: str, *, success: bool, error_code: str | None = None) -> dict[str, Any]:
        if not success and (type(error_code) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error_code)):
            raise ValueError("error_code must be sanitized")
        with self._connect() as conn:
            row = conn.execute("select * from bursawatch_source_work where work_key=%s for update", (wid,)).fetchone()
            if not row or row["status"] != "leased" or row["lease_token"] != token or row["lease_until"] <= _now():
                raise InboxConflict("work lease is missing or expired")
            status = "done" if success else "dead_letter" if row["attempts"] >= MAX_ATTEMPTS else "pending"
            delay = min(3600, 2 ** row["attempts"] * 30)
            updated = conn.execute("update bursawatch_source_work set status=%s, error_code=%s, available_at=now()+(%s * interval '1 second'), lease_token=null, lease_until=null where work_key=%s returning *", (status, None if success else error_code, 0 if success else delay, wid)).fetchone()
            return self._work(updated)

    def fence(self, wid: str, token: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("select w.event_key,w.version,w.status,w.lease_token,w.lease_until,(select max(v.version) from bursawatch_source_event_versions v where v.event_key=w.event_key) as current_version from bursawatch_source_work w where w.work_key=%s", (wid,)).fetchone()
            return bool(row and row["status"] == "leased" and row["lease_token"] == token and row["lease_until"] > _now() and row["version"] == row["current_version"])

    def inspect(self, key: str) -> dict[str, Any]:
        with self._connect() as conn:
            event = conn.execute("select event_key, endpoint_id, publisher_id, platform, provider_event_id, created_at from bursawatch_source_events where event_key=%s", (key,)).fetchone()
            if not event:
                raise KeyError(key)
            versions = conn.execute("select version,kind,revision_id,envelope,created_at,actor_id,reason from bursawatch_source_event_versions where event_key=%s order by version", (key,)).fetchall()
            work = conn.execute("select * from bursawatch_source_work where event_key=%s order by version,capability_id", (key,)).fetchall()
            return {"event": {**dict(event), "created_at": event["created_at"].isoformat(), "versions": [{**dict(v), "created_at": v["created_at"].isoformat()} for v in versions]}, "work": [self._work(w) for w in work]}

    def list_work(self, status: str, limit: int = 100) -> list[dict[str, Any]]:
        if status not in {"pending", "leased", "done", "dead_letter", "suppressed", "superseded"} or not 1 <= limit <= 100:
            raise ValueError("invalid work filter")
        with self._connect() as conn:
            rows = conn.execute("select * from bursawatch_source_work where status=%s order by available_at,work_key limit %s", (status, limit)).fetchall()
            return [self._work(row) for row in rows]

    def _operator_action(self, wid: str, actor: str, reason: str, action: str) -> dict[str, Any]:
        if not actor or type(reason) is not str or not 1 <= len(reason.strip()) <= 500:
            raise ValueError("actor and bounded reason required")
        with self._connect() as conn:
            row = conn.execute("select status from bursawatch_source_work where work_key=%s for update", (wid,)).fetchone()
            allowed = ("pending", "dead_letter") if action == "suppress" else ("dead_letter", "suppressed")
            if not row or row["status"] not in allowed:
                raise InboxConflict("work state disallows operator action")
            status = "suppressed" if action == "suppress" else "pending"
            updated = conn.execute("update bursawatch_source_work set status=%s, attempts=case when %s='replay' then 0 else attempts end, available_at=now(), lease_token=null, lease_until=null, error_code=null where work_key=%s returning *", (status, action, wid)).fetchone()
            conn.execute("insert into bursawatch_source_work_audit (work_key,action,actor_id,reason) values (%s,%s,%s,%s)", (wid, action, actor, reason))
            return self._work(updated)

    def suppress(self, wid: str, actor: str, reason: str) -> dict[str, Any]:
        return self._operator_action(wid, actor, reason, "suppress")

    def replay(self, wid: str, actor: str, reason: str) -> dict[str, Any]:
        return self._operator_action(wid, actor, reason, "replay")

    def revise(self, key: str, raw: object, kind: str, revision_id: str, actor: str, reason: str) -> dict[str, Any]:
        if kind not in {"correction", "tombstone"}:
            raise ValueError("invalid revision kind")
        revision_id = _revision_identity(revision_id)
        envelope = validate_envelope(raw)
        if event_key(envelope) != key or (kind == "tombstone" and envelope["payload"]):
            raise ValueError("revision identity or tombstone payload is invalid")
        if not actor or type(reason) is not str or not 1 <= len(reason.strip()) <= 500:
            raise ValueError("actor and bounded reason required")
        with self._connect() as conn:
            conn.execute("select pg_advisory_xact_lock(71938142)")
            source = conn.execute("select publisher_id from bursawatch_source_events where event_key=%s", (key,)).fetchone()
            if not source:
                raise KeyError(key)
            if source["publisher_id"] != envelope["publisher_id"]:
                raise ValueError("correction must retain publisher identity")
            prior = conn.execute("select version,kind,envelope from bursawatch_source_event_versions where event_key=%s and revision_id=%s", (key, revision_id)).fetchone()
            if prior:
                if not _same_revision(prior, envelope, kind):
                    raise InboxConflict("revision identity already accepted with different content")
                rows = conn.execute("select work_key from bursawatch_source_work where event_key=%s and version=%s order by work_key", (key, prior["version"])).fetchall()
                return {"event_key": key, "version": prior["version"], "duplicate": True, "work_keys": [row["work_key"] for row in rows]}
            old = conn.execute("select version,kind,envelope from bursawatch_source_event_versions where event_key=%s order by version desc limit 1 for update", (key,)).fetchone()
            if not old:
                raise KeyError(key)
            if old["kind"] == "tombstone":
                raise InboxConflict("tombstoned source event cannot be revised")
            if old["envelope"] == envelope and old["kind"] == kind:
                raise InboxConflict("duplicate correction")
            version = old["version"] + 1
            original = conn.execute("select capability_id,pipeline_id,capability_version,catalog_revision,settings,config_source from bursawatch_source_work where event_key=%s and version=1", (key,)).fetchall()
            subs = [{"capability_id": row["capability_id"], "pipeline": row["pipeline_id"], "capability_version": row["capability_version"], "catalog_revision": row["catalog_revision"], "settings": row["settings"], "config_source": row["config_source"]} for row in original]
            conn.execute("insert into bursawatch_source_event_versions (event_key,version,kind,envelope,content_hash,actor_id,reason,revision_id) values (%s,%s,%s,%s::jsonb,%s,%s,%s,%s)", (key, version, kind, json.dumps(envelope), envelope["content_hash"], actor, reason, revision_id))
            conn.execute("update bursawatch_source_work set status='superseded', lease_token=null, lease_until=null where event_key=%s and version<%s and status<>'done'", (key, version))
            keys = [self._insert_work(conn, key, version, sub) for sub in subs]
            return {"event_key": key, "version": version, "duplicate": False, "work_keys": keys}
