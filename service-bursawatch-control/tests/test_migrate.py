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
        self.transaction_count = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    @contextmanager
    def transaction(self):
        self.transaction_count += 1
        yield

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


def write_migration(
    directory: Path,
    name: str,
    sql: str = "-- bursawatch-release: automatic\nselect 1;",
) -> None:
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


def test_discover_migrations_requires_an_explicit_release_header_for_new_files(tmp_path: Path):
    write_migration(tmp_path, "001_first.sql", "select 1;")

    with pytest.raises(MigrationError, match="must start"):
        discover_migrations(tmp_path)


def test_discover_migrations_accepts_a_manual_release_header(tmp_path: Path):
    write_migration(tmp_path, "001_first.sql", "-- bursawatch-release: manual\nselect 1;")

    migrations = discover_migrations(tmp_path)

    assert migrations[0].release_eligibility == "manual"


def test_discover_migrations_uses_the_checked_legacy_eligibility_registry():
    directory = Path(__file__).resolve().parents[1] / "migrations"

    migrations = discover_migrations(directory)

    assert {migration.name for migration in migrations} == {
        "001_initial.sql",
        "002_seed_watchers.sql",
        "003_desired_schedule_controls.sql",
        "004_supabase_data_api_hardening.sql",
        "005_add_remaining_schedule_controls.sql",
        "006_scheduler_reconciliation_runtime.sql",
        "007_preserve_paused_instagram_baseline.sql",
        "008_profile_avatar_metadata.sql",
        "009_promote_whatsapp_v2_baseline.sql",
        "010_refresh_bri_source_emoji.sql",
        "011_stockbit_snips_control_plane.sql",
        "012_stockbit_scheduler_job_key.sql",
        "013_source_catalog.sql",
        "014_source_inbox.sql",
        "015_source_revision_identity.sql",
        "016_source_execution_fence.sql",
        "017_x_swing_route_groups.sql",
        "018_bri_whatsapp_news_compatibility.sql",
        "019_operator_inventory.sql",
        "020_publications.sql",
        "021_phintas_swing_compatibility.sql",
        "022_rename_x_source_display_names.sql",
    }
    assert {migration.release_eligibility for migration in migrations} == {"automatic", "manual"}
    assert next(
        migration.release_eligibility
        for migration in migrations
        if migration.name == "011_stockbit_snips_control_plane.sql"
    ) == "manual"
    assert next(
        migration.release_eligibility
        for migration in migrations
        if migration.name == "017_x_swing_route_groups.sql"
    ) == "automatic"
    assert next(
        migration.release_eligibility
        for migration in migrations
        if migration.name == "019_operator_inventory.sql"
    ) == "manual"
    assert next(
        migration.release_eligibility
        for migration in migrations
        if migration.name == "020_publications.sql"
    ) == "automatic"
    assert next(
        migration.release_eligibility
        for migration in migrations
        if migration.name == "022_rename_x_source_display_names.sql"
    ) == "manual"


def test_apply_migrations_records_each_immutable_file_and_is_idempotent(tmp_path: Path):
    write_migration(tmp_path, "001_first.sql")
    write_migration(tmp_path, "002_second.sql")
    connection = FakeConnection()

    first = apply_migrations("postgresql://example", tmp_path, connect=lambda _dsn: connection)

    assert first == ["applied: 001_first.sql", "applied: 002_second.sql"]
    assert sorted(connection.ledger) == ["001_first.sql", "002_second.sql"]
    assert connection.transaction_count == 2
    assert connection.closed is True

    connection.closed = False
    second = apply_migrations("postgresql://example", tmp_path, connect=lambda _dsn: connection)

    assert second == ["already applied: 001_first.sql", "already applied: 002_second.sql"]
    assert connection.transaction_count == 4
    assert connection.closed is True


def test_apply_migrations_refuses_a_changed_file_after_it_was_recorded(tmp_path: Path):
    write_migration(tmp_path, "001_first.sql", "-- bursawatch-release: automatic\nselect 1;")
    connection = FakeConnection()
    apply_migrations("postgresql://example", tmp_path, connect=lambda _dsn: connection)
    write_migration(tmp_path, "001_first.sql", "-- bursawatch-release: automatic\nselect 2;")

    with pytest.raises(MigrationError, match="has changed"):
        apply_migrations("postgresql://example", tmp_path, connect=lambda _dsn: connection)
