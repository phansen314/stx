from __future__ import annotations

import importlib.resources
import sqlite3
import sys
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

_OLD_DB_DIR = Path.home() / ".local" / "share" / "sticky-notes"
_NEW_DB_DIR = Path.home() / ".local" / "share" / "stx"
DEFAULT_DB_PATH = _NEW_DB_DIR / "stx.db"


def _migrate_data_dir() -> None:
    if _OLD_DB_DIR.exists() and not _NEW_DB_DIR.exists():
        _OLD_DB_DIR.rename(_NEW_DB_DIR)
        print(f"stx: migrated data directory {_OLD_DB_DIR} → {_NEW_DB_DIR}", file=sys.stderr)


SCHEMA_VERSION = 23


def _strip_line_comment(line: str) -> str:
    """Remove ``-- ...`` trailing comments without breaking `--` inside strings.

    Walks the line tracking whether we are inside a single-quoted string
    literal (doubled `''` escape handled naturally by the toggle). Returns
    the line truncated at the first out-of-string `--`.
    """
    in_str = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "'":
            in_str = not in_str
        elif not in_str and ch == "-" and i + 1 < len(line) and line[i + 1] == "-":
            return line[:i]
        i += 1
    return line


def _split_sql_statements(sql: str) -> list[str]:
    """Split a SQL script into individual statements.

    Uses ``sqlite3.complete_statement`` so semicolons inside string literals
    do not slice a statement mid-definition. Line comments (``-- ...``) are
    stripped before accumulation since ``complete_statement`` is not
    comment-aware.
    """
    statements: list[str] = []
    buf = ""
    for line in sql.splitlines(keepends=True):
        buf += _strip_line_comment(line)
        if sqlite3.complete_statement(buf):
            stmt = buf.strip()
            if stmt:
                statements.append(stmt)
            buf = ""
    tail = buf.strip()
    if tail:
        statements.append(tail)
    return statements


def read_schema() -> str:
    return importlib.resources.files("stx").joinpath("schema.sql").read_text()


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    _migrate_data_dir()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level="DEFERRED")
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
    except Exception:
        conn.close()
        raise
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    schema = read_schema()
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current == 0:
        with transaction(conn):
            for statement in _split_sql_statements(schema):
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
        raise RuntimeError(f"Foreign key violations after migration: {violations!r}")


def _read_migration(version: int) -> str:
    """Read a numbered SQL migration file from the migrations package."""
    pkg = importlib.resources.files("stx.migrations")
    prefix = f"{version:03d}_"
    for resource in pkg.iterdir():
        if resource.name.startswith(prefix) and resource.name.endswith(".sql"):
            return resource.read_text()
    raise FileNotFoundError(f"No migration file found for version {version}")


def _pre_migration_check(conn: sqlite3.Connection, target_version: int) -> None:
    """Per-version pre-flight validation before running a migration.

    Runs while the existing schema is still intact so any precondition
    failure can be surfaced with a clear, actionable error before any
    destructive DDL executes.
    """
    if target_version == 11:
        # Migration 011 adds CHECK (json_valid(metadata)) to tasks via a
        # cascade-recreate. Any existing row with invalid JSON would fail
        # the INSERT INTO tasks_new step with an opaque "CHECK constraint
        # failed" error. Surface a clearer message instead.
        bad = conn.execute("SELECT id FROM tasks WHERE NOT json_valid(metadata) LIMIT 1").fetchone()
        if bad is not None:
            raise RuntimeError(
                f"Cannot migrate to schema version 11: task id={bad[0]} has "
                f"invalid JSON in its metadata column. Fix or clear the row "
                f"before retrying the migration."
            )
        # Same migration also retroactively adds CHECK (field IN (...)) to
        # task_history.field. That constraint was dropped in migration 008
        # and could contain off-allowlist values if the DB was manipulated
        # via raw SQL between 008 and now. Pre-check symmetrically.
        allowed_fields = (
            "title",
            "description",
            "status_id",
            "project_id",
            "priority",
            "due_date",
            "position",
            "archived",
            "start_date",
            "finish_date",
            "group_id",
        )
        placeholders = ",".join("?" * len(allowed_fields))
        bad_hist = conn.execute(
            f"SELECT id, field FROM task_history WHERE field NOT IN ({placeholders}) LIMIT 1",
            allowed_fields,
        ).fetchone()
        if bad_hist is not None:
            raise RuntimeError(
                f"Cannot migrate to schema version 11: task_history id={bad_hist[0]} "
                f"has off-allowlist field value {bad_hist[1]!r}. Expected one of: "
                f"{', '.join(allowed_fields)}."
            )


