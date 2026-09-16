from dataclasses import replace
from datetime import datetime, timedelta
import json
import sqlite3
from unittest.mock import Mock

import pytest

from calendar import sessions_ago
from conftest import example_buy_event, social_event
from discord_forum import DiscordForumClient, DiscordForumError
from engine import BoardEngine, source_outcome_state
from models import Checkpoint, MarketState, PlanLevels, SourceEvent
from render import discord_length, render_source_replies, render_source_reply
from store import BoardStore, StoreBlockedError
from tags import CHART_CONTEXT, LEGACY_SOURCE_PLAN, SUPPORTING_SETUP


def at(value="2026-09-19T09:05:00+07:00") -> datetime:
    return datetime.fromisoformat(value)


@pytest.fixture
def engine(tmp_path):
    client = Mock(spec=DiscordForumClient)
    client.execute.side_effect = lambda op, payload: (
        {"thread_id": "123", "starter_message_id": "456"}
        if op == "create_thread" else {"message_id": "789"}
    )
    return BoardEngine(BoardStore(tmp_path / "board.sqlite3"), client)


def social(**changes):
    return replace(social_event("x:marketwriter:101", "KPIG", "KPIG: Wave IV menuju 97 sampai 108"), **changes)


def gtw(**changes):
    defaults = {
        "source": "kelas-investasi",
        "source_title": "Good to watch - KPIG #GTW",
        "source_url": "https://t.me/kelasinvestasiid/101",
        "all_content": "### <:kelasinvestasi:1> KPIG: Akumulasi kuat\n\n**Source status:** Good to watch",
        "media_path": "/tmp/gtw-chart.png",
    }
    defaults.update(changes)
    return replace(
        social_event("kelas-investasi:101:KPIG", "KPIG", "Good to watch - KPIG #GTW"),
        **defaults,
    )


def buy(**changes):
    return replace(example_buy_event(ticker="KPIG"), **changes)


def status(value, **changes):
    return replace(buy(), **{"kind": "status", "plan": None, "event_key": "phintraco:status:1", "source_status": value, **changes})


def operations(engine):
    return engine.store.operations_for_ticker("KPIG")


def test_social_event_creates_source_episode_and_normal_reply(engine):
    event = social(media_urls=("https://pbs.twimg.com/media/chart.png",))
    assert engine.submit(event, at()) == "board_submitted"
    episode = engine.store.active_episode("KPIG")
    assert (episode.lifecycle, episode.title) == ("source", event.source_title)
    assert (episode.lifecycle_tag, episode.market_tag) == (CHART_CONTEXT, None)
    assert [op.operation for op in operations(engine)] == ["create_thread"]
    assert operations(engine)[0].payload["tag_names"] == [CHART_CONTEXT]
    assert operations(engine)[0].payload["media_url"] == event.media_urls[0]
    assert operations(engine)[0].payload["content"] == render_source_reply(event)


def test_kelas_source_reply_chunks_are_durable_ordered_and_preserve_media(engine):
    content = "source analysis " * 350
    event = SourceEvent.from_json(
        {
            "event_key": "kelas-investasi:101:RAJA",
            "source": "kelas-investasi",
            "kind": "social",
            "ticker": "RAJA",
            "published_at": "2026-09-19T09:05:00+07:00",
            "source_url": "https://t.me/kelasinvestasiid/101",
            "all_content": content,
            "source_title": "Good to watch - RAJA #GTW",
            "source_status": None,
            "plan": None,
            "media_path": "/tmp/raja-header.jpg",
            "media_urls": [],
        }
    )

    assert engine.submit(event, at()) == "board_submitted"

    replies = [item for item in engine.store.operations_for_ticker("RAJA") if item.operation == "post_source_reply"]
    assert len(replies) > 1
    assert all(len(item.payload["content"]) <= 2000 for item in replies)
    assert "".join(item.payload["content"] for item in replies) == "".join(render_source_replies(event)[1:])
    assert all(item.payload["media"] is None for item in replies)
    assert len({item.payload["nonce_value"] for item in replies}) == len(replies)


