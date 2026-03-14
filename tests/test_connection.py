from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest

from helpers import insert_board, insert_column, insert_task
from sticky_notes.connection import get_connection, init_db, transaction


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
            "boards", "projects", "columns",
            "tasks", "task_dependencies", "task_history",
        }

    def test_idempotent(self, conn: sqlite3.Connection) -> None:
        init_db(conn)  # second call should not raise


class TestTransaction:
    def test_commit_on_success(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            conn.execute("INSERT INTO boards (name) VALUES ('test')")
        row = conn.execute(
            "SELECT name FROM boards WHERE name = 'test'",
        ).fetchone()
        assert row is not None
        assert row["name"] == "test"

    def test_rollback_on_exception(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError):
            with transaction(conn):
                conn.execute("INSERT INTO boards (name) VALUES ('rollback_test')")
                raise ValueError("boom")
        row = conn.execute(
            "SELECT name FROM boards WHERE name = 'rollback_test'",
        ).fetchone()
        assert row is None

    def test_nested_transaction_not_allowed(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            conn.execute("INSERT INTO boards (name) VALUES ('outer')")
            with pytest.raises(RuntimeError, match="Cannot nest transactions"):
                with transaction(conn):
                    pass
        # Outer transaction should still have committed successfully
        row = conn.execute(
            "SELECT name FROM boards WHERE name = 'outer'"
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
                proxy.execute("INSERT INTO boards (name) VALUES ('rb_test')")
                proxy._fail_rollback = True
                raise ValueError("boom")

        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, OSError)
        assert "disk full" in str(exc_info.value.__cause__)


class TestSelfDependencyConstraint:
    def test_task_cannot_depend_on_itself(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            board_id = insert_board(conn, "b")
            col_id = insert_column(conn, board_id, "col")
            task_id = insert_task(conn, board_id, "t", col_id)
        with pytest.raises(sqlite3.IntegrityError):
            with transaction(conn):
                conn.execute(
                    "INSERT INTO task_dependencies (task_id, depends_on_id) "
                    "VALUES (?, ?)",
                    (task_id, task_id),
                )

    def test_valid_dependency_allowed(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            board_id = insert_board(conn, "b")
            col_id = insert_column(conn, board_id, "col")
            t1 = insert_task(conn, board_id, "t1", col_id)
            t2 = insert_task(conn, board_id, "t2", col_id)
        with transaction(conn):
            conn.execute(
                "INSERT INTO task_dependencies (task_id, depends_on_id) "
                "VALUES (?, ?)",
                (t1, t2),
            )
        row = conn.execute("SELECT * FROM task_dependencies").fetchone()
        assert row["task_id"] == t1
        assert row["depends_on_id"] == t2


class TestColumnArchived:
    def test_column_has_archived_default_zero(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            board_id = insert_board(conn, "b")
            insert_column(conn, board_id, "col")
        row = conn.execute(
            "SELECT archived FROM columns WHERE name = 'col'",
        ).fetchone()
        assert row["archived"] == 0

    def test_column_archived_can_be_set(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            board_id = insert_board(conn, "b")
            conn.execute(
                "INSERT INTO columns (board_id, name, archived) VALUES (?, 'col', 1)",
                (board_id,),
            )
        row = conn.execute(
            "SELECT archived FROM columns WHERE name = 'col'",
        ).fetchone()
        assert row["archived"] == 1


class TestForeignKeyEnforcement:
    def test_rejects_task_with_nonexistent_board(
        self, conn: sqlite3.Connection,
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            with transaction(conn):
                conn.execute(
                    "INSERT INTO columns (board_id, name) VALUES (999, 'col')",
                )

    def test_rejects_task_with_nonexistent_column(
        self, conn: sqlite3.Connection,
    ) -> None:
        with transaction(conn):
            board_id = insert_board(conn, "b")
        with pytest.raises(sqlite3.IntegrityError):
            with transaction(conn):
                conn.execute(
                    "INSERT INTO tasks (board_id, title, column_id) "
                    "VALUES (?, 't', 999)",
                    (board_id,),
                )


class TestTaskHistoryFieldConstraint:
    def test_rejects_invalid_field_value(
        self, conn: sqlite3.Connection,
    ) -> None:
        with transaction(conn):
            board_id = insert_board(conn, "b")
            col_id = insert_column(conn, board_id, "col")
            task_id = insert_task(conn, board_id, "t", col_id)
        with pytest.raises(sqlite3.IntegrityError):
            with transaction(conn):
                conn.execute(
                    "INSERT INTO task_history (task_id, field, new_value, source) "
                    "VALUES (?, 'bogus_field', 'v', 'test')",
                    (task_id,),
                )

    def test_accepts_valid_field_value(
        self, conn: sqlite3.Connection,
    ) -> None:
        with transaction(conn):
            board_id = insert_board(conn, "b")
            col_id = insert_column(conn, board_id, "col")
            task_id = insert_task(conn, board_id, "t", col_id)
        with transaction(conn):
            conn.execute(
                "INSERT INTO task_history (task_id, field, new_value, source) "
                "VALUES (?, 'title', 'new_title', 'test')",
                (task_id,),
            )
        row = conn.execute("SELECT field FROM task_history").fetchone()
        assert row["field"] == "title"
