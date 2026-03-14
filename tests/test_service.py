from __future__ import annotations

import sqlite3

import pytest

from sticky_notes.models import Board, Column, Project, Task, TaskHistory
from sticky_notes.service_models import ProjectDetail, ProjectRef, TaskDetail, TaskRef
from tests.helpers import (
    insert_board as _raw_insert_board,
    insert_column as _raw_insert_column,
    insert_project as _raw_insert_project,
    insert_task as _raw_insert_task,
    insert_task_dependency as _raw_insert_task_dependency,
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


# ---- Board ----


class TestBoardService:
    def test_create(self, conn: sqlite3.Connection) -> None:
        board = service.create_board(conn, "work")
        assert isinstance(board, Board)
        assert board.name == "work"
        assert board.archived is False

    def test_create_duplicate_raises(self, conn: sqlite3.Connection) -> None:
        service.create_board(conn, "work")
        with pytest.raises(sqlite3.IntegrityError):
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

    def test_update(self, conn: sqlite3.Connection) -> None:
        bid = insert_board(conn)
        col = service.create_column(conn, bid, "old")
        updated = service.update_column(conn, col.id, {"name": "new"})
        assert updated.name == "new"


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
        with pytest.raises(sqlite3.IntegrityError):
            service.add_dependency(conn, tid, tid)


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
