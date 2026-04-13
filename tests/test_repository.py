from __future__ import annotations

import sqlite3

import pytest

from stx.models import (
    EntityType,
    Group,
    JournalEntry,
    NewGroup,
    NewJournalEntry,
    NewProject,
    NewStatus,
    NewTag,
    NewTask,
    NewWorkspace,
    Project,
    Status,
    Tag,
    Task,
    TaskField,
    TaskFilter,
    Workspace,
)
from stx.repository import (
    add_group_edge,
    add_tag_to_task,
    add_task_edge,
    archive_group_edge,
    archive_task_edge,
    batch_child_ids_by_group,
    batch_tag_ids_by_task,
    batch_task_ids_by_group,
    copy_task_metadata,
    get_archived_group_edge_kind,
    get_archived_task_edge_kind,
    get_group,
    get_group_ancestry,
    get_group_by_title,
    get_group_edge_kind,
    get_group_edge_metadata,
    get_project,
    get_project_by_name,
    get_status,
    get_status_by_name,
    get_subtree_group_ids,
    get_tag,
    get_tag_by_name,
    get_task,
    get_task_by_title,
    get_task_edge_kind,
    get_task_edge_metadata,
    get_workspace,
    get_workspace_by_name,
    insert_group,
    insert_journal_entry,
    insert_project,
    insert_status,
    insert_tag,
    insert_task,
    insert_workspace,
    list_all_group_edge_rows,
    list_all_group_edges,
    list_all_task_edge_rows,
    list_all_task_edges,
    list_child_groups,
    list_group_edge_sources_into_hydrated,
    list_group_edge_targets_from,
    list_group_edge_targets_from_hydrated,
    list_groups,
    list_groups_by_workspace,
    list_journal,
    list_projects,
    list_statuses,
    list_tag_ids_by_task,
    list_tags,
    list_tags_by_task,
    list_task_edge_sources_into,
    list_task_edge_sources_into_hydrated,
    list_task_edge_targets_from,
    list_task_edge_targets_from_hydrated,
    list_task_ids_by_group,
    list_task_ids_by_project,
    list_task_ids_by_tag,
    list_tasks,
    list_tasks_by_ids,
    list_tasks_by_project,
    list_tasks_by_status,
    list_tasks_filtered,
    list_ungrouped_task_ids,
    list_workspaces,
    remove_group_edge_metadata_key,
    remove_group_metadata_key,
    remove_project_metadata_key,
    remove_tag_from_task,
    remove_task_edge_metadata_key,
    remove_task_metadata_key,
    remove_workspace_metadata_key,
    reparent_children,
    replace_group_edge_metadata,
    replace_task_edge_metadata,
    set_group_edge_metadata_key,
    set_group_metadata_key,
    set_project_metadata_key,
    set_task_edge_metadata_key,
    set_task_group_id,
    set_task_metadata_key,
    set_workspace_metadata_key,
    unassign_tasks_from_group,
    update_group,
    update_project,
    update_status,
    update_tag,
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


# ---- Project ----


class TestProjectRepository:
    def test_insert_returns_project(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="p1"))
        assert isinstance(proj, Project)
        assert proj.name == "p1"
        assert proj.description is None

    def test_get_project(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="p1"))
        assert get_project(conn, proj.id) == proj

    def test_get_project_missing(self, conn: sqlite3.Connection) -> None:
        assert get_project(conn, 9999) is None

    def test_list_projects_excludes_archived(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        insert_project(conn, NewProject(workspace_id=workspace.id, name="p1"))
        p2 = insert_project(conn, NewProject(workspace_id=workspace.id, name="p2"))
        update_project(conn, p2.id, {"archived": True})
        assert len(list_projects(conn, workspace.id)) == 1
        assert len(list_projects(conn, workspace.id, include_archived=True)) == 2

    def test_list_projects_only_archived(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        insert_project(conn, NewProject(workspace_id=workspace.id, name="p1"))
        p2 = insert_project(conn, NewProject(workspace_id=workspace.id, name="p2"))
        update_project(conn, p2.id, {"archived": True})
        result = list_projects(conn, workspace.id, only_archived=True)
        assert len(result) == 1
        assert result[0].name == "p2"

    def test_update_project(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="old"))
        updated = update_project(conn, proj.id, {"name": "new", "description": "hi"})
        assert updated.name == "new"
        assert updated.description == "hi"

    def test_update_project_bad_field(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="x"))
        with pytest.raises(ValueError, match="disallowed"):
            update_project(conn, proj.id, {"id": 99})

    def test_update_project_missing_id(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            update_project(conn, 9999, {"name": "y"})

    def test_get_project_by_name(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="backend"))
        assert get_project_by_name(conn, workspace.id, "backend") == proj
        assert get_project_by_name(conn, workspace.id, "nope") is None

    def test_get_project_by_name_case_insensitive(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="Backend"))
        assert get_project_by_name(conn, workspace.id, "backend") == proj
        assert get_project_by_name(conn, workspace.id, "BACKEND") == proj

    def test_unique_name_case_insensitive(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        insert_project(conn, NewProject(workspace_id=workspace.id, name="Backend"))
        with pytest.raises(sqlite3.IntegrityError):
            insert_project(conn, NewProject(workspace_id=workspace.id, name="backend"))


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
            conn, NewTask(workspace_id=workspace.id, title="a", status_id=col.id, position=1)
        )
        t2 = insert_task(
            conn, NewTask(workspace_id=workspace.id, title="b", status_id=col.id, position=0)
        )
        tasks = list_tasks(conn, workspace.id)
        assert tasks[0].id == t2.id
        assert tasks[1].id == t1.id

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

    def test_list_tasks_by_project(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="p"))
        insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="a", status_id=col.id, project_id=proj.id),
        )
        insert_task(conn, NewTask(workspace_id=workspace.id, title="b", status_id=col.id))
        assert len(list_tasks_by_project(conn, proj.id)) == 1

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

    def test_list_tasks_by_project_excludes_archived(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="p"))
        insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="a", status_id=col.id, project_id=proj.id),
        )
        t2 = insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="b", status_id=col.id, project_id=proj.id),
        )
        update_task(conn, t2.id, {"archived": True})
        assert len(list_tasks_by_project(conn, proj.id)) == 1
        assert len(list_tasks_by_project(conn, proj.id, include_archived=True)) == 2

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
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="p"))
        task = insert_task(
            conn,
            NewTask(
                workspace_id=workspace.id,
                title="full",
                status_id=col.id,
                project_id=proj.id,
                description="details here",
                priority=3,
                due_date=1700000000,
                position=5,
                start_date=1699000000,
                finish_date=1701000000,
            ),
        )
        assert task.title == "full"
        assert task.project_id == proj.id
        assert task.description == "details here"
        assert task.priority == 3
        assert task.due_date == 1700000000
        assert task.position == 5
        assert task.start_date == 1699000000
        assert task.finish_date == 1701000000


# ---- Task edges ----


