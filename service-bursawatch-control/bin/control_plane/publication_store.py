"""Immutable, forward-only publication read model and deterministic paging."""

from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from .publication_model import OWNER_ROUTES, validate_publication


class PublicationConflict(ValueError):
    """A cutover, publication key, or version conflicts with accepted state."""


FILTER_KEYS = {"type", "route", "date_from", "date_to", "source", "ticker"}


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _normalize_filters(filters: dict[str, str] | None) -> dict[str, str]:
    if filters is None:
        return {}
    if type(filters) is not dict or set(filters) - FILTER_KEYS:
        raise ValueError("publication filters are invalid")
    clean: dict[str, str] = {}
    for key, value in filters.items():
        if type(value) is not str or not 1 <= len(value) <= 200:
            raise ValueError("publication filter is invalid")
        clean[key] = value
    for key in ("date_from", "date_to"):
        if key in clean:
            try:
                parsed = datetime.fromisoformat(clean[key].replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("publication date filter is invalid") from exc
            if parsed.tzinfo is None:
                raise ValueError("publication date filter must have timezone")
            clean[key] = parsed.astimezone(timezone.utc).isoformat()
    return clean


def _cursor_encode(sort_key: tuple[str, str, int], filters: dict[str, str]) -> str:
    payload = {"key": sort_key, "filters_sha256": hashlib.sha256(_canonical(filters)).hexdigest()}
    return base64.urlsafe_b64encode(_canonical(payload)).decode("ascii").rstrip("=")


def _cursor_decode(value: str, filters: dict[str, str]) -> tuple[str, str, int]:
    if type(value) is not str or not 1 <= len(value) <= 2048:
        raise ValueError("publication cursor is invalid")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("publication cursor is invalid") from exc
    key = payload.get("key") if type(payload) is dict else None
    expected_hash = hashlib.sha256(_canonical(filters)).hexdigest()
    if (
        type(payload) is not dict
        or payload.get("filters_sha256") != expected_hash
        or type(key) is not list
        or len(key) != 3
        or type(key[0]) is not str
        or type(key[1]) is not str
        or type(key[2]) is not int
    ):
        raise ValueError("publication cursor is invalid for these filters")
    return key[0], key[1], key[2]


def _matches(row: dict[str, Any], filters: dict[str, str]) -> bool:
    if "type" in filters and row["type"] != filters["type"]:
        return False
    if "route" in filters and row["route"] != filters["route"]:
        return False
    if "ticker" in filters and row["ticker"] != filters["ticker"]:
        return False
    if "source" in filters and filters["source"].casefold() not in row["source_name"].casefold():
        return False
    if "date_from" in filters and row["delivery_confirmed_at"] < filters["date_from"]:
        return False
    if "date_to" in filters and row["delivery_confirmed_at"] > filters["date_to"]:
        return False
    return True


def _sort_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return row["delivery_confirmed_at"], row["publication_id"], row["version"]


class MemoryPublicationStore:
    def __init__(self) -> None:
        self._cutover: dict[str, Any] | None = None
        self._rows: dict[tuple[str, int], dict[str, Any]] = {}

    def activate(self, boundary: str, owner_ids: tuple[str, ...]) -> None:
        if self._cutover is not None:
            raise PublicationConflict("publication cutover is already active")
        if type(owner_ids) is not tuple or not owner_ids or len(owner_ids) != len(set(owner_ids)) or any(owner not in OWNER_ROUTES for owner in owner_ids):
            raise ValueError("publication owner set is invalid")
        try:
            at = datetime.fromisoformat(boundary.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise ValueError("publication cutover boundary is invalid") from exc
        if at.tzinfo is None:
            raise ValueError("publication cutover boundary needs timezone")
        self._cutover = {"boundary": at.isoformat(), "owner_ids": tuple(owner_ids)}

    def cutover(self) -> dict[str, Any] | None:
        return deepcopy(self._cutover)

    def accept(self, owner_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        if self._cutover is None:
            raise PublicationConflict("publication cutover is not active")
        if owner_id not in self._cutover["owner_ids"]:
            raise ValueError("publication owner is outside the cutover set")
        record = validate_publication(snapshot, owner_id)
        if datetime.fromisoformat(record["delivery_confirmed_at"]) <= datetime.fromisoformat(self._cutover["boundary"]):
            raise ValueError("publication delivery is before or at cutover")
        publication_id = record["publication_id"]
        key = (publication_id, record["version"])
        existing = self._rows.get(key)
        if existing is not None:
            if existing["digest"] != record["digest"]:
                raise PublicationConflict("publication version digest conflicts with accepted output")
            return self._ack(existing)
        if record["version"] > 1 and (publication_id, record["version"] - 1) not in self._rows:
            raise PublicationConflict("publication previous version is missing")
        if record["version"] == 1 and any(identity == publication_id for identity, _version in self._rows):
            raise PublicationConflict("publication initial version is missing or conflicts")
        self._rows[key] = deepcopy(record)
        return self._ack(record)

    @staticmethod
    def _ack(record: dict[str, Any]) -> dict[str, Any]:
        return {"publication_id": record["publication_id"], "version": record["version"], "digest": record["digest"]}

    def get(self, publication_id: str) -> dict[str, Any]:
        versions = [deepcopy(row) for (identity, _version), row in self._rows.items() if identity == publication_id]
        if not versions:
            raise KeyError(publication_id)
        versions.sort(key=lambda row: row["version"])
        linked = [
            {"publication_id": identity, "type": row["type"], "delivery_confirmed_at": row["delivery_confirmed_at"]}
            for (identity, version), row in self._rows.items()
            if version == 1 and row["parent_publication_id"] == publication_id
        ]
        linked.sort(key=lambda row: (row["delivery_confirmed_at"], row["publication_id"]))
        return {"publication_id": publication_id, "versions": versions, "linked": linked}

    def list_page(self, *, limit: int = 20, cursor: str | None = None, filters: dict[str, str] | None = None) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("publication page limit is invalid")
        clean_filters = _normalize_filters(filters)
        cursor_key = _cursor_decode(cursor, clean_filters) if cursor is not None else None
        latest: dict[str, dict[str, Any]] = {}
        for (identity, _version), row in self._rows.items():
            previous = latest.get(identity)
            if previous is None or previous["version"] < row["version"]:
                latest[identity] = row
        rows = [row for row in latest.values() if _matches(row, clean_filters)]
        rows.sort(key=_sort_key, reverse=True)
        if cursor_key is not None:
            rows = [row for row in rows if _sort_key(row) < cursor_key]
        page = rows[:limit]
        next_cursor = _cursor_encode(_sort_key(page[-1]), clean_filters) if len(rows) > limit and page else None
        return {"items": deepcopy(page), "next_cursor": next_cursor}


class PostgresPublicationStore:
    """Publication read model using the Control Plane's process-local pool."""

    def __init__(self, dsn: str, *, pool: Any | None = None) -> None:
        self.dsn = dsn
        self.pool = pool

    def _connect(self):
        if self.pool is not None:
            return self.pool.connection()
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.dsn, row_factory=dict_row, prepare_threshold=None)

    @staticmethod
    def _decode(value: object) -> dict[str, Any]:
        if type(value) is str:
            value = json.loads(value)
        if type(value) is not dict:
            raise RuntimeError("stored publication snapshot is invalid")
        return deepcopy(value)

    def activate(self, boundary: str, owner_ids: tuple[str, ...]) -> None:
        # Reuse the exact memory validation before touching persistent state.
        candidate = MemoryPublicationStore()
        candidate.activate(boundary, owner_ids)
        cutover = candidate.cutover()
        assert cutover is not None
        import psycopg

        try:
            with self._connect() as conn:
                conn.execute(
                    "insert into bursawatch_publication_cutover (singleton, boundary_at, owner_ids) "
                    "values (true, %s::timestamptz, %s::jsonb)",
                    (cutover["boundary"], json.dumps(list(cutover["owner_ids"]))),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise PublicationConflict("publication cutover is already active") from exc

    def cutover(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "select boundary_at, owner_ids from bursawatch_publication_cutover where singleton = true"
            ).fetchone()
        if row is None:
            return None
        owner_ids = row["owner_ids"]
        if type(owner_ids) is str:
            owner_ids = json.loads(owner_ids)
        return {"boundary": row["boundary_at"].isoformat(), "owner_ids": tuple(owner_ids)}

    def accept(self, owner_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        record = validate_publication(snapshot, owner_id)
        publication_id = record["publication_id"]
        with self._connect() as conn:
            cutover = conn.execute(
                "select boundary_at, owner_ids from bursawatch_publication_cutover where singleton = true"
            ).fetchone()
            if cutover is None:
                raise PublicationConflict("publication cutover is not active")
            owners = cutover["owner_ids"]
            if type(owners) is str:
                owners = json.loads(owners)
            if owner_id not in owners:
                raise ValueError("publication owner is outside the cutover set")
            if datetime.fromisoformat(record["delivery_confirmed_at"]) <= cutover["boundary_at"]:
                raise ValueError("publication delivery is before or at cutover")
            conn.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", (publication_id,))
            existing = conn.execute(
                "select digest from bursawatch_publications where publication_id = %s and version = %s",
                (publication_id, record["version"]),
            ).fetchone()
            if existing is not None:
                if existing["digest"] != record["digest"]:
                    raise PublicationConflict("publication version digest conflicts with accepted output")
                return MemoryPublicationStore._ack(record)
            previous = conn.execute(
                "select max(version) as latest from bursawatch_publications where publication_id = %s",
                (publication_id,),
            ).fetchone()["latest"]
            if (record["version"] == 1 and previous is not None) or (
                record["version"] > 1 and previous != record["version"] - 1
            ):
                raise PublicationConflict("publication previous version is missing or conflicts")
            conn.execute(
                "insert into bursawatch_publications "
                "(publication_id, version, owner_id, owner_key, publication_type, route, "
                "source_name, ticker, delivery_confirmed_at, parent_publication_id, digest, snapshot) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s::timestamptz, %s, %s, %s::jsonb)",
                (
                    publication_id, record["version"], owner_id, record["owner_key"], record["type"],
                    record["route"], record["source_name"], record["ticker"],
                    record["delivery_confirmed_at"], record["parent_publication_id"],
                    record["digest"], json.dumps(record, ensure_ascii=False),
                ),
            )
        return MemoryPublicationStore._ack(record)

    def get(self, publication_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            version_rows = conn.execute(
                "select snapshot from bursawatch_publications where publication_id = %s order by version",
                (publication_id,),
            ).fetchall()
            if not version_rows:
                raise KeyError(publication_id)
            linked_rows = conn.execute(
                "select distinct on (publication_id) publication_id, publication_type, delivery_confirmed_at "
                "from bursawatch_publications where parent_publication_id = %s "
                "order by publication_id, version desc",
                (publication_id,),
            ).fetchall()
        versions = [self._decode(row["snapshot"]) for row in version_rows]
        linked = [
            {
                "publication_id": row["publication_id"],
                "type": row["publication_type"],
                "delivery_confirmed_at": row["delivery_confirmed_at"].isoformat(),
            }
            for row in linked_rows
        ]
        linked.sort(key=lambda row: (row["delivery_confirmed_at"], row["publication_id"]))
        return {"publication_id": publication_id, "versions": versions, "linked": linked}

    def list_page(self, *, limit: int = 20, cursor: str | None = None, filters: dict[str, str] | None = None) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("publication page limit is invalid")
        clean_filters = _normalize_filters(filters)
        cursor_key = _cursor_decode(cursor, clean_filters) if cursor is not None else None
        where: list[str] = []
        parameters: list[object] = []
        for key, column in (("type", "publication_type"), ("route", "route"), ("ticker", "ticker")):
            if key in clean_filters:
                where.append(f"{column} = %s")
                parameters.append(clean_filters[key])
        if "source" in clean_filters:
            where.append("position(lower(%s) in lower(source_name)) > 0")
            parameters.append(clean_filters["source"])
        if "date_from" in clean_filters:
            where.append("delivery_confirmed_at >= %s::timestamptz")
            parameters.append(clean_filters["date_from"])
        if "date_to" in clean_filters:
            where.append("delivery_confirmed_at <= %s::timestamptz")
            parameters.append(clean_filters["date_to"])
        if cursor_key is not None:
            where.append("(delivery_confirmed_at, publication_id, version) < (%s::timestamptz, %s, %s)")
            parameters.extend(cursor_key)
        predicate = " where " + " and ".join(where) if where else ""
        query = (
            "with latest as (select distinct on (publication_id) publication_id, version, "
            "publication_type, route, source_name, ticker, delivery_confirmed_at, snapshot "
            "from bursawatch_publications order by publication_id, version desc) "
            f"select snapshot from latest{predicate} "
            "order by delivery_confirmed_at desc, publication_id desc, version desc limit %s"
        )
        parameters.append(limit + 1)
        with self._connect() as conn:
            rows = conn.execute(query, parameters).fetchall()
        records = [self._decode(row["snapshot"]) for row in rows]
        page = records[:limit]
        next_cursor = _cursor_encode(_sort_key(page[-1]), clean_filters) if len(records) > limit and page else None
        return {"items": page, "next_cursor": next_cursor}
