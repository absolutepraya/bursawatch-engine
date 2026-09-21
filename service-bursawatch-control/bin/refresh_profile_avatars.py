#!/usr/bin/env python3
"""Refresh stale automatic profile avatar URLs in the private control-plane DB."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import os
import sys

from control_plane.profile_metadata import (
    AvatarResolutionError,
    ProfileMetadataInput,
    RssHubAvatarResolver,
    profile_inputs_from_config,
)
from control_plane.store import PostgresStore, ProfileAvatarRecord


DEFAULT_STALE_AFTER_SECONDS = 86_400


def _stale(record: ProfileAvatarRecord, cutoff: datetime) -> bool:
    if record.last_success_at is None:
        return True
    try:
        fetched_at = datetime.fromisoformat(record.last_success_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if fetched_at.tzinfo is None:
        return True
    return fetched_at <= cutoff


def _refresh_one(store: PostgresStore, resolver: RssHubAvatarResolver, record: ProfileAvatarRecord) -> bool:
    profile = ProfileMetadataInput(
        profile_id=record.profile_id,
        handle=record.handle,
        display_name=record.display_name,
        profile_url=record.profile_url,
        enabled=record.enabled,
    )
    try:
        resolution = resolver.resolve(profile)
        store.record_profile_avatar_success(
            record.watcher_id,
            record.profile_id,
            resolution.url,
            resolution.source,
            record.handle,
            record.profile_url,
        )
        return True
    except (AvatarResolutionError, KeyError, ValueError) as exc:
        store.record_profile_avatar_failure(
            record.watcher_id,
            record.profile_id,
            str(exc),
            record.handle,
            record.profile_url,
        )
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=int(os.environ.get("CONTROL_PLANE_AVATAR_REFRESH_STALE_SECONDS", DEFAULT_STALE_AFTER_SECONDS)),
        help="refresh automatic avatars with no success or a success older than this interval",
    )
    parser.add_argument("--watcher-id", help="refresh one watcher instead of the full catalog")
    args = parser.parse_args()

    if not 60 <= args.stale_after_seconds <= 31_536_000:
        parser.error("--stale-after-seconds must be between 60 and 31536000")
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        print("avatar refresh refused: DATABASE_URL is required", file=sys.stderr)
        return 1

    store = PostgresStore(dsn)
    resolver = RssHubAvatarResolver.from_environment()
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=args.stale_after_seconds)
    watcher_ids = [args.watcher_id] if args.watcher_id else [item.watcher_id for item in store.list_watchers()]

    refreshed = 0
    skipped = 0
    failed = 0
    for watcher_id in watcher_ids:
        try:
            snapshot = store.get_config(watcher_id)
            profiles = profile_inputs_from_config(snapshot.config)
            records = store.sync_profile_metadata(watcher_id, profiles)
        except (KeyError, ValueError) as exc:
            print(f"{watcher_id}: skipped: {exc}")
            skipped += 1
            continue
        for record in records:
            if record.avatar_mode != "auto" or not _stale(record, cutoff):
                skipped += 1
                continue
            if _refresh_one(store, resolver, record):
                refreshed += 1
                print(f"{watcher_id}/{record.profile_id}: refreshed")
            else:
                failed += 1
                print(f"{watcher_id}/{record.profile_id}: failed")

    print(f"avatar refresh: refreshed={refreshed} skipped={skipped} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
