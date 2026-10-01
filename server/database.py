"""Small database adapter used by the Master Clip API.

SQLite remains available for local development.  Render uses DATABASE_URL and
therefore PostgreSQL/Supabase.  The adapter deliberately presents the narrow
DB-API surface this service needs, while converting SQLite-style placeholders
to PostgreSQL placeholders in one audited place.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


class PostgresConnection:
    def __init__(self, url: str):
        self.raw = psycopg.connect(url, row_factory=dict_row)

    def execute(self, statement: str, parameters: tuple[Any, ...] = ()):
        return self.raw.execute(statement.replace("?", "%s"), parameters)

    def executescript(self, script: str) -> None:
        # Schema statements contain no functions/procedural bodies, so this is
        # safe and keeps SQLite and PostgreSQL bootstrap definitions aligned.
        for statement in script.split(";"):
            if statement.strip():
                self.raw.execute(statement)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type:
            self.raw.rollback()
        else:
            self.raw.commit()
        self.raw.close()


def connection(sqlite_path: Path):
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return PostgresConnection(url)
    database = sqlite3.connect(sqlite_path)
    database.row_factory = sqlite3.Row
    return database


def is_postgres() -> bool:
    return bool(os.getenv("DATABASE_URL", "").strip())
