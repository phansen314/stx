from __future__ import annotations

import importlib.resources
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "sticky-notes" / "sticky-notes.db"

SCHEMA_VERSION = 6


def read_schema() -> str:
    from .models import TaskField

    raw = importlib.resources.files("sticky_notes").joinpath("schema.sql").read_text()
    task_field_values = ", ".join(f"'{f.value}'" for f in TaskField)
    result = raw.replace("__TASK_FIELD_VALUES__", task_field_values)
    if "__TASK_FIELD_VALUES__" in result:
        raise AssertionError(
            "schema.sql placeholder __TASK_FIELD_VALUES__ was not replaced; "
            "was the placeholder renamed in schema.sql?"
        )
    return result


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
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current == 0:
        with transaction(conn):
            for statement in schema.split(";"):
                statement = statement.strip()
                if statement:
                    conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    else:
        _run_migrations(conn)


# ---- Migration framework ----


def _reenable_fks(conn: sqlite3.Connection) -> None:
    """Re-enable foreign keys after a migration and validate existing data."""
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(
            f"Foreign key violations after migration: {violations!r}"
        )


def _read_migration(version: int) -> str:
    """Read a numbered SQL migration file from the migrations package."""
    pkg = importlib.resources.files("sticky_notes.migrations")
    prefix = f"{version:03d}_"
    for resource in pkg.iterdir():
        if resource.name.startswith(prefix) and resource.name.endswith(".sql"):
            return resource.read_text()
    raise FileNotFoundError(f"No migration file found for version {version}")


def _run_migrations(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema version {current} is newer than this "
            f"build ({SCHEMA_VERSION}); refusing to downgrade"
        )
    for target_version in range(current + 1, SCHEMA_VERSION + 1):
        sql = _read_migration(target_version)
        conn.execute("PRAGMA foreign_keys = OFF")
        with transaction(conn):
            for statement in sql.split(";"):
                statement = statement.strip()
                if statement:
                    conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {target_version}")
        _reenable_fks(conn)


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
