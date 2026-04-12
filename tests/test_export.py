from __future__ import annotations

import datetime
import json
import sqlite3

import pytest
from helpers import (
    insert_group,
    insert_project,
    insert_status,
    insert_tag,
    insert_task,
    insert_task_dependency,
    insert_task_history,
    insert_task_tag,
    insert_workspace,
)

from stx.connection import SCHEMA_VERSION, transaction
from stx.export import _md_escape, export_full_json, export_markdown
from stx.repository import set_task_group_id

# ---- Helpers ----


def _seed_workspace(conn: sqlite3.Connection) -> int:
    """Create a workspace with statuses, projects, tasks, and a dependency."""
    with transaction(conn):
        bid = insert_workspace(conn, "Work")
        col_todo = insert_status(conn, bid, "Todo")
        col_done = insert_status(conn, bid, "Done")
        pid = insert_project(conn, bid, "Backend", description="API work")
        t1 = insert_task(
            conn,
            bid,
            "Set up CI",
            col_todo,
            project_id=pid,
            priority=2,
            due_date=1777593600,
        )
        t2 = insert_task(conn, bid, "Write docs", col_done)
        insert_task_dependency(conn, t2, t1)
    return bid


# ---- Tests ----


class TestExportEmpty:
    def test_no_workspaces(self, conn: sqlite3.Connection) -> None:
        md = export_markdown(conn)
        assert "# stx Export" in md
        assert "## Workspace" not in md

    def test_archived_workspace_excluded(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "Old")
        with transaction(conn):
            conn.execute("UPDATE workspaces SET archived = 1 WHERE id = ?", (bid,))
        md = export_markdown(conn)
        assert "Old" not in md