def test_gtw_source_event_uses_supporting_setup_tag(engine):
    engine.submit(gtw(), at())
    episode = engine.store.active_episode("KPIG")
    assert episode.lifecycle_tag == SUPPORTING_SETUP
    assert operations(engine)[0].payload["tag_names"] == [SUPPORTING_SETUP]


def test_gtw_is_stronger_than_existing_x_context(engine):
    engine.submit(social(), at())
    engine.submit(gtw(), at("2026-09-20T09:05:00+07:00"))
    episode = engine.store.active_episode("KPIG")
    assert episode.lifecycle_tag == SUPPORTING_SETUP
    patches = [op for op in operations(engine) if op.operation == "patch_thread"]
    assert patches[-1].payload["tag_names"] == [SUPPORTING_SETUP]


def test_higher_tier_replaces_chart_starter_and_preserves_one_normal_history_reply(engine):
    chart = social(
        all_content=(
            "### <:twitter:1> KPIG: Chart view\n"
            "-# <:marketwriter:2> Market Writer\n\n"
            "*(Ringkasan)* Chart context.\n\n"
            "**Status date:** 19 Sep 2026 09:05 WIB\n\n"
            "[View on X](<https://x.com/marketwriter/status/101>)"
        ),
        media_urls=("https://pbs.twimg.com/media/chart.png",),
    )
    stronger = gtw(media_path=None)
    engine.submit(chart, at())
    engine.submit(stronger, at("2026-09-20T09:05:00+07:00"))

    episode = engine.store.active_episode("KPIG")
    with engine.store.transaction() as tx:
        assert tx.starter_source_event(episode.id).event_key == stronger.event_key
    ops = operations(engine)
    assert [op.operation for op in ops] == [
        "create_thread", "edit_starter", "post_source_reply", "patch_thread"
    ]
    assert ops[0].payload["content"] == render_source_reply(chart)
    assert ops[0].payload["media_url"] == chart.media_urls[0]
    assert ops[1].payload["content"] == render_source_reply(stronger)
    assert ops[2].payload["content"] == render_source_reply(chart)
    assert not ops[2].payload["content"].startswith("> ")
    assert ":history:" in ops[2].payload["nonce_value"]
    assert ops[3].payload["name"] == stronger.source_title


def test_newer_same_tier_source_updates_thread_title_and_starter(engine):
    first = social(source_title="KPIG: First chart view")
    newer = social(
        event_key="x:marketwriter:102",
        source_title="KPIG: Newer chart view",
        published_at=at("2026-09-20T09:05:00+07:00"),
    )
    engine.submit(first, at())
    engine.submit(newer, at("2026-09-20T09:05:00+07:00"))

    episode = engine.store.active_episode("KPIG")
    assert episode.title == newer.source_title
    patch = [op for op in operations(engine) if op.operation == "patch_thread"][-1]
    assert patch.payload["name"] == newer.source_title


def test_tag_migration_rewrites_legacy_source_tag_and_queues_patch(engine):
    engine.submit(social(), at())
    engine.drain(now=at())
    legacy = replace(engine.store.active_episode("KPIG"), lifecycle_tag=LEGACY_SOURCE_PLAN)
    with engine.store.transaction() as tx:
        tx.update_episode(legacy)

    result = engine.schedule_tag_migration(at("2026-09-20T09:00:00+07:00"))
    assert result == {"scheduled": 1, "unchanged": 0, "blocked": 0}
    assert engine.store.active_episode("KPIG").lifecycle_tag == CHART_CONTEXT
    patch = [op for op in operations(engine) if op.operation == "patch_thread"][-1]
    assert patch.payload["tag_names"] == [CHART_CONTEXT]


