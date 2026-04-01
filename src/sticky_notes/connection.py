from __future__ import annotations

import importlib.resources
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "sticky-notes" / "sticky-notes.db"

SCHEMA_VERSION = 1

type Migration = tuple[int, Callable[[sqlite3.Connection], None]]


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
    _run_migrations(conn)


# ---- Migration framework ----


def _run_migrations(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for target_version, migrate_fn in MIGRATIONS:
        if current < target_version:
            migrate_fn(conn)
            conn.execute(f"PRAGMA user_version = {target_version}")
            current = target_version
    if current < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _migrate_001_task_history_group_id(conn: sqlite3.Connection) -> None:
    """Recreate task_history if its CHECK constraint is missing 'group_id'.

    The CREATE TABLE DDL below is a point-in-time snapshot of the task_history
    schema at version 1. Do not update it to match future schema changes —
    later migrations handle those independently.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='task_history'"
    ).fetchone()
    if row is None:
        return
    ddl: str = row[0]
    if "'group_id'" in ddl:
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    with transaction(conn):
        conn.execute("ALTER TABLE task_history RENAME TO _task_history_old")
        conn.execute(
            "CREATE TABLE task_history ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  task_id INTEGER NOT NULL REFERENCES tasks(id),"
            "  field TEXT NOT NULL CHECK (field IN ("
            "    'title', 'description', 'column_id', 'project_id',"
            "    'priority', 'due_date', 'position', 'archived',"
            "    'start_date', 'finish_date', 'group_id'"
            "  )),"
            "  old_value TEXT,"
            "  new_value TEXT NOT NULL,"
            "  source TEXT NOT NULL,"
            "  changed_at INTEGER NOT NULL DEFAULT (unixepoch())"
            ")"
        )
        conn.execute(
            "INSERT INTO task_history (id, task_id, field, old_value, new_value, source, changed_at) "
            "SELECT id, task_id, field, old_value, new_value, source, changed_at FROM _task_history_old"
        )
        conn.execute("DROP TABLE _task_history_old")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_history_task_id ON task_history(task_id)"
        )
    conn.execute("PRAGMA foreign_keys = ON")


MIGRATIONS: list[Migration] = [
    (1, _migrate_001_task_history_group_id),
]


# ---- Transaction helper ----


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
