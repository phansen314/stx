from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from helpers import insert_status, insert_task, insert_workspace

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
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        assert tables == {
            "workspaces",
            "projects",
            "statuses",
            "tasks",
            "task_dependencies",
            "task_history",
            "tags",
            "task_tags",
            "groups",
            "group_dependencies",
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
        row = conn.execute("SELECT name FROM workspaces WHERE name = 'outer'").fetchone()
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
                    "INSERT INTO task_dependencies (task_id, depends_on_id) VALUES (?, ?)",
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
        self,
        conn: sqlite3.Connection,
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            with transaction(conn):
                conn.execute(
                    "INSERT INTO statuses (workspace_id, name) VALUES (999, 'col')",
                )

    def test_rejects_task_with_nonexistent_status(
        self,
        conn: sqlite3.Connection,
    ) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn, "b")
        with pytest.raises(sqlite3.IntegrityError):
            with transaction(conn):
                conn.execute(
                    "INSERT INTO tasks (workspace_id, title, status_id) VALUES (?, 't', 999)",
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
        conn.execute(
            "INSERT INTO tasks (id, board_id, title, column_id, project_id) VALUES (1, 1, 'grouped', 1, 1)"
        )
        conn.execute(
            "INSERT INTO tasks (id, board_id, title, column_id, project_id) VALUES (2, 1, 'ungrouped', 1, 1)"
        )
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
            r[0]
            for r in conn.execute(
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
        assert conn.execute("SELECT id FROM workspaces WHERE name = 'B'").fetchone() is not None
        # Verify composite FK (group_id, project_id) enforces group-project match
        conn.execute("INSERT INTO projects (id, workspace_id, name) VALUES (2, 1, 'p2')")
        conn.execute(
            "INSERT INTO groups (id, workspace_id, project_id, title) VALUES (2, 1, 2, 'g2')"
        )
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
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        assert "group_dependencies" in tables
        # After migration 006: boards→workspaces, board_id→workspace_id
        conn.execute("INSERT INTO workspaces (id, name) VALUES (1, 'b')")
        conn.execute("INSERT INTO projects (id, workspace_id, name) VALUES (1, 1, 'p')")
        conn.execute(
            "INSERT INTO groups (id, workspace_id, project_id, title) VALUES (1, 1, 1, 'g')"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO group_dependencies (group_id, depends_on_id, workspace_id) VALUES (1, 1, 1)"
            )
        conn.close()

    def _bootstrap_v10_schema(self, conn: sqlite3.Connection) -> None:
        """Recreate the schema as it existed at SCHEMA_VERSION = 10.

        Used by migration 011 tests to exercise the cascade-recreate path.
        Matches the accumulated output of migrations 001-010:
        - workspaces / projects / groups without metadata columns
        - tasks with metadata column (from migration 010) but NO CHECK
        - task_dependencies / task_tags / task_history as of migration 008
        - groups.description column (from migration 009)
        """
        conn.executescript("""
            CREATE TABLE workspaces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE,
                archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
                created_at INTEGER NOT NULL DEFAULT (unixepoch())
            );
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                name TEXT NOT NULL COLLATE NOCASE,
                description TEXT,
                archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                UNIQUE (id, workspace_id)
            );
            CREATE TABLE statuses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                name TEXT NOT NULL COLLATE NOCASE,
                archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                UNIQUE (id, workspace_id)
            );
            CREATE TABLE groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
                parent_id INTEGER,
                title TEXT NOT NULL COLLATE NOCASE,
                description TEXT,
                position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
                archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                UNIQUE (id, project_id),
                FOREIGN KEY (parent_id, project_id) REFERENCES groups(id, project_id) ON DELETE RESTRICT
            );
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL,
                project_id INTEGER,
                title TEXT NOT NULL COLLATE NOCASE,
                description TEXT,
                status_id INTEGER NOT NULL,
                priority INTEGER NOT NULL DEFAULT 1 CHECK (priority BETWEEN 1 AND 5),
                due_date INTEGER,
                position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
                archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                start_date INTEGER,
                finish_date INTEGER,
                group_id INTEGER,
                metadata TEXT NOT NULL DEFAULT '{}',
                CHECK (start_date IS NULL OR finish_date IS NULL OR finish_date >= start_date),
                CHECK (group_id IS NULL OR project_id IS NOT NULL),
                FOREIGN KEY (status_id, workspace_id) REFERENCES statuses(id, workspace_id) ON DELETE RESTRICT,
                FOREIGN KEY (project_id, workspace_id) REFERENCES projects(id, workspace_id) ON DELETE RESTRICT,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
                FOREIGN KEY (group_id, project_id) REFERENCES groups(id, project_id) ON DELETE RESTRICT,
                UNIQUE (id, workspace_id)
            );
            CREATE TABLE task_dependencies (
                task_id INTEGER NOT NULL,
                depends_on_id INTEGER NOT NULL,
                workspace_id INTEGER NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
                PRIMARY KEY (task_id, depends_on_id),
                CHECK (task_id != depends_on_id),
                FOREIGN KEY (task_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE,
                FOREIGN KEY (depends_on_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE
            );
            CREATE TABLE group_dependencies (
                group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
                depends_on_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
                workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
                archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
                PRIMARY KEY (group_id, depends_on_id),
                CHECK (group_id != depends_on_id)
            );
            CREATE TABLE tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                name TEXT NOT NULL COLLATE NOCASE,
                archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                UNIQUE (id, workspace_id)
            );
            CREATE TABLE task_tags (
                task_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                workspace_id INTEGER NOT NULL,
                PRIMARY KEY (task_id, tag_id),
                FOREIGN KEY (task_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id, workspace_id) REFERENCES tags(id, workspace_id) ON DELETE CASCADE
            );
            CREATE TABLE task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                field TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                source TEXT NOT NULL,
                changed_at INTEGER NOT NULL DEFAULT (unixepoch())
            );

            -- Accumulated indexes from migrations 001..010
            CREATE UNIQUE INDEX uq_workspaces_name_active ON workspaces(name) WHERE archived = 0;
            CREATE UNIQUE INDEX uq_projects_workspace_name_active ON projects(workspace_id, name) WHERE archived = 0;
            CREATE UNIQUE INDEX uq_statuses_workspace_name_active ON statuses(workspace_id, name) WHERE archived = 0;
            CREATE UNIQUE INDEX uq_tags_workspace_name_active ON tags(workspace_id, name) WHERE archived = 0;
            CREATE UNIQUE INDEX uq_groups_project_title_active ON groups(project_id, title) WHERE archived = 0;
            CREATE UNIQUE INDEX uq_tasks_workspace_title_active ON tasks(workspace_id, title) WHERE archived = 0;
            CREATE INDEX idx_tasks_status_archived_position ON tasks(status_id, archived, position, id);
            CREATE INDEX idx_tasks_workspace_archived_position ON tasks(workspace_id, archived, position, id);
            CREATE INDEX idx_tasks_project_archived_position ON tasks(project_id, archived, position, id);
            CREATE INDEX idx_statuses_workspace_archived_name ON statuses(workspace_id, archived, name, id);
            CREATE INDEX idx_groups_parent_archived_position ON groups(parent_id, archived, position, id);
            CREATE INDEX idx_groups_project_archived_position ON groups(project_id, archived, position, id);
            CREATE INDEX idx_tags_workspace_archived_name ON tags(workspace_id, archived, name);
            CREATE INDEX idx_task_history_task_changed ON task_history(task_id, changed_at DESC, id DESC);
            CREATE INDEX idx_tasks_project_archived_group ON tasks(project_id, archived, group_id);
            CREATE INDEX idx_task_dependencies_depends_on_id ON task_dependencies(depends_on_id);
            CREATE INDEX idx_group_dependencies_depends_on_id ON group_dependencies(depends_on_id);
            CREATE INDEX idx_task_tags_tag_id ON task_tags(tag_id);
            CREATE INDEX idx_tasks_group_id ON tasks(group_id);
        """)
        conn.execute("PRAGMA user_version = 10")
        conn.commit()

    def test_migration_011_adds_entity_metadata_and_tightens_task_check(
        self,
        tmp_path: Path,
    ) -> None:
        """Cascade-recreate path: metadata columns on wsp/proj/grp, CHECK on
        tasks.metadata, task_history field CHECK, dependent data preserved."""
        import json as _json

        db_path = tmp_path / "v10.db"
        conn = get_connection(db_path)
        self._bootstrap_v10_schema(conn)

        # Seed a row in every cascade-recreated table so we can verify
        # preservation after the DROP + RENAME dance.
        conn.execute("INSERT INTO workspaces (name) VALUES ('w')")
        conn.execute("INSERT INTO statuses (workspace_id, name) VALUES (1, 'todo')")
        conn.execute("INSERT INTO projects (workspace_id, name) VALUES (1, 'p')")
        conn.execute("INSERT INTO groups (workspace_id, project_id, title) VALUES (1, 1, 'g')")
        conn.execute(
            "INSERT INTO tasks (workspace_id, title, status_id, metadata) "
            "VALUES (1, 't1', 1, '{\"branch\":\"feat\"}')"
        )
        conn.execute("INSERT INTO tasks (workspace_id, title, status_id) VALUES (1, 't2', 1)")
        conn.execute(
            "INSERT INTO task_dependencies (task_id, depends_on_id, workspace_id) VALUES (2, 1, 1)"
        )
        conn.execute("INSERT INTO tags (workspace_id, name) VALUES (1, 'bug')")
        conn.execute("INSERT INTO task_tags (task_id, tag_id, workspace_id) VALUES (1, 1, 1)")
        conn.execute(
            "INSERT INTO task_history (task_id, workspace_id, field, new_value, source) "
            "VALUES (1, 1, 'title', 'updated', 'test')"
        )
        conn.commit()

        _run_migrations(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION

        # Metadata columns added to the three entities with default '{}'
        for table in ("workspaces", "projects", "groups"):
            row = conn.execute(f"SELECT metadata FROM {table}").fetchone()
            assert row[0] == "{}"

        # Task metadata preserved byte-for-byte
        t1 = conn.execute("SELECT metadata FROM tasks WHERE id=1").fetchone()
        assert _json.loads(t1[0]) == {"branch": "feat"}

        # json_valid CHECK is now enforced on all four entity tables
        for sql in (
            "UPDATE workspaces SET metadata = 'not json' WHERE id = 1",
            "UPDATE projects SET metadata = 'not json' WHERE id = 1",
            "UPDATE groups SET metadata = 'not json' WHERE id = 1",
            "UPDATE tasks SET metadata = 'not json' WHERE id = 1",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="json_valid"):
                conn.execute(sql)

        # task_history.field CHECK added alongside the recreate
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO task_history (task_id, workspace_id, field, new_value, source) "
                "VALUES (1, 1, 'bogus_field', 'x', 'test')"
            )

        # Dependent rows preserved
        assert conn.execute("SELECT COUNT(*) FROM task_dependencies").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM task_tags").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM task_history").fetchone()[0] == 1

        # Cascade FKs still fire after the recreate
        conn.execute("DELETE FROM tasks WHERE id = 1")
        assert conn.execute("SELECT COUNT(*) FROM task_tags WHERE task_id = 1").fetchone()[0] == 0
        assert (
            conn.execute("SELECT COUNT(*) FROM task_history WHERE task_id = 1").fetchone()[0] == 0
        )
        conn.close()

    def test_migration_011_fails_fast_on_invalid_task_metadata(
        self,
        tmp_path: Path,
    ) -> None:
        """Pre-flight check in _pre_migration_check should surface a clear
        error before the destructive recreate runs, leaving the DB at v10."""
        db_path = tmp_path / "v10_bad.db"
        conn = get_connection(db_path)
        self._bootstrap_v10_schema(conn)

        conn.execute("INSERT INTO workspaces (name) VALUES ('w')")
        conn.execute("INSERT INTO statuses (workspace_id, name) VALUES (1, 'todo')")
        conn.execute(
            "INSERT INTO tasks (workspace_id, title, status_id, metadata) "
            "VALUES (1, 't', 1, 'not json at all')"
        )
        conn.commit()

        with pytest.raises(RuntimeError, match="invalid JSON"):
            _run_migrations(conn)

        # DB stays at v10 (no partial-migration state)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 10
        # And the tasks table still has no json_valid CHECK (rollback held)
        conn.execute("UPDATE tasks SET metadata = 'still not json' WHERE id = 1")
        conn.close()

    def test_migration_011_fails_fast_on_off_allowlist_task_history_field(
        self,
        tmp_path: Path,
    ) -> None:
        """Pre-flight check should also surface off-allowlist task_history.field
        values before the recreate adds the CHECK constraint."""
        db_path = tmp_path / "v10_badhist.db"
        conn = get_connection(db_path)
        self._bootstrap_v10_schema(conn)

        conn.execute("INSERT INTO workspaces (name) VALUES ('w')")
        conn.execute("INSERT INTO statuses (workspace_id, name) VALUES (1, 'todo')")
        conn.execute("INSERT INTO tasks (workspace_id, title, status_id) VALUES (1, 't', 1)")
        conn.execute(
            "INSERT INTO task_history (task_id, workspace_id, field, new_value, source) "
            "VALUES (1, 1, 'bogus_field', 'x', 'raw')"
        )
        conn.commit()

        with pytest.raises(RuntimeError, match="off-allowlist field value 'bogus_field'"):
            _run_migrations(conn)

        assert conn.execute("PRAGMA user_version").fetchone()[0] == 10
        conn.close()

    def test_migration_011_yields_schema_shape_matching_fresh(
        self,
        tmp_path: Path,
    ) -> None:
        """After migration 011, the migrated DB's table/column/index shape
        should match a fresh init_db DB. Catches any drift between the
        migration file and schema.sql."""

        def snapshot(c: sqlite3.Connection) -> dict:
            result: dict = {"tables": {}, "indexes": {}}
            table_names = sorted(
                r[0]
                for r in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' AND name != '_user_migrations'"
                )
            )
            for t in table_names:
                cols = [
                    (r["name"], r["type"], bool(r["notnull"]), r["dflt_value"], bool(r["pk"]))
                    for r in c.execute(f"PRAGMA table_info({t})")
                ]
                fks = sorted(
                    (r["from"], r["table"], r["to"], r["on_delete"])
                    for r in c.execute(f"PRAGMA foreign_key_list({t})")
                )
                result["tables"][t] = {"columns": cols, "fks": fks}
            index_names = sorted(
                r[0]
                for r in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
                )
            )
            for name in index_names:
                cols = [r["name"] for r in c.execute(f"PRAGMA index_info({name})")]
                result["indexes"][name] = cols
            return result

        fresh_path = tmp_path / "fresh.db"
        fresh = get_connection(fresh_path)
        init_db(fresh)
        fresh_shape = snapshot(fresh)
        fresh.close()

        migrated_path = tmp_path / "migrated.db"
        migrated = get_connection(migrated_path)
        self._bootstrap_v10_schema(migrated)
        _run_migrations(migrated)
        migrated_shape = snapshot(migrated)
        migrated.close()

        assert fresh_shape["tables"] == migrated_shape["tables"], (
            f"table shape differs:\n"
            f"  fresh-only tables: {set(fresh_shape['tables']) - set(migrated_shape['tables'])}\n"
            f"  migrated-only:     {set(migrated_shape['tables']) - set(fresh_shape['tables'])}"
        )
        assert fresh_shape["indexes"] == migrated_shape["indexes"], (
            f"index shape differs:\n"
            f"  fresh-only indexes: {set(fresh_shape['indexes']) - set(migrated_shape['indexes'])}\n"
            f"  migrated-only:      {set(migrated_shape['indexes']) - set(fresh_shape['indexes'])}"
        )

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
        self,
        conn: sqlite3.Connection,
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
        self,
        conn: sqlite3.Connection,
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
