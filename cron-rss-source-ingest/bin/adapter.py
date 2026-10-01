"""Stockbit's four fixed RSS lanes as system-owned source endpoints."""
from __future__ import annotations

import hashlib
import json
import re
import stat
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for local_name, runtime_name in (
    ("lib-bursawatch-control", "lib-bursawatch-control"),
    ("lib-bursawatch-source-ingest", "lib-bursawatch-source-ingest-pilot"),
):
    candidate = ROOT / local_name / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / runtime_name / "bin"
    sys.path.insert(0, str(candidate))
owner = ROOT / "cron-stockbit-snips" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-stockbit-snips" / "bin"
sys.path.insert(0, str(owner))

from source_ingest import IntakeBlocked, _cursor as _load_cursor_record, _write, bind_catalog_revision, ingest_all, select_endpoints
from legacy_cursor_seed import (
    LegacySeedBlocked,
    _catalog_transition_temporaries,
    blocked_seed_plan,
    plan_seed,
    read_legacy_snapshot,
)
from config import FEEDS
from rss import FetchResult

ALLOWED = {"stockbit_snips"}
_VALIDATOR_VERSION = 1
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _validator_path(state_root: Path, endpoint_id: str) -> Path:
    return state_root / endpoint_id.replace(":", "-") / "http-validators.json"


def _header_value(value: Any, label: str) -> str | None:
    if value is None or value == "":
        return None
    if type(value) is not str or len(value) > 2048 or "\r" in value or "\n" in value:
        raise IntakeBlocked(f"Stockbit {label} validator is invalid")
    return value


def _load_validators(state_root: Path, endpoint_id: str) -> dict[str, str | None]:
    path = _validator_path(state_root, endpoint_id)
    if not path.exists():
        return {"etag": None, "last_modified": None}
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise IntakeBlocked("Stockbit RSS validators are invalid") from error
    if type(value) is not dict or set(value) != {"version", "etag", "last_modified"} or value.get("version") != _VALIDATOR_VERSION:
        raise IntakeBlocked("Stockbit RSS validators are invalid")
    try:
        return {
            "etag": _header_value(value["etag"], "ETag"),
            "last_modified": _header_value(value["last_modified"], "Last-Modified"),
        }
    except IntakeBlocked as error:
        raise IntakeBlocked("Stockbit RSS validators are invalid") from error


def _rss_projection(snapshot: dict[str, Any], loaded_config: Any) -> tuple[list[dict[str, Any]], str]:
    if type(snapshot) is not dict or type(snapshot.get("subscriptions")) is not list:
        raise IntakeBlocked("effective Stockbit catalog is invalid")
    if any(type(row) is not dict for row in snapshot["subscriptions"]):
        raise IntakeBlocked("effective Stockbit catalog subscriptions are invalid")
    try:
        selected, _feeds = endpoints(snapshot, loaded_config)
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise IntakeBlocked("effective Stockbit catalog does not match live watcher config") from error

    expected = {(f"rss:stockbit:{feed.lane.value}", "stockbit_snips") for feed in FEEDS}
    rows: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    for row in snapshot["subscriptions"]:
        if row.get("platform") != "rss" or row.get("enabled") is not True:
            continue
        endpoint_id = row.get("endpoint_id")
        capability_id = row.get("capability_id")
        if type(endpoint_id) is not str or type(capability_id) is not str:
            raise IntakeBlocked("effective Stockbit RSS identity is invalid")
        identity = (endpoint_id, capability_id)
        if identity in identities:
            raise IntakeBlocked("effective Stockbit RSS identity is duplicated")
        identities.add(identity)
        rows.append(row)
    if len(FEEDS) != 4 or identities != expected or set(selected) != {endpoint for endpoint, _capability in expected}:
        raise IntakeBlocked("effective Stockbit catalog must contain exactly four enabled lanes")
    rows.sort(key=lambda row: (row["endpoint_id"], row["capability_id"]))
    try:
        raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise IntakeBlocked("effective Stockbit RSS projection is invalid") from error
    return rows, hashlib.sha256(raw).hexdigest()


