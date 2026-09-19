from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import secrets
from typing import Any, Protocol

from .contract import ConfigSnapshot, config_checksum, validate_watcher_id


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    watcher_id: str
    scheduler_job_id: str | None
    trigger: str
    config_revision: int
    started_at: str
    finished_at: str | None = None
    status: str = "running"
    error: str | None = None


@dataclass(frozen=True)
class EventRecord:
    run_id: str
    event_id: str
    occurred_at: str
    level: str
    phase: str
    event_type: str
    message: str
    attributes: dict[str, Any]


@dataclass(frozen=True)
class WatcherSummary:
    watcher_id: str
    display_name: str
    current_revision: int | None
    updated_at: str


class Store(Protocol):
    def list_watchers(self) -> list[WatcherSummary]: ...

    def get_config(self, watcher_id: str) -> ConfigSnapshot: ...

    def put_config(
        self,
        watcher_id: str,
        config_version: int,
        config: dict[str, Any],
        actor_id: str,
    ) -> ConfigSnapshot: ...

    def start_run(
        self,
        watcher_id: str,
        config_revision: int,
        scheduler_job_id: str | None,
        trigger: str,
        run_id: str | None = None,
    ) -> RunRecord: ...

    def append_event(self, event: EventRecord) -> EventRecord: ...

    def finish_run(self, run_id: str, status: str, error: str | None) -> RunRecord: ...

    def list_runs(self, watcher_id: str, limit: int) -> list[RunRecord]: ...

    def list_events(self, run_id: str, limit: int) -> list[EventRecord]: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_run_id(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > 128:
        raise ValueError("run_id must be non-empty text of at most 128 characters")
    return value


def _event_matches(left: EventRecord, right: EventRecord) -> bool:
    try:
        left_time = datetime.fromisoformat(left.occurred_at.replace("Z", "+00:00"))
        right_time = datetime.fromisoformat(right.occurred_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (
        left.run_id == right.run_id
        and left.event_id == right.event_id
        and left_time == right_time
        and left.level == right.level
        and left.phase == right.phase
        and left.event_type == right.event_type
        and left.message == right.message
        and left.attributes == right.attributes
    )


class InMemoryStore:
    """Small deterministic store for API contract tests and local exploration."""

    def __init__(self) -> None:
        self._configs: dict[str, list[ConfigSnapshot]] = {}
        self._runs: dict[str, RunRecord] = {}
        self._events: dict[tuple[str, str], EventRecord] = {}

    def list_watchers(self) -> list[WatcherSummary]:
        return [
            WatcherSummary(
                watcher_id=watcher_id,
                display_name=watcher_id,
                current_revision=snapshots[-1].revision,
                updated_at=snapshots[-1].updated_at,
            )
            for watcher_id, snapshots in sorted(self._configs.items())
            if snapshots
        ]

    def seed_config(self, watcher_id: str, config_version: int, config: dict[str, Any]) -> ConfigSnapshot:
        return self._put(watcher_id, config_version, config)

    def get_config(self, watcher_id: str) -> ConfigSnapshot:
        validate_watcher_id(watcher_id)
        try:
            return self._configs[watcher_id][-1]
        except (KeyError, IndexError) as exc:
            raise KeyError(watcher_id) from exc

    def put_config(
        self,
        watcher_id: str,
        config_version: int,
        config: dict[str, Any],
        actor_id: str,
    ) -> ConfigSnapshot:
        del actor_id
        return self._put(watcher_id, config_version, config)

    def _put(self, watcher_id: str, config_version: int, config: dict[str, Any]) -> ConfigSnapshot:
        validate_watcher_id(watcher_id)
        revision = len(self._configs.get(watcher_id, [])) + 1
        snapshot = ConfigSnapshot(
            watcher_id=watcher_id,
            revision=revision,
            config_version=config_version,
            config=deepcopy(config),
            config_sha256=config_checksum(config),
            updated_at=_now(),
        )
        self._configs.setdefault(watcher_id, []).append(snapshot)
        return snapshot

    def start_run(
        self,
        watcher_id: str,
        config_revision: int,
        scheduler_job_id: str | None,
        trigger: str,
        run_id: str | None = None,
    ) -> RunRecord:
        validate_watcher_id(watcher_id)
        if run_id is None:
            run_id = secrets.token_hex(16)
        else:
            _validate_run_id(run_id)
            existing = self._runs.get(run_id)
            if existing is not None:
                if (
                    existing.watcher_id,
                    existing.config_revision,
                    existing.scheduler_job_id,
                    existing.trigger,
                ) != (watcher_id, config_revision, scheduler_job_id, trigger):
                    raise ValueError("run_id already exists with different run attributes")
                return existing
        run = RunRecord(
            run_id=run_id,
            watcher_id=watcher_id,
            scheduler_job_id=scheduler_job_id,
            trigger=trigger,
            config_revision=config_revision,
            started_at=_now(),
        )
        self._runs[run_id] = run
        return run

    def append_event(self, event: EventRecord) -> EventRecord:
        key = (event.run_id, event.event_id)
        existing = self._events.get(key)
        if existing is not None:
            if not _event_matches(existing, event):
                raise ValueError("event_id already exists with different event data")
            return existing
        self._events[key] = EventRecord(
            run_id=event.run_id,
            event_id=event.event_id,
            occurred_at=event.occurred_at,
            level=event.level,
            phase=event.phase,
            event_type=event.event_type,
            message=event.message,
            attributes=deepcopy(event.attributes),
        )
        return self._events[key]

    def finish_run(self, run_id: str, status: str, error: str | None) -> RunRecord:
        try:
            current = self._runs[run_id]
        except KeyError as exc:
            raise KeyError(run_id) from exc
        if current.finished_at is not None:
            if current.status != status or current.error != error:
                raise ValueError("run is already finished with different result")
            return current
        finished = RunRecord(
            run_id=current.run_id,
            watcher_id=current.watcher_id,
            scheduler_job_id=current.scheduler_job_id,
            trigger=current.trigger,
            config_revision=current.config_revision,
            started_at=current.started_at,
            finished_at=_now(),
            status=status,
            error=error,
        )
        self._runs[run_id] = finished
        return finished

    def list_runs(self, watcher_id: str, limit: int) -> list[RunRecord]:
        validate_watcher_id(watcher_id)
        return sorted(
            (run for run in self._runs.values() if run.watcher_id == watcher_id),
            key=lambda run: run.started_at,
            reverse=True,
        )[:limit]

    def list_events(self, run_id: str, limit: int) -> list[EventRecord]:
        return sorted(
            (event for event in self._events.values() if event.run_id == run_id),
            key=lambda event: event.occurred_at,
        )[:limit]

    @property
    def runs(self) -> dict[str, RunRecord]:
        return dict(self._runs)

    @property
    def events(self) -> dict[tuple[str, str], EventRecord]:
        return dict(self._events)


class PostgresStore:
    """Postgres implementation used by the deployed control-plane service."""

    def __init__(self, dsn: str) -> None:
        if type(dsn) is not str or not dsn.strip():
            raise ValueError("Postgres DSN is required")
        self.dsn = dsn

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("psycopg is required for the Postgres control-plane store") from exc
        return psycopg.connect(self.dsn, row_factory=dict_row)

    @staticmethod
    def _timestamp(value: object) -> str:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise RuntimeError("database returned a naive timestamp")
            return value.isoformat()
        return str(value)

    @classmethod
    def _snapshot(cls, row: dict[str, Any]) -> ConfigSnapshot:
        return ConfigSnapshot(
            watcher_id=row["watcher_id"],
            revision=row["revision"],
            config_version=row["config_version"],
            config=row["config"],
            config_sha256=row["config_sha256"],
            updated_at=cls._timestamp(row["created_at"]),
        )

    def get_config(self, watcher_id: str) -> ConfigSnapshot:
        validate_watcher_id(watcher_id)
        query = """
            select w.watcher_id, r.revision, r.config_version, r.config,
                   r.config_sha256, r.created_at
              from bursawatch_watchers w
              join bursawatch_config_revisions r
                on r.watcher_id = w.watcher_id
               and r.revision = w.current_revision
             where w.watcher_id = %s
        """
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, (watcher_id,))
            row = cursor.fetchone()
        if row is None:
            raise KeyError(watcher_id)
        return self._snapshot(row)

    def list_watchers(self) -> list[WatcherSummary]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                select watcher_id, display_name, current_revision, updated_at
                  from bursawatch_watchers
                 order by watcher_id
                """
            )
            rows = cursor.fetchall()
        return [
            WatcherSummary(
                watcher_id=row["watcher_id"],
                display_name=row["display_name"],
                current_revision=row["current_revision"],
                updated_at=self._timestamp(row["updated_at"]),
            )
            for row in rows
        ]

    def put_config(
        self,
        watcher_id: str,
        config_version: int,
        config: dict[str, Any],
        actor_id: str,
    ) -> ConfigSnapshot:
        validate_watcher_id(watcher_id)
        if type(actor_id) is not str or not actor_id.strip():
            raise ValueError("actor_id is required")
        checksum = config_checksum(config)
        try:
            from psycopg.types.json import Jsonb
        except ImportError as exc:
            raise RuntimeError("psycopg is required for the Postgres control-plane store") from exc
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                insert into bursawatch_watchers (watcher_id, display_name, validator_key)
                values (%s, %s, %s)
                on conflict (watcher_id) do nothing
                """,
                (watcher_id, watcher_id, watcher_id),
            )
            cursor.execute(
                """
                select current_revision
                  from bursawatch_watchers
                 where watcher_id = %s
                 for update
                """,
                (watcher_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("watcher registration was not created")
            revision = (row["current_revision"] or 0) + 1
            cursor.execute(
                """
                insert into bursawatch_config_revisions
                    (watcher_id, revision, config_version, config, config_sha256, actor_id)
                values (%s, %s, %s, %s, %s, %s)
                returning watcher_id, revision, config_version, config,
                          config_sha256, created_at
                """,
                (watcher_id, revision, config_version, Jsonb(config), checksum, actor_id),
            )
            inserted = cursor.fetchone()
            cursor.execute(
                """
                update bursawatch_watchers
                   set current_revision = %s, updated_at = now()
                 where watcher_id = %s
                """,
                (revision, watcher_id),
            )
        if inserted is None:
            raise RuntimeError("database did not return the new config revision")
        return self._snapshot(inserted)

    def start_run(
        self,
        watcher_id: str,
        config_revision: int,
        scheduler_job_id: str | None,
        trigger: str,
        run_id: str | None = None,
    ) -> RunRecord:
        validate_watcher_id(watcher_id)
        if run_id is None:
            run_id = secrets.token_hex(16)
        else:
            _validate_run_id(run_id)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                insert into bursawatch_runs
                    (run_id, watcher_id, scheduler_job_id, trigger, config_revision, started_at, status)
                values (%s, %s, %s, %s, %s, now(), 'running')
                on conflict (run_id) do nothing
                """,
                (run_id, watcher_id, scheduler_job_id, trigger, config_revision),
            )
            cursor.execute(
                """
                select run_id, watcher_id, scheduler_job_id, trigger,
                       config_revision, started_at, finished_at, status, error
                  from bursawatch_runs
                 where run_id = %s
                """,
                (run_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError("database did not return the run")
        existing = self._run(row)
        if (
            existing.watcher_id,
            existing.config_revision,
            existing.scheduler_job_id,
            existing.trigger,
        ) != (watcher_id, config_revision, scheduler_job_id, trigger):
            raise ValueError("run_id already exists with different run attributes")
        return existing

    @classmethod
    def _run(cls, row: dict[str, Any]) -> RunRecord:
        return RunRecord(
            run_id=row["run_id"],
            watcher_id=row["watcher_id"],
            scheduler_job_id=row["scheduler_job_id"],
            trigger=row["trigger"],
            config_revision=row["config_revision"],
            started_at=cls._timestamp(row["started_at"]),
            finished_at=cls._timestamp(row["finished_at"]) if row["finished_at"] else None,
            status=row["status"],
            error=row["error"],
        )

    def append_event(self, event: EventRecord) -> EventRecord:
        try:
            from psycopg.types.json import Jsonb
        except ImportError as exc:
            raise RuntimeError("psycopg is required for the Postgres control-plane store") from exc
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                insert into bursawatch_events
                    (run_id, event_id, occurred_at, level, phase, event_type, message, attributes)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (run_id, event_id) do nothing
                """,
                (
                    event.run_id,
                    event.event_id,
                    datetime.fromisoformat(event.occurred_at.replace("Z", "+00:00")),
                    event.level,
                    event.phase,
                    event.event_type,
                    event.message,
                    Jsonb(event.attributes),
                ),
            )
            cursor.execute(
                """
                select run_id, event_id, occurred_at, level, phase, event_type, message, attributes
                  from bursawatch_events
                 where run_id = %s and event_id = %s
                """,
                (event.run_id, event.event_id),
            )
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError("database did not return the event")
        stored = EventRecord(
            run_id=row["run_id"],
            event_id=row["event_id"],
            occurred_at=self._timestamp(row["occurred_at"]),
            level=row["level"],
            phase=row["phase"],
            event_type=row["event_type"],
            message=row["message"],
            attributes=row["attributes"],
        )
        if not _event_matches(stored, event):
            raise ValueError("event_id already exists with different event data")
        return stored

    def finish_run(self, run_id: str, status: str, error: str | None) -> RunRecord:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                update bursawatch_runs
                   set finished_at = now(), status = %s, error = %s
                 where run_id = %s and finished_at is null
                returning run_id, watcher_id, scheduler_job_id, trigger,
                          config_revision, started_at, finished_at, status, error
                """,
                (status, error, run_id),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    """
                    select run_id, watcher_id, scheduler_job_id, trigger,
                           config_revision, started_at, finished_at, status, error
                      from bursawatch_runs
                     where run_id = %s
                    """,
                    (run_id,),
                )
                row = cursor.fetchone()
        if row is None:
            raise KeyError(run_id)
        existing = self._run(row)
        if existing.finished_at is not None and (existing.status != status or existing.error != error):
            raise ValueError("run is already finished with different result")
        return existing

    def list_runs(self, watcher_id: str, limit: int) -> list[RunRecord]:
        validate_watcher_id(watcher_id)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                select run_id, watcher_id, scheduler_job_id, trigger,
                       config_revision, started_at, finished_at, status, error
                  from bursawatch_runs
                 where watcher_id = %s
                 order by started_at desc
                 limit %s
                """,
                (watcher_id, limit),
            )
            rows = cursor.fetchall()
        return [self._run(row) for row in rows]

    def list_events(self, run_id: str, limit: int) -> list[EventRecord]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                select run_id, event_id, occurred_at, level, phase, event_type, message, attributes
                  from bursawatch_events
                 where run_id = %s
                 order by occurred_at asc
                 limit %s
                """,
                (run_id, limit),
            )
            rows = cursor.fetchall()
        return [
            EventRecord(
                run_id=row["run_id"],
                event_id=row["event_id"],
                occurred_at=self._timestamp(row["occurred_at"]),
                level=row["level"],
                phase=row["phase"],
                event_type=row["event_type"],
                message=row["message"],
                attributes=row["attributes"],
            )
            for row in rows
        ]
