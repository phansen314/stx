from __future__ import annotations

import datetime
import sqlite3

import pytest

from helpers import (
    insert_board,
    insert_column,
    insert_project,
    insert_task,
    insert_task_dependency,
)
from sticky_notes.connection import transaction
from sticky_notes.export import export_markdown


# ---- Helpers ----


def _seed_board(conn: sqlite3.Connection) -> int:
    """Create a board with columns, projects, tasks, and a dependency."""
    with transaction(conn):
        bid = insert_board(conn, "Work")
        col_todo = insert_column(conn, bid, "Todo", position=0)
        col_done = insert_column(conn, bid, "Done", position=1)
        pid = insert_project(conn, bid, "Backend", description="API work")
        t1 = insert_task(
            conn, bid, "Set up CI", col_todo,
            project_id=pid, priority=2, due_date=1777593600,
        )
        t2 = insert_task(conn, bid, "Write docs", col_done)
        insert_task_dependency(conn, t2, t1)
    return bid


# ---- Tests ----


class TestExportEmpty:
    def test_no_boards(self, conn: sqlite3.Connection) -> None:
        md = export_markdown(conn)
        assert "# Sticky Notes Export" in md
        assert "## Board" not in md

    def test_archived_board_excluded(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_board(conn, "Old")
        with transaction(conn):
            conn.execute("UPDATE boards SET archived = 1 WHERE id = ?", (bid,))
        md = export_markdown(conn)
        assert "Old" not in md


class TestExportFull:
    @pytest.fixture(autouse=True)
    def _seed(self, conn: sqlite3.Connection) -> None:
        _seed_board(conn)

    def test_header(self, conn: sqlite3.Connection) -> None:
        md = export_markdown(conn)
        assert md.startswith("# Sticky Notes Export\n")
        assert f"Generated: {datetime.date.today().isoformat()}" in md

    def test_board_heading(self, conn: sqlite3.Connection) -> None:
        md = export_markdown(conn)
        assert "## Board: Work" in md

    def test_column_table(self, conn: sqlite3.Connection) -> None:
        md = export_markdown(conn)
        assert "### Columns" in md
        assert "| 1 | Todo | 1 |" in md
        assert "| 2 | Done | 1 |" in md

    def test_project_table(self, conn: sqlite3.Connection) -> None:
        md = export_markdown(conn)
        assert "### Projects" in md
        assert "| Backend | API work | 1 |" in md

    def test_task_table(self, conn: sqlite3.Connection) -> None:
        md = export_markdown(conn)
        assert "### Tasks" in md
        assert "#### Todo" in md
        assert "| task-0001 | Set up CI | P2 | Backend | 2026-05-01 |" in md
        assert "#### Done" in md
        assert "| task-0002 | Write docs | P1 |  |  |" in md

    def test_dependency_mermaid(self, conn: sqlite3.Connection) -> None:
        md = export_markdown(conn)
        assert "### Dependencies" in md
        assert "```mermaid" in md
        assert "    task-0002 --> task-0001" in md
        assert '> Arrow reads "depends on"' in md


class TestExportEdgeCases:
    def test_empty_column_omitted_from_tasks_section(self, conn: sqlite3.Connection) -> None:
        """A column with zero tasks should not get a #### heading."""
        with transaction(conn):
            bid = insert_board(conn, "B")
            insert_column(conn, bid, "Empty", position=0)
        md = export_markdown(conn)
        assert "#### Empty" not in md

    def test_no_projects_section_when_none_exist(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_board(conn, "B")
            insert_column(conn, bid, "Col", position=0)
        md = export_markdown(conn)
        assert "### Projects" not in md

    def test_no_deps_section_when_none_exist(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_board(conn, "B")
            col = insert_column(conn, bid, "Col", position=0)
            insert_task(conn, bid, "Solo", col)
        md = export_markdown(conn)
        assert "### Dependencies" not in md
        assert "mermaid" not in md

    def test_archived_tasks_excluded(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_board(conn, "B")
            col = insert_column(conn, bid, "Col", position=0)
            tid = insert_task(conn, bid, "Hidden", col)
        with transaction(conn):
            conn.execute("UPDATE tasks SET archived = 1 WHERE id = ?", (tid,))
        md = export_markdown(conn)
        assert "Hidden" not in md

    def test_project_with_no_description(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_board(conn, "B")
            insert_column(conn, bid, "Col", position=0)
            insert_project(conn, bid, "NoDesc", description=None)
        md = export_markdown(conn)
        assert "| NoDesc |  | 0 |" in md

    def test_multiple_boards(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            for name in ("Alpha", "Beta"):
                bid = insert_board(conn, name)
                insert_column(conn, bid, "Col", position=0)
        md = export_markdown(conn)
        assert "## Board: Alpha" in md
        assert "## Board: Beta" in md

    def test_cross_board_deps_excluded(self, conn: sqlite3.Connection) -> None:
        """A dependency linking tasks on different boards should not appear."""
        with transaction(conn):
            b1 = insert_board(conn, "B1")
            b2 = insert_board(conn, "B2")
            c1 = insert_column(conn, b1, "C", position=0)
            c2 = insert_column(conn, b2, "C", position=0)
            t1 = insert_task(conn, b1, "T1", c1)
            t2 = insert_task(conn, b2, "T2", c2)
            insert_task_dependency(conn, t2, t1)
        md = export_markdown(conn)
        # Neither board section should show a dependencies block
        assert "### Dependencies" not in md