class TestTaskEdgeRepository:
    def _setup(self, conn: sqlite3.Connection) -> tuple[Task, Task, Task]:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        t1 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t1", status_id=col.id))
        t2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t2", status_id=col.id))
        t3 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t3", status_id=col.id))
        return t1, t2, t3

    def test_add_and_list_target_ids(self, conn: sqlite3.Connection) -> None:
        t1, t2, t3 = self._setup(conn)
        add_task_edge(conn, t1.id, t2.id, t1.workspace_id, kind="blocks")
        add_task_edge(conn, t1.id, t3.id, t1.workspace_id, kind="blocks")
        ids = list_task_edge_targets_from(conn, t1.id)
        assert set(ids) == {t2.id, t3.id}

    def test_list_source_ids(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_task_edge(conn, t1.id, t2.id, t1.workspace_id, kind="blocks")
        assert list_task_edge_sources_into(conn, t2.id) == (t1.id,)

    def test_archive_edge(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_task_edge(conn, t1.id, t2.id, t1.workspace_id, kind="blocks")
        archive_task_edge(conn, t1.id, t2.id)
        assert list_task_edge_targets_from(conn, t1.id) == ()
        # Row still exists in DB with archived=1
        row = conn.execute(
            "SELECT archived FROM task_edges WHERE source_id = ? AND target_id = ?",
            (t1.id, t2.id),
        ).fetchone()
        assert row is not None
        assert row["archived"] == 1

    def test_archive_nonexistent_is_silent(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        archive_task_edge(conn, t1.id, t2.id)  # no-op, no error

    def test_list_edge_targets_from_hydrated(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_task_edge(conn, t1.id, t2.id, t1.workspace_id, kind="blocks")
        results = list_task_edge_targets_from_hydrated(conn, t1.id)
        assert len(results) == 1
        task, kind = results[0]
        assert task.id == t2.id
        assert isinstance(task, Task)
        assert kind == "blocks"

    def test_list_edge_sources_into_hydrated(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_task_edge(conn, t1.id, t2.id, t1.workspace_id, kind="blocks")
        results = list_task_edge_sources_into_hydrated(conn, t2.id)
        assert len(results) == 1
        task, kind = results[0]
        assert task.id == t1.id
        assert kind == "blocks"

    def test_duplicate_edge_is_idempotent(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_task_edge(conn, t1.id, t2.id, t1.workspace_id, kind="blocks")
        add_task_edge(conn, t1.id, t2.id, t1.workspace_id, kind="blocks")  # upsert — no error
        assert list_task_edge_targets_from(conn, t1.id) == (t2.id,)

    def test_self_edge_raises(self, conn: sqlite3.Connection) -> None:
        t1, _, _ = self._setup(conn)
        with pytest.raises(sqlite3.IntegrityError):
            add_task_edge(conn, t1.id, t1.id, t1.workspace_id, kind="blocks")

    def test_list_all_task_edges(self, conn: sqlite3.Connection) -> None:
        t1, t2, t3 = self._setup(conn)
        add_task_edge(conn, t2.id, t1.id, t2.workspace_id, kind="blocks")
        add_task_edge(conn, t3.id, t1.id, t3.workspace_id, kind="blocks")
        deps = list_all_task_edges(conn)
        assert set(deps) == {(t2.id, t1.id, "blocks"), (t3.id, t1.id, "blocks")}

    def test_list_all_task_edges_empty(self, conn: sqlite3.Connection) -> None:
        self._setup(conn)
        assert list_all_task_edges(conn) == ()

    def test_list_all_excludes_archived(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_task_edge(conn, t2.id, t1.id, t2.workspace_id, kind="blocks")
        archive_task_edge(conn, t2.id, t1.id)
        assert list_all_task_edges(conn) == ()

    def test_readd_after_archive(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_task_edge(conn, t2.id, t1.id, t2.workspace_id, kind="blocks")
        archive_task_edge(conn, t2.id, t1.id)
        add_task_edge(
            conn, t2.id, t1.id, t2.workspace_id, kind="blocks"
        )  # re-create — should not crash
        assert list_task_edge_targets_from(conn, t2.id) == (t1.id,)

    def test_get_task_edge_kind_active(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        assert get_task_edge_kind(conn, t1.id, t2.id) is None
        add_task_edge(conn, t1.id, t2.id, t1.workspace_id, kind="blocks")
        assert get_task_edge_kind(conn, t1.id, t2.id) == "blocks"

    def test_get_task_edge_kind_archived_returns_none(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_task_edge(conn, t1.id, t2.id, t1.workspace_id, kind="blocks")
        archive_task_edge(conn, t1.id, t2.id)
        assert get_task_edge_kind(conn, t1.id, t2.id) is None

    def test_get_archived_task_edge_kind(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        assert get_archived_task_edge_kind(conn, t1.id, t2.id) is None
        add_task_edge(conn, t1.id, t2.id, t1.workspace_id, kind="blocks")
        # Active edge — archived lookup must still return None
        assert get_archived_task_edge_kind(conn, t1.id, t2.id) is None
        archive_task_edge(conn, t1.id, t2.id)
        assert get_archived_task_edge_kind(conn, t1.id, t2.id) == "blocks"

    def test_list_task_edge_targets_from_hydrated_returns_kind(
        self, conn: sqlite3.Connection
    ) -> None:
        t1, t2, _ = self._setup(conn)
        add_task_edge(conn, t1.id, t2.id, t1.workspace_id, kind="blocks")
        results = list_task_edge_targets_from_hydrated(conn, t1.id)
        assert len(results) == 1
        task, kind = results[0]
        assert task.id == t2.id
        assert kind == "blocks"

    def test_list_task_edge_sources_into_hydrated_returns_kind(
        self, conn: sqlite3.Connection
    ) -> None:
        t1, t2, _ = self._setup(conn)
        add_task_edge(conn, t1.id, t2.id, t1.workspace_id, kind="related-to")
        results = list_task_edge_sources_into_hydrated(conn, t2.id)
        assert len(results) == 1
        task, kind = results[0]
        assert task.id == t1.id
        assert kind == "related-to"

    def test_list_all_task_edge_rows_includes_metadata(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_task_edge(conn, t1.id, t2.id, t1.workspace_id, kind="blocks")
        rows = list_all_task_edge_rows(conn)
        assert len(rows) == 1
        assert rows[0]["kind"] == "blocks"
        assert rows[0]["metadata"] == {}

    def test_add_edge_with_kind(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_task_edge(conn, t1.id, t2.id, t1.workspace_id, kind="blocks")
        row = conn.execute(
            "SELECT kind FROM task_edges WHERE source_id = ? AND target_id = ?",
            (t1.id, t2.id),
        ).fetchone()
        assert row["kind"] == "blocks"

    def test_edge_missing_kind_raises(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        with pytest.raises(TypeError):
            add_task_edge(conn, t1.id, t2.id)  # type: ignore[call-arg]


# ---- Group edges ----


class TestGroupEdgeRepository:
    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int, int, int]:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="p"))
        g1 = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g1")
        ).id
        g2 = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g2")
        ).id
        g3 = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g3")
        ).id
        return g1, g2, g3, workspace.id

    def test_add_and_list_target_ids(self, conn: sqlite3.Connection) -> None:
        g1, g2, g3, ws = self._setup(conn)
        add_group_edge(conn, g1, g2, ws, kind="blocks")
        add_group_edge(conn, g1, g3, ws, kind="blocks")
        ids = list_group_edge_targets_from(conn, g1)
        assert set(ids) == {g2, g3}

    def test_archive_group_edge(self, conn: sqlite3.Connection) -> None:
        g1, g2, _, ws = self._setup(conn)
        add_group_edge(conn, g1, g2, ws, kind="blocks")
        archive_group_edge(conn, g1, g2)
        assert list_group_edge_targets_from(conn, g1) == ()
        # Row still exists in DB with archived=1
        row = conn.execute(
            "SELECT archived FROM group_edges WHERE source_id = ? AND target_id = ?",
            (g1, g2),
        ).fetchone()
        assert row is not None
        assert row["archived"] == 1

    def test_archive_nonexistent_is_silent(self, conn: sqlite3.Connection) -> None:
        g1, g2, _, _ = self._setup(conn)
        archive_group_edge(conn, g1, g2)  # no-op, no error

    def test_duplicate_is_idempotent(self, conn: sqlite3.Connection) -> None:
        g1, g2, _, ws = self._setup(conn)
        add_group_edge(conn, g1, g2, ws, kind="blocks")
        add_group_edge(conn, g1, g2, ws, kind="blocks")  # upsert — no error
        assert list_group_edge_targets_from(conn, g1) == (g2,)

    def test_self_edge_raises(self, conn: sqlite3.Connection) -> None:
        g1, _, _, ws = self._setup(conn)
        with pytest.raises(sqlite3.IntegrityError):
            add_group_edge(conn, g1, g1, ws, kind="blocks")

    def test_list_all_group_edges(self, conn: sqlite3.Connection) -> None:
        g1, g2, g3, ws = self._setup(conn)
        add_group_edge(conn, g2, g1, ws, kind="blocks")
        add_group_edge(conn, g3, g1, ws, kind="blocks")
        deps = list_all_group_edges(conn)
        assert set(deps) == {(g2, g1, "blocks"), (g3, g1, "blocks")}

    def test_list_all_group_edges_empty(self, conn: sqlite3.Connection) -> None:
        self._setup(conn)
        assert list_all_group_edges(conn) == ()

    def test_list_all_group_edges_excludes_archived(self, conn: sqlite3.Connection) -> None:
        g1, g2, _, ws = self._setup(conn)
        add_group_edge(conn, g1, g2, ws, kind="blocks")
        archive_group_edge(conn, g1, g2)
        assert list_all_group_edges(conn) == ()

    def test_readd_group_edge_after_archive(self, conn: sqlite3.Connection) -> None:
        g1, g2, _, ws = self._setup(conn)
        add_group_edge(conn, g1, g2, ws, kind="blocks")
        archive_group_edge(conn, g1, g2)
        add_group_edge(conn, g1, g2, ws, kind="blocks")  # re-create — should not crash
        assert list_group_edge_targets_from(conn, g1) == (g2,)

    def test_get_group_edge_kind_active(self, conn: sqlite3.Connection) -> None:
        g1, g2, _, ws = self._setup(conn)
        assert get_group_edge_kind(conn, g1, g2) is None
        add_group_edge(conn, g1, g2, ws, kind="blocks")
        assert get_group_edge_kind(conn, g1, g2) == "blocks"

    def test_get_archived_group_edge_kind(self, conn: sqlite3.Connection) -> None:
        g1, g2, _, ws = self._setup(conn)
        assert get_archived_group_edge_kind(conn, g1, g2) is None
        add_group_edge(conn, g1, g2, ws, kind="blocks")
        # Active edge — archived lookup must still return None
        assert get_archived_group_edge_kind(conn, g1, g2) is None
        archive_group_edge(conn, g1, g2)
        assert get_archived_group_edge_kind(conn, g1, g2) == "blocks"

    def test_list_group_edge_targets_from_hydrated_returns_kind(
        self, conn: sqlite3.Connection
    ) -> None:
        g1, g2, _, ws = self._setup(conn)
        add_group_edge(conn, g1, g2, ws, kind="blocks")
        results = list_group_edge_targets_from_hydrated(conn, g1)
        assert len(results) == 1
        group, kind = results[0]
        assert group.id == g2
        assert kind == "blocks"

    def test_list_group_edge_sources_into_hydrated_returns_kind(
        self, conn: sqlite3.Connection
    ) -> None:
        g1, g2, _, ws = self._setup(conn)
        add_group_edge(conn, g1, g2, ws, kind="related-to")
        results = list_group_edge_sources_into_hydrated(conn, g2)
        assert len(results) == 1
        group, kind = results[0]
        assert group.id == g1
        assert kind == "related-to"

    def test_list_all_group_edge_rows(self, conn: sqlite3.Connection) -> None:
        g1, g2, _, ws = self._setup(conn)
        add_group_edge(conn, g1, g2, ws, kind="blocks")
        rows = list_all_group_edge_rows(conn)
        assert len(rows) == 1
        assert rows[0]["source_id"] == g1
        assert rows[0]["target_id"] == g2
        assert rows[0]["kind"] == "blocks"
        assert rows[0]["metadata"] == {}


# ---- Edge metadata ----


class TestTaskEdgeMetadata:
    def _setup(self, conn: sqlite3.Connection) -> tuple[Task, Task]:
        workspace = insert_workspace(conn, NewWorkspace(name="w"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        t1 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t1", status_id=col.id))
        t2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t2", status_id=col.id))
        add_task_edge(conn, t1.id, t2.id, t1.workspace_id, kind="blocks")
        return t1, t2

    def test_get_empty_metadata(self, conn: sqlite3.Connection) -> None:
        t1, t2 = self._setup(conn)
        assert get_task_edge_metadata(conn, t1.id, t2.id) == {}

    def test_set_and_get_metadata(self, conn: sqlite3.Connection) -> None:
        t1, t2 = self._setup(conn)
        set_task_edge_metadata_key(conn, t1.id, t2.id, "note", "urgent")
        assert get_task_edge_metadata(conn, t1.id, t2.id) == {"note": "urgent"}

    def test_remove_metadata_key(self, conn: sqlite3.Connection) -> None:
        t1, t2 = self._setup(conn)
        set_task_edge_metadata_key(conn, t1.id, t2.id, "note", "urgent")
        remove_task_edge_metadata_key(conn, t1.id, t2.id, "note")
        assert get_task_edge_metadata(conn, t1.id, t2.id) == {}

    def test_replace_metadata(self, conn: sqlite3.Connection) -> None:
        t1, t2 = self._setup(conn)
        replace_task_edge_metadata(conn, t1.id, t2.id, '{"a": "1", "b": "2"}')
        assert get_task_edge_metadata(conn, t1.id, t2.id) == {"a": "1", "b": "2"}

    def test_get_nonexistent_edge_raises(self, conn: sqlite3.Connection) -> None:
        t1, t2 = self._setup(conn)
        with pytest.raises(LookupError):
            get_task_edge_metadata(conn, t1.id, 9999)

    def test_archived_edge_metadata_is_invisible(self, conn: sqlite3.Connection) -> None:
        """All metadata ops on an archived task edge must raise LookupError."""
        t1, t2 = self._setup(conn)
        set_task_edge_metadata_key(conn, t1.id, t2.id, "note", "v")
        archive_task_edge(conn, t1.id, t2.id)
        with pytest.raises(LookupError):
            get_task_edge_metadata(conn, t1.id, t2.id)
        with pytest.raises(LookupError):
            set_task_edge_metadata_key(conn, t1.id, t2.id, "k", "v")
        with pytest.raises(LookupError):
            remove_task_edge_metadata_key(conn, t1.id, t2.id, "note")
        with pytest.raises(LookupError):
            replace_task_edge_metadata(conn, t1.id, t2.id, "{}")


class TestGroupEdgeMetadata:
    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int]:
        workspace = insert_workspace(conn, NewWorkspace(name="w"))
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="p"))
        g1 = insert_group(
            conn, NewGroup(workspace_id=workspace.id, project_id=proj.id, title="g1")
        ).id
        g2 = insert_group(
            conn, NewGroup(workspace_id=workspace.id, project_id=proj.id, title="g2")
        ).id
        add_group_edge(conn, g1, g2, workspace.id, kind="blocks")
        return g1, g2

    def test_get_empty_metadata(self, conn: sqlite3.Connection) -> None:
        g1, g2 = self._setup(conn)
        assert get_group_edge_metadata(conn, g1, g2) == {}

    def test_set_and_get_metadata(self, conn: sqlite3.Connection) -> None:
        g1, g2 = self._setup(conn)
        set_group_edge_metadata_key(conn, g1, g2, "note", "critical")
        assert get_group_edge_metadata(conn, g1, g2) == {"note": "critical"}

    def test_remove_metadata_key(self, conn: sqlite3.Connection) -> None:
        g1, g2 = self._setup(conn)
        set_group_edge_metadata_key(conn, g1, g2, "note", "critical")
        remove_group_edge_metadata_key(conn, g1, g2, "note")
        assert get_group_edge_metadata(conn, g1, g2) == {}

    def test_replace_metadata(self, conn: sqlite3.Connection) -> None:
        g1, g2 = self._setup(conn)
        replace_group_edge_metadata(conn, g1, g2, '{"x": "y"}')
        assert get_group_edge_metadata(conn, g1, g2) == {"x": "y"}

    def test_archived_edge_metadata_is_invisible(self, conn: sqlite3.Connection) -> None:
        """All metadata ops on an archived group edge must raise LookupError."""
        g1, g2 = self._setup(conn)
        set_group_edge_metadata_key(conn, g1, g2, "note", "v")
        archive_group_edge(conn, g1, g2)
        with pytest.raises(LookupError):
            get_group_edge_metadata(conn, g1, g2)
        with pytest.raises(LookupError):
            set_group_edge_metadata_key(conn, g1, g2, "k", "v")
        with pytest.raises(LookupError):
            remove_group_edge_metadata_key(conn, g1, g2, "note")
        with pytest.raises(LookupError):
            replace_group_edge_metadata(conn, g1, g2, "{}")


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


# ---- Project helper ----


class TestProjectHelper:
    def test_list_task_ids_by_project(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="p"))
        t1 = insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="a", status_id=col.id, project_id=proj.id),
        )
        insert_task(conn, NewTask(workspace_id=workspace.id, title="b", status_id=col.id))
        ids = list_task_ids_by_project(conn, proj.id)
        assert ids == (t1.id,)


class TestListTasksFiltered:
    def _seed(self, conn: sqlite3.Connection):
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col1 = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        col2 = insert_status(conn, NewStatus(workspace_id=workspace.id, name="done"))
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="p"))
        t1 = insert_task(
            conn,
            NewTask(
                workspace_id=workspace.id,
                title="Fix login bug",
                status_id=col1.id,
                project_id=proj.id,
                priority=3,
            ),
        )
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
                project_id=proj.id,
                priority=2,
            ),
        )
        return workspace, col1, col2, proj, t1, t2, t3

    def test_no_filter(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, workspace.id)
        assert len(result) == 3

    def test_filter_by_column(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, workspace.id, task_filter=TaskFilter(status_id=col1.id))
        assert len(result) == 2
        assert all(t.status_id == col1.id for t in result)

    def test_filter_by_project(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, workspace.id, task_filter=TaskFilter(project_id=proj.id))
        assert len(result) == 2
        assert all(t.project_id == proj.id for t in result)

    def test_filter_by_priority(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, workspace.id, task_filter=TaskFilter(priority=3))
        assert len(result) == 1
        assert result[0].title == "Fix login bug"

    def test_filter_by_search(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, workspace.id, task_filter=TaskFilter(search="login"))
        assert len(result) == 1
        assert result[0].title == "Fix login bug"

    def test_search_case_insensitive(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, workspace.id, task_filter=TaskFilter(search="LOGIN"))
        assert len(result) == 1

    def test_combined_filters(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(
            conn,
            workspace.id,
            task_filter=TaskFilter(status_id=col1.id, project_id=proj.id),
        )
        assert len(result) == 1
        assert result[0].title == "Fix login bug"

    def test_include_archived(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        update_task(conn, t1.id, {"archived": True})
        result = list_tasks_filtered(conn, workspace.id)
        assert len(result) == 2
        result_all = list_tasks_filtered(
            conn, workspace.id, task_filter=TaskFilter(include_archived=True)
        )
        assert len(result_all) == 3

    def test_no_matches(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, workspace.id, task_filter=TaskFilter(priority=5))
        assert result == ()

    def test_filter_by_tag(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        tag = insert_tag(conn, NewTag(workspace_id=workspace.id, name="bug"))
        add_tag_to_task(conn, t1.id, tag.id)
        result = list_tasks_filtered(conn, workspace.id, task_filter=TaskFilter(tag_id=tag.id))
        assert len(result) == 1
        assert result[0].id == t1.id

    def test_filter_by_group(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        grp = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="frontend")
        )
        set_task_group_id(conn, t1.id, grp.id)
        set_task_group_id(conn, t3.id, grp.id)
        result = list_tasks_filtered(conn, workspace.id, task_filter=TaskFilter(group_id=grp.id))
        assert {t.id for t in result} == {t1.id, t3.id}


# ---- Tag ----


class TestTagRepository:
    def _setup(self, conn: sqlite3.Connection) -> Workspace:
        return insert_workspace(conn, NewWorkspace(name="b"))

    def test_insert_and_get(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        tag = insert_tag(conn, NewTag(workspace_id=workspace.id, name="bug"))
        assert isinstance(tag, Tag)
        assert tag.name == "bug"
        assert tag.workspace_id == workspace.id
        assert tag.archived is False
        fetched = get_tag(conn, tag.id)
        assert fetched is not None
        assert fetched.id == tag.id

    def test_get_missing(self, conn: sqlite3.Connection) -> None:
        assert get_tag(conn, 9999) is None

    def test_get_by_name(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        tag = insert_tag(conn, NewTag(workspace_id=workspace.id, name="feature"))
        fetched = get_tag_by_name(conn, workspace.id, "feature")
        assert fetched is not None
        assert fetched.id == tag.id

    def test_get_by_name_missing(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        assert get_tag_by_name(conn, workspace.id, "nope") is None

    def test_list_excludes_archived(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        insert_tag(conn, NewTag(workspace_id=workspace.id, name="a"))
        t2 = insert_tag(conn, NewTag(workspace_id=workspace.id, name="b"))
        update_tag(conn, t2.id, {"archived": True})
        assert len(list_tags(conn, workspace.id)) == 1
        assert len(list_tags(conn, workspace.id, include_archived=True)) == 2

    def test_list_only_archived(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        insert_tag(conn, NewTag(workspace_id=workspace.id, name="active"))
        t2 = insert_tag(conn, NewTag(workspace_id=workspace.id, name="gone"))
        update_tag(conn, t2.id, {"archived": True})
        tags = list_tags(conn, workspace.id, only_archived=True)
        assert len(tags) == 1
        assert tags[0].name == "gone"

    def test_list_ordered_by_name(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        insert_tag(conn, NewTag(workspace_id=workspace.id, name="zebra"))
        insert_tag(conn, NewTag(workspace_id=workspace.id, name="alpha"))
        insert_tag(conn, NewTag(workspace_id=workspace.id, name="middle"))
        tags = list_tags(conn, workspace.id)
        assert [t.name for t in tags] == ["alpha", "middle", "zebra"]

    def test_update(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        tag = insert_tag(conn, NewTag(workspace_id=workspace.id, name="old"))
        updated = update_tag(conn, tag.id, {"name": "new"})
        assert updated.name == "new"

    def test_update_bad_field(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        tag = insert_tag(conn, NewTag(workspace_id=workspace.id, name="t"))
        with pytest.raises(ValueError):
            update_tag(conn, tag.id, {"workspace_id": 999})

    def test_update_missing(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            update_tag(conn, 9999, {"name": "x"})

    def test_unique_name_per_workspace(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        insert_tag(conn, NewTag(workspace_id=workspace.id, name="dup"))
        with pytest.raises(sqlite3.IntegrityError):
            insert_tag(conn, NewTag(workspace_id=workspace.id, name="dup"))

    def test_unique_name_case_insensitive(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        insert_tag(conn, NewTag(workspace_id=workspace.id, name="Bug"))
        with pytest.raises(sqlite3.IntegrityError):
            insert_tag(conn, NewTag(workspace_id=workspace.id, name="bug"))

    def test_get_by_name_case_insensitive(self, conn: sqlite3.Connection) -> None:
        workspace = self._setup(conn)
        tag = insert_tag(conn, NewTag(workspace_id=workspace.id, name="Bug"))
        fetched = get_tag_by_name(conn, workspace.id, "bug")
        assert fetched is not None
        assert fetched.id == tag.id

    def test_same_name_different_workspaces(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, NewWorkspace(name="b1"))
        b2 = insert_workspace(conn, NewWorkspace(name="b2"))
        t1 = insert_tag(conn, NewTag(workspace_id=b1.id, name="shared"))
        t2 = insert_tag(conn, NewTag(workspace_id=b2.id, name="shared"))
        assert t1.id != t2.id


class TestTaskTagRepository:
    def _setup(self, conn: sqlite3.Connection) -> tuple[Workspace, Status, Task, Tag, Tag]:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t1", status_id=col.id))
        tag1 = insert_tag(conn, NewTag(workspace_id=workspace.id, name="bug"))
        tag2 = insert_tag(conn, NewTag(workspace_id=workspace.id, name="feature"))
        return workspace, col, task, tag1, tag2

    def test_add_and_list_tag_ids(self, conn: sqlite3.Connection) -> None:
        _, _, task, tag1, tag2 = self._setup(conn)
        add_tag_to_task(conn, task.id, tag1.id)
        add_tag_to_task(conn, task.id, tag2.id)
        ids = list_tag_ids_by_task(conn, task.id)
        assert set(ids) == {tag1.id, tag2.id}

    def test_list_tag_ids_excludes_archived_by_default(self, conn: sqlite3.Connection) -> None:
        _, _, task, tag1, tag2 = self._setup(conn)
        add_tag_to_task(conn, task.id, tag1.id)
        add_tag_to_task(conn, task.id, tag2.id)
        update_tag(conn, tag1.id, {"archived": True})
        ids = list_tag_ids_by_task(conn, task.id)
        assert set(ids) == {tag2.id}

    def test_list_tag_ids_include_archived(self, conn: sqlite3.Connection) -> None:
        _, _, task, tag1, tag2 = self._setup(conn)
        add_tag_to_task(conn, task.id, tag1.id)
        add_tag_to_task(conn, task.id, tag2.id)
        update_tag(conn, tag1.id, {"archived": True})
        ids = list_tag_ids_by_task(conn, task.id, include_archived=True)
        assert set(ids) == {tag1.id, tag2.id}

    def test_list_tags_by_task(self, conn: sqlite3.Connection) -> None:
        _, _, task, tag1, tag2 = self._setup(conn)
        add_tag_to_task(conn, task.id, tag1.id)
        add_tag_to_task(conn, task.id, tag2.id)
        tags = list_tags_by_task(conn, task.id)
        assert len(tags) == 2
        assert all(isinstance(t, Tag) for t in tags)
        # ordered by name
        assert tags[0].name == "bug"
        assert tags[1].name == "feature"

    def test_list_tags_by_task_excludes_archived(self, conn: sqlite3.Connection) -> None:
        _, _, task, tag1, tag2 = self._setup(conn)
        add_tag_to_task(conn, task.id, tag1.id)
        add_tag_to_task(conn, task.id, tag2.id)
        update_tag(conn, tag1.id, {"archived": True})
        assert len(list_tags_by_task(conn, task.id)) == 1
        assert len(list_tags_by_task(conn, task.id, include_archived=True)) == 2

    def test_list_task_ids_by_tag(self, conn: sqlite3.Connection) -> None:
        workspace, col, task, tag1, _ = self._setup(conn)
        task2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t2", status_id=col.id))
        add_tag_to_task(conn, task.id, tag1.id)
        add_tag_to_task(conn, task2.id, tag1.id)
        ids = list_task_ids_by_tag(conn, tag1.id)
        assert set(ids) == {task.id, task2.id}

    def test_remove_tag_from_task(self, conn: sqlite3.Connection) -> None:
        _, _, task, tag1, _ = self._setup(conn)
        add_tag_to_task(conn, task.id, tag1.id)
        assert len(list_tag_ids_by_task(conn, task.id)) == 1
        remove_tag_from_task(conn, task.id, tag1.id)
        assert list_tag_ids_by_task(conn, task.id) == ()

    def test_duplicate_tag_raises(self, conn: sqlite3.Connection) -> None:
        _, _, task, tag1, _ = self._setup(conn)
        add_tag_to_task(conn, task.id, tag1.id)
        with pytest.raises(sqlite3.IntegrityError):
            add_tag_to_task(conn, task.id, tag1.id)

    def test_batch_tag_ids_by_task(self, conn: sqlite3.Connection) -> None:
        workspace, col, task, tag1, tag2 = self._setup(conn)
        task2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t2", status_id=col.id))
        add_tag_to_task(conn, task.id, tag1.id)
        add_tag_to_task(conn, task.id, tag2.id)
        add_tag_to_task(conn, task2.id, tag1.id)
        result = batch_tag_ids_by_task(conn, (task.id, task2.id))
        assert set(result[task.id]) == {tag1.id, tag2.id}
        assert result[task2.id] == (tag1.id,)

    def test_batch_tag_ids_excludes_archived(self, conn: sqlite3.Connection) -> None:
        workspace, col, task, tag1, tag2 = self._setup(conn)
        add_tag_to_task(conn, task.id, tag1.id)
        add_tag_to_task(conn, task.id, tag2.id)
        update_tag(conn, tag1.id, {"archived": True})
        result = batch_tag_ids_by_task(conn, (task.id,))
        assert result[task.id] == (tag2.id,)
        result_all = batch_tag_ids_by_task(conn, (task.id,), include_archived=True)
        assert set(result_all[task.id]) == {tag1.id, tag2.id}

    def test_batch_tag_ids_empty(self, conn: sqlite3.Connection) -> None:
        assert batch_tag_ids_by_task(conn, ()) == {}


# ---- Group ----


class TestGroupRepository:
    def _setup(self, conn: sqlite3.Connection) -> tuple[Workspace, Project]:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="p"))
        return workspace, proj

    def test_insert_returns_group(self, conn: sqlite3.Connection) -> None:
        workspace, proj = self._setup(conn)
        grp = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="Frontend")
        )
        assert isinstance(grp, Group)
        assert grp.title == "Frontend"
        assert grp.archived is False
        assert grp.parent_id is None
        assert grp.id >= 1

    def test_get_group(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        grp = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g")
        )
        assert get_group(conn, grp.id) == grp

    def test_get_group_missing(self, conn: sqlite3.Connection) -> None:
        assert get_group(conn, 9999) is None

    def test_get_group_by_title(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        grp = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="Backend")
        )
        assert get_group_by_title(conn, proj.id, "Backend") == grp
        assert get_group_by_title(conn, proj.id, "nope") is None

    def test_get_group_by_title_case_insensitive(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        grp = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="Backend")
        )
        assert get_group_by_title(conn, proj.id, "backend") == grp
        assert get_group_by_title(conn, proj.id, "BACKEND") == grp

    def test_unique_title_case_insensitive(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="Backend")
        )
        with pytest.raises(sqlite3.IntegrityError):
            insert_group(
                conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="backend")
            )

    def test_list_groups_excludes_archived(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g1"))
        g2 = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g2")
        )
        update_group(conn, g2.id, {"archived": True})
        assert len(list_groups(conn, proj.id)) == 1
        assert len(list_groups(conn, proj.id, include_archived=True)) == 2

    def test_list_groups_only_archived(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="active")
        )
        g2 = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="gone")
        )
        update_group(conn, g2.id, {"archived": True})
        groups = list_groups(conn, proj.id, only_archived=True)
        assert len(groups) == 1
        assert groups[0].title == "gone"

    def test_list_groups_ordered_by_position(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        g1 = insert_group(
            conn,
            NewGroup(
                workspace_id=proj.workspace_id, project_id=proj.id, title="second", position=1
            ),
        )
        g2 = insert_group(
            conn,
            NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="first", position=0),
        )
        groups = list_groups(conn, proj.id)
        assert groups[0].id == g2.id
        assert groups[1].id == g1.id

    def test_update_group(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        grp = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="old")
        )
        updated = update_group(conn, grp.id, {"title": "new"})
        assert updated.title == "new"

    def test_update_group_bad_field(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        grp = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g")
        )
        with pytest.raises(ValueError, match="disallowed"):
            update_group(conn, grp.id, {"id": 99})

    def test_update_group_missing_id(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            update_group(conn, 9999, {"title": "x"})

    def test_unique_title_per_project(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="dup")
        )
        with pytest.raises(sqlite3.IntegrityError):
            insert_group(
                conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="dup")
            )

    def test_same_title_different_projects(self, conn: sqlite3.Connection) -> None:
        workspace, proj1 = self._setup(conn)
        proj2 = insert_project(conn, NewProject(workspace_id=workspace.id, name="p2"))
        g1 = insert_group(
            conn, NewGroup(workspace_id=proj1.workspace_id, project_id=proj1.id, title="shared")
        )
        g2 = insert_group(
            conn, NewGroup(workspace_id=proj2.workspace_id, project_id=proj2.id, title="shared")
        )
        assert g1.id != g2.id

    def test_insert_with_parent(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        parent = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="parent")
        )
        child = insert_group(
            conn,
            NewGroup(
                workspace_id=proj.workspace_id,
                project_id=proj.id,
                title="child",
                parent_id=parent.id,
            ),
        )
        assert child.parent_id == parent.id

    def test_insert_with_invalid_parent_fk(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        with pytest.raises(sqlite3.IntegrityError):
            insert_group(
                conn,
                NewGroup(
                    workspace_id=proj.workspace_id, project_id=proj.id, title="bad", parent_id=9999
                ),
            )


class TestTaskGroupRepository:
    def _setup(self, conn: sqlite3.Connection) -> tuple[Workspace, Status, Project, Group]:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="p"))
        grp = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g")
        )
        return workspace, col, proj, grp

    def test_assign_and_get(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp = self._setup(conn)
        task = insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="t", status_id=col.id, project_id=proj.id),
        )
        set_task_group_id(conn, task.id, grp.id)
        assert get_task(conn, task.id).group_id == grp.id

    def test_get_unassigned_returns_none(self, conn: sqlite3.Connection) -> None:
        workspace, col, _, _ = self._setup(conn)
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id))
        assert get_task(conn, task.id).group_id is None

    def test_update_replaces_group(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp1 = self._setup(conn)
        grp2 = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g2")
        )
        task = insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="t", status_id=col.id, project_id=proj.id),
        )
        set_task_group_id(conn, task.id, grp1.id)
        set_task_group_id(conn, task.id, grp2.id)
        assert get_task(conn, task.id).group_id == grp2.id

    def test_unassign(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp = self._setup(conn)
        task = insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="t", status_id=col.id, project_id=proj.id),
        )
        set_task_group_id(conn, task.id, grp.id)
        set_task_group_id(conn, task.id, None)
        assert get_task(conn, task.id).group_id is None

    def test_list_task_ids_by_group(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp = self._setup(conn)
        t1 = insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="t1", status_id=col.id, project_id=proj.id),
        )
        t2 = insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="t2", status_id=col.id, project_id=proj.id),
        )
        set_task_group_id(conn, t1.id, grp.id)
        set_task_group_id(conn, t2.id, grp.id)
        ids = list_task_ids_by_group(conn, grp.id)
        assert set(ids) == {t1.id, t2.id}

    def test_list_ungrouped_task_ids(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp = self._setup(conn)
        t1 = insert_task(
            conn,
            NewTask(
                workspace_id=workspace.id, title="grouped", status_id=col.id, project_id=proj.id
            ),
        )
        t2 = insert_task(
            conn,
            NewTask(
                workspace_id=workspace.id, title="ungrouped", status_id=col.id, project_id=proj.id
            ),
        )
        set_task_group_id(conn, t1.id, grp.id)
        ids = list_ungrouped_task_ids(conn, proj.id)
        assert ids == (t2.id,)

    def test_group_mismatched_project_raises(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp = self._setup(conn)
        proj2 = insert_project(conn, NewProject(workspace_id=workspace.id, name="p2"))
        task = insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="t", status_id=col.id, project_id=proj2.id),
        )
        with pytest.raises(sqlite3.IntegrityError):
            set_task_group_id(conn, task.id, grp.id)

    def test_group_matching_project_succeeds(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp = self._setup(conn)
        task = insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="t", status_id=col.id, project_id=proj.id),
        )
        set_task_group_id(conn, task.id, grp.id)
        assert get_task(conn, task.id).group_id == grp.id

    def test_change_project_while_grouped_raises(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp = self._setup(conn)
        proj2 = insert_project(conn, NewProject(workspace_id=workspace.id, name="p2"))
        task = insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="t", status_id=col.id, project_id=proj.id),
        )
        set_task_group_id(conn, task.id, grp.id)
        with pytest.raises(sqlite3.IntegrityError):
            update_task(conn, task.id, {"project_id": proj2.id})

    def test_group_without_project_raises(self, conn: sqlite3.Connection) -> None:
        workspace, col, _, grp = self._setup(conn)
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id))
        with pytest.raises(sqlite3.IntegrityError):
            set_task_group_id(conn, task.id, grp.id)

    def test_hard_delete_group_with_tasks_raises(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp = self._setup(conn)
        task = insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="t", status_id=col.id, project_id=proj.id),
        )
        set_task_group_id(conn, task.id, grp.id)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM groups WHERE id = ?", (grp.id,))

    def test_bulk_unassign_by_group(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp = self._setup(conn)
        t1 = insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="t1", status_id=col.id, project_id=proj.id),
        )
        t2 = insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="t2", status_id=col.id, project_id=proj.id),
        )
        set_task_group_id(conn, t1.id, grp.id)
        set_task_group_id(conn, t2.id, grp.id)
        unassign_tasks_from_group(conn, grp.id)
        assert get_task(conn, t1.id).group_id is None
        assert get_task(conn, t2.id).group_id is None


