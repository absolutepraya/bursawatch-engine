from datetime import datetime, timedelta
import sqlite3
from zoneinfo import ZoneInfo

import pytest

from conftest import example_buy_event
from models import Checkpoint, MarketState
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
    operation = store.enqueue_test_operation("create_thread", episode.id, at())

    claim = store.claim_due_outbox(at())
    assert claim is not None
    assert claim.claim_token is not None
    store.fail_outbox(operation.id, claim.claim_token, "Discord request failed", at())
    retry = store.claim_due_outbox(at(6))

    assert retry is not None
    assert retry.id == operation.id
    assert retry.attempts == 1
    assert retry.claim_token is not None
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


def test_history_cleanup_queues_and_completes_legacy_message_deletion(tmp_path) -> None:
    store = BoardStore(tmp_path / "board.sqlite3")
    episode = store.create_episode("SCMA", "primary", "SCMA: Buy", at())
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE episodes SET thread_id = ?, starter_message_id = ? WHERE id = ?",
            ("thread-1", "starter-1", episode.id),
        )
    with store.transaction() as tx:
        history_id = tx.add_history(episode.id, None, "> old history", at(), "legacy:1")
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE history_events SET discord_message_id = ? WHERE id = ?",
            ("history-7", history_id),
        )
    assert store.history_cleanup_count() == 1

    with store.transaction() as tx:
        assert tx.schedule_history_deletes(at()) == 1

    operation = next(item for item in store.operations_for_ticker("SCMA") if item.operation == "delete_message")
    assert operation.payload["thread_id"] == "thread-1"
    assert operation.payload["message_id"] == "history-7"
    claim = store.claim_due_outbox(at())
    assert claim is not None
    store.complete_outbox(operation.id, claim.claim_token, {}, at())
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT deleted_at FROM history_events WHERE id = ?", (history_id,)).fetchone()[0]
    assert store.history_cleanup_count() == 0


def test_source_only_episode_rejects_factual_checkpoint(tmp_path) -> None:
    store = BoardStore(tmp_path / "board.sqlite3")
    episode = store.create_episode("SCMA", "source", "SCMA: source context", at())
    checkpoint = Checkpoint.market(
        session_date="2026-09-19",
        checked_at="2026-09-19T16:30:00+07:00",
        close_price="230",
        state=MarketState.TP1_REACHED,
    )

    with pytest.raises(StoreBlockedError, match="primary"):
        store.record_checkpoint(episode.id, checkpoint)

    assert store.count_rows("checkpoints") == 0


def test_stale_claimant_cannot_complete_or_fail_reclaimed_outbox_work(tmp_path) -> None:
    store = BoardStore(tmp_path / "board.sqlite3")
    episode = store.create_episode("SCMA", "source", "SCMA: source context", at())
    operation = store.enqueue_outbox("create_thread", episode.id, {}, "create:SCMA", at())

    first_claim = store.claim_due_outbox(at())
    second_claim = store.claim_due_outbox(at(11))

    assert first_claim is not None
    assert second_claim is not None
    assert first_claim.id == second_claim.id == operation.id
    assert first_claim.claim_token != second_claim.claim_token

    with pytest.raises(StoreBlockedError, match="claim token"):
        store.complete_outbox(operation.id, first_claim.claim_token, {"thread_id": "old"}, at(11))
    with pytest.raises(StoreBlockedError, match="claim token"):
        store.fail_outbox(operation.id, first_claim.claim_token, "old worker", at(11))

    store.complete_outbox(operation.id, second_claim.claim_token, {"thread_id": "new"}, at(11))
    assert store.claim_due_outbox(at(59)) is None


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
    assert store.schema_version == 7

    connection = sqlite3.connect(path)
    assert connection.execute("SELECT event_key, ticker FROM source_events").fetchone() == (
        "phintraco:1444713822:33655",
        "SCMA",
    )
    connection.close()


