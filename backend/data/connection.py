"""
Database connection helper for the BonusReport data layer.

Single source of truth for opening psycopg connections to the
Postgres database. Reads DATABASE_URL from a .env file at project
root (or from the actual environment if .env is absent — production
deploys typically set it via the runtime, not a file).

Usage:
    from data.connection import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM ref_staff")
            print(cur.fetchone())

Design notes:
  - We use a context manager so connections always close, even if
    an exception fires mid-query.
  - We do NOT cache or pool connections. The data layer is invoked
    once per run (load ReferenceData → run engine → write output).
    Pool complexity isn't earned yet.
  - The dict_row factory makes cursor.fetchone() / fetchall() return
    dicts instead of tuples. Matches how engine code expects
    ReferenceData entries (each row is dict-shaped, not positional).
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv


# Load .env at module import time. Idempotent — calling load_dotenv
# multiple times is harmless. If a .env file isn't found, this
# silently does nothing and we fall back to whatever DATABASE_URL
# is already set in the environment (e.g. on Railway).
load_dotenv()


class DatabaseUrlMissingError(RuntimeError):
    """DATABASE_URL is neither in .env nor in the environment."""


def _get_database_url() -> str:
    """Read DATABASE_URL or fail loudly. Never returns empty."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise DatabaseUrlMissingError(
            "DATABASE_URL is not set. Either add it to backend/.env "
            "or set it in your environment before running."
        )
    return url


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    """
    Open a psycopg connection, yield it, then close it.

    All cursors opened from the yielded connection use dict_row, so
    cur.fetchone() returns a dict like {'id': 1, 'name': '...'} not
    a tuple.

    Yields:
        An open psycopg.Connection. Auto-closed on exit (success or
        exception).

    Raises:
        DatabaseUrlMissingError: DATABASE_URL not set anywhere.
        psycopg.OperationalError: connection failed (network, auth,
            etc.) — propagated from psycopg unchanged.
    """
    conn = psycopg.connect(_get_database_url(), row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Smoke test — `python -m data.connection` runs this.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    current_database() AS db,
                    current_user        AS usr,
                    inet_server_port()  AS port
            """)
            row = cur.fetchone()
            print(f"Connected to: {row['db']} as {row['usr']} (port {row['port']})")

            cur.execute("SELECT count(*) AS n FROM ref_staff")
            print(f"ref_staff rows: {cur.fetchone()['n']}")

            cur.execute("""
                SELECT count(*) AS n
                FROM information_schema.tables
                WHERE table_schema = 'public'
            """)
            print(f"public schema tables: {cur.fetchone()['n']}")