def _journal_digest(value: Any) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _validate_rss_journal(
    root: Path,
    path: Path,
    from_revision: int,
    to_revision: int,
    *,
    projection_sha256: str,
    watch_config_revision: int,
    origin_revision: int,
    accepted_statuses: set[str],
) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise IntakeBlocked("RSS catalog transition journal is missing or not private")
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise IntakeBlocked("RSS catalog transition journal is invalid") from error
    if (
        type(journal) is not dict
        or set(journal) != {"version", "status", "plan", "seeded_endpoints"}
        or type(journal.get("version")) is not int
        or journal["version"] != 1
        or type(journal.get("status")) is not str
        or journal["status"] not in accepted_statuses
        or type(journal.get("plan")) is not dict
        or journal.get("seeded_endpoints") != []
    ):
        raise IntakeBlocked("RSS catalog transition journal has an unsupported shape")

    plan = journal["plan"]
    expected_plan_keys = {
        "version", "status", "apply", "state_root", "transition_path", "from_revision",
        "to_revision", "state_files", "seeds", "metadata", "revision_only",
    }
    expected_path = root / "catalog-transitions" / f"{from_revision}-to-{to_revision}.json"
    metadata = plan.get("metadata")
    if (
        set(plan) != expected_plan_keys
        or type(plan.get("version")) is not int
        or plan["version"] != 1
        or plan.get("status") != "preview"
        or plan.get("apply") is not False
        or plan.get("revision_only") is not True
        or type(plan.get("from_revision")) is not int
        or plan["from_revision"] != from_revision
        or type(plan.get("to_revision")) is not int
        or plan["to_revision"] != to_revision
        or plan.get("state_root") != str(root)
        or plan.get("transition_path") != str(expected_path)
        or plan.get("seeds") != []
        or type(metadata) is not dict
        or set(metadata) != {
            "transition_type", "projection_sha256", "watch_config_revision", "prior_catalog_sha256",
            "target_catalog_sha256", "seed_origin_revision", "reason",
        }
        or metadata.get("transition_type") != "rss-compatible-catalog-transition"
        or metadata.get("projection_sha256") != projection_sha256
        or type(metadata.get("watch_config_revision")) is not int
        or metadata["watch_config_revision"] != watch_config_revision
        or type(metadata.get("seed_origin_revision")) is not int
        or metadata["seed_origin_revision"] != origin_revision
        or not _journal_digest(metadata.get("prior_catalog_sha256"))
        or not _journal_digest(metadata.get("target_catalog_sha256"))
        or type(metadata.get("reason")) is not str
        or len(metadata["reason"]) < 20
    ):
        raise IntakeBlocked("RSS catalog transition journal does not prove this reader projection")
    state_files = plan.get("state_files")
    if type(state_files) is not dict or any(
        type(name) is not str
        or Path(name).is_absolute()
        or ".." in Path(name).parts
        or not _journal_digest(digest)
        for name, digest in state_files.items()
    ):
        raise IntakeBlocked("RSS catalog transition journal fingerprint is invalid")
    return journal


