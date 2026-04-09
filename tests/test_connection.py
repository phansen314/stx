from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest

from helpers import insert_workspace, insert_status, insert_task
from sticky_notes.connection import (
    SCHEMA_VERSION,
    _run_migrations,
    get_connection,
    init_db,
    transaction,
)


class TestGetConnection:
    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "test.db"
        c = get_connection(nested)
        assert nested.parent.exists()
        c.close()

    def test_row_factory_is_sqlite_row(self, conn: sqlite3.Connection) -> None:
        assert conn.row_factory is sqlite3.Row

    def test_foreign_keys_enabled(self, conn: sqlite3.Connection) -> None:
        result = conn.execute("PRAGMA foreign_keys").fetchone()
        assert result[0] == 1

    def test_wal_mode(self, conn: sqlite3.Connection) -> None:
        result = conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0] == "wal"


class TestInitDb:
    def test_tables_created(self, conn: sqlite3.Connection) -> None:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        assert tables == {
            "workspaces", "projects", "statuses",
            "tasks", "task_dependencies", "task_history",
            "tags", "task_tags",
            "groups", "group_dependencies",
        }

    def test_idempotent(self, conn: sqlite3.Connection) -> None:
        init_db(conn)  # second call should not raise

    def test_fresh_db_sets_user_version(self, conn: sqlite3.Connection) -> None:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION

    def test_idempotent_preserves_user_version(self, conn: sqlite3.Connection) -> None:
        init_db(conn)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION


