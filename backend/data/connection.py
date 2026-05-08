"""
backend/data/connection.py

Database connection for the BonusReport engine.

Loads DATABASE_URL from backend/.env using an ABSOLUTE path computed from
this file's own location, so it works regardless of the caller's working
directory (engine CLI, FastAPI, tests, scripts run from anywhere).
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv


# Compute backend/.env path relative to THIS file, not the caller's CWD.
#   this file lives at: backend/data/connection.py
#   .parent          -> backend/data/
#   .parent.parent   -> backend/
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)


def get_connection() -> psycopg.Connection:
    """
    Open a psycopg connection to the BonusReport database.

    Caller manages the connection lifecycle (use as a context manager).
    Cursor factory is dict_row, so result rows behave as dicts.
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            f"DATABASE_URL is not set. Either add it to {_ENV_PATH} "
            f"or set it in your environment before running."
        )
    return psycopg.connect(database_url, row_factory=dict_row)
