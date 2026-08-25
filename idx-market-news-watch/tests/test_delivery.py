import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import delivery
from market_data import MarketSnapshot
import state as state_module
from domain import CompanyCandidate, EventClass, Provider, SourceKind
from selection import SelectionCandidate
from state import empty_state, enqueue_candidate, load_state


class Response:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


def _item(provider, message_id, ticker, event_class, published_at, facts=("contract value",)):
    return SelectionCandidate(
        candidate=CompanyCandidate(
            provider=provider,
            source_message_id=message_id,
            ticker=ticker,
            source_kind=SourceKind.CORPORATE_ENTRY,
            published_at=published_at,
            source_text="source text is not reposted",
            direct_image=False,
        ),
        event_class=event_class,
        ranking_band=1,
        material_facts=facts,
        dedupe_facts=("counterparty", "term"),
    )


@pytest.fixture
def dewa_tier_one():
    return _item(
        Provider.TUNTUN,
        13597,
        "DEWA",
        EventClass.CORPORATE_ACTION,
        datetime(2026, 7, 14, 6, 18, tzinfo=timezone.utc),
    )


@pytest.fixture
def cbre_tier_two():
    return _item(
        Provider.TUNTUN,
        13598,
        "CBRE",
        EventClass.QUANTIFIED_OPERATIONAL_EXECUTION,
        datetime(2026, 7, 14, 6, 20, tzinfo=timezone.utc),
    )


@pytest.fixture
def anm_tier_two():
    return _item(
        Provider.PHINTRACO,
        13599,
        "ANTM",
        EventClass.OTHER_COMPANY_OPERATION,
        datetime(2026, 7, 14, 6, 21, tzinfo=timezone.utc),
    )


def test_news_item_has_no_delivery_window_heading(dewa_tier_one):
    alert = delivery.format_news_item(dewa_tier_one)

    assert alert.startswith(
        "### <:tuntun:1531272430985937086> DEWA (DEWA)"
    )
    assert all(label not in alert for label in ("PRE-MARKET", "POST-MARKET", "INTRA-DAY"))
    assert "┈" * 13 in alert
    assert "[Sumber]" not in alert
    assert "BUY" not in alert
    assert len(alert) <= 2000


def test_news_item_preserves_material_fact_capitalization():
    alert = delivery.format_news_item(
        _item(
            Provider.TUNTUN,
            14039,
            "SINI",
            EventClass.MNA_OR_ASSET_TRANSACTION,
            datetime(2026, 7, 23, 5, 51, tzinfo=timezone.utc),
            facts=("SINI acquired KMS.", "KMS revenue is projected at US$159 million in 2027."),
        )
    )

    assert "SINI acquired KMS. KMS revenue is projected at US$159 million in 2027." in alert
    assert "•" not in alert


def test_entry_uses_yahoo_snapshot_for_canonical_name_and_rupiah_changes(monkeypatch, dewa_tier_one):
    monkeypatch.setattr(
        delivery,
        "get_market_snapshot",
        lambda ticker, source_text: MarketSnapshot("PT Darma Henwa Tbk", 472, 32, 7.27, -18, -3.67),
    )

    alert = delivery.format_news_item(dewa_tier_one)

    assert "DEWA (PT Darma Henwa Tbk)" in alert
    assert (
        "*Harga terakhir (IDR):* 472\n"
        "<:green:1531274822221434911>1D: +32 (+7,27%)\n"
        "<:red:1531274756853202974>1W: -18 (-3,67%)"
    ) in alert


def test_flat_market_change_uses_grey_emoji(monkeypatch, dewa_tier_one):
    monkeypatch.setattr(
        delivery,
        "get_market_snapshot",
        lambda ticker, source_text: MarketSnapshot("PT Darma Henwa Tbk", 472, 0, 0, 0, 0),
    )

    alert = delivery.format_news_item(dewa_tier_one)

    assert alert.count("<:grey:1531279158913536182>") == 2


def test_investment_language_guard_does_not_reject_the_factual_word_holds():
    assert not delivery._contains_investment_language("DSSA holds more than 99% of BMT.")
    assert delivery._contains_investment_language("The source recommends BUY.")


def test_each_news_item_is_a_standalone_message_without_a_shared_heading(monkeypatch, tmp_path, dewa_tier_one):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    second = _item(
        Provider.TUNTUN,
        13601,
        "ADRO",
        EventClass.CORPORATE_ACTION,
        datetime(2026, 7, 14, 6, 20, tzinfo=timezone.utc),
    )
    state = empty_state()
    now = datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc)
    for item in (dewa_tier_one, second):
        enqueue_candidate(state, item.candidate, now)
        state["candidates"][item.key]["phase"] = "pending_delivery"
    posted = []
    monkeypatch.setattr(delivery, "post_discord_text", lambda content, *args, **kwargs: posted.append(content) or "id")

    assert asyncio.run(delivery.deliver_event(state, dewa_tier_one, "123", now))
    assert asyncio.run(delivery.deliver_event(state, second, "123", now))

    assert posted[0].startswith("### <:tuntun:1531272430985937086> DEWA")
    assert posted[1].startswith("### <:tuntun:1531272430985937086> ADRO (ADRO)")
    assert all("INTRA-DAY" not in message for message in posted)


