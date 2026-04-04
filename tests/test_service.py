from __future__ import annotations

import sqlite3

import pytest

from sticky_notes.models import Board, Column, Group, Project, Tag, Task, TaskFilter, TaskHistory
from sticky_notes.service_models import GroupDetail, GroupRef, ProjectDetail, ProjectRef, TaskDetail, TaskRef
from tests.helpers import (
    insert_board as _raw_insert_board,
    insert_column as _raw_insert_column,
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


def insert_board(conn: sqlite3.Connection, name: str = "board1") -> int:
    rid = _raw_insert_board(conn, name)
    _commit(conn)
    return rid


def insert_column(
    conn: sqlite3.Connection, board_id: int, name: str = "todo", position: int = 0
) -> int:
    rid = _raw_insert_column(conn, board_id, name, position)
    _commit(conn)
    return rid


def insert_project(
    conn: sqlite3.Connection, board_id: int, name: str = "proj1", description: str | None = "desc"
) -> int:
    rid = _raw_insert_project(conn, board_id, name, description)
    _commit(conn)
    return rid


def insert_task(
    conn: sqlite3.Connection,
    board_id: int,
    title: str,
    column_id: int,
    project_id: int | None = None,
    priority: int = 1,
    due_date: int | None = None,
) -> int:
    rid = _raw_insert_task(conn, board_id, title, column_id, project_id, priority, due_date)
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
    conn: sqlite3.Connection, board_id: int, name: str = "tag1"
) -> int:
    rid = _raw_insert_tag(conn, board_id, name)
    _commit(conn)
    return rid


def insert_task_tag(
    conn: sqlite3.Connection, task_id: int, tag_id: int
) -> None:
    _raw_insert_task_tag(conn, task_id, tag_id)
    _commit(conn)


# ---- Board ----


class TestBoardService:
    def test_create(self, conn: sqlite3.Connection) -> None:
        board = service.create_board(conn, "work")
        assert isinstance(board, Board)
        assert board.name == "work"
        assert board.archived is False

    def test_create_duplicate_raises(self, conn: sqlite3.Connection) -> None:
        service.create_board(conn, "work")
        with pytest.raises(ValueError, match="board with this name already exists"):
            service.create_board(conn, "work")

    def test_get(self, conn: sqlite3.Connection) -> None:
        board = service.create_board(conn, "work")
        assert service.get_board(conn, board.id) == board

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_board(conn, 999)

    def test_get_by_name(self, conn: sqlite3.Connection) -> None:
        board = service.create_board(conn, "work")
        assert service.get_board_by_name(conn, "work") == board

    def test_get_by_name_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_board_by_name(conn, "nope")

    def test_list(self, conn: sqlite3.Connection) -> None:
        b1 = service.create_board(conn, "a")
        b2 = service.create_board(conn, "b")
        assert service.list_boards(conn) == (b1, b2)

    def test_list_excludes_archived(self, conn: sqlite3.Connection) -> None:
        b1 = service.create_board(conn, "a")
        service.create_board(conn, "b")
        service.update_board(conn, b1.id, {"archived": True})
        active = service.list_boards(conn)
        assert len(active) == 1
        assert active[0].name == "b"

    def test_list_include_archived(self, conn: sqlite3.Connection) -> None:
        service.create_board(conn, "a")
        service.create_board(conn, "b")
        service.update_board(conn, 1, {"archived": True})
        assert len(service.list_boards(conn, include_archived=True)) == 2

    def test_update(self, conn: sqlite3.Connection) -> None:
        board = service.create_board(conn, "old")
        updated = service.update_board(conn, board.id, {"name": "new"})
        assert updated.name == "new"

    def test_archive_board_with_active_columns_blocked(self, conn: sqlite3.Connection) -> None:
        board = service.create_board(conn, "work")
        service.create_column(conn, board.id, "todo")
        with pytest.raises(ValueError, match="active column"):
            service.update_board(conn, board.id, {"archived": True})

    def test_archive_board_with_active_projects_blocked(self, conn: sqlite3.Connection) -> None:
        board = service.create_board(conn, "work")
        service.create_project(conn, board.id, "proj")
        with pytest.raises(ValueError, match="active project"):
            service.update_board(conn, board.id, {"archived": True})

    def test_archive_empty_board_allowed(self, conn: sqlite3.Connection) -> None:
        board = service.create_board(conn, "work")
        updated = service.update_board(conn, board.id, {"archived": True})
        assert updated.archived is True


# ---- Column ----


