from __future__ import annotations

import sqlite3

import pytest

from sticky_notes.models import (
    Workspace,
    Group,
    NewWorkspace,
    NewGroup,
    NewProject,
    NewStatus,
    NewTag,
    NewTask,
    NewTaskHistory,
    Project,
    Status,
    Tag,
    Task,
    TaskField,
    TaskFilter,
    TaskHistory,
)
from sticky_notes.repository import (
    add_dependency,
    add_group_dependency,
    add_tag_to_task,
    batch_child_ids_by_group,
    batch_dependency_ids,
    batch_tag_ids_by_task,
    batch_task_ids_by_group,
    get_workspace,
    get_workspace_by_name,
    get_status,
    get_status_by_name,
    get_group,
    get_group_by_title,
    get_project,
    get_project_by_name,
    get_group_ancestry,
    get_reachable_group_dep_ids,
    get_reachable_task_ids,
    get_subtree_group_ids,
    get_tag,
    get_tag_by_name,
    get_task,
    get_task_by_title,
    insert_workspace,
    insert_status,
    insert_group,
    insert_project,
    insert_tag,
    insert_task,
    insert_task_history,
    list_all_dependencies,
    list_all_group_dependencies,
    list_blocked_by_ids,
    list_blocked_by_tasks,
    list_blocks_ids,
    list_blocks_tasks,
    list_workspaces,
    list_child_groups,
    list_statuses,
    list_groups,
    list_groups_by_workspace,
    list_projects,
    list_tag_ids_by_task,
    list_tags,
    list_tags_by_task,
    list_task_history,
    list_task_ids_by_group,
    list_task_ids_by_project,
    list_task_ids_by_tag,
    list_tasks,
    list_tasks_by_status,
    list_tasks_by_ids,
    list_tasks_by_project,
    list_tasks_filtered,
    list_ungrouped_task_ids,
    list_group_blocked_by_ids,
    archive_dependency,
    archive_group_dependency,
    remove_tag_from_task,
    reparent_children,
    set_task_group_id,
    unassign_tasks_from_group,
    update_workspace,
    update_status,
    update_group,
    update_project,
    update_tag,
    update_task,
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
            from sticky_notes import repository
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
        task = insert_task(
            conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id)
        )
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
        col2 = insert_status(
            conn, NewStatus(workspace_id=workspace.id, name="done")
        )
        insert_task(conn, NewTask(workspace_id=workspace.id, title="a", status_id=col1.id))
        insert_task(conn, NewTask(workspace_id=workspace.id, title="b", status_id=col2.id))
        assert len(list_tasks_by_status(conn, col1.id)) == 1
        assert len(list_tasks_by_status(conn, col2.id)) == 1

    def test_list_tasks_by_project(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="p"))
        insert_task(
            conn,
            NewTask(
                workspace_id=workspace.id, title="a", status_id=col.id, project_id=proj.id
            ),
        )
        insert_task(conn, NewTask(workspace_id=workspace.id, title="b", status_id=col.id))
        assert len(list_tasks_by_project(conn, proj.id)) == 1

    def test_update_task(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        task = insert_task(
            conn, NewTask(workspace_id=workspace.id, title="old", status_id=col.id)
        )
        updated = update_task(conn, task.id, {"title": "new", "priority": 3})
        assert updated.title == "new"
        assert updated.priority == 3

    def test_update_task_bad_field(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        task = insert_task(
            conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id)
        )
        with pytest.raises(ValueError, match="disallowed"):
            update_task(conn, task.id, {"id": 99})

    def test_update_task_missing_id(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            update_task(conn, 9999, {"title": "y"})

    def test_list_tasks_by_status_excludes_archived(
        self, conn: sqlite3.Connection
    ) -> None:
        workspace, col = self._setup(conn)
        insert_task(conn, NewTask(workspace_id=workspace.id, title="a", status_id=col.id))
        t2 = insert_task(
            conn, NewTask(workspace_id=workspace.id, title="b", status_id=col.id)
        )
        update_task(conn, t2.id, {"archived": True})
        assert len(list_tasks_by_status(conn, col.id)) == 1
        assert len(list_tasks_by_status(conn, col.id, include_archived=True)) == 2

    def test_list_tasks_by_project_excludes_archived(
        self, conn: sqlite3.Connection
    ) -> None:
        workspace, col = self._setup(conn)
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="p"))
        insert_task(
            conn,
            NewTask(
                workspace_id=workspace.id, title="a", status_id=col.id, project_id=proj.id
            ),
        )
        t2 = insert_task(
            conn,
            NewTask(
                workspace_id=workspace.id, title="b", status_id=col.id, project_id=proj.id
            ),
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
            insert_task(conn, NewTask(workspace_id=workspace.id, title="fix login", status_id=col.id))

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

    def test_priority_below_lower_bound_rejected(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        with pytest.raises(sqlite3.IntegrityError):
            insert_task(
                conn, NewTask(workspace_id=workspace.id, title="bad", status_id=col.id, priority=0)
            )

    def test_priority_above_upper_bound_rejected(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        with pytest.raises(sqlite3.IntegrityError):
            insert_task(
                conn, NewTask(workspace_id=workspace.id, title="bad", status_id=col.id, priority=6)
            )

    def test_empty_title_allowed(self, conn: sqlite3.Connection) -> None:
        workspace, col = self._setup(conn)
        task = insert_task(
            conn, NewTask(workspace_id=workspace.id, title="", status_id=col.id)
        )
        assert task.title == ""

    def test_insert_task_with_all_optional_fields(
        self, conn: sqlite3.Connection
    ) -> None:
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


# ---- Task dependencies ----


class TestTaskDependencyRepository:
    def _setup(self, conn: sqlite3.Connection) -> tuple[Task, Task, Task]:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        t1 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t1", status_id=col.id))
        t2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t2", status_id=col.id))
        t3 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t3", status_id=col.id))
        return t1, t2, t3

    def test_add_and_list_blocked_by_ids(self, conn: sqlite3.Connection) -> None:
        t1, t2, t3 = self._setup(conn)
        add_dependency(conn, t1.id, t2.id)
        add_dependency(conn, t1.id, t3.id)
        ids = list_blocked_by_ids(conn, t1.id)
        assert set(ids) == {t2.id, t3.id}

    def test_list_blocks_ids(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_dependency(conn, t1.id, t2.id)
        assert list_blocks_ids(conn, t2.id) == (t1.id,)

    def test_archive_dependency(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_dependency(conn, t1.id, t2.id)
        archive_dependency(conn, t1.id, t2.id)
        assert list_blocked_by_ids(conn, t1.id) == ()
        # Row still exists in DB with archived=1
        row = conn.execute(
            "SELECT archived FROM task_dependencies WHERE task_id = ? AND depends_on_id = ?",
            (t1.id, t2.id),
        ).fetchone()
        assert row is not None
        assert row["archived"] == 1

    def test_archive_nonexistent_is_silent(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        archive_dependency(conn, t1.id, t2.id)  # no-op, no error

    def test_list_blocked_by_tasks(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_dependency(conn, t1.id, t2.id)
        tasks = list_blocked_by_tasks(conn, t1.id)
        assert len(tasks) == 1
        assert tasks[0].id == t2.id
        assert isinstance(tasks[0], Task)

    def test_list_blocks_tasks(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_dependency(conn, t1.id, t2.id)
        tasks = list_blocks_tasks(conn, t2.id)
        assert len(tasks) == 1
        assert tasks[0].id == t1.id

    def test_duplicate_dependency_is_idempotent(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_dependency(conn, t1.id, t2.id)
        add_dependency(conn, t1.id, t2.id)  # upsert — no error
        assert list_blocked_by_ids(conn, t1.id) == (t2.id,)

    def test_self_dependency_raises(self, conn: sqlite3.Connection) -> None:
        t1, _, _ = self._setup(conn)
        with pytest.raises(sqlite3.IntegrityError):
            add_dependency(conn, t1.id, t1.id)

    def test_list_all_dependencies(self, conn: sqlite3.Connection) -> None:
        t1, t2, t3 = self._setup(conn)
        add_dependency(conn, t2.id, t1.id)
        add_dependency(conn, t3.id, t1.id)
        deps = list_all_dependencies(conn)
        assert set(deps) == {(t2.id, t1.id), (t3.id, t1.id)}

    def test_list_all_dependencies_empty(self, conn: sqlite3.Connection) -> None:
        self._setup(conn)
        assert list_all_dependencies(conn) == ()

    def test_list_all_excludes_archived(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_dependency(conn, t2.id, t1.id)
        archive_dependency(conn, t2.id, t1.id)
        assert list_all_dependencies(conn) == ()

    def test_readd_after_archive(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_dependency(conn, t2.id, t1.id)
        archive_dependency(conn, t2.id, t1.id)
        add_dependency(conn, t2.id, t1.id)  # re-create — should not crash
        assert list_blocked_by_ids(conn, t2.id) == (t1.id,)

    def test_batch_dependency_ids(self, conn: sqlite3.Connection) -> None:
        t1, t2, t3 = self._setup(conn)
        add_dependency(conn, t2.id, t1.id)
        add_dependency(conn, t3.id, t1.id)
        blocked_by, blocks = batch_dependency_ids(conn, (t1.id, t2.id, t3.id))
        assert blocked_by[t1.id] == ()
        assert blocked_by[t2.id] == (t1.id,)
        assert blocked_by[t3.id] == (t1.id,)
        assert set(blocks[t1.id]) == {t2.id, t3.id}
        assert blocks[t2.id] == ()
        assert blocks[t3.id] == ()

    def test_batch_dependency_ids_empty(self, conn: sqlite3.Connection) -> None:
        blocked_by, blocks = batch_dependency_ids(conn, ())
        assert blocked_by == {}
        assert blocks == {}

    def test_get_reachable_task_ids_linear(self, conn: sqlite3.Connection) -> None:
        t1, t2, t3 = self._setup(conn)
        add_dependency(conn, t1.id, t2.id)  # t1 -> t2
        add_dependency(conn, t2.id, t3.id)  # t2 -> t3
        assert set(get_reachable_task_ids(conn, t1.id)) == {t2.id, t3.id}
        assert get_reachable_task_ids(conn, t2.id) == (t3.id,)
        assert get_reachable_task_ids(conn, t3.id) == ()

    def test_get_reachable_task_ids_diamond(self, conn: sqlite3.Connection) -> None:
        t1, t2, t3 = self._setup(conn)
        bid = t1.workspace_id
        cid = t1.status_id
        t4 = insert_task(conn, NewTask(workspace_id=bid, title="d4", status_id=cid))
        add_dependency(conn, t1.id, t2.id)  # t1 -> t2
        add_dependency(conn, t1.id, t3.id)  # t1 -> t3
        add_dependency(conn, t2.id, t4.id)  # t2 -> t4
        add_dependency(conn, t3.id, t4.id)  # t3 -> t4
        assert set(get_reachable_task_ids(conn, t1.id)) == {t2.id, t3.id, t4.id}

    def test_get_reachable_task_ids_no_deps(self, conn: sqlite3.Connection) -> None:
        t1, _, _ = self._setup(conn)
        assert get_reachable_task_ids(conn, t1.id) == ()


# ---- Group dependencies ----


class TestGroupDependencyRepository:
    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int, int]:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="p"))
        g1 = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g1")).id
        g2 = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g2")).id
        g3 = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g3")).id
        return g1, g2, g3

    def test_add_and_list_blocked_by_ids(self, conn: sqlite3.Connection) -> None:
        g1, g2, g3 = self._setup(conn)
        add_group_dependency(conn, g1, g2)
        add_group_dependency(conn, g1, g3)
        ids = list_group_blocked_by_ids(conn, g1)
        assert set(ids) == {g2, g3}

    def test_archive_group_dependency(self, conn: sqlite3.Connection) -> None:
        g1, g2, _ = self._setup(conn)
        add_group_dependency(conn, g1, g2)
        archive_group_dependency(conn, g1, g2)
        assert list_group_blocked_by_ids(conn, g1) == ()
        # Row still exists in DB with archived=1
        row = conn.execute(
            "SELECT archived FROM group_dependencies WHERE group_id = ? AND depends_on_id = ?",
            (g1, g2),
        ).fetchone()
        assert row is not None
        assert row["archived"] == 1

    def test_archive_nonexistent_is_silent(self, conn: sqlite3.Connection) -> None:
        g1, g2, _ = self._setup(conn)
        archive_group_dependency(conn, g1, g2)  # no-op, no error

    def test_duplicate_is_idempotent(self, conn: sqlite3.Connection) -> None:
        g1, g2, _ = self._setup(conn)
        add_group_dependency(conn, g1, g2)
        add_group_dependency(conn, g1, g2)  # upsert — no error
        assert list_group_blocked_by_ids(conn, g1) == (g2,)

    def test_self_dependency_raises(self, conn: sqlite3.Connection) -> None:
        g1, _, _ = self._setup(conn)
        with pytest.raises(sqlite3.IntegrityError):
            add_group_dependency(conn, g1, g1)

    def test_list_all_group_dependencies(self, conn: sqlite3.Connection) -> None:
        g1, g2, g3 = self._setup(conn)
        add_group_dependency(conn, g2, g1)
        add_group_dependency(conn, g3, g1)
        deps = list_all_group_dependencies(conn)
        assert set(deps) == {(g2, g1), (g3, g1)}

    def test_list_all_group_dependencies_empty(self, conn: sqlite3.Connection) -> None:
        self._setup(conn)
        assert list_all_group_dependencies(conn) == ()

    def test_list_all_group_deps_excludes_archived(self, conn: sqlite3.Connection) -> None:
        g1, g2, _ = self._setup(conn)
        add_group_dependency(conn, g1, g2)
        archive_group_dependency(conn, g1, g2)
        assert list_all_group_dependencies(conn) == ()

    def test_readd_group_dep_after_archive(self, conn: sqlite3.Connection) -> None:
        g1, g2, _ = self._setup(conn)
        add_group_dependency(conn, g1, g2)
        archive_group_dependency(conn, g1, g2)
        add_group_dependency(conn, g1, g2)  # re-create — should not crash
        assert list_group_blocked_by_ids(conn, g1) == (g2,)

    def test_get_reachable_group_dep_ids_linear(self, conn: sqlite3.Connection) -> None:
        g1, g2, g3 = self._setup(conn)
        add_group_dependency(conn, g1, g2)  # g1 -> g2
        add_group_dependency(conn, g2, g3)  # g2 -> g3
        assert set(get_reachable_group_dep_ids(conn, g1)) == {g2, g3}
        assert get_reachable_group_dep_ids(conn, g2) == (g3,)
        assert get_reachable_group_dep_ids(conn, g3) == ()

    def test_get_reachable_group_dep_ids_no_deps(self, conn: sqlite3.Connection) -> None:
        g1, _, _ = self._setup(conn)
        assert get_reachable_group_dep_ids(conn, g1) == ()


# ---- Task history ----


class TestTaskHistoryRepository:
    def test_insert_returns_task_history(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        task = insert_task(
            conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id)
        )
        h = insert_task_history(
            conn,
            NewTaskHistory(
                task_id=task.id,
                workspace_id=task.workspace_id,
                field=TaskField.TITLE,
                old_value="t",
                new_value="new",
                source="tui",
            ),
        )
        assert isinstance(h, TaskHistory)
        assert h.field == TaskField.TITLE
        assert h.old_value == "t"
        assert h.new_value == "new"

    def test_list_task_history_ordered_desc(self, conn: sqlite3.Connection) -> None:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        task = insert_task(
            conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id)
        )
        h1 = insert_task_history(
            conn,
            NewTaskHistory(
                task_id=task.id,
                workspace_id=task.workspace_id,
                field=TaskField.TITLE,
                new_value="v1",
                source="tui",
            ),
        )
        h2 = insert_task_history(
            conn,
            NewTaskHistory(
                task_id=task.id,
                workspace_id=task.workspace_id,
                field=TaskField.TITLE,
                new_value="v2",
                source="tui",
            ),
        )
        history = list_task_history(conn, task.id)
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
            NewTask(
                workspace_id=workspace.id, title="a", status_id=col.id, project_id=proj.id
            ),
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
        t1 = insert_task(conn, NewTask(workspace_id=workspace.id, title="Fix login bug", status_id=col1.id, project_id=proj.id, priority=3))
        t2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="Add search", status_id=col1.id, priority=1))
        t3 = insert_task(conn, NewTask(workspace_id=workspace.id, title="Deploy release", status_id=col2.id, project_id=proj.id, priority=2))
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
            conn, workspace.id,
            task_filter=TaskFilter(status_id=col1.id, project_id=proj.id),
        )
        assert len(result) == 1
        assert result[0].title == "Fix login bug"

    def test_include_archived(self, conn: sqlite3.Connection) -> None:
        workspace, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        update_task(conn, t1.id, {"archived": True})
        result = list_tasks_filtered(conn, workspace.id)
        assert len(result) == 2
        result_all = list_tasks_filtered(conn, workspace.id, task_filter=TaskFilter(include_archived=True))
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
        grp = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="frontend"))
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
        grp = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="Frontend"))
        assert isinstance(grp, Group)
        assert grp.title == "Frontend"
        assert grp.archived is False
        assert grp.parent_id is None
        assert grp.id >= 1

    def test_get_group(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        grp = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g"))
        assert get_group(conn, grp.id) == grp

    def test_get_group_missing(self, conn: sqlite3.Connection) -> None:
        assert get_group(conn, 9999) is None

    def test_get_group_by_title(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        grp = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="Backend"))
        assert get_group_by_title(conn, proj.id, "Backend") == grp
        assert get_group_by_title(conn, proj.id, "nope") is None

    def test_get_group_by_title_case_insensitive(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        grp = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="Backend"))
        assert get_group_by_title(conn, proj.id, "backend") == grp
        assert get_group_by_title(conn, proj.id, "BACKEND") == grp

    def test_unique_title_case_insensitive(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="Backend"))
        with pytest.raises(sqlite3.IntegrityError):
            insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="backend"))

    def test_list_groups_excludes_archived(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g1"))
        g2 = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g2"))
        update_group(conn, g2.id, {"archived": True})
        assert len(list_groups(conn, proj.id)) == 1
        assert len(list_groups(conn, proj.id, include_archived=True)) == 2

    def test_list_groups_ordered_by_position(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        g1 = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="second", position=1))
        g2 = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="first", position=0))
        groups = list_groups(conn, proj.id)
        assert groups[0].id == g2.id
        assert groups[1].id == g1.id

    def test_update_group(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        grp = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="old"))
        updated = update_group(conn, grp.id, {"title": "new"})
        assert updated.title == "new"

    def test_update_group_bad_field(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        grp = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g"))
        with pytest.raises(ValueError, match="disallowed"):
            update_group(conn, grp.id, {"id": 99})

    def test_update_group_missing_id(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            update_group(conn, 9999, {"title": "x"})

    def test_unique_title_per_project(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="dup"))
        with pytest.raises(sqlite3.IntegrityError):
            insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="dup"))

    def test_same_title_different_projects(self, conn: sqlite3.Connection) -> None:
        workspace, proj1 = self._setup(conn)
        proj2 = insert_project(conn, NewProject(workspace_id=workspace.id, name="p2"))
        g1 = insert_group(conn, NewGroup(workspace_id=proj1.workspace_id, project_id=proj1.id, title="shared"))
        g2 = insert_group(conn, NewGroup(workspace_id=proj2.workspace_id, project_id=proj2.id, title="shared"))
        assert g1.id != g2.id

    def test_insert_with_parent(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        parent = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="parent"))
        child = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="child", parent_id=parent.id)
        )
        assert child.parent_id == parent.id

    def test_insert_with_invalid_parent_fk(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        with pytest.raises(sqlite3.IntegrityError):
            insert_group(
                conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="bad", parent_id=9999)
            )


