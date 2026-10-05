"""Exercise the label migration against an explicitly isolated PostgreSQL DB."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from control_plane.contract import config_checksum


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations/022_rename_x_source_display_names.sql"
WATCHER = "bursawatch-x-account-watch"
RENAMED = json.loads((ROOT / "baseline-configs" / f"{WATCHER}.json").read_text())
PREVIOUS = deepcopy(RENAMED)
for profile in PREVIOUS["profiles"]:
    if profile["id"] == "doktermarket":
        profile["display_name"] = "DokterMarket"
        profile["additional_prompt_instruction"] = profile["additional_prompt_instruction"].replace(
            "Dokter Market", "DokterMarket"
        )
    elif profile["id"] == "aldotjahjadi8":
        profile["display_name"] = "IHSG Journal 🍀🌞"


@pytest.fixture
def connection():
    dsn = os.environ.get("BURSAWATCH_TEST_POSTGRES_URL")
    if not dsn:
        pytest.skip("requires an isolated test Postgres database")
    with psycopg.connect(dsn) as conn:
        with conn.transaction(force_rollback=True):
            schema = f"rename_test_{uuid4().hex}"
            conn.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
            conn.execute(sql.SQL("set local search_path to {}").format(sql.Identifier(schema)))
            conn.execute((ROOT / "migrations/001_initial.sql").read_text())
            conn.execute("""
                create table bursawatch_source_publishers (
                    publisher_id text primary key,
                    name text not null,
                    system_owned boolean not null default true
                );
                insert into bursawatch_source_publishers (publisher_id, name) values
                    ('x-doktermarket', 'DokterMarket'),
                    ('x-aldotjahjadi8', 'IHSG Journal 🍀🌞'),
                    ('unrelated', 'Other Analyst');
            """)
            yield conn


def seed_config(conn, *, revision=1, actor="source-baseline", checksum=None):
    conn.execute(
        "insert into bursawatch_watchers (watcher_id, display_name, validator_key) values (%s, 'X Watch', 'x')",
        (WATCHER,),
    )
    conn.execute(
        """insert into bursawatch_config_revisions
           (watcher_id, revision, config_version, config, config_sha256, actor_id)
           values (%s, %s, 1, %s, %s, %s)""",
        (WATCHER, revision, Jsonb(PREVIOUS), checksum or config_checksum(PREVIOUS), actor),
    )
    conn.execute("update bursawatch_watchers set current_revision = %s", (revision,))


def test_manual_migration_preserves_history_and_changes_only_the_reviewed_labels(connection):
    assert MIGRATION.read_text().startswith("-- bursawatch-release: manual\n")
    seed_config(connection)
    connection.execute(MIGRATION.read_text())
    connection.execute(MIGRATION.read_text())

    rows = connection.execute(
        "select revision, config, config_sha256, actor_id from bursawatch_config_revisions order by revision"
    ).fetchall()
    assert rows == [
        (1, PREVIOUS, config_checksum(PREVIOUS), "source-baseline"),
        (2, RENAMED, config_checksum(RENAMED), "source-baseline-correction"),
    ]
    assert connection.execute("select current_revision from bursawatch_watchers").fetchone() == (2,)
    assert dict(connection.execute("select publisher_id, name from bursawatch_source_publishers").fetchall()) == {
        "x-doktermarket": "Dokter Market",
        "x-aldotjahjadi8": "Aldo Tjahjadi",
        "unrelated": "Other Analyst",
    }


@pytest.mark.parametrize("overrides", [
    {"actor": "dashboard-admin"},
    {"revision": 2},
    {"checksum": "0" * 64},
])
def test_migration_does_not_promote_operator_or_unrecognized_configurations(connection, overrides):
    seed_config(connection, **overrides)
    before = connection.execute("select * from bursawatch_config_revisions").fetchall()
    connection.execute(MIGRATION.read_text())
    assert connection.execute("select * from bursawatch_config_revisions").fetchall() == before
    assert connection.execute("select current_revision from bursawatch_watchers").fetchone() == (
        overrides.get("revision", 1),
    )


def test_migration_preserves_custom_publisher_labels_and_works_before_baseline_seeding(connection):
    connection.execute("update bursawatch_source_publishers set name = 'Custom label' where publisher_id = 'x-doktermarket'")
    connection.execute("update bursawatch_source_publishers set system_owned = false where publisher_id = 'x-aldotjahjadi8'")
    before = connection.execute("select * from bursawatch_source_publishers order by publisher_id").fetchall()
    connection.execute(MIGRATION.read_text())
    assert connection.execute("select * from bursawatch_source_publishers order by publisher_id").fetchall() == before
    assert connection.execute("select count(*) from bursawatch_config_revisions").fetchone() == (0,)