class TestColumnService:
    def test_create(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        col = service.create_column(conn, bid, "todo")
        assert isinstance(col, Column)
        assert col.name == "todo"

    def test_get(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        col = service.create_column(conn, bid, "todo")
        assert service.get_column(conn, col.id) == col

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_column(conn, 999)

    def test_list(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        c1 = service.create_column(conn, bid, "todo", position=0)
        c2 = service.create_column(conn, bid, "done", position=1)
        assert service.list_columns(conn, bid) == (c1, c2)

    def test_get_by_name(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        col = service.create_column(conn, bid, "todo")
        assert service.get_column_by_name(conn, bid, "todo") == col

    def test_get_by_name_missing_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        with pytest.raises(LookupError, match="not found"):
            service.get_column_by_name(conn, bid, "nope")

    def test_update(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        col = service.create_column(conn, bid, "old")
        updated = service.update_column(conn, col.id, {"name": "new"})
        assert updated.name == "new"

    def test_archive_column_with_active_tasks_blocked(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        insert_task(conn, bid, "task", cid)
        with pytest.raises(ValueError, match="active task"):
            service.update_column(conn, cid, {"archived": True})

    def test_archive_empty_column_allowed(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        col = service.create_column(conn, bid, "empty")
        updated = service.update_column(conn, col.id, {"archived": True})
        assert updated.archived is True


# ---- Project ----


class TestProjectService:
    def test_create(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        proj = service.create_project(conn, bid, "alpha", description="desc")
        assert isinstance(proj, Project)
        assert proj.name == "alpha"
        assert proj.description == "desc"

    def test_get(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        proj = service.create_project(conn, bid, "alpha")
        assert service.get_project(conn, proj.id) == proj

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_project(conn, 999)

    def test_get_by_name(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        proj = service.create_project(conn, bid, "alpha")
        assert service.get_project_by_name(conn, bid, "alpha") == proj

    def test_get_by_name_missing_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        with pytest.raises(LookupError, match="not found"):
            service.get_project_by_name(conn, bid, "nope")

    def test_get_ref(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        proj = service.create_project(conn, bid, "alpha")
        t1 = insert_task(conn, bid, "t1", cid, project_id=proj.id)
        t2 = insert_task(conn, bid, "t2", cid, project_id=proj.id)
        ref = service.get_project_ref(conn, proj.id)
        assert isinstance(ref, ProjectRef)
        assert set(ref.task_ids) == {t1, t2}

    def test_get_detail(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        proj = service.create_project(conn, bid, "alpha")
        insert_task(conn, bid, "t1", cid, project_id=proj.id)
        detail = service.get_project_detail(conn, proj.id)
        assert isinstance(detail, ProjectDetail)
        assert len(detail.tasks) == 1
        assert detail.tasks[0].title == "t1"

    def test_list(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        p1 = service.create_project(conn, bid, "a")
        p2 = service.create_project(conn, bid, "b")
        assert service.list_projects(conn, bid) == (p1, p2)

    def test_update(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        proj = service.create_project(conn, bid, "old")
        updated = service.update_project(conn, proj.id, {"name": "new"})
        assert updated.name == "new"

    def test_archive_project_with_active_tasks_blocked(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        proj = service.create_project(conn, bid, "alpha")
        insert_task(conn, bid, "task", cid, project_id=proj.id)
        with pytest.raises(ValueError, match="active task"):
            service.update_project(conn, proj.id, {"archived": True})

    def test_archive_project_with_active_groups_blocked(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        proj = service.create_project(conn, bid, "alpha")
        insert_group(conn, proj.id, "g1")
        with pytest.raises(ValueError, match="active group"):
            service.update_project(conn, proj.id, {"archived": True})

    def test_archive_empty_project_allowed(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        proj = service.create_project(conn, bid, "alpha")
        updated = service.update_project(conn, proj.id, {"archived": True})
        assert updated.archived is True


# ---- Task ----


class TestTaskService:
    def test_create(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        task = service.create_task(conn, bid, "do stuff", cid)
        assert isinstance(task, Task)
        assert task.title == "do stuff"
        assert task.priority == 1

    def test_get(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        task = service.create_task(conn, bid, "do stuff", cid)
        assert service.get_task(conn, task.id) == task

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_task(conn, 999)

    def test_get_by_title(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        task = service.create_task(conn, bid, "Find me", cid)
        found = service.get_task_by_title(conn, bid, "Find me")
        assert found.id == task.id
        assert found.title == "Find me"

    def test_get_by_title_missing_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        with pytest.raises(LookupError, match="not found"):
            service.get_task_by_title(conn, bid, "nonexistent")

    def test_get_ref(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        insert_task_dependency(conn, t2, t1)
        ref = service.get_task_ref(conn, t2)
        assert isinstance(ref, TaskRef)
        assert ref.blocked_by_ids == (t1,)
        assert ref.blocks_ids == ()

    def test_get_detail(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        pid = insert_project(conn, bid)
        tid = insert_task(conn, bid, "a", cid, project_id=pid)
        detail = service.get_task_detail(conn, tid)
        assert isinstance(detail, TaskDetail)
        assert detail.column.id == cid
        assert detail.project is not None
        assert detail.project.id == pid

    def test_get_detail_no_project(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        tid = insert_task(conn, bid, "a", cid)
        detail = service.get_task_detail(conn, tid)
        assert detail.project is None

    def test_get_detail_with_deps_and_history(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        t1 = insert_task(conn, bid, "blocker", cid)
        t2 = insert_task(conn, bid, "blocked", cid)
        insert_task_dependency(conn, t2, t1)
        service.update_task(conn, t2, {"title": "renamed"}, "tui")
        detail = service.get_task_detail(conn, t2)
        assert len(detail.blocked_by) == 1
        assert detail.blocked_by[0].id == t1
        assert len(detail.history) == 1

    def test_list(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        service.create_task(conn, bid, "a", cid)
        service.create_task(conn, bid, "b", cid)
        tasks = service.list_tasks(conn, bid)
        assert len(tasks) == 2

    def test_list_refs(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        insert_task_dependency(conn, t2, t1)
        refs = service.list_task_refs(conn, bid)
        assert len(refs) == 2
        assert all(isinstance(r, TaskRef) for r in refs)
        ref_map = {r.id: r for r in refs}
        assert ref_map[t1].blocks_ids == (t2,)
        assert ref_map[t2].blocked_by_ids == (t1,)

    def test_update(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        task = service.create_task(conn, bid, "old", cid)
        updated = service.update_task(conn, task.id, {"title": "new"}, "tui")
        assert updated.title == "new"

    def test_update_records_history(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        task = service.create_task(conn, bid, "old", cid)
        service.update_task(conn, task.id, {"title": "new"}, "tui")
        history = service.list_task_history(conn, task.id)
        assert len(history) == 1
        assert history[0].field == "title"
        assert history[0].old_value == "old"
        assert history[0].new_value == "new"
        assert history[0].source == "tui"

    def test_update_skips_history_when_unchanged(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        task = service.create_task(conn, bid, "same", cid)
        service.update_task(conn, task.id, {"title": "same"}, "tui")
        history = service.list_task_history(conn, task.id)
        assert len(history) == 0

    def test_update_multiple_fields_records_multiple_history(
        self, conn: sqlite3.Connection
    ) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        task = service.create_task(conn, bid, "old", cid, priority=1)
        service.update_task(conn, task.id, {"title": "new", "priority": 5}, "mcp")
        history = service.list_task_history(conn, task.id)
        assert len(history) == 2
        fields = {h.field for h in history}
        assert fields == {"title", "priority"}

    def test_update_none_old_value_stored_as_null(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        assert task.description is None
        service.update_task(conn, task.id, {"description": "added"}, "tui")
        history = service.list_task_history(conn, task.id)
        assert len(history) == 1
        assert history[0].old_value is None
        assert history[0].new_value == "added"

    def test_move_task(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        c1 = insert_column(conn, bid, "todo", 0)
        c2 = insert_column(conn, bid, "done", 1)
        task = service.create_task(conn, bid, "t", c1)
        moved = service.move_task(conn, task.id, c2, 0, "tui")
        assert moved.column_id == c2
        history = service.list_task_history(conn, task.id)
        assert any(h.field == "column_id" for h in history)

    # ---- Pre-validation ----

    def test_create_priority_too_low(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        with pytest.raises(ValueError, match="priority"):
            service.create_task(conn, bid, "t", cid, priority=0)

    def test_create_priority_too_high(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        with pytest.raises(ValueError, match="priority"):
            service.create_task(conn, bid, "t", cid, priority=6)

    def test_create_negative_position(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        with pytest.raises(ValueError, match="position"):
            service.create_task(conn, bid, "t", cid, position=-1)

    def test_create_finish_before_start(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        with pytest.raises(ValueError, match="finish date"):
            service.create_task(conn, bid, "t", cid, start_date=200, finish_date=100)

    def test_update_priority_out_of_range(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        with pytest.raises(ValueError, match="priority"):
            service.update_task(conn, task.id, {"priority": 0}, "test")

    def test_update_negative_position(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        with pytest.raises(ValueError, match="position"):
            service.update_task(conn, task.id, {"position": -1}, "test")

    def test_update_finish_before_existing_start(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        task = service.create_task(conn, bid, "t", cid, start_date=200)
        with pytest.raises(ValueError, match="finish date"):
            service.update_task(conn, task.id, {"finish_date": 100}, "test")

    def test_update_start_after_existing_finish(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        task = service.create_task(conn, bid, "t", cid, finish_date=100)
        with pytest.raises(ValueError, match="finish date"):
            service.update_task(conn, task.id, {"start_date": 200}, "test")

    def test_update_column_wrong_board(self, conn: sqlite3.Connection) -> None:
        b1 = insert_board(conn, "board1")
        b2 = insert_board(conn, "board2")
        c1 = insert_column(conn, b1, "todo")
        c2 = insert_column(conn, b2, "done")
        task = service.create_task(conn, b1, "t", c1)
        with pytest.raises(ValueError, match="board"):
            service.update_task(conn, task.id, {"column_id": c2}, "test")

    def test_update_project_wrong_board(self, conn: sqlite3.Connection) -> None:
        b1 = insert_board(conn, "board1")
        b2 = insert_board(conn, "board2")
        c1 = insert_column(conn, b1)
        insert_column(conn, b2)
        p2 = insert_project(conn, b2, "proj2")
        task = service.create_task(conn, b1, "t", c1)
        with pytest.raises(ValueError, match="board"):
            service.update_task(conn, task.id, {"project_id": p2}, "test")

    def test_update_column_not_found(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        with pytest.raises(LookupError, match="column 999"):
            service.update_task(conn, task.id, {"column_id": 999}, "test")

    def test_update_project_not_found(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        with pytest.raises(LookupError, match="project 999"):
            service.update_task(conn, task.id, {"project_id": 999}, "test")

    # ---- Archival safety ----

    def test_move_to_archived_column_blocked(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        c1 = insert_column(conn, bid, "active")
        c2 = insert_column(conn, bid, "archived")
        service.update_column(conn, c2, {"archived": True})
        task = service.create_task(conn, bid, "t", c1)
        with pytest.raises(ValueError, match="archived"):
            service.update_task(conn, task.id, {"column_id": c2}, "test")

    def test_assign_to_archived_project_blocked(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        proj = service.create_project(conn, bid, "old")
        service.update_project(conn, proj.id, {"archived": True})
        task = service.create_task(conn, bid, "t", cid)
        with pytest.raises(ValueError, match="archived"):
            service.update_task(conn, task.id, {"project_id": proj.id}, "test")

    def test_assign_to_archived_group_blocked(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        pid = insert_project(conn, bid)
        gid = insert_group(conn, pid, "g1")
        service.archive_group(conn, gid)
        tid = insert_task(conn, bid, "t", cid)
        with pytest.raises(ValueError, match="archived"):
            service.assign_task_to_group(conn, tid, gid)


# ---- Dependency ----


class TestDependencyService:
    def test_add(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_dependency(conn, t2, t1)
        ref = service.get_task_ref(conn, t2)
        assert ref.blocked_by_ids == (t1,)

    def test_remove(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_dependency(conn, t2, t1)
        service.remove_dependency(conn, t2, t1)
        ref = service.get_task_ref(conn, t2)
        assert ref.blocked_by_ids == ()

    def test_add_self_ref_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        tid = insert_task(conn, bid, "a", cid)
        with pytest.raises(ValueError, match="cannot depend on itself"):
            service.add_dependency(conn, tid, tid)

    def test_add_cross_board_raises(self, conn: sqlite3.Connection) -> None:
        b1 = insert_board(conn, "board1")
        b2 = insert_board(conn, "board2")
        c1 = insert_column(conn, b1)
        c2 = insert_column(conn, b2)
        t1 = insert_task(conn, b1, "a", c1)
        t2 = insert_task(conn, b2, "b", c2)
        with pytest.raises(ValueError, match="same board"):
            service.add_dependency(conn, t2, t1)

    def test_cycle_direct(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_dependency(conn, t1, t2)  # t1 -> t2
        with pytest.raises(ValueError, match="cycle"):
            service.add_dependency(conn, t2, t1)  # t2 -> t1 would cycle

    def test_cycle_transitive(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        t3 = insert_task(conn, bid, "c", cid)
        service.add_dependency(conn, t1, t2)  # t1 -> t2
        service.add_dependency(conn, t2, t3)  # t2 -> t3
        with pytest.raises(ValueError, match="cycle"):
            service.add_dependency(conn, t3, t1)  # t3 -> t1 would cycle

    def test_non_cycle_allowed(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        t3 = insert_task(conn, bid, "c", cid)
        service.add_dependency(conn, t1, t2)  # t1 -> t2
        service.add_dependency(conn, t1, t3)  # t1 -> t3 (diamond, not cycle)
        service.add_dependency(conn, t2, t3)  # t2 -> t3 (converge, not cycle)
        ref = service.get_task_ref(conn, t1)
        assert set(ref.blocked_by_ids) == {t2, t3}

    def test_add_duplicate_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_dependency(conn, t1, t2)
        with pytest.raises(ValueError, match="already depends"):
            service.add_dependency(conn, t1, t2)


# ---- History ----


class TestHistoryService:
    def test_list(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        service.update_task(conn, task.id, {"title": "new"}, "tui")
        history = service.list_task_history(conn, task.id)
        assert len(history) == 1
        assert isinstance(history[0], TaskHistory)


# ---- Filtered listing ----


class TestListTaskRefsFiltered:
    def test_no_filter_returns_all(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        insert_task(conn, bid, "a", cid)
        insert_task(conn, bid, "b", cid)
        refs = service.list_task_refs_filtered(conn, bid)
        assert len(refs) == 2
        assert all(isinstance(r, TaskRef) for r in refs)

    def test_filter_by_column(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        c1 = insert_column(conn, bid, "todo", 0)
        c2 = insert_column(conn, bid, "done", 1)
        insert_task(conn, bid, "a", c1)
        insert_task(conn, bid, "b", c2)
        refs = service.list_task_refs_filtered(conn, bid, task_filter=TaskFilter(column_id=c1))
        assert len(refs) == 1
        assert refs[0].title == "a"

    def test_filter_by_priority(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        insert_task(conn, bid, "low", cid, priority=1)
        insert_task(conn, bid, "high", cid, priority=3)
        refs = service.list_task_refs_filtered(conn, bid, task_filter=TaskFilter(priority=3))
        assert len(refs) == 1
        assert refs[0].title == "high"

    def test_filter_with_dependencies(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        insert_task_dependency(conn, t2, t1)
        refs = service.list_task_refs_filtered(conn, bid)
        ref_map = {r.id: r for r in refs}
        assert ref_map[t2].blocked_by_ids == (t1,)
        assert ref_map[t1].blocks_ids == (t2,)

    def test_filter_by_search(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        insert_task(conn, bid, "Fix login", cid)
        insert_task(conn, bid, "Add search", cid)
        refs = service.list_task_refs_filtered(conn, bid, task_filter=TaskFilter(search="login"))
        assert len(refs) == 1
        assert refs[0].title == "Fix login"


# ---- Move task to board ----


class TestMoveTaskToBoard:
    def test_happy_path(self, conn: sqlite3.Connection) -> None:
        b1 = insert_board(conn, "board1")
        c1 = insert_column(conn, b1, "todo")
        tid = insert_task(conn, b1, "my task", c1, priority=3)

        b2 = insert_board(conn, "board2")
        c2 = insert_column(conn, b2, "backlog")

        new = service.move_task_to_board(conn, tid, b2, c2, source="test")
        assert new.board_id == b2
        assert new.column_id == c2
        assert new.title == "my task"
        assert new.priority == 3
        assert new.archived == 0

        old = service.get_task(conn, tid)
        assert old.archived == 1

    def test_with_project(self, conn: sqlite3.Connection) -> None:
        b1 = insert_board(conn, "board1")
        c1 = insert_column(conn, b1, "todo")
        tid = insert_task(conn, b1, "task", c1)

        b2 = insert_board(conn, "board2")
        c2 = insert_column(conn, b2, "backlog")
        pid = insert_project(conn, b2, "proj")

        new = service.move_task_to_board(conn, tid, b2, c2, project_id=pid, source="test")
        assert new.project_id == pid

    def test_title_conflict(self, conn: sqlite3.Connection) -> None:
        b1 = insert_board(conn, "board1")
        c1 = insert_column(conn, b1, "todo")
        insert_task(conn, b1, "dup", c1)

        b2 = insert_board(conn, "board2")
        c2 = insert_column(conn, b2, "backlog")
        insert_task(conn, b2, "dup", c2)

        t1 = service.get_task_by_title(conn, b1, "dup")
        with pytest.raises(ValueError, match="task with this title already exists"):
            service.move_task_to_board(conn, t1.id, b2, c2, source="test")

    def test_blocked_by_deps(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        t1 = insert_task(conn, bid, "blocker", cid)
        t2 = insert_task(conn, bid, "blocked", cid)
        insert_task_dependency(conn, t2, t1)

        b2 = insert_board(conn, "board2")
        c2 = insert_column(conn, b2, "backlog")

        with pytest.raises(ValueError, match="dependencies"):
            service.move_task_to_board(conn, t2, b2, c2, source="test")

    def test_blocks_deps(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        t1 = insert_task(conn, bid, "blocker", cid)
        t2 = insert_task(conn, bid, "blocked", cid)
        insert_task_dependency(conn, t2, t1)

        b2 = insert_board(conn, "board2")
        c2 = insert_column(conn, b2, "backlog")

        with pytest.raises(ValueError, match="dependencies"):
            service.move_task_to_board(conn, t1, b2, c2, source="test")

    def test_archived_task(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        tid = insert_task(conn, bid, "task", cid)
        service.update_task(conn, tid, {"archived": True}, source="test")

        b2 = insert_board(conn, "board2")
        c2 = insert_column(conn, b2, "backlog")

        with pytest.raises(ValueError, match="archived"):
            service.move_task_to_board(conn, tid, b2, c2, source="test")

    def test_column_wrong_board(self, conn: sqlite3.Connection) -> None:
        b1 = insert_board(conn, "board1")
        c1 = insert_column(conn, b1, "todo")
        tid = insert_task(conn, b1, "task", c1)

        b2 = insert_board(conn, "board2")
        insert_column(conn, b2, "backlog")

        with pytest.raises(ValueError, match="does not belong"):
            service.move_task_to_board(conn, tid, b2, c1, source="test")

    def test_project_wrong_board(self, conn: sqlite3.Connection) -> None:
        b1 = insert_board(conn, "board1")
        c1 = insert_column(conn, b1, "todo")
        p1 = insert_project(conn, b1, "proj1")
        tid = insert_task(conn, b1, "task", c1)

        b2 = insert_board(conn, "board2")
        c2 = insert_column(conn, b2, "backlog")

        with pytest.raises(ValueError, match="does not belong"):
            service.move_task_to_board(conn, tid, b2, c2, project_id=p1, source="test")

    def test_copies_dates(self, conn: sqlite3.Connection) -> None:
        b1 = insert_board(conn, "board1")
        c1 = insert_column(conn, b1, "todo")
        task = service.create_task(
            conn, b1, "dated", c1,
            due_date=1700000000, start_date=1699000000, finish_date=1701000000,
        )

        b2 = insert_board(conn, "board2")
        c2 = insert_column(conn, b2, "backlog")

        new = service.move_task_to_board(conn, task.id, b2, c2, source="test")
        assert new.due_date == 1700000000
        assert new.start_date == 1699000000
        assert new.finish_date == 1701000000


# ---- Group ----


class TestGroupService:
    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int, int]:
        """Returns (board_id, column_id, project_id)."""
        bid = insert_board(conn, "board1")
        cid = insert_column(conn, bid, "todo")
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

    def test_list_groups(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        service.create_group(conn, pid, "g1")
        service.create_group(conn, pid, "g2")
        refs = service.list_groups(conn, pid)
        assert len(refs) == 2
        assert all(isinstance(r, GroupRef) for r in refs)

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

    def test_archive_orphans_tasks(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        tid = insert_task(conn, bid, "t", cid, project_id=pid)
        service.assign_task_to_group(conn, tid, grp.id)
        service.archive_group(conn, grp.id)
        assert service.get_task(conn, tid).group_id is None

    def test_archive_reparents_children(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        parent = service.create_group(conn, pid, "parent")
        mid = service.create_group(conn, pid, "mid", parent_id=parent.id)
        child = service.create_group(conn, pid, "child", parent_id=mid.id)
        service.archive_group(conn, mid.id)
        refreshed_child = service.get_group(conn, child.id)
        assert refreshed_child.parent_id == parent.id

    def test_archive_group_is_archived(self, conn: sqlite3.Connection) -> None:
        _, _, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        service.archive_group(conn, grp.id)
        assert service.get_group(conn, grp.id).archived is True

    def test_get_group_detail(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        parent = service.create_group(conn, pid, "parent")
        child = service.create_group(conn, pid, "child", parent_id=parent.id)
        tid = insert_task(conn, bid, "t", cid, project_id=pid)
        service.assign_task_to_group(conn, tid, parent.id)
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


class TestTaskGroupAssignment:
    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int, int]:
        bid = insert_board(conn, "board1")
        cid = insert_column(conn, bid, "todo")
        pid = insert_project(conn, bid, "proj1")
        return bid, cid, pid

    def test_assign_task(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        tid = insert_task(conn, bid, "t", cid, project_id=pid)
        service.assign_task_to_group(conn, tid, grp.id)
        assert service.get_task(conn, tid).group_id == grp.id

    def test_assign_auto_sets_project_id(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        tid = insert_task(conn, bid, "t", cid)  # no project_id
        service.assign_task_to_group(conn, tid, grp.id)
        updated = service.get_task(conn, tid)
        assert updated.project_id == pid

    def test_assign_cross_project_raises(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid1 = self._setup(conn)
        pid2 = insert_project(conn, bid, "proj2")
        grp = service.create_group(conn, pid1, "g")
        tid = insert_task(conn, bid, "t", cid, project_id=pid2)
        with pytest.raises(ValueError, match="project"):
            service.assign_task_to_group(conn, tid, grp.id)

    def test_unassign_task(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        tid = insert_task(conn, bid, "t", cid, project_id=pid)
        service.assign_task_to_group(conn, tid, grp.id)
        service.unassign_task_from_group(conn, tid)
        assert service.get_task(conn, tid).group_id is None


class TestTaskGroupHistory:
    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int, int]:
        bid = insert_board(conn, "board1")
        cid = insert_column(conn, bid, "todo")
        pid = insert_project(conn, bid, "proj1")
        return bid, cid, pid

    def test_assign_records_history(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        tid = insert_task(conn, bid, "t", cid, project_id=pid)
        service.assign_task_to_group(conn, tid, grp.id)
        history = service.list_task_history(conn, tid)
        group_entries = [h for h in history if h.field.value == "group_id"]
        assert len(group_entries) == 1
        assert group_entries[0].old_value is None
        assert group_entries[0].new_value == str(grp.id)
        assert group_entries[0].source == "assign_task_to_group"

    def test_reassign_records_old_and_new(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        g1 = service.create_group(conn, pid, "g1")
        g2 = service.create_group(conn, pid, "g2")
        tid = insert_task(conn, bid, "t", cid, project_id=pid)
        service.assign_task_to_group(conn, tid, g1.id)
        service.assign_task_to_group(conn, tid, g2.id)
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
        service.assign_task_to_group(conn, tid, grp.id)
        service.unassign_task_from_group(conn, tid)
        history = service.list_task_history(conn, tid)
        group_entries = [h for h in history if h.field.value == "group_id"]
        assert len(group_entries) == 2
        # newest first
        unassign = group_entries[0]
        assert unassign.old_value == str(grp.id)
        assert unassign.new_value is None
        assert unassign.source == "unassign_task_from_group"

    def test_unassign_no_op_no_history(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        tid = insert_task(conn, bid, "t", cid, project_id=pid)
        service.unassign_task_from_group(conn, tid)
        history = service.list_task_history(conn, tid)
        assert not [h for h in history if h.field.value == "group_id"]

    def test_archive_group_records_history(self, conn: sqlite3.Connection) -> None:
        bid, cid, pid = self._setup(conn)
        grp = service.create_group(conn, pid, "g")
        t1 = insert_task(conn, bid, "t1", cid, project_id=pid)
        t2 = insert_task(conn, bid, "t2", cid, project_id=pid)
        service.assign_task_to_group(conn, t1, grp.id)
        service.assign_task_to_group(conn, t2, grp.id)
        service.archive_group(conn, grp.id)
        for tid in (t1, t2):
            history = service.list_task_history(conn, tid)
            group_entries = [h for h in history if h.field.value == "group_id"]
            archive_entry = [h for h in group_entries if h.source == "archive_group"]
            assert len(archive_entry) == 1
            assert archive_entry[0].old_value == str(grp.id)
            assert archive_entry[0].new_value is None


# ---- Tag ----


class TestTagService:
    def test_create_tag(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        tag = service.create_tag(conn, bid, "bug")
        assert isinstance(tag, Tag)
        assert tag.name == "bug"
        assert tag.board_id == bid
        assert tag.archived is False

    def test_create_tag_duplicate_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        service.create_tag(conn, bid, "bug")
        with pytest.raises(ValueError, match="tag with this name already exists"):
            service.create_tag(conn, bid, "bug")

    def test_get_tag(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        tag = service.create_tag(conn, bid, "bug")
        assert service.get_tag(conn, tag.id) == tag

    def test_get_tag_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_tag(conn, 999)

    def test_get_tag_by_name(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        tag = service.create_tag(conn, bid, "bug")
        assert service.get_tag_by_name(conn, bid, "bug") == tag

    def test_get_tag_by_name_missing_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        with pytest.raises(LookupError, match="not found"):
            service.get_tag_by_name(conn, bid, "nope")

    def test_list_tags(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        service.create_tag(conn, bid, "bug")
        service.create_tag(conn, bid, "feature")
        tags = service.list_tags(conn, bid)
        assert len(tags) == 2
        assert tags[0].name == "bug"
        assert tags[1].name == "feature"

    def test_list_tags_excludes_archived(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        tag = service.create_tag(conn, bid, "old")
        service.create_tag(conn, bid, "active")
        service.archive_tag(conn, tag.id)
        tags = service.list_tags(conn, bid)
        assert len(tags) == 1
        assert tags[0].name == "active"

    def test_list_tags_include_archived(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        tag = service.create_tag(conn, bid, "old")
        service.create_tag(conn, bid, "active")
        service.archive_tag(conn, tag.id)
        tags = service.list_tags(conn, bid, include_archived=True)
        assert len(tags) == 2

    def test_archive_tag(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        tag = service.create_tag(conn, bid, "bug")
        archived = service.archive_tag(conn, tag.id)
        assert archived.archived is True
        assert archived.id == tag.id

    def test_tag_task(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        tid = insert_task(conn, bid, "t", cid)
        tag = service.tag_task(conn, tid, "bug", bid)
        assert isinstance(tag, Tag)
        assert tag.name == "bug"
        ref = service.get_task_ref(conn, tid)
        assert tag.id in ref.tag_ids

    def test_tag_task_duplicate_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        tid = insert_task(conn, bid, "t", cid)
        service.tag_task(conn, tid, "bug", bid)
        with pytest.raises(ValueError, match="already has this tag"):
            service.tag_task(conn, tid, "bug", bid)

    def test_tag_task_creates_tag(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        tid = insert_task(conn, bid, "t", cid)
        tag = service.tag_task(conn, tid, "newlabel", bid)
        assert service.get_tag_by_name(conn, bid, "newlabel") == tag

    def test_tag_task_missing_task_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        with pytest.raises(LookupError):
            service.tag_task(conn, 9999, "bug", bid)

    def test_tag_task_cross_board_raises(self, conn: sqlite3.Connection) -> None:
        b1 = insert_board(conn, "board1")
        b2 = insert_board(conn, "board2")
        c1 = insert_column(conn, b1)
        tid = insert_task(conn, b1, "t", c1)
        with pytest.raises(ValueError, match="not board"):
            service.tag_task(conn, tid, "bug", b2)

    def test_untag_task_cross_board_raises(self, conn: sqlite3.Connection) -> None:
        b1 = insert_board(conn, "board1")
        b2 = insert_board(conn, "board2")
        c1 = insert_column(conn, b1)
        tid = insert_task(conn, b1, "t", c1)
        service.tag_task(conn, tid, "bug", b1)
        with pytest.raises(ValueError, match="not board"):
            service.untag_task(conn, tid, "bug", b2)

    def test_untag_task(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        tid = insert_task(conn, bid, "t", cid)
        service.tag_task(conn, tid, "bug", bid)
        service.untag_task(conn, tid, "bug", bid)
        ref = service.get_task_ref(conn, tid)
        assert ref.tag_ids == ()

    def test_untag_task_missing_tag_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        tid = insert_task(conn, bid, "t", cid)
        with pytest.raises(LookupError, match="not found"):
            service.untag_task(conn, tid, "nonexistent", bid)

    def test_untag_task_not_tagged_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        tid = insert_task(conn, bid, "t", cid)
        service.create_tag(conn, bid, "bug")
        with pytest.raises(LookupError, match="not tagged"):
            service.untag_task(conn, tid, "bug", bid)

    def test_untag_task_missing_task_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        service.create_tag(conn, bid, "bug")
        with pytest.raises(LookupError, match="task 9999 not found"):
            service.untag_task(conn, 9999, "bug", bid)

    def test_get_task_ref_has_tag_ids(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        tid = insert_task(conn, bid, "t", cid)
        tag_id = insert_tag(conn, bid, "bug")
        insert_task_tag(conn, tid, tag_id)
        ref = service.get_task_ref(conn, tid)
        assert ref.tag_ids == (tag_id,)

    def test_get_task_detail_has_tags(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        tid = insert_task(conn, bid, "t", cid)
        tag_id = insert_tag(conn, bid, "bug")
        insert_task_tag(conn, tid, tag_id)
        detail = service.get_task_detail(conn, tid)
        assert len(detail.tags) == 1
        assert detail.tags[0].id == tag_id
        assert detail.tags[0].name == "bug"

    def test_list_task_refs_has_tag_ids(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        tag_id = insert_tag(conn, bid, "bug")
        insert_task_tag(conn, t1, tag_id)
        refs = service.list_task_refs(conn, bid)
        ref_map = {r.id: r for r in refs}
        assert ref_map[t1].tag_ids == (tag_id,)
        assert ref_map[t2].tag_ids == ()

    def test_list_task_refs_filtered_by_tag(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        cid = insert_column(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        insert_task(conn, bid, "b", cid)
        tag_id = insert_tag(conn, bid, "bug")
        insert_task_tag(conn, t1, tag_id)
        refs = service.list_task_refs_filtered(
            conn, bid, task_filter=TaskFilter(tag_id=tag_id)
        )
        assert len(refs) == 1
        assert refs[0].id == t1
        assert refs[0].tag_ids == (tag_id,)
