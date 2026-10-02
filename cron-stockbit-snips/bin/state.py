from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
import tempfile
from typing import Iterator

from models import Article, Feed, FeedLane


STATE_VERSION = 2
PUBLICATION_LEDGER_KEY = "publication_projection"
AGENT_LEASE = timedelta(minutes=2)
RETRY_MINUTES = (1, 2, 4, 8, 15, 30, 60)


def new_state(feeds: tuple[Feed, ...]) -> dict[str, object]:
    return {
        "version": STATE_VERSION,
        "feeds": {
            feed.lane.value: {
                "cursor": None,
                "etag": None,
                "last_modified": None,
                "last_poll_success": None,
                "last_error": None,
                "enabled": True,
            }
            for feed in feeds
        },
        "articles": {},
        "last_run": None,
        "last_heartbeat": None,
    }


def _valid_timestamp(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def load_state(path: Path, feeds: tuple[Feed, ...]) -> dict[str, object]:
    if not path.exists():
        return new_state(feeds)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Stockbit Snips state is unreadable") from error
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] not in {1, STATE_VERSION}:
        raise RuntimeError("Stockbit Snips state has an unsupported version")
    source_version = value["version"]
    if not isinstance(value.get("feeds"), dict) or not isinstance(value.get("articles"), dict):
        raise RuntimeError("Stockbit Snips state has invalid containers")
    expected_lanes = {feed.lane.value for feed in feeds}
    if set(value["feeds"]) != expected_lanes:
        raise RuntimeError("Stockbit Snips state feed lanes do not match the package")
    for lane, record in value["feeds"].items():
        if not isinstance(record, dict) or not _valid_timestamp(record.get("last_poll_success")):
            raise RuntimeError(f"Stockbit Snips state feed {lane} is invalid")
        if source_version == STATE_VERSION and type(record.get("enabled")) is not bool:
            raise RuntimeError(f"Stockbit Snips state feed {lane} enabled is invalid")
        cursor = record.get("cursor")
        if cursor is not None and (
            not isinstance(cursor, dict)
            or not isinstance(cursor.get("guid"), str)
            or not isinstance(cursor.get("published_at"), str)
            or not _valid_timestamp(cursor.get("published_at"))
        ):
            raise RuntimeError(f"Stockbit Snips state cursor {lane} is invalid")
    for key, record in value["articles"].items():
        if not isinstance(key, str) or not isinstance(record, dict):
            raise RuntimeError("Stockbit Snips article state is invalid")
        if record.get("phase") not in {"awaiting_agent", "pending_delivery", "delivered", "excluded", "split"}:
            raise RuntimeError(f"Stockbit Snips article phase {key} is invalid")
        if not isinstance(record.get("article"), dict):
            raise RuntimeError(f"Stockbit Snips article payload {key} is invalid")
        try:
            article = Article.from_payload(record["article"])
        except (TypeError, ValueError) as error:
            raise RuntimeError(f"Stockbit Snips article payload {key} is invalid") from error
        if article.key != key:
            raise RuntimeError(f"Stockbit Snips article key {key} is invalid")
        if not _valid_timestamp(record.get("agent_lease_until")):
            raise RuntimeError(f"Stockbit Snips agent lease {key} is invalid")
        if not _valid_retry(record.get("retry")):
            raise RuntimeError(f"Stockbit Snips article retry {key} is invalid")
        if record.get("phase") == "split":
            child_keys = record.get("news_item_keys")
            if type(child_keys) is not list or not 1 <= len(child_keys) <= 16 or len(set(child_keys)) != len(child_keys):
                raise RuntimeError("Stockbit split item keys are invalid")
            for child_key in child_keys:
                child_record = value["articles"].get(child_key)
                if not isinstance(child_record, dict) or child_record.get("parent_candidate_key") != key:
                    raise RuntimeError("Stockbit split item identity is invalid")
        if "config_snapshot" in record and not _valid_config_snapshot(record["config_snapshot"]):
            raise RuntimeError(f"Stockbit Snips article config snapshot {key} is invalid")
    if PUBLICATION_LEDGER_KEY in value:
        _validate_publication_ledger(value[PUBLICATION_LEDGER_KEY])
    if source_version == 1:
        value["version"] = STATE_VERSION
        for record in value["feeds"].values():
            record["enabled"] = True
    return value