class TestTransaction:
    def test_commit_on_success(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            conn.execute("INSERT INTO workspaces (name) VALUES ('test')")
        row = conn.execute(
            "SELECT name FROM workspaces WHERE name = 'test'",
        ).fetchone()
        assert row is not None
        assert row["name"] == "test"

    def test_rollback_on_exception(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError):
            with transaction(conn):
                conn.execute("INSERT INTO workspaces (name) VALUES ('rollback_test')")
                raise ValueError("boom")
        row = conn.execute(
            "SELECT name FROM workspaces WHERE name = 'rollback_test'",
        ).fetchone()
        assert row is None

    def test_nested_transaction_not_allowed(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            conn.execute("INSERT INTO workspaces (name) VALUES ('outer')")
            with pytest.raises(RuntimeError, match="Cannot nest transactions"):
                with transaction(conn):
                    pass
        # Outer transaction should still have committed successfully
        row = conn.execute(
            "SELECT name FROM workspaces WHERE name = 'outer'"
        ).fetchone()
        assert row is not None
        assert row["name"] == "outer"

    def test_rollback_failure_chains_exceptions(self, conn: sqlite3.Connection) -> None:
        """Verify raise exc from rollback_exc pattern in transaction()."""

        class FailingRollbackConn:
            """Proxy that fails on ROLLBACK but delegates everything else."""

            def __init__(self, real_conn: sqlite3.Connection) -> None:
                self._real = real_conn
                self._fail_rollback = False

            def __getattr__(self, name: str):
                return getattr(self._real, name)

            def execute(self, sql, *args, **kwargs):
                if self._fail_rollback and sql == "ROLLBACK":
                    raise OSError("disk full")
                return self._real.execute(sql, *args, **kwargs)

        proxy = FailingRollbackConn(conn)

        with pytest.raises(ValueError, match="boom") as exc_info:
            with transaction(proxy):  # type: ignore[arg-type]
                proxy.execute("INSERT INTO workspaces (name) VALUES ('rb_test')")
                proxy._fail_rollback = True
                raise ValueError("boom")

        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, OSError)
        assert "disk full" in str(exc_info.value.__cause__)


class TestSelfDependencyConstraint:
    def test_task_cannot_depend_on_itself(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn, "b")
            col_id = insert_status(conn, workspace_id, "col")
            task_id = insert_task(conn, workspace_id, "t", col_id)
        with pytest.raises(sqlite3.IntegrityError):
            with transaction(conn):
                conn.execute(
                    "INSERT INTO task_dependencies (task_id, depends_on_id) "
                    "VALUES (?, ?)",
                    (task_id, task_id),
                )

    def test_valid_dependency_allowed(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn, "b")
            col_id = insert_status(conn, workspace_id, "col")
            t1 = insert_task(conn, workspace_id, "t1", col_id)
            t2 = insert_task(conn, workspace_id, "t2", col_id)
        with transaction(conn):
            conn.execute(
                "INSERT INTO task_dependencies (task_id, depends_on_id, workspace_id) "
                "VALUES (?, ?, ?)",
                (t1, t2, workspace_id),
            )
        row = conn.execute("SELECT * FROM task_dependencies").fetchone()
        assert row["task_id"] == t1
        assert row["depends_on_id"] == t2


class TestStatusArchived:
    def test_status_has_archived_default_zero(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn, "b")
            insert_status(conn, workspace_id, "col")
        row = conn.execute(
            "SELECT archived FROM statuses WHERE name = 'col'",
        ).fetchone()
        assert row["archived"] == 0

    def test_status_archived_can_be_set(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn, "b")
            conn.execute(
                "INSERT INTO statuses (workspace_id, name, archived) VALUES (?, 'col', 1)",
                (workspace_id,),
            )
        row = conn.execute(
            "SELECT archived FROM statuses WHERE name = 'col'",
        ).fetchone()
        assert row["archived"] == 1


class TestForeignKeyEnforcement:
    def test_rejects_task_with_nonexistent_workspace(
        self, conn: sqlite3.Connection,
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            with transaction(conn):
                conn.execute(
                    "INSERT INTO statuses (workspace_id, name) VALUES (999, 'col')",
                )

    def test_rejects_task_with_nonexistent_status(
        self, conn: sqlite3.Connection,
    ) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn, "b")
        with pytest.raises(sqlite3.IntegrityError):
            with transaction(conn):
                conn.execute(
                    "INSERT INTO tasks (workspace_id, title, status_id) "
                    "VALUES (?, 't', 999)",
                    (workspace_id,),
                )


class TestCrossWorkspaceConstraints:
    def test_dependency_same_workspace_allowed(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "b")
            cid = insert_status(conn, bid)
            t1 = insert_task(conn, bid, "t1", cid)
            t2 = insert_task(conn, bid, "t2", cid)
        with transaction(conn):
            conn.execute(
                "INSERT INTO task_dependencies (task_id, depends_on_id, workspace_id) "
                "VALUES (?, ?, ?)",
                (t1, t2, bid),
            )
        row = conn.execute("SELECT * FROM task_dependencies").fetchone()
        assert row["task_id"] == t1
        assert row["depends_on_id"] == t2
        assert row["workspace_id"] == bid

    def test_dependency_cross_workspace_rejected(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            b1 = insert_workspace(conn, "b1")
            b2 = insert_workspace(conn, "b2")
            c1 = insert_status(conn, b1)
            c2 = insert_status(conn, b2)
            t1 = insert_task(conn, b1, "t1", c1)
            t2 = insert_task(conn, b2, "t2", c2)
        with pytest.raises(sqlite3.IntegrityError):
            with transaction(conn):
                conn.execute(
                    "INSERT INTO task_dependencies (task_id, depends_on_id, workspace_id) "
                    "VALUES (?, ?, ?)",
                    (t1, t2, b1),
                )

    def test_tag_same_workspace_allowed(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "b")
            cid = insert_status(conn, bid)
            tid = insert_task(conn, bid, "t", cid)
            tag_id = conn.execute(
                "INSERT INTO tags (workspace_id, name) VALUES (?, 'bug')", (bid,)
            ).lastrowid
        with transaction(conn):
            conn.execute(
                "INSERT INTO task_tags (task_id, tag_id, workspace_id) VALUES (?, ?, ?)",
                (tid, tag_id, bid),
            )
        row = conn.execute("SELECT * FROM task_tags").fetchone()
        assert row["task_id"] == tid
        assert row["tag_id"] == tag_id
        assert row["workspace_id"] == bid

    def test_tag_cross_workspace_rejected(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            b1 = insert_workspace(conn, "b1")
            b2 = insert_workspace(conn, "b2")
            c1 = insert_status(conn, b1)
            tid = insert_task(conn, b1, "t", c1)
            tag_id = conn.execute(
                "INSERT INTO tags (workspace_id, name) VALUES (?, 'bug')", (b2,)
            ).lastrowid
        with pytest.raises(sqlite3.IntegrityError):
            with transaction(conn):
                conn.execute(
                    "INSERT INTO task_tags (task_id, tag_id, workspace_id) VALUES (?, ?, ?)",
                    (tid, tag_id, b1),
                )


class TestMigrations:
    def test_migration_001_upgrades_old_task_history(self, tmp_path: Path) -> None:
        """Simulate a v0 database with old CHECK constraint, verify migration fixes it."""
        db_path = tmp_path / "old.db"
        conn = get_connection(db_path)
        # Bootstrap a v0-era schema: tables exist but task_history has an old
        # CHECK constraint (no 'group_id').
        conn.executescript("""
            CREATE TABLE boards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT (unixepoch())
            );
            CREATE TABLE columns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL REFERENCES boards(id),
                name TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                UNIQUE (board_id, name)
            );
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL REFERENCES boards(id),
                name TEXT NOT NULL,
                description TEXT,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                UNIQUE (board_id, name)
            );
            CREATE TABLE groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                parent_id INTEGER REFERENCES groups(id),
                title TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                UNIQUE (project_id, title)
            );
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL REFERENCES boards(id),
                project_id INTEGER REFERENCES projects(id),
                title TEXT NOT NULL,
                description TEXT,
                column_id INTEGER NOT NULL REFERENCES columns(id),
                priority INTEGER NOT NULL DEFAULT 1,
                due_date INTEGER,
                position INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                start_date INTEGER,
                finish_date INTEGER,
                UNIQUE (board_id, title)
            );
            CREATE TABLE task_groups (
                task_id INTEGER PRIMARY KEY REFERENCES tasks(id),
                group_id INTEGER NOT NULL REFERENCES groups(id)
            );
            CREATE TABLE task_dependencies (
                task_id INTEGER NOT NULL REFERENCES tasks(id),
                depends_on_id INTEGER NOT NULL REFERENCES tasks(id),
                PRIMARY KEY (task_id, depends_on_id),
                CHECK (task_id != depends_on_id)
            );
            CREATE TABLE task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES tasks(id),
                field TEXT NOT NULL CHECK (field IN (
                    'title','description','column_id','project_id',
                    'priority','due_date','position','archived',
                    'start_date','finish_date'
                )),
                old_value TEXT,
                new_value TEXT NOT NULL,
                source TEXT NOT NULL,
                changed_at INTEGER NOT NULL DEFAULT (unixepoch())
            );
        """)
        # Seed data
        conn.execute("INSERT INTO boards (id, name) VALUES (1, 'b')")
        conn.execute("INSERT INTO columns (id, board_id, name) VALUES (1, 1, 'c')")
        conn.execute("INSERT INTO tasks (id, board_id, title, column_id) VALUES (1, 1, 't', 1)")
        conn.execute(
            "INSERT INTO task_history (task_id, field, new_value, source) "
            "VALUES (1, 'title', 'old', 'test')"
        )
        conn.commit()

        # Run migrations from v0
        _run_migrations(conn)

        # Verify user_version is updated
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        # Verify data preserved
        row = conn.execute("SELECT * FROM task_history WHERE task_id = 1").fetchone()
        assert row["field"] == "title"
        # Verify new CHECK allows group_id
        conn.execute(
            "INSERT INTO task_history (task_id, workspace_id, field, new_value, source) "
            "VALUES (1, 1, 'group_id', '5', 'test')"
        )
        conn.close()

    def test_migration_002_moves_task_groups_to_inline(self, tmp_path: Path) -> None:
        """Simulate a v1 database with task_groups join table, verify migration inlines group_id."""
        db_path = tmp_path / "v1.db"
        conn = get_connection(db_path)
        # Bootstrap v1 schema: tasks without group_id, task_groups join table
        conn.executescript("""
            CREATE TABLE boards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT (unixepoch())
            );
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL REFERENCES boards(id),
                name TEXT NOT NULL,
                description TEXT,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                UNIQUE (board_id, name)
            );
            CREATE TABLE columns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL REFERENCES boards(id),
                name TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                UNIQUE (board_id, name)
            );
            CREATE TABLE groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                parent_id INTEGER REFERENCES groups(id),
                title TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                UNIQUE (project_id, title)
            );
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL REFERENCES boards(id),
                project_id INTEGER REFERENCES projects(id),
                title TEXT NOT NULL,
                description TEXT,
                column_id INTEGER NOT NULL REFERENCES columns(id),
                priority INTEGER NOT NULL DEFAULT 1,
                due_date INTEGER,
                position INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                start_date INTEGER,
                finish_date INTEGER,
                UNIQUE (board_id, title)
            );
            CREATE TABLE task_groups (
                task_id INTEGER PRIMARY KEY REFERENCES tasks(id),
                group_id INTEGER NOT NULL REFERENCES groups(id)
            );
            CREATE TABLE task_dependencies (
                task_id INTEGER NOT NULL REFERENCES tasks(id),
                depends_on_id INTEGER NOT NULL REFERENCES tasks(id),
                PRIMARY KEY (task_id, depends_on_id),
                CHECK (task_id != depends_on_id)
            );
            CREATE TABLE task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES tasks(id),
                field TEXT NOT NULL CHECK (field IN (
                    'title','description','column_id','project_id',
                    'priority','due_date','position','archived',
                    'start_date','finish_date','group_id'
                )),
                old_value TEXT,
                new_value TEXT NOT NULL,
                source TEXT NOT NULL,
                changed_at INTEGER NOT NULL DEFAULT (unixepoch())
            );
        """)
        # Seed data: workspace, project, column, group, tasks with join-table assignments
        conn.execute("INSERT INTO boards (id, name) VALUES (1, 'b')")
        conn.execute("INSERT INTO projects (id, board_id, name) VALUES (1, 1, 'p')")
        conn.execute("INSERT INTO columns (id, board_id, name) VALUES (1, 1, 'c')")
        conn.execute("INSERT INTO groups (id, project_id, title) VALUES (1, 1, 'g')")
        conn.execute("INSERT INTO tasks (id, board_id, title, column_id, project_id) VALUES (1, 1, 'grouped', 1, 1)")
        conn.execute("INSERT INTO tasks (id, board_id, title, column_id, project_id) VALUES (2, 1, 'ungrouped', 1, 1)")
        conn.execute("INSERT INTO task_groups (task_id, group_id) VALUES (1, 1)")
        conn.execute("PRAGMA user_version = 1")
        conn.commit()

        # Run migrations directly (not init_db, which would try to apply the
        # current schema.sql — including indexes on columns that don't exist
        # until migration 002 adds them).
        _run_migrations(conn)

        # Verify user_version is updated
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        # Verify task_groups table is gone
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        assert "task_groups" not in tables
        # Verify group_id inlined correctly
        row = conn.execute("SELECT group_id FROM tasks WHERE id = 1").fetchone()
        assert row["group_id"] == 1
        row = conn.execute("SELECT group_id FROM tasks WHERE id = 2").fetchone()
        assert row["group_id"] is None
        # Verify COLLATE NOCASE applied to name/title columns by migration 003
        # (case-insensitive lookup should work on workspaces after rebuild)
        assert conn.execute(
            "SELECT id FROM workspaces WHERE name = 'B'"
        ).fetchone() is not None
        # Verify composite FK (group_id, project_id) enforces group-project match
        conn.execute("INSERT INTO projects (id, workspace_id, name) VALUES (2, 1, 'p2')")
        conn.execute("INSERT INTO groups (id, workspace_id, project_id, title) VALUES (2, 1, 2, 'g2')")
        with pytest.raises(sqlite3.IntegrityError):
            # Task in project 1 cannot be assigned to group in project 2
            conn.execute(
                "INSERT INTO tasks (workspace_id, title, status_id, project_id, group_id) "
                "VALUES (1, 'bad', 1, 1, 2)"
            )
        conn.close()

    def test_migration_005_adds_group_dependencies(self, tmp_path: Path) -> None:
        """Simulate a v4 database without group_dependencies, verify migrations 005+006 run."""
        db_path = tmp_path / "v4.db"
        conn = get_connection(db_path)
        # Bootstrap a v4-era schema manually (post-column-to-status, pre-group-dependencies,
        # still uses boards/board_id — migration 006 will rename to workspaces/workspace_id)
        conn.executescript("""
            CREATE TABLE boards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT COLLATE NOCASE UNIQUE NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT (unixepoch())
            );
            CREATE TABLE statuses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL REFERENCES boards(id),
                name TEXT COLLATE NOCASE NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                UNIQUE (board_id, name)
            );
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL REFERENCES boards(id),
                name TEXT COLLATE NOCASE NOT NULL,
                description TEXT,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                UNIQUE (board_id, name)
            );
            CREATE TABLE groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                parent_id INTEGER REFERENCES groups(id),
                title TEXT COLLATE NOCASE NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                UNIQUE (project_id, title)
            );
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL REFERENCES boards(id),
                project_id INTEGER REFERENCES projects(id),
                title TEXT NOT NULL COLLATE NOCASE,
                description TEXT,
                status_id INTEGER NOT NULL REFERENCES statuses(id),
                priority INTEGER NOT NULL DEFAULT 1 CHECK (priority BETWEEN 1 AND 5),
                due_date INTEGER,
                position INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                start_date INTEGER,
                finish_date INTEGER,
                group_id INTEGER
            );
            CREATE TABLE task_dependencies (
                task_id INTEGER NOT NULL REFERENCES tasks(id),
                depends_on_id INTEGER NOT NULL REFERENCES tasks(id),
                board_id INTEGER NOT NULL REFERENCES boards(id),
                PRIMARY KEY (task_id, depends_on_id),
                CHECK (task_id != depends_on_id)
            );
            CREATE TABLE tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL REFERENCES boards(id),
                name TEXT COLLATE NOCASE NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                UNIQUE (board_id, name)
            );
            CREATE TABLE task_tags (
                task_id INTEGER NOT NULL REFERENCES tasks(id),
                tag_id INTEGER NOT NULL REFERENCES tags(id),
                board_id INTEGER NOT NULL REFERENCES boards(id),
                PRIMARY KEY (task_id, tag_id)
            );
            CREATE TABLE task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES tasks(id),
                field TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                source TEXT NOT NULL,
                changed_at INTEGER NOT NULL DEFAULT (unixepoch())
            );
        """)
        conn.execute("PRAGMA user_version = 4")
        conn.commit()

        _run_migrations(conn)

        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        assert "group_dependencies" in tables
        # After migration 006: boards→workspaces, board_id→workspace_id
        conn.execute("INSERT INTO workspaces (id, name) VALUES (1, 'b')")
        conn.execute("INSERT INTO projects (id, workspace_id, name) VALUES (1, 1, 'p')")
        conn.execute("INSERT INTO groups (id, workspace_id, project_id, title) VALUES (1, 1, 1, 'g')")
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO group_dependencies (group_id, depends_on_id, workspace_id) VALUES (1, 1, 1)"
            )
        conn.close()

    def test_migration_skips_when_already_current(self, conn: sqlite3.Connection) -> None:
        """Fresh DB is already at current version — migrations are no-ops."""
        version_before = conn.execute("PRAGMA user_version").fetchone()[0]
        init_db(conn)
        version_after = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version_before == version_after == SCHEMA_VERSION

    def test_downgrade_rejected(self, tmp_path: Path) -> None:
        """DB schema newer than this build must raise RuntimeError."""
        db_path = tmp_path / "future.db"
        conn = get_connection(db_path)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        conn.commit()
        with pytest.raises(RuntimeError, match="newer than this build"):
            _run_migrations(conn)
        conn.close()


class TestTaskHistoryFieldConstraint:
    def test_rejects_invalid_field_value(
        self, conn: sqlite3.Connection,
    ) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn, "b")
            col_id = insert_status(conn, workspace_id, "col")
            task_id = insert_task(conn, workspace_id, "t", col_id)
        with pytest.raises(sqlite3.IntegrityError):
            with transaction(conn):
                conn.execute(
                    "INSERT INTO task_history (task_id, workspace_id, field, new_value, source) "
                    "VALUES (?, ?, 'bogus_field', 'v', 'test')",
                    (task_id, workspace_id),
                )

    def test_accepts_valid_field_value(
        self, conn: sqlite3.Connection,
    ) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn, "b")
            col_id = insert_status(conn, workspace_id, "col")
            task_id = insert_task(conn, workspace_id, "t", col_id)
        with transaction(conn):
            conn.execute(
                "INSERT INTO task_history (task_id, workspace_id, field, new_value, source) "
                "VALUES (?, ?, 'title', 'new_title', 'test')",
                (task_id, workspace_id),
            )
        row = conn.execute("SELECT field FROM task_history").fetchone()
        assert row["field"] == "title"


