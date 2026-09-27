from datetime import UTC, datetime, timedelta

import pytest

import recovery
import state


NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def payload(post_id="101", *, author="Kutekians", age_hours=2, parent=None):
    return {
        "tweetID": post_id,
        "user_screen_name": author,
        "date_epoch": int((NOW - timedelta(hours=age_hours)).timestamp()),
        "text": "Source fact",
        "mediaURLs": ["https://pbs.twimg.com/media/chart.jpg"],
        "replyingToID": parent,
        "replyingTo": author if parent else None,
    }


def test_preview_accepts_recent_owned_post_below_cursor_without_changing_state(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "102"}
    before = repr(value)

    rows = recovery.preview(
        value, (profile,), ["https://x.com/Kutekians/status/101?s=20"], NOW,
        lambda selected, post_id: payload(post_id),
    )

    assert [(row.profile.id, row.post.post_id, row.status) for row in rows] == [
        (profile.id, "101", "eligible")
    ]
    assert repr(value) == before


def test_recovery_deduplicates_against_outbox_and_delivery_and_is_idempotent(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "102"}
    fetch = lambda _profile, post_id: payload(post_id)
    url = "https://x.com/Kutekians/status/101"

    rows = recovery.preview(value, (profile,), [url], NOW, fetch)
    assert recovery.apply(value, rows, NOW) == 1
    assert value["profiles"][profile.id]["cursor"] == "102"
    assert len(value["outbox"]) == 1
    assert value["outbox"][0]["post_id"] == "101"
    assert value["outbox"][0]["recovery"]["kind"] == "source_gap"
    delivered = state.record_delivery(value, value["outbox"][0], "100000000000000001", NOW, False)
    assert delivered["recovery"]["kind"] == "source_gap"
    assert recovery.preview(value, (profile,), [url], NOW, fetch)[0].status == "already_queued"
    assert recovery.apply(value, rows, NOW) == 0

    value["outbox"].clear()
    value["deliveries"].append({"profile_id": profile.id, "source_post_ids": ["101"]})
    assert recovery.preview(value, (profile,), [url], NOW, fetch)[0].status == "already_delivered"


@pytest.mark.parametrize(
    ("post", "expected"),
    [
        (payload(age_hours=25), "expired"),
        (payload(author="other"), "author_mismatch"),
        (payload(parent="100"), "reply_requires_review"),
    ],
)
def test_recovery_rejects_stale_foreign_and_partial_thread_posts(config_path, post, expected):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "102"}
    row = recovery.preview(
        value, (profile,), ["https://x.com/Kutekians/status/101"], NOW,
        lambda _profile, _post_id: post,
    )[0]
    assert row.status == expected
    assert recovery.apply(value, [row], NOW) == 0


def test_recovery_rejects_future_cursor_and_invalid_or_duplicate_urls(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "100"}
    url = "https://x.com/Kutekians/status/101"
    row = recovery.preview(value, (profile,), [url], NOW, lambda _p, post_id: payload(post_id))[0]
    assert row.status == "await_normal_poll"
    with pytest.raises(ValueError, match="duplicate"):
        recovery.preview(value, (profile,), [url, url], NOW, lambda _p, post_id: payload(post_id))
    with pytest.raises(ValueError, match="invalid X status URL"):
        recovery.preview(value, (profile,), ["https://evil.test/Kutekians/status/101"], NOW, lambda _p, post_id: payload(post_id))


def test_scanner_recovery_command_rechecks_and_queues_without_rewinding_cursor(tmp_path, config_path, monkeypatch):
    import scan

    storage = tmp_path / "state.json"
    value = state.new_state()
    value["profiles"]["kutekians"] = {"cursor": "102"}
    state.save_state(storage, value)
    monkeypatch.setattr(scan, "state_path", lambda: storage)
    monkeypatch.setattr(scan, "config_path", lambda: config_path)
    monkeypatch.setattr(recovery, "fetch_public_detail", lambda _profile, post_id: {
        **payload(post_id),
        "date_epoch": int((datetime.now(UTC) - timedelta(hours=2)).timestamp()),
    })
    url = "https://x.com/Kutekians/status/101"

    preview = scan.recover_missing_source([url])
    assert preview["posts"][0]["status"] == "eligible"
    assert state.load_state(storage)["outbox"] == []
    with pytest.raises(ValueError, match="RECOVERY_APPLY"):
        scan.recover_missing_source([url], apply=True)
    monkeypatch.setenv("X_POST_WATCH_RECOVERY_APPLY", "1")

    applied = scan.recover_missing_source([url], apply=True)

    assert applied["queued"] == 1
    assert state.load_state(storage)["profiles"]["kutekians"]["cursor"] == "102"
    assert state.load_state(storage)["outbox"][0]["agent_phase"] == "pending"