class TestTaskGroupRepository:
    def _setup(
        self, conn: sqlite3.Connection
    ) -> tuple[Workspace, Status, Project, Group]:
        workspace = insert_workspace(conn, NewWorkspace(name="b"))
        col = insert_status(conn, NewStatus(workspace_id=workspace.id, name="todo"))
        proj = insert_project(conn, NewProject(workspace_id=workspace.id, name="p"))
        grp = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g"))
        return workspace, col, proj, grp

    def test_assign_and_get(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp = self._setup(conn)
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id, project_id=proj.id))
        set_task_group_id(conn, task.id, grp.id)
        assert get_task(conn, task.id).group_id == grp.id

    def test_get_unassigned_returns_none(self, conn: sqlite3.Connection) -> None:
        workspace, col, _, _ = self._setup(conn)
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id))
        assert get_task(conn, task.id).group_id is None

    def test_update_replaces_group(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp1 = self._setup(conn)
        grp2 = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g2"))
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id, project_id=proj.id))
        set_task_group_id(conn, task.id, grp1.id)
        set_task_group_id(conn, task.id, grp2.id)
        assert get_task(conn, task.id).group_id == grp2.id

    def test_unassign(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp = self._setup(conn)
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id, project_id=proj.id))
        set_task_group_id(conn, task.id, grp.id)
        set_task_group_id(conn, task.id, None)
        assert get_task(conn, task.id).group_id is None

    def test_list_task_ids_by_group(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp = self._setup(conn)
        t1 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t1", status_id=col.id, project_id=proj.id))
        t2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t2", status_id=col.id, project_id=proj.id))
        set_task_group_id(conn, t1.id, grp.id)
        set_task_group_id(conn, t2.id, grp.id)
        ids = list_task_ids_by_group(conn, grp.id)
        assert set(ids) == {t1.id, t2.id}

    def test_list_ungrouped_task_ids(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp = self._setup(conn)
        t1 = insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="grouped", status_id=col.id, project_id=proj.id),
        )
        t2 = insert_task(
            conn,
            NewTask(workspace_id=workspace.id, title="ungrouped", status_id=col.id, project_id=proj.id),
        )
        set_task_group_id(conn, t1.id, grp.id)
        ids = list_ungrouped_task_ids(conn, proj.id)
        assert ids == (t2.id,)

    def test_group_mismatched_project_raises(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp = self._setup(conn)
        proj2 = insert_project(conn, NewProject(workspace_id=workspace.id, name="p2"))
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id, project_id=proj2.id))
        with pytest.raises(sqlite3.IntegrityError):
            set_task_group_id(conn, task.id, grp.id)

    def test_group_matching_project_succeeds(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp = self._setup(conn)
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id, project_id=proj.id))
        set_task_group_id(conn, task.id, grp.id)
        assert get_task(conn, task.id).group_id == grp.id

    def test_change_project_while_grouped_raises(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp = self._setup(conn)
        proj2 = insert_project(conn, NewProject(workspace_id=workspace.id, name="p2"))
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id, project_id=proj.id))
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
        task = insert_task(conn, NewTask(workspace_id=workspace.id, title="t", status_id=col.id, project_id=proj.id))
        set_task_group_id(conn, task.id, grp.id)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM groups WHERE id = ?", (grp.id,))

    def test_bulk_unassign_by_group(self, conn: sqlite3.Connection) -> None:
        workspace, col, proj, grp = self._setup(conn)
        t1 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t1", status_id=col.id, project_id=proj.id))
        t2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t2", status_id=col.id, project_id=proj.id))
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
        parent = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="parent"))
        c1 = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="c1", parent_id=parent.id)
        )
        c2 = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="c2", parent_id=parent.id)
        )
        children = list_child_groups(conn, parent.id)
        assert {g.id for g in children} == {c1.id, c2.id}

    def test_list_child_groups_excludes_archived(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        parent = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="parent"))
        insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="c1", parent_id=parent.id)
        )
        c2 = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="c2", parent_id=parent.id)
        )
        update_group(conn, c2.id, {"archived": True})
        assert len(list_child_groups(conn, parent.id)) == 1
        assert len(list_child_groups(conn, parent.id, include_archived=True)) == 2

    def test_get_subtree_group_ids(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        root = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="root"))
        mid = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="mid", parent_id=root.id)
        )
        leaf = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="leaf", parent_id=mid.id)
        )
        ids = get_subtree_group_ids(conn, root.id)
        assert set(ids) == {root.id, mid.id, leaf.id}

    def test_subtree_includes_archived(self, conn: sqlite3.Connection) -> None:
        # Archived descendants must be included so cycle detection sees the full graph.
        # A cycle through an archived intermediate node is still a cycle.
        _, proj = self._setup(conn)
        root = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="root"))
        child = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="child", parent_id=root.id)
        )
        update_group(conn, child.id, {"archived": True})
        ids = get_subtree_group_ids(conn, root.id)
        assert set(ids) == {root.id, child.id}

    def test_get_group_ancestry(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        root = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="root"))
        mid = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="mid", parent_id=root.id))
        leaf = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="leaf", parent_id=mid.id))
        ancestry = get_group_ancestry(conn, leaf.id)
        assert [g.id for g in ancestry] == [root.id, mid.id, leaf.id]

    def test_get_group_ancestry_root(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        root = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="root"))
        ancestry = get_group_ancestry(conn, root.id)
        assert len(ancestry) == 1
        assert ancestry[0].id == root.id

    def test_get_group_ancestry_missing(self, conn: sqlite3.Connection) -> None:
        ancestry = get_group_ancestry(conn, 9999)
        assert ancestry == ()

    def test_reparent_children(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        g1 = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g1"))
        g2 = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g2"))
        child = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="child", parent_id=g1.id)
        )
        reparent_children(conn, g1.id, g2.id)
        updated = get_group(conn, child.id)
        assert updated is not None
        assert updated.parent_id == g2.id

    def test_reparent_to_none(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        parent = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="parent"))
        child = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="child", parent_id=parent.id)
        )
        reparent_children(conn, parent.id, None)
        updated = get_group(conn, child.id)
        assert updated is not None
        assert updated.parent_id is None


