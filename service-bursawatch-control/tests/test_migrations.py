from __future__ import annotations

from pathlib import Path


def test_supabase_hardening_enables_rls_and_revokes_browser_roles():
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations/004_supabase_data_api_hardening.sql"
    ).read_text(encoding="utf-8")
    tables = (
        "bursawatch_watchers",
        "bursawatch_config_revisions",
        "bursawatch_runs",
        "bursawatch_events",
        "bursawatch_scheduler_jobs",
        "bursawatch_schedule_revisions",
    )

    for table in tables:
        assert f"alter table {table} enable row level security;" in migration
        assert f"'{table}'" in migration
    assert "revoke all privileges on table public.%I from public" in migration
    assert "from anon" in migration
    assert "from authenticated" in migration