class TestMigrationFileStructure:
    def test_schema_version_matches_highest_migration(self) -> None:
        """SCHEMA_VERSION must equal the highest numbered migration file."""
        import importlib.resources

        pkg = importlib.resources.files("sticky_notes.migrations")
        versions = [
            int(r.name[:3])
            for r in pkg.iterdir()
            if r.name.endswith(".sql") and r.name[:3].isdigit()
        ]
        assert versions, "No migration SQL files found"
        assert max(versions) == SCHEMA_VERSION

    def test_migration_files_contain_no_pragmas(self) -> None:
        """Migration SQL files must not contain PRAGMAs or transaction control."""
        import importlib.resources

        pkg = importlib.resources.files("sticky_notes.migrations")
        for resource in pkg.iterdir():
            if not resource.name.endswith(".sql"):
                continue
            content = resource.read_text().upper()
            assert "PRAGMA" not in content, f"{resource.name} contains PRAGMA"
            assert "\nBEGIN" not in content, f"{resource.name} contains BEGIN"
            assert "\nCOMMIT" not in content, f"{resource.name} contains COMMIT"
            assert "\nROLLBACK" not in content, f"{resource.name} contains ROLLBACK"

    def test_migration_file_sequence_is_contiguous(self) -> None:
        """Migration file version numbers must form a contiguous sequence 1..N."""
        import importlib.resources

        pkg = importlib.resources.files("sticky_notes.migrations")
        versions = sorted(
            int(r.name[:3])
            for r in pkg.iterdir()
            if r.name.endswith(".sql") and r.name[:3].isdigit()
        )
        assert versions == list(range(1, len(versions) + 1))