class TestBatchGroupQueries:
    def _setup(
        self, conn: sqlite3.Connection
    ) -> tuple[Workspace, Status, Project]:
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
        g1 = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g1"))
        g2 = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g2"))
        t1 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t1", status_id=col.id, project_id=proj.id))
        t2 = insert_task(conn, NewTask(workspace_id=workspace.id, title="t2", status_id=col.id, project_id=proj.id))
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
        parent = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="parent"))
        c1 = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="c1", parent_id=parent.id)
        )
        c2 = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="c2", parent_id=parent.id)
        )
        result = batch_child_ids_by_group(conn, (parent.id,))
        assert set(result[parent.id]) == {c1.id, c2.id}

    def test_batch_child_ids_excludes_archived(self, conn: sqlite3.Connection) -> None:
        _, _, proj = self._setup(conn)
        parent = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="parent"))
        c1 = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="c1", parent_id=parent.id)
        )
        c2 = insert_group(
            conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="c2", parent_id=parent.id)
        )
        update_group(conn, c2.id, {"archived": True})
        result = batch_child_ids_by_group(conn, (parent.id,))
        assert result[parent.id] == (c1.id,)
        result_all = batch_child_ids_by_group(
            conn, (parent.id,), include_archived=True,
        )
        assert set(result_all[parent.id]) == {c1.id, c2.id}

    def test_batch_child_ids_by_group_empty(self, conn: sqlite3.Connection) -> None:
        assert batch_child_ids_by_group(conn, ()) == {}

    # -- list_groups_by_workspace --

    def test_list_groups_by_workspace(self, conn: sqlite3.Connection) -> None:
        workspace, _, proj = self._setup(conn)
        g1 = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g1", position=1))
        g2 = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g2", position=0))
        result = list_groups_by_workspace(conn, workspace.id)
        assert len(result) == 2
        assert result[0].id == g2.id  # position 0 first
        assert result[1].id == g1.id

    def test_list_groups_by_workspace_excludes_archived(self, conn: sqlite3.Connection) -> None:
        workspace, _, proj = self._setup(conn)
        insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g1"))
        g2 = insert_group(conn, NewGroup(workspace_id=proj.workspace_id, project_id=proj.id, title="g2"))
        update_group(conn, g2.id, {"archived": True})
        assert len(list_groups_by_workspace(conn, workspace.id)) == 1
        assert len(list_groups_by_workspace(conn, workspace.id, include_archived=True)) == 2

    def test_list_groups_by_workspace_multi_project(self, conn: sqlite3.Connection) -> None:
        workspace, _, proj1 = self._setup(conn)
        proj2 = insert_project(conn, NewProject(workspace_id=workspace.id, name="p2"))
        insert_group(conn, NewGroup(workspace_id=proj1.workspace_id, project_id=proj1.id, title="g1"))
        insert_group(conn, NewGroup(workspace_id=proj2.workspace_id, project_id=proj2.id, title="g2"))
        result = list_groups_by_workspace(conn, workspace.id)
        assert len(result) == 2

    def test_list_groups_by_workspace_empty(self, conn: sqlite3.Connection) -> None:
        workspace, _, _ = self._setup(conn)
        assert list_groups_by_workspace(conn, workspace.id) == ()
