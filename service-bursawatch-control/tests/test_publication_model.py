from __future__ import annotations

from copy import deepcopy

import pytest

from control_plane.publication_model import validate_publication


OWNER = "bursawatch-tg-market-news"


def publication(**changes):
    value = {
        "api_version": 1,
        "owner_key": "source:synthetic:1",
        "version": 1,
        "supersedes_version": None,
        "type": "idx_company_news",
        "route": "id_stocks_news",
        "source_event_key": "synthetic-event-1",
        "source_name": "Synthetic publisher",
        "source_url": "https://example.test/story/1",
        "source_published_at": "2026-09-29T07:00:00+00:00",
        "market_data_as_of": None,
        "delivery_confirmed_at": "2026-09-29T07:02:00+00:00",
        "title": "Synthetic company update",
        "ticker": "TEST",
        "broker_levels": None,
        "parent_publication_id": None,
        "board_episode_id": None,
        "config_revision": 2,
        "renderer_version": "news-renderer-v1",
        "source_version": "synthetic-source-v1",
        "required_operation_keys": ["synthetic-delivery-1"],
        "legs": [{
            "operation_key": "synthetic-delivery-1",
            "operation_digest": "a" * 64,
            "receipt_operation_id": "synthetic-operation-id",
            "destination": "123456789012345678",
            "receipt_id": "987654321098765432",
            "status": "delivered",
            "message_url": "https://discord.com/channels/123456789012345678/123456789012345678/987654321098765432",
            "text": "Exact synthetic rendered text",
            "attachments": [],
        }],
    }
    value.update(changes)
    return value


def test_partial_leg_is_not_published():
    value = publication()
    pending = deepcopy(value["legs"][0])
    pending["operation_key"] = "synthetic-delivery-2"
    pending["status"] = "pending"
    value["required_operation_keys"].append("synthetic-delivery-2")
    value["legs"].append(pending)
    with pytest.raises(ValueError, match="delivery leg"):
        validate_publication(value, OWNER)


def test_omitted_required_leg_and_unbound_receipt_link_fail():
    value = publication(required_operation_keys=["synthetic-delivery-1", "synthetic-delivery-2"])
    with pytest.raises(ValueError, match="required delivery legs"):
        validate_publication(value, OWNER)
    value = publication()
    value["legs"][0]["message_url"] = (
        "https://discord.com/channels/123456789012345678/123456789012345678/987654321098765433"
    )
    with pytest.raises(ValueError, match="message URL"):
        validate_publication(value, OWNER)


def test_publication_preserves_more_than_ten_exact_delivery_legs():
    value = publication()
    legs = []
    for index in range(17):
        receipt_id = f"{987654321098765432 + index:018d}"
        key = f"synthetic-delivery-{index}"
        legs.append({
            **value["legs"][0],
            "operation_key": key,
            "operation_digest": f"{index + 1:064x}",
            "receipt_id": receipt_id,
            "message_url": f"https://discord.com/channels/123456789012345678/123456789012345678/{receipt_id}",
        })
    value["legs"] = legs
    value["required_operation_keys"] = [leg["operation_key"] for leg in legs]

    record = validate_publication(value, OWNER)

    assert len(record["legs"]) == 17
    with pytest.raises(ValueError, match="bounded delivery legs"):
        validate_publication({**value, "legs": legs * 4 + legs[:1]}, OWNER)