class TestExportFull:
    @pytest.fixture(autouse=True)
    def _seed(self, conn: sqlite3.Connection) -> None:
        _seed_workspace(conn)

    def test_header(self, conn: sqlite3.Connection) -> None:
        md = export_markdown(conn)
        assert md.startswith("# stx Export\n")
        assert f"Generated: {datetime.date.today().isoformat()}" in md

    def test_workspace_heading(self, conn: sqlite3.Connection) -> None:
        md = export_markdown(conn)
        assert "## Workspace: Work" in md

    def test_column_table(self, conn: sqlite3.Connection) -> None:
        md = export_markdown(conn)
        assert "### Statuses" in md
        assert "| 1 | Done | 1 |" in md
        assert "| 2 | Todo | 1 |" in md

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
            bid = insert_workspace(conn, "B")
            insert_status(conn, bid, "Empty")
        md = export_markdown(conn)
        assert "#### Empty" not in md

    def test_no_projects_section_when_none_exist(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            insert_status(conn, bid, "Col")
        md = export_markdown(conn)
        assert "### Projects" not in md

    def test_no_deps_section_when_none_exist(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            col = insert_status(conn, bid, "Col")
            insert_task(conn, bid, "Solo", col)
        md = export_markdown(conn)
        assert "### Dependencies" not in md
        assert "mermaid" not in md

    def test_archived_tasks_excluded(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            col = insert_status(conn, bid, "Col")
            tid = insert_task(conn, bid, "Hidden", col)
        with transaction(conn):
            conn.execute("UPDATE tasks SET archived = 1 WHERE id = ?", (tid,))
        md = export_markdown(conn)
        assert "Hidden" not in md

    def test_project_with_no_description(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            insert_status(conn, bid, "Col")
            insert_project(conn, bid, "NoDesc", description=None)
        md = export_markdown(conn)
        assert "| NoDesc |  | 0 |" in md

    def test_multiple_workspaces(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            for name in ("Alpha", "Beta"):
                bid = insert_workspace(conn, name)
                insert_status(conn, bid, "Col")
        md = export_markdown(conn)
        assert "## Workspace: Alpha" in md
        assert "## Workspace: Beta" in md

    def test_cross_workspace_deps_prevented(self, conn: sqlite3.Connection) -> None:
        """Composite FK prevents dependencies between tasks on different workspaces."""
        with transaction(conn):
            b1 = insert_workspace(conn, "B1")
            b2 = insert_workspace(conn, "B2")
            c1 = insert_status(conn, b1, "C")
            c2 = insert_status(conn, b2, "C")
            t1 = insert_task(conn, b1, "T1", c1)
            t2 = insert_task(conn, b2, "T2", c2)
        with pytest.raises(sqlite3.IntegrityError):
            with transaction(conn):
                insert_task_dependency(conn, t2, t1)


class TestExportTags:
    def test_tags_section(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            col = insert_status(conn, bid, "Col")
            tid = insert_task(conn, bid, "Fix bug", col)
            tag_id = insert_tag(conn, bid, "bug")
            insert_task_tag(conn, tid, tag_id)
        md = export_markdown(conn)
        assert "### Tags" in md
        assert "| bug | 1 |" in md

    def test_tags_in_task_table(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            col = insert_status(conn, bid, "Col")
            tid = insert_task(conn, bid, "Fix bug", col)
            tag_id = insert_tag(conn, bid, "bug")
            insert_task_tag(conn, tid, tag_id)
        md = export_markdown(conn)
        assert "| task-0001 | Fix bug | P1 |  | bug |  |" in md

    def test_no_tags_section_when_none_exist(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            col = insert_status(conn, bid, "Col")
            insert_task(conn, bid, "Task", col)
        md = export_markdown(conn)
        assert "### Tags" not in md


class TestExportGroups:
    def test_groups_section_with_tasks(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            col = insert_status(conn, bid, "Col")
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
            bid = insert_workspace(conn, "B")
            col = insert_status(conn, bid, "Col")
            pid = insert_project(conn, bid, "P")
            parent = insert_group(conn, pid, "Frontend")
            insert_group(conn, pid, "Components", parent_id=parent)
        md = export_markdown(conn)
        assert "**Frontend**" in md
        assert "**Components**" in md

    def test_no_groups_section_when_none_exist(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            insert_status(conn, bid, "Col")
            insert_project(conn, bid, "P")
        md = export_markdown(conn)
        assert "### Groups" not in md

    def test_ungrouped_tasks_count(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            col = insert_status(conn, bid, "Col")
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
            bid = insert_workspace(conn, "B")
            col = insert_status(conn, bid, "Col")
            insert_task(conn, bid, "foo | bar", col)
        md = export_markdown(conn)
        assert r"foo \| bar" in md
        assert "foo | bar |" not in md  # raw pipe must not appear in table cell

    def test_newline_in_title_replaced(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            col = insert_status(conn, bid, "Col")
            insert_task(conn, bid, "line1\nline2", col)
        md = export_markdown(conn)
        assert "line1<br>line2" in md

    def test_backtick_in_project_description_escaped(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            insert_status(conn, bid, "Col")
            insert_project(conn, bid, "P", description="use `cmd` here")
        md = export_markdown(conn)
        assert r"use \`cmd\` here" in md


class TestExportDescriptions:
    def test_descriptions_section(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            col = insert_status(conn, bid, "Col")
            insert_task(conn, bid, "Fix bug", col, description="Crashes on startup")
        md = export_markdown(conn)
        assert "### Descriptions" in md
        assert "#### task-0001: Fix bug" in md
        assert "Crashes on startup" in md

    def test_no_descriptions_section_when_none(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            col = insert_status(conn, bid, "Col")
            insert_task(conn, bid, "Task", col)
        md = export_markdown(conn)
        assert "### Descriptions" not in md

    def test_only_described_tasks_appear(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            col = insert_status(conn, bid, "Col")
            insert_task(conn, bid, "Has desc", col, description="Details here")
            insert_task(conn, bid, "No desc", col)
        md = export_markdown(conn)
        assert "#### task-0001: Has desc" in md
        assert "Details here" in md
        assert "task-0002" not in md.split("### Descriptions")[1].split("###")[0]


class TestExportFullJson:
    def test_schema_version(self, conn: sqlite3.Connection) -> None:
        result = export_full_json(conn)
        assert result["schema_version"] == SCHEMA_VERSION

    def test_exported_at_is_recent_epoch(self, conn: sqlite3.Connection) -> None:
        import time

        before = int(time.time())
        result = export_full_json(conn)
        after = int(time.time())
        assert before <= result["exported_at"] <= after

    def test_top_level_keys(self, conn: sqlite3.Connection) -> None:
        result = export_full_json(conn)
        assert set(result.keys()) == {
            "schema_version",
            "exported_at",
            "workspaces",
            "statuses",
            "projects",
            "tasks",
            "tags",
            "groups",
            "task_tags",
            "task_dependencies",
            "task_history",
        }

    def test_empty_db_all_lists_empty(self, conn: sqlite3.Connection) -> None:
        result = export_full_json(conn)
        for key in (
            "workspaces",
            "statuses",
            "projects",
            "tasks",
            "tags",
            "groups",
            "task_tags",
            "task_dependencies",
            "task_history",
        ):
            assert result[key] == [], f"expected {key} to be empty"

    def test_json_serializable(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            col = insert_status(conn, bid, "Todo")
            pid = insert_project(conn, bid, "P", description="desc")
            tid = insert_task(conn, bid, "T1", col, project_id=pid)
            tag_id = insert_tag(conn, bid, "bug")
            insert_task_tag(conn, tid, tag_id)
            insert_task_history(conn, tid, field="title", old_value="Old", new_value="T1")
        result = export_full_json(conn)
        serialized = json.dumps(result)  # must not raise TypeError
        assert isinstance(serialized, str)

    def test_archived_rows_included(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            col = insert_status(conn, bid, "Done")
            tid = insert_task(conn, bid, "archived task", col)
            conn.execute("UPDATE tasks SET archived = 1 WHERE id = ?", (tid,))
            conn.execute("UPDATE workspaces SET archived = 1 WHERE id = ?", (bid,))
        result = export_full_json(conn)
        assert any(b["archived"] is True for b in result["workspaces"])
        assert any(t["archived"] is True for t in result["tasks"])

    def test_all_seeded_ids_present(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "Work")
            col1 = insert_status(conn, bid, "Todo")
            col2 = insert_status(conn, bid, "Done")
            pid = insert_project(conn, bid, "Backend")
            t1 = insert_task(conn, bid, "T1", col1, project_id=pid)
            t2 = insert_task(conn, bid, "T2", col2)
            insert_task_dependency(conn, t2, t1)
            tag_id = insert_tag(conn, bid, "urgent")
            insert_task_tag(conn, t1, tag_id)
        result = export_full_json(conn)
        workspace_ids = {b["id"] for b in result["workspaces"]}
        assert bid in workspace_ids
        task_ids = {t["id"] for t in result["tasks"]}
        assert {t1, t2} <= task_ids
        assert any(
            d["task_id"] == t2 and d["depends_on_id"] == t1 for d in result["task_dependencies"]
        )
        assert any(tt["task_id"] == t1 and tt["tag_id"] == tag_id for tt in result["task_tags"])

    def test_task_history_included(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            col = insert_status(conn, bid, "Todo")
            tid = insert_task(conn, bid, "T", col)
            insert_task_history(conn, tid, field="title", old_value="old", new_value="T")
        result = export_full_json(conn)
        history = result["task_history"]
        assert len(history) == 1
        assert history[0]["task_id"] == tid
        assert history[0]["field"] == "title"
        assert history[0]["old_value"] == "old"
        assert history[0]["new_value"] == "T"

    def test_task_dependency_workspace_id_preserved(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "B")
            col = insert_status(conn, bid, "Todo")
            t1 = insert_task(conn, bid, "T1", col)
            t2 = insert_task(conn, bid, "T2", col)
            insert_task_dependency(conn, t2, t1)
        result = export_full_json(conn)
        dep = result["task_dependencies"][0]
        assert dep["workspace_id"] == bid


class TestExportMetadata:
    def test_json_export_includes_metadata(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "W")
            col = insert_status(conn, bid, "Todo")
            tid = insert_task(conn, bid, "T1", col)
            conn.execute(
                """UPDATE tasks SET metadata = '{"branch":"feat/kv"}' WHERE id = ?""",
                (tid,),
            )
        result = export_full_json(conn)
        task = result["tasks"][0]
        assert task["metadata"] == {"branch": "feat/kv"}

    def test_markdown_export_includes_metadata_section(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "W")
            col = insert_status(conn, bid, "Todo")
            tid = insert_task(conn, bid, "T1", col)
            conn.execute(
                """UPDATE tasks SET metadata = '{"branch":"feat/kv"}' WHERE id = ?""",
                (tid,),
            )
        md = export_markdown(conn)
        assert "### Task Metadata" in md
        assert "**branch**" in md
        assert "feat/kv" in md

    def test_markdown_export_omits_metadata_when_empty(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "W")
            col = insert_status(conn, bid, "Todo")
            insert_task(conn, bid, "T1", col)
        md = export_markdown(conn)
        assert "### Task Metadata" not in md
        assert "### Project Metadata" not in md
        assert "### Group Metadata" not in md


class TestExportEntityMetadata:
    def test_workspace_metadata_block(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "W")
            insert_status(conn, bid, "Todo")
            conn.execute(
                """UPDATE workspaces SET metadata = '{"env":"prod"}' WHERE id = ?""",
                (bid,),
            )
        md = export_markdown(conn)
        assert "## Workspace: W" in md
        assert "**Metadata:**" in md
        assert "**env**: prod" in md

    def test_project_metadata_section(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "W")
            insert_status(conn, bid, "Todo")
            pid = insert_project(conn, bid, "backend")
            conn.execute(
                """UPDATE projects SET metadata = '{"owner":"alice"}' WHERE id = ?""",
                (pid,),
            )
        md = export_markdown(conn)
        assert "### Project Metadata" in md
        assert "#### backend" in md
        assert "**owner**: alice" in md

    def test_group_metadata_section(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "W")
            insert_status(conn, bid, "Todo")
            pid = insert_project(conn, bid, "backend")
            gid = insert_group(conn, pid, "Sprint1")
            conn.execute(
                """UPDATE groups SET metadata = '{"sprint":"3"}' WHERE id = ?""",
                (gid,),
            )
        md = export_markdown(conn)
        assert "### Group Metadata" in md
        assert "#### backend > Sprint1" in md
        assert "**sprint**: 3" in md

    def test_json_export_includes_entity_metadata(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            bid = insert_workspace(conn, "W")
            insert_status(conn, bid, "Todo")
            pid = insert_project(conn, bid, "backend")
            gid = insert_group(conn, pid, "Sprint1")
            conn.execute('UPDATE workspaces SET metadata = \'{"env":"prod"}\' WHERE id = ?', (bid,))
            conn.execute(
                'UPDATE projects SET metadata = \'{"owner":"alice"}\' WHERE id = ?', (pid,)
            )
            conn.execute('UPDATE groups SET metadata = \'{"sprint":"3"}\' WHERE id = ?', (gid,))
        result = export_full_json(conn)
        assert result["workspaces"][0]["metadata"] == {"env": "prod"}
        assert result["projects"][0]["metadata"] == {"owner": "alice"}
        assert result["groups"][0]["metadata"] == {"sprint": "3"}