def test_format_migration_rewrites_existing_starter_and_source_reply(engine):
    legacy = (
        "### <:phintraco:1531272488645038091> HOLD: **KPIG**\n\n"
        "**Status:** On track<:hold:1531284248235868333>\n"
        "**Status date:** Fri, Sep 11 2026, 10:13 WIB\n"
        "**Source:** [Phintraco Sekuritas](<https://t.me/phintraprofits/33656>) | "
        "Alrich Paskalis T, Investment Advisor"
    )
    engine.submit(buy(media_path="/tmp/chart.jpg"), at())
    event = replace(
        status("On track", event_key="phintraco:status:legacy", source_url="https://t.me/phintraprofits/33656"),
        all_content=legacy,
    )
    engine.submit(event, at())
    engine.drain(now=at())
    source_reply = next(op for op in operations(engine) if op.operation == "post_source_reply")
    with sqlite3.connect(engine.store.path) as connection:
        # The public operation object exposes the parsed payload, so update the
        # durable row directly to model the old message already on Discord.
        connection.execute(
            "UPDATE source_events SET all_content = ? WHERE event_key = ?",
            (legacy, event.event_key),
        )
        connection.execute(
            "UPDATE outbox SET payload_json = ? WHERE id = ?",
            (json.dumps({**source_reply.payload, "content": legacy}), source_reply.id),
        )

    scheduled = engine.schedule_format_migration(at())
    assert scheduled == 2
    migrations = [
        op for op in operations(engine)
        if op.operation == "edit_starter"
        and op.payload.get("nonce_value", "").startswith("format-migration:v")
    ]
    assert len(migrations) == 2
    reply_migration = next(
        op for op in migrations
        if op.payload.get("target_message_id") == "789"
        and op.payload.get("nonce_value", "").startswith("format-migration:v5:")
    )
    assert "KPIG: On track" in reply_migration.payload["content"]
    assert "On track <:hold:1531284248235868333>" in reply_migration.payload["content"]


def test_format_migration_moves_legacy_source_card_into_starter(engine):
    event = social()
    engine.submit(event, at())
    engine.drain(now=at())
    episode = engine.store.active_episode("KPIG")
    with engine.store.transaction() as tx:
        tx.update_episode(replace(episode, starter_source_event_id=None))
        tx.enqueue_outbox(
            "post_source_reply",
            episode.id,
            {"content": "legacy source reply", "nonce_value": f"event:{event.event_key}:post_source_reply"},
            f"event:{event.event_key}:post_source_reply",
            at(),
        )
    engine.drain(now=at())

    scheduled = engine.schedule_format_migration(at("2026-09-20T09:00:00+07:00"))
    assert scheduled == 2
    migration = next(
        op for op in operations(engine)
        if op.operation == "edit_starter" and op.payload["nonce_value"].startswith("format-migration:v6:source:")
    )
    assert migration.payload["content"] == render_source_reply(event)
    deletion = next(op for op in operations(engine) if op.operation == "delete_message")
    assert deletion.payload["message_id"] == "789"


def test_buy_promotes_without_reposting_non_gtw_social_reply(engine):
    engine.submit(social(), at())
    engine.drain(now=at())
    engine.submit(buy(media_path="/tmp/original.png"), at("2026-09-22T09:05:00+07:00"))
    assert [op.operation for op in operations(engine)] == [
        "create_thread", "edit_starter", "post_source_reply", "patch_thread"
    ]
    assert operations(engine)[1].payload["chart"] is None
    assert operations(engine)[3].payload["tag_names"] == ["Primary plan"]
    assert engine.store.active_episode("KPIG").title == "KPIG: Buy"


