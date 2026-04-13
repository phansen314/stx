from __future__ import annotations

import sqlite3

import pytest

from stx.models import (
    EntityType,
    Group,
    JournalEntry,
    NewGroup,
    NewJournalEntry,
    NewStatus,
    NewTask,
    NewWorkspace,
    Status,
    Task,
    TaskField,
    TaskFilter,
    Workspace,
)
from stx.repository import (
    add_edge,
    archive_edge,
    batch_child_ids_by_group,
    batch_task_ids_by_group,
    copy_task_metadata,
    get_active_edge,
    get_archived_edge,
    get_edge_metadata,
    get_group,
    get_group_ancestry,
    get_group_by_title,
    get_status,
    get_status_by_name,
    get_subtree_group_ids,
    get_task,
    get_task_by_title,
    get_workspace,
    get_workspace_by_name,
    insert_group,
    insert_journal_entry,
    insert_status,
    insert_task,
    insert_workspace,
    list_all_edge_rows,
    list_child_groups,
    list_edge_sources_into,
    list_edge_sources_into_hydrated,
    list_edge_targets_from,
    list_edge_targets_from_hydrated,
    list_edges_by_workspace,
    list_groups,
    list_groups_by_workspace,
    list_journal,
    list_statuses,
    list_task_ids_by_group,
    list_tasks,
    list_tasks_by_ids,
    list_tasks_by_status,
    list_tasks_filtered,
    list_ungrouped_task_ids,
    list_workspaces,
    remove_edge_metadata_key,
    remove_group_metadata_key,
    remove_task_metadata_key,
    remove_workspace_metadata_key,
    reparent_children,
    replace_edge_metadata,
    set_edge_metadata_key,
    set_group_metadata_key,
    set_task_group_id,
    set_task_metadata_key,
    set_workspace_metadata_key,
    unassign_tasks_from_group,
    update_group,
    update_status,
    update_task,
    update_workspace,
)

# ---- Workspace ----


