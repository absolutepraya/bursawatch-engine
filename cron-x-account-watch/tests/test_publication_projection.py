from datetime import UTC, datetime, timedelta

import pytest

import publication_projection as projection
import scan
import state
from bursawatch_discord_delivery.models import Attachment, OperationIntent, OperationReceipt
from models import DiscordChannel, PostKind, Profile, SourcePost, ThreadHandling


NOW = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)


def _profile() -> Profile:
    return Profile(
        id="marketwriter",
        enabled=True,
        profile_url="https://x.com/marketwriter",
        handle="marketwriter",
        display_name="Market Writer",
        twitter_emoji="<:twitter:1531672630602498129>",
        emoji="<:marketwriter:1531673483459821729>",
        discord_channels=(DiscordChannel("id_stocks_news", "1531655369884045382", "IDX news"),),
        forward_normal_post=True,
        forward_quote_post=True,
        forward_reply=False,
        forward_repost=False,
        forward_media=True,
        enable_llm_title=True,
        enable_llm_summary=True,
        enable_llm_routing=True,
        enable_llm_relevance_filter=True,
        relevance_scope="stock_market",
        additional_prompt_instruction="",
        max_items_per_poll=50,
        thread_handling=ThreadHandling("disabled", 1, 60, 1),
    )


def _leg(number: int, *, text: str | None = "META: Revenue outlook improved", attachment: bool = False) -> dict:
    attachments = (Attachment("chart.jpg", "image/jpeg", b"chart bytes"),) if attachment else ()
    operation = OperationIntent(
        key=f"bursawatch-x-account-watch:{number:064x}",
        kind="channel_message_create",
        ordering_key="channel:1531655369884045382",
        target={"channel_id": "1531655369884045382"},
        payload={"content": text or "", "allowed_mentions": {"parse": []}},
        attachments=attachments,
    )
    receipt = OperationReceipt(
        id=f"operation-{number}",
        key=operation.key,
        digest=operation.digest,
        status="delivered",
        receipt={"channel_id": "1531655369884045382", "message_id": f"{1531655369884045400 + number}"},
    )
    leg = projection.confirmed_leg(operation, receipt, text=text)
    return leg


def _event(*, route="id_stocks_news", post_id="101", thread_root_id="101", legs=None, replacement_of=None):
    post = SourcePost(
        "marketwriter",
        post_id,
        f"https://x.com/marketwriter/status/{post_id}",
        NOW - timedelta(minutes=2),
        "META reports stronger revenue.",
        PostKind.NORMAL,
        None,
        None,
        (),
        (),
    )
    return {
        "profile_id": "marketwriter",
        "post_id": post_id,
        "thread_root_id": thread_root_id,
        "post": state.serialize_post(post),
        "thread_posts": [state.serialize_post(post)],
        "route": route,
        "title": "META: Pendapatan kuartal melampaui perkiraan",
        "summary": "*(Ringkasan)* Pendapatan META meningkat.",
        "source_event_key": f"source-{post_id}",
        "source_catalog_revision": 3,
        "replacement_of": replacement_of or [],
        "publication_legs": legs if legs is not None else [_leg(1)],
    }


@pytest.mark.parametrize(
    ("route", "expected_type"),
    [
        ("id_stocks_news", "idx_company_news"),
        ("us_stocks_news", "us_company_news"),
        ("macro_news", "macro_news"),
        ("id_stocks_swing", "swing_context"),
    ],
)
def test_routes_keep_news_types_and_swing_is_context_not_a_broker_plan(monkeypatch, route, expected_type):
    monkeypatch.setenv("BURSAWATCH_X_ACCOUNT_WATCH_PUBLICATION_ENABLED", "1")
    value = state.new_state()
    item = _event(route=route)

    assert projection.record_confirmed_event(value, item, _profile(), NOW)
    record = next(iter(value["publication_projection"]["records"].values()))["snapshot"]

    assert record["type"] == expected_type
    assert record["broker_levels"] is None
    assert record["ticker"] == "META"


def test_projection_waits_until_every_required_delivery_receipt_is_present(monkeypatch):
    monkeypatch.setenv("BURSAWATCH_X_ACCOUNT_WATCH_PUBLICATION_ENABLED", "1")
    value = state.new_state()
    item = _event(legs=[_leg(1), {**_leg(2), "status": "pending"}])

    with pytest.raises(projection.IncompletePublication, match="receipt"):
        projection.record_confirmed_event(value, item, _profile(), NOW)
    assert value["publication_projection"]["records"] == {}


def test_projection_retains_every_leg_above_the_previous_ten_leg_bound(monkeypatch):
    monkeypatch.setenv("BURSAWATCH_X_ACCOUNT_WATCH_PUBLICATION_ENABLED", "1")
    value = state.new_state()
    legs = [_leg(number) for number in range(1, 18)]

    assert projection.record_confirmed_event(value, _event(legs=legs), _profile(), NOW)
    snapshot = next(iter(value["publication_projection"]["records"].values()))["snapshot"]

    assert snapshot["required_operation_keys"] == [leg["operation_key"] for leg in legs]
    assert snapshot["legs"] == [
        {key: leg[key] for key in ("operation_key", "operation_digest", "receipt_operation_id", "destination", "receipt_id", "status", "message_url", "text", "attachments")}
        for leg in legs
    ]