def test_buy_promotes_and_preserves_latest_source_starter_once(engine):
    source = gtw()
    engine.submit(source, at())
    newer_source = gtw(
        event_key="kelas-investasi:102:KPIG",
        published_at=at("2026-09-20T09:05:00+07:00"),
        source_url="https://t.me/kelasinvestasiid/102",
        all_content="### <:kelasinvestasi:1> KPIG: Breakout watch\n\n**Source status:** Good to watch",
        media_path="/tmp/gtw-chart-new.png",
    )
    engine.submit(newer_source, at("2026-09-20T09:06:00+07:00"))
    engine.drain(now=at())

    promotion = buy(media_path="/tmp/phintraco-chart.png")
    assert engine.submit(promotion, at("2026-09-22T09:05:00+07:00")) == "board_submitted"

    replies = [op for op in operations(engine) if op.operation == "post_source_reply"]
    assert len(replies) == 2
    history = replies[-1]
    assert history.payload["content"] == render_source_reply(newer_source)
    assert history.payload["media"] is None
    assert ":history:" in history.payload["nonce_value"]
    assert engine.submit(promotion, at("2026-09-22T09:05:00+07:00")) == "board_duplicate"
    assert len([op for op in operations(engine) if op.operation == "post_source_reply"]) == 2


@pytest.mark.parametrize("lifecycle", ["source", "primary"])
@pytest.mark.parametrize("days_before, same_episode", [(0, True), (1, False)])
def test_twenty_session_boundary_uses_event_date(engine, lifecycle, days_before, same_episode):
    incoming = at("2026-10-20T09:05:00+07:00")
    boundary = sessions_ago(incoming.date(), 20) - timedelta(days=days_before)
    first_time = datetime.combine(boundary, incoming.timetz())
    first = social() if lifecycle == "source" else buy()
    engine.submit(replace(first, published_at=first_time), first_time)
    prior = engine.store.active_episode("KPIG")
    engine.submit(buy(event_key="new-buy", published_at=incoming), incoming + timedelta(days=100))
    active = engine.store.active_episode("KPIG")
    assert (active.id == prior.id) is same_episode
    assert active.lifecycle == "primary"
    if not same_episode:
        assert engine.store.episode(prior.id).closed_at is not None
        assert not any(op.payload.get("archived") for op in operations(engine))


def test_replacement_retains_replies_and_records_prior_url(engine):
    engine.submit(buy(media_path="/tmp/old.png"), at())
    engine.submit(social(), at())
    engine.submit(buy(event_key="new-buy", source_url="https://t.me/phintraprofits/777", media_path="/tmp/new.png"), at())
    ops = operations(engine)
    assert [op.operation for op in ops] == ["create_thread", "post_source_reply", "edit_starter", "post_source_reply", "patch_thread"]
    edit = next(op for op in ops if op.operation == "edit_starter")
    assert edit.payload["chart"] is None
    assert not any("Replacement" in op.payload.get("content", "") for op in ops)
    assert engine.store.count_rows("plans") == 2


def test_duplicate_event_is_noop_and_interrupted_intake_resumes(engine):
    event = buy()
    engine.store.submit_event(event, at())
    assert engine.submit(event, at()) == "board_submitted"
    before = operations(engine)
    assert engine.submit(event, at()) == "board_duplicate"
    assert operations(engine) == before
    assert engine.store.count_rows("plans") == 1


def test_transition_failure_rolls_back_and_retries(engine, monkeypatch):
    original = engine.store._enqueue_outbox
    monkeypatch.setattr(engine.store, "_enqueue_outbox", Mock(side_effect=RuntimeError("abort")))
    with pytest.raises(RuntimeError, match="abort"):
        engine.submit(buy(), at())
    assert engine.store.active_episode("KPIG") is None
    assert engine.store.count_rows("plans") == 0
    monkeypatch.setattr(engine.store, "_enqueue_outbox", original)
    assert engine.submit(buy(), at()) == "board_submitted"


@pytest.mark.parametrize("has_source", [False, True])
def test_status_without_primary_is_ignored(engine, has_source):
    if has_source:
        engine.submit(social(), at())
    before = operations(engine)
    assert engine.submit(status("HOLD"), at()) == "board_ignored"
    assert operations(engine) == before
    assert engine.submit(status("HOLD"), at()) == "board_duplicate"


