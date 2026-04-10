from __future__ import annotations

import sqlite3

import pytest

from sticky_notes.models import Workspace, Status, Group, Project, Tag, Task, TaskFilter, TaskHistory
from sticky_notes.service_models import (
    WorkspaceContext,
    WorkspaceListView,
    GroupDetail,
    GroupRef,
    ProjectDetail,
    TaskDetail,
    TaskListItem,
)
from tests.helpers import (
    insert_workspace as _raw_insert_workspace,
    insert_status as _raw_insert_status,
    insert_group as _raw_insert_group,
    insert_project as _raw_insert_project,
    insert_task as _raw_insert_task,
    insert_tag as _raw_insert_tag,
    insert_task_dependency as _raw_insert_task_dependency,
    insert_task_tag as _raw_insert_task_tag,
)

from sticky_notes import service


# Raw helpers leave an implicit transaction open.  Wrap them so each
# call commits immediately, keeping the connection free for service-layer
# transaction() blocks.


def _commit(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        conn.commit()


def insert_workspace(conn: sqlite3.Connection, name: str = "workspace1") -> int:
    rid = _raw_insert_workspace(conn, name)
    _commit(conn)
    return rid


def insert_status(
    conn: sqlite3.Connection, workspace_id: int, name: str = "todo"
) -> int:
    rid = _raw_insert_status(conn, workspace_id, name)
    _commit(conn)
    return rid


def insert_project(
    conn: sqlite3.Connection, workspace_id: int, name: str = "proj1", description: str | None = "desc"
) -> int:
    rid = _raw_insert_project(conn, workspace_id, name, description)
    _commit(conn)
    return rid


def insert_task(
    conn: sqlite3.Connection,
    workspace_id: int,
    title: str,
    status_id: int,
    project_id: int | None = None,
    priority: int = 1,
    due_date: int | None = None,
) -> int:
    rid = _raw_insert_task(conn, workspace_id, title, status_id, project_id, priority, due_date)
    _commit(conn)
    return rid


def insert_task_dependency(
    conn: sqlite3.Connection, task_id: int, depends_on_id: int
) -> None:
    _raw_insert_task_dependency(conn, task_id, depends_on_id)
    _commit(conn)


def insert_group(
    conn: sqlite3.Connection,
    project_id: int,
    title: str = "group1",
    parent_id: int | None = None,
    position: int = 0,
) -> int:
    rid = _raw_insert_group(conn, project_id, title, parent_id, position)
    _commit(conn)
    return rid


def insert_tag(
    conn: sqlite3.Connection, workspace_id: int, name: str = "tag1"
) -> int:
    rid = _raw_insert_tag(conn, workspace_id, name)
    _commit(conn)
    return rid


def insert_task_tag(
    conn: sqlite3.Connection, task_id: int, tag_id: int
) -> None:
    _raw_insert_task_tag(conn, task_id, tag_id)
    _commit(conn)


# ---- Workspace ----


class TestWorkspaceService:
    def test_create(self, conn: sqlite3.Connection) -> None:
        workspace = service.create_workspace(conn, "work")
        assert isinstance(workspace, Workspace)
        assert workspace.name == "work"
        assert workspace.archived is False

    def test_create_duplicate_raises(self, conn: sqlite3.Connection) -> None:
        service.create_workspace(conn, "work")
        with pytest.raises(ValueError, match="workspace with this name already exists"):
            service.create_workspace(conn, "work")

    def test_get(self, conn: sqlite3.Connection) -> None:
        workspace = service.create_workspace(conn, "work")
        assert service.get_workspace(conn, workspace.id) == workspace

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_workspace(conn, 999)

    def test_get_by_name(self, conn: sqlite3.Connection) -> None:
        workspace = service.create_workspace(conn, "work")
        assert service.get_workspace_by_name(conn, "work") == workspace

    def test_get_by_name_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_workspace_by_name(conn, "nope")

    def test_list(self, conn: sqlite3.Connection) -> None:
        b1 = service.create_workspace(conn, "a")
        b2 = service.create_workspace(conn, "b")
        assert service.list_workspaces(conn) == (b1, b2)

    def test_list_excludes_archived(self, conn: sqlite3.Connection) -> None:
        b1 = service.create_workspace(conn, "a")
        service.create_workspace(conn, "b")
        service.update_workspace(conn, b1.id, {"archived": True})
        active = service.list_workspaces(conn)
        assert len(active) == 1
        assert active[0].name == "b"

    def test_list_include_archived(self, conn: sqlite3.Connection) -> None:
        service.create_workspace(conn, "a")
        service.create_workspace(conn, "b")
        service.update_workspace(conn, 1, {"archived": True})
        assert len(service.list_workspaces(conn, include_archived=True)) == 2

    def test_update(self, conn: sqlite3.Connection) -> None:
        workspace = service.create_workspace(conn, "old")
        updated = service.update_workspace(conn, workspace.id, {"name": "new"})
        assert updated.name == "new"

    def test_update_archive_with_active_children_blocked(self, conn: sqlite3.Connection) -> None:
        workspace = service.create_workspace(conn, "work")
        service.create_status(conn, workspace.id, "todo")
        with pytest.raises(ValueError, match="active status"):
            service.update_workspace(conn, workspace.id, {"archived": True})

    def test_archive_empty_workspace_allowed(self, conn: sqlite3.Connection) -> None:
        workspace = service.create_workspace(conn, "work")
        updated = service.update_workspace(conn, workspace.id, {"archived": True})
        assert updated.archived is True


# ---- Status ----


class TestStatusService:
    def test_create(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        col = service.create_status(conn, bid, "todo")
        assert isinstance(col, Status)
        assert col.name == "todo"

    def test_get(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        col = service.create_status(conn, bid, "todo")
        assert service.get_status(conn, col.id) == col

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_status(conn, 999)

    def test_list_statuses_ordered_alphabetically(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        service.create_status(conn, bid, "todo")
        service.create_status(conn, bid, "done")
        statuses = service.list_statuses(conn, bid)
        assert [s.name for s in statuses] == ["done", "todo"]

    def test_get_by_name(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        col = service.create_status(conn, bid, "todo")
        assert service.get_status_by_name(conn, bid, "todo") == col

    def test_get_by_name_missing_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        with pytest.raises(LookupError, match="not found"):
            service.get_status_by_name(conn, bid, "nope")

    def test_update(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        col = service.create_status(conn, bid, "old")
        updated = service.update_status(conn, col.id, {"name": "new"})
        assert updated.name == "new"

    def test_archive_status_with_active_tasks_blocked(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        insert_task(conn, bid, "task", cid)
        with pytest.raises(ValueError, match="active task"):
            service.update_status(conn, cid, {"archived": True})

    def test_archive_empty_status_allowed(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        col = service.create_status(conn, bid, "empty")
        updated = service.update_status(conn, col.id, {"archived": True})
        assert updated.archived is True


# ---- Project ----


class TestProjectService:
    def test_create(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        proj = service.create_project(conn, bid, "alpha", description="desc")
        assert isinstance(proj, Project)
        assert proj.name == "alpha"
        assert proj.description == "desc"

    def test_get(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        proj = service.create_project(conn, bid, "alpha")
        assert service.get_project(conn, proj.id) == proj

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_project(conn, 999)

    def test_get_by_name(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        proj = service.create_project(conn, bid, "alpha")
        assert service.get_project_by_name(conn, bid, "alpha") == proj

    def test_get_by_name_missing_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        with pytest.raises(LookupError, match="not found"):
            service.get_project_by_name(conn, bid, "nope")

    def test_get_detail(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        proj = service.create_project(conn, bid, "alpha")
        insert_task(conn, bid, "t1", cid, project_id=proj.id)
        detail = service.get_project_detail(conn, proj.id)
        assert isinstance(detail, ProjectDetail)
        assert len(detail.tasks) == 1
        assert detail.tasks[0].title == "t1"

    def test_list(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        p1 = service.create_project(conn, bid, "a")
        p2 = service.create_project(conn, bid, "b")
        assert service.list_projects(conn, bid) == (p1, p2)

    def test_update(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        proj = service.create_project(conn, bid, "old")
        updated = service.update_project(conn, proj.id, {"name": "new"})
        assert updated.name == "new"

    def test_update_archive_with_active_children_blocked(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        proj = service.create_project(conn, bid, "alpha")
        insert_task(conn, bid, "task", cid, project_id=proj.id)
        with pytest.raises(ValueError, match="active task"):
            service.update_project(conn, proj.id, {"archived": True})

    def test_archive_empty_project_allowed(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        proj = service.create_project(conn, bid, "alpha")
        updated = service.update_project(conn, proj.id, {"archived": True})
        assert updated.archived is True


# ---- Task ----


class TestTaskService:
    def test_create(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "do stuff", cid)
        assert isinstance(task, Task)
        assert task.title == "do stuff"
        assert task.priority == 1

    def test_create_with_tags_auto_creates(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid, tags=("bug", "urgent"))
        detail = service.get_task_detail(conn, task.id)
        assert {t.name for t in detail.tags} == {"bug", "urgent"}

    def test_create_with_tags_reuses_existing(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        existing = service.create_tag(conn, bid, "bug")
        task = service.create_task(conn, bid, "t", cid, tags=("bug",))
        detail = service.get_task_detail(conn, task.id)
        assert len(detail.tags) == 1
        assert detail.tags[0].id == existing.id

    def test_get(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "do stuff", cid)
        assert service.get_task(conn, task.id) == task

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_task(conn, 999)

    def test_get_by_title(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "Find me", cid)
        found = service.get_task_by_title(conn, bid, "Find me")
        assert found.id == task.id
        assert found.title == "Find me"

    def test_get_by_title_missing_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        with pytest.raises(LookupError, match="not found"):
            service.get_task_by_title(conn, bid, "nonexistent")

    def test_resolve_task_id_numeric(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "a", cid)
        assert service.resolve_task_id(conn, bid, str(task.id)) == task.id
        assert service.resolve_task_id(conn, bid, f"task-{task.id:04d}") == task.id
        assert service.resolve_task_id(conn, bid, f"#{task.id}") == task.id

    def test_resolve_task_id_title_fallback(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "Find me", cid)
        assert service.resolve_task_id(conn, bid, "Find me", by_title=True) == task.id

    def test_resolve_task_id_no_title_without_flag_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        service.create_task(conn, bid, "Find me", cid)
        with pytest.raises(LookupError):
            service.resolve_task_id(conn, bid, "Find me")

    def test_resolve_task_id_missing_title_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        with pytest.raises(LookupError):
            service.resolve_task_id(conn, bid, "nonexistent task", by_title=True)

    def test_get_detail(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        pid = insert_project(conn, bid)
        tid = insert_task(conn, bid, "a", cid, project_id=pid)
        detail = service.get_task_detail(conn, tid)
        assert isinstance(detail, TaskDetail)
        assert detail.status.id == cid
        assert detail.project is not None
        assert detail.project.id == pid

    def test_get_detail_no_project(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        tid = insert_task(conn, bid, "a", cid)
        detail = service.get_task_detail(conn, tid)
        assert detail.project is None

    def test_get_task_detail_hydrates_group(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        pid = insert_project(conn, bid)
        grp = service.create_group(conn, pid, "Auth")
        task = service.create_task(conn, bid, "t", cid, project_id=pid)
        service.assign_task_to_group(conn, task.id, grp.id, source="test")
        detail = service.get_task_detail(conn, task.id)
        assert detail.group is not None
        assert detail.group.id == grp.id
        assert detail.group.title == "Auth"

    def test_get_task_detail_group_none_when_unassigned(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        tid = insert_task(conn, bid, "a", cid)
        detail = service.get_task_detail(conn, tid)
        assert detail.group is None

    def test_get_detail_with_deps_and_history(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "blocker", cid)
        t2 = insert_task(conn, bid, "blocked", cid)
        insert_task_dependency(conn, t2, t1)
        service.update_task(conn, t2, {"title": "renamed"}, "tui")
        detail = service.get_task_detail(conn, t2)
        assert len(detail.blocked_by) == 1
        assert detail.blocked_by[0].id == t1
        assert len(detail.history) == 1

    def test_list(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        service.create_task(conn, bid, "a", cid)
        service.create_task(conn, bid, "b", cid)
        tasks = service.list_tasks(conn, bid)
        assert len(tasks) == 2

    def test_update(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "old", cid)
        updated = service.update_task(conn, task.id, {"title": "new"}, "tui")
        assert updated.title == "new"

    def test_update_with_add_and_remove_tags(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid, tags=("bug",))
        service.update_task(
            conn, task.id, {"title": "t2"}, "cli",
            add_tags=("urgent",), remove_tags=("bug",),
        )
        detail = service.get_task_detail(conn, task.id)
        assert detail.title == "t2"
        assert {t.name for t in detail.tags} == {"urgent"}

    def test_update_tag_only_no_field_changes(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        updated = service.update_task(conn, task.id, {}, "cli", add_tags=("bug",))
        assert updated.title == "t"
        detail = service.get_task_detail(conn, task.id)
        assert {t.name for t in detail.tags} == {"bug"}

    def test_update_with_no_changes_is_noop(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        result = service.update_task(conn, task.id, {}, "cli")
        assert result.id == task.id
        assert result.title == task.title

    def test_update_remove_nonexistent_tag_rolls_back(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "old", cid)
        with pytest.raises(LookupError):
            service.update_task(
                conn, task.id, {"title": "new"}, "cli",
                remove_tags=("nonexistent",),
            )
        # field change must be rolled back since remove_tags failed in same transaction
        assert service.get_task(conn, task.id).title == "old"

    def test_update_records_history(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "old", cid)
        service.update_task(conn, task.id, {"title": "new"}, "tui")
        history = service.list_task_history(conn, task.id)
        assert len(history) == 1
        assert history[0].field == "title"
        assert history[0].old_value == "old"
        assert history[0].new_value == "new"
        assert history[0].source == "tui"

    def test_update_skips_history_when_unchanged(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "same", cid)
        service.update_task(conn, task.id, {"title": "same"}, "tui")
        history = service.list_task_history(conn, task.id)
        assert len(history) == 0

    def test_update_multiple_fields_records_multiple_history(
        self, conn: sqlite3.Connection
    ) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "old", cid, priority=1)
        service.update_task(conn, task.id, {"title": "new", "priority": 5}, "mcp")
        history = service.list_task_history(conn, task.id)
        assert len(history) == 2
        fields = {h.field for h in history}
        assert fields == {"title", "priority"}

    def test_update_none_old_value_stored_as_null(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        assert task.description is None
        service.update_task(conn, task.id, {"description": "added"}, "tui")
        history = service.list_task_history(conn, task.id)
        assert len(history) == 1
        assert history[0].old_value is None
        assert history[0].new_value == "added"

    def test_move_task(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        c1 = insert_status(conn, bid, "todo")
        c2 = insert_status(conn, bid, "done")
        task = service.create_task(conn, bid, "t", c1)
        moved = service.move_task(conn, task.id, c2, 0, "tui")
        assert moved.status_id == c2
        history = service.list_task_history(conn, task.id)
        assert any(h.field == "status_id" for h in history)

    def test_move_task_with_project_change(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        c1 = insert_status(conn, bid, "todo")
        c2 = insert_status(conn, bid, "doing")
        pid = insert_project(conn, bid, "alpha")
        task = service.create_task(conn, bid, "t", c1)
        moved = service.move_task(conn, task.id, c2, 0, "cli", project_id=pid)
        assert moved.status_id == c2
        assert moved.project_id == pid
        history = service.list_task_history(conn, task.id)
        assert any(h.field == "project_id" for h in history)
        assert any(h.field == "status_id" for h in history)

    def test_move_task_project_unchanged_by_default(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        c1 = insert_status(conn, bid, "todo")
        c2 = insert_status(conn, bid, "doing")
        pid = insert_project(conn, bid, "alpha")
        task = service.create_task(conn, bid, "t", c1, project_id=pid)
        moved = service.move_task(conn, task.id, c2, 0, "cli")
        assert moved.project_id == pid

    # ---- Pre-validation ----

    def test_create_priority_too_low(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        with pytest.raises(ValueError, match="priority"):
            service.create_task(conn, bid, "t", cid, priority=0)

    def test_create_priority_too_high(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        with pytest.raises(ValueError, match="priority"):
            service.create_task(conn, bid, "t", cid, priority=6)

    def test_create_negative_position(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        with pytest.raises(ValueError, match="position"):
            service.create_task(conn, bid, "t", cid, position=-1)

    def test_create_finish_before_start(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        with pytest.raises(ValueError, match="finish date"):
            service.create_task(conn, bid, "t", cid, start_date=200, finish_date=100)

    def test_update_priority_out_of_range(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        with pytest.raises(ValueError, match="priority"):
            service.update_task(conn, task.id, {"priority": 0}, "test")

    def test_update_negative_position(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        with pytest.raises(ValueError, match="position"):
            service.update_task(conn, task.id, {"position": -1}, "test")

    def test_update_finish_before_existing_start(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid, start_date=200)
        with pytest.raises(ValueError, match="finish date"):
            service.update_task(conn, task.id, {"finish_date": 100}, "test")

    def test_update_start_after_existing_finish(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid, finish_date=100)
        with pytest.raises(ValueError, match="finish date"):
            service.update_task(conn, task.id, {"start_date": 200}, "test")

    def test_update_status_wrong_workspace(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, "workspace1")
        b2 = insert_workspace(conn, "workspace2")
        c1 = insert_status(conn, b1, "todo")
        c2 = insert_status(conn, b2, "done")
        task = service.create_task(conn, b1, "t", c1)
        with pytest.raises(ValueError, match="workspace"):
            service.update_task(conn, task.id, {"status_id": c2}, "test")

    def test_update_project_wrong_workspace(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, "workspace1")
        b2 = insert_workspace(conn, "workspace2")
        c1 = insert_status(conn, b1)
        insert_status(conn, b2)
        p2 = insert_project(conn, b2, "proj2")
        task = service.create_task(conn, b1, "t", c1)
        with pytest.raises(ValueError, match="workspace"):
            service.update_task(conn, task.id, {"project_id": p2}, "test")

    def test_update_status_not_found(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        with pytest.raises(LookupError, match="status 999"):
            service.update_task(conn, task.id, {"status_id": 999}, "test")

    def test_update_project_not_found(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        with pytest.raises(LookupError, match="project 999"):
            service.update_task(conn, task.id, {"project_id": 999}, "test")

    # ---- Archival safety ----

    def test_move_to_archived_status_blocked(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        c1 = insert_status(conn, bid, "active")
        c2 = insert_status(conn, bid, "archived")
        service.update_status(conn, c2, {"archived": True})
        task = service.create_task(conn, bid, "t", c1)
        with pytest.raises(ValueError, match="archived"):
            service.update_task(conn, task.id, {"status_id": c2}, "test")

    def test_assign_to_archived_project_blocked(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        proj = service.create_project(conn, bid, "old")
        service.update_project(conn, proj.id, {"archived": True})
        task = service.create_task(conn, bid, "t", cid)
        with pytest.raises(ValueError, match="archived"):
            service.update_task(conn, task.id, {"project_id": proj.id}, "test")

    def test_assign_to_archived_group_blocked(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        pid = insert_project(conn, bid)
        gid = insert_group(conn, pid, "g1")
        service.cascade_archive_group(conn, gid, source="test")
        tid = insert_task(conn, bid, "t", cid)
        with pytest.raises(ValueError, match="archived"):
            service.assign_task_to_group(conn, tid, gid, source="test")


# ---- Dependency ----


class TestDependencyService:
    def test_add(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_dependency(conn, t2, t1)
        detail = service.get_task_detail(conn, t2)
        assert any(t.id == t1 for t in detail.blocked_by)

    def test_remove(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_dependency(conn, t2, t1)
        service.archive_dependency(conn, t2, t1)
        detail = service.get_task_detail(conn, t2)
        assert detail.blocked_by == ()

    def test_add_self_ref_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        tid = insert_task(conn, bid, "a", cid)
        with pytest.raises(ValueError, match="cannot depend on itself"):
            service.add_dependency(conn, tid, tid)

    def test_add_cross_workspace_raises(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, "workspace1")
        b2 = insert_workspace(conn, "workspace2")
        c1 = insert_status(conn, b1)
        c2 = insert_status(conn, b2)
        t1 = insert_task(conn, b1, "a", c1)
        t2 = insert_task(conn, b2, "b", c2)
        with pytest.raises(ValueError, match="same workspace"):
            service.add_dependency(conn, t2, t1)

    def test_cycle_direct(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_dependency(conn, t1, t2)  # t1 -> t2
        with pytest.raises(ValueError, match="cycle"):
            service.add_dependency(conn, t2, t1)  # t2 -> t1 would cycle

    def test_cycle_transitive(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        t3 = insert_task(conn, bid, "c", cid)
        service.add_dependency(conn, t1, t2)  # t1 -> t2
        service.add_dependency(conn, t2, t3)  # t2 -> t3
        with pytest.raises(ValueError, match="cycle"):
            service.add_dependency(conn, t3, t1)  # t3 -> t1 would cycle

    def test_non_cycle_allowed(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        t3 = insert_task(conn, bid, "c", cid)
        service.add_dependency(conn, t1, t2)  # t1 -> t2
        service.add_dependency(conn, t1, t3)  # t1 -> t3 (diamond, not cycle)
        service.add_dependency(conn, t2, t3)  # t2 -> t3 (converge, not cycle)
        detail = service.get_task_detail(conn, t1)
        assert {t.id for t in detail.blocked_by} == {t2, t3}

    def test_add_duplicate_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_dependency(conn, t1, t2)
        with pytest.raises(ValueError, match="already depends"):
            service.add_dependency(conn, t1, t2)


# ---- Group Dependency ----


class TestGroupDependencyService:
    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int, int, int]:
        bid = insert_workspace(conn)
        pid = insert_project(conn, bid)
        g1 = insert_group(conn, pid, "g1")
        g2 = insert_group(conn, pid, "g2")
        g3 = insert_group(conn, pid, "g3")
        return bid, g1, g2, g3

    def test_add(self, conn: sqlite3.Connection) -> None:
        _, g1, g2, _ = self._setup(conn)
        service.add_group_dependency(conn, g1, g2)
        deps = service.list_all_group_dependencies(conn)
        assert (g1, g2) in deps

    def test_archive(self, conn: sqlite3.Connection) -> None:
        _, g1, g2, _ = self._setup(conn)
        service.add_group_dependency(conn, g1, g2)
        service.archive_group_dependency(conn, g1, g2)
        assert service.list_all_group_dependencies(conn) == ()

    def test_add_self_ref_raises(self, conn: sqlite3.Connection) -> None:
        _, g1, _, _ = self._setup(conn)
        with pytest.raises(ValueError, match="cannot depend on itself"):
            service.add_group_dependency(conn, g1, g1)

    def test_cycle_direct(self, conn: sqlite3.Connection) -> None:
        _, g1, g2, _ = self._setup(conn)
        service.add_group_dependency(conn, g1, g2)  # g1 -> g2
        with pytest.raises(ValueError, match="cycle"):
            service.add_group_dependency(conn, g2, g1)  # g2 -> g1 would cycle

    def test_cycle_transitive(self, conn: sqlite3.Connection) -> None:
        _, g1, g2, g3 = self._setup(conn)
        service.add_group_dependency(conn, g1, g2)  # g1 -> g2
        service.add_group_dependency(conn, g2, g3)  # g2 -> g3
        with pytest.raises(ValueError, match="cycle"):
            service.add_group_dependency(conn, g3, g1)  # g3 -> g1 would cycle

    def test_add_duplicate_raises(self, conn: sqlite3.Connection) -> None:
        _, g1, g2, _ = self._setup(conn)
        service.add_group_dependency(conn, g1, g2)
        with pytest.raises(ValueError, match="already depends"):
            service.add_group_dependency(conn, g1, g2)


# ---- History ----


class TestHistoryService:
    def test_list(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        service.update_task(conn, task.id, {"title": "new"}, "tui")
        history = service.list_task_history(conn, task.id)
        assert len(history) == 1
        assert isinstance(history[0], TaskHistory)

    def test_list_missing_task_returns_empty(self, conn: sqlite3.Connection) -> None:
        assert service.list_task_history(conn, 9999) == ()


# ---- Filtered listing ----


class TestListTasksFiltered:
    def test_no_filter_returns_all(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        insert_task(conn, bid, "a", cid)
        insert_task(conn, bid, "b", cid)
        tasks = service.list_tasks_filtered(conn, bid)
        assert len(tasks) == 2
        assert all(isinstance(t, Task) for t in tasks)

    def test_filter_by_status(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        c1 = insert_status(conn, bid, "todo")
        c2 = insert_status(conn, bid, "done")
        insert_task(conn, bid, "a", c1)
        insert_task(conn, bid, "b", c2)
        tasks = service.list_tasks_filtered(conn, bid, task_filter=TaskFilter(status_id=c1))
        assert len(tasks) == 1
        assert tasks[0].title == "a"

    def test_filter_by_priority(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        insert_task(conn, bid, "low", cid, priority=1)
        insert_task(conn, bid, "high", cid, priority=3)
        tasks = service.list_tasks_filtered(conn, bid, task_filter=TaskFilter(priority=3))
        assert len(tasks) == 1
        assert tasks[0].title == "high"

    def test_filter_by_search(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        insert_task(conn, bid, "Fix login", cid)
        insert_task(conn, bid, "Add search", cid)
        tasks = service.list_tasks_filtered(conn, bid, task_filter=TaskFilter(search="login"))
        assert len(tasks) == 1
        assert tasks[0].title == "Fix login"


# ---- Move task to workspace ----


class TestMoveTaskToWorkspace:
    def test_happy_path(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, "workspace1")
        c1 = insert_status(conn, b1, "todo")
        tid = insert_task(conn, b1, "my task", c1, priority=3)

        b2 = insert_workspace(conn, "workspace2")
        c2 = insert_status(conn, b2, "backlog")

        new = service.move_task_to_workspace(conn, tid, b2, c2, source="test")
        assert new.workspace_id == b2
        assert new.status_id == c2
        assert new.title == "my task"
        assert new.priority == 3
        assert new.archived == 0

        old = service.get_task(conn, tid)
        assert old.archived == 1

    def test_with_project(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, "workspace1")
        c1 = insert_status(conn, b1, "todo")
        tid = insert_task(conn, b1, "task", c1)

        b2 = insert_workspace(conn, "workspace2")
        c2 = insert_status(conn, b2, "backlog")
        pid = insert_project(conn, b2, "proj")

        new = service.move_task_to_workspace(conn, tid, b2, c2, project_id=pid, source="test")
        assert new.project_id == pid

    def test_title_conflict(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, "workspace1")
        c1 = insert_status(conn, b1, "todo")
        insert_task(conn, b1, "dup", c1)

        b2 = insert_workspace(conn, "workspace2")
        c2 = insert_status(conn, b2, "backlog")
        insert_task(conn, b2, "dup", c2)

        t1 = service.get_task_by_title(conn, b1, "dup")
        with pytest.raises(ValueError, match="task with this title already exists"):
            service.move_task_to_workspace(conn, t1.id, b2, c2, source="test")

    def test_blocked_by_deps(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "blocker", cid)
        t2 = insert_task(conn, bid, "blocked", cid)
        insert_task_dependency(conn, t2, t1)

        b2 = insert_workspace(conn, "workspace2")
        c2 = insert_status(conn, b2, "backlog")

        with pytest.raises(ValueError, match="dependencies"):
            service.move_task_to_workspace(conn, t2, b2, c2, source="test")

    def test_blocks_deps(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "blocker", cid)
        t2 = insert_task(conn, bid, "blocked", cid)
        insert_task_dependency(conn, t2, t1)

        b2 = insert_workspace(conn, "workspace2")
        c2 = insert_status(conn, b2, "backlog")

        with pytest.raises(ValueError, match="dependencies"):
            service.move_task_to_workspace(conn, t1, b2, c2, source="test")

    def test_archived_task(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        tid = insert_task(conn, bid, "task", cid)
        service.update_task(conn, tid, {"archived": True}, source="test")

        b2 = insert_workspace(conn, "workspace2")
        c2 = insert_status(conn, b2, "backlog")

        with pytest.raises(ValueError, match="archived"):
            service.move_task_to_workspace(conn, tid, b2, c2, source="test")

    def test_status_wrong_workspace(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, "workspace1")
        c1 = insert_status(conn, b1, "todo")
        tid = insert_task(conn, b1, "task", c1)

        b2 = insert_workspace(conn, "workspace2")
        insert_status(conn, b2, "backlog")

        with pytest.raises(ValueError, match="does not belong"):
            service.move_task_to_workspace(conn, tid, b2, c1, source="test")

    def test_project_wrong_workspace(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, "workspace1")
        c1 = insert_status(conn, b1, "todo")
        p1 = insert_project(conn, b1, "proj1")
        tid = insert_task(conn, b1, "task", c1)

        b2 = insert_workspace(conn, "workspace2")
        c2 = insert_status(conn, b2, "backlog")

        with pytest.raises(ValueError, match="does not belong"):
            service.move_task_to_workspace(conn, tid, b2, c2, project_id=p1, source="test")

    def test_copies_dates(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, "workspace1")
        c1 = insert_status(conn, b1, "todo")
        task = service.create_task(
            conn, b1, "dated", c1,
            due_date=1700000000, start_date=1699000000, finish_date=1701000000,
        )

        b2 = insert_workspace(conn, "workspace2")
        c2 = insert_status(conn, b2, "backlog")

        new = service.move_task_to_workspace(conn, task.id, b2, c2, source="test")
        assert new.due_date == 1700000000
        assert new.start_date == 1699000000
        assert new.finish_date == 1701000000

    # ---- preview_move_to_workspace ----

    def test_preview_clean(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, "b1")
        c1 = insert_status(conn, b1, "todo")
        tid = insert_task(conn, b1, "t", c1)
        b2 = insert_workspace(conn, "b2")
        c2 = insert_status(conn, b2, "backlog")
        preview = service.preview_move_to_workspace(conn, tid, b2, c2)
        assert preview.can_move is True
        assert preview.blocking_reason is None
        assert preview.dependency_ids == ()
        assert preview.is_archived is False
        assert preview.task_title == "t"
        assert preview.source_workspace_id == b1
        assert preview.target_workspace_id == b2
        assert preview.target_status_id == c2

    def test_preview_with_deps(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "blocker", cid)
        t2 = insert_task(conn, bid, "blocked", cid)
        insert_task_dependency(conn, t2, t1)
        b2 = insert_workspace(conn, "b2")
        c2 = insert_status(conn, b2, "backlog")
        preview = service.preview_move_to_workspace(conn, t2, b2, c2)
        assert preview.can_move is False
        assert preview.dependency_ids == (t1,)
        assert "dependencies" in preview.blocking_reason

    def test_preview_archived_task(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        tid = insert_task(conn, bid, "t", cid)
        service.update_task(conn, tid, {"archived": True}, source="test")
        b2 = insert_workspace(conn, "b2")
        c2 = insert_status(conn, b2, "backlog")
        preview = service.preview_move_to_workspace(conn, tid, b2, c2)
        assert preview.can_move is False
        assert preview.is_archived is True
        assert "archived" in preview.blocking_reason

    def test_preview_invalid_target_status(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, "b1")
        c1 = insert_status(conn, b1, "todo")
        tid = insert_task(conn, b1, "t", c1)
        b2 = insert_workspace(conn, "b2")
        # Pass c1 (belongs to b1) as if it were on b2
        preview = service.preview_move_to_workspace(conn, tid, b2, c1)
        assert preview.can_move is False
        assert "does not belong" in preview.blocking_reason

    def test_preview_does_not_mutate(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, "b1")
        c1 = insert_status(conn, b1, "todo")
        tid = insert_task(conn, b1, "t", c1)
        b2 = insert_workspace(conn, "b2")
        c2 = insert_status(conn, b2, "backlog")
        before = service.get_task(conn, tid)
        service.preview_move_to_workspace(conn, tid, b2, c2)
        after = service.get_task(conn, tid)
        assert before == after


# ---- Group ----


class TestGroupService:
    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int, int]:
        """Returns (workspace_id, status_id, project_id)."""
        bid = insert_workspace(conn, "workspace1")
        cid = insert_status(conn, bid, "todo")
        pid = insert_project(conn, bid, "proj1")
        return bid, cid, pid

    def test_create_group(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "Frontend")
        assert isinstance(grp, Group)
        assert grp.title == "Frontend"
        assert grp.project_id == pid

    def test_create_with_parent(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        parent = service.create_group(conn, pid, "parent")
        child = service.create_group(conn, pid, "child", parent_id=parent.id)
        assert child.parent_id == parent.id

    def test_create_with_cross_project_parent_raises(self, conn: sqlite3.Connection) -> None:
        bid, _, pid1 = self._setup(conn)
        pid2 = insert_project(conn, bid, "proj2")
        parent = service.create_group(conn, pid1, "parent")
        with pytest.raises(ValueError, match="not"):
            service.create_group(conn, pid2, "child", parent_id=parent.id)

    def test_create_with_missing_parent_raises(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        with pytest.raises(LookupError, match="parent"):
            service.create_group(conn, pid, "child", parent_id=9999)

    def test_get_group(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        assert service.get_group(conn, grp.id) == grp

    def test_get_group_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_group(conn, 9999)

    def test_get_group_by_title(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "Backend")
        assert service.get_group_by_title(conn, pid, "Backend") == grp

    def test_get_group_by_title_missing_raises(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        with pytest.raises(LookupError):
            service.get_group_by_title(conn, pid, "nope")

    def test_resolve_group_scoped_to_project(self, conn: sqlite3.Connection) -> None:
        bid, _, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "Frontend")
        resolved = service.resolve_group_by_title(conn, bid, "Frontend", project_id=pid)
        assert resolved == grp

    def test_resolve_group_unique_across_workspace(self, conn: sqlite3.Connection) -> None:
        bid, _, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "Frontend")
        resolved = service.resolve_group_by_title(conn, bid, "Frontend")
        assert resolved == grp

    def test_resolve_group_case_insensitive(self, conn: sqlite3.Connection) -> None:
        bid, _, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "Frontend")
        resolved = service.resolve_group_by_title(conn, bid, "frontend")
        assert resolved == grp

    def test_resolve_group_missing_raises(self, conn: sqlite3.Connection) -> None:
        bid, _, _ = self._setup(conn)
        with pytest.raises(LookupError, match="not found"):
            service.resolve_group_by_title(conn, bid, "nope")

    def test_resolve_group_ambiguous_raises(self, conn: sqlite3.Connection) -> None:
        bid, _, pid1 = self._setup(conn)
        pid2 = insert_project(conn, bid, "proj2")
        service.create_group(conn, pid1, "shared")
        service.create_group(conn, pid2, "shared")
        with pytest.raises(LookupError, match="ambiguous"):
            service.resolve_group_by_title(conn, bid, "shared")

    def test_resolve_group_ambiguity_ignored_when_scoped(self, conn: sqlite3.Connection) -> None:
        bid, _, pid1 = self._setup(conn)
        pid2 = insert_project(conn, bid, "proj2")
        service.create_group(conn, pid1, "shared")
        g2 = service.create_group(conn, pid2, "shared")
        resolved = service.resolve_group_by_title(conn, bid, "shared", project_id=pid2)
        assert resolved == g2

    def test_resolve_group_by_project_name(self, conn: sqlite3.Connection) -> None:
        bid, _, pid1 = self._setup(conn)
        pid2 = insert_project(conn, bid, "proj2")
        g1 = service.create_group(conn, pid1, "shared")
        g2 = service.create_group(conn, pid2, "shared")
        assert service.resolve_group(conn, bid, "shared", project_name="proj1") == g1
        assert service.resolve_group(conn, bid, "shared", project_name="proj2") == g2

    def test_resolve_group_no_project_name_unambiguous(self, conn: sqlite3.Connection) -> None:
        bid, _, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "only")
        assert service.resolve_group(conn, bid, "only") == grp

    def test_resolve_group_unknown_project_raises(self, conn: sqlite3.Connection) -> None:
        bid, _, pid = self._setup(conn)
        service.create_group(conn, pid, "g")
        with pytest.raises(LookupError):
            service.resolve_group(conn, bid, "g", project_name="no-such-project")

    def test_get_ancestry_single(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "root")
        ancestry = service.get_group_ancestry(conn, grp.id)
        assert len(ancestry) == 1
        assert ancestry[0].id == grp.id

    def test_get_ancestry_nested(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        root = service.create_group(conn, pid, "root")
        mid = service.create_group(conn, pid, "mid", parent_id=root.id)
        leaf = service.create_group(conn, pid, "leaf", parent_id=mid.id)
        ancestry = service.get_group_ancestry(conn, leaf.id)
        assert [g.id for g in ancestry] == [root.id, mid.id, leaf.id]

    def test_get_ancestry_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_group_ancestry(conn, 9999)

    def test_list_groups(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        service.create_group(conn, pid, "g1")
        service.create_group(conn, pid, "g2")
        refs = service.list_groups(conn, pid)
        assert len(refs) == 2
        assert all(isinstance(r, GroupRef) for r in refs)

    def test_build_tree_flat(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        g1 = service.create_group(conn, pid, "a")
        g2 = service.create_group(conn, pid, "b")
        tree = service.build_group_tree(conn, pid)
        assert tree.project_id == pid
        assert len(tree.roots) == 2
        assert {r.group.id for r in tree.roots} == {g1.id, g2.id}
        assert all(r.children == () for r in tree.roots)
        assert tree.ungrouped_task_count == 0

    def test_build_tree_nested(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        root = service.create_group(conn, pid, "root")
        mid = service.create_group(conn, pid, "mid", parent_id=root.id)
        leaf = service.create_group(conn, pid, "leaf", parent_id=mid.id)
        tree = service.build_group_tree(conn, pid)
        assert len(tree.roots) == 1
        assert tree.roots[0].group.id == root.id
        assert len(tree.roots[0].children) == 1
        assert tree.roots[0].children[0].group.id == mid.id
        assert tree.roots[0].children[0].children[0].group.id == leaf.id

    def test_build_tree_with_ungrouped_count(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        t1 = insert_task(conn, bid, "t1", cid, project_id=pid)
        insert_task(conn, bid, "t2", cid, project_id=pid)
        service.assign_task_to_group(conn, t1, grp.id, source="test")
        tree = service.build_group_tree(conn, pid)
        assert tree.ungrouped_task_count == 1

    def test_build_tree_archived_filter(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        service.create_group(conn, pid, "live")
        arch = service.create_group(conn, pid, "arch")
        service.cascade_archive_group(conn, arch.id, source="test")
        tree_default = service.build_group_tree(conn, pid)
        assert len(tree_default.roots) == 1
        tree_all = service.build_group_tree(conn, pid, include_archived=True)
        assert len(tree_all.roots) == 2

    def test_update_group(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "old")
        updated = service.update_group(conn, grp.id, {"title": "new"})
        assert updated.title == "new"

    def test_reparent_cycle_detection(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        g1 = service.create_group(conn, pid, "g1")
        g2 = service.create_group(conn, pid, "g2", parent_id=g1.id)
        g3 = service.create_group(conn, pid, "g3", parent_id=g2.id)
        with pytest.raises(ValueError, match="cycle"):
            service.update_group(conn, g1.id, {"parent_id": g3.id})

    def test_reparent_to_self_raises(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        g = service.create_group(conn, pid, "g")
        with pytest.raises(ValueError, match="cycle"):
            service.update_group(conn, g.id, {"parent_id": g.id})

    def test_cascade_archive_archives_tasks(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        tid = insert_task(conn, bid, "t", cid, project_id=pid)
        service.assign_task_to_group(conn, tid, grp.id, source="test")
        service.cascade_archive_group(conn, grp.id, source="test")
        assert service.get_task(conn, tid).archived is True

    def test_cascade_archive_archives_descendants(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        parent = service.create_group(conn, pid, "parent")
        mid = service.create_group(conn, pid, "mid", parent_id=parent.id)
        child = service.create_group(conn, pid, "child", parent_id=mid.id)
        service.cascade_archive_group(conn, parent.id, source="test")
        assert service.get_group(conn, parent.id).archived is True
        assert service.get_group(conn, mid.id).archived is True
        assert service.get_group(conn, child.id).archived is True

    def test_cascade_archive_group_is_archived(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        service.cascade_archive_group(conn, grp.id, source="test")
        assert service.get_group(conn, grp.id).archived is True

    def test_get_group_detail(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        parent = service.create_group(conn, pid, "parent")
        child = service.create_group(conn, pid, "child", parent_id=parent.id)
        tid = insert_task(conn, bid, "t", cid, project_id=pid)
        service.assign_task_to_group(conn, tid, parent.id, source="test")
        detail = service.get_group_detail(conn, parent.id)
        assert isinstance(detail, GroupDetail)
        assert len(detail.tasks) == 1
        assert detail.tasks[0].id == tid
        assert len(detail.children) == 1
        assert detail.children[0].id == child.id
        assert detail.parent is None

    def test_get_group_detail_with_parent(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        parent = service.create_group(conn, pid, "parent")
        child = service.create_group(conn, pid, "child", parent_id=parent.id)
        detail = service.get_group_detail(conn, child.id)
        assert detail.parent is not None
        assert detail.parent.id == parent.id

    def test_cascade_archive_group_integrity_error_becomes_value_error(
        self, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sticky_notes import repository as repo_mod
        _, _, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        def raise_integrity(*args, **kwargs):
            raise sqlite3.IntegrityError(
                "UNIQUE constraint failed: groups.project_id, groups.title"
            )
        monkeypatch.setattr(repo_mod, "update_group", raise_integrity)
        with pytest.raises(ValueError):
            service.cascade_archive_group(conn, grp.id, source="test")


class TestTaskGroupAssignment:
    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int, int]:
        bid = insert_workspace(conn, "workspace1")
        cid = insert_status(conn, bid, "todo")
        pid = insert_project(conn, bid, "proj1")
        return bid, cid, pid

    def test_assign_task(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        tid = insert_task(conn, bid, "t", cid, project_id=pid)
        service.assign_task_to_group(conn, tid, grp.id, source="test")
        assert service.get_task(conn, tid).group_id == grp.id

    def test_assign_auto_sets_project_id(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        tid = insert_task(conn, bid, "t", cid)  # no project_id
        service.assign_task_to_group(conn, tid, grp.id, source="test")
        updated = service.get_task(conn, tid)
        assert updated.project_id == pid

    def test_assign_cross_project_raises(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid1 = self._setup(conn)
        pid2 = insert_project(conn, bid, "proj2")
        grp = service.create_group(conn, pid1, "g")
        tid = insert_task(conn, bid, "t", cid, project_id=pid2)
        with pytest.raises(ValueError, match="project"):
            service.assign_task_to_group(conn, tid, grp.id, source="test")

    def test_unassign_task(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        tid = insert_task(conn, bid, "t", cid, project_id=pid)
        service.assign_task_to_group(conn, tid, grp.id, source="test")
        service.unassign_task_from_group(conn, tid, source="test")
        assert service.get_task(conn, tid).group_id is None


class TestTaskGroupHistory:
    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int, int]:
        bid = insert_workspace(conn, "workspace1")
        cid = insert_status(conn, bid, "todo")
        pid = insert_project(conn, bid, "proj1")
        return bid, cid, pid

    def test_assign_records_history(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        tid = insert_task(conn, bid, "t", cid, project_id=pid)
        service.assign_task_to_group(conn, tid, grp.id, source="test")
        history = service.list_task_history(conn, tid)
        group_entries = [h for h in history if h.field.value == "group_id"]
        assert len(group_entries) == 1
        assert group_entries[0].old_value is None
        assert group_entries[0].new_value == str(grp.id)
        assert group_entries[0].source == "test"

    def test_source_forwarded_to_history(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        tid = insert_task(conn, bid, "t", cid, project_id=pid)
        service.assign_task_to_group(conn, tid, grp.id, source="cli")
        history = service.list_task_history(conn, tid)
        entry = next(h for h in history if h.field.value == "group_id")
        assert entry.source == "cli"
        service.unassign_task_from_group(conn, tid, source="tui")
        history2 = service.list_task_history(conn, tid)
        unassign = next(h for h in history2 if h.field.value == "group_id" and h.new_value is None)
        assert unassign.source == "tui"

    def test_reassign_records_old_and_new(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        g1 = service.create_group(conn, pid, "g1")
        g2 = service.create_group(conn, pid, "g2")
        tid = insert_task(conn, bid, "t", cid, project_id=pid)
        service.assign_task_to_group(conn, tid, g1.id, source="test")
        service.assign_task_to_group(conn, tid, g2.id, source="test")
        history = service.list_task_history(conn, tid)
        group_entries = [h for h in history if h.field.value == "group_id"]
        assert len(group_entries) == 2
        # newest first (ORDER BY changed_at DESC)
        assert group_entries[0].old_value == str(g1.id)
        assert group_entries[0].new_value == str(g2.id)

    def test_unassign_records_history(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        tid = insert_task(conn, bid, "t", cid, project_id=pid)
        service.assign_task_to_group(conn, tid, grp.id, source="test")
        service.unassign_task_from_group(conn, tid, source="test")
        history = service.list_task_history(conn, tid)
        group_entries = [h for h in history if h.field.value == "group_id"]
        assert len(group_entries) == 2
        # newest first
        unassign = group_entries[0]
        assert unassign.old_value == str(grp.id)
        assert unassign.new_value is None
        assert unassign.source == "test"

    def test_unassign_no_op_no_history(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        tid = insert_task(conn, bid, "t", cid, project_id=pid)
        service.unassign_task_from_group(conn, tid, source="test")
        history = service.list_task_history(conn, tid)
        assert not [h for h in history if h.field.value == "group_id"]

    def test_assign_records_project_id_side_effect(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        # Task with NO project: assignment should auto-set project_id AND record it.
        tid = insert_task(conn, bid, "t", cid)
        service.assign_task_to_group(conn, tid, grp.id, source="test")
        history = service.list_task_history(conn, tid)
        proj_entries = [h for h in history if h.field.value == "project_id"]
        assert len(proj_entries) == 1
        assert proj_entries[0].old_value is None
        assert proj_entries[0].new_value == str(pid)
        assert proj_entries[0].source == "test"
        # group_id history is still recorded alongside
        group_entries = [h for h in history if h.field.value == "group_id"]
        assert len(group_entries) == 1

    def test_assign_same_group_no_history(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        tid = insert_task(conn, bid, "t", cid, project_id=pid)
        service.assign_task_to_group(conn, tid, grp.id, source="test")
        service.assign_task_to_group(conn, tid, grp.id, source="test")
        history = service.list_task_history(conn, tid)
        group_entries = [h for h in history if h.field.value == "group_id"]
        # The second call is a no-op (group_id already matches); _record_changes skips it.
        assert len(group_entries) == 1

# ---- Tag ----


class TestTagService:
    def test_create_tag(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        tag = service.create_tag(conn, bid, "bug")
        assert isinstance(tag, Tag)
        assert tag.name == "bug"
        assert tag.workspace_id == bid
        assert tag.archived is False

    def test_create_tag_duplicate_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        service.create_tag(conn, bid, "bug")
        with pytest.raises(ValueError, match="tag with this name already exists"):
            service.create_tag(conn, bid, "bug")

    def test_get_tag(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        tag = service.create_tag(conn, bid, "bug")
        assert service.get_tag(conn, tag.id) == tag

    def test_get_tag_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_tag(conn, 999)

    def test_get_tag_by_name(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        tag = service.create_tag(conn, bid, "bug")
        assert service.get_tag_by_name(conn, bid, "bug") == tag

    def test_get_tag_by_name_missing_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        with pytest.raises(LookupError, match="not found"):
            service.get_tag_by_name(conn, bid, "nope")

    def test_list_tags(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        service.create_tag(conn, bid, "bug")
        service.create_tag(conn, bid, "feature")
        tags = service.list_tags(conn, bid)
        assert len(tags) == 2
        assert tags[0].name == "bug"
        assert tags[1].name == "feature"

    def test_list_tags_excludes_archived(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        tag = service.create_tag(conn, bid, "old")
        service.create_tag(conn, bid, "active")
        service.archive_tag(conn, tag.id)
        tags = service.list_tags(conn, bid)
        assert len(tags) == 1
        assert tags[0].name == "active"

    def test_list_tags_include_archived(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        tag = service.create_tag(conn, bid, "old")
        service.create_tag(conn, bid, "active")
        service.archive_tag(conn, tag.id)
        tags = service.list_tags(conn, bid, include_archived=True)
        assert len(tags) == 2

    def test_archive_tag(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        tag = service.create_tag(conn, bid, "bug")
        archived = service.archive_tag(conn, tag.id)
        assert archived.archived is True
        assert archived.id == tag.id

    def test_archive_tag_integrity_error_becomes_value_error(
        self, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sticky_notes import repository as repo_mod
        bid = insert_workspace(conn)
        tag = service.create_tag(conn, bid, "bug")
        def raise_integrity(*args, **kwargs):
            raise sqlite3.IntegrityError("UNIQUE constraint failed: tags.workspace_id, tags.name")
        monkeypatch.setattr(repo_mod, "update_tag", raise_integrity)
        with pytest.raises(ValueError):
            service.archive_tag(conn, tag.id)

    def test_tag_task(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        tid = insert_task(conn, bid, "t", cid)
        tag = service.tag_task(conn, tid, "bug", bid)
        assert isinstance(tag, Tag)
        assert tag.name == "bug"
        detail = service.get_task_detail(conn, tid)
        assert any(t.id == tag.id for t in detail.tags)

    def test_tag_task_duplicate_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        tid = insert_task(conn, bid, "t", cid)
        service.tag_task(conn, tid, "bug", bid)
        with pytest.raises(ValueError, match="already has this tag"):
            service.tag_task(conn, tid, "bug", bid)

    def test_tag_task_creates_tag(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        tid = insert_task(conn, bid, "t", cid)
        tag = service.tag_task(conn, tid, "newlabel", bid)
        assert service.get_tag_by_name(conn, bid, "newlabel") == tag

    def test_tag_task_missing_task_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        with pytest.raises(LookupError):
            service.tag_task(conn, 9999, "bug", bid)

    def test_tag_task_cross_workspace_raises(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, "workspace1")
        b2 = insert_workspace(conn, "workspace2")
        c1 = insert_status(conn, b1)
        tid = insert_task(conn, b1, "t", c1)
        with pytest.raises(ValueError, match="not workspace"):
            service.tag_task(conn, tid, "bug", b2)

    def test_untag_task_cross_workspace_raises(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, "workspace1")
        b2 = insert_workspace(conn, "workspace2")
        c1 = insert_status(conn, b1)
        tid = insert_task(conn, b1, "t", c1)
        service.tag_task(conn, tid, "bug", b1)
        with pytest.raises(ValueError, match="not workspace"):
            service.untag_task(conn, tid, "bug", b2)

    def test_untag_task(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        tid = insert_task(conn, bid, "t", cid)
        service.tag_task(conn, tid, "bug", bid)
        service.untag_task(conn, tid, "bug", bid)
        detail = service.get_task_detail(conn, tid)
        assert detail.tags == ()

    def test_untag_task_missing_tag_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        tid = insert_task(conn, bid, "t", cid)
        with pytest.raises(LookupError, match="not found"):
            service.untag_task(conn, tid, "nonexistent", bid)

    def test_untag_task_not_tagged_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        tid = insert_task(conn, bid, "t", cid)
        service.create_tag(conn, bid, "bug")
        with pytest.raises(LookupError, match="not tagged"):
            service.untag_task(conn, tid, "bug", bid)

    def test_untag_task_missing_task_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        service.create_tag(conn, bid, "bug")
        with pytest.raises(LookupError, match="task 9999 not found"):
            service.untag_task(conn, 9999, "bug", bid)

    def test_get_task_detail_has_tags(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        tid = insert_task(conn, bid, "t", cid)
        tag_id = insert_tag(conn, bid, "bug")
        insert_task_tag(conn, tid, tag_id)
        detail = service.get_task_detail(conn, tid)
        assert len(detail.tags) == 1
        assert detail.tags[0].id == tag_id
        assert detail.tags[0].name == "bug"

    def test_list_tasks_filtered_by_tag(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        insert_task(conn, bid, "b", cid)
        tag_id = insert_tag(conn, bid, "bug")
        insert_task_tag(conn, t1, tag_id)
        tasks = service.list_tasks_filtered(
            conn, bid, task_filter=TaskFilter(tag_id=tag_id)
        )
        assert len(tasks) == 1
        assert tasks[0].id == t1


# ---- Workspace list view ----


class TestGetWorkspaceListView:
    def test_empty_workspace(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn, "empty")
        view = service.get_workspace_list_view(conn, bid)
        assert isinstance(view, WorkspaceListView)
        assert view.workspace.id == bid
        assert view.workspace.name == "empty"
        assert view.statuses == ()

    def test_empty_statuses_render_as_empty_tuples(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        c1 = insert_status(conn, bid, "todo")
        c2 = insert_status(conn, bid, "done")
        insert_task(conn, bid, "a", c1)
        view = service.get_workspace_list_view(conn, bid)
        assert len(view.statuses) == 2
        # alphabetical: done(c2) first, then todo(c1)
        assert view.statuses[0].status.id == c2
        assert view.statuses[0].tasks == ()
        assert view.statuses[1].status.id == c1
        assert len(view.statuses[1].tasks) == 1

    def test_statuses_in_alphabetical_order(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        c_done = insert_status(conn, bid, "done")
        c_todo = insert_status(conn, bid, "todo")
        c_wip = insert_status(conn, bid, "wip")
        view = service.get_workspace_list_view(conn, bid)
        assert [c.status.id for c in view.statuses] == [c_done, c_todo, c_wip]

    def test_task_items_carry_project_name(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        pid = insert_project(conn, bid, "proj-x")
        insert_task(conn, bid, "with-proj", cid, project_id=pid)
        insert_task(conn, bid, "no-proj", cid)
        view = service.get_workspace_list_view(conn, bid)
        items = view.statuses[0].tasks
        by_title = {i.title: i for i in items}
        assert by_title["with-proj"].project_name == "proj-x"
        assert by_title["no-proj"].project_name is None
        assert all(isinstance(i, TaskListItem) for i in items)

    def test_task_items_carry_tag_names(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t_tagged = insert_task(conn, bid, "tagged", cid)
        insert_task(conn, bid, "untagged", cid)
        bug = insert_tag(conn, bid, "bug")
        urgent = insert_tag(conn, bid, "urgent")
        insert_task_tag(conn, t_tagged, bug)
        insert_task_tag(conn, t_tagged, urgent)
        view = service.get_workspace_list_view(conn, bid)
        items = view.statuses[0].tasks
        by_title = {i.title: i for i in items}
        assert set(by_title["tagged"].tag_names) == {"bug", "urgent"}
        assert by_title["untagged"].tag_names == ()

    def test_resolves_names_with_one_query_per_entity_type(
        self, conn: sqlite3.Connection
    ) -> None:
        """Regression: the view should not do N+1 queries for project/tag names."""
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        pid = insert_project(conn, bid, "p")
        tag = insert_tag(conn, bid, "t")
        for i in range(5):
            tid = insert_task(conn, bid, f"task-{i}", cid, project_id=pid)
            insert_task_tag(conn, tid, tag)
        view = service.get_workspace_list_view(conn, bid)
        for item in view.statuses[0].tasks:
            assert item.project_name == "p"
            assert item.tag_names == ("t",)

    def test_include_archived_shows_archived_statuses(
        self, conn: sqlite3.Connection
    ) -> None:
        bid = insert_workspace(conn)
        c_active = insert_status(conn, bid, "active")
        c_arch = insert_status(conn, bid, "archived")
        insert_task(conn, bid, "a", c_active)
        t_arch = insert_task(conn, bid, "arch-task", c_arch)
        # Must archive the task first — service forbids archiving a status
        # with active tasks.
        service.update_task(conn, t_arch, {"archived": True}, source="test")
        service.update_status(conn, c_arch, {"archived": True})
        # default: archived status hidden; its (archived) task also hidden
        view = service.get_workspace_list_view(conn, bid)
        assert [c.status.id for c in view.statuses] == [c_active]
        # include_archived: archived status and its task appear
        view_all = service.get_workspace_list_view(conn, bid, include_archived=True)
        cols_by_id = {c.status.id: c for c in view_all.statuses}
        assert c_active in cols_by_id
        assert c_arch in cols_by_id
        assert len(cols_by_id[c_arch].tasks) == 1
        assert cols_by_id[c_arch].tasks[0].title == "arch-task"

    def test_filter_by_status_id(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        c_todo = insert_status(conn, bid, "todo")
        c_done = insert_status(conn, bid, "done")
        insert_task(conn, bid, "in-todo", c_todo)
        insert_task(conn, bid, "in-done", c_done)
        view = service.get_workspace_list_view(conn, bid, status_id=c_todo)
        # All statuses still present in view skeleton, but only matching
        # tasks populate. Non-matching statuses have empty tasks.
        cols_by_id = {c.status.id: c for c in view.statuses}
        assert len(cols_by_id[c_todo].tasks) == 1
        assert cols_by_id[c_todo].tasks[0].title == "in-todo"
        assert cols_by_id[c_done].tasks == ()

    def test_filter_by_project_id(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        pid = insert_project(conn, bid, "myproj")
        insert_task(conn, bid, "in-proj", cid, project_id=pid)
        insert_task(conn, bid, "no-proj", cid)
        view = service.get_workspace_list_view(conn, bid, project_id=pid)
        titles = [t.title for t in view.statuses[0].tasks]
        assert titles == ["in-proj"]

    def test_filter_by_tag_id(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "tagged", cid)
        insert_task(conn, bid, "untagged", cid)
        tag = insert_tag(conn, bid, "bug")
        insert_task_tag(conn, t1, tag)
        view = service.get_workspace_list_view(conn, bid, tag_id=tag)
        titles = [t.title for t in view.statuses[0].tasks]
        assert titles == ["tagged"]

    def test_filter_by_priority(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        insert_task(conn, bid, "low", cid, priority=1)
        insert_task(conn, bid, "high", cid, priority=5)
        view = service.get_workspace_list_view(conn, bid, priority=5)
        titles = [t.title for t in view.statuses[0].tasks]
        assert titles == ["high"]

    def test_missing_workspace_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_workspace_list_view(conn, 9999)


# ---- Workspace context ----


class TestGetWorkspaceContext:
    def test_empty_workspace(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn, "ctx-workspace")
        ctx = service.get_workspace_context(conn, bid)
        assert isinstance(ctx, WorkspaceContext)
        assert ctx.view.workspace.id == bid
        assert ctx.projects == ()
        assert ctx.tags == ()
        assert ctx.groups == ()

    def test_includes_projects(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        insert_project(conn, bid, "alpha")
        insert_project(conn, bid, "beta")
        ctx = service.get_workspace_context(conn, bid)
        names = {p.name for p in ctx.projects}
        assert names == {"alpha", "beta"}

    def test_includes_tags(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        insert_tag(conn, bid, "bug")
        ctx = service.get_workspace_context(conn, bid)
        assert len(ctx.tags) == 1
        assert ctx.tags[0].name == "bug"

    def test_includes_groups(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        pid = insert_project(conn, bid, "proj")
        grp = service.create_group(conn, pid, "sprint-1")
        ctx = service.get_workspace_context(conn, bid)
        assert len(ctx.groups) == 1
        assert ctx.groups[0].id == grp.id
        assert ctx.groups[0].title == "sprint-1"

    def test_groups_from_multiple_projects(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        p1 = insert_project(conn, bid, "p1")
        p2 = insert_project(conn, bid, "p2")
        service.create_group(conn, p1, "g1")
        service.create_group(conn, p2, "g2")
        ctx = service.get_workspace_context(conn, bid)
        assert len(ctx.groups) == 2
        titles = {g.title for g in ctx.groups}
        assert titles == {"g1", "g2"}

    def test_archived_excluded(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        pid = insert_project(conn, bid, "proj")
        insert_tag(conn, bid, "tag1")
        service.create_group(conn, pid, "grp")
        # archive all three via raw SQL
        conn.execute("UPDATE projects SET archived=1 WHERE id=?", (pid,))
        conn.execute("UPDATE tags SET archived=1 WHERE workspace_id=?", (bid,))
        conn.execute("UPDATE groups SET archived=1 WHERE project_id=?", (pid,))
        conn.commit()
        ctx = service.get_workspace_context(conn, bid)
        assert ctx.projects == ()
        assert ctx.tags == ()
        assert ctx.groups == ()

    def test_missing_workspace_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_workspace_context(conn, 9999)


# ---- Archive preview + cascade ----


class TestArchivePreviewAndCascade:
    def _setup_full(self, conn: sqlite3.Connection) -> tuple[int, int, int, int, int, int]:
        """Create workspace with 2 statuses, 1 project, 2 groups (parent+child), 2 tasks."""
        bid = insert_workspace(conn)
        cid1 = insert_status(conn, bid, "todo")
        cid2 = insert_status(conn, bid, "done")
        pid = insert_project(conn, bid, "proj")
        g1 = insert_group(conn, pid, "parent")
        g2 = insert_group(conn, pid, "child", parent_id=g1)
        t1 = insert_task(conn, bid, "t1", cid1, project_id=pid)
        t2 = insert_task(conn, bid, "t2", cid2, project_id=pid)
        service.assign_task_to_group(conn, t1, g1, source="test")
        service.assign_task_to_group(conn, t2, g2, source="test")
        return bid, pid, g1, g2, t1, t2

    # ---- Preview correctness ----

    def test_preview_archive_task(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        tid = insert_task(conn, bid, "t", cid)
        preview = service.preview_archive_task(conn, tid)
        assert preview.entity_type == "task"
        assert preview.already_archived is False
        assert preview.task_count == 0
        assert preview.group_count == 0

    def test_preview_archive_task_already_archived(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        tid = insert_task(conn, bid, "t", cid)
        service.archive_task(conn, tid, source="test")
        preview = service.preview_archive_task(conn, tid)
        assert preview.already_archived is True
        assert preview.task_count == 0

    def test_preview_archive_group(self, conn: sqlite3.Connection) -> None:
        bid, pid, g1, g2, t1, t2 = self._setup_full(conn)
        preview = service.preview_archive_group(conn, g1)
        assert preview.entity_type == "group"
        assert preview.group_count == 1  # child group
        assert preview.task_count == 2   # both tasks

    def test_preview_archive_project(self, conn: sqlite3.Connection) -> None:
        bid, pid, g1, g2, t1, t2 = self._setup_full(conn)
        preview = service.preview_archive_project(conn, pid)
        assert preview.entity_type == "project"
        assert preview.group_count == 2
        assert preview.task_count == 2

    def test_preview_archive_workspace(self, conn: sqlite3.Connection) -> None:
        bid, pid, g1, g2, t1, t2 = self._setup_full(conn)
        preview = service.preview_archive_workspace(conn, bid)
        assert preview.entity_type == "workspace"
        assert preview.project_count == 1
        assert preview.group_count == 2
        assert preview.status_count == 2
        assert preview.task_count == 2

    # ---- Cascade correctness ----

    def test_cascade_archive_group_archives_all(self, conn: sqlite3.Connection) -> None:
        bid, pid, g1, g2, t1, t2 = self._setup_full(conn)
        service.cascade_archive_group(conn, g1, source="test")
        assert service.get_group(conn, g1).archived is True
        assert service.get_group(conn, g2).archived is True
        assert service.get_task(conn, t1).archived is True
        assert service.get_task(conn, t2).archived is True

    def test_cascade_archive_project_archives_all(self, conn: sqlite3.Connection) -> None:
        bid, pid, g1, g2, t1, t2 = self._setup_full(conn)
        service.cascade_archive_project(conn, pid, source="test")
        assert service.get_project(conn, pid).archived is True
        assert service.get_group(conn, g1).archived is True
        assert service.get_group(conn, g2).archived is True
        assert service.get_task(conn, t1).archived is True
        assert service.get_task(conn, t2).archived is True

    def test_cascade_archive_workspace_archives_all(self, conn: sqlite3.Connection) -> None:
        bid, pid, g1, g2, t1, t2 = self._setup_full(conn)
        service.cascade_archive_workspace(conn, bid, source="test")
        assert service.get_workspace(conn, bid).archived is True
        assert service.get_project(conn, pid).archived is True
        assert service.get_group(conn, g1).archived is True
        assert service.get_task(conn, t1).archived is True
        # All statuses archived
        from sticky_notes import repository as repo
        statuses = repo.list_statuses(conn, bid, include_archived=True)
        assert all(s.archived for s in statuses)

    # ---- Cascade history recording ----

    def test_cascade_archive_group_records_history(self, conn: sqlite3.Connection) -> None:
        bid, pid, g1, g2, t1, t2 = self._setup_full(conn)
        service.cascade_archive_group(conn, g1, source="test")
        for tid in (t1, t2):
            history = service.list_task_history(conn, tid)
            archived_entries = [h for h in history if h.field.value == "archived"]
            assert len(archived_entries) == 1
            assert archived_entries[0].old_value == "False"
            assert archived_entries[0].new_value == "True"
            assert archived_entries[0].source == "test"

    def test_cascade_archive_project_records_history(self, conn: sqlite3.Connection) -> None:
        bid, pid, g1, g2, t1, t2 = self._setup_full(conn)
        service.cascade_archive_project(conn, pid, source="test")
        for tid in (t1, t2):
            history = service.list_task_history(conn, tid)
            archived_entries = [h for h in history if h.field.value == "archived"]
            assert len(archived_entries) == 1

    def test_cascade_archive_workspace_records_history(self, conn: sqlite3.Connection) -> None:
        bid, pid, g1, g2, t1, t2 = self._setup_full(conn)
        service.cascade_archive_workspace(conn, bid, source="test")
        for tid in (t1, t2):
            history = service.list_task_history(conn, tid)
            archived_entries = [h for h in history if h.field.value == "archived"]
            assert len(archived_entries) == 1

    # ---- Dep re-creation after archive ----

    def test_readd_dependency_after_archive(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_dependency(conn, t2, t1)
        service.archive_dependency(conn, t2, t1)
        service.add_dependency(conn, t2, t1)  # should not crash
        detail = service.get_task_detail(conn, t2)
        assert len(detail.blocked_by) == 1

    def test_readd_group_dependency_after_archive(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        pid = insert_project(conn, bid, "p")
        g1 = insert_group(conn, pid, "g1")
        g2 = insert_group(conn, pid, "g2")
        service.add_group_dependency(conn, g1, g2)
        service.archive_group_dependency(conn, g1, g2)
        service.add_group_dependency(conn, g1, g2)  # should not crash
        deps = service.list_all_group_dependencies(conn)
        assert (g1, g2) in deps


# ---- Task metadata ----


class TestTaskMeta:
    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int]:
        bid = insert_workspace(conn, "w")
        sid = insert_status(conn, bid, "todo")
        tid = insert_task(conn, bid, "task1", sid)
        return bid, tid

    def test_set_meta(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        task = service.set_task_meta(conn, tid, "branch", "feat/kv")
        assert task.metadata == {"branch": "feat/kv"}

    def test_set_meta_overwrite(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        service.set_task_meta(conn, tid, "branch", "feat/old")
        task = service.set_task_meta(conn, tid, "branch", "feat/new")
        assert task.metadata["branch"] == "feat/new"

    def test_remove_meta(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        service.set_task_meta(conn, tid, "branch", "feat/kv")
        task = service.remove_task_meta(conn, tid, "branch")
        assert task.metadata == {}

    def test_remove_nonexistent_key_raises(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        with pytest.raises(LookupError, match="not found"):
            service.remove_task_meta(conn, tid, "nope")

    def test_key_validation_empty(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        with pytest.raises(ValueError, match="1-64 characters"):
            service.set_task_meta(conn, tid, "", "v")

    def test_key_validation_too_long(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        with pytest.raises(ValueError, match="1-64 characters"):
            service.set_task_meta(conn, tid, "k" * 65, "v")

    def test_key_validation_bad_chars(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        with pytest.raises(ValueError, match="must match"):
            service.set_task_meta(conn, tid, "BAD KEY", "v")

    def test_value_validation_too_long(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        with pytest.raises(ValueError, match="500"):
            service.set_task_meta(conn, tid, "k", "v" * 501)

    def test_metadata_survives_task_update(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        service.set_task_meta(conn, tid, "branch", "feat/kv")
        service.update_task(conn, tid, {"title": "new title"}, "test")
        task = service.get_task(conn, tid)
        assert task.metadata == {"branch": "feat/kv"}

    def test_move_task_to_workspace_copies_metadata(self, conn: sqlite3.Connection) -> None:
        bid1, tid = self._setup(conn)
        service.set_task_meta(conn, tid, "branch", "feat/kv")
        service.set_task_meta(conn, tid, "jira", "PROJ-1")
        bid2 = insert_workspace(conn, "w2")
        sid2 = insert_status(conn, bid2, "todo")
        new_task = service.move_task_to_workspace(conn, tid, bid2, sid2, source="test")
        assert new_task.metadata == {"branch": "feat/kv", "jira": "PROJ-1"}
