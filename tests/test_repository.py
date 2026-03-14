from __future__ import annotations

import sqlite3

import pytest

from sticky_notes.models import (
    Board,
    Column,
    NewBoard,
    NewColumn,
    NewProject,
    NewTask,
    NewTaskHistory,
    Project,
    Task,
    TaskField,
    TaskHistory,
)
from sticky_notes.repository import (
    add_dependency,
    get_board,
    get_board_by_name,
    get_column,
    get_column_by_name,
    get_project,
    get_project_by_name,
    get_task,
    get_task_by_title,
    insert_board,
    insert_column,
    insert_project,
    insert_task,
    insert_task_history,
    list_all_dependencies,
    list_blocked_by_ids,
    list_blocked_by_tasks,
    list_blocks_ids,
    list_blocks_tasks,
    list_boards,
    list_columns,
    list_projects,
    list_task_history,
    list_task_ids_by_project,
    list_tasks,
    list_tasks_by_column,
    list_tasks_by_project,
    remove_dependency,
    update_board,
    update_column,
    update_project,
    update_task,
)


# ---- Board ----


class TestBoardRepository:
    def test_insert_returns_board(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="work"))
        assert isinstance(board, Board)
        assert board.name == "work"
        assert board.archived is False
        assert board.id >= 1

    def test_get_board(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="work"))
        fetched = get_board(conn, board.id)
        assert fetched == board

    def test_get_board_missing(self, conn: sqlite3.Connection) -> None:
        assert get_board(conn, 9999) is None

    def test_get_board_by_name(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="work"))
        assert get_board_by_name(conn, "work") == board
        assert get_board_by_name(conn, "nope") is None

    def test_list_boards_excludes_archived(self, conn: sqlite3.Connection) -> None:
        b1 = insert_board(conn, NewBoard(name="a"))
        b2 = insert_board(conn, NewBoard(name="b"))
        update_board(conn, b2.id, {"archived": True})
        boards = list_boards(conn)
        assert len(boards) == 1
        assert boards[0].id == b1.id

    def test_list_boards_include_archived(self, conn: sqlite3.Connection) -> None:
        insert_board(conn, NewBoard(name="a"))
        b2 = insert_board(conn, NewBoard(name="b"))
        update_board(conn, b2.id, {"archived": True})
        boards = list_boards(conn, include_archived=True)
        assert len(boards) == 2

    def test_update_board(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="old"))
        updated = update_board(conn, board.id, {"name": "new"})
        assert updated.name == "new"
        assert updated.id == board.id

    def test_update_board_bad_field(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="x"))
        with pytest.raises(ValueError, match="disallowed"):
            update_board(conn, board.id, {"id": 99})

    def test_update_board_empty_changes(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="x"))
        with pytest.raises(ValueError, match="empty"):
            update_board(conn, board.id, {})

    def test_update_board_missing_id(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            update_board(conn, 9999, {"name": "y"})


# ---- Column ----


class TestColumnRepository:
    def test_insert_returns_column(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="b"))
        col = insert_column(conn, NewColumn(board_id=board.id, name="todo", position=0))
        assert isinstance(col, Column)
        assert col.name == "todo"
        assert col.board_id == board.id

    def test_get_column(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="b"))
        col = insert_column(conn, NewColumn(board_id=board.id, name="todo"))
        assert get_column(conn, col.id) == col

    def test_get_column_missing(self, conn: sqlite3.Connection) -> None:
        assert get_column(conn, 9999) is None

    def test_list_columns_ordered_by_position(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="b"))
        c2 = insert_column(conn, NewColumn(board_id=board.id, name="done", position=2))
        c1 = insert_column(conn, NewColumn(board_id=board.id, name="todo", position=1))
        cols = list_columns(conn, board.id)
        assert cols[0].id == c1.id
        assert cols[1].id == c2.id

    def test_list_columns_excludes_archived(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="b"))
        insert_column(conn, NewColumn(board_id=board.id, name="todo"))
        c2 = insert_column(conn, NewColumn(board_id=board.id, name="done", position=1))
        update_column(conn, c2.id, {"archived": True})
        assert len(list_columns(conn, board.id)) == 1
        assert len(list_columns(conn, board.id, include_archived=True)) == 2

    def test_update_column(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="b"))
        col = insert_column(conn, NewColumn(board_id=board.id, name="old"))
        updated = update_column(conn, col.id, {"name": "new"})
        assert updated.name == "new"

    def test_update_column_bad_field(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="b"))
        col = insert_column(conn, NewColumn(board_id=board.id, name="x"))
        with pytest.raises(ValueError, match="disallowed"):
            update_column(conn, col.id, {"created_at": 0})

    def test_update_column_missing_id(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            update_column(conn, 9999, {"name": "y"})

    def test_get_column_by_name(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="b"))
        col = insert_column(conn, NewColumn(board_id=board.id, name="done", position=0))
        assert get_column_by_name(conn, board.id, "done") == col
        assert get_column_by_name(conn, board.id, "nope") is None