def test_confirmed_edit_adds_a_later_version_under_the_same_publication_identity(monkeypatch):
    monkeypatch.setenv("BURSAWATCH_X_ACCOUNT_WATCH_PUBLICATION_ENABLED", "1")
    value = state.new_state()
    first = _event()
    projection.record_confirmed_event(value, first, _profile(), NOW)
    second = _event(post_id="102", thread_root_id="101", legs=[_leg(2)], replacement_of=["marketwriter:101"])

    projection.record_confirmed_event(value, second, _profile(), NOW + timedelta(minutes=1))
    snapshots = [record["snapshot"] for record in value["publication_projection"]["records"].values()]

    assert [item["version"] for item in sorted(snapshots, key=lambda item: item["version"])] == [1, 2]
    assert {item["owner_key"] for item in snapshots} == {"x:marketwriter:101"}
    assert next(item for item in snapshots if item["version"] == 2)["supersedes_version"] == 1


def test_retry_of_board_pending_event_does_not_create_another_projection_version(monkeypatch):
    monkeypatch.setenv("BURSAWATCH_X_ACCOUNT_WATCH_PUBLICATION_ENABLED", "1")
    value = state.new_state()
    item = _event()

    assert projection.record_confirmed_event(value, item, _profile(), NOW)
    assert not projection.record_confirmed_event(value, item, _profile(), NOW + timedelta(minutes=5))
    assert len(value["publication_projection"]["records"]) == 1


def test_projection_outage_retries_saved_snapshot_without_discord_operations(monkeypatch):
    monkeypatch.setenv("BURSAWATCH_X_ACCOUNT_WATCH_PUBLICATION_ENABLED", "1")
    value = state.new_state()
    projection.record_confirmed_event(value, _event(legs=[_leg(1), _leg(2, text=None, attachment=True)]), _profile(), NOW)
    owner_key, saved = projection.pending_publication_intents(value)[0]
    discord_operation_count = 2

    class OfflineClient:
        def __init__(self):
            self.submitted = []

        def submit(self, snapshot):
            self.submitted.append(snapshot)
            raise OSError("projection offline")

        def checkpoint(self, _comparison):
            raise OSError("projection offline")

    client = OfflineClient()
    first = projection.drain(value, NOW, client=client)
    second = projection.drain(value, NOW + timedelta(minutes=1), client=client)

    assert first == second == {"accepted": 0, "pending": 1}
    assert client.submitted == [saved, saved]
    assert discord_operation_count == 2
    assert projection.pending_publication_intents(value) == [(owner_key, saved)]


def test_pruning_delivery_history_keeps_pending_projection_and_checkpoint_boundary(monkeypatch):
    monkeypatch.setenv("BURSAWATCH_X_ACCOUNT_WATCH_PUBLICATION_ENABLED", "1")
    value = state.new_state()
    projection.record_confirmed_event(value, _event(), _profile(), NOW - timedelta(days=100))
    before = projection.checkpoint_comparison(value, NOW)

    state.prune_deliveries(value, NOW)
    after = projection.checkpoint_comparison(value, NOW)

    assert value["publication_projection"]["records"]
    assert after == before
    assert after["accepted_through_at"] is None
    assert after["outstanding_count"] == 1


def test_projection_is_disabled_without_owner_flag(monkeypatch):
    monkeypatch.delenv("BURSAWATCH_X_ACCOUNT_WATCH_PUBLICATION_ENABLED", raising=False)
    value = state.new_state()

    assert not projection.record_confirmed_event(value, _event(), _profile(), NOW)
    assert "publication_projection" not in value


def test_scanner_persists_confirmed_receipt_before_removing_x_event(tmp_path, monkeypatch):
    monkeypatch.setenv("BURSAWATCH_X_ACCOUNT_WATCH_PUBLICATION_ENABLED", "1")
    profile = _profile()
    item = _event()
    item.update({
        "text_index": 0,
        "media_index": 0,
        "text_message_ids": [],
        "media_message_ids": [],
        "media_skipped_urls": [],
        "media_errors": [],
        "publication_legs": [],
        "updated_tweet": False,
        "agent_phase": "ready",
        "board_phase": "pending",
    })
    value = state.new_state()
    value["outbox"].append(item)
    storage = tmp_path / "state.json"
    rendered = []

    def post_text(content, channel, _dry_run, nonce_value):
        rendered.append(content)
        operation = OperationIntent(
            key=scan.discord.operation_key_for_nonce(nonce_value),
            kind="channel_message_create",
            ordering_key=f"channel:{channel}",
            target={"channel_id": channel},
            payload={"content": content, "allowed_mentions": {"parse": []}},
        )
        receipt = OperationReceipt(
            id="operation-confirmed",
            key=operation.key,
            digest=operation.digest,
            status="delivered",
            receipt={"channel_id": channel, "message_id": "1531655369884045411"},
        )
        return "1531655369884045411", operation, receipt

    monkeypatch.setattr(scan.discord, "post_text_with_receipt", post_text)

    completed = scan._deliver(
        value,
        {profile.id: profile},
        0,
        False,
        storage,
        scan.RunStats(),
        NOW,
    )

    assert completed is True
    saved = state.load_state(storage)
    assert saved["outbox"] == []
    record = next(iter(saved["publication_projection"]["records"].values()))
    assert record["snapshot"]["legs"][0]["text"] == rendered[0]
    assert record["snapshot"]["required_operation_keys"] == [record["snapshot"]["legs"][0]["operation_key"]]