def _validate_publication_ledger(value: object) -> None:
    if type(value) is not dict:
        raise RuntimeError("Stockbit publication ledger is invalid")
    for owner_key, record in value.items():
        if (not isinstance(owner_key, str) or not owner_key or type(record) is not dict
                or set(record) != {"snapshot", "ack"}):
            raise RuntimeError("Stockbit publication entry is invalid")
        snapshot = record["snapshot"]
        if (type(snapshot) is not dict or snapshot.get("owner_key") != owner_key
                or type(snapshot.get("version")) is not int or snapshot["version"] != 1
                or not _valid_timestamp(snapshot.get("delivery_confirmed_at"))):
            raise RuntimeError("Stockbit publication snapshot identity is invalid")
        required = snapshot.get("required_operation_keys")
        legs = snapshot.get("legs")
        if (type(required) is not list or not required
                or any(type(item) is not str or not item for item in required)
                or len(required) != len(set(required)) or type(legs) is not list
                or [leg.get("operation_key") for leg in legs if type(leg) is dict] != required
                or len(legs) != len(required)
                or any(type(leg) is not dict or leg.get("status") != "delivered" for leg in legs)):
            raise RuntimeError("Stockbit publication legs are incomplete")
        ack = record["ack"]
        if ack is not None and (
            type(ack) is not dict or set(ack) != {"publication_id", "version", "digest"}
            or type(ack.get("publication_id")) is not str
            or len(ack["publication_id"]) != 64
            or any(char not in "0123456789abcdef" for char in ack["publication_id"])
            or type(ack.get("version")) is not int or ack["version"] != snapshot["version"]
            or type(ack.get("digest")) is not str or len(ack["digest"]) != 64
            or any(char not in "0123456789abcdef" for char in ack["digest"])
        ):
            raise RuntimeError("Stockbit publication acknowledgment is invalid")


def record_publication_intent(value: dict[str, object], snapshot: dict[str, object]) -> bool:
    ledger = value.setdefault(PUBLICATION_LEDGER_KEY, {})
    if type(ledger) is not dict:
        raise RuntimeError("Stockbit publication ledger is invalid")
    owner_key = snapshot.get("owner_key")
    if type(owner_key) is not str or not owner_key:
        raise ValueError("Stockbit publication identity is invalid")
    existing = ledger.get(owner_key)
    if existing is not None:
        if type(existing) is not dict or existing.get("snapshot") != snapshot:
            raise RuntimeError("Stockbit publication identity conflicts with its saved intent")
        return False
    ledger[owner_key] = {"snapshot": snapshot, "ack": None}
    return True