class TestGroupTreeRepository:
    def _setup(self, conn: sqlite3.Connection) -> tuple[Workspace, Project]:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="p"))
        return workspace, proj

    def test_list_child_groups(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        parent = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="parent")
        )
        c1 = insert_group(
            conn,
            NewGroup(
                workspace_id=proj.workspace_id, project_id=proj.id, title="c1", parent_id=parent.id
            ),
        )
        c2 = insert_group(
            conn,
            NewGroup(
                workspace_id=proj.workspace_id, project_id=proj.id, title="c2", parent_id=parent.id
            ),
        )
        children = list_child_groups(conn, parent.id)
        assert {g.id for g in children} == {c1.id, c2.id}

    def test_list_child_groups_excludes_archived(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        parent = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="parent")
        )
        insert_group(
            conn,
            NewGroup(
                workspace_id=proj.workspace_id, project_id=proj.id, title="c1", parent_id=parent.id
            ),
        )
        c2 = insert_group(
            conn,
            NewGroup(
                workspace_id=proj.workspace_id, project_id=proj.id, title="c2", parent_id=parent.id
            ),
        )
        update_group(conn, c2.id, {"archived": True})
        assert len(list_child_groups(conn, parent.id)) == 1
        assert len(list_child_groups(conn, parent.id, include_archived=True)) == 2

    def test_get_subtree_group_ids(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        root = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="root")
        )
        mid = insert_group(
            conn,
            NewGroup(
                workspace_id=proj.workspace_id, project_id=proj.id, title="mid", parent_id=root.id
            ),
        )
        leaf = insert_group(
            conn,
            NewGroup(
                workspace_id=proj.workspace_id, project_id=proj.id, title="leaf", parent_id=mid.id
            ),
        )
        ids = get_subtree_group_ids(conn, root.id)
        assert set(ids) == {root.id, mid.id, leaf.id}

    def test_subtree_includes_archived(self, conn: sqlite3.Connection) -> None:
        # Archived descendants must be included so cycle detection sees the full graph.
        # A cycle through an archived intermediate node is still a cycle.
        _, proj = self._setup(conn)
        root = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="root")
        )
        child = insert_group(
            conn,
            NewGroup(
                workspace_id=proj.workspace_id, project_id=proj.id, title="child", parent_id=root.id
            ),
        )
        update_group(conn, child.id, {"archived": True})
        ids = get_subtree_group_ids(conn, root.id)
        assert set(ids) == {root.id, child.id}

    def test_get_group_ancestry(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        root = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="root")
        )
        mid = insert_group(
            conn,
            NewGroup(
                workspace_id=proj.workspace_id, project_id=proj.id, title="mid", parent_id=root.id
            ),
        )
        leaf = insert_group(
            conn,
            NewGroup(
                workspace_id=proj.workspace_id, project_id=proj.id, title="leaf", parent_id=mid.id
            ),
        )
        ancestry = get_group_ancestry(conn, leaf.id)
        assert [g.id for g in ancestry] == [root.id, mid.id, leaf.id]

    def test_get_group_ancestry_root(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        root = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="root")
        )
        ancestry = get_group_ancestry(conn, root.id)
        assert len(ancestry) == 1
        assert ancestry[0].id == root.id

    def test_get_group_ancestry_missing(self, conn: sqlite3.Connection) -> None:
        ancestry = get_group_ancestry(conn, 9999)
        assert ancestry == ()

    def test_reparent_children(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        g1 = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g1")
        )
        g2 = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g2")
        )
        child = insert_group(
            conn,
            NewGroup(
                workspace_id=proj.workspace_id, project_id=proj.id, title="child", parent_id=g1.id
            ),
        )
        reparent_children(conn, g1.id, g2.id)
        updated = get_group(conn, child.id)
        assert updated is not None
        assert updated.parent_id == g2.id

    def test_reparent_to_none(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        parent = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="parent")
        )
        child = insert_group(
            conn,
            NewGroup(
                workspace_id=proj.workspace_id,
                project_id=proj.id,
                title="child",
                parent_id=parent.id,
            ),
        )
        reparent_children(conn, parent.id, None)
        updated = get_group(conn, child.id)
        assert updated is not None
        assert updated.parent_id is None


