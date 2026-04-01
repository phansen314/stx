from __future__ import annotations

import sqlite3

import pytest

from sticky_notes.models import (
    Board,
    Column,
    Group,
    NewBoard,
    NewColumn,
    NewGroup,
    NewProject,
    NewTask,
    NewTaskHistory,
    Project,
    Task,
    TaskField,
    TaskFilter,
    TaskHistory,
)
from sticky_notes.repository import (
    add_dependency,
    assign_task_to_group,
    batch_child_ids_by_group,
    batch_dependency_ids,
    batch_group_ids_by_task,
    batch_task_ids_by_group,
    delete_task_groups_by_group,
    get_board,
    get_board_by_name,
    get_column,
    get_column_by_name,
    get_group,
    get_group_by_title,
    get_project,
    get_project_by_name,
    get_subtree_group_ids,
    get_task,
    get_task_by_title,
    get_task_group_id,
    insert_board,
    insert_column,
    insert_group,
    insert_project,
    insert_task,
    insert_task_history,
    list_all_dependencies,
    list_blocked_by_ids,
    list_blocked_by_tasks,
    list_blocks_ids,
    list_blocks_tasks,
    list_boards,
    list_child_groups,
    list_columns,
    list_groups,
    list_groups_by_board,
    list_projects,
    list_task_history,
    list_task_ids_by_group,
    list_task_ids_by_project,
    list_tasks,
    list_tasks_by_column,
    list_tasks_by_ids,
    list_tasks_by_project,
    list_tasks_filtered,
    list_ungrouped_task_ids,
    remove_dependency,
    reparent_children,
    unassign_task_from_group,
    update_board,
    update_column,
    update_group,
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

    def test_update_board_invalid_column_name(self, conn: sqlite3.Connection) -> None:
        board = insert_board(conn, NewBoard(name="x"))
        with pytest.raises(ValueError, match="invalid column name"):
            # Bypass allowlist with a patched frozenset to test the regex guard
            from sticky_notes import repository
            orig = repository._BOARD_UPDATABLE
            repository._BOARD_UPDATABLE = frozenset({"name; DROP TABLE boards--"})
            try:
                update_board(conn, board.id, {"name; DROP TABLE boards--": "pwned"})
            finally:
                repository._BOARD_UPDATABLE = orig

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


class TestListTasksFiltered:
    def _seed(self, conn: sqlite3.Connection):
        board = insert_board(conn, NewBoard(name="b"))
        col1 = insert_column(conn, NewColumn(board_id=board.id, name="todo", position=0))
        col2 = insert_column(conn, NewColumn(board_id=board.id, name="done", position=1))
        proj = insert_project(conn, NewProject(board_id=board.id, name="p"))
        t1 = insert_task(conn, NewTask(board_id=board.id, title="Fix login bug", column_id=col1.id, project_id=proj.id, priority=3))
        t2 = insert_task(conn, NewTask(board_id=board.id, title="Add search", column_id=col1.id, priority=1))
        t3 = insert_task(conn, NewTask(board_id=board.id, title="Deploy release", column_id=col2.id, project_id=proj.id, priority=2))
        return board, col1, col2, proj, t1, t2, t3

    def test_no_filter(self, conn: sqlite3.Connection) -> None:
        board, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, board.id)
        assert len(result) == 3

    def test_filter_by_column(self, conn: sqlite3.Connection) -> None:
        board, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, board.id, task_filter=TaskFilter(column_id=col1.id))
        assert len(result) == 2
        assert all(t.column_id == col1.id for t in result)

    def test_filter_by_project(self, conn: sqlite3.Connection) -> None:
        board, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, board.id, task_filter=TaskFilter(project_id=proj.id))
        assert len(result) == 2
        assert all(t.project_id == proj.id for t in result)

    def test_filter_by_priority(self, conn: sqlite3.Connection) -> None:
        board, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, board.id, task_filter=TaskFilter(priority=3))
        assert len(result) == 1
        assert result[0].title == "Fix login bug"

    def test_filter_by_search(self, conn: sqlite3.Connection) -> None:
        board, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, board.id, task_filter=TaskFilter(search="login"))
        assert len(result) == 1
        assert result[0].title == "Fix login bug"

    def test_search_case_insensitive(self, conn: sqlite3.Connection) -> None:
        board, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, board.id, task_filter=TaskFilter(search="LOGIN"))
        assert len(result) == 1

    def test_combined_filters(self, conn: sqlite3.Connection) -> None:
        board, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(
            conn, board.id,
            task_filter=TaskFilter(column_id=col1.id, project_id=proj.id),
        )
        assert len(result) == 1
        assert result[0].title == "Fix login bug"

    def test_include_archived(self, conn: sqlite3.Connection) -> None:
        board, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        update_task(conn, t1.id, {"archived": True})
        result = list_tasks_filtered(conn, board.id)
        assert len(result) == 2
        result_all = list_tasks_filtered(conn, board.id, task_filter=TaskFilter(include_archived=True))
        assert len(result_all) == 3

    def test_no_matches(self, conn: sqlite3.Connection) -> None:
        board, col1, col2, proj, t1, t2, t3 = self._seed(conn)
        result = list_tasks_filtered(conn, board.id, task_filter=TaskFilter(priority=5))
        assert result == ()