def test_hold_preserves_plan_chart_and_factual_tag(engine):
    event = buy(plan=PlanLevels("208 to 212", "<200", ("230", "240")), media_path="/tmp/chart.png")
    engine.submit(event, at())
    engine.submit(status("First target achieved"), at())
    engine.submit(status("HOLD", event_key="hold"), at())
    episode = engine.store.active_episode("KPIG")
    assert episode.market_tag == "TP1 reached"
    assert engine.store.active_plan(episode.id).source_status == "HOLD"
    edits = [op for op in operations(engine) if op.operation == "edit_starter"]
    assert "**Source status:** HOLD" in edits[-1].payload["content"]
    assert "**Entry:** 208 to 212" in edits[-1].payload["content"]
    assert edits[-1].payload["chart"] is None
    patches = [op for op in operations(engine) if op.operation == "patch_thread"]
    assert patches[-1].payload["tag_names"] == ["Primary plan", "TP1 reached"]


@pytest.mark.parametrize("text,state", [
    ("Stop-loss hit", MarketState.STOP_LOSS_BREACHED),
    ("All targets achieved", MarketState.TP6_REACHED),
    ("First target achieved", MarketState.TP1_REACHED),
    ("Second target achieved", MarketState.TP2_REACHED),
    ("Third target achieved", MarketState.TP3_REACHED),
    ("Fourth target achieved", MarketState.TP4_REACHED),
    ("Fifth target achieved", MarketState.TP5_REACHED),
    ("Sixth target achieved", MarketState.TP6_REACHED),
    ("6th target achieved", MarketState.TP6_REACHED),
    ("7th target achieved", MarketState.TP6_REACHED),
    ("First target 230 achieved", MarketState.TP1_REACHED),
    ("HOLD", None), ("Target 1 might be achieved", None),
])
def test_direct_outcome_mapping(text, state):
    plan = buy(plan=PlanLevels("1", "0", ("2", "3", "4", "5", "6", "7", "8")))
    assert source_outcome_state(status(text), plan) == state


@pytest.mark.parametrize("text", ["Stop-loss hit", "All targets achieved", "First target achieved"])
def test_terminal_outcome_resolves_once_and_later_buy_starts_fresh(engine, text):
    engine.submit(buy(media_path="/tmp/chart.png"), at())
    prior = engine.store.active_episode("KPIG")
    engine.submit(status(text, kind="reminder"), at())
    resolved = engine.store.episode(prior.id)
    assert resolved.lifecycle == "resolved"
    assert resolved.lifecycle_tag == "Resolved"
    assert resolved.market_tag in {"TP1 reached", "Stop-loss breached"}
    assert engine.store.active_episode("KPIG") is None
    before = operations(engine)
    assert engine.submit(status("HOLD", event_key="late-hold"), at()) == "board_ignored"
    assert operations(engine) == before
    assert not any("Resolved:" in op.payload.get("content", "") for op in before)
    assert not any(op.operation == "post_history_reply" for op in before)
    assert [op for op in before if op.operation == "patch_thread"][-1].payload["tag_names"] == ["Resolved", resolved.market_tag]
    assert not any(op.payload.get("archived") for op in before)
    with pytest.raises(StoreBlockedError, match="active primary"):
        engine.store.record_checkpoint(prior.id, Checkpoint.market(session_date="2026-09-19", checked_at=at().isoformat(), close_price="230", state=MarketState.TP1_REACHED))
    engine.submit(buy(event_key="later-buy"), at())
    assert engine.store.active_episode("KPIG").id != prior.id