class TestBatchGroupQueries:
    def _setup(self, conn: sqlite3.Connection) -> tuple[Workspace, Status, Project]:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="p"))
        return workspace, col, proj

    # -- list_tasks_by_ids --

    def test_list_tasks_by_ids_returns_tasks(self, conn: sqlite3.Connection) -> None:
        workspace, col, _ = self._setup(conn)
        t1 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t1", status_id=col.id))
        t2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t2", status_id=col.id))
        tasks = list_tasks_by_ids(conn, (t1.id, t2.id))
        assert len(tasks) == 2
        assert {t.id for t in tasks} == {t1.id, t2.id}
        assert all(isinstance(t, Task) for t in tasks)

    def test_list_tasks_by_ids_empty(self, conn: sqlite3.Connection) -> None:
        assert list_tasks_by_ids(conn, ()) == ()

    def test_list_tasks_by_ids_missing_ids_ignored(self, conn: sqlite3.Connection) -> None:
        workspace, col, _ = self._setup(conn)
        t1 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t1", status_id=col.id))
        tasks = list_tasks_by_ids(conn, (t1.id, 9999))
        assert len(tasks) == 1
        assert tasks[0].id == t1.id

    # -- batch_task_ids_by_group --

    def test_batch_task_ids_by_group(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj = self._setup(conn)
        g1 = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g1")
        )
        g2 = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g2")
        )
        t1 = insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="t1", status_id=col.id, project_id=proj.id),
        )
        t2 = insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="t2", status_id=col.id, project_id=proj.id),
        )
        set_task_group_id(conn, t1.id, g1.id)
        set_task_group_id(conn, t2.id, g1.id)
        result = batch_task_ids_by_group(conn, (g1.id, g2.id))
        assert set(result[g1.id]) == {t1.id, t2.id}
        assert result[g2.id] == ()

    def test_batch_task_ids_by_group_empty(self, conn: sqlite3.Connection) -> None:
        assert batch_task_ids_by_group(conn, ()) == {}

    # -- batch_child_ids_by_group --

    def test_batch_child_ids_by_group(self, conn: sqlite3.Connection) -> None:
        _, _, proj = self._setup(conn)
        parent = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="parent")
        )
        c1 = insert_group(
            conn,
            NewGroup(
                workspace_id=proj.workspace_id, project_id=proj.id, title="c1", parent_id=parent.id
            ),
        )
        c2 = insert_group(
            conn,
            NewGroup(
                workspace_id=proj.workspace_id, project_id=proj.id, title="c2", parent_id=parent.id
            ),
        )
        result = batch_child_ids_by_group(conn, (parent.id,))
        assert set(result[parent.id]) == {c1.id, c2.id}

    def test_batch_child_ids_excludes_archived(self, conn: sqlite3.Connection) -> None:
        _, _, proj = self._setup(conn)
        parent = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="parent")
        )
        c1 = insert_group(
            conn,
            NewGroup(
                workspace_id=proj.workspace_id, project_id=proj.id, title="c1", parent_id=parent.id
            ),
        )
        c2 = insert_group(
            conn,
            NewGroup(
                workspace_id=proj.workspace_id, project_id=proj.id, title="c2", parent_id=parent.id
            ),
        )
        update_group(conn, c2.id, {"archived": True})
        result = batch_child_ids_by_group(conn, (parent.id,))
        assert result[parent.id] == (c1.id,)
        result_all = batch_child_ids_by_group(
            conn,
            (parent.id,),
            include_archived=True,
        )
        assert set(result_all[parent.id]) == {c1.id, c2.id}

    def test_batch_child_ids_by_group_empty(self, conn: sqlite3.Connection) -> None:
        assert batch_child_ids_by_group(conn, ()) == {}

    # -- list_groups_by_workspace --

    def test_list_groups_by_workspace(self, conn: sqlite3.Connection) -> None:
        workspace, _, proj = self._setup(conn)
        g1 = insert_group(
            conn,
            NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g1", position=1),
        )
        g2 = insert_group(
            conn,
            NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g2", position=0),
        )
        result = list_groups_by_workspace(conn, workspace.id)
        assert len(result) == 2
        assert result[0].id == g2.id  # position 0 first
        assert result[1].id == g1.id

    def test_list_groups_by_workspace_excludes_archived(self, conn: sqlite3.Connection) -> None:
        workspace, _, proj = self._setup(conn)
        insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g1"))
        g2 = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g2")
        )
        update_group(conn, g2.id, {"archived": True})
        assert len(list_groups_by_workspace(conn, workspace.id)) == 1
        assert len(list_groups_by_workspace(conn, workspace.id, include_archived=True)) == 2

    def test_list_groups_by_workspace_multi_project(self, conn: sqlite3.Connection) -> None:
        workspace, _, proj1 = self._setup(conn)
        proj2 = insert_project(conn, NewProject(workspace_id=workspace.id, name="p2"))
        insert_group(
            conn, NewGroup(workspace_id=proj1.workspace_id, project_id=proj1.id, title="g1")
        )
        insert_group(
            conn, NewGroup(workspace_id=proj2.workspace_id, project_id=proj2.id, title="g2")
        )
        result = list_groups_by_workspace(conn, workspace.id)
        assert len(result) == 2

    def test_list_groups_by_workspace_empty(self, conn: sqlite3.Connection) -> None:
        workspace, _, _ = self._setup(conn)
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
    """Repository-layer metadata set/remove for workspaces, projects, and groups.

    Exercises the generic _set_metadata_key / _remove_metadata_key helpers via
    each public per-entity wrapper. Service-layer case normalization and
    validation is covered in test_service.py.
    """

    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int, int]:
        w = insert_workspace(conn, NewWorkspace(name="w"))
        p = insert_project(conn, NewProject(workspace_id=w.id, name="p"))
        g = insert_group(conn, NewGroup(workspace_id=w.id, project_id=p.id, title="g"))
        return w.id, p.id, g.id

    def test_workspace_set_remove(self, conn: sqlite3.Connection) -> None:
        wid, _, _ = self._setup(conn)
        set_workspace_metadata_key(conn, wid, "env", "prod")
        import json as _json

        row = conn.execute("SELECT metadata FROM workspaces WHERE id = ?", (wid,)).fetchone()
        assert _json.loads(row["metadata"]) == {"env": "prod"}
        remove_workspace_metadata_key(conn, wid, "env")
        row = conn.execute("SELECT metadata FROM workspaces WHERE id = ?", (wid,)).fetchone()
        assert _json.loads(row["metadata"]) == {}

    def test_project_set_remove(self, conn: sqlite3.Connection) -> None:
        _, pid, _ = self._setup(conn)
        set_project_metadata_key(conn, pid, "owner", "alice")
        import json as _json

        row = conn.execute("SELECT metadata FROM projects WHERE id = ?", (pid,)).fetchone()
        assert _json.loads(row["metadata"]) == {"owner": "alice"}
        remove_project_metadata_key(conn, pid, "owner")
        row = conn.execute("SELECT metadata FROM projects WHERE id = ?", (pid,)).fetchone()
        assert _json.loads(row["metadata"]) == {}

    def test_group_set_remove(self, conn: sqlite3.Connection) -> None:
        _, _, gid = self._setup(conn)
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

    def test_project_nonexistent_raises(self, conn: sqlite3.Connection) -> None:
        self._setup(conn)
        with pytest.raises(LookupError, match="project 999 not found"):
            set_project_metadata_key(conn, 999, "k", "v")

    def test_group_nonexistent_raises(self, conn: sqlite3.Connection) -> None:
        self._setup(conn)
        with pytest.raises(LookupError, match="group 999 not found"):
            set_group_metadata_key(conn, 999, "k", "v")
