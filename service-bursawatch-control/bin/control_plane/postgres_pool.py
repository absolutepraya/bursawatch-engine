"""Bounded, process-local Postgres connections for the long-lived API."""

from __future__ import annotations


def create_postgres_pool(dsn: str):
    try:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
    except ImportError as exc:
        raise RuntimeError("psycopg with pool support is required for the Postgres API") from exc

    # The API runs as one Uvicorn process. The inbox may borrow a catalog
    # connection while holding its own transaction, so one slot is insufficient.
    # Supavisor transaction mode does not support server-side prepared statements.
    return ConnectionPool(
        conninfo=dsn,
        min_size=1,
        max_size=4,
        timeout=10.0,
        open=False,
        kwargs={"row_factory": dict_row, "prepare_threshold": None},
    )