def pending_publication_intents(value: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
    ledger = value.get(PUBLICATION_LEDGER_KEY, {})
    if type(ledger) is not dict:
        raise RuntimeError("Stockbit publication ledger is invalid")
    return sorted(
        ((key, record["snapshot"]) for key, record in ledger.items()
         if type(record) is dict and record.get("ack") is None),
        key=lambda item: (item[1]["delivery_confirmed_at"], item[0]),
    )


def acknowledge_publication_intent(
    value: dict[str, object], owner_key: str, ack: dict[str, object]
) -> bool:
    ledger = value.get(PUBLICATION_LEDGER_KEY)
    record = ledger.get(owner_key) if type(ledger) is dict else None
    if type(record) is not dict:
        raise RuntimeError("Stockbit publication acknowledgment has no intent")
    if record["ack"] is not None:
        if record["ack"] != ack:
            raise RuntimeError("Stockbit publication acknowledgment changed")
        return False
    record["ack"] = ack
    return True


def publication_checkpoint_comparison(value: dict[str, object], compared_at: datetime) -> dict[str, object]:
    ledger = value.get(PUBLICATION_LEDGER_KEY, {})
    if type(ledger) is not dict:
        raise RuntimeError("Stockbit publication ledger is invalid")
    ordered = sorted(
        ledger.items(), key=lambda item: (item[1]["snapshot"]["delivery_confirmed_at"], item[0])
    )
    confirmed = max(
        (record["snapshot"]["delivery_confirmed_at"] for record in ledger.values()), default=None
    )
    accepted = None
    for _key, record in ordered:
        if record["ack"] is None:
            break
        accepted = record["snapshot"]["delivery_confirmed_at"]
    if confirmed is not None and not any(record["ack"] is None for record in ledger.values()):
        accepted = confirmed
    return {
        "compared_at": compared_at.isoformat(),
        "confirmed_through_at": confirmed,
        "accepted_through_at": accepted,
        "outstanding_count": sum(1 for record in ledger.values() if record["ack"] is None),
    }


def _valid_retry(value: object) -> bool:
    if type(value) is not dict or set(value) != {"attempts", "next_attempt_at", "last_error"}:
        return False
    attempts = value["attempts"]
    last_error = value["last_error"]
    return (
        type(attempts) is int
        and attempts >= 0
        and _valid_timestamp(value["next_attempt_at"])
        and (last_error is None or type(last_error) is str)
    )


def _valid_config_snapshot(value: object) -> bool:
    if type(value) is not dict or set(value) != {
        "revision",
        "additional_prompt_instruction",
        "id_stocks_news_channel_id",
        "macro_news_channel_id",
    }:
        return False
    if type(value["revision"]) is not int or value["revision"] < 1:
        return False
    instruction = value["additional_prompt_instruction"]
    if type(instruction) is not str or len(instruction) > 800:
        return False
    issuer = value["id_stocks_news_channel_id"]
    macro = value["macro_news_channel_id"]
    return all(type(channel) is str and channel.isascii() and channel.isdecimal() and 17 <= len(channel) <= 20 for channel in (issuer, macro)) and issuer != macro


def save_state(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


@contextmanager
def run_lock(path: Path) -> Iterator[None]:
    lock_path = Path(f"{path}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def feed_record(value: dict[str, object], lane: FeedLane) -> dict[str, object]:
    feeds = value["feeds"]
    assert isinstance(feeds, dict)
    record = feeds[lane.value]
    assert isinstance(record, dict)
    return record


def cursor_tuple(record: dict[str, object]) -> tuple[datetime, str] | None:
    cursor = record.get("cursor")
    if not isinstance(cursor, dict):
        return None
    try:
        published_at = datetime.fromisoformat(cursor["published_at"])
    except (KeyError, TypeError, ValueError):
        return None
    return published_at, str(cursor["guid"])


def set_cursor(record: dict[str, object], article: Article) -> None:
    record["cursor"] = {"published_at": article.published_at.isoformat(), "guid": article.guid}


def article_is_new(record: dict[str, object], article: Article) -> bool:
    cursor = cursor_tuple(record)
    return cursor is None or (article.published_at, article.guid) > cursor


def queue_article(value: dict[str, object], article: Article, now: datetime) -> bool:
    articles = value["articles"]
    assert isinstance(articles, dict)
    if article.key in articles:
        return False
    articles[article.key] = {
        "article": article.to_payload(),
        "phase": "awaiting_agent",
        "enqueued_at": now.isoformat(),
        "agent_lease_until": None,
        "analysis": None,
        "rendered": None,
        "retry": {"attempts": 0, "next_attempt_at": None, "last_error": None},
    }
    return True


def article_from_record(key: str, record: object) -> Article:
    if not isinstance(record, dict) or record.get("article") is None:
        raise RuntimeError(f"Stockbit Snips article {key} is malformed")
    article = Article.from_payload(record["article"])
    if article.key != key:
        raise RuntimeError(f"Stockbit Snips article {key} has an inconsistent key")
    return article


def pending_agent(value: dict[str, object], now: datetime) -> tuple[str, Article] | None:
    articles = value["articles"]
    assert isinstance(articles, dict)
    candidates: list[tuple[datetime, str, Article]] = []
    for key, record in articles.items():
        if not isinstance(record, dict) or record.get("phase") != "awaiting_agent":
            continue
        lease = record.get("agent_lease_until")
        if isinstance(lease, str):
            try:
                if datetime.fromisoformat(lease) > now:
                    continue
            except ValueError:
                continue
        article = article_from_record(key, record)
        candidates.append((article.published_at, key, article))
    if not candidates:
        return None
    _, key, article = min(candidates)
    return key, article


def claim_agent(record: dict[str, object], now: datetime) -> None:
    record["agent_lease_until"] = (now + AGENT_LEASE).isoformat()


def retry_due(record: dict[str, object], now: datetime) -> bool:
    retry = record.get("retry")
    if not isinstance(retry, dict):
        return True
    next_attempt = retry.get("next_attempt_at")
    if next_attempt is None:
        return True
    try:
        return datetime.fromisoformat(next_attempt) <= now
    except (TypeError, ValueError):
        return True


def mark_delivery_failure(record: dict[str, object], now: datetime, error: str) -> None:
    retry = record.setdefault("retry", {})
    assert isinstance(retry, dict)
    attempts = int(retry.get("attempts", 0)) + 1
    retry.update(
        {
            "attempts": attempts,
            "next_attempt_at": (now + timedelta(minutes=RETRY_MINUTES[min(attempts - 1, len(RETRY_MINUTES) - 1)])).isoformat(),
            "last_error": " ".join(error.split())[:300],
        }
    )
