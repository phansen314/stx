from __future__ import annotations

import importlib.resources
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "sticky-notes" / "sticky-notes.db"


def read_schema() -> str:
    return (
        importlib.resources.files("sticky_notes").joinpath("schema.sql").read_text()
    )


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level="DEFERRED")
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
    except Exception:
        conn.close()
        raise
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    schema = read_schema()
    with transaction(conn):
        for statement in schema.split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(statement)


@contextmanager
def transaction(
    conn: sqlite3.Connection,
) -> Generator[sqlite3.Connection, None, None]:
    if conn.in_transaction:
        raise RuntimeError("Cannot nest transactions; already inside a transaction")
    conn.execute("BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception as rollback_exc:
            raise exc from rollback_exc
        raise