def test_drain_persists_ids_and_does_not_overtake_failed_work(engine):
    engine.submit(social(), at())
    engine.client.execute.side_effect = DiscordForumError("temporary")
    assert engine.drain(now=at()) == 0
    assert operations(engine)[0].attempts == 1
    assert engine.drain(now=at()) == 0
    assert engine.client.execute.call_count == 1
    engine.client.execute.side_effect = lambda op, payload: {"thread_id": "123", "starter_message_id": "456"} if op == "create_thread" else {"message_id": "789"}
    assert engine.drain(now=at() + timedelta(minutes=1)) == 1
    episode = engine.store.active_episode("KPIG")
    assert (episode.thread_id, episode.starter_message_id) == ("123", "456")
    assert engine.client.execute.call_args.args[1]["content"] == render_source_reply(social())
    assert all(op.status == "complete" for op in operations(engine))


def test_drain_uses_persisted_work_after_restart(engine):
    engine.submit(buy(), at())
    engine.submit(status("HOLD"), at())
    restarted = BoardEngine(BoardStore(engine.store.path), engine.client)
    assert restarted.drain(now=at()) == 4
    edits = [call.args[1] for call in engine.client.execute.call_args_list if call.args[0] == "edit_starter"]
    assert edits[-1]["message_id"] == "456"
    assert engine.store.count_rows("history_events") == 0


def test_interrupted_replay_uses_original_payload_after_restart(engine):
    engine.store.submit_event(buy(), at())
    restarted = BoardEngine(BoardStore(engine.store.path), engine.client)
    changed = buy(ticker="SCMA", source_status="untrusted retry")
    restarted.submit(changed, at())
    assert restarted.store.active_episode("SCMA") is None
    active = restarted.store.active_episode("KPIG")
    assert restarted.store.active_plan(active.id).source_status == "New setup"


def test_status_preserves_existing_checkpoint_and_unavailable_display(engine):
    engine.submit(buy(), at())
    active = engine.store.active_episode("KPIG")
    engine.store.record_checkpoint(active.id, Checkpoint.market(
        session_date="2026-09-21", checked_at="2026-09-21T16:30:00+07:00",
        close_price="215", state=MarketState.ABOVE_ENTRY))
    engine.store.record_checkpoint(active.id, Checkpoint.unavailable_at(
        session_date="2026-09-22", checked_at="2026-09-22T16:30:00+07:00"))
    engine.submit(status("HOLD"), at("2026-09-22T17:00:00+07:00"))
    card = next(op.payload["content"] for op in reversed(operations(engine)) if op.operation == "edit_starter")
    assert "**Market checkpoint:** Market check unavailable" in card
    assert "**Closing price:** Rp215" in card
    assert "**Last checked:** 21 Sep 2026 16:30 WIB" in card


def test_distinct_unchanged_status_posts_source_without_quoted_transition(engine):
    engine.submit(buy(), at())
    engine.submit(status("HOLD"), at())
    before = engine.store.count_rows("history_events")
    engine.submit(status("HOLD", event_key="another-hold", source_url="https://t.me/phintraprofits/999"), at())
    assert engine.store.count_rows("history_events") == before
    replies = [op for op in operations(engine) if op.operation == "post_source_reply"]
    assert len(replies) == 2
    assert "https://t.me/phintraprofits/999" in replies[-1].payload["content"]


def test_long_source_status_is_chunked_without_synthetic_history(engine):
    engine.submit(buy(), at())
    long_status = "Source status " + ("📈 status detail " * 500)
    update = status(long_status, event_key="long-status")
    engine.submit(replace(update, all_content=long_status), at())

    histories = [op for op in operations(engine) if op.operation == "post_history_reply"]
    replies = [op for op in operations(engine) if op.operation == "post_source_reply"]
    assert histories == []
    assert len(replies) > 1
    assert all(discord_length(op.payload["content"]) <= 2000 for op in replies)
    assert all(not op.payload["content"].startswith("> ") for op in replies)
    assert any("Source status" in op.payload["content"] for op in replies)
    assert engine.store.pending_outbox_count() == len(operations(engine))
    engine.drain(now=at())
    engine.submit(status("HOLD", event_key="after-long-status"), at())
    engine.drain(now=at())
    assert engine.store.pending_outbox_count() == 0