class TestWorkspaceRepository:
    def test_insert_returns_workspace(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="work"))
        assert isinstance(workspace, Workspace)
        assert workspace.name == "work"
        assert workspace.archived is False
        assert workspace.id >= 1

    def test_get_workspace(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="work"))
        fetched = get_workspace(conn, workspace.id)
        assert fetched == workspace

    def test_get_workspace_missing(self, conn: sqlite3.Connection) -> None:
        assert get_workspace(conn, 9999) is None

    def test_get_workspace_by_name(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="work"))
        assert get_workspace_by_name(conn, "work") == workspace
        assert get_workspace_by_name(conn, "nope") is None

    def test_get_workspace_by_name_case_insensitive(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="Work"))
        assert get_workspace_by_name(conn, "work") == workspace
        assert get_workspace_by_name(conn, "WORK") == workspace

    def test_unique_name_case_insensitive(self, conn: sqlite3.Connection) -> None:
        insert_workspace(conn, NewWorkspace(name="Dev"))
        with pytest.raises(sqlite3.IntegrityError):
            insert_workspace(conn, NewWorkspace(name="dev"))

    def test_list_workspaces_excludes_archived(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, NewWorkspace(name="a"))
        b2 = insert_workspace(conn, NewWorkspace(name="b"))
        update_workspace(conn, b2.id, {"archived": True})
        workspaces = list_workspaces(conn)
        assert len(workspaces) == 1
        assert workspaces[0].id == b1.id

    def test_list_workspaces_include_archived(self, conn: sqlite3.Connection) -> None:
        insert_workspace(conn, NewWorkspace(name="a"))
        b2 = insert_workspace(conn, NewWorkspace(name="b"))
        update_workspace(conn, b2.id, {"archived": True})
        workspaces = list_workspaces(conn, include_archived=True)
        assert len(workspaces) == 2

    def test_list_workspaces_only_archived(self, conn: sqlite3.Connection) -> None:
        insert_workspace(conn, NewWorkspace(name="active"))
        b2 = insert_workspace(conn, NewWorkspace(name="gone"))
        update_workspace(conn, b2.id, {"archived": True})
        workspaces = list_workspaces(conn, only_archived=True)
        assert len(workspaces) == 1
        assert workspaces[0].name == "gone"

    def test_update_workspace(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="old"))
        updated = update_workspace(conn, workspace.id, {"name": "new"})
        assert updated.name == "new"
        assert updated.id == workspace.id

    def test_update_workspace_bad_field(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="x"))
        with pytest.raises(ValueError, match="disallowed"):
            update_workspace(conn, workspace.id, {"id": 99})

    def test_update_workspace_empty_changes(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="x"))
        with pytest.raises(ValueError, match="empty"):
            update_workspace(conn, workspace.id, {})

    def test_update_workspace_invalid_column_name(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="x"))
        with pytest.raises(ValueError, match="invalid column name"):
            # Bypass allowlist with a patched frozenset to test the regex guard
            from stx import repository

            orig = repository._WORKSPACE_UPDATABLE
            repository._WORKSPACE_UPDATABLE = frozenset({"name; DROP TABLE workspaces--"})
            try:
                update_workspace(conn, workspace.id, {"name; DROP TABLE workspaces--": "pwned"})
            finally:
                repository._WORKSPACE_UPDATABLE = orig

    def test_update_workspace_missing_id(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            update_workspace(conn, 9999, {"name": "y"})


# ---- Status ----


class TestStatusRepository:
    def test_insert_returns_status(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        assert isinstance(col, Status)
        assert col.name == "todo"
        assert col.workspace_id == workspace.id

    def test_get_status(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        assert get_status(conn, col.id) == col

    def test_get_status_missing(self, conn: sqlite3.Connection) -> None:
        assert get_status(conn, 9999) is None

    def test_list_statuses_ordered_alphabetically(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        insert_status(conn, NewStatus(workspace_id=workspace.id, name="zebra"))
        insert_status(conn, NewStatus(workspace_id=workspace.id, name="alpha"))
        cols = list_statuses(conn, workspace.id)
        assert cols[0].name == "alpha"
        assert cols[1].name == "zebra"

    def test_list_statuses_excludes_archived(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        c2 = insert_status(conn, NewStatus(workspace_id=workspace.id, name="done"))
        update_status(conn, c2.id, {"archived": True})
        assert len(list_statuses(conn, workspace.id)) == 1
        assert len(list_statuses(conn, workspace.id, include_archived=True)) == 2

    def test_list_statuses_only_archived(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        c2 = insert_status(conn, NewStatus(workspace_id=workspace.id, name="done"))
        update_status(conn, c2.id, {"archived": True})
        result = list_statuses(conn, workspace.id, only_archived=True)
        assert len(result) == 1
        assert result[0].name == "done"

    def test_update_status(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="old"))
        updated = update_status(conn, col.id, {"name": "new"})
        assert updated.name == "new"

    def test_update_status_bad_field(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="x"))
        with pytest.raises(ValueError, match="disallowed"):
            update_status(conn, col.id, {"created_at": 0})

    def test_update_status_missing_id(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            update_status(conn, 9999, {"name": "y"})

    def test_get_status_by_name(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="done"))
        assert get_status_by_name(conn, workspace.id, "done") == col
        assert get_status_by_name(conn, workspace.id, "nope") is None

    def test_get_status_by_name_case_insensitive(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="In Progress"))
        assert get_status_by_name(conn, workspace.id, "in progress") == col
        assert get_status_by_name(conn, workspace.id, "IN PROGRESS") == col

    def test_unique_name_case_insensitive(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        insert_status(conn, NewStatus(workspace_id=workspace.id, name="Todo"))
        with pytest.raises(sqlite3.IntegrityError):
            insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))


# ---- Task ----


class TestTaskRepository:
    def _setup(self, conn: sqlite3.Connection) -> tuple[Workspace, Status]:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        return workspace, col

    def test_insert_returns_task(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        task = insert_task(
            conn, NewTask(workspace_id=workspace.id, title="do stuff", status_id=col.id)
        )
        assert isinstance(task, Task)
        assert task.title == "do stuff"
        assert task.archived is False
        assert task.priority == 1

    def test_get_task(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id))
        assert get_task(conn, task.id) == task

    def test_get_task_missing(self, conn: sqlite3.Connection) -> None:
        assert get_task(conn, 9999) is None

    def test_list_tasks_by_workspace(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        t1 = insert_task(
            conn, NewTask(workspace_id=workspace.id, title="a", status_id=col.id)
        )
        t2 = insert_task(
            conn, NewTask(workspace_id=workspace.id, title="b", status_id=col.id)
        )
        tasks = list_tasks(conn, workspace.id)
        assert tasks[0].id == t1.id
        assert tasks[1].id == t2.id

    def test_list_tasks_excludes_archived(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        insert_task(conn, NewTask(workspace_id=workspace.id, title="a", status_id=col.id))
        t2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="b", status_id=col.id))
        update_task(conn, t2.id, {"archived": True})
        assert len(list_tasks(conn, workspace.id)) == 1
        assert len(list_tasks(conn, workspace.id, include_archived=True)) == 2

    def test_list_tasks_by_status(self, conn: sqlite3.Connection) -> None:
        workspace, col1 = self._setup(conn)
        col2 = insert_status(conn, NewStatus(workspace_id=workspace.id, name="done"))
        insert_task(conn, NewTask(workspace_id=workspace.id, title="a", status_id=col1.id))
        insert_task(conn, NewTask(workspace_id=workspace.id, title="b", status_id=col2.id))
        assert len(list_tasks_by_status(conn, col1.id)) == 1
        assert len(list_tasks_by_status(conn, col2.id)) == 1

    def test_update_task(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="old", status_id=col.id))
        updated = update_task(conn, task.id, {"title": "new", "priority": 3})
        assert updated.title == "new"
        assert updated.priority == 3

    def test_update_task_bad_field(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id))
        with pytest.raises(ValueError, match="disallowed"):
            update_task(conn, task.id, {"id": 99})

    def test_update_task_missing_id(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            update_task(conn, 9999, {"title": "y"})

    def test_list_tasks_by_status_excludes_archived(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        insert_task(conn, NewTask(workspace_id=workspace.id, title="a", status_id=col.id))
        t2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="b", status_id=col.id))
        update_task(conn, t2.id, {"archived": True})
        assert len(list_tasks_by_status(conn, col.id)) == 1
        assert len(list_tasks_by_status(conn, col.id, include_archived=True)) == 2

    def test_get_task_by_title(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        task = insert_task(
            conn, NewTask(workspace_id=workspace.id, title="Find me", status_id=col.id)
        )
        found = get_task_by_title(conn, workspace.id, "Find me")
        assert found is not None
        assert found.id == task.id
        assert found.title == "Find me"

    def test_get_task_by_title_missing(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        assert get_task_by_title(conn, workspace.id, "nonexistent") is None

    def test_get_task_by_title_case_insensitive(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        task = insert_task(
            conn, NewTask(workspace_id=workspace.id, title="Fix Login", status_id=col.id)
        )
        assert get_task_by_title(conn, workspace.id, "fix login") is not None
        assert get_task_by_title(conn, workspace.id, "FIX LOGIN") is not None

    def test_unique_title_case_insensitive(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        insert_task(conn, NewTask(workspace_id=workspace.id, title="Fix Login", status_id=col.id))
        with pytest.raises(sqlite3.IntegrityError):
            insert_task(
                conn, NewTask(workspace_id=workspace.id, title="fix login", status_id=col.id)
            )

    def test_priority_at_lower_bound(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        task = insert_task(
            conn, NewTask(workspace_id=workspace.id, title="low", status_id=col.id, priority=1)
        )
        assert task.priority == 1

    def test_priority_at_upper_bound(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        task = insert_task(
            conn, NewTask(workspace_id=workspace.id, title="high", status_id=col.id, priority=5)
        )
        assert task.priority == 5

    def test_priority_accepts_unbounded_integers(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        task_low = insert_task(
            conn, NewTask(workspace_id=workspace.id, title="t-low", status_id=col.id, priority=-1)
        )
        task_high = insert_task(
            conn, NewTask(workspace_id=workspace.id, title="t-high", status_id=col.id, priority=42)
        )
        assert task_low.priority == -1
        assert task_high.priority == 42

    def test_empty_title_allowed(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="", status_id=col.id))
        assert task.title == ""

    def test_insert_task_with_all_optional_fields(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        task = insert_task(
            conn,
            NewTask(
                workspace_id=workspace.id,
                title="full",
                status_id=col.id,
                description="details here",
                priority=3,
                due_date=1700000000,
                start_date=1699000000,
                finish_date=1701000000,
            ),
        )
        assert task.title == "full"
        assert task.description == "details here"
        assert task.priority == 3
        assert task.due_date == 1700000000
        assert task.start_date == 1699000000
        assert task.finish_date == 1701000000


# ---- Edges ----


class TestEdgeRepository:
    def _setup_tasks(self, conn: sqlite3.Connection) -> tuple[Task, Task, Task]:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        t1 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t1", status_id=col.id))
        t2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t2", status_id=col.id))
        t3 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t3", status_id=col.id))
        return t1, t2, t3

    def _setup_groups(self, conn: sqlite3.Connection) -> tuple[int, int, int, int]:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        g1 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g1")).id
        g2 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g2")).id
        g3 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g3")).id
        return g1, g2, g3, workspace.id

    # ---- Task→Task edges ----

    def test_add_and_list_task_targets(self, conn: sqlite3.Connection) -> None:
        t1, t2, t3 = self._setup_tasks(conn)
        add_edge(conn, "task", t1.id, "task", t2.id, t1.workspace_id, "blocks")
        add_edge(conn, "task", t1.id, "task", t3.id, t1.workspace_id, "blocks")
        targets = list_edge_targets_from(conn, "task", t1.id)
        assert {nid for _, nid in targets} == {t2.id, t3.id}

    def test_list_task_sources(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup_tasks(conn)
        add_edge(conn, "task", t1.id, "task", t2.id, t1.workspace_id, "blocks")
        sources = list_edge_sources_into(conn, "task", t2.id)
        assert {nid for _, nid in sources} == {t1.id}

    def test_archive_task_edge(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup_tasks(conn)
        add_edge(conn, "task", t1.id, "task", t2.id, t1.workspace_id, "blocks")
        archive_edge(conn, "task", t1.id, "task", t2.id, "blocks")
        assert list_edge_targets_from(conn, "task", t1.id) == ()
        # Row still exists with archived=1
        row = conn.execute(
            "SELECT archived FROM edges WHERE from_type='task' AND from_id=? AND to_id=?",
            (t1.id, t2.id),
        ).fetchone()
        assert row is not None
        assert row["archived"] == 1

    def test_archive_nonexistent_is_silent(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup_tasks(conn)
        archive_edge(conn, "task", t1.id, "task", t2.id, "blocks")  # no-op

    def test_task_edge_targets_from_hydrated(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup_tasks(conn)
        add_edge(conn, "task", t1.id, "task", t2.id, t1.workspace_id, "blocks")
        results = list_edge_targets_from_hydrated(conn, "task", t1.id)
        assert len(results) == 1
        to_type, to_id, title, kind = results[0]
        assert to_type == "task"
        assert to_id == t2.id
        assert title == "t2"
        assert kind == "blocks"

    def test_task_edge_sources_into_hydrated(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup_tasks(conn)
        add_edge(conn, "task", t1.id, "task", t2.id, t1.workspace_id, "blocks")
        results = list_edge_sources_into_hydrated(conn, "task", t2.id)
        assert len(results) == 1
        from_type, from_id, title, kind = results[0]
        assert from_type == "task"
        assert from_id == t1.id
        assert title == "t1"
        assert kind == "blocks"

    def test_duplicate_edge_upsert(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup_tasks(conn)
        add_edge(conn, "task", t1.id, "task", t2.id, t1.workspace_id, "blocks")
        add_edge(conn, "task", t1.id, "task", t2.id, t1.workspace_id, "blocks")  # upsert
        targets = list_edge_targets_from(conn, "task", t1.id)
        assert len(targets) == 1

    def test_self_task_edge_raises(self, conn: sqlite3.Connection) -> None:
        t1, _, _ = self._setup_tasks(conn)
        with pytest.raises(sqlite3.IntegrityError):
            add_edge(conn, "task", t1.id, "task", t1.id, t1.workspace_id, "blocks")

    def test_list_all_edge_rows_includes_metadata(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup_tasks(conn)
        add_edge(conn, "task", t1.id, "task", t2.id, t1.workspace_id, "blocks")
        rows = list_all_edge_rows(conn)
        assert len(rows) == 1
        assert rows[0]["kind"] == "blocks"
        assert rows[0]["metadata"] == {}

    def test_list_all_edge_rows_excludes_nothing(self, conn: sqlite3.Connection) -> None:
        """list_all_edge_rows includes archived rows (used for export)."""
        t1, t2, _ = self._setup_tasks(conn)
        add_edge(conn, "task", t1.id, "task", t2.id, t1.workspace_id, "blocks")
        archive_edge(conn, "task", t1.id, "task", t2.id, "blocks")
        rows = list_all_edge_rows(conn)
        assert len(rows) == 1
        assert rows[0]["archived"] is True

    def test_edge_stored_with_correct_columns(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup_tasks(conn)
        add_edge(conn, "task", t1.id, "task", t2.id, t1.workspace_id, "blocks")
        row = conn.execute(
            "SELECT kind FROM edges WHERE from_type='task' AND from_id=? AND to_id=?",
            (t1.id, t2.id),
        ).fetchone()
        assert row["kind"] == "blocks"

    def test_readd_after_archive(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup_tasks(conn)
        add_edge(conn, "task", t2.id, "task", t1.id, t2.workspace_id, "blocks")
        archive_edge(conn, "task", t2.id, "task", t1.id, "blocks")
        add_edge(conn, "task", t2.id, "task", t1.id, t2.workspace_id, "blocks")  # no crash
        targets = list_edge_targets_from(conn, "task", t2.id)
        assert ("task", t1.id) in targets

    def test_get_active_edge(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup_tasks(conn)
        assert get_active_edge(conn, "task", t1.id, "task", t2.id, "blocks") is None
        add_edge(conn, "task", t1.id, "task", t2.id, t1.workspace_id, "blocks")
        assert get_active_edge(conn, "task", t1.id, "task", t2.id, "blocks") is not None

    def test_get_active_edge_archived_returns_none(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup_tasks(conn)
        add_edge(conn, "task", t1.id, "task", t2.id, t1.workspace_id, "blocks")
        archive_edge(conn, "task", t1.id, "task", t2.id, "blocks")
        assert get_active_edge(conn, "task", t1.id, "task", t2.id, "blocks") is None

    def test_get_archived_edge(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup_tasks(conn)
        assert get_archived_edge(conn, "task", t1.id, "task", t2.id, "blocks") is None
        add_edge(conn, "task", t1.id, "task", t2.id, t1.workspace_id, "blocks")
        assert get_archived_edge(conn, "task", t1.id, "task", t2.id, "blocks") is None
        archive_edge(conn, "task", t1.id, "task", t2.id, "blocks")
        assert get_archived_edge(conn, "task", t1.id, "task", t2.id, "blocks") is not None

    def test_list_all_active_via_workspace(self, conn: sqlite3.Connection) -> None:
        t1, t2, t3 = self._setup_tasks(conn)
        add_edge(conn, "task", t2.id, "task", t1.id, t2.workspace_id, "blocks")
        add_edge(conn, "task", t3.id, "task", t1.id, t3.workspace_id, "blocks")
        items = list_edges_by_workspace(conn, t1.workspace_id)
        pairs = {(e.from_id, e.to_id, e.kind) for e in items}
        assert pairs == {(t2.id, t1.id, "blocks"), (t3.id, t1.id, "blocks")}

    def test_list_workspace_edges_excludes_archived(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup_tasks(conn)
        add_edge(conn, "task", t2.id, "task", t1.id, t2.workspace_id, "blocks")
        archive_edge(conn, "task", t2.id, "task", t1.id, "blocks")
        assert list_edges_by_workspace(conn, t1.workspace_id) == ()

    # ---- Group→Group edges ----

    def test_add_and_list_group_targets(self, conn: sqlite3.Connection) -> None:
        g1, g2, g3, ws = self._setup_groups(conn)
        add_edge(conn, "group", g1, "group", g2, ws, "blocks")
        add_edge(conn, "group", g1, "group", g3, ws, "blocks")
        targets = list_edge_targets_from(conn, "group", g1)
        assert {nid for _, nid in targets} == {g2, g3}

    def test_archive_group_edge(self, conn: sqlite3.Connection) -> None:
        g1, g2, _, ws = self._setup_groups(conn)
        add_edge(conn, "group", g1, "group", g2, ws, "blocks")
        archive_edge(conn, "group", g1, "group", g2, "blocks")
        assert list_edge_targets_from(conn, "group", g1) == ()
        row = conn.execute(
            "SELECT archived FROM edges WHERE from_type='group' AND from_id=? AND to_id=?",
            (g1, g2),
        ).fetchone()
        assert row is not None
        assert row["archived"] == 1

    def test_duplicate_group_edge_upsert(self, conn: sqlite3.Connection) -> None:
        g1, g2, _, ws = self._setup_groups(conn)
        add_edge(conn, "group", g1, "group", g2, ws, "blocks")
        add_edge(conn, "group", g1, "group", g2, ws, "blocks")  # upsert
        targets = list_edge_targets_from(conn, "group", g1)
        assert len(targets) == 1

    def test_self_group_edge_raises(self, conn: sqlite3.Connection) -> None:
        g1, _, _, ws = self._setup_groups(conn)
        with pytest.raises(sqlite3.IntegrityError):
            add_edge(conn, "group", g1, "group", g1, ws, "blocks")

    def test_group_edge_sources_into_hydrated(self, conn: sqlite3.Connection) -> None:
        g1, g2, _, ws = self._setup_groups(conn)
        add_edge(conn, "group", g1, "group", g2, ws, "related-to")
        results = list_edge_sources_into_hydrated(conn, "group", g2)
        assert len(results) == 1
        from_type, from_id, title, kind = results[0]
        assert from_type == "group"
        assert from_id == g1
        assert kind == "related-to"

    def test_readd_group_edge_after_archive(self, conn: sqlite3.Connection) -> None:
        g1, g2, _, ws = self._setup_groups(conn)
        add_edge(conn, "group", g1, "group", g2, ws, "blocks")
        archive_edge(conn, "group", g1, "group", g2, "blocks")
        add_edge(conn, "group", g1, "group", g2, ws, "blocks")  # no crash
        targets = list_edge_targets_from(conn, "group", g1)
        assert ("group", g2) in targets

    # ---- Cross-type edges ----

    def test_cross_type_edge_task_to_group(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t1", status_id=col.id))
        group = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g1"))
        add_edge(conn, "task", task.id, "group", group.id, workspace.id, "spawns")
        targets = list_edge_targets_from(conn, "task", task.id)
        assert ("group", group.id) in targets


# ---- Edge metadata ----


class TestEdgeMetadata:
    def _setup(self, conn: sqlite3.Connection) -> tuple[Task, Task]:
        workspace = insert_workspace(conn, NewWorkspace(name="w"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        t1 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t1", status_id=col.id))
        t2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t2", status_id=col.id))
        add_edge(conn, "task", t1.id, "task", t2.id, t1.workspace_id, "blocks")
        return t1, t2

    def test_get_empty_metadata(self, conn: sqlite3.Connection) -> None:
        t1, t2 = self._setup(conn)
        assert get_edge_metadata(conn, "task", t1.id, "task", t2.id, "blocks") == {}

    def test_set_and_get_metadata(self, conn: sqlite3.Connection) -> None:
        t1, t2 = self._setup(conn)
        set_edge_metadata_key(conn, "task", t1.id, "task", t2.id, "blocks", "note", "urgent")
        assert get_edge_metadata(conn, "task", t1.id, "task", t2.id, "blocks") == {"note": "urgent"}

    def test_remove_metadata_key(self, conn: sqlite3.Connection) -> None:
        t1, t2 = self._setup(conn)
        set_edge_metadata_key(conn, "task", t1.id, "task", t2.id, "blocks", "note", "urgent")
        remove_edge_metadata_key(conn, "task", t1.id, "task", t2.id, "blocks", "note")
        assert get_edge_metadata(conn, "task", t1.id, "task", t2.id, "blocks") == {}

    def test_replace_metadata(self, conn: sqlite3.Connection) -> None:
        t1, t2 = self._setup(conn)
        replace_edge_metadata(conn, "task", t1.id, "task", t2.id, "blocks", '{"a": "1", "b": "2"}')
        assert get_edge_metadata(conn, "task", t1.id, "task", t2.id, "blocks") == {"a": "1", "b": "2"}

    def test_get_nonexistent_edge_raises(self, conn: sqlite3.Connection) -> None:
        t1, t2 = self._setup(conn)
        with pytest.raises(LookupError):
            get_edge_metadata(conn, "task", t1.id, "task", 9999, "blocks")

    def test_archived_edge_metadata_is_invisible(self, conn: sqlite3.Connection) -> None:
        """All metadata ops on an archived edge must raise LookupError."""
        t1, t2 = self._setup(conn)
        set_edge_metadata_key(conn, "task", t1.id, "task", t2.id, "blocks", "note", "v")
        archive_edge(conn, "task", t1.id, "task", t2.id, "blocks")
        with pytest.raises(LookupError):
            get_edge_metadata(conn, "task", t1.id, "task", t2.id, "blocks")
        with pytest.raises(LookupError):
            set_edge_metadata_key(conn, "task", t1.id, "task", t2.id, "blocks", "k", "v")
        with pytest.raises(LookupError):
            remove_edge_metadata_key(conn, "task", t1.id, "task", t2.id, "blocks", "note")
        with pytest.raises(LookupError):
            replace_edge_metadata(conn, "task", t1.id, "task", t2.id, "blocks", "{}")

    def test_group_edge_metadata(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="w"))
        g1 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g1")).id
        g2 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g2")).id
        add_edge(conn, "group", g1, "group", g2, workspace.id, "blocks")
        set_edge_metadata_key(conn, "group", g1, "group", g2, "blocks", "note", "critical")
        assert get_edge_metadata(conn, "group", g1, "group", g2, "blocks") == {"note": "critical"}
        remove_edge_metadata_key(conn, "group", g1, "group", g2, "blocks", "note")
        assert get_edge_metadata(conn, "group", g1, "group", g2, "blocks") == {}
        replace_edge_metadata(conn, "group", g1, "group", g2, "blocks", '{"x": "y"}')
        assert get_edge_metadata(conn, "group", g1, "group", g2, "blocks") == {"x": "y"}


# ---- Journal ----


class TestJournalRepository:
    def test_insert_returns_journal_entry(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id))
        h = insert_journal_entry(
            conn,
            NewJournalEntry(
                entity_type=EntityType.TASK,
                entity_id=task.id,
                workspace_id=task.workspace_id,
                field=TaskField.TITLE,
                old_value="t",
                new_value="new",
                source="tui",
            ),
        )
        assert isinstance(h, JournalEntry)
        assert h.entity_type == EntityType.TASK
        assert h.entity_id == task.id
        assert h.field == TaskField.TITLE
        assert h.old_value == "t"
        assert h.new_value == "new"

    def test_list_journal_ordered_desc(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id))
        h1 = insert_journal_entry(
            conn,
            NewJournalEntry(
                entity_type=EntityType.TASK,
                entity_id=task.id,
                workspace_id=task.workspace_id,
                field=TaskField.TITLE,
                new_value="v1",
                source="tui",
            ),
        )
        h2 = insert_journal_entry(
            conn,
            NewJournalEntry(
                entity_type=EntityType.TASK,
                entity_id=task.id,
                workspace_id=task.workspace_id,
                field=TaskField.TITLE,
                new_value="v2",
                source="tui",
            ),
        )
        history = list_journal(conn, EntityType.TASK, task.id)
        assert len(history) == 2
        # DESC order: h2 first (later changed_at), then h1
        assert history[0].id == h2.id
        assert history[1].id == h1.id


class TestListTasksFiltered:
    def _seed(self, conn: sqlite3.Connection):
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col1 = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        col2 = insert_status(conn, NewStatus(workspace_id=workspace.id, name="done"))
        grp = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g"))
        t1 = insert_task(
            conn,
            NewTask(
                workspace_id=workspace.id,
                title="Fix login bug",
                status_id=col1.id,
                priority=3,
            ),
        )
        set_task_group_id(conn, t1.id, grp.id)
        t2 = insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="Add search", status_id=col1.id, priority=1),
        )
        t3 = insert_task(
            conn,
            NewTask(
                workspace_id=workspace.id,
                title="Deploy release",
                status_id=col2.id,
                priority=2,
            ),
        )
        set_task_group_id(conn, t3.id, grp.id)
        return workspace, col1, col2, grp, t1, t2, t3

    def test_no_filter(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, grp, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, workspace.id)
        assert len(result) == 3

    def test_filter_by_column(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, grp, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, workspace.id, task_filter=TaskFilter(status_id=col1.id))
        assert len(result) == 2
        assert all(t.status_id == col1.id for t in result)

    def test_filter_by_priority(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, grp, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, workspace.id, task_filter=TaskFilter(priority=3))
        assert len(result) == 1
        assert result[0].title == "Fix login bug"

    def test_filter_by_search(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, grp, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, workspace.id, task_filter=TaskFilter(search="login"))
        assert len(result) == 1
        assert result[0].title == "Fix login bug"

    def test_search_case_insensitive(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, grp, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, workspace.id, task_filter=TaskFilter(search="LOGIN"))
        assert len(result) == 1

    def test_combined_filters(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, grp, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(
            conn,
            workspace.id,
            task_filter=TaskFilter(status_id=col1.id, group_id=grp.id),
        )
        assert len(result) == 1
        assert result[0].title == "Fix login bug"

    def test_include_archived(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, grp, t1, t2, t3 = self._seed(conn)
        update_task(conn, t1.id, {"archived": True})
        result = list_tasks_filtered(conn, workspace.id)
        assert len(result) == 2
        result_all = list_tasks_filtered(
            conn, workspace.id, task_filter=TaskFilter(include_archived=True)
        )
        assert len(result_all) == 3

    def test_no_matches(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, grp, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, workspace.id, task_filter=TaskFilter(priority=5))
        assert result == ()

    def test_filter_by_group(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, grp, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, workspace.id, task_filter=TaskFilter(group_id=grp.id))
        assert {t.id for t in result} == {t1.id, t3.id}


# ---- Group ----


class TestGroupRepository:
    def _setup(self, conn: sqlite3.Connection) -> Workspace:
        return insert_workspace(conn, NewWorkspace(name="b"))

    def test_insert_returns_group(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        grp = insert_group(conn, NewGroup(workspace_id=workspace.id, title="Frontend"))
        assert isinstance(grp, Group)
        assert grp.title == "Frontend"
        assert grp.archived is False
        assert grp.parent_id is None
        assert grp.id >= 1

    def test_get_group(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        grp = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g"))
        assert get_group(conn, grp.id) == grp

    def test_get_group_missing(self, conn: sqlite3.Connection) -> None:
        assert get_group(conn, 9999) is None

    def test_get_group_by_title(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        grp = insert_group(conn, NewGroup(workspace_id=workspace.id, title="Backend"))
        assert get_group_by_title(conn, workspace.id, None, "Backend") == grp
        assert get_group_by_title(conn, workspace.id, None, "nope") is None

    def test_get_group_by_title_case_insensitive(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        grp = insert_group(conn, NewGroup(workspace_id=workspace.id, title="Backend"))
        assert get_group_by_title(conn, workspace.id, None, "backend") == grp
        assert get_group_by_title(conn, workspace.id, None, "BACKEND") == grp

    def test_unique_title_case_insensitive(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        insert_group(conn, NewGroup(workspace_id=workspace.id, title="Backend"))
        with pytest.raises(sqlite3.IntegrityError):
            insert_group(conn, NewGroup(workspace_id=workspace.id, title="backend"))

    def test_list_groups_excludes_archived(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        insert_group(conn, NewGroup(workspace_id=workspace.id, title="g1"))
        g2 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g2"))
        update_group(conn, g2.id, {"archived": True})
        assert len(list_groups(conn, workspace.id)) == 1
        assert len(list_groups(conn, workspace.id, include_archived=True)) == 2

    def test_list_groups_only_archived(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        insert_group(conn, NewGroup(workspace_id=workspace.id, title="active"))
        g2 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="gone"))
        update_group(conn, g2.id, {"archived": True})
        groups = list_groups(conn, workspace.id, only_archived=True)
        assert len(groups) == 1
        assert groups[0].title == "gone"

    def test_list_groups_ordered_by_id(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        g1 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="first"))
        g2 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="second"))
        groups = list_groups(conn, workspace.id)
        assert groups[0].id == g1.id
        assert groups[1].id == g2.id

    def test_update_group(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        grp = insert_group(conn, NewGroup(workspace_id=workspace.id, title="old"))
        updated = update_group(conn, grp.id, {"title": "new"})
        assert updated.title == "new"

    def test_update_group_bad_field(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        grp = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g"))
        with pytest.raises(ValueError, match="disallowed"):
            update_group(conn, grp.id, {"id": 99})

    def test_update_group_missing_id(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            update_group(conn, 9999, {"title": "x"})

    def test_unique_title_per_workspace(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        insert_group(conn, NewGroup(workspace_id=workspace.id, title="dup"))
        with pytest.raises(sqlite3.IntegrityError):
            insert_group(conn, NewGroup(workspace_id=workspace.id, title="dup"))

    def test_same_title_different_parents(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        p1 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="parent1"))
        p2 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="parent2"))
        g1 = insert_group(
            conn, NewGroup(workspace_id=workspace.id, title="shared", parent_id=p1.id)
        )
        g2 = insert_group(
            conn, NewGroup(workspace_id=workspace.id, title="shared", parent_id=p2.id)
        )
        assert g1.id != g2.id

    def test_insert_with_parent(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        parent = insert_group(conn, NewGroup(workspace_id=workspace.id, title="parent"))
        child = insert_group(
            conn, NewGroup(workspace_id=workspace.id, title="child", parent_id=parent.id)
        )
        assert child.parent_id == parent.id

    def test_insert_with_invalid_parent_fk(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        with pytest.raises(sqlite3.IntegrityError):
            insert_group(
                conn, NewGroup(workspace_id=workspace.id, title="bad", parent_id=9999)
            )


class TestTaskGroupRepository:
    def _setup(self, conn: sqlite3.Connection) -> tuple[Workspace, Status, Group]:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        grp = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g"))
        return workspace, col, grp

    def test_assign_and_get(self, conn: sqlite3.Connection) -> None:
        workspace, col, grp = self._setup(conn)
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id))
        set_task_group_id(conn, task.id, grp.id)
        assert get_task(conn, task.id).group_id == grp.id

    def test_get_unassigned_returns_none(self, conn: sqlite3.Connection) -> None:
        workspace, col, _ = self._setup(conn)
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id))
        assert get_task(conn, task.id).group_id is None

    def test_update_replaces_group(self, conn: sqlite3.Connection) -> None:
        workspace, col, grp1 = self._setup(conn)
        grp2 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g2"))
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id))
        set_task_group_id(conn, task.id, grp1.id)
        set_task_group_id(conn, task.id, grp2.id)
        assert get_task(conn, task.id).group_id == grp2.id

    def test_unassign(self, conn: sqlite3.Connection) -> None:
        workspace, col, grp = self._setup(conn)
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id))
        set_task_group_id(conn, task.id, grp.id)
        set_task_group_id(conn, task.id, None)
        assert get_task(conn, task.id).group_id is None

    def test_list_task_ids_by_group(self, conn: sqlite3.Connection) -> None:
        workspace, col, grp = self._setup(conn)
        t1 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t1", status_id=col.id))
        t2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t2", status_id=col.id))
        set_task_group_id(conn, t1.id, grp.id)
        set_task_group_id(conn, t2.id, grp.id)
        ids = list_task_ids_by_group(conn, grp.id)
        assert set(ids) == {t1.id, t2.id}

    def test_list_ungrouped_task_ids(self, conn: sqlite3.Connection) -> None:
        workspace, col, grp = self._setup(conn)
        t1 = insert_task(conn, NewTask(workspace_id=workspace.id, title="grouped", status_id=col.id))
        t2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="ungrouped", status_id=col.id))
        set_task_group_id(conn, t1.id, grp.id)
        ids = list_ungrouped_task_ids(conn, workspace.id)
        assert ids == (t2.id,)

    def test_group_mismatched_workspace_raises(self, conn: sqlite3.Connection) -> None:
        workspace, col, grp = self._setup(conn)
        ws2 = insert_workspace(conn, NewWorkspace(name="other"))
        col2 = insert_status(conn, NewStatus(workspace_id=ws2.id, name="todo"))
        task = insert_task(conn, NewTask(workspace_id=ws2.id, title="t", status_id=col2.id))
        with pytest.raises(sqlite3.IntegrityError):
            set_task_group_id(conn, task.id, grp.id)

    def test_group_matching_workspace_succeeds(self, conn: sqlite3.Connection) -> None:
        workspace, col, grp = self._setup(conn)
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id))
        set_task_group_id(conn, task.id, grp.id)
        assert get_task(conn, task.id).group_id == grp.id

    def test_hard_delete_group_with_tasks_raises(self, conn: sqlite3.Connection) -> None:
        workspace, col, grp = self._setup(conn)
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id))
        set_task_group_id(conn, task.id, grp.id)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM groups WHERE id = ?", (grp.id,))

    def test_bulk_unassign_by_group(self, conn: sqlite3.Connection) -> None:
        workspace, col, grp = self._setup(conn)
        t1 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t1", status_id=col.id))
        t2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t2", status_id=col.id))
        set_task_group_id(conn, t1.id, grp.id)
        set_task_group_id(conn, t2.id, grp.id)
        unassign_tasks_from_group(conn, grp.id)
        assert get_task(conn, t1.id).group_id is None
        assert get_task(conn, t2.id).group_id is None


class TestGroupTreeRepository:
    def _setup(self, conn: sqlite3.Connection) -> Workspace:
        return insert_workspace(conn, NewWorkspace(name="b"))

    def test_list_child_groups(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        parent = insert_group(conn, NewGroup(workspace_id=workspace.id, title="parent"))
        c1 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="c1", parent_id=parent.id))
        c2 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="c2", parent_id=parent.id))
        children = list_child_groups(conn, parent.id)
        assert {g.id for g in children} == {c1.id, c2.id}

    def test_list_child_groups_excludes_archived(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        parent = insert_group(conn, NewGroup(workspace_id=workspace.id, title="parent"))
        insert_group(conn, NewGroup(workspace_id=workspace.id, title="c1", parent_id=parent.id))
        c2 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="c2", parent_id=parent.id))
        update_group(conn, c2.id, {"archived": True})
        assert len(list_child_groups(conn, parent.id)) == 1
        assert len(list_child_groups(conn, parent.id, include_archived=True)) == 2

    def test_get_subtree_group_ids(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        root = insert_group(conn, NewGroup(workspace_id=workspace.id, title="root"))
        mid = insert_group(conn, NewGroup(workspace_id=workspace.id, title="mid", parent_id=root.id))
        leaf = insert_group(conn, NewGroup(workspace_id=workspace.id, title="leaf", parent_id=mid.id))
        ids = get_subtree_group_ids(conn, root.id)
        assert set(ids) == {root.id, mid.id, leaf.id}

    def test_subtree_includes_archived(self, conn: sqlite3.Connection) -> None:
        # Archived descendants must be included so cycle detection sees the full graph.
        # A cycle through an archived intermediate node is still a cycle.
        workspace = self._setup(conn)
        root = insert_group(conn, NewGroup(workspace_id=workspace.id, title="root"))
        child = insert_group(conn, NewGroup(workspace_id=workspace.id, title="child", parent_id=root.id))
        update_group(conn, child.id, {"archived": True})
        ids = get_subtree_group_ids(conn, root.id)
        assert set(ids) == {root.id, child.id}

    def test_get_group_ancestry(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        root = insert_group(conn, NewGroup(workspace_id=workspace.id, title="root"))
        mid = insert_group(conn, NewGroup(workspace_id=workspace.id, title="mid", parent_id=root.id))
        leaf = insert_group(conn, NewGroup(workspace_id=workspace.id, title="leaf", parent_id=mid.id))
        ancestry = get_group_ancestry(conn, leaf.id)
        assert [g.id for g in ancestry] == [root.id, mid.id, leaf.id]

    def test_get_group_ancestry_root(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        root = insert_group(conn, NewGroup(workspace_id=workspace.id, title="root"))
        ancestry = get_group_ancestry(conn, root.id)
        assert len(ancestry) == 1
        assert ancestry[0].id == root.id

    def test_get_group_ancestry_missing(self, conn: sqlite3.Connection) -> None:
        ancestry = get_group_ancestry(conn, 9999)
        assert ancestry == ()

    def test_reparent_children(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        g1 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g1"))
        g2 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g2"))
        child = insert_group(conn, NewGroup(workspace_id=workspace.id, title="child", parent_id=g1.id))
        reparent_children(conn, g1.id, g2.id)
        updated = get_group(conn, child.id)
        assert updated is not None
        assert updated.parent_id == g2.id

    def test_reparent_to_none(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        parent = insert_group(conn, NewGroup(workspace_id=workspace.id, title="parent"))
        child = insert_group(conn, NewGroup(workspace_id=workspace.id, title="child", parent_id=parent.id))
        reparent_children(conn, parent.id, None)
        updated = get_group(conn, child.id)
        assert updated is not None
        assert updated.parent_id is None


class TestBatchGroupQueries:
    def _setup(self, conn: sqlite3.Connection) -> tuple[Workspace, Status]:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        return workspace, col

    # -- list_tasks_by_ids --

    def test_list_tasks_by_ids_returns_tasks(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        t1 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t1", status_id=col.id))
        t2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t2", status_id=col.id))
        tasks = list_tasks_by_ids(conn, (t1.id, t2.id))
        assert len(tasks) == 2
        assert {t.id for t in tasks} == {t1.id, t2.id}
        assert all(isinstance(t, Task) for t in tasks)

    def test_list_tasks_by_ids_empty(self, conn: sqlite3.Connection) -> None:
        assert list_tasks_by_ids(conn, ()) == ()

    def test_list_tasks_by_ids_missing_ids_ignored(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        t1 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t1", status_id=col.id))
        tasks = list_tasks_by_ids(conn, (t1.id, 9999))
        assert len(tasks) == 1
        assert tasks[0].id == t1.id

    # -- batch_task_ids_by_group --

    def test_batch_task_ids_by_group(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        g1 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g1"))
        g2 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g2"))
        t1 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t1", status_id=col.id))
        t2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t2", status_id=col.id))
        set_task_group_id(conn, t1.id, g1.id)
        set_task_group_id(conn, t2.id, g1.id)
        result = batch_task_ids_by_group(conn, (g1.id, g2.id))
        assert set(result[g1.id]) == {t1.id, t2.id}
        assert result[g2.id] == ()

    def test_batch_task_ids_by_group_empty(self, conn: sqlite3.Connection) -> None:
        assert batch_task_ids_by_group(conn, ()) == {}

    # -- batch_child_ids_by_group --

    def test_batch_child_ids_by_group(self, conn: sqlite3.Connection) -> None:
        workspace, _ = self._setup(conn)
        parent = insert_group(conn, NewGroup(workspace_id=workspace.id, title="parent"))
        c1 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="c1", parent_id=parent.id))
        c2 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="c2", parent_id=parent.id))
        result = batch_child_ids_by_group(conn, (parent.id,))
        assert set(result[parent.id]) == {c1.id, c2.id}

    def test_batch_child_ids_excludes_archived(self, conn: sqlite3.Connection) -> None:
        workspace, _ = self._setup(conn)
        parent = insert_group(conn, NewGroup(workspace_id=workspace.id, title="parent"))
        c1 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="c1", parent_id=parent.id))
        c2 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="c2", parent_id=parent.id))
        update_group(conn, c2.id, {"archived": True})
        result = batch_child_ids_by_group(conn, (parent.id,))
        assert result[parent.id] == (c1.id,)
        result_all = batch_child_ids_by_group(conn, (parent.id,), include_archived=True)
        assert set(result_all[parent.id]) == {c1.id, c2.id}

    def test_batch_child_ids_by_group_empty(self, conn: sqlite3.Connection) -> None:
        assert batch_child_ids_by_group(conn, ()) == {}

    # -- list_groups_by_workspace --

    def test_list_groups_by_workspace(self, conn: sqlite3.Connection) -> None:
        workspace, _ = self._setup(conn)
        g1 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g1"))
        g2 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g2"))
        result = list_groups_by_workspace(conn, workspace.id)
        assert len(result) == 2
        assert result[0].id == g1.id
        assert result[1].id == g2.id

    def test_list_groups_by_workspace_excludes_archived(self, conn: sqlite3.Connection) -> None:
        workspace, _ = self._setup(conn)
        insert_group(conn, NewGroup(workspace_id=workspace.id, title="g1"))
        g2 = insert_group(conn, NewGroup(workspace_id=workspace.id, title="g2"))
        update_group(conn, g2.id, {"archived": True})
        assert len(list_groups_by_workspace(conn, workspace.id)) == 1
        assert len(list_groups_by_workspace(conn, workspace.id, include_archived=True)) == 2

    def test_list_groups_by_workspace_multi_group(self, conn: sqlite3.Connection) -> None:
        workspace, _ = self._setup(conn)
        insert_group(conn, NewGroup(workspace_id=workspace.id, title="g1"))
        insert_group(conn, NewGroup(workspace_id=workspace.id, title="g2"))
        result = list_groups_by_workspace(conn, workspace.id)
        assert len(result) == 2

    def test_list_groups_by_workspace_empty(self, conn: sqlite3.Connection) -> None:
        workspace, _ = self._setup(conn)
        assert list_groups_by_workspace(conn, workspace.id) == ()


# ---- Task metadata ----


class TestTaskMetadata:
    def _setup(self, conn: sqlite3.Connection) -> int:
        w = insert_workspace(conn, NewWorkspace(name="w"))
        s = insert_status(conn, NewStatus(workspace_id=w.id, name="todo"))
        t = insert_task(conn, NewTask(workspace_id=w.id, title="t", status_id=s.id))
        return t.id

    def test_set_metadata_key(self, conn: sqlite3.Connection) -> None:
        tid = self._setup(conn)
        set_task_metadata_key(conn, tid, "branch", "feat/kv")
        row = conn.execute("SELECT metadata FROM tasks WHERE id = ?", (tid,)).fetchone()
        assert '"branch"' in row["metadata"]
        assert "feat/kv" in row["metadata"]

    def test_overwrite_metadata_key(self, conn: sqlite3.Connection) -> None:
        tid = self._setup(conn)
        set_task_metadata_key(conn, tid, "branch", "feat/old")
        set_task_metadata_key(conn, tid, "branch", "feat/new")
        row = conn.execute("SELECT metadata FROM tasks WHERE id = ?", (tid,)).fetchone()
        import json

        meta = json.loads(row["metadata"])
        assert meta["branch"] == "feat/new"

    def test_remove_metadata_key(self, conn: sqlite3.Connection) -> None:
        tid = self._setup(conn)
        set_task_metadata_key(conn, tid, "branch", "feat/kv")
        remove_task_metadata_key(conn, tid, "branch")
        row = conn.execute("SELECT metadata FROM tasks WHERE id = ?", (tid,)).fetchone()
        import json

        assert json.loads(row["metadata"]) == {}

    def test_remove_nonexistent_key_is_noop(self, conn: sqlite3.Connection) -> None:
        """At the repo level, removing a key that doesn't exist is a no-op (rowcount=1)."""
        tid = self._setup(conn)
        remove_task_metadata_key(conn, tid, "nope")  # should not raise
        row = conn.execute("SELECT metadata FROM tasks WHERE id = ?", (tid,)).fetchone()
        import json

        assert json.loads(row["metadata"]) == {}

    def test_set_on_nonexistent_task_raises(self, conn: sqlite3.Connection) -> None:
        self._setup(conn)
        with pytest.raises(LookupError, match="task 999 not found"):
            set_task_metadata_key(conn, 999, "k", "v")

    def test_remove_on_nonexistent_task_raises(self, conn: sqlite3.Connection) -> None:
        self._setup(conn)
        with pytest.raises(LookupError, match="task 999 not found"):
            remove_task_metadata_key(conn, 999, "k")

    def test_key_with_dot_treated_literally(self, conn: sqlite3.Connection) -> None:
        """Keys with dots should be treated as flat keys, not JSON path separators."""
        tid = self._setup(conn)
        set_task_metadata_key(conn, tid, "deploy.env", "prod")
        task = get_task(conn, tid)
        assert task is not None
        assert task.metadata == {"deploy.env": "prod"}

    def test_copy_task_metadata(self, conn: sqlite3.Connection) -> None:
        src = self._setup(conn)
        # Fresh task on the same workspace serves as the copy destination.
        dst_row = conn.execute(
            "SELECT workspace_id, status_id FROM tasks WHERE id = ?", (src,)
        ).fetchone()
        dst_task = insert_task(
            conn,
            NewTask(
                workspace_id=dst_row["workspace_id"], title="dst", status_id=dst_row["status_id"]
            ),
        )
        set_task_metadata_key(conn, src, "branch", "feat/kv")
        set_task_metadata_key(conn, src, "jira", "proj-1")
        copy_task_metadata(conn, src, dst_task.id)
        dst_meta = get_task(conn, dst_task.id).metadata
        assert dst_meta == {"branch": "feat/kv", "jira": "proj-1"}
        # Source should be unchanged.
        assert get_task(conn, src).metadata == {"branch": "feat/kv", "jira": "proj-1"}

    def test_copy_task_metadata_nonexistent_dst_raises(self, conn: sqlite3.Connection) -> None:
        src = self._setup(conn)
        with pytest.raises(LookupError, match="task 999 not found"):
            copy_task_metadata(conn, src, 999)


class TestEntityMetadata:
    """Repository-layer metadata set/remove for workspaces and groups.

    Exercises the generic _set_metadata_key / _remove_metadata_key helpers via
    each public per-entity wrapper. Service-layer case normalization and
    validation is covered in test_service.py.
    """

    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int]:
        w = insert_workspace(conn, NewWorkspace(name="w"))
        g = insert_group(conn, NewGroup(workspace_id=w.id, title="g"))
        return w.id, g.id

    def test_workspace_set_remove(self, conn: sqlite3.Connection) -> None:
        wid, _ = self._setup(conn)
        set_workspace_metadata_key(conn, wid, "env", "prod")
        import json as _json

        row = conn.execute("SELECT metadata FROM workspaces WHERE id = ?", (wid,)).fetchone()
        assert _json.loads(row["metadata"]) == {"env": "prod"}
        remove_workspace_metadata_key(conn, wid, "env")
        row = conn.execute("SELECT metadata FROM workspaces WHERE id = ?", (wid,)).fetchone()
        assert _json.loads(row["metadata"]) == {}

    def test_group_set_remove(self, conn: sqlite3.Connection) -> None:
        _, gid = self._setup(conn)
        set_group_metadata_key(conn, gid, "sprint", "3")
        import json as _json

        row = conn.execute("SELECT metadata FROM groups WHERE id = ?", (gid,)).fetchone()
        assert _json.loads(row["metadata"]) == {"sprint": "3"}
        remove_group_metadata_key(conn, gid, "sprint")
        row = conn.execute("SELECT metadata FROM groups WHERE id = ?", (gid,)).fetchone()
        assert _json.loads(row["metadata"]) == {}

    def test_workspace_nonexistent_raises(self, conn: sqlite3.Connection) -> None:
        self._setup(conn)
        with pytest.raises(LookupError, match="workspace 999 not found"):
            set_workspace_metadata_key(conn, 999, "k", "v")

    def test_group_nonexistent_raises(self, conn: sqlite3.Connection) -> None:
        self._setup(conn)
        with pytest.raises(LookupError, match="group 999 not found"):
            set_group_metadata_key(conn, 999, "k", "v")
