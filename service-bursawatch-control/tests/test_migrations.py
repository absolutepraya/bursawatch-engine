from __future__ import annotations

from pathlib import Path

from control_plane.contract import schedule_checksum


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
        "bursawatch_schema_migrations",
    )

    for table in tables:
        assert f"alter table {table} enable row level security;" in migration
        assert f"'{table}'" in migration
    assert "revoke all privileges on table public.%I from public" in migration
    assert "from anon" in migration
    assert "from authenticated" in migration


def test_remaining_schedule_controls_seed_safe_baselines():
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations/005_add_remaining_schedule_controls.sql"
    ).read_text(encoding="utf-8")
    expected = {
        "bursawatch-tg-market-news": {
            "watcher_id": "bursawatch-tg-market-news",
            "display_name": "Telegram Market News",
            "minimum": 60,
            "maximum": 3_600,
            "enabled": True,
            "interval": 60,
        },
        "bursawatch-tg-kelas-investasi-gtw": {
            "watcher_id": "bursawatch-tg-kelas-investasi-gtw",
            "display_name": "Telegram Kelas Investasi GTW",
            "minimum": 300,
            "maximum": 21_600,
            "enabled": True,
            "interval": 3_600,
        },
        "bursawatch-wa-channel-watch": {
            "watcher_id": "bursawatch-wa-channel-watch",
            "display_name": "WhatsApp Channel Watch",
            "minimum": 60,
            "maximum": 21_600,
            "enabled": False,
            "interval": 60,
        },
    }

    for job_id, job in expected.items():
        assert (
            f"('{job_id}', '{job['watcher_id']}', '{job['display_name']}', "
            f"'{job_id}', 'interval', {job['minimum']}, {job['maximum']})"
        ) in migration
        checksum = schedule_checksum(job["enabled"], job["interval"], "Asia/Jakarta")
        assert (
            f"('{job_id}', 1, {str(job['enabled']).lower()}, {job['interval']}, "
            f"'Asia/Jakarta', '{checksum}', 'source-baseline')"
        ) in migration

    assert "and current_schedule_revision is null;" in migration


def test_scheduler_reconciliation_migration_records_safe_errors_and_corrects_x_runtime_key():
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations/006_scheduler_reconciliation_runtime.sql"
    ).read_text(encoding="utf-8")

    assert "add column if not exists reconciliation_error text;" in migration
    assert "length(reconciliation_error) between 1 and 500" in migration
    assert "runtime_job_key = 'bursawatch-x-account-watch'" in migration
    assert "runtime_job_key = 'x-post-source'" in migration


def test_paused_instagram_baseline_correction_is_additive_and_does_not_touch_hermes():
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations/007_preserve_paused_instagram_baseline.sql"
    ).read_text(encoding="utf-8")
    checksum = schedule_checksum(False, 3_600, "Asia/Jakarta")

    assert "bursawatch-ig-account-watch-source" in migration
    assert f"'bursawatch-ig-account-watch-source', 2, false, 3600, 'Asia/Jakarta', '{checksum}'" in migration
    assert "source-baseline-correction" in migration
    assert "and current_schedule_revision = 1;" in migration
    assert "hermes cron" not in migration.lower()


def test_profile_avatar_metadata_is_private_and_keeps_url_state_out_of_watcher_config():
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations/008_profile_avatar_metadata.sql"
    ).read_text(encoding="utf-8")

    assert migration.startswith("-- bursawatch-release: automatic\n")
    assert "create table if not exists bursawatch_profile_avatars" in migration
    assert "primary key (watcher_id, profile_id)" in migration
    assert "avatar_mode in ('auto', 'manual')" in migration
    assert "alter table bursawatch_profile_avatars enable row level security;" in migration
    assert "revoke all privileges on table public.bursawatch_profile_avatars from public" in migration
    assert "bursawatch_config_revisions" not in migration