# ---- Project ----


class TestProjectRepository:
    def test_insert_returns_project(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="b"))
        proj = insert_project(conn, NewProject(board_id=board.id, name="p1"))
        assert isinstance(proj, Project)
        assert proj.name == "p1"
        assert proj.description is None

    def test_get_project(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="b"))
        proj = insert_project(conn, NewProject(board_id=board.id, name="p1"))
        assert get_project(conn, proj.id) == proj

    def test_get_project_missing(self, conn: sqlite3.Connection) -> None:
        assert get_project(conn, 9999) is None

    def test_list_projects_excludes_archived(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="b"))
        insert_project(conn, NewProject(board_id=board.id, name="p1"))
        p2 = insert_project(conn, NewProject(board_id=board.id, name="p2"))
        update_project(conn, p2.id, {"archived": True})
        assert len(list_projects(conn, board.id)) == 1
        assert len(list_projects(conn, board.id, include_archived=True)) == 2

    def test_update_project(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="b"))
        proj = insert_project(conn, NewProject(board_id=board.id, name="old"))
        updated = update_project(conn, proj.id, {"name": "new", "description": "hi"})
        assert updated.name == "new"
        assert updated.description == "hi"

    def test_update_project_bad_field(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="b"))
        proj = insert_project(conn, NewProject(board_id=board.id, name="x"))
        with pytest.raises(ValueError, match="disallowed"):
            update_project(conn, proj.id, {"id": 99})

    def test_update_project_missing_id(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            update_project(conn, 9999, {"name": "y"})

    def test_get_project_by_name(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="b"))
        proj = insert_project(conn, NewProject(board_id=board.id, name="backend"))
        assert get_project_by_name(conn, board.id, "backend") == proj
        assert get_project_by_name(conn, board.id, "nope") is None


# ---- Task ----


