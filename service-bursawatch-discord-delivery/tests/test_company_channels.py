import pytest

from discord_delivery.discord_gateway import DiscordGateway
from discord_delivery.models import OperationIntent, ValidationError, validate_query, validate_receipt


def intent(kind="text_channel_create", payload=None):
    return OperationIntent(key="company-news:global-channel", kind=kind, ordering_key="company-news:channels",
        target={"guild_id": "123456789012345678"} if kind.endswith("create") else {"channel_id": "234567890123456789"},
        payload=payload or {"name": "global-company-news", "parent_id": "345678901234567890",
            "permission_overwrites": [{"id": "123456789012345678", "type": 0, "allow": "1024", "deny": "2048"}]})


def test_company_channel_creation_has_fixed_text_type_and_preserves_reviewed_permissions():
    value = intent()
    method, path, payload = DiscordGateway.request_spec(value)
    assert (method, path) == ("POST", "/guilds/123456789012345678/channels")
    assert payload == {**value.payload, "type": 0}
    assert validate_receipt({"channel_id": "234567890123456789"}, value.kind, value.target) == {"channel_id": "234567890123456789"}


def test_existing_company_channel_can_be_renamed_without_a_message():
    value = intent("text_channel_edit", {"name": "indonesia-company-news", "topic": "Public and private companies"})
    assert DiscordGateway.request_spec(value) == ("PATCH", "/channels/234567890123456789", dict(value.payload))


@pytest.mark.parametrize("payload", [{"name": "bad", "type": 15},
    {"name": "bad", "permission_overwrites": [{"id": "1", "type": True, "allow": "0", "deny": "0"}]},
    {"name": "bad", "parent_id": "https://example.test"}])
def test_channel_provisioning_rejects_untyped_or_invalid_payloads(payload):
    with pytest.raises(ValidationError):
        intent(payload=payload)


def test_guild_channel_inventory_is_read_only_and_bounded(monkeypatch):
    gateway = DiscordGateway("synthetic-token")
    calls = []
    def request(method, path):
        calls.append((method, path))
        return [{"id": "234567890123456789", "name": "global-company-news", "type": 0}]
    monkeypatch.setattr(gateway, "_request", request)
    query = validate_query({"kind": "guild_channels", "guild_id": "123456789012345678"})
    assert gateway.query(query)[0]["name"] == "global-company-news"
    assert calls == [("GET", "/guilds/123456789012345678/channels")]
    with pytest.raises(ValidationError):
        validate_query({**query, "url": "https://example.test"})
