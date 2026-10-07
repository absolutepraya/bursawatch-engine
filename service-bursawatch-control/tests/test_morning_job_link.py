from pathlib import Path
import sqlite3

from control_plane.operator_inventory import component_view


OWNER = "bursawatch-dc-morning-brief"


def test_persisted_morning_link_is_idempotent_and_preserves_paused_schedule():
    # This additive migration uses SQL supported by both engines. Verify the
    # stored relationship without production credentials or provider calls.
    db = sqlite3.connect(":memory:")
    db.execute("pragma foreign_keys = on")
    db.execute("create table bursawatch_scheduler_jobs (job_id text primary key, enabled boolean, interval_seconds integer, revision integer)")
    db.execute("create table bursawatch_component_jobs (component_id text, job_id text references bursawatch_scheduler_jobs(job_id), primary key (component_id, job_id))")
    db.execute("insert into bursawatch_scheduler_jobs values (?, false, 60, 1)", (OWNER,))
    before = db.execute("select * from bursawatch_scheduler_jobs").fetchall()
    migration = (Path(__file__).resolve().parents[1] / "migrations/025_morning_brief_job_link.sql").read_text()
    assert migration.startswith("-- bursawatch-release: automatic")
    db.executescript(migration)
    db.executescript(migration)
    assert db.execute("select component_id, job_id from bursawatch_component_jobs").fetchall() == [(OWNER, OWNER)]
    assert db.execute("select * from bursawatch_scheduler_jobs").fetchall() == before
    assert component_view(OWNER)["job_ids"] == [OWNER]
    db.close()