def _require_rss_transition_chain(
    state_root: Path,
    origin_revision: int,
    through_revision: int,
    projection_sha256: str,
    watch_config_revision: int,
    *,
    allow_pending_edge: tuple[int, int] | None = None,
) -> None:
    """Require complete adjacent RSS transition journals from seed origin."""
    if (
        type(origin_revision) is not int
        or type(through_revision) is not int
        or origin_revision < 1
        or through_revision < origin_revision
        or type(watch_config_revision) is not int
        or watch_config_revision < 1
        or not _journal_digest(projection_sha256)
    ):
        raise IntakeBlocked("RSS catalog transition chain inputs are invalid")
    if allow_pending_edge is not None and (
        type(allow_pending_edge) is not tuple
        or len(allow_pending_edge) != 2
        or type(allow_pending_edge[0]) is not int
        or type(allow_pending_edge[1]) is not int
        or allow_pending_edge != (through_revision, through_revision + 1)
    ):
        raise IntakeBlocked("RSS pending catalog edge is invalid")

    root = Path(state_root).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise IntakeBlocked("RSS catalog transition state root is invalid")
    try:
        root = root.resolve(strict=True)
    except OSError as error:
        raise IntakeBlocked("RSS catalog transition state root is unavailable") from error
    directory = root / "catalog-transitions"
    if directory.is_symlink():
        raise IntakeBlocked("RSS catalog transition directory cannot be a symlink")
    expected_paths = {
        directory / f"{revision}-to-{revision + 1}.json"
        for revision in range(origin_revision, through_revision)
    }
    pending_path: Path | None = None
    if allow_pending_edge is not None:
        pending_path = directory / f"{allow_pending_edge[0]}-to-{allow_pending_edge[1]}.json"
    allowed_paths = set(expected_paths)
    if pending_path is not None and (pending_path.exists() or pending_path.is_symlink()):
        allowed_paths.add(pending_path)

    if directory.exists():
        if not directory.is_dir() or stat.S_IMODE(directory.stat().st_mode) & 0o077:
            raise IntakeBlocked("RSS catalog transition directory is unsafe")
        try:
            entries = set(directory.iterdir())
        except OSError as error:
            raise IntakeBlocked("RSS catalog transition directory is unreadable") from error
        try:
            temporary_paths = _catalog_transition_temporaries(directory)
        except LegacySeedBlocked as error:
            raise IntakeBlocked("RSS catalog transition temporary entry is unsafe") from error
        if entries - temporary_paths != allowed_paths:
            raise IntakeBlocked("RSS catalog transition history has a gap or unexpected entry")
    elif expected_paths or (pending_path is not None and pending_path.exists()):
        raise IntakeBlocked("RSS catalog transition history is incomplete")

    for path in sorted(expected_paths):
        from_revision = int(path.stem.split("-to-")[0])
        _validate_rss_journal(
            root,
            path,
            from_revision,
            from_revision + 1,
            projection_sha256=projection_sha256,
            watch_config_revision=watch_config_revision,
            origin_revision=origin_revision,
            accepted_statuses={"complete"},
        )
    if pending_path is not None and pending_path in allowed_paths:
        _validate_rss_journal(
            root,
            pending_path,
            allow_pending_edge[0],
            allow_pending_edge[1],
            projection_sha256=projection_sha256,
            watch_config_revision=watch_config_revision,
            origin_revision=origin_revision,
            accepted_statuses={"applying", "complete"},
        )