# ---- Group ----


class TestGroupRepository:
    def _setup(self, conn: sqlite3.Connection) -> tuple[Board, Project]:
        board = insert_board(conn, NewBoard(name="b"))
        proj = insert_project(conn, NewProject(board_id=board.id, name="p"))
        return board, proj

    def test_insert_returns_group(self, conn: sqlite3.Connection) -> None:
        board, proj = self._setup(conn)
        grp = insert_group(conn, NewGroup(project_id=proj.id, title="Frontend"))
        assert isinstance(grp, Group)
        assert grp.title == "Frontend"
        assert grp.archived is False
        assert grp.parent_id is None
        assert grp.id >= 1

    def test_get_group(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        grp = insert_group(conn, NewGroup(project_id=proj.id, title="g"))
        assert get_group(conn, grp.id) == grp

    def test_get_group_missing(self, conn: sqlite3.Connection) -> None:
        assert get_group(conn, 9999) is None

    def test_get_group_by_title(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        grp = insert_group(conn, NewGroup(project_id=proj.id, title="Backend"))
        assert get_group_by_title(conn, proj.id, "Backend") == grp
        assert get_group_by_title(conn, proj.id, "nope") is None

    def test_list_groups_excludes_archived(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        insert_group(conn, NewGroup(project_id=proj.id, title="g1"))
        g2 = insert_group(conn, NewGroup(project_id=proj.id, title="g2"))
        update_group(conn, g2.id, {"archived": True})
        assert len(list_groups(conn, proj.id)) == 1
        assert len(list_groups(conn, proj.id, include_archived=True)) == 2

    def test_list_groups_ordered_by_position(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        g1 = insert_group(conn, NewGroup(project_id=proj.id, title="second", position=1))
        g2 = insert_group(conn, NewGroup(project_id=proj.id, title="first", position=0))
        groups = list_groups(conn, proj.id)
        assert groups[0].id == g2.id
        assert groups[1].id == g1.id

    def test_update_group(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        grp = insert_group(conn, NewGroup(project_id=proj.id, title="old"))
        updated = update_group(conn, grp.id, {"title": "new"})
        assert updated.title == "new"

    def test_update_group_bad_field(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        grp = insert_group(conn, NewGroup(project_id=proj.id, title="g"))
        with pytest.raises(ValueError, match="disallowed"):
            update_group(conn, grp.id, {"id": 99})

    def test_update_group_missing_id(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            update_group(conn, 9999, {"title": "x"})

    def test_unique_title_per_project(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        insert_group(conn, NewGroup(project_id=proj.id, title="dup"))
        with pytest.raises(sqlite3.IntegrityError):
            insert_group(conn, NewGroup(project_id=proj.id, title="dup"))

    def test_same_title_different_projects(self, conn: sqlite3.Connection) -> None:
        board, proj1 = self._setup(conn)
        proj2 = insert_project(conn, NewProject(board_id=board.id, name="p2"))
        g1 = insert_group(conn, NewGroup(project_id=proj1.id, title="shared"))
        g2 = insert_group(conn, NewGroup(project_id=proj2.id, title="shared"))
        assert g1.id != g2.id

    def test_insert_with_parent(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        parent = insert_group(conn, NewGroup(project_id=proj.id, title="parent"))
        child = insert_group(
            conn, NewGroup(project_id=proj.id, title="child", parent_id=parent.id)
        )
        assert child.parent_id == parent.id

    def test_insert_with_invalid_parent_fk(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        with pytest.raises(sqlite3.IntegrityError):
            insert_group(
                conn, NewGroup(project_id=proj.id, title="bad", parent_id=9999)
            )


class TestTaskGroupRepository:
    def _setup(
        self, conn: sqlite3.Connection
    ) -> tuple[Board, Column, Project, Group]:
        board = insert_board(conn, NewBoard(name="b"))
        col = insert_column(conn, NewColumn(board_id=board.id, name="todo"))
        proj = insert_project(conn, NewProject(board_id=board.id, name="p"))
        grp = insert_group(conn, NewGroup(project_id=proj.id, title="g"))
        return board, col, proj, grp

    def test_assign_and_get(self, conn: sqlite3.Connection) -> None:
        board, col, proj, grp = self._setup(conn)
        task = insert_task(conn, NewTask(board_id=board.id, title="t", column_id=col.id))
        assign_task_to_group(conn, task.id, grp.id)
        assert get_task_group_id(conn, task.id) == grp.id

    def test_get_unassigned_returns_none(self, conn: sqlite3.Connection) -> None:
        board, col, _, _ = self._setup(conn)
        task = insert_task(conn, NewTask(board_id=board.id, title="t", column_id=col.id))
        assert get_task_group_id(conn, task.id) is None

    def test_upsert_replaces_group(self, conn: sqlite3.Connection) -> None:
        board, col, proj, grp1 = self._setup(conn)
        grp2 = insert_group(conn, NewGroup(project_id=proj.id, title="g2"))
        task = insert_task(conn, NewTask(board_id=board.id, title="t", column_id=col.id))
        assign_task_to_group(conn, task.id, grp1.id)
        assign_task_to_group(conn, task.id, grp2.id)
        assert get_task_group_id(conn, task.id) == grp2.id

    def test_unassign(self, conn: sqlite3.Connection) -> None:
        board, col, _, grp = self._setup(conn)
        task = insert_task(conn, NewTask(board_id=board.id, title="t", column_id=col.id))
        assign_task_to_group(conn, task.id, grp.id)
        unassign_task_from_group(conn, task.id)
        assert get_task_group_id(conn, task.id) is None

    def test_list_task_ids_by_group(self, conn: sqlite3.Connection) -> None:
        board, col, _, grp = self._setup(conn)
        t1 = insert_task(conn, NewTask(board_id=board.id, title="t1", column_id=col.id))
        t2 = insert_task(conn, NewTask(board_id=board.id, title="t2", column_id=col.id))
        assign_task_to_group(conn, t1.id, grp.id)
        assign_task_to_group(conn, t2.id, grp.id)
        ids = list_task_ids_by_group(conn, grp.id)
        assert set(ids) == {t1.id, t2.id}

    def test_list_ungrouped_task_ids(self, conn: sqlite3.Connection) -> None:
        board, col, proj, grp = self._setup(conn)
        t1 = insert_task(
            conn,
            NewTask(board_id=board.id, title="grouped", column_id=col.id, project_id=proj.id),
        )
        t2 = insert_task(
            conn,
            NewTask(board_id=board.id, title="ungrouped", column_id=col.id, project_id=proj.id),
        )
        assign_task_to_group(conn, t1.id, grp.id)
        ids = list_ungrouped_task_ids(conn, proj.id)
        assert ids == (t2.id,)

    def test_delete_task_groups_by_group(self, conn: sqlite3.Connection) -> None:
        board, col, _, grp = self._setup(conn)
        t1 = insert_task(conn, NewTask(board_id=board.id, title="t1", column_id=col.id))
        t2 = insert_task(conn, NewTask(board_id=board.id, title="t2", column_id=col.id))
        assign_task_to_group(conn, t1.id, grp.id)
        assign_task_to_group(conn, t2.id, grp.id)
        delete_task_groups_by_group(conn, grp.id)
        assert get_task_group_id(conn, t1.id) is None
        assert get_task_group_id(conn, t2.id) is None


class TestGroupTreeRepository:
    def _setup(self, conn: sqlite3.Connection) -> tuple[Board, Project]:
        board = insert_board(conn, NewBoard(name="b"))
        proj = insert_project(conn, NewProject(board_id=board.id, name="p"))
        return board, proj

    def test_list_child_groups(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        parent = insert_group(conn, NewGroup(project_id=proj.id, title="parent"))
        c1 = insert_group(
            conn, NewGroup(project_id=proj.id, title="c1", parent_id=parent.id)
        )
        c2 = insert_group(
            conn, NewGroup(project_id=proj.id, title="c2", parent_id=parent.id)
        )
        children = list_child_groups(conn, parent.id)
        assert {g.id for g in children} == {c1.id, c2.id}

    def test_list_child_groups_excludes_archived(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        parent = insert_group(conn, NewGroup(project_id=proj.id, title="parent"))
        insert_group(
            conn, NewGroup(project_id=proj.id, title="c1", parent_id=parent.id)
        )
        c2 = insert_group(
            conn, NewGroup(project_id=proj.id, title="c2", parent_id=parent.id)
        )
        update_group(conn, c2.id, {"archived": True})
        assert len(list_child_groups(conn, parent.id)) == 1
        assert len(list_child_groups(conn, parent.id, include_archived=True)) == 2

    def test_get_subtree_group_ids(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        root = insert_group(conn, NewGroup(project_id=proj.id, title="root"))
        mid = insert_group(
            conn, NewGroup(project_id=proj.id, title="mid", parent_id=root.id)
        )
        leaf = insert_group(
            conn, NewGroup(project_id=proj.id, title="leaf", parent_id=mid.id)
        )
        ids = get_subtree_group_ids(conn, root.id)
        assert set(ids) == {root.id, mid.id, leaf.id}

    def test_subtree_excludes_archived(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        root = insert_group(conn, NewGroup(project_id=proj.id, title="root"))
        child = insert_group(
            conn, NewGroup(project_id=proj.id, title="child", parent_id=root.id)
        )
        update_group(conn, child.id, {"archived": True})
        ids = get_subtree_group_ids(conn, root.id)
        assert set(ids) == {root.id}

    def test_reparent_children(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        g1 = insert_group(conn, NewGroup(project_id=proj.id, title="g1"))
        g2 = insert_group(conn, NewGroup(project_id=proj.id, title="g2"))
        child = insert_group(
            conn, NewGroup(project_id=proj.id, title="child", parent_id=g1.id)
        )
        reparent_children(conn, g1.id, g2.id)
        updated = get_group(conn, child.id)
        assert updated is not None
        assert updated.parent_id == g2.id

    def test_reparent_to_none(self, conn: sqlite3.Connection) -> None:
        _, proj = self._setup(conn)
        parent = insert_group(conn, NewGroup(project_id=proj.id, title="parent"))
        child = insert_group(
            conn, NewGroup(project_id=proj.id, title="child", parent_id=parent.id)
        )
        reparent_children(conn, parent.id, None)
        updated = get_group(conn, child.id)
        assert updated is not None
        assert updated.parent_id is None


class TestBatchGroupQueries:
    def _setup(
        self, conn: sqlite3.Connection
    ) -> tuple[Board, Column, Project]:
        board = insert_board(conn, NewBoard(name="b"))
        col = insert_column(conn, NewColumn(board_id=board.id, name="todo"))
        proj = insert_project(conn, NewProject(board_id=board.id, name="p"))
        return board, col, proj

    # -- list_tasks_by_ids --

    def test_list_tasks_by_ids_returns_tasks(self, conn: sqlite3.Connection) -> None:
        board, col, _ = self._setup(conn)
        t1 = insert_task(conn, NewTask(board_id=board.id, title="t1", column_id=col.id))
        t2 = insert_task(conn, NewTask(board_id=board.id, title="t2", column_id=col.id))
        tasks = list_tasks_by_ids(conn, (t1.id, t2.id))
        assert len(tasks) == 2
        assert {t.id for t in tasks} == {t1.id, t2.id}
        assert all(isinstance(t, Task) for t in tasks)

    def test_list_tasks_by_ids_empty(self, conn: sqlite3.Connection) -> None:
        assert list_tasks_by_ids(conn, ()) == ()

    def test_list_tasks_by_ids_missing_ids_ignored(self, conn: sqlite3.Connection) -> None:
        board, col, _ = self._setup(conn)
        t1 = insert_task(conn, NewTask(board_id=board.id, title="t1", column_id=col.id))
        tasks = list_tasks_by_ids(conn, (t1.id, 9999))
        assert len(tasks) == 1
        assert tasks[0].id == t1.id

    # -- batch_task_ids_by_group --

    def test_batch_task_ids_by_group(self, conn: sqlite3.Connection) -> None:
        board, col, proj = self._setup(conn)
        g1 = insert_group(conn, NewGroup(project_id=proj.id, title="g1"))
        g2 = insert_group(conn, NewGroup(project_id=proj.id, title="g2"))
        t1 = insert_task(conn, NewTask(board_id=board.id, title="t1", column_id=col.id))
        t2 = insert_task(conn, NewTask(board_id=board.id, title="t2", column_id=col.id))
        assign_task_to_group(conn, t1.id, g1.id)
        assign_task_to_group(conn, t2.id, g1.id)
        result = batch_task_ids_by_group(conn, (g1.id, g2.id))
        assert set(result[g1.id]) == {t1.id, t2.id}
        assert result[g2.id] == ()

    def test_batch_task_ids_by_group_empty(self, conn: sqlite3.Connection) -> None:
        assert batch_task_ids_by_group(conn, ()) == {}

    # -- batch_child_ids_by_group --

    def test_batch_child_ids_by_group(self, conn: sqlite3.Connection) -> None:
        _, _, proj = self._setup(conn)
        parent = insert_group(conn, NewGroup(project_id=proj.id, title="parent"))
        c1 = insert_group(
            conn, NewGroup(project_id=proj.id, title="c1", parent_id=parent.id)
        )
        c2 = insert_group(
            conn, NewGroup(project_id=proj.id, title="c2", parent_id=parent.id)
        )
        result = batch_child_ids_by_group(conn, (parent.id,))
        assert set(result[parent.id]) == {c1.id, c2.id}

    def test_batch_child_ids_excludes_archived(self, conn: sqlite3.Connection) -> None:
        _, _, proj = self._setup(conn)
        parent = insert_group(conn, NewGroup(project_id=proj.id, title="parent"))
        c1 = insert_group(
            conn, NewGroup(project_id=proj.id, title="c1", parent_id=parent.id)
        )
        c2 = insert_group(
            conn, NewGroup(project_id=proj.id, title="c2", parent_id=parent.id)
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

    # -- batch_group_ids_by_task --

    def test_batch_group_ids_by_task(self, conn: sqlite3.Connection) -> None:
        board, col, proj = self._setup(conn)
        grp = insert_group(conn, NewGroup(project_id=proj.id, title="g"))
        t1 = insert_task(conn, NewTask(board_id=board.id, title="t1", column_id=col.id))
        t2 = insert_task(conn, NewTask(board_id=board.id, title="t2", column_id=col.id))
        t3 = insert_task(conn, NewTask(board_id=board.id, title="ungrouped", column_id=col.id))
        assign_task_to_group(conn, t1.id, grp.id)
        assign_task_to_group(conn, t2.id, grp.id)
        result = batch_group_ids_by_task(conn, (t1.id, t2.id, t3.id))
        assert result[t1.id] == grp.id
        assert result[t2.id] == grp.id
        assert t3.id not in result

    def test_batch_group_ids_by_task_empty(self, conn: sqlite3.Connection) -> None:
        assert batch_group_ids_by_task(conn, ()) == {}

    # -- list_groups_by_board --

    def test_list_groups_by_board(self, conn: sqlite3.Connection) -> None:
        board, _, proj = self._setup(conn)
        g1 = insert_group(conn, NewGroup(project_id=proj.id, title="g1", position=1))
        g2 = insert_group(conn, NewGroup(project_id=proj.id, title="g2", position=0))
        result = list_groups_by_board(conn, board.id)
        assert len(result) == 2
        assert result[0].id == g2.id  # position 0 first
        assert result[1].id == g1.id

    def test_list_groups_by_board_excludes_archived(self, conn: sqlite3.Connection) -> None:
        board, _, proj = self._setup(conn)
        insert_group(conn, NewGroup(project_id=proj.id, title="g1"))
        g2 = insert_group(conn, NewGroup(project_id=proj.id, title="g2"))
        update_group(conn, g2.id, {"archived": True})
        assert len(list_groups_by_board(conn, board.id)) == 1
        assert len(list_groups_by_board(conn, board.id, include_archived=True)) == 2

    def test_list_groups_by_board_multi_project(self, conn: sqlite3.Connection) -> None:
        board, _, proj1 = self._setup(conn)
        proj2 = insert_project(conn, NewProject(board_id=board.id, name="p2"))
        insert_group(conn, NewGroup(project_id=proj1.id, title="g1"))
        insert_group(conn, NewGroup(project_id=proj2.id, title="g2"))
        result = list_groups_by_board(conn, board.id)
        assert len(result) == 2

    def test_list_groups_by_board_empty(self, conn: sqlite3.Connection) -> None:
        board, _, _ = self._setup(conn)
        assert list_groups_by_board(conn, board.id) == ()