def test_replacement_clears_factual_tag(engine):
    engine.submit(buy(plan=PlanLevels("208 to 212", "<200", ("230", "240"))), at())
    engine.submit(status("First target achieved"), at())
    engine.submit(buy(event_key="replacement"), at())
    active = engine.store.active_episode("KPIG")
    assert active.market_tag is None
    patch = next(op for op in reversed(operations(engine)) if op.operation == "patch_thread")
    assert patch.payload["tag_names"] == ["Primary plan"]


def test_replacement_status_does_not_restore_prior_plan_checkpoints(engine):
    engine.submit(buy(), at())
    active = engine.store.active_episode("KPIG")
    engine.store.record_checkpoint(active.id, Checkpoint.market(
        session_date="2026-09-21", checked_at="2026-09-21T16:30:00+07:00",
        close_price="215", state=MarketState.ABOVE_ENTRY))
    engine.submit(buy(event_key="replacement"), at("2026-09-22T09:00:00+07:00"))
    engine.submit(status("HOLD"), at("2026-09-22T10:00:00+07:00"))
    card = next(op.payload["content"] for op in reversed(operations(engine)) if op.operation == "edit_starter")
    assert "**Closing price:**" not in card


def test_engine_intents_execute_through_real_client_in_no_post_mode(engine, monkeypatch):
    request = Mock(side_effect=AssertionError("HTTP must not run"))
    monkeypatch.setattr("discord_forum.requests.request", request)
    engine.client = DiscordForumClient(no_post=True)
    engine.submit(social(), at())
    engine.submit(buy(), at())
    engine.submit(status("Stop-loss hit"), at())
    assert engine.drain(now=at()) == 7
    assert all(op.status == "complete" for op in operations(engine))
    request.assert_not_called()


def test_illustrated_buy_replaced_by_chartless_buy_clears_old_attachment(engine, monkeypatch):
    engine.submit(buy(media_path="/tmp/old-chart.png"), at())
    engine.drain(now=at())
    engine.submit(buy(event_key="chartless-replacement", media_path=None), at())
    response = Mock(status_code=200, ok=True)
    response.json.return_value = {"attachments": [{"id": "42", "filename": "old-chart.png"}]}
    request = Mock(return_value=response)
    monkeypatch.setattr("discord_forum.requests.request", request)
    engine.client = DiscordForumClient(token="test-token", no_post=False)

    assert engine.drain(now=at(), limit=1) == 1

    request.assert_called_once()
    assert request.call_args.args[0] == "PATCH"
    assert request.call_args.kwargs["json"]["attachments"] == []


def test_six_target_all_targets_confirmation_resolves_with_tp6_tag(engine):
    event = buy(plan=PlanLevels("208 to 212", "<200", ("230", "240", "250", "260", "270", "280")))
    engine.submit(event, at())
    prior = engine.store.active_episode("KPIG")
    engine.submit(status("Fifth target achieved"), at())
    assert engine.store.active_episode("KPIG").lifecycle == "primary"

    engine.submit(status("All targets achieved", event_key="all-targets", kind="reminder"), at())

    assert engine.store.active_episode("KPIG") is None
    resolved = engine.store.episode(prior.id)
    assert (resolved.lifecycle, resolved.lifecycle_tag, resolved.market_tag) == ("resolved", "Resolved", "TP6 reached")
    patch = next(op for op in reversed(operations(engine)) if op.operation == "patch_thread")
    assert patch.payload["tag_names"] == ["Resolved", "TP6 reached"]
    edit = next(op for op in reversed(operations(engine)) if op.operation == "edit_starter")
    assert "**Target 6:** 280" in edit.payload["content"]
    assert "**Source status:** All targets achieved" in edit.payload["content"]
    assert engine.store.active_plan(prior.id) is None
