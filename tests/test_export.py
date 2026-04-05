from __future__ import annotations

import datetime
import sqlite3

import pytest

from helpers import (
    insert_board,
    insert_column,
    insert_group,
    insert_project,
    insert_tag,
    insert_task,
    insert_task_dependency,
    insert_task_tag,
)
from sticky_notes.repository import set_task_group_id
from sticky_notes.connection import transaction
from sticky_notes.export import export_markdown, _md_escape


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
        assert "| task-0001 | Set up CI | P2 | Backend |  | 2026-05-01 |" in md
        assert "#### Done" in md
        assert "| task-0002 | Write docs | P1 |  |  |  |" in md

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

    def test_cross_board_deps_prevented(self, conn: sqlite3.Connection) -> None:
        """Composite FK prevents dependencies between tasks on different boards."""
        with transaction(conn):
            b1 = insert_board(conn, "B1")
            b2 = insert_board(conn, "B2")
            c1 = insert_column(conn, b1, "C", position=0)
            c2 = insert_column(conn, b2, "C", position=0)
            t1 = insert_task(conn, b1, "T1", c1)
            t2 = insert_task(conn, b2, "T2", c2)
        with pytest.raises(sqlite3.IntegrityError):
            with transaction(conn):
                insert_task_dependency(conn, t2, t1)


class TestExportTags:
    def test_tags_section(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_board(conn, "B")
            col = insert_column(conn, bid, "Col", position=0)
            tid = insert_task(conn, bid, "Fix bug", col)
            tag_id = insert_tag(conn, bid, "bug")
            insert_task_tag(conn, tid, tag_id)
        md = export_markdown(conn)
        assert "### Tags" in md
        assert "| bug | 1 |" in md

    def test_tags_in_task_table(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_board(conn, "B")
            col = insert_column(conn, bid, "Col", position=0)
            tid = insert_task(conn, bid, "Fix bug", col)
            tag_id = insert_tag(conn, bid, "bug")
            insert_task_tag(conn, tid, tag_id)
        md = export_markdown(conn)
        assert "| task-0001 | Fix bug | P1 |  | bug |  |" in md

    def test_no_tags_section_when_none_exist(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_board(conn, "B")
            col = insert_column(conn, bid, "Col", position=0)
            insert_task(conn, bid, "Task", col)
        md = export_markdown(conn)
        assert "### Tags" not in md


class TestExportGroups:
    def test_groups_section_with_tasks(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_board(conn, "B")
            col = insert_column(conn, bid, "Col", position=0)
            pid = insert_project(conn, bid, "P")
            gid = insert_group(conn, pid, "Frontend")
            tid = insert_task(conn, bid, "Fix UI", col, project_id=pid)
            set_task_group_id(conn, tid, gid)
        md = export_markdown(conn)
        assert "### Groups" in md
        assert "**Frontend**" in md
        assert "task-0001: Fix UI" in md

    def test_nested_groups(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_board(conn, "B")
            col = insert_column(conn, bid, "Col", position=0)
            pid = insert_project(conn, bid, "P")
            parent = insert_group(conn, pid, "Frontend")
            insert_group(conn, pid, "Components", parent_id=parent)
        md = export_markdown(conn)
        assert "**Frontend**" in md
        assert "**Components**" in md

    def test_no_groups_section_when_none_exist(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_board(conn, "B")
            insert_column(conn, bid, "Col", position=0)
            insert_project(conn, bid, "P")
        md = export_markdown(conn)
        assert "### Groups" not in md

    def test_ungrouped_tasks_count(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_board(conn, "B")
            col = insert_column(conn, bid, "Col", position=0)
            pid = insert_project(conn, bid, "P")
            insert_group(conn, pid, "G")
            insert_task(conn, bid, "Ungrouped", col, project_id=pid)
        md = export_markdown(conn)
        assert "1 ungrouped task" in md


class TestMdEscape:
    def test_pipe_escaped(self) -> None:
        assert _md_escape("foo | bar") == r"foo \| bar"

    def test_backtick_escaped(self) -> None:
        assert _md_escape("foo `bar`") == r"foo \`bar\`"

    def test_newline_replaced(self) -> None:
        assert _md_escape("line1\nline2") == "line1<br>line2"

    def test_plain_unchanged(self) -> None:
        assert _md_escape("hello world") == "hello world"


class TestExportMdEscaping:
    def test_pipe_in_title_escaped(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_board(conn, "B")
            col = insert_column(conn, bid, "Col", position=0)
            insert_task(conn, bid, "foo | bar", col)
        md = export_markdown(conn)
        assert r"foo \| bar" in md
        assert "foo | bar |" not in md  # raw pipe must not appear in table cell

    def test_newline_in_title_replaced(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_board(conn, "B")
            col = insert_column(conn, bid, "Col", position=0)
            insert_task(conn, bid, "line1\nline2", col)
        md = export_markdown(conn)
        assert "line1<br>line2" in md

    def test_backtick_in_project_description_escaped(
        self, conn: sqlite3.Connection
    ) -> None:
        with transaction(conn):
            bid = insert_board(conn, "B")
            insert_column(conn, bid, "Col", position=0)
            insert_project(conn, bid, "P", description="use `cmd` here")
        md = export_markdown(conn)
        assert r"use \`cmd\` here" in md