class TestTaskRepository:
    def _setup(self, conn: sqlite3.Connection) -> tuple[Board, Column]:
        board = insert_board(conn, NewBoard(name="b"))
        col = insert_column(conn, NewColumn(board_id=board.id, name="todo"))
        return board, col

    def test_insert_returns_task(self, conn: sqlite3.Connection) -> None:
        board, col = self._setup(conn)
        task = insert_task(
            conn, NewTask(board_id=board.id, title="do stuff", column_id=col.id)
        )
        assert isinstance(task, Task)
        assert task.title == "do stuff"
        assert task.archived is False
        assert task.priority == 1

    def test_get_task(self, conn: sqlite3.Connection) -> None:
        board, col = self._setup(conn)
        task = insert_task(
            conn, NewTask(board_id=board.id, title="t", column_id=col.id)
        )
        assert get_task(conn, task.id) == task

    def test_get_task_missing(self, conn: sqlite3.Connection) -> None:
        assert get_task(conn, 9999) is None

    def test_list_tasks_by_board(self, conn: sqlite3.Connection) -> None:
        board, col = self._setup(conn)
        t1 = insert_task(
            conn, NewTask(board_id=board.id, title="a", column_id=col.id, position=1)
        )
        t2 = insert_task(
            conn, NewTask(board_id=board.id, title="b", column_id=col.id, position=0)
        )
        tasks = list_tasks(conn, board.id)
        assert tasks[0].id == t2.id
        assert tasks[1].id == t1.id

    def test_list_tasks_excludes_archived(self, conn: sqlite3.Connection) -> None:
        board, col = self._setup(conn)
        insert_task(conn, NewTask(board_id=board.id, title="a", column_id=col.id))
        t2 = insert_task(conn, NewTask(board_id=board.id, title="b", column_id=col.id))
        update_task(conn, t2.id, {"archived": True})
        assert len(list_tasks(conn, board.id)) == 1
        assert len(list_tasks(conn, board.id, include_archived=True)) == 2

    def test_list_tasks_by_column(self, conn: sqlite3.Connection) -> None:
        board, col1 = self._setup(conn)
        col2 = insert_column(
            conn, NewColumn(board_id=board.id, name="done", position=1)
        )
        insert_task(conn, NewTask(board_id=board.id, title="a", column_id=col1.id))
        insert_task(conn, NewTask(board_id=board.id, title="b", column_id=col2.id))
        assert len(list_tasks_by_column(conn, col1.id)) == 1
        assert len(list_tasks_by_column(conn, col2.id)) == 1

    def test_list_tasks_by_project(self, conn: sqlite3.Connection) -> None:
        board, col = self._setup(conn)
        proj = insert_project(conn, NewProject(board_id=board.id, name="p"))
        insert_task(
            conn,
            NewTask(
                board_id=board.id, title="a", column_id=col.id, project_id=proj.id
            ),
        )
        insert_task(conn, NewTask(board_id=board.id, title="b", column_id=col.id))
        assert len(list_tasks_by_project(conn, proj.id)) == 1

    def test_update_task(self, conn: sqlite3.Connection) -> None:
        board, col = self._setup(conn)
        task = insert_task(
            conn, NewTask(board_id=board.id, title="old", column_id=col.id)
        )
        updated = update_task(conn, task.id, {"title": "new", "priority": 3})
        assert updated.title == "new"
        assert updated.priority == 3

    def test_update_task_bad_field(self, conn: sqlite3.Connection) -> None:
        board, col = self._setup(conn)
        task = insert_task(
            conn, NewTask(board_id=board.id, title="t", column_id=col.id)
        )
        with pytest.raises(ValueError, match="disallowed"):
            update_task(conn, task.id, {"id": 99})

    def test_update_task_missing_id(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            update_task(conn, 9999, {"title": "y"})

    def test_list_tasks_by_column_excludes_archived(
        self, conn: sqlite3.Connection
    ) -> None:
        board, col = self._setup(conn)
        insert_task(conn, NewTask(board_id=board.id, title="a", column_id=col.id))
        t2 = insert_task(
            conn, NewTask(board_id=board.id, title="b", column_id=col.id)
        )
        update_task(conn, t2.id, {"archived": True})
        assert len(list_tasks_by_column(conn, col.id)) == 1
        assert len(list_tasks_by_column(conn, col.id, include_archived=True)) == 2

    def test_list_tasks_by_project_excludes_archived(
        self, conn: sqlite3.Connection
    ) -> None:
        board, col = self._setup(conn)
        proj = insert_project(conn, NewProject(board_id=board.id, name="p"))
        insert_task(
            conn,
            NewTask(
                board_id=board.id, title="a", column_id=col.id, project_id=proj.id
            ),
        )
        t2 = insert_task(
            conn,
            NewTask(
                board_id=board.id, title="b", column_id=col.id, project_id=proj.id
            ),
        )
        update_task(conn, t2.id, {"archived": True})
        assert len(list_tasks_by_project(conn, proj.id)) == 1
        assert len(list_tasks_by_project(conn, proj.id, include_archived=True)) == 2

    def test_get_task_by_title(self, conn: sqlite3.Connection) -> None:
        board, col = self._setup(conn)
        task = insert_task(
            conn, NewTask(board_id=board.id, title="Find me", column_id=col.id)
        )
        found = get_task_by_title(conn, board.id, "Find me")
        assert found is not None
        assert found.id == task.id
        assert found.title == "Find me"

    def test_get_task_by_title_missing(self, conn: sqlite3.Connection) -> None:
        board, col = self._setup(conn)
        assert get_task_by_title(conn, board.id, "nonexistent") is None

    def test_priority_at_lower_bound(self, conn: sqlite3.Connection) -> None:
        board, col = self._setup(conn)
        task = insert_task(
            conn, NewTask(board_id=board.id, title="low", column_id=col.id, priority=1)
        )
        assert task.priority == 1

    def test_priority_at_upper_bound(self, conn: sqlite3.Connection) -> None:
        board, col = self._setup(conn)
        task = insert_task(
            conn, NewTask(board_id=board.id, title="high", column_id=col.id, priority=5)
        )
        assert task.priority == 5

    def test_priority_below_lower_bound_rejected(self, conn: sqlite3.Connection) -> None:
        board, col = self._setup(conn)
        with pytest.raises(sqlite3.IntegrityError):
            insert_task(
                conn, NewTask(board_id=board.id, title="bad", column_id=col.id, priority=0)
            )

    def test_priority_above_upper_bound_rejected(self, conn: sqlite3.Connection) -> None:
        board, col = self._setup(conn)
        with pytest.raises(sqlite3.IntegrityError):
            insert_task(
                conn, NewTask(board_id=board.id, title="bad", column_id=col.id, priority=6)
            )

    def test_empty_title_allowed(self, conn: sqlite3.Connection) -> None:
        board, col = self._setup(conn)
        task = insert_task(
            conn, NewTask(board_id=board.id, title="", column_id=col.id)
        )
        assert task.title == ""

    def test_insert_task_with_all_optional_fields(
        self, conn: sqlite3.Connection
    ) -> None:
        board, col = self._setup(conn)
        proj = insert_project(conn, NewProject(board_id=board.id, name="p"))
        task = insert_task(
            conn,
            NewTask(
                board_id=board.id,
                title="full",
                column_id=col.id,
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
        board = insert_board(conn, NewBoard(name="b"))
        col = insert_column(conn, NewColumn(board_id=board.id, name="todo"))
        t1 = insert_task(conn, NewTask(board_id=board.id, title="t1", column_id=col.id))
        t2 = insert_task(conn, NewTask(board_id=board.id, title="t2", column_id=col.id))
        t3 = insert_task(conn, NewTask(board_id=board.id, title="t3", column_id=col.id))
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

    def test_remove_dependency(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_dependency(conn, t1.id, t2.id)
        remove_dependency(conn, t1.id, t2.id)
        assert list_blocked_by_ids(conn, t1.id) == ()

    def test_remove_nonexistent_is_silent(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        remove_dependency(conn, t1.id, t2.id)  # no-op, no error

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

    def test_duplicate_dependency_raises(self, conn: sqlite3.Connection) -> None:
        t1, t2, _ = self._setup(conn)
        add_dependency(conn, t1.id, t2.id)
        with pytest.raises(sqlite3.IntegrityError):
            add_dependency(conn, t1.id, t2.id)

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


# ---- Task history ----


class TestTaskHistoryRepository:
    def test_insert_returns_task_history(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="b"))
        col = insert_column(conn, NewColumn(board_id=board.id, name="todo"))
        task = insert_task(
            conn, NewTask(board_id=board.id, title="t", column_id=col.id)
        )
        h = insert_task_history(
            conn,
            NewTaskHistory(
                task_id=task.id,
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
        board = insert_board(conn, NewBoard(name="b"))
        col = insert_column(conn, NewColumn(board_id=board.id, name="todo"))
        task = insert_task(
            conn, NewTask(board_id=board.id, title="t", column_id=col.id)
        )
        h1 = insert_task_history(
            conn,
            NewTaskHistory(
                task_id=task.id,
                field=TaskField.TITLE,
                new_value="v1",
                source="tui",
            ),
        )
        h2 = insert_task_history(
            conn,
            NewTaskHistory(
                task_id=task.id,
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
        board = insert_board(conn, NewBoard(name="b"))
        col = insert_column(conn, NewColumn(board_id=board.id, name="todo"))
        proj = insert_project(conn, NewProject(board_id=board.id, name="p"))
        t1 = insert_task(
            conn,
            NewTask(
                board_id=board.id, title="a", column_id=col.id, project_id=proj.id
            ),
        )
        insert_task(conn, NewTask(board_id=board.id, title="b", column_id=col.id))
        ids = list_task_ids_by_project(conn, proj.id)
        assert ids == (t1.id,)