def _python_migration_022(conn: sqlite3.Connection) -> None:
    """Rename group/task titles containing '/' or ':' to '__' equivalents.

    Path syntax (introduced in 0.15) reserves both characters as delimiters.
    Pre-existing rows are migrated in-place before the CHECK in schema.sql
    starts applying to fresh DBs. Collisions with the renamed value (or with
    each other) get a deterministic ``__N`` suffix; N is the lowest free
    integer ≥ 2 within the row's uniqueness scope.

    Each rename is journaled with ``source='migration:022'`` and bumps
    ``version`` so any in-flight CAS reader observes the change.
    """

    def _suffix_until_free(
        base: str,
        is_taken: Callable[[str], bool],
    ) -> str:
        if not is_taken(base):
            return base
        n = 2
        while is_taken(f"{base}__{n}"):
            n += 1
        return f"{base}__{n}"

    # Groups: scope = (workspace_id, COALESCE(parent_id, -1)) among non-archived.
    rows = conn.execute(
        "SELECT id, workspace_id, parent_id, title "
        "FROM groups WHERE archived = 0 AND (title LIKE '%/%' OR title LIKE '%:%') "
        "ORDER BY id"
    ).fetchall()
    for r in rows:
        gid, wsid, parent_id, old_title = r["id"], r["workspace_id"], r["parent_id"], r["title"]
        base = old_title.replace("/", "__").replace(":", "__")
        parent_clause = "parent_id IS NULL" if parent_id is None else "parent_id = ?"
        params: tuple = (wsid, gid) if parent_id is None else (wsid, parent_id, gid)

        def is_taken(candidate: str, _params=params, _clause=parent_clause) -> bool:
            row = conn.execute(
                f"SELECT 1 FROM groups WHERE workspace_id = ? AND {_clause} "
                f"AND archived = 0 AND id != ? AND title = ? LIMIT 1",
                (*_params, candidate),
            ).fetchone()
            return row is not None

        new_title = _suffix_until_free(base, is_taken)
        conn.execute(
            "UPDATE groups SET title = ?, version = version + 1 WHERE id = ?",
            (new_title, gid),
        )
        conn.execute(
            "INSERT INTO journal (entity_type, entity_id, workspace_id, "
            "field, old_value, new_value, source) "
            "VALUES ('group', ?, ?, 'title', ?, ?, 'migration:022')",
            (gid, wsid, old_title, new_title),
        )

    # Tasks: scope = workspace_id among non-archived.
    rows = conn.execute(
        "SELECT id, workspace_id, title FROM tasks "
        "WHERE archived = 0 AND (title LIKE '%/%' OR title LIKE '%:%') "
        "ORDER BY id"
    ).fetchall()
    for r in rows:
        tid, wsid, old_title = r["id"], r["workspace_id"], r["title"]
        base = old_title.replace("/", "__").replace(":", "__")

        def is_taken(candidate: str, _wsid=wsid, _tid=tid) -> bool:
            row = conn.execute(
                "SELECT 1 FROM tasks WHERE workspace_id = ? AND archived = 0 "
                "AND id != ? AND title = ? LIMIT 1",
                (_wsid, _tid, candidate),
            ).fetchone()
            return row is not None

        new_title = _suffix_until_free(base, is_taken)
        conn.execute(
            "UPDATE tasks SET title = ?, version = version + 1 WHERE id = ?",
            (new_title, tid),
        )
        conn.execute(
            "INSERT INTO journal (entity_type, entity_id, workspace_id, "
            "field, old_value, new_value, source) "
            "VALUES ('task', ?, ?, 'title', ?, ?, 'migration:022')",
            (tid, wsid, old_title, new_title),
        )


_PYTHON_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    22: _python_migration_022,
}


def _run_migrations(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema version {current} is newer than this "
            f"build ({SCHEMA_VERSION}); refusing to downgrade"
        )
    for target_version in range(current + 1, SCHEMA_VERSION + 1):
        _pre_migration_check(conn, target_version)
        sql = _read_migration(target_version)
        py_hook = _PYTHON_MIGRATIONS.get(target_version)
        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            with transaction(conn):
                if py_hook is not None:
                    py_hook(conn)
                for statement in _split_sql_statements(sql):
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {target_version}")
            _reenable_fks(conn)
        except Exception:
            # Ensure FK enforcement is restored on the connection even when
            # the migration itself failed. The transaction has already rolled
            # back, so we skip the foreign_key_check validation (the pre-
            # migration state was consistent and nothing changed).
            conn.execute("PRAGMA foreign_keys = ON")
            raise


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