def plan_legacy_cursor_seed(
    legacy_state_path: Path,
    endpoint: dict[str, Any],
    catalog_revision: int,
    *,
    state_root: Path | None = None,
    page: FetchResult | None = None,
) -> dict[str, Any]:
    """Preview a legacy GUID cursor only when one bounded page proves it exactly."""
    if type(endpoint) is not dict:
        raise LegacySeedBlocked("Stockbit endpoint identity is invalid")
    if state_root is None or page is None:
        return blocked_seed_plan(
            legacy_state_path,
            endpoint,
            catalog_revision,
            "Stockbit cursor preview requires exact GUID boundary proof from a fresh bounded page response and a destination state root",
        )

    def blocked(reason: str) -> dict[str, Any]:
        return blocked_seed_plan(legacy_state_path, endpoint, catalog_revision, reason)

    if type(catalog_revision) is not int or catalog_revision < 1:
        return blocked("Stockbit endpoint identity or catalog revision is invalid")
    lane = endpoint.get("provider_id")
    from config import FEEDS
    feed = next((candidate for candidate in FEEDS if candidate.lane.value == lane), None)
    expected = (
        "rss",
        f"rss:stockbit:{lane}" if isinstance(lane, str) else None,
        "stockbit",
        feed.url if feed is not None else None,
        lane,
    )
    observed = tuple(endpoint.get(key) for key in ("platform", "endpoint_id", "publisher_id", "address", "provider_id"))
    if feed is None or observed != expected or endpoint.get("catalog_revision") != catalog_revision:
        return blocked("Stockbit endpoint does not match a fixed lane and catalog revision")
    if type(page) is not FetchResult or page.feed != feed or page.not_modified is not False or type(page.articles) is not tuple or len(page.articles) > 20:
        return blocked("Stockbit cursor preview requires a fresh page response of at most 20 items from the selected lane")

    try:
        raw, legacy = read_legacy_snapshot(legacy_state_path)
    except LegacySeedBlocked as error:
        return blocked(str(error))
    feeds = legacy.get("feeds")
    record = feeds.get(lane) if type(feeds) is dict else None
    cursor = record.get("cursor") if type(record) is dict else None
    if type(cursor) is not dict:
        return blocked("Stockbit legacy lane has no cursor boundary")
    guid = cursor.get("guid")
    timestamp = cursor.get("published_at")
    if type(guid) is not str or not guid.strip() or len(guid) > 4096 or type(timestamp) is not str:
        return blocked("Stockbit legacy cursor GUID or publication timestamp is invalid")
    try:
        normalized_timestamp = f"{timestamp[:-1]}+00:00" if timestamp.endswith("Z") else timestamp
        boundary = datetime.fromisoformat(normalized_timestamp)
        if boundary.tzinfo is None or boundary.utcoffset() is None:
            raise ValueError("timezone required")
    except ValueError:
        return blocked("Stockbit legacy cursor publication timestamp is invalid")

    identities: list[tuple[datetime, str]] = []
    matching_guid = []
    for article in page.articles:
        published_at = getattr(article, "published_at", None)
        article_guid = getattr(article, "guid", None)
        article_lane = getattr(article, "lane", None)
        if (
            article_lane != feed.lane
            or not isinstance(published_at, datetime)
            or published_at.tzinfo is None
            or published_at.utcoffset() is None
            or type(article_guid) is not str
            or not article_guid.strip()
            or len(article_guid) > 4096
        ):
            return blocked("Stockbit bounded page contains an invalid lane identity")
        identities.append((published_at, article_guid))
        if article_guid == guid:
            matching_guid.append(published_at)
    if any(identities[index] < identities[index + 1] for index in range(len(identities) - 1)):
        return blocked("Stockbit bounded page is not ordered by the legacy publication cursor")
    if len({article_guid for _published_at, article_guid in identities}) != len(identities):
        return blocked("Stockbit bounded page contains duplicate GUIDs")
    if len(matching_guid) != 1:
        return blocked("Stockbit legacy cursor GUID is absent or ambiguous in the bounded page")
    if matching_guid[0] != boundary:
        return blocked("Stockbit legacy cursor GUID publication timestamp differs from the bounded page")

    try:
        validators = {
            "etag": _header_value(page.etag, "ETag"),
            "last_modified": _header_value(page.last_modified, "Last-Modified"),
        }
    except IntakeBlocked as error:
        return blocked(str(error))
    page_identity_bytes = json.dumps(
        [(published_at.isoformat(), article_guid) for published_at, article_guid in identities],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    plan = plan_seed(
        legacy_state_path=legacy_state_path,
        state_root=state_root,
        endpoint=endpoint,
        snapshot_bytes=raw,
        catalog_revision=catalog_revision,
        anchor=hashlib.sha256(guid.encode("utf-8")).hexdigest(),
        cursor_shape="generic",
        boundary_timestamp=timestamp,
    )
    plan["feed_page_sha256"] = hashlib.sha256(page_identity_bytes).hexdigest()
    plan["feed_page_item_count"] = len(identities)
    plan["http_validators"] = validators
    return plan


def _bind_revision(state_root: Path, revision: int) -> None:
    """Fail closed on feed re-enable until a reviewed future-only transition."""
    path = state_root / "watch-config-revision.json"
    if not path.exists():
        if any(state_root.glob("rss-stockbit-*/cursor.json")):
            raise IntakeBlocked("RSS cursors have no recorded live configuration revision")
        _write(path, {"revision": revision})
        return
    try:
        recorded = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise IntakeBlocked("RSS live configuration revision record is invalid") from error
    if type(recorded) is not dict or recorded.get("revision") != revision:
        raise IntakeBlocked("Stockbit live configuration revision changed; reviewed future-only transition required")


def require_legacy_cursor_seed(state_root: Path, snapshot: dict[str, Any], loaded_config: Any) -> None:
    """Accept an immutable legacy seed only through a complete RSS journal chain."""
    root = Path(state_root).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise IntakeBlocked("RSS migration cursor handoff is missing")
    try:
        root = root.resolve(strict=True)
    except OSError as error:
        raise IntakeBlocked("RSS migration cursor handoff is unavailable") from error
    catalog_revision = snapshot.get("revision") if type(snapshot) is dict else None
    watch_config_revision = getattr(loaded_config, "revision", None)
    if (
        type(catalog_revision) is not int
        or catalog_revision < 1
        or type(watch_config_revision) is not int
        or watch_config_revision < 1
    ):
        raise IntakeBlocked("RSS migration revisions are invalid")

    for filename, expected in (
        ("catalog-revision.json", catalog_revision),
        ("watch-config-revision.json", watch_config_revision),
    ):
        path = root / filename
        if path.is_symlink() or not path.is_file():
            raise IntakeBlocked("RSS migration revision handoff is missing")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            raise IntakeBlocked("RSS migration revision handoff is invalid") from None
        if (
            type(value) is not dict
            or set(value) != {"revision"}
            or type(value.get("revision")) is not int
            or value["revision"] != expected
        ):
            raise IntakeBlocked("RSS migration revision handoff does not match live configuration")

    _projection, projection_sha256 = _rss_projection(snapshot, loaded_config)
    expected_lanes = {feed.lane.value for feed in FEEDS}
    lane_dirs = list(root.glob("rss-stockbit-*"))
    observed_lanes = {path.name.removeprefix("rss-stockbit-") for path in lane_dirs}
    if len(FEEDS) != 4 or observed_lanes != expected_lanes or len(lane_dirs) != 4 or any(path.is_symlink() or not path.is_dir() for path in lane_dirs):
        raise IntakeBlocked("RSS migration cursor handoff does not contain exactly four lanes")

    seed_origins: set[int] = set()
    snapshot_digests: set[str] = set()
    for feed in FEEDS:
        endpoint_id = f"rss:stockbit:{feed.lane.value}"
        endpoint = {
            "platform": "rss",
            "endpoint_id": endpoint_id,
            "publisher_id": "stockbit",
            "address": feed.url,
            "provider_id": feed.lane.value,
        }
        cursor_path = root / endpoint_id.replace(":", "-") / "cursor.json"
        validator_path = _validator_path(root, endpoint_id)
        if cursor_path.is_symlink() or not cursor_path.is_file() or validator_path.is_symlink() or not validator_path.is_file():
            raise IntakeBlocked("RSS migration cursor or validator handoff is missing")
        try:
            cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            raise IntakeBlocked("RSS migration cursor handoff is invalid") from None
        if (
            type(cursor) is not dict
            or cursor.get("initialized") is not True
            or type(cursor.get("anchor")) is not str
            or not _DIGEST.fullmatch(cursor["anchor"])
            or type(cursor.get("position")) not in {str, type(None)}
            or type(cursor.get("boundary_published_at")) is not str
            or not isinstance(cursor.get("legacy_seed"), dict)
        ):
            raise IntakeBlocked("RSS migration cursor handoff is invalid")
        try:
            boundary = datetime.fromisoformat(cursor["boundary_published_at"].replace("Z", "+00:00"))
        except ValueError:
            raise IntakeBlocked("RSS migration cursor boundary is invalid") from None
        if boundary.tzinfo is None or boundary.utcoffset() is None:
            raise IntakeBlocked("RSS migration cursor boundary is invalid")
        seed = cursor["legacy_seed"]
        origin = seed.get("catalog_revision")
        digest = seed.get("legacy_state_sha256")
        try:
            seed_boundary = datetime.fromisoformat(seed["boundary_timestamp"].replace("Z", "+00:00"))
        except (KeyError, AttributeError, TypeError, ValueError):
            raise IntakeBlocked("RSS migration seed boundary is invalid") from None
        if seed_boundary.tzinfo is None or seed_boundary.utcoffset() is None:
            raise IntakeBlocked("RSS migration seed boundary is invalid")
        if (
            type(origin) is not int
            or origin < 1
            or origin > catalog_revision
            or seed.get("endpoint") != endpoint
            or seed.get("cursor_shape") != "generic"
            or type(seed.get("proposed_anchor")) is not str
            or not _DIGEST.fullmatch(seed["proposed_anchor"])
            or type(digest) is not str
            or not _DIGEST.fullmatch(digest)
        ):
            raise IntakeBlocked("RSS migration cursor provenance is invalid")
        seed_origins.add(origin)
        snapshot_digests.add(digest)
        try:
            _load_validators(root, endpoint_id)
        except (IntakeBlocked, OSError, ValueError):
            raise IntakeBlocked("RSS migration validators are invalid") from None
    if len(seed_origins) != 1 or len(snapshot_digests) != 1:
        raise IntakeBlocked("RSS migration cursors do not share one legacy seed origin")

    _require_rss_transition_chain(
        root,
        next(iter(seed_origins)),
        catalog_revision,
        projection_sha256,
        watch_config_revision,
    )


def endpoints(snapshot: dict[str, Any], loaded_config: Any) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    from config import FEEDS
    if type(loaded_config.revision) is not int or loaded_config.revision < 1:
        raise IntakeBlocked("Stockbit requires a validated live configuration revision")
    feeds = {feed.lane.value: feed for feed in FEEDS}
    configured = {setting.lane.value: setting.enabled for setting in loaded_config.config.feeds}
    if set(configured) != set(feeds):
        raise IntakeBlocked("Stockbit must retain exactly four fixed lanes")
    bindings = {f"rss:stockbit:{lane}": {"platform": "rss", "publisher_id": "stockbit", "address": feed.url, "provider_id": lane} for lane, feed in feeds.items() if configured[lane]}
    selected = select_endpoints(snapshot, "rss", bindings, ALLOWED)
    if set(selected) != set(bindings):
        raise IntakeBlocked("Stockbit catalog and live enabled lanes differ")
    return selected, feeds


def _item(article: Any, loaded_config: Any) -> dict[str, Any]:
    payload = article.to_payload()
    # Stockbit intake is text-only. Thumbnail/enclosure URLs are optional RSS
    # metadata: never fetch or carry them into accepted source events.
    payload.pop("media_url", None)
    watch = loaded_config.config
    frozen = {
        "revision": loaded_config.revision,
        "additional_prompt_instruction": watch.additional_prompt_instruction,
        "id_stocks_news_channel_id": watch.id_stocks_news_channel_id,
        "macro_news_channel_id": watch.macro_news_channel_id,
    }
    return {"provider_event_id": hashlib.sha256(article.guid.encode("utf-8")).hexdigest(), "published_at": article.published_at.isoformat(), "source_url": article.url, "payload": {"article": payload, "watch_config_revision": loaded_config.revision, "watch_config_snapshot": frozen}, "media_required": False, "media_refs": []}


def _validate_live_page(articles: Any, feed: Any, cursor: dict[str, Any] | None) -> tuple[Any, ...]:
    if type(articles) not in {tuple, list} or len(articles) > 20:
        raise IntakeBlocked("Stockbit RSS page is not a bounded ordered page")
    values = tuple(articles)
    identities: list[tuple[datetime, str]] = []
    provider_ids: set[str] = set()
    for article in values:
        published_at = getattr(article, "published_at", None)
        guid = getattr(article, "guid", None)
        if (
            getattr(article, "lane", None) != feed.lane
            or not isinstance(published_at, datetime)
            or published_at.tzinfo is None
            or published_at.utcoffset() is None
            or type(guid) is not str
            or not guid.strip()
            or len(guid) > 4096
        ):
            raise IntakeBlocked("Stockbit RSS page contains an invalid lane identity")
        provider_ids.add(hashlib.sha256(guid.encode("utf-8")).hexdigest())
        identities.append((published_at, guid))
    if any(identities[index] < identities[index + 1] for index in range(len(identities) - 1)):
        raise IntakeBlocked("Stockbit RSS page is not ordered by publication time and GUID")
    if len(provider_ids) != len(identities):
        raise IntakeBlocked("Stockbit RSS page contains duplicate GUIDs")
    if cursor is not None and type(cursor.get("anchor")) is str and cursor.get("anchor") not in provider_ids:
        boundary_text = cursor.get("boundary_published_at")
        if type(boundary_text) is str:
            try:
                boundary = datetime.fromisoformat(boundary_text.replace("Z", "+00:00"))
            except ValueError:
                raise IntakeBlocked("Stockbit RSS cursor boundary is invalid") from None
            if boundary.tzinfo is None or boundary.utcoffset() is None:
                raise IntakeBlocked("Stockbit RSS cursor boundary is invalid")
            if any(published_at == boundary for published_at, _guid in identities):
                raise IntakeBlocked("Stockbit RSS page cannot order a tied timestamp without the cursor")
    return values


def run_once(snapshot: dict[str, Any], loaded_config: Any, state_root: Path, inbox: Any, observed_at: datetime, *, fetch_feed: Any = None) -> list[dict[str, Any]]:
    selected, feeds = endpoints(snapshot, loaded_config)
    bind_catalog_revision(state_root, snapshot["revision"])
    _bind_revision(state_root, loaded_config.revision)
    if fetch_feed is None:
        from rss import fetch_feed as fetch_feed_impl
        fetch_feed = fetch_feed_impl
    fetchers = {}
    received_validators: dict[str, dict[str, str | None]] = {}
    fetched_counts: dict[str, int] = {}
    for endpoint_id, endpoint in selected.items():
        feed = feeds[endpoint["provider_id"]]
        def fetch(_cursor: dict[str, Any] | None, feed: Any = feed, endpoint_id: str = endpoint_id) -> dict[str, Any]:
            validators = _load_validators(state_root, endpoint_id)
            result = fetch_feed(
                feed,
                page=1,
                etag=validators["etag"],
                last_modified=validators["last_modified"],
                provider_order=True,
            )
            if result.not_modified:
                if getattr(result, "articles", ()) not in ((), []):
                    raise IntakeBlocked("Stockbit 304 response contains page items")
                fetched_counts[endpoint_id] = 0
                return {"items": [], "truncated": False, "contiguous": False}
            raw_articles = getattr(result, "articles", None)
            fetched_counts[endpoint_id] = len(raw_articles) if type(raw_articles) in {tuple, list} else 0
            cursor_path = state_root / endpoint_id.replace(":", "-") / "cursor.json"
            articles = _validate_live_page(raw_articles, feed, _load_cursor_record(cursor_path))
            received_validators[endpoint_id] = {
                "etag": _header_value(getattr(result, "etag", None), "ETag"),
                "last_modified": _header_value(getattr(result, "last_modified", None), "Last-Modified"),
            }
            # The optional parser flag preserves the XML item order. Stockbit
            # presents newest first, so reverse once for oldest-first handoff.
            return {"items": [_item(article, loaded_config) for article in reversed(articles)], "truncated": len(articles) >= 20, "contiguous": False}
        fetchers[endpoint_id] = fetch
    outcomes = ingest_all(selected, fetchers, state_root, inbox, observed_at, "stockbit-rss-parser-1")
    successful = {"accepted", "empty", "bootstrapped", "bootstrapped_empty"}
    for outcome in outcomes:
        endpoint_id = outcome.get("endpoint_id")
        outcome["fetched"] = fetched_counts.get(endpoint_id, 0)
        if outcome.get("status") not in successful or endpoint_id not in received_validators:
            continue
        _write(
            _validator_path(state_root, endpoint_id),
            {"version": _VALIDATOR_VERSION, **received_validators[endpoint_id]},
        )
    return outcomes