@pytest.mark.parametrize("owner_id,kind,route", [
    ("bursawatch-tg-market-news", "idx_company_news", "id_stocks_news"),
    ("bursawatch-tg-market-news", "industry_news", "id_industry_news"),
    ("bursawatch-tg-market-news", "macro_news", "macro_news"),
    ("bursawatch-tg-market-news", "stock_status", "id_stocks_news"),
    ("bursawatch-stockbit-snips", "idx_company_news", "id_stocks_news"),
    ("bursawatch-x-account-watch", "us_company_news", "us_stocks_news"),
    ("bursawatch-x-account-watch", "swing_context", "id_stocks_swing"),
    ("bursawatch-tg-phintraco-swing", "broker_swing_update", "id_stocks_swing"),
    ("bursawatch-ig-account-watch", "macro_news", "macro_news"),
    ("bursawatch-wa-channel-watch", "industry_news", "id_industry_news"),
    ("bursawatch-tg-kelas-investasi-gtw", "swing_bundle", "id_stocks_swing"),
    ("bursawatch-dc-swing-board", "swing_board_update", "swing_board"),
])
def test_approved_owner_type_and_route_are_distinct(owner_id, kind, route):
    changes = {"type": kind, "route": route}
    if kind == "broker_swing_update":
        changes["parent_publication_id"] = "a" * 64
    record = validate_publication(publication(**changes), owner_id)
    assert record["type"] == kind
    assert record["route"] == route
    assert record["owner_id"] == owner_id


def test_broker_plan_requires_phintraco_and_complete_source_levels():
    levels = {
        "entry": "100 to 105",
        "stop": "95",
        "targets": ["120", "130"],
        "units": "IDR per share",
        "attribution": "Synthetic broker",
    }
    value = publication(type="broker_swing_plan", route="id_stocks_swing", broker_levels=levels)
    with pytest.raises(ValueError, match="owner"):
        validate_publication(value, OWNER)
    assert validate_publication(value, "bursawatch-tg-phintraco-swing")["broker_levels"] == levels
    del levels["stop"]
    with pytest.raises(ValueError, match="broker levels"):
        validate_publication(value, "bursawatch-tg-phintraco-swing")


def test_broker_update_requires_phintraco_parent_and_cannot_claim_plan_levels():
    original = validate_publication(
        publication(type="broker_swing_plan", route="id_stocks_swing", broker_levels={
            "entry": "100", "stop": "95", "targets": ["110"],
            "units": "IDR per share", "attribution": "Synthetic broker",
        }),
        "bursawatch-tg-phintraco-swing",
    )
    update = publication(
        type="broker_swing_update", route="id_stocks_swing",
        parent_publication_id=original["publication_id"], broker_levels=None,
    )
    result = validate_publication(update, "bursawatch-tg-phintraco-swing")
    assert result["type"] == "broker_swing_update"
    assert result["parent_publication_id"] == original["publication_id"]
    assert result["broker_levels"] is None
    with pytest.raises(ValueError, match="link to a known original"):
        validate_publication({**update, "parent_publication_id": None}, "bursawatch-tg-phintraco-swing")
    with pytest.raises(ValueError, match="complete plan levels"):
        validate_publication({**update, "broker_levels": {
            "entry": "100", "stop": "95", "targets": ["110"],
            "units": "IDR per share", "attribution": "Synthetic broker",
        }}, "bursawatch-tg-phintraco-swing")


def test_unsafe_urls_private_media_and_unaware_times_fail_closed():
    with pytest.raises(ValueError, match="source_url"):
        validate_publication(publication(source_url="http://example.test/private"), OWNER)
    with pytest.raises(ValueError, match="delivery_confirmed_at"):
        validate_publication(publication(delivery_confirmed_at="2026-09-29T07:02:00"), OWNER)
    value = publication()
    value["legs"][0]["attachments"] = [{"private_media_ref": "secret://object"}]
    with pytest.raises(ValueError, match="attachment"):
        validate_publication(value, OWNER)
    value["legs"][0]["attachments"] = [{
        "filename": "chart.png",
        "content_type": "image/png",
        "discord_url": "https://storage.example.test/private/chart.png",
    }]
    with pytest.raises(ValueError, match="attachment discord_url"):
        validate_publication(value, OWNER)


def test_identity_is_owner_scoped_and_digest_changes_with_exact_output():
    first = validate_publication(publication(), OWNER)
    other = validate_publication(publication(), "bursawatch-stockbit-snips")
    edited = publication()
    edited["legs"][0]["text"] = "A different rendered text"
    changed = validate_publication(edited, OWNER)
    assert first["publication_id"] != other["publication_id"]
    assert first["publication_id"] == changed["publication_id"]
    assert first["digest"] != changed["digest"]
