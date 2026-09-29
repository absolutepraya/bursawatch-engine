from scripts.production_snapshot import (
    parse_cron_listing,
    parse_cron_status,
    parse_release_status,
    parse_schedule_catalog,
    compare_schedule_registry,
)


def test_parse_cron_listing_filters_other_tasks_and_limits_output_fields() -> None:
    listing = """\
  0f706b936242 [active]
    Name:      personal-scele-digest
    Schedule:  0 7 * * 1,3,5
    Last run:  2026-09-28T07:01:03+07:00  ok

  0c6b17e4c944 [active]
    Name:      cron-stockbit-snips
    Schedule:  every 15m
    Deliver:   discord:private
    Skills:    bursawatch-rss-source-ingest
    Script:    bursawatch-rss-source-ingest.sh
    Last run:  2026-09-29T11:14:34+07:00  ok
    Execution: completed secret-or-payload

  6a0b4f895b07 [paused]
    Name:      bursawatch-tg-market-news
    Schedule:  * * * * *
    Skills:    bursawatch-tg-market-news
    Script:    bursawatch-tg-market-news.sh
    Last run:  2026-09-27T13:05:08+07:00  error: Script exited with code 1
stdout:
private payload must never be returned
"""

    jobs = parse_cron_listing(listing)

    by_id = {job["id"]: job for job in jobs}
    assert set(by_id) == {"0c6b17e4c944", "6a0b4f895b07"}
    assert by_id["0c6b17e4c944"] == {
        "id": "0c6b17e4c944",
        "state": "active",
        "name": "cron-stockbit-snips",
        "schedule": "every 15m",
        "skills": ["bursawatch-rss-source-ingest"],
        "script": "bursawatch-rss-source-ingest.sh",
        "last_run_status": "ok",
    }
    assert by_id["6a0b4f895b07"] == {
        "id": "6a0b4f895b07",
        "state": "paused",
        "name": "bursawatch-tg-market-news",
        "schedule": "* * * * *",
        "skills": ["bursawatch-tg-market-news"],
        "script": "bursawatch-tg-market-news.sh",
        "last_run_status": "error",
    }
    assert "private payload must never be returned" not in repr(jobs)


def test_parse_release_status_discards_unneeded_fields() -> None:
    raw = """{
      "version": 1,
      "last_success_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "github_status": {
        "sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "state": "success",
        "description": "released 8 units"
      },
      "blocked": null,
      "transient": null,
      "private_detail": "must not appear in the result"
    }"""

    assert parse_release_status(raw) == {
        "last_success_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "github_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "github_state": "success",
        "blocked": False,
        "transient": False,
    }


def test_parse_cron_status_keeps_only_health_fields() -> None:
    output = """\
✓ Gateway is running - cron jobs will fire automatically
  PID: 1234
  Ticker heartbeat: 12s ago

  16 active job(s)
  Next run: 2026-09-29T11:18:00+07:00
"""

    assert parse_cron_status(output) == {
        "gateway_running": True,
    }


def test_schedule_catalog_is_filtered_and_compared_to_hermes_registry() -> None:
    payload = """[
      {
        "runtime_job_key": "personal-private-job",
        "schedule": {"enabled": true, "interval_seconds": 60},
        "secret": "must not appear"
      },
      {
        "runtime_job_key": "bursawatch-wa-channel-watch",
        "schedule": {"enabled": true, "interval_seconds": 60, "revision": 8},
        "reconciliation": {"status": "applied", "applied_revision": 8, "effective": true, "last_error": "private"}
      },
      {
        "runtime_job_key": "bursawatch-tg-kelas-investasi-gtw",
        "schedule": {"enabled": false, "interval_seconds": 3600, "revision": 4},
        "reconciliation": {"status": "applied", "applied_revision": 4, "effective": true}
      }
    ]"""

    schedules = parse_schedule_catalog(payload)
    registry = [
        {
            "name": "bursawatch-wa-channel-watch",
            "state": "active",
            "schedule": "every 1m",
        },
        {
            "name": "bursawatch-tg-kelas-investasi-gtw",
            "state": "paused",
            "schedule": "0 * * * *",
        },
    ]

    compared = compare_schedule_registry(schedules, registry)

    assert [item["runtime_job_key"] for item in compared] == [
        "bursawatch-tg-kelas-investasi-gtw",
        "bursawatch-wa-channel-watch",
    ]
    assert all(item["registry_matches_desired"] for item in compared)
    assert compared[0]["interval_minutes"] == 60
    assert compared[0]["hermes_interval_minutes"] == 60
    assert compared[1]["interval_minutes"] == 1
    assert "private" not in repr(compared)