def test_version_two_outbox_migrates_to_claim_tokens_without_reset(tmp_path) -> None:
    path = tmp_path / "board.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA user_version = 2;
        CREATE TABLE outbox (
            id INTEGER PRIMARY KEY,
            operation TEXT NOT NULL,
            episode_id INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            dedupe_key TEXT NOT NULL UNIQUE,
            attempts INTEGER NOT NULL,
            next_attempt_at TEXT NOT NULL,
            status TEXT NOT NULL,
            claimed_at TEXT,
            last_error TEXT,
            completion_json TEXT,
            completed_at TEXT
        );
        INSERT INTO outbox (
            operation, episode_id, payload_json, dedupe_key, attempts,
            next_attempt_at, status
        ) VALUES ('create_thread', 1, '{}', 'existing', 0,
                  '2026-09-19T09:05:00+07:00', 'pending');
        """
    )
    connection.close()

    store = BoardStore(path)

    assert store.schema_version == 7
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT dedupe_key, claim_token FROM outbox").fetchone() == (
        "existing",
        None,
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


def test_version_three_migration_preserves_event_plan_and_outbox(tmp_path) -> None:
    path = tmp_path / "board.sqlite3"
    original = BoardStore(path)
    event = example_buy_event()
    submitted = original.submit_event(event, at())
    with original.transaction() as tx:
        episode = tx.create_episode("SCMA", "primary", "SCMA: Buy", at())
        tx.replace_plan(episode.id, submitted.id, event, at())
        tx.enqueue_outbox("create_thread", episode.id, {"content": "preserved"}, "original", at())
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE source_events DROP COLUMN board_processed_at")
        connection.execute("PRAGMA user_version = 3")

    upgraded = BoardStore(path)

    assert upgraded.schema_version == 7
    assert upgraded.count_rows("source_events") == 1
    assert upgraded.active_plan(episode.id) == event
    assert upgraded.operations_for_ticker("SCMA")[0].payload == {"content": "preserved"}
    with upgraded.transaction() as tx:
        assert tx.event_processed(submitted.id) is False


def test_version_five_history_migration_preserves_rows_and_adds_chunk_identity(tmp_path) -> None:
    path = tmp_path / "board.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        PRAGMA user_version = 5;
        CREATE TABLE episodes (id INTEGER PRIMARY KEY);
        CREATE TABLE source_events (id INTEGER PRIMARY KEY);
        INSERT INTO episodes (id) VALUES (1);
        INSERT INTO source_events (id) VALUES (1);
        CREATE TABLE history_events (
            id INTEGER PRIMARY KEY,
            episode_id INTEGER NOT NULL REFERENCES episodes(id),
            source_event_id INTEGER REFERENCES source_events(id),
            material_payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            discord_message_id TEXT,
            UNIQUE(episode_id, material_payload)
        );
        INSERT INTO history_events
            (id, episode_id, source_event_id, material_payload, created_at, discord_message_id)
        VALUES (7, 1, 1, '> old history', '2026-09-19T02:05:00+00:00', 'message-7');
        """
    )
    connection.close()

    store = BoardStore(path)

    assert store.schema_version == 7
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT material_payload, discord_message_id, history_key FROM history_events"
        ).fetchone() == ("> old history", "message-7", "legacy:7")


def test_failed_predecessor_blocks_its_episode_but_not_other_tickers(tmp_path) -> None:
    store = BoardStore(tmp_path / "board.sqlite3")
    first = store.create_episode("SCMA", "primary", "SCMA: Buy", at())
    second = store.create_episode("KPIG", "source", "KPIG source", at())
    create = store.enqueue_outbox("create_thread", first.id, {}, "first-create", at())
    store.enqueue_outbox("edit_starter", first.id, {}, "first-edit", at())
    independent = store.enqueue_outbox("create_thread", second.id, {}, "second-create", at())
    claim = store.claim_due_outbox(at())
    assert claim.id == create.id
    store.fail_outbox(claim.id, claim.claim_token, "retry", at())
    assert store.claim_due_outbox(at()).id == independent.id
    assert store.claim_due_outbox(at()) is None


def test_claim_order_compares_absolute_times_for_existing_timezone_offsets(tmp_path) -> None:
    store = BoardStore(tmp_path / "board.sqlite3")
    episode = store.create_episode("SCMA", "source", "SCMA source", at())
    operation = store.enqueue_outbox("create_thread", episode.id, {}, "offset", at())
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE outbox SET next_attempt_at = ? WHERE id = ?", (at().isoformat(), operation.id))
    utc_now = datetime.fromisoformat("2026-09-19T02:05:00+00:00")
    assert store.claim_due_outbox(utc_now).id == operation.id


def test_backoff_caps_at_sixty_minutes_and_completed_work_is_not_claimed(tmp_path) -> None:
    store = BoardStore(tmp_path / "board.sqlite3")
    episode = store.create_episode("SCMA", "source", "SCMA: source context", at())
    operation = store.enqueue_test_operation("create_thread", episode.id, at())
    claim = store.claim_due_outbox(at())
    assert claim is not None
    assert claim.claim_token is not None

    for expected_delay in (1, 2, 4, 8, 15, 30, 60, 60):
        store.fail_outbox(operation.id, claim.claim_token, "temporary", at())
        assert store.due_at(operation.id) == at() + timedelta(minutes=expected_delay)
        claim = store.claim_due_outbox(store.due_at(operation.id))
        assert claim is not None
        assert claim.claim_token is not None

    store.complete_outbox(operation.id, claim.claim_token, {"thread_id": "123"}, at())
    assert store.claim_due_outbox(at(59)) is None
