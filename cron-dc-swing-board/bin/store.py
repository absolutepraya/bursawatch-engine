"""Single-owner durable store for the IDX Swing plan board.

The store records intent only. Discord operations are performed later by the
owner's outbox drainer, never from these transaction methods.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import fcntl
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Mapping
from uuid import uuid4

from models import Checkpoint, Episode, MarketState, OutboxOperation, PlanLevels, SourceEvent, SubmittedEvent


SCHEMA_VERSION = 12
_LEGAL_OPERATIONS = frozenset(
    {"create_thread", "edit_starter", "post_source_reply", "post_history_reply", "delete_message", "patch_thread"}
)
_BACKOFF_MINUTES = (1, 2, 4, 8, 15, 30, 60)
_LEASE = timedelta(minutes=5)
_TABLES = frozenset({"source_events", "episodes", "plans", "checkpoints", "history_events", "outbox", "close_attempts", "channel_outbox"})


class StoreBlockedError(RuntimeError):
    """The database cannot be safely opened without operator intervention."""


@dataclass(frozen=True)
class ActivePrimaryPlan:
    """The sole mutable plan selected for a close-phase transaction."""

    episode: Episode
    plan_id: int
    event: SourceEvent
    source_updated_at: datetime


@dataclass(frozen=True)
class PlanCard:
    """Latest plan projection used when rewriting an existing starter card."""

    episode: Episode
    plan_id: int
    event_id: int
    event: SourceEvent
    source_updated_at: datetime


@dataclass(frozen=True)
class SourceReply:
    """A completed board source reply that can be safely rewritten in place."""

    outbox_id: int
    episode: Episode
    event: SourceEvent
    message_id: str
    chunk_index: int
    current_content: str
    has_media: bool
    is_history: bool


@dataclass(frozen=True)
class ChannelOutboxOperation:
    """Durable typed channel delivery intent, currently used by heartbeats."""

    id: int
    channel_id: str
    content: str
    dedupe_key: str
    attempts: int
    status: str
    claim_token: str | None


class BoardStore:
    """Owns the board SQLite file and its retry-safe outbound intents."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.lock_path = Path(f"{self.path}.lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @property
    def schema_version(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def submit_event(self, event: SourceEvent, received_at: datetime) -> SubmittedEvent:
        """Atomically store immutable source identity, without creating outbox work."""
        received_at = _aware(received_at, "received_at")
        with self._transaction() as connection:
            return self._submit_event(connection, event, received_at)

    @staticmethod
    def _submit_event(
        connection: sqlite3.Connection, event: SourceEvent, received_at: datetime
    ) -> SubmittedEvent:
        cursor = connection.execute(
                """
                INSERT INTO source_events (
                    event_key, source, kind, ticker, published_at, source_url,
                    all_content, source_title, source_status, plan_entry,
                    plan_stop_loss, plan_targets_json, media_path, media_urls_json,
                    matched_setup_event_key, media_paths_json, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_key) DO NOTHING
                """,
                (
                    event.event_key,
                    event.source,
                    event.kind,
                    event.ticker,
                    _timestamp(event.published_at),
                    event.source_url,
                    event.all_content,
                    event.source_title,
                    event.source_status,
                    event.plan.entry if event.plan else None,
                    event.plan.stop_loss if event.plan else None,
                    json.dumps(event.plan.targets) if event.plan else None,
                    event.media_path,
                    json.dumps(event.media_urls),
                    event.matched_setup_event_key,
                    json.dumps(event.media_paths),
                    _timestamp(received_at),
                ),
        )
        if cursor.rowcount:
            return SubmittedEvent(int(cursor.lastrowid), True)
        row = connection.execute(
            "SELECT id FROM source_events WHERE event_key = ?", (event.event_key,)
        ).fetchone()
        return SubmittedEvent(int(row[0]), False)

    def create_episode(
        self, ticker: str, lifecycle: str, title: str, opened_at: datetime
    ) -> Episode:
        with self._transaction() as connection:
            return self._create_episode(connection, ticker, lifecycle, title, opened_at)

    def _create_episode(
        self,
        connection: sqlite3.Connection,
        ticker: str,
        lifecycle: str,
        title: str,
        opened_at: datetime,
    ) -> Episode:
        if lifecycle not in {"source", "primary"}:
            raise ValueError("new episode lifecycle must be source or primary")
        if not ticker or not ticker.isupper() or not title.strip():
            raise ValueError("episode ticker and title must be non-empty")
        opened_at = _aware(opened_at, "opened_at")
        try:
            cursor = connection.execute(
                """
                INSERT INTO episodes (ticker, lifecycle, title, opened_at, latest_material_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ticker, lifecycle, title, _timestamp(opened_at), _timestamp(opened_at)),
            )
        except sqlite3.IntegrityError as exc:
            raise StoreBlockedError(f"ticker {ticker} already has an open episode") from exc
        return self._episode(connection, int(cursor.lastrowid))

    def active_episode(self, ticker: str) -> Episode | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM episodes WHERE ticker = ? AND closed_at IS NULL", (ticker,)
            ).fetchone()
            return _episode_from_row(row) if row else None

    def episode_for_event(self, event_key: str) -> Episode | None:
        """Resolve one immutable source event to its board-owned episode."""
        if not isinstance(event_key, str) or not event_key:
            raise ValueError("event_key must be non-empty")
        prefix = f"event:{event_key}:"
        with self._connection() as connection:
            row = connection.execute(
                """SELECT e.* FROM episodes e
                LEFT JOIN source_events starter
                  ON starter.id = e.starter_source_event_id
                 AND starter.event_key = ?
                WHERE starter.id IS NOT NULL
                   OR EXISTS (
                       SELECT 1 FROM outbox o
                       WHERE o.episode_id = e.id
                         AND (o.dedupe_key = ? OR o.dedupe_key LIKE ?)
                   )
                ORDER BY e.id DESC LIMIT 1""",
                (event_key, prefix.rstrip(":"), f"{prefix}%"),
            ).fetchone()
            return _episode_from_row(row) if row else None

    def episodes(self) -> list[Episode]:
        """Return every board episode for an explicit presentation migration."""
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM episodes ORDER BY id").fetchall()
            return [_episode_from_row(row) for row in rows]

    def episode(self, episode_id: int) -> Episode:
        with self._connection() as connection:
            return self._episode(connection, episode_id)

    def active_plan(self, episode_id: int) -> SourceEvent | None:
        with self._connection() as connection:
            return BoardStoreTransaction(self, connection).active_plan(episode_id)

    def episode_sources(self, episode_id: int) -> set[str]:
        """Return source names attached to an episode's durable source replies."""
        with self._connection() as connection:
            return BoardStoreTransaction(self, connection).episode_sources(episode_id)

    def active_primary_plans(self) -> list[ActivePrimaryPlan]:
        """Enumerate only plans that a close phase may factually update."""
        with self._connection() as connection:
            return BoardStoreTransaction(self, connection).active_primary_plans()

    def latest_plan_cards(self) -> list[PlanCard]:
        with self._connection() as connection:
            return BoardStoreTransaction(self, connection).latest_plan_cards()

    def episode_source_events(self, episode_id: int) -> list[tuple[int, SourceEvent]]:
        with self._connection() as connection:
            return BoardStoreTransaction(self, connection).episode_source_events(episode_id)

    def starter_source_event(self, episode_id: int) -> SourceEvent | None:
        with self._connection() as connection:
            return BoardStoreTransaction(self, connection).starter_source_event(episode_id)

    def completed_source_replies(self) -> list[SourceReply]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT o.id AS outbox_id, o.payload_json, o.completion_json, o.dedupe_key, "
                "e.id AS episode_id, e.ticker, e.lifecycle, e.title, e.opened_at, "
                "e.latest_material_at, e.closed_at, e.thread_id, e.starter_message_id, "
                "e.starter_source_event_id, "
                "e.lifecycle_tag, e.market_tag FROM outbox o "
                "JOIN episodes e ON e.id = o.episode_id "
                "WHERE o.operation = 'post_source_reply' AND o.status = 'complete' "
                "AND o.completion_json IS NOT NULL AND e.thread_id IS NOT NULL "
                "ORDER BY o.id"
            ).fetchall()
            replies: list[SourceReply] = []
            for row in rows:
                payload = json.loads(row["payload_json"])
                completion = json.loads(row["completion_json"])
                message_id = completion.get("message_id")
                if not isinstance(message_id, str) or not message_id:
                    continue
                event_key, chunk_index = _source_event_key_from_dedupe(row["dedupe_key"])
                event_row = connection.execute(
                    "SELECT * FROM source_events WHERE event_key = ?", (event_key,)
                ).fetchone()
                if event_row is None:
                    continue
                replies.append(SourceReply(
                    outbox_id=int(row["outbox_id"]),
                    episode=Episode(
                        id=int(row["episode_id"]), ticker=row["ticker"],
                        lifecycle=row["lifecycle"], title=row["title"],
                        opened_at=_parse_timestamp(row["opened_at"]),
                        latest_material_at=_parse_timestamp(row["latest_material_at"]),
                        closed_at=_parse_timestamp(row["closed_at"]) if row["closed_at"] else None,
                        thread_id=row["thread_id"], starter_message_id=row["starter_message_id"],
                        starter_source_event_id=row["starter_source_event_id"],
                        lifecycle_tag=row["lifecycle_tag"], market_tag=row["market_tag"],
                    ),
                    event=_source_event_from_row(event_row),
                    message_id=message_id,
                    chunk_index=chunk_index,
                    current_content=str(payload.get("content") or ""),
                    has_media=bool(payload.get("media") or payload.get("media_url")),
                    is_history=":history:" in str(row["dedupe_key"]),
                ))
            return replies

    def pending_outbox_count(self) -> int:
        with self._connection() as connection:
            forum_pending = int(connection.execute(
                "SELECT COUNT(*) FROM outbox WHERE status != 'complete'"
            ).fetchone()[0])
            channel_pending = int(connection.execute(
                "SELECT COUNT(*) FROM channel_outbox WHERE status != 'complete'"
            ).fetchone()[0])
            return forum_pending + channel_pending

    def history_cleanup_count(self) -> int:
        with self._connection() as connection:
            return int(connection.execute(
                """SELECT COUNT(*) FROM history_events h
                JOIN episodes e ON e.id = h.episode_id
                WHERE h.discord_message_id IS NOT NULL
                  AND h.deleted_at IS NULL
                  AND e.thread_id IS NOT NULL"""
            ).fetchone()[0])

    def outbox_health(self) -> dict[str, int]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(last_error IS NOT NULL), 0) "
                "FROM outbox WHERE status != 'complete'"
            ).fetchone()
            channel = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(last_error IS NOT NULL), 0) "
                "FROM channel_outbox WHERE status != 'complete'"
            ).fetchone()
            return {"pending": int(row[0]) + int(channel[0]), "failed": int(row[1]) + int(channel[1])}

    def enqueue_heartbeat(
        self, channel_id: str, content: str, dedupe_key: str, now: datetime
    ) -> ChannelOutboxOperation:
        if not channel_id.strip() or not content.strip() or not dedupe_key.strip():
            raise ValueError("heartbeat channel, content, and identity must be non-empty")
        now = _aware(now, "now")
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO channel_outbox (
                    channel_id, content, dedupe_key, attempts, next_attempt_at,
                    status, created_at
                ) VALUES (?, ?, ?, 0, ?, 'pending', ?)
                ON CONFLICT(dedupe_key) DO NOTHING""",
                (channel_id, content, dedupe_key, _timestamp(now), _timestamp(now)),
            )
            row = connection.execute(
                "SELECT * FROM channel_outbox WHERE dedupe_key = ?", (dedupe_key,)
            ).fetchone()
            if row["channel_id"] != channel_id or row["content"] != content:
                raise StoreBlockedError("heartbeat identity conflicts with persisted intent")
            return _channel_outbox_from_row(row)

    def claim_due_heartbeat(self, now: datetime) -> ChannelOutboxOperation | None:
        now = _aware(now, "now")
        stale_before = now - _LEASE
        with self._transaction() as connection:
            row = connection.execute(
                """SELECT id FROM channel_outbox
                WHERE ((status = 'pending' AND julianday(next_attempt_at) <= julianday(?))
                   OR (status = 'claimed' AND julianday(claimed_at) <= julianday(?)))
                ORDER BY id LIMIT 1""",
                (_timestamp(now), _timestamp(stale_before)),
            ).fetchone()
            if row is None:
                return None
            claim_token = uuid4().hex
            connection.execute(
                "UPDATE channel_outbox SET status = 'claimed', claimed_at = ?, claim_token = ? WHERE id = ?",
                (_timestamp(now), claim_token, int(row[0])),
            )
            claimed = connection.execute(
                "SELECT * FROM channel_outbox WHERE id = ?", (int(row[0]),)
            ).fetchone()
            return _channel_outbox_from_row(claimed)

    def complete_heartbeat(
        self, operation_id: int, claim_token: str, receipt: Mapping[str, Any], completed_at: datetime
    ) -> None:
        completed_at = _aware(completed_at, "completed_at")
        receipt_json = json.dumps(dict(receipt), sort_keys=True, separators=(",", ":"))
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM channel_outbox WHERE id = ?", (operation_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown heartbeat operation: {operation_id}")
            if row["status"] == "complete":
                if row["completion_json"] != receipt_json:
                    raise StoreBlockedError("heartbeat receipt cannot be replaced")
                return
            if row["status"] != "claimed" or row["claim_token"] != claim_token:
                raise StoreBlockedError("heartbeat claim no longer owns operation")
            connection.execute(
                """UPDATE channel_outbox SET status = 'complete', completion_json = ?,
                    completed_at = ?, claimed_at = NULL, claim_token = NULL
                WHERE id = ?""",
                (receipt_json, _timestamp(completed_at), operation_id),
            )

    def fail_heartbeat(self, operation_id: int, claim_token: str, error: str, failed_at: datetime) -> None:
        if not error.strip():
            raise ValueError("heartbeat error must be non-empty")
        failed_at = _aware(failed_at, "failed_at")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM channel_outbox WHERE id = ?", (operation_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown heartbeat operation: {operation_id}")
            if row["status"] != "claimed" or row["claim_token"] != claim_token:
                raise StoreBlockedError("heartbeat claim no longer owns operation")
            attempts = int(row["attempts"]) + 1
            delay = _BACKOFF_MINUTES[min(attempts - 1, len(_BACKOFF_MINUTES) - 1)]
            connection.execute(
                """UPDATE channel_outbox SET attempts = ?, next_attempt_at = ?,
                    status = 'pending', claimed_at = NULL, claim_token = NULL, last_error = ?
                WHERE id = ?""",
                (attempts, _timestamp(failed_at + timedelta(minutes=delay)), error, operation_id),
            )

    def pending_heartbeat_count(self) -> int:
        with self._connection() as connection:
            return int(connection.execute(
                "SELECT COUNT(*) FROM channel_outbox WHERE status != 'complete'"
            ).fetchone()[0])

    def heartbeat_receipt(self, operation_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT completion_json FROM channel_outbox WHERE id = ?", (operation_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown heartbeat operation: {operation_id}")
            return json.loads(row[0]) if row[0] else None

    @contextmanager
    def delivery_lock(self) -> Iterator[bool]:
        """Fence live HTTP workers as well as durable claims, across processes."""
        with Path(f"{self.path}.delivery.lock").open("a+") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def set_create_snapshot(self, operation_id: int, claim_token: str, snapshot: dict | None) -> None:
        with self._transaction() as connection:
            row = self._require_claim(connection, operation_id, claim_token)
            payload = json.loads(row["payload_json"])
            if snapshot is None:
                payload.pop("create_snapshot", None)
            else:
                payload["create_snapshot"] = snapshot
            connection.execute("UPDATE outbox SET payload_json = ? WHERE id = ?",
                               (json.dumps(payload, sort_keys=True), operation_id))

    def persist_claimed_outbox_payload(
        self, operation_id: int, claim_token: str, payload: Mapping[str, Any]
    ) -> None:
        """Persist resolved transport inputs while retaining the claimed intent."""
        value = dict(payload)
        value.pop("_delivery_key", None)
        with self._transaction() as connection:
            self._require_claim(connection, operation_id, claim_token)
            connection.execute(
                "UPDATE outbox SET payload_json = ? WHERE id = ?",
                (json.dumps(value, sort_keys=True), operation_id),
            )

    def operations_for_ticker(self, ticker: str) -> list[OutboxOperation]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT o.* FROM outbox o JOIN episodes e ON e.id = o.episode_id "
                "WHERE e.ticker = ? ORDER BY o.id", (ticker,)
            ).fetchall()
            return [_outbox_from_row(row) for row in rows]

    def record_checkpoint(
        self,
        episode_id: int,
        checkpoint: Checkpoint,
        source_freshness: str | None = None,
    ) -> None:
        """Persist a factual or unavailable checkpoint, without Discord work."""
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT lifecycle, closed_at FROM episodes WHERE id = ?", (episode_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown episode: {episode_id}")
            if row["lifecycle"] != "primary" or row["closed_at"] is not None:
                raise StoreBlockedError(
                    "only active primary episodes may record checkpoints"
                )
            connection.execute(
                """
                INSERT INTO checkpoints (
                    episode_id, session_date, checked_at, source_freshness,
                    close_price, market_state, unavailable
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(episode_id, session_date, checked_at) DO NOTHING
                """,
                (
                    episode_id,
                    checkpoint.session_date,
                    checkpoint.checked_at,
                    source_freshness,
                    checkpoint.close_price,
                    checkpoint.state.value if checkpoint.state else None,
                    int(checkpoint.unavailable),
                ),
            )

    def enqueue_outbox(
        self,
        operation: str,
        episode_id: int,
        payload: Mapping[str, Any],
        dedupe_key: str,
        now: datetime,
    ) -> OutboxOperation:
        with self._transaction() as connection:
            return self._enqueue_outbox(
                connection, operation, episode_id, payload, dedupe_key, now
            )

    def _enqueue_outbox(
        self,
        connection: sqlite3.Connection,
        operation: str,
        episode_id: int,
        payload: Mapping[str, Any],
        dedupe_key: str,
        now: datetime,
    ) -> OutboxOperation:
        if operation not in _LEGAL_OPERATIONS:
            raise ValueError(f"unsupported outbox operation: {operation}")
        if not dedupe_key.strip():
            raise ValueError("dedupe_key must be non-empty")
        now = _aware(now, "now")
        payload_json = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))
        cursor = connection.execute(
            """
            INSERT INTO outbox (
                operation, episode_id, payload_json, dedupe_key, attempts,
                next_attempt_at, status
            ) VALUES (?, ?, ?, ?, 0, ?, 'pending')
            ON CONFLICT(dedupe_key) DO NOTHING
            """,
            (operation, episode_id, payload_json, dedupe_key, _timestamp(now)),
        )
        if cursor.rowcount:
            return self._outbox(connection, int(cursor.lastrowid))
        row = connection.execute(
            "SELECT id FROM outbox WHERE dedupe_key = ?", (dedupe_key,)
        ).fetchone()
        return self._outbox(connection, int(row[0]))

    @contextmanager
    def transaction(self) -> Iterator[BoardStoreTransaction]:
        """Coordinate an engine transition and all of its outbox intents atomically."""
        with self._transaction() as connection:
            yield BoardStoreTransaction(self, connection)

    def enqueue_test_operation(
        self, operation: str, episode_id: int, now: datetime
    ) -> OutboxOperation:
        """Test-only convenience that still uses the production outbox constraints."""
        return self.enqueue_outbox(
            operation,
            episode_id,
            {"test": True},
            f"test:{operation}:{episode_id}",
            now,
        )

    def claim_due_outbox(self, now: datetime) -> OutboxOperation | None:
        now = _aware(now, "now")
        stale_before = now - _LEASE
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT o.id FROM outbox o
                WHERE ((o.status = 'pending' AND julianday(o.next_attempt_at) <= julianday(?))
                   OR (o.status = 'claimed' AND julianday(o.claimed_at) <= julianday(?)))
                  AND NOT EXISTS (
                    SELECT 1 FROM outbox prior
                    WHERE prior.episode_id = o.episode_id AND prior.id < o.id
                      AND prior.status != 'complete'
                  )
                ORDER BY o.id
                LIMIT 1
                """,
                (_timestamp(now), _timestamp(stale_before)),
            ).fetchone()
            if row is None:
                return None
            claim_token = uuid4().hex
            connection.execute(
                """
                UPDATE outbox
                SET status = 'claimed', claimed_at = ?, claim_token = ?
                WHERE id = ?
                """,
                (_timestamp(now), claim_token, int(row[0])),
            )
            return self._outbox(connection, int(row[0]))

    def complete_outbox(
        self,
        operation_id: int,
        claim_token: str,
        completion: Mapping[str, Any],
        completed_at: datetime,
    ) -> None:
        completed_at = _aware(completed_at, "completed_at")
        with self._transaction() as connection:
            operation = self._require_claim(connection, operation_id, claim_token)
            if operation["operation"] == "create_thread":
                # Minimal store-only callers may record partial completions; the
                # engine validates both identifiers before completing creates.
                connection.execute(
                    "UPDATE episodes SET thread_id = COALESCE(?, thread_id), "
                    "starter_message_id = COALESCE(?, starter_message_id) WHERE id = ?",
                    (completion.get("thread_id"), completion.get("starter_message_id"), operation["episode_id"]),
                )
            elif operation["operation"] == "post_history_reply":
                payload = json.loads(operation["payload_json"])
                connection.execute(
                    "UPDATE history_events SET discord_message_id = ? WHERE id = ?",
                    (completion.get("message_id"), payload.get("history_id")),
                )
            elif operation["operation"] == "delete_message":
                payload = json.loads(operation["payload_json"])
                connection.execute(
                    "UPDATE history_events SET deleted_at = ? WHERE id = ?",
                    (_timestamp(completed_at), payload.get("history_id")),
                )
            elif operation["operation"] == "patch_thread":
                payload = json.loads(operation["payload_json"])
                if payload.get("archived") is True and "cancelled" not in completion:
                    connection.execute(
                        "UPDATE episodes SET archived_at = COALESCE(archived_at, ?) WHERE id = ?",
                        (_timestamp(completed_at), operation["episode_id"]),
                    )
            connection.execute(
                """
                UPDATE outbox
                SET status = 'complete', completion_json = ?, completed_at = ?,
                    claimed_at = NULL, claim_token = NULL
                WHERE id = ?
                """,
                (json.dumps(dict(completion), sort_keys=True), _timestamp(completed_at), operation_id),
            )
            connection.execute(
                """UPDATE episodes SET quiet_started_at = ?
                WHERE id = ? AND lifecycle = 'resolved' AND archived_at IS NULL
                  AND quiet_started_at IS NULL
                  AND NOT EXISTS (SELECT 1 FROM outbox WHERE episode_id = ? AND status != 'complete')""",
                (_timestamp(completed_at), operation["episode_id"], operation["episode_id"]),
            )

    def fail_outbox(
        self, operation_id: int, claim_token: str, error: str, failed_at: datetime,
        *, minimum_delay_seconds: float = 0,
    ) -> None:
        if not error.strip():
            raise ValueError("outbox error must be non-empty")
        failed_at = _aware(failed_at, "failed_at")
        with self._transaction() as connection:
            row = self._require_claim(connection, operation_id, claim_token)
            attempts = int(row["attempts"]) + 1
            delay = _BACKOFF_MINUTES[min(attempts - 1, len(_BACKOFF_MINUTES) - 1)]
            delay_seconds = max(delay * 60, minimum_delay_seconds)
            connection.execute(
                """
                UPDATE outbox
                SET attempts = ?, next_attempt_at = ?, status = 'pending',
                    claimed_at = NULL, claim_token = NULL, last_error = ?
                WHERE id = ?
                """,
                (attempts, _timestamp(failed_at + timedelta(seconds=delay_seconds)), error, operation_id),
            )

    def due_at(self, operation_id: int) -> datetime:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT next_attempt_at FROM outbox WHERE id = ?", (operation_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown outbox operation: {operation_id}")
            return _parse_timestamp(row[0])

    def count_rows(self, table: str) -> int:
        if table not in _TABLES:
            raise ValueError(f"unknown board table: {table}")
        with self._connection() as connection:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def _initialize(self) -> None:
        with self._locked():
            connection = sqlite3.connect(self.path, isolation_level=None)
            try:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if version > SCHEMA_VERSION:
                    raise StoreBlockedError(f"unknown schema version: {version}")
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("BEGIN IMMEDIATE")
                try:
                    if version == 0:
                        _create_schema(connection)
                    elif version == 1:
                        _migrate_v1_to_v2(connection)
                        _migrate_v2_to_v3(connection)
                    elif version == 2:
                        _migrate_v2_to_v3(connection)
                    if version in {1, 2, 3}:
                        _migrate_v3_to_v4(connection)
                    if version in {1, 2, 3, 4}:
                        _migrate_v4_to_v5(connection)
                    if version in {1, 2, 3, 4, 5}:
                        _migrate_v5_to_v6(connection)
                    if version in {1, 2, 3, 4, 5, 6}:
                        _migrate_v6_to_v7(connection)
                    if version in {1, 2, 3, 4, 5, 6, 7}:
                        _migrate_v7_to_v8(connection)
                    if version in {1, 2, 3, 4, 5, 6, 7, 8}:
                        _migrate_v8_to_v9(connection)
                    if version in {1, 2, 3, 4, 5, 6, 7, 8, 9}:
                        _migrate_v9_to_v10(connection)
                    if version in {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}:
                        _migrate_v10_to_v11(connection)
                    if version in {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11}:
                        _migrate_v11_to_v12(connection)
                    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                    connection.execute("COMMIT")
                except BaseException:
                    connection.execute("ROLLBACK")
                    raise
            finally:
                connection.close()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with self._locked():
            connection = sqlite3.connect(self.path, isolation_level=None)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA foreign_keys=ON")
                yield connection
            finally:
                connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._locked():
            connection = sqlite3.connect(self.path, isolation_level=None)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("BEGIN IMMEDIATE")
                try:
                    yield connection
                    connection.execute("COMMIT")
                except BaseException:
                    connection.execute("ROLLBACK")
                    raise
            finally:
                connection.close()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.lock_path.touch(exist_ok=True)
        with self.lock_path.open("r+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _episode(connection: sqlite3.Connection, episode_id: int) -> Episode:
        row = connection.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown episode: {episode_id}")
        return _episode_from_row(row)

    @staticmethod
    def _outbox(connection: sqlite3.Connection, operation_id: int) -> OutboxOperation:
        row = connection.execute("SELECT * FROM outbox WHERE id = ?", (operation_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown outbox operation: {operation_id}")
        return _outbox_from_row(row)

    @staticmethod
    def _require_claim(
        connection: sqlite3.Connection, operation_id: int, claim_token: str
    ) -> sqlite3.Row:
        if not claim_token:
            raise StoreBlockedError("outbox claim token is required")
        row = connection.execute(
            "SELECT * FROM outbox WHERE id = ?", (operation_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown outbox operation: {operation_id}")
        if row["status"] != "claimed" or row["claim_token"] != claim_token:
            raise StoreBlockedError("outbox claim token no longer owns operation")
        return row


class BoardStoreTransaction:
    """The engine-facing write surface for one all-or-nothing board transition."""

    def __init__(self, store: BoardStore, connection: sqlite3.Connection) -> None:
        self._store = store
        self._connection = connection

    def create_episode(
        self, ticker: str, lifecycle: str, title: str, opened_at: datetime
    ) -> Episode:
        return self._store._create_episode(
            self._connection, ticker, lifecycle, title, opened_at
        )

    def episode(self, episode_id: int) -> Episode:
        return self._store._episode(self._connection, episode_id)

    def submit_event(self, event: SourceEvent, received_at: datetime) -> SubmittedEvent:
        return self._store._submit_event(self._connection, event, _aware(received_at, "received_at"))

    def event_processed(self, event_id: int) -> bool:
        row = self._connection.execute(
            "SELECT board_processed_at FROM source_events WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown source event: {event_id}")
        return row[0] is not None

    def source_event(self, event_id: int) -> SourceEvent:
        row = self._connection.execute(
            "SELECT * FROM source_events WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown source event: {event_id}")
        return _source_event_from_row(row)

    def latest_source_event(self, episode_id: int, source: str) -> SourceEvent | None:
        """Return the newest source reply event attached to one episode.

        Source events intentionally remain immutable and are not linked to an
        episode by a watcher-owned foreign key.  The board's durable source
        reply intents carry that relationship, so inspect those intents and
        resolve their event keys back to the immutable source rows.  This also
        keeps promotion retries independent from watcher state.
        """
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source must be non-empty")
        rows = self._connection.execute(
            """SELECT id, dedupe_key FROM outbox
            WHERE episode_id = ? AND operation = 'post_source_reply'
            ORDER BY id DESC""",
            (episode_id,),
        ).fetchall()
        seen: set[str] = set()
        candidates: list[tuple[datetime, int, SourceEvent]] = []
        for row in rows:
            try:
                event_key, _ = _source_event_key_from_dedupe(row["dedupe_key"])
            except StoreBlockedError:
                continue
            if event_key in seen:
                continue
            seen.add(event_key)
            event_row = self._connection.execute(
                "SELECT * FROM source_events WHERE event_key = ?", (event_key,)
            ).fetchone()
            if event_row is None or event_row["source"].casefold() != source.casefold():
                continue
            event = _source_event_from_row(event_row)
            candidates.append((event.published_at, int(event_row["id"]), event))
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item[0], item[1]))[2]

    def episode_source_events(self, episode_id: int) -> list[tuple[int, SourceEvent]]:
        """Return unique immutable source events represented by an episode."""
        rows = self._connection.execute(
            "SELECT dedupe_key FROM outbox "
            "WHERE episode_id = ? AND operation = 'post_source_reply' ORDER BY id",
            (episode_id,),
        ).fetchall()
        seen: set[str] = set()
        events: list[tuple[int, SourceEvent]] = []
        for row in rows:
            try:
                event_key, _ = _source_event_key_from_dedupe(row["dedupe_key"])
            except StoreBlockedError:
                continue
            if event_key in seen:
                continue
            seen.add(event_key)
            event_row = self._connection.execute(
                "SELECT * FROM source_events WHERE event_key = ?", (event_key,)
            ).fetchone()
            if event_row is not None:
                events.append((int(event_row["id"]), _source_event_from_row(event_row)))
        return events

    def mark_event_processed(self, event_id: int, now: datetime) -> None:
        self._connection.execute(
            "UPDATE source_events SET board_processed_at = ? WHERE id = ?",
            (_timestamp(now), event_id),
        )

    def active_episode(self, ticker: str) -> Episode | None:
        row = self._connection.execute(
            "SELECT * FROM episodes WHERE ticker = ? AND closed_at IS NULL", (ticker,)
        ).fetchone()
        return _episode_from_row(row) if row else None

    def historical_episode(self, ticker: str, published_at: datetime) -> Episode | None:
        """Find the newest resolution covering a late source event."""
        row = self._connection.execute(
            """SELECT * FROM episodes WHERE ticker = ? AND lifecycle = 'resolved'
            AND julianday(opened_at) <= julianday(?)
            AND julianday(closed_at) >= julianday(?)
            ORDER BY julianday(closed_at) DESC, id DESC LIMIT 1""",
            (ticker, _timestamp(published_at), _timestamp(published_at)),
        ).fetchone()
        return _episode_from_row(row) if row else None

    def active_episodes(self) -> list[Episode]:
        rows = self._connection.execute(
            "SELECT * FROM episodes WHERE closed_at IS NULL ORDER BY id"
        ).fetchall()
        return [_episode_from_row(row) for row in rows]

    def resolved_episodes(self) -> list[Episode]:
        rows = self._connection.execute(
            "SELECT * FROM episodes WHERE lifecycle = 'resolved' AND archived_at IS NULL ORDER BY id"
        ).fetchall()
        return [_episode_from_row(row) for row in rows]

    def latest_plan_card(self, episode_id: int) -> PlanCard | None:
        return next((card for card in self.latest_plan_cards() if card.episode.id == episode_id), None)

    def has_pending_outbox(self, episode_id: int) -> bool:
        return bool(self._connection.execute(
            "SELECT 1 FROM outbox WHERE episode_id = ? AND status != 'complete' LIMIT 1",
            (episode_id,),
        ).fetchone())

    def episode_sources(self, episode_id: int) -> set[str]:
        """Resolve immutable source names through the board-owned reply intents."""
        return episode_sources_from_connection(self._connection, episode_id)

    def update_episode(self, episode: Episode) -> None:
        self._connection.execute(
            """UPDATE episodes SET lifecycle = ?, title = ?, latest_material_at = ?,
            closed_at = ?, starter_source_event_id = ?, lifecycle_tag = ?, market_tag = ?,
            resolution_reason = ?, quiet_started_at = ?, archived_at = ?
            WHERE id = ?""",
            (episode.lifecycle, episode.title, _timestamp(episode.latest_material_at),
             _timestamp(episode.closed_at) if episode.closed_at else None,
             episode.starter_source_event_id, episode.lifecycle_tag, episode.market_tag,
             episode.resolution_reason,
             _timestamp(episode.quiet_started_at) if episode.quiet_started_at else None,
             _timestamp(episode.archived_at) if episode.archived_at else None,
             episode.id),
        )

    def starter_source_event(self, episode_id: int) -> SourceEvent | None:
        """Return the immutable source event currently projected by the starter."""
        row = self._connection.execute(
            """SELECT s.* FROM episodes e JOIN source_events s
            ON s.id = e.starter_source_event_id WHERE e.id = ?""",
            (episode_id,),
        ).fetchone()
        return _source_event_from_row(row) if row else None

    def source_starter_content(self, episode_id: int) -> str | None:
        """Recover managed source card text from pre-starter-link episodes."""
        rows = self._connection.execute(
            """SELECT payload_json FROM outbox WHERE episode_id = ?
            AND operation IN ('create_thread', 'edit_starter') ORDER BY id DESC""",
            (episode_id,),
        ).fetchall()
        for row in rows:
            content = json.loads(row["payload_json"]).get("content")
            if isinstance(content, str) and content:
                return content
        return None

    def active_plan(self, episode_id: int) -> SourceEvent | None:
        row = self._connection.execute(
            """SELECT s.*, p.source_status AS current_status,
            p.entry AS active_plan_entry, p.stop_loss AS active_plan_stop_loss,
            p.targets_json AS active_plan_targets_json FROM plans p
            JOIN source_events s ON s.id = p.source_event_id
            WHERE p.episode_id = ? AND p.terminal_at IS NULL ORDER BY p.id DESC LIMIT 1""",
            (episode_id,),
        ).fetchone()
        return _projected_plan_from_row(row) if row else None

    def active_primary_plans(self) -> list[ActivePrimaryPlan]:
        rows = self._connection.execute(
            """SELECT e.*, p.id AS plan_id, s.*, p.source_status AS current_status,
            p.source_status_at, p.entry AS active_plan_entry,
            p.stop_loss AS active_plan_stop_loss, p.targets_json AS active_plan_targets_json
            FROM episodes e JOIN plans p ON p.episode_id = e.id
            JOIN source_events s ON s.id = p.source_event_id
            WHERE e.lifecycle = 'primary' AND e.closed_at IS NULL AND p.terminal_at IS NULL
            ORDER BY e.id"""
        ).fetchall()
        return [
            ActivePrimaryPlan(
                episode=_episode_from_row(row),
                plan_id=int(row["plan_id"]),
                event=_projected_plan_from_row(row),
                source_updated_at=_parse_timestamp(row["source_status_at"]),
            )
            for row in rows
        ]

    def latest_plan_cards(self) -> list[PlanCard]:
        rows = self._connection.execute(
            """SELECT e.*, p.id AS plan_id, s.id AS source_event_id, s.*, p.source_status AS current_status,
            p.source_status_at, p.entry AS active_plan_entry,
            p.stop_loss AS active_plan_stop_loss, p.targets_json AS active_plan_targets_json
            FROM episodes e JOIN plans p ON p.episode_id = e.id
            JOIN source_events s ON s.id = p.source_event_id
            WHERE p.id = (SELECT MAX(latest.id) FROM plans latest WHERE latest.episode_id = e.id)
            ORDER BY e.id"""
        ).fetchall()
        return [
            PlanCard(
                episode=_episode_from_row(row),
                plan_id=int(row["plan_id"]),
                event_id=int(row["source_event_id"]),
                event=_projected_plan_from_row(row),
                source_updated_at=_parse_timestamp(row["source_status_at"]),
            )
            for row in rows
        ]

    def close_attempted(self, plan_id: int, session_date: str, phase: str) -> bool:
        _close_phase(phase)
        row = self._connection.execute(
            "SELECT 1 FROM close_attempts WHERE plan_id = ? AND session_date = ? AND phase = ?",
            (plan_id, session_date, phase),
        ).fetchone()
        return row is not None

    def initial_close_unavailable(self, plan_id: int, session_date: str) -> bool:
        row = self._connection.execute(
            """SELECT available FROM close_attempts
            WHERE plan_id = ? AND session_date = ? AND phase = 'initial'""",
            (plan_id, session_date),
        ).fetchone()
        return row is not None and not bool(row[0])

    def record_close_attempt(
        self, plan_id: int, session_date: str, phase: str, attempted_at: datetime, available: bool
    ) -> bool:
        _close_phase(phase)
        if not isinstance(available, bool):
            raise ValueError("available must be a boolean")
        cursor = self._connection.execute(
            """INSERT INTO close_attempts (plan_id, session_date, phase, attempted_at, available)
            VALUES (?, ?, ?, ?, ?) ON CONFLICT(plan_id, session_date, phase) DO NOTHING""",
            (plan_id, session_date, phase, _timestamp(attempted_at), int(available)),
        )
        return bool(cursor.rowcount)

    def record_checkpoint(
        self, episode_id: int, checkpoint: Checkpoint, source_freshness: str | None = None
    ) -> None:
        row = self._connection.execute(
            "SELECT lifecycle, closed_at FROM episodes WHERE id = ?", (episode_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown episode: {episode_id}")
        if row["lifecycle"] != "primary" or row["closed_at"] is not None:
            raise StoreBlockedError("only active primary episodes may record checkpoints")
        self._connection.execute(
            """INSERT INTO checkpoints (
                episode_id, session_date, checked_at, source_freshness,
                close_price, market_state, unavailable
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(episode_id, session_date, checked_at) DO NOTHING""",
            (episode_id, checkpoint.session_date, checkpoint.checked_at, source_freshness,
             checkpoint.close_price, checkpoint.state.value if checkpoint.state else None,
             int(checkpoint.unavailable)),
        )

    def replace_plan(self, episode_id: int, event_id: int, event: SourceEvent, now: datetime) -> None:
        if event.plan is None:
            raise ValueError("replacement requires plan levels")
        self.finish_plan(episode_id, now)
        self._connection.execute(
            """INSERT INTO plans (episode_id, source_event_id, entry, stop_loss,
            targets_json, source_status, source_status_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (episode_id, event_id, event.plan.entry, event.plan.stop_loss,
             json.dumps(event.plan.targets), event.source_status or "New setup",
             _timestamp(event.published_at)),
        )

    def update_plan_targets(self, episode_id: int, targets: tuple[str, ...]) -> None:
        """Update the current mutable target ladder without rewriting source facts."""
        if type(targets) is not tuple:
            raise ValueError("plan targets must be a tuple")
        row = self._connection.execute(
            """SELECT p.entry, p.stop_loss FROM plans p
            JOIN episodes e ON e.id = p.episode_id
            WHERE p.episode_id = ? AND p.terminal_at IS NULL
            AND e.lifecycle = 'primary' AND e.closed_at IS NULL
            ORDER BY p.id DESC LIMIT 1""",
            (episode_id,),
        ).fetchone()
        if row is None:
            raise StoreBlockedError("only an active primary plan may update targets")
        PlanLevels(row["entry"], row["stop_loss"], targets)
        self._connection.execute(
            "UPDATE plans SET targets_json = ? WHERE episode_id = ? AND terminal_at IS NULL",
            (json.dumps(targets), episode_id),
        )

    def finish_plan(self, episode_id: int, now: datetime) -> None:
        self._connection.execute(
            "UPDATE plans SET terminal_at = ? WHERE episode_id = ? AND terminal_at IS NULL",
            (_timestamp(now), episode_id),
        )

    def set_source_status(self, episode_id: int, source_status: str, updated_at: datetime) -> None:
        self._connection.execute(
            "UPDATE plans SET source_status = ?, source_status_at = ? "
            "WHERE episode_id = ? AND terminal_at IS NULL",
            (source_status, _timestamp(updated_at), episode_id),
        )

    def latest_checkpoints(self, episode_id: int) -> tuple[Checkpoint | None, Checkpoint | None]:
        rows = self._connection.execute(
            """SELECT c.* FROM checkpoints c WHERE c.episode_id = ?
            AND julianday(c.checked_at) >= (
                SELECT julianday(s.received_at) FROM plans p
                JOIN source_events s ON s.id = p.source_event_id
                WHERE p.episode_id = ? AND p.id = (
                    SELECT MAX(latest.id) FROM plans latest WHERE latest.episode_id = p.episode_id
                )
            ) ORDER BY julianday(c.checked_at) DESC, c.id DESC""",
            (episode_id, episode_id),
        ).fetchall()
        def checkpoint(row):
            return Checkpoint(row["session_date"], row["checked_at"], row["close_price"],
                              MarketState(row["market_state"]) if row["market_state"] else None,
                              bool(row["unavailable"]))
        latest = checkpoint(rows[0]) if rows else None
        valid = next((checkpoint(row) for row in rows if not row["unavailable"]), None)
        return latest, valid

    def add_history(
        self,
        episode_id: int,
        event_id: int | None,
        content: str,
        now: datetime,
        history_key: str | None = None,
    ) -> int:
        history_key = history_key or f"content:{content}"
        self._connection.execute(
            """INSERT INTO history_events (
                episode_id, source_event_id, material_payload, created_at, history_key
            )
            VALUES (?, ?, ?, ?, ?) ON CONFLICT(episode_id, history_key) DO NOTHING""",
            (episode_id, event_id, content, _timestamp(now), history_key),
        )
        return int(self._connection.execute(
            "SELECT id FROM history_events WHERE episode_id = ? AND history_key = ?",
            (episode_id, history_key),
        ).fetchone()[0])

    def schedule_history_deletes(self, now: datetime) -> int:
        """Queue every still-visible quoted history reply for deletion."""
        rows = self._connection.execute(
            """SELECT h.id AS history_id, h.episode_id, h.discord_message_id, e.thread_id
            FROM history_events h JOIN episodes e ON e.id = h.episode_id
            WHERE h.discord_message_id IS NOT NULL AND h.deleted_at IS NULL
            ORDER BY h.id"""
        ).fetchall()
        scheduled = 0
        for row in rows:
            if not row["thread_id"]:
                continue
            history_id = int(row["history_id"])
            self.enqueue_outbox(
                "delete_message",
                int(row["episode_id"]),
                {
                    "thread_id": str(row["thread_id"]),
                    "message_id": str(row["discord_message_id"]),
                    "history_id": history_id,
                    "nonce_value": f"cleanup-history:{history_id}",
                },
                f"cleanup-history:{history_id}",
                now,
            )
            scheduled += 1
        return scheduled

    def enqueue_outbox(
        self,
        operation: str,
        episode_id: int,
        payload: Mapping[str, Any],
        dedupe_key: str,
        now: datetime,
    ) -> OutboxOperation:
        return self._store._enqueue_outbox(
            self._connection, operation, episode_id, payload, dedupe_key, now
        )


def _create_schema(connection: sqlite3.Connection) -> None:
    _execute_statements(
        connection,
        """
        CREATE TABLE source_events (
            id INTEGER PRIMARY KEY,
            event_key TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL,
            kind TEXT NOT NULL,
            ticker TEXT NOT NULL,
            published_at TEXT NOT NULL,
            source_url TEXT NOT NULL,
            all_content TEXT NOT NULL,
            source_title TEXT NOT NULL,
            source_status TEXT,
            plan_entry TEXT,
            plan_stop_loss TEXT,
            plan_targets_json TEXT,
            media_path TEXT,
            media_urls_json TEXT NOT NULL,
            matched_setup_event_key TEXT,
            media_paths_json TEXT NOT NULL DEFAULT '[]',
            received_at TEXT NOT NULL,
            board_processed_at TEXT
        );
        """
    )
    _create_non_event_tables(connection)


def _create_non_event_tables(connection: sqlite3.Connection) -> None:
    _execute_statements(
        connection,
        """
        CREATE TABLE episodes (
            id INTEGER PRIMARY KEY,
            ticker TEXT NOT NULL,
            lifecycle TEXT NOT NULL CHECK (lifecycle IN ('source', 'primary', 'resolved')),
            title TEXT NOT NULL,
            opened_at TEXT NOT NULL,
            latest_material_at TEXT NOT NULL,
            closed_at TEXT,
            thread_id TEXT,
            starter_message_id TEXT,
            starter_source_event_id INTEGER REFERENCES source_events(id),
            lifecycle_tag TEXT,
            market_tag TEXT,
            resolution_reason TEXT,
            quiet_started_at TEXT,
            archived_at TEXT
        );
        CREATE UNIQUE INDEX one_open_episode_per_ticker
            ON episodes(ticker) WHERE closed_at IS NULL;
        CREATE TABLE plans (
            id INTEGER PRIMARY KEY,
            episode_id INTEGER NOT NULL REFERENCES episodes(id),
            source_event_id INTEGER NOT NULL UNIQUE REFERENCES source_events(id),
            entry TEXT NOT NULL,
            stop_loss TEXT NOT NULL,
            targets_json TEXT NOT NULL,
            source_status TEXT NOT NULL,
            source_status_at TEXT NOT NULL,
            terminal_at TEXT
        );
        CREATE TABLE checkpoints (
            id INTEGER PRIMARY KEY,
            episode_id INTEGER NOT NULL REFERENCES episodes(id),
            session_date TEXT NOT NULL,
            checked_at TEXT NOT NULL,
            source_freshness TEXT,
            close_price TEXT,
            market_state TEXT,
            unavailable INTEGER NOT NULL CHECK (unavailable IN (0, 1)),
            UNIQUE(episode_id, session_date, checked_at)
        );
        CREATE TABLE history_events (
            id INTEGER PRIMARY KEY,
            episode_id INTEGER NOT NULL REFERENCES episodes(id),
            source_event_id INTEGER REFERENCES source_events(id),
            material_payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            discord_message_id TEXT,
            deleted_at TEXT,
            history_key TEXT NOT NULL,
            UNIQUE(episode_id, history_key)
        );
        CREATE TABLE outbox (
            id INTEGER PRIMARY KEY,
            operation TEXT NOT NULL CHECK (operation IN (
                'create_thread', 'edit_starter', 'post_source_reply',
                'post_history_reply', 'delete_message', 'patch_thread'
            )),
            episode_id INTEGER NOT NULL REFERENCES episodes(id),
            payload_json TEXT NOT NULL,
            dedupe_key TEXT NOT NULL UNIQUE,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending', 'claimed', 'complete')),
            claimed_at TEXT,
            claim_token TEXT,
            last_error TEXT,
            completion_json TEXT,
            completed_at TEXT
        );
        CREATE TABLE close_attempts (
            id INTEGER PRIMARY KEY,
            plan_id INTEGER NOT NULL REFERENCES plans(id),
            session_date TEXT NOT NULL,
            phase TEXT NOT NULL CHECK (phase IN ('initial', 'retry')),
            attempted_at TEXT NOT NULL,
            available INTEGER NOT NULL CHECK (available IN (0, 1)),
            UNIQUE(plan_id, session_date, phase)
        );
        CREATE TABLE channel_outbox (
            id INTEGER PRIMARY KEY,
            channel_id TEXT NOT NULL,
            content TEXT NOT NULL,
            dedupe_key TEXT NOT NULL UNIQUE,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending', 'claimed', 'complete')),
            claimed_at TEXT,
            claim_token TEXT,
            last_error TEXT,
            completion_json TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL
        );
        """
    )


def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
    """Upgrade the initial event-only schema additively, retaining every row."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(source_events)")}
    additions = {
        "source": "TEXT NOT NULL DEFAULT ''",
        "kind": "TEXT NOT NULL DEFAULT ''",
        "published_at": "TEXT NOT NULL DEFAULT ''",
        "source_url": "TEXT NOT NULL DEFAULT ''",
        "all_content": "TEXT NOT NULL DEFAULT ''",
        "source_title": "TEXT NOT NULL DEFAULT ''",
        "source_status": "TEXT",
        "plan_entry": "TEXT",
        "plan_stop_loss": "TEXT",
        "plan_targets_json": "TEXT",
        "media_path": "TEXT",
        "media_urls_json": "TEXT NOT NULL DEFAULT '[]'",
        "received_at": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE source_events ADD COLUMN {name} {definition}")
    _create_missing_tables(connection)


def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(outbox)")}
    if "claim_token" not in columns:
        connection.execute("ALTER TABLE outbox ADD COLUMN claim_token TEXT")


def _migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(source_events)")}
    # The v2 outbox-only compatibility fixture has no source table to migrate.
    if columns and "board_processed_at" not in columns:
        connection.execute("ALTER TABLE source_events ADD COLUMN board_processed_at TEXT")


def _migrate_v4_to_v5(connection: sqlite3.Connection) -> None:
    """Retain every prior fact while adding idempotent per-plan close attempts."""
    connection.execute(
        """CREATE TABLE IF NOT EXISTS close_attempts (
            id INTEGER PRIMARY KEY,
            plan_id INTEGER NOT NULL REFERENCES plans(id),
            session_date TEXT NOT NULL,
            phase TEXT NOT NULL CHECK (phase IN ('initial', 'retry')),
            attempted_at TEXT NOT NULL,
            available INTEGER NOT NULL CHECK (available IN (0, 1)),
            UNIQUE(plan_id, session_date, phase)
        )"""
    )


def _migrate_v5_to_v6(connection: sqlite3.Connection) -> None:
    """Allow repeated quoted chunks to retain distinct Discord message IDs."""
    existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "history_events" not in existing:
        return
    connection.execute(
        """CREATE TABLE history_events_v6 (
            id INTEGER PRIMARY KEY,
            episode_id INTEGER NOT NULL REFERENCES episodes(id),
            source_event_id INTEGER REFERENCES source_events(id),
            material_payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            discord_message_id TEXT,
            history_key TEXT NOT NULL,
            UNIQUE(episode_id, history_key)
        )"""
    )
    connection.execute(
        """INSERT INTO history_events_v6 (
            id, episode_id, source_event_id, material_payload, created_at,
            discord_message_id, history_key
        )
        SELECT id, episode_id, source_event_id, material_payload, created_at,
               discord_message_id, 'legacy:' || id
        FROM history_events"""
    )
    connection.execute("DROP TABLE history_events")
    connection.execute("ALTER TABLE history_events_v6 RENAME TO history_events")


def _migrate_v6_to_v7(connection: sqlite3.Connection) -> None:
    """Add source-status timestamps and durable history-message deletion."""
    existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    plan_columns = {row[1] for row in connection.execute("PRAGMA table_info(plans)")} if "plans" in existing else set()
    if "plans" in existing and "source_status_at" not in plan_columns:
        connection.execute("ALTER TABLE plans ADD COLUMN source_status_at TEXT")
        connection.execute(
            """UPDATE plans SET source_status_at = COALESCE(
                (
                    SELECT MAX(status_event.published_at)
                    FROM source_events status_event
                    JOIN episodes status_episode ON status_episode.id = plans.episode_id
                    JOIN source_events opened_event ON opened_event.id = plans.source_event_id
                    WHERE status_event.ticker = status_episode.ticker
                      AND status_event.source_status IS NOT NULL
                      AND julianday(status_event.published_at) >= julianday(opened_event.published_at)
                      AND (
                          status_episode.closed_at IS NULL
                          OR julianday(status_event.published_at) <= julianday(status_episode.closed_at)
                      )
                ),
                (SELECT published_at FROM source_events WHERE source_events.id = plans.source_event_id),
                terminal_at,
                ''
            )
            WHERE source_status_at IS NULL"""
        )

    history_columns = {row[1] for row in connection.execute("PRAGMA table_info(history_events)")} if "history_events" in existing else set()
    if "history_events" in existing and "deleted_at" not in history_columns:
        connection.execute("ALTER TABLE history_events ADD COLUMN deleted_at TEXT")

    # SQLite CHECK constraints are part of the table definition, so recreate
    # the outbox table once to admit the approved cleanup operation while
    # retaining every pending and completed intent.
    outbox_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'outbox'"
    ).fetchone()
    if outbox_sql and "'delete_message'" not in str(outbox_sql[0]) and "episodes" in existing:
        connection.execute(
            """CREATE TABLE outbox_v7 (
                id INTEGER PRIMARY KEY,
                operation TEXT NOT NULL CHECK (operation IN (
                    'create_thread', 'edit_starter', 'post_source_reply',
                    'post_history_reply', 'delete_message', 'patch_thread'
                )),
                episode_id INTEGER NOT NULL REFERENCES episodes(id),
                payload_json TEXT NOT NULL,
                dedupe_key TEXT NOT NULL UNIQUE,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('pending', 'claimed', 'complete')),
                claimed_at TEXT,
                claim_token TEXT,
                last_error TEXT,
                completion_json TEXT,
                completed_at TEXT
            )"""
        )
        connection.execute(
            """INSERT INTO outbox_v7 (
                id, operation, episode_id, payload_json, dedupe_key, attempts,
                next_attempt_at, status, claimed_at, claim_token, last_error,
                completion_json, completed_at
            ) SELECT id, operation, episode_id, payload_json, dedupe_key, attempts,
                next_attempt_at, status, claimed_at, claim_token, last_error,
                completion_json, completed_at FROM outbox"""
        )
        connection.execute("DROP TABLE outbox")
        connection.execute("ALTER TABLE outbox_v7 RENAME TO outbox")
    if "outbox" in existing or outbox_sql:
        connection.execute(
            """UPDATE outbox SET status = 'complete', completion_json = ?,
            completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
            claimed_at = NULL, claim_token = NULL
            WHERE operation = 'post_history_reply' AND status != 'complete'""",
            (json.dumps({"cancelled": "quoted history retired"}, sort_keys=True),),
        )


def _migrate_v7_to_v8(connection: sqlite3.Connection) -> None:
    """Track the immutable source event currently rendered by each starter."""
    existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "episodes" not in existing:
        return
    columns = {row[1] for row in connection.execute("PRAGMA table_info(episodes)")}
    if "starter_source_event_id" not in columns:
        connection.execute(
            "ALTER TABLE episodes ADD COLUMN starter_source_event_id INTEGER REFERENCES source_events(id)"
        )


def _migrate_v8_to_v9(connection: sqlite3.Connection) -> None:
    """Add a durable channel outbox for scheduled heartbeat operations."""
    connection.execute(
        """CREATE TABLE IF NOT EXISTS channel_outbox (
            id INTEGER PRIMARY KEY,
            channel_id TEXT NOT NULL,
            content TEXT NOT NULL,
            dedupe_key TEXT NOT NULL UNIQUE,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending', 'claimed', 'complete')),
            claimed_at TEXT,
            claim_token TEXT,
            last_error TEXT,
            completion_json TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL
        )"""
    )


def _migrate_v9_to_v10(connection: sqlite3.Connection) -> None:
    """Add lifecycle facts without rewriting existing events."""
    existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "episodes" in existing:
        episode_columns = {row[1] for row in connection.execute("PRAGMA table_info(episodes)")}
        for name in ("resolution_reason", "quiet_started_at", "archived_at"):
            if name not in episode_columns:
                connection.execute(f"ALTER TABLE episodes ADD COLUMN {name} TEXT")


def _migrate_v10_to_v11(connection: sqlite3.Connection) -> None:
    """Persist an optional immutable link from an update to its weekly setup."""
    existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "source_events" not in existing:
        return
    columns = {row[1] for row in connection.execute("PRAGMA table_info(source_events)")}
    if "matched_setup_event_key" not in columns:
        connection.execute("ALTER TABLE source_events ADD COLUMN matched_setup_event_key TEXT")


def _migrate_v11_to_v12(connection: sqlite3.Connection) -> None:
    """Persist ordered source media paths without rewriting existing events."""
    existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "source_events" not in existing:
        return
    columns = {row[1] for row in connection.execute("PRAGMA table_info(source_events)")}
    if "media_paths_json" not in columns:
        connection.execute("ALTER TABLE source_events ADD COLUMN media_paths_json TEXT NOT NULL DEFAULT '[]'")


def _create_missing_tables(connection: sqlite3.Connection) -> None:
    existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "episodes" not in existing:
        _create_non_event_tables(connection)


def _timestamp(value: datetime) -> str:
    return _aware(value, "timestamp").astimezone(timezone.utc).isoformat()


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return value


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _close_phase(value: str) -> None:
    if value not in {"initial", "retry"}:
        raise ValueError("close phase must be initial or retry")


def _source_event_key_from_dedupe(value: str) -> tuple[str, int]:
    prefix = "event:"
    marker = ":post_source_reply"
    if not value.startswith(prefix) or marker not in value:
        raise StoreBlockedError("source reply dedupe key is invalid")
    event_key, _, suffix = value[len(prefix):].rpartition(marker)
    if not event_key:
        raise StoreBlockedError("source reply event identity is missing")
    chunk_index = 0
    if suffix.startswith(":"):
        trailing = suffix.rsplit(":", 1)[-1]
        if trailing.isdigit():
            chunk_index = int(trailing)
    return event_key, chunk_index


def episode_sources_from_connection(
    connection: sqlite3.Connection, episode_id: int
) -> set[str]:
    """Resolve source names for one episode using an existing read connection."""
    starter = connection.execute(
        """SELECT s.source FROM episodes e JOIN source_events s
        ON s.id = e.starter_source_event_id WHERE e.id = ?""",
        (episode_id,),
    ).fetchone()
    sources: set[str] = {str(starter["source"])} if starter is not None else set()
    rows = connection.execute(
        "SELECT dedupe_key FROM outbox "
        "WHERE episode_id = ? AND operation = 'post_source_reply'",
        (episode_id,),
    ).fetchall()
    seen: set[str] = set()
    for row in rows:
        try:
            event_key, _ = _source_event_key_from_dedupe(row["dedupe_key"])
        except StoreBlockedError:
            continue
        if event_key in seen:
            continue
        seen.add(event_key)
        event = connection.execute(
            "SELECT source FROM source_events WHERE event_key = ?", (event_key,)
        ).fetchone()
        if event is not None:
            sources.add(str(event["source"]))
    return sources


def _episode_from_row(row: sqlite3.Row) -> Episode:
    return Episode(
        id=int(row["id"]),
        ticker=row["ticker"],
        lifecycle=row["lifecycle"],
        title=row["title"],
        opened_at=_parse_timestamp(row["opened_at"]),
        latest_material_at=_parse_timestamp(row["latest_material_at"]),
        closed_at=_parse_timestamp(row["closed_at"]) if row["closed_at"] else None,
        thread_id=row["thread_id"],
        starter_message_id=row["starter_message_id"],
        starter_source_event_id=row["starter_source_event_id"],
        lifecycle_tag=row["lifecycle_tag"],
        market_tag=row["market_tag"],
        resolution_reason=row["resolution_reason"],
        quiet_started_at=_parse_timestamp(row["quiet_started_at"]) if row["quiet_started_at"] else None,
        archived_at=_parse_timestamp(row["archived_at"]) if row["archived_at"] else None,
    )


def _channel_outbox_from_row(row: sqlite3.Row) -> ChannelOutboxOperation:
    return ChannelOutboxOperation(
        id=int(row["id"]),
        channel_id=str(row["channel_id"]),
        content=str(row["content"]),
        dedupe_key=str(row["dedupe_key"]),
        attempts=int(row["attempts"]),
        status=str(row["status"]),
        claim_token=row["claim_token"],
    )


def _source_event_from_row(row: sqlite3.Row) -> SourceEvent:
    paths = tuple(json.loads(row["media_paths_json"]))
    if not paths and row["media_path"]:
        paths = (row["media_path"],)
    return SourceEvent(
        event_key=row["event_key"], source=row["source"], kind=row["kind"], ticker=row["ticker"],
        published_at=_parse_timestamp(row["published_at"]), source_url=row["source_url"],
        all_content=row["all_content"], source_title=row["source_title"],
        source_status=row["source_status"],
        plan=PlanLevels(row["plan_entry"], row["plan_stop_loss"], tuple(json.loads(row["plan_targets_json"])))
        if row["plan_entry"] else None,
        media_path=row["media_path"], media_urls=tuple(json.loads(row["media_urls_json"])),
        media_paths=paths,
        matched_setup_event_key=row["matched_setup_event_key"],
    )


def _projected_plan_from_row(row: sqlite3.Row) -> SourceEvent:
    event = _source_event_from_row(row)
    plan = PlanLevels(
        row["active_plan_entry"],
        row["active_plan_stop_loss"],
        tuple(json.loads(row["active_plan_targets_json"])),
    )
    return replace(event, plan=plan, source_status=row["current_status"])


def _outbox_from_row(row: sqlite3.Row) -> OutboxOperation:
    return OutboxOperation(
        id=int(row["id"]),
        operation=row["operation"],
        episode_id=int(row["episode_id"]),
        payload=json.loads(row["payload_json"]),
        dedupe_key=row["dedupe_key"],
        attempts=int(row["attempts"]),
        next_attempt_at=_parse_timestamp(row["next_attempt_at"]),
        status=row["status"],
        last_error=row["last_error"],
        claim_token=row["claim_token"],
    )


def _execute_statements(connection: sqlite3.Connection, script: str) -> None:
    """Execute static schema DDL without executescript's implicit transaction commit."""
    for statement in script.split(";"):
        if statement.strip():
            connection.execute(statement)
