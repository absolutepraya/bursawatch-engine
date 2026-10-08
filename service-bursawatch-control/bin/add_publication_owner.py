#!/usr/bin/env python3
"""Append one owner, with its own reviewed boundary, to the existing publication cutover."""

from __future__ import annotations

import argparse
import os
import sys

from control_plane.publication_store import PostgresPublicationStore, PublicationConflict


def add_owner(owner_id: str, boundary: str, dsn: str) -> None:
    if not dsn:
        raise ValueError("DATABASE_URL is required")
    PostgresPublicationStore(dsn).add_owner(owner_id, boundary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True, help="Declared owner identity from publication_model.OWNER_ROUTES")
    parser.add_argument("--boundary", required=True, help="Reviewed aware ISO timestamp; only later delivery counts")
    args = parser.parse_args(argv)
    try:
        add_owner(args.owner, args.boundary, os.environ.get("DATABASE_URL", ""))
    except (ValueError, PublicationConflict) as exc:
        print(f"publication owner addition refused: {exc}", file=sys.stderr)
        return 1
    print("publication owner added to the cutover set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