def test_tier_two_uses_the_same_standalone_format_and_oversize_is_rejected(cbre_tier_two):
    assert delivery.format_news_item(cbre_tier_two).startswith("### <:tuntun:1531272430985937086> CBRE")
    oversized = _item(
        Provider.TUNTUN,
        13600,
        "ADRO",
        EventClass.CORPORATE_ACTION,
        datetime(2026, 7, 14, 6, 18, tzinfo=timezone.utc),
        facts=("x" * 2_000,),
    )
    with pytest.raises(ValueError, match="2,000"):
        delivery.format_news_item(oversized)


@pytest.mark.parametrize("status", [200, 201])
def test_post_text_uses_v10_nonce_and_treats_200_and_201_as_success(monkeypatch, status):
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return Response(status, {"id": "42"})

    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
    monkeypatch.setattr(delivery.requests, "request", request)

    assert delivery.post_discord_text("message", "123", "event-key") == "42"
    assert calls == [
        (
            "POST",
            "https://discord.com/api/v10/channels/123/messages",
            {
                "headers": {"Authorization": "Bot token", "Content-Type": "application/json"},
                "json": {
                    "content": "message",
                    "nonce": delivery.discord_nonce("event-key", "text"),
                    "enforce_nonce": True,
                },
                "timeout": 20,
            },
        )
    ]
    assert delivery.discord_nonce("event-key", "text") == delivery.discord_nonce("event-key", "text")
    assert len(delivery.discord_nonce("event-key", "text")) == 24


