from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from migrate import MigrationError, apply_migrations, discover_migrations


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self.row: tuple[str] | None = None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[str, ...] | None = None) -> None:
        normalized = " ".join(sql.split())
        self.connection.executed.append((normalized, params))
        if normalized.startswith("select checksum"):
            assert params is not None
            checksum = self.connection.ledger.get(params[0])
            self.row = (checksum,) if checksum is not None else None
        elif normalized.startswith("insert into bursawatch_schema_migrations"):
            assert params is not None
            self.connection.ledger[params[0]] = params[1]

    def fetchone(self) -> tuple[str] | None:
        return self.row


class FakeConnection:
    def __init__(self) -> None:
        self.ledger: dict[str, str] = {}
        self.executed: list[tuple[str, tuple[str, ...] | None]] = []
        self.commits = 0
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    @contextmanager
    def transaction(self):
        yield

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


def write_migration(directory: Path, name: str, sql: str = "select 1;") -> None:
    (directory / name).write_text(sql, encoding="utf-8")


def test_discover_migrations_orders_files_and_rejects_duplicate_prefixes(tmp_path: Path):
    write_migration(tmp_path, "002_second.sql")
    write_migration(tmp_path, "001_first.sql")
    assert [migration.name for migration in discover_migrations(tmp_path)] == [
        "001_first.sql",
        "002_second.sql",
    ]

    write_migration(tmp_path, "001_duplicate.sql")
    with pytest.raises(MigrationError, match="duplicate"):
        discover_migrations(tmp_path)


def test_apply_migrations_records_each_immutable_file_and_is_idempotent(tmp_path: Path):
    write_migration(tmp_path, "001_first.sql")
    write_migration(tmp_path, "002_second.sql")
    connection = FakeConnection()

    first = apply_migrations("postgresql://example", tmp_path, connect=lambda _dsn: connection)

    assert first == ["applied: 001_first.sql", "applied: 002_second.sql"]
    assert sorted(connection.ledger) == ["001_first.sql", "002_second.sql"]
    assert connection.closed is True

    connection.closed = False
    second = apply_migrations("postgresql://example", tmp_path, connect=lambda _dsn: connection)

    assert second == ["already applied: 001_first.sql", "already applied: 002_second.sql"]
    assert connection.closed is True


def test_apply_migrations_refuses_a_changed_file_after_it_was_recorded(tmp_path: Path):
    write_migration(tmp_path, "001_first.sql", "select 1;")
    connection = FakeConnection()
    apply_migrations("postgresql://example", tmp_path, connect=lambda _dsn: connection)
    write_migration(tmp_path, "001_first.sql", "select 2;")

    with pytest.raises(MigrationError, match="has changed"):
        apply_migrations("postgresql://example", tmp_path, connect=lambda _dsn: connection)
