"""Single-owner durable store for the IDX Swing plan board.

The store records intent only. Discord operations are performed later by the
owner's outbox drainer, never from these transaction methods.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Mapping

from models import Checkpoint, Episode, OutboxOperation, SourceEvent, SubmittedEvent


SCHEMA_VERSION = 2
_LEGAL_OPERATIONS = frozenset(
    {"create_thread", "edit_starter", "post_source_reply", "post_history_reply", "patch_thread"}
)
_BACKOFF_MINUTES = (1, 2, 4, 8, 15, 30, 60)
_LEASE = timedelta(minutes=5)
_TABLES = frozenset({"source_events", "episodes", "plans", "checkpoints", "history_events", "outbox"})


class StoreBlockedError(RuntimeError):
    """The database cannot be safely opened without operator intervention."""


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
            cursor = connection.execute(
                """
                INSERT INTO source_events (
                    event_key, source, kind, ticker, published_at, source_url,
                    all_content, source_title, source_status, plan_entry,
                    plan_stop_loss, plan_targets_json, media_path, media_urls_json,
                    received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def record_checkpoint(
        self,
        episode_id: int,
        checkpoint: Checkpoint,
        source_freshness: str | None = None,
    ) -> None:
        """Persist a factual or unavailable checkpoint, without Discord work."""
        with self._transaction() as connection:
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

    def enqueue_test_operation(self, operation: str, episode_id: int) -> OutboxOperation:
        """Test-only convenience that still uses the production outbox constraints."""
        return self.enqueue_outbox(
            operation,
            episode_id,
            {"test": True},
            f"test:{operation}:{episode_id}",
            datetime.now().astimezone(),
        )

    def claim_due_outbox(self, now: datetime) -> OutboxOperation | None:
        now = _aware(now, "now")
        stale_before = now - _LEASE
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT id FROM outbox
                WHERE (status = 'pending' AND next_attempt_at <= ?)
                   OR (status = 'claimed' AND claimed_at <= ?)
                ORDER BY id
                LIMIT 1
                """,
                (_timestamp(now), _timestamp(stale_before)),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE outbox SET status = 'claimed', claimed_at = ? WHERE id = ?",
                (_timestamp(now), int(row[0])),
            )
            return self._outbox(connection, int(row[0]))

    def complete_outbox(
        self, operation_id: int, completion: Mapping[str, Any], completed_at: datetime
    ) -> None:
        completed_at = _aware(completed_at, "completed_at")
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE outbox
                SET status = 'complete', completion_json = ?, completed_at = ?, claimed_at = NULL
                WHERE id = ? AND status != 'complete'
                """,
                (json.dumps(dict(completion), sort_keys=True), _timestamp(completed_at), operation_id),
            )
            if cursor.rowcount == 0 and not connection.execute(
                "SELECT 1 FROM outbox WHERE id = ?", (operation_id,)
            ).fetchone():
                raise KeyError(f"unknown outbox operation: {operation_id}")

    def fail_outbox(self, operation_id: int, error: str, failed_at: datetime) -> None:
        if not error.strip():
            raise ValueError("outbox error must be non-empty")
        failed_at = _aware(failed_at, "failed_at")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT attempts, status FROM outbox WHERE id = ?", (operation_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown outbox operation: {operation_id}")
            if row[1] == "complete":
                raise StoreBlockedError("cannot fail completed outbox operation")
            attempts = int(row[0]) + 1
            delay = _BACKOFF_MINUTES[min(attempts - 1, len(_BACKOFF_MINUTES) - 1)]
            connection.execute(
                """
                UPDATE outbox
                SET attempts = ?, next_attempt_at = ?, status = 'pending',
                    claimed_at = NULL, last_error = ?
                WHERE id = ?
                """,
                (attempts, _timestamp(failed_at + timedelta(minutes=delay)), error, operation_id),
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
            received_at TEXT NOT NULL
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
            lifecycle_tag TEXT,
            market_tag TEXT
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
            UNIQUE(episode_id, material_payload)
        );
        CREATE TABLE outbox (
            id INTEGER PRIMARY KEY,
            operation TEXT NOT NULL CHECK (operation IN (
                'create_thread', 'edit_starter', 'post_source_reply',
                'post_history_reply', 'patch_thread'
            )),
            episode_id INTEGER NOT NULL REFERENCES episodes(id),
            payload_json TEXT NOT NULL,
            dedupe_key TEXT NOT NULL UNIQUE,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending', 'claimed', 'complete')),
            claimed_at TEXT,
            last_error TEXT,
            completion_json TEXT,
            completed_at TEXT
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


def _create_missing_tables(connection: sqlite3.Connection) -> None:
    existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "episodes" not in existing:
        _create_non_event_tables(connection)


def _timestamp(value: datetime) -> str:
    return _aware(value, "timestamp").isoformat()


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return value


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


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
        lifecycle_tag=row["lifecycle_tag"],
        market_tag=row["market_tag"],
    )


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
    )


def _execute_statements(connection: sqlite3.Connection, script: str) -> None:
    """Execute static schema DDL without executescript's implicit transaction commit."""
    for statement in script.split(";"):
        if statement.strip():
            connection.execute(statement)
