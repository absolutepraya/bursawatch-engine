from datetime import datetime, timedelta
import sqlite3
from zoneinfo import ZoneInfo

import pytest

from conftest import example_buy_event
from store import BoardStore, StoreBlockedError


WIB = ZoneInfo("Asia/Jakarta")


def at(minute: int = 5) -> datetime:
    return datetime(2026, 9, 19, 9, minute, tzinfo=WIB)


def test_duplicate_source_event_is_recorded_once(tmp_path) -> None:
    store = BoardStore(tmp_path / "board.sqlite3")
    event = example_buy_event("phintraco:1444713822:33655")

    first = store.submit_event(event, at(5))
    second = store.submit_event(event, at(6))

    assert first.inserted is True
    assert second.inserted is False
    assert store.count_rows("source_events") == 1
    assert store.count_rows("outbox") == 0


def test_failed_operation_retries_without_second_operation(tmp_path) -> None:
    store = BoardStore(tmp_path / "board.sqlite3")
    episode = store.create_episode("SCMA", "source", "SCMA: source context", at())
    operation = store.enqueue_test_operation("create_thread", episode.id)

    store.fail_outbox(operation.id, "Discord request failed", at())
    retry = store.claim_due_outbox(at(6))

    assert retry is not None
    assert retry.id == operation.id
    assert retry.attempts == 1
    assert store.count_rows("outbox") == 1


def test_duplicate_outbox_intent_reuses_the_existing_operation(tmp_path) -> None:
    store = BoardStore(tmp_path / "board.sqlite3")
    episode = store.create_episode("SCMA", "source", "SCMA: source context", at())

    first = store.enqueue_outbox(
        "post_source_reply",
        episode.id,
        {"content": "SCMA source"},
        "source:SCMA:33655",
        at(),
    )
    second = store.enqueue_outbox(
        "post_source_reply",
        episode.id,
        {"content": "SCMA source"},
        "source:SCMA:33655",
        at(6),
    )

    assert first.id == second.id
    assert store.count_rows("outbox") == 1


def test_transition_transaction_rolls_back_episode_and_intent_together(tmp_path) -> None:
    store = BoardStore(tmp_path / "board.sqlite3")

    with pytest.raises(RuntimeError, match="abort"):
        with store.transaction() as transition:
            episode = transition.create_episode("SCMA", "source", "SCMA: source context", at())
            transition.enqueue_outbox(
                "create_thread", episode.id, {}, "create:SCMA", at()
            )
            raise RuntimeError("abort")

    assert store.active_episode("SCMA") is None
    assert store.count_rows("outbox") == 0


def test_version_one_database_migrates_without_losing_source_rows(tmp_path) -> None:
    path = tmp_path / "board.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA user_version = 1;
        CREATE TABLE source_events (
            id INTEGER PRIMARY KEY,
            event_key TEXT NOT NULL UNIQUE,
            ticker TEXT NOT NULL
        );
        INSERT INTO source_events (event_key, ticker)
        VALUES ('phintraco:1444713822:33655', 'SCMA');
        """
    )
    connection.close()

    store = BoardStore(path)

    assert store.count_rows("source_events") == 1
    assert store.schema_version == 2

    connection = sqlite3.connect(path)
    assert connection.execute("SELECT event_key, ticker FROM source_events").fetchone() == (
        "phintraco:1444713822:33655",
        "SCMA",
    )
    connection.close()


def test_unknown_schema_version_is_blocked_without_table_mutation(tmp_path) -> None:
    path = tmp_path / "board.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA user_version = 99;
        CREATE TABLE sentinel (value TEXT NOT NULL);
        INSERT INTO sentinel (value) VALUES ('unchanged');
        """
    )
    connection.close()

    with pytest.raises(StoreBlockedError, match="unknown schema version"):
        BoardStore(path)

    connection = sqlite3.connect(path)
    assert connection.execute("SELECT value FROM sentinel").fetchone() == ("unchanged",)
    assert connection.execute("PRAGMA user_version").fetchone() == (99,)
    connection.close()


def test_backoff_caps_at_sixty_minutes_and_completed_work_is_not_claimed(tmp_path) -> None:
    store = BoardStore(tmp_path / "board.sqlite3")
    episode = store.create_episode("SCMA", "source", "SCMA: source context", at())
    operation = store.enqueue_test_operation("create_thread", episode.id)

    for expected_delay in (1, 2, 4, 8, 15, 30, 60, 60):
        store.fail_outbox(operation.id, "temporary", at())
        assert store.due_at(operation.id) == at() + timedelta(minutes=expected_delay)
        claimed = store.claim_due_outbox(store.due_at(operation.id))
        assert claimed is not None

    store.complete_outbox(operation.id, {"thread_id": "123"}, at())
    assert store.claim_due_outbox(at(59)) is None
