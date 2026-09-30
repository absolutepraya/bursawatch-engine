#!/usr/bin/env python3
"""Record the one reviewed forward-only publication boundary on the host."""

from __future__ import annotations

import argparse
import os
import sys

from control_plane.publication_model import OWNER_ROUTES
from control_plane.publication_store import PostgresPublicationStore, PublicationConflict


def activate(boundary: str, dsn: str) -> None:
    if not dsn:
        raise ValueError("DATABASE_URL is required")
    PostgresPublicationStore(dsn).activate(boundary, tuple(OWNER_ROUTES))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boundary", required=True, help="Reviewed aware ISO timestamp; records the forward-only start")
    args = parser.parse_args(argv)
    try:
        activate(args.boundary, os.environ.get("DATABASE_URL", ""))
    except (ValueError, PublicationConflict) as exc:
        print(f"publication activation refused: {exc}", file=sys.stderr)
        return 1
    print("publication cutover recorded for the fixed owner set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