def test_post_text_rejects_oversize_before_request(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
    monkeypatch.setattr(delivery.requests, "request", lambda *args, **kwargs: pytest.fail("called"))

    with pytest.raises(ValueError, match="2,000"):
        delivery.post_discord_text("x" * 2_001, "123", "event-key")


def test_post_text_reports_discord_http_rejection(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
    monkeypatch.setattr(delivery.requests, "request", lambda *args, **kwargs: Response(403, {"message": "Missing Access"}))

    with pytest.raises(delivery.DiscordRejected, match="Discord HTTP 403: Missing Access"):
        delivery.post_discord_text("message", "123", "event-key")


def test_post_text_reports_discord_rate_limit(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
    monkeypatch.setattr(
        delivery.requests, "request", lambda *args, **kwargs: Response(429, {"retry_after": 2.5})
    )

    with pytest.raises(delivery.DiscordRateLimited, match="2.5") as error:
        delivery.post_discord_text("message", "123", "event-key")
    assert error.value.retry_after == 2.5


def test_post_image_uploads_cached_bytes_and_accepts_200(monkeypatch, tmp_path):
    image = tmp_path / "source.jpg"
    image.write_bytes(b"jpeg bytes")
    observed = {}

    def request(method, url, **kwargs):
        observed.update(method=method, url=url, kwargs=kwargs)
        return Response(200, {"id": "image-id"})

    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
    monkeypatch.setattr(delivery.requests, "request", request)

    assert delivery.post_discord_image(image, "123", "event-key") == "image-id"
    assert observed["method"] == "POST"
    assert observed["url"] == "https://discord.com/api/v10/channels/123/messages"
    assert observed["kwargs"]["data"]["payload_json"]
    assert "files[0]" in observed["kwargs"]["files"]


def test_capture_direct_image_requires_the_exact_source_message_photo(tmp_path, dewa_tier_one):
    candidate = dewa_tier_one.candidate
    client = SimpleNamespace()
    requested = []

    async def get_messages(entity, ids):
        requested.append((entity, ids))
        return SimpleNamespace(id=ids, photo=object())

    async def download_media(message, file):
        assert file is bytes
        return b"jpeg bytes"

    client.get_messages = get_messages
    client.download_media = download_media

    cached = asyncio.run(delivery.capture_direct_image(client, "source", candidate, tmp_path / "media"))

    assert requested == [("source", candidate.source_message_id)]
    assert cached is not None
    assert cached.read_bytes() == b"jpeg bytes"
    assert cached.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "media").stat().st_mode & 0o777 == 0o700


def test_capture_direct_image_ignores_missing_or_mismatched_photo(tmp_path, dewa_tier_one):
    candidate = dewa_tier_one.candidate

    class Client:
        async def get_messages(self, entity, ids):
            return SimpleNamespace(id=ids + 1, photo=object())

        async def download_media(self, message, file):
            pytest.fail("must not download a mismatched message")

    assert asyncio.run(delivery.capture_direct_image(Client(), "source", candidate, tmp_path)) is None


def test_tier_one_persists_text_before_post_and_marks_delivered_only_after_success(
    monkeypatch, tmp_path, dewa_tier_one
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    state = empty_state()
    now = datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc)
    enqueue_candidate(state, dewa_tier_one.candidate, now)
    state["candidates"][dewa_tier_one.key]["phase"] = "pending_delivery"
    observed_phase = []

    def post(content, channel_id, event_key, dry_run=False):
        observed_phase.append(state["candidates"][dewa_tier_one.key]["phase"])
        assert state["stats"]["delivery_payloads"][dewa_tier_one.key]["content"] == content
        return "discord-text-id"

    monkeypatch.setattr(delivery, "post_discord_text", post)

    assert asyncio.run(delivery.deliver_event(state, dewa_tier_one, "123", now, media_directory=tmp_path / "media"))
    assert observed_phase == ["pending_delivery"]
    assert state["candidates"][dewa_tier_one.key]["phase"] == "delivered"
    assert state["stats"]["delivery_payloads"][dewa_tier_one.key]["text_discord_id"] == "discord-text-id"
    assert state["last_delivery_success"] == now.isoformat()


def test_rate_limited_text_preserves_payload_and_uses_state_retry(
    monkeypatch, tmp_path, dewa_tier_one
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    state = empty_state()
    now = datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc)
    enqueue_candidate(state, dewa_tier_one.candidate, now)
    state["candidates"][dewa_tier_one.key]["phase"] = "pending_delivery"

    def rate_limited(*args, **kwargs):
        raise delivery.DiscordRateLimited(120)

    monkeypatch.setattr(delivery, "post_discord_text", rate_limited)


    assert not asyncio.run(delivery.deliver_event(state, dewa_tier_one, "123", now))
    assert state["stats"]["delivery_payloads"][dewa_tier_one.key]["content"] == delivery.format_news_item(
        dewa_tier_one
    )
    assert state["candidates"][dewa_tier_one.key]["phase"] == "pending_delivery"
    assert state["candidates"][dewa_tier_one.key]["retry"]["last_error"] == "Discord rate limited for 120 seconds"
    retry_due_at = datetime.fromisoformat(
        state["candidates"][dewa_tier_one.key]["retry"]["next_attempt_at"]
    )
    assert retry_due_at >= now + timedelta(seconds=120)
    restored = load_state()
    assert restored["candidates"][dewa_tier_one.key]["phase"] == "pending_delivery"
    assert restored["stats"]["delivery_payloads"][dewa_tier_one.key]["content"] == delivery.format_news_item(
        dewa_tier_one
    )
    assert datetime.fromisoformat(
        restored["candidates"][dewa_tier_one.key]["retry"]["next_attempt_at"]
    ) >= now + timedelta(seconds=120)


def test_text_only_immediate_delivery_never_attempts_source_image(
    monkeypatch, tmp_path, dewa_tier_one
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    state = empty_state()
    now = datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc)
    enqueue_candidate(state, dewa_tier_one.candidate, now)
    state["candidates"][dewa_tier_one.key]["phase"] = "pending_delivery"
    monkeypatch.setattr(delivery, "post_discord_text", lambda *args, **kwargs: "discord-text-id")

    async def broken_capture(*args, **kwargs):
        raise OSError("download failed")

    monkeypatch.setattr(delivery, "capture_direct_image", broken_capture)
    client = SimpleNamespace()

    assert asyncio.run(
        delivery.deliver_event(
            state,
            dewa_tier_one,
            "123",
            now,
            client=client,
            entity="source",
            media_directory=tmp_path / "media",
        )
    )
    assert state["candidates"][dewa_tier_one.key]["phase"] == "delivered"
    assert state["stats"]["delivery_payloads"][dewa_tier_one.key]["image_error"] is None


def test_tier_two_standalone_delivery_never_enters_media_capture(
    monkeypatch, tmp_path, cbre_tier_two
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    state = empty_state()
    now = datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc)
    enqueue_candidate(state, cbre_tier_two.candidate, now)
    state["candidates"][cbre_tier_two.key]["phase"] = "pending_delivery"
    monkeypatch.setattr(delivery, "post_discord_text", lambda *args, **kwargs: "discord-text-id")

    async def fail_capture(*args, **kwargs):
        pytest.fail("Standalone news delivery must not capture media")

    monkeypatch.setattr(delivery, "capture_direct_image", fail_capture)

    assert asyncio.run(
        delivery.deliver_event(
            state,
            cbre_tier_two,
            "123",
            now,
            client=SimpleNamespace(),
            entity="source",
        )
    )
    assert state["candidates"][cbre_tier_two.key]["phase"] == "delivered"
