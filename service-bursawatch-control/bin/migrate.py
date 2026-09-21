#!/usr/bin/env python3
"""Apply immutable Bursawatch control-plane migrations with a database ledger."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable


MIGRATION_RE = re.compile(r"[0-9]{3}_[a-z0-9_]+\.sql")
RELEASE_HEADER_RE = re.compile(
    r"\A\s*--\s*bursawatch-release:\s*(automatic|manual)\s*(?:\r?\n|\Z)",
    re.IGNORECASE,
)
LEGACY_RELEASE_POLICY_FILE = "legacy-release-eligibility.json"
LOCK_NAME = "bursawatch-control-plane-migrations-v1"


class MigrationError(RuntimeError):
    """A migration cannot be safely selected or applied."""


@dataclass(frozen=True)
class Migration:
    name: str
    checksum: str
    sql: str
    release_eligibility: str


def _legacy_release_eligibilities(directory: Path) -> dict[str, str]:
    policy_path = directory / LEGACY_RELEASE_POLICY_FILE
    if not policy_path.is_file():
        return {}
    try:
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError("legacy migration eligibility policy is invalid") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise MigrationError("legacy migration eligibility policy has an unsupported version")
    entries = payload.get("migrations")
    if not isinstance(entries, dict):
        raise MigrationError("legacy migration eligibility policy must contain migrations")
    normalized: dict[str, str] = {}
    for name, eligibility in entries.items():
        if not isinstance(name, str) or not MIGRATION_RE.fullmatch(name):
            raise MigrationError("legacy migration eligibility policy has an invalid migration name")
        if eligibility not in {"automatic", "manual"}:
            raise MigrationError("legacy migration eligibility policy has an invalid eligibility")
        normalized[name] = eligibility
    return normalized


def _release_eligibility(name: str, sql: str, legacy: dict[str, str]) -> str:
    match = RELEASE_HEADER_RE.match(sql)
    if match is not None:
        if name in legacy:
            raise MigrationError(f"legacy migration must remain headerless: {name}")
        return match.group(1).lower()
    try:
        return legacy[name]
    except KeyError as exc:
        raise MigrationError(
            f"migration must start with '-- bursawatch-release: automatic' or "
            f"'-- bursawatch-release: manual': {name}"
        ) from exc


def discover_migrations(directory: Path) -> list[Migration]:
    try:
        paths = sorted(path for path in directory.iterdir() if path.is_file())
    except OSError as exc:
        raise MigrationError("migration directory could not be read") from exc
    legacy = _legacy_release_eligibilities(directory)
    migrations: list[Migration] = []
    seen_prefixes: set[str] = set()
    for path in paths:
        if not MIGRATION_RE.fullmatch(path.name):
            continue
        prefix = path.name.partition("_")[0]
        if prefix in seen_prefixes:
            raise MigrationError(f"duplicate migration prefix: {prefix}")
        seen_prefixes.add(prefix)
        try:
            sql = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise MigrationError(f"migration could not be read: {path.name}") from exc
        if not sql.strip():
            raise MigrationError(f"migration is empty: {path.name}")
        migrations.append(
            Migration(
                name=path.name,
                checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                sql=sql,
                release_eligibility=_release_eligibility(path.name, sql, legacy),
            )
        )
    unknown_legacy = sorted(set(legacy) - {migration.name for migration in migrations})
    if unknown_legacy:
        raise MigrationError(
            "legacy migration eligibility policy refers to missing migrations: "
            + ", ".join(unknown_legacy)
        )
    if not migrations:
        raise MigrationError("no migrations were found")
    return migrations


def _connect(dsn: str):
    try:
        import psycopg
    except ImportError as exc:
        raise MigrationError("psycopg is required to run migrations") from exc
    return psycopg.connect(dsn)


def _ensure_ledger(connection: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            create table if not exists bursawatch_schema_migrations (
                migration_name text primary key,
                checksum text not null check (length(checksum) = 64),
                applied_at timestamptz not null default now()
            )
            """
        )
    connection.commit()


def _acquire_lock(connection: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute("select pg_advisory_lock(hashtext(%s))", (LOCK_NAME,))
    connection.commit()


def _release_lock(connection: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute("select pg_advisory_unlock(hashtext(%s))", (LOCK_NAME,))
    connection.commit()


def apply_migrations(
    dsn: str,
    directory: Path,
    *,
    connect: Callable[[str], Any] = _connect,
) -> list[str]:
    if type(dsn) is not str or not dsn.strip():
        raise MigrationError("DATABASE_URL is required")
    migrations = discover_migrations(directory)
    connection = connect(dsn)
    locked = False
    outcomes: list[str] = []
    try:
        _ensure_ledger(connection)
        _acquire_lock(connection)
        locked = True
        for migration in migrations:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "select checksum from bursawatch_schema_migrations where migration_name = %s",
                        (migration.name,),
                    )
                    row = cursor.fetchone()
                    if row is not None:
                        if row[0] != migration.checksum:
                            raise MigrationError(f"applied migration has changed: {migration.name}")
                        outcomes.append(f"already applied: {migration.name}")
                        continue
                    cursor.execute(migration.sql)
                    cursor.execute(
                        """
                        insert into bursawatch_schema_migrations (migration_name, checksum)
                        values (%s, %s)
                        """,
                        (migration.name, migration.checksum),
                    )
                outcomes.append(f"applied: {migration.name}")
    finally:
        if locked:
            _release_lock(connection)
        connection.close()
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "migrations",
        help="directory containing ordered .sql migrations",
    )
    args = parser.parse_args()
    try:
        outcomes = apply_migrations(os.environ.get("DATABASE_URL", ""), args.migrations_dir)
    except MigrationError as exc:
        print(f"migration refused: {exc}", file=sys.stderr)
        return 1
    for outcome in outcomes:
        print(outcome)
    return 0


if __name__ == "__main__":
    sys.exit(main())
