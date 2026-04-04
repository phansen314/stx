from __future__ import annotations

import dataclasses
import re
import sqlite3
from typing import NamedTuple

import pytest

from helpers import (
    insert_board,
    insert_column,
    insert_project,
    insert_task,
    insert_task_dependency,
    insert_task_history,
)
from sticky_notes.connection import read_schema, transaction
from sticky_notes.mappers import (
    shallow_fields,
    project_ref_to_detail,
    project_to_ref,
    row_to_board,
    row_to_column,
    row_to_project,
    row_to_task,
    row_to_task_history,
    task_ref_to_detail,
    task_to_ref,
)
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
from sticky_notes.service_models import ProjectDetail, ProjectRef, TaskDetail, TaskRef


# ---- Seed helpers ----


class FullSeed(NamedTuple):
    conn: sqlite3.Connection
    board_id: int
    project_id: int
    column_id: int
    task1_id: int
    task2_id: int
    history_id: int


@pytest.fixture
def seeded(conn: sqlite3.Connection) -> FullSeed:
    """Full data graph for tests that need tasks, deps, and history."""
    with transaction(conn):
        board_id = insert_board(conn)
        project_id = insert_project(conn, board_id)
        column_id = insert_column(conn, board_id)
        task1_id = insert_task(
            conn, board_id, "task1", column_id, project_id, priority=5,
        )
        task2_id = insert_task(conn, board_id, "task2", column_id, priority=3)
        insert_task_dependency(conn, task1_id, task2_id)
        history_id = insert_task_history(
            conn, task1_id, field="title", old_value="old",
            new_value="task1", source="tui",
        )
    return FullSeed(
        conn=conn,
        board_id=board_id,
        project_id=project_id,
        column_id=column_id,
        task1_id=task1_id,
        task2_id=task2_id,
        history_id=history_id,
    )


# ---- Row → model tests ----


class TestRowToBoard:
    def test_maps_row(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            board_id = insert_board(conn)
        row = conn.execute(
            "SELECT * FROM boards WHERE id = ?", (board_id,),
        ).fetchone()
        board = row_to_board(row)
        assert isinstance(board, Board)
        assert board.id == board_id
        assert board.name == "board1"
        assert board.archived is False

    def test_archived_is_bool(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            board_id = insert_board(conn)
        with transaction(conn):
            conn.execute("UPDATE boards SET archived = 1 WHERE id = ?", (board_id,))
        row = conn.execute(
            "SELECT * FROM boards WHERE id = ?", (board_id,),
        ).fetchone()
        board = row_to_board(row)
        assert board.archived is True


class TestRowToColumn:
    def test_maps_row(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            board_id = insert_board(conn)
            col_id = insert_column(conn, board_id)
        row = conn.execute(
            "SELECT * FROM columns WHERE id = ?", (col_id,),
        ).fetchone()
        col = row_to_column(row)
        assert isinstance(col, Column)
        assert col.id == col_id
        assert col.name == "todo"
        assert col.position == 0
        assert col.archived is False
        assert isinstance(col.created_at, int)

    def test_archived_is_bool(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            board_id = insert_board(conn)
            col_id = insert_column(conn, board_id)
        with transaction(conn):
            conn.execute("UPDATE columns SET archived = 1 WHERE id = ?", (col_id,))
        row = conn.execute(
            "SELECT * FROM columns WHERE id = ?", (col_id,),
        ).fetchone()
        col = row_to_column(row)
        assert col.archived is True


class TestRowToProject:
    def test_maps_row(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            board_id = insert_board(conn)
            proj_id = insert_project(conn, board_id)
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (proj_id,),
        ).fetchone()
        project = row_to_project(row)
        assert isinstance(project, Project)
        assert project.name == "proj1"
        assert project.description == "desc"

    def test_archived_is_bool(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            board_id = insert_board(conn)
            proj_id = insert_project(conn, board_id)
        with transaction(conn):
            conn.execute("UPDATE projects SET archived = 1 WHERE id = ?", (proj_id,))
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (proj_id,),
        ).fetchone()
        project = row_to_project(row)
        assert project.archived is True


class TestRowToTask:
    def test_maps_row(self, seeded: FullSeed) -> None:
        row = seeded.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (seeded.task1_id,),
        ).fetchone()
        task = row_to_task(row)
        assert isinstance(task, Task)
        assert task.title == "task1"
        assert task.priority == 5
        assert task.project_id == seeded.project_id
        assert task.archived is False

    def test_maps_null_optional_fields(self, seeded: FullSeed) -> None:
        """Task with NULL project_id, description, due_date, start_date, finish_date."""
        row = seeded.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (seeded.task2_id,),
        ).fetchone()
        task = row_to_task(row)
        assert task.project_id is None
        assert task.description is None
        assert task.due_date is None
        assert task.start_date is None
        assert task.finish_date is None


class TestRowToTaskHistory:
    def test_maps_row(self, seeded: FullSeed) -> None:
        row = seeded.conn.execute(
            "SELECT * FROM task_history WHERE id = ?", (seeded.history_id,),
        ).fetchone()
        history = row_to_task_history(row)
        assert isinstance(history, TaskHistory)
        assert history.field == TaskField.TITLE
        assert history.old_value == "old"
        assert history.new_value == "task1"
        assert history.source == "tui"

    def test_raises_on_invalid_field(self, conn: sqlite3.Connection) -> None:
        """row_to_task_history raises ValueError for unknown field values."""
        fake_row = {
            "id": 1,
            "task_id": 1,
            "field": "nonexistent_field",
            "old_value": None,
            "new_value": "v",
            "source": "test",
            "changed_at": 0,
        }
        with pytest.raises(ValueError):
            row_to_task_history(fake_row)  # type: ignore[arg-type]


# ---- shallow_fields tests ----


class TestShallowFields:
    def test_extracts_base_class_fields(self) -> None:
        task = Task(
            id=1, board_id=1, title="t", project_id=None, description=None,
            column_id=1, priority=1, due_date=None, position=0,
            archived=False, created_at=0, start_date=None, finish_date=None, group_id=None,
        )
        fields = shallow_fields(task, Task)
        assert set(fields.keys()) == {
            "id", "board_id", "title", "project_id", "description",
            "column_id", "priority", "due_date", "position",
            "archived", "created_at", "start_date", "finish_date", "group_id",
        }

    def test_filters_subclass_fields_when_parent_specified(self) -> None:
        ref = TaskRef(
            id=1, board_id=1, title="t", project_id=None, description=None,
            column_id=1, priority=1, due_date=None, position=0,
            archived=False, created_at=0, start_date=None, finish_date=None, group_id=None,
            blocked_by_ids=(2,), blocks_ids=(3,),
        )
        fields = shallow_fields(ref, Task)
        assert "blocked_by_ids" not in fields
        assert "blocks_ids" not in fields

    def test_includes_subclass_fields_when_subclass_specified(self) -> None:
        ref = TaskRef(
            id=1, board_id=1, title="t", project_id=None, description=None,
            column_id=1, priority=1, due_date=None, position=0,
            archived=False, created_at=0, start_date=None, finish_date=None, group_id=None,
            blocked_by_ids=(2,), blocks_ids=(3,),
        )
        fields = shallow_fields(ref, TaskRef)
        assert fields["blocked_by_ids"] == (2,)
        assert fields["blocks_ids"] == (3,)

    def test_rejects_non_dataclass(self) -> None:
        with pytest.raises(TypeError, match="is not a dataclass"):
            shallow_fields("not a dataclass", str)

    def test_rejects_wrong_instance_type(self) -> None:
        board = Board(id=1, name="b", archived=False, created_at=0)
        with pytest.raises(TypeError, match="is not an instance of"):
            shallow_fields(board, Task)


# ---- Model → ref tests ----


class TestTaskToRef:
    def test_creates_ref(self) -> None:
        task = Task(
            id=1, board_id=1, title="t", project_id=None, description=None,
            column_id=1, priority=1, due_date=None, position=0,
            archived=False, created_at=0, start_date=None, finish_date=None, group_id=None,
        )
        ref = task_to_ref(task, blocked_by_ids=(2,), blocks_ids=(3,))
        assert isinstance(ref, TaskRef)
        assert ref.title == "t"
        assert ref.blocked_by_ids == (2,)
        assert ref.blocks_ids == (3,)

    def test_ref_input_replaces_dependency_ids(self) -> None:
        """Passing a TaskRef replaces its dependency IDs with the new ones."""
        ref = TaskRef(
            id=1, board_id=1, title="t", project_id=None, description=None,
            column_id=1, priority=1, due_date=None, position=0,
            archived=False, created_at=0, start_date=None, finish_date=None, group_id=None,
            blocked_by_ids=(99,), blocks_ids=(88,),
        )
        new_ref = task_to_ref(ref, blocked_by_ids=(2,), blocks_ids=(3,))
        assert new_ref.blocked_by_ids == (2,)
        assert new_ref.blocks_ids == (3,)


class TestTaskRefToDetail:
    def test_creates_detail(self) -> None:
        col = Column(
            id=1, board_id=1, name="todo", position=0,
            archived=False, created_at=0,
        )
        ref = TaskRef(
            id=1, board_id=1, title="t", project_id=None, description=None,
            column_id=1, priority=1, due_date=None, position=0,
            archived=False, created_at=0, start_date=None, finish_date=None, group_id=None,
            blocked_by_ids=(), blocks_ids=(),
        )
        detail = task_ref_to_detail(
            ref, column=col, project=None,
            blocked_by=(), blocks=(), history=(),
        )
        assert isinstance(detail, TaskDetail)
        assert detail.column == col
        assert detail.title == "t"


class TestProjectToRef:
    def test_creates_ref(self) -> None:
        project = Project(
            id=1, board_id=1, name="p", description=None,
            archived=False, created_at=0,
        )
        ref = project_to_ref(project, task_ids=(1, 2))
        assert isinstance(ref, ProjectRef)
        assert ref.task_ids == (1, 2)
        assert ref.name == "p"


class TestProjectRefToDetail:
    def test_creates_detail(self) -> None:
        ref = ProjectRef(
            id=1, board_id=1, name="p", description=None,
            archived=False, created_at=0, task_ids=(1,),
        )
        detail = project_ref_to_detail(ref, tasks=())
        assert isinstance(detail, ProjectDetail)
        assert detail.task_ids == (1,)
        assert detail.tasks == ()

    def test_project_detail_inherits_from_project_ref(self) -> None:
        assert issubclass(ProjectDetail, ProjectRef)


# ---- Pre-insert default tests ----


class TestPreInsertDefaults:
    def test_new_board_has_no_defaults(self) -> None:
        board = NewBoard(name="b")
        assert board.name == "b"

    def test_new_project_defaults(self) -> None:
        proj = NewProject(board_id=1, name="p")
        assert proj.description is None

    def test_new_column_defaults(self) -> None:
        col = NewColumn(board_id=1, name="c")
        assert col.position == 0

    def test_new_task_defaults(self) -> None:
        task = NewTask(board_id=1, title="t", column_id=1)
        assert task.project_id is None
        assert task.description is None
        assert task.priority == 1
        assert task.due_date is None
        assert task.position == 0
        assert task.start_date is None
        assert task.finish_date is None

    def test_new_task_history_defaults(self) -> None:
        hist = NewTaskHistory(task_id=1, field=TaskField.TITLE, new_value="v", source="tui")
        assert hist.old_value is None


# ---- TaskDetail column required ----


class TestTaskDetailColumn:
    def test_column_is_required(self) -> None:
        ref = TaskRef(
            id=1, board_id=1, title="t", project_id=None, description=None,
            column_id=1, priority=1, due_date=None, position=0,
            archived=False, created_at=0, start_date=None, finish_date=None, group_id=None,
            blocked_by_ids=(), blocks_ids=(),
        )
        with pytest.raises(TypeError, match="column is required"):
            TaskDetail(**shallow_fields(ref, TaskRef))

    def test_other_fields_default(self) -> None:
        col = Column(
            id=1, board_id=1, name="c", position=0,
            archived=False, created_at=0,
        )
        ref = TaskRef(
            id=1, board_id=1, title="t", project_id=None, description=None,
            column_id=1, priority=1, due_date=None, position=0,
            archived=False, created_at=0, start_date=None, finish_date=None, group_id=None,
            blocked_by_ids=(), blocks_ids=(),
        )
        detail = TaskDetail(**shallow_fields(ref, TaskRef), column=col)
        assert detail.column == col
        assert detail.project is None
        assert detail.blocked_by == ()
        assert detail.blocks == ()
        assert detail.history == ()


# ---- Cross-layer consistency tests ----


def _schema_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Extract column names from a live table using PRAGMA table_info."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


class TestTaskFieldMatchesSchema:
    def test_rendered_schema_contains_all_task_fields(self) -> None:
        """read_schema() generates the CHECK from TaskField, so drift is impossible.
        This test verifies the template substitution works correctly."""
        schema = read_schema()
        for field in TaskField:
            assert f"'{field.value}'" in schema, f"TaskField.{field.name} missing from rendered schema"
        assert "__TASK_FIELD_VALUES__" not in schema, "placeholder was not substituted"


class TestNewBoardFieldsMatchSchema:
    def test_new_board_covers_insertable_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "boards")
        db_defaulted = {"id", "created_at", "archived"}
        new_board_fields = {f.name for f in dataclasses.fields(NewBoard)}
        assert new_board_fields | db_defaulted == schema_cols


class TestNewProjectFieldsMatchSchema:
    def test_new_project_covers_insertable_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "projects")
        db_defaulted = {"id", "created_at", "archived"}
        new_proj_fields = {f.name for f in dataclasses.fields(NewProject)}
        assert new_proj_fields | db_defaulted == schema_cols


class TestNewColumnFieldsMatchSchema:
    def test_new_column_covers_insertable_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "columns")
        db_defaulted = {"id", "created_at", "archived"}
        new_col_fields = {f.name for f in dataclasses.fields(NewColumn)}
        assert new_col_fields | db_defaulted == schema_cols


class TestNewTaskFieldsMatchSchema:
    def test_new_task_covers_insertable_columns(self, conn: sqlite3.Connection) -> None:
        """NewTask fields + DB-defaulted/service-managed columns should cover all tasks columns."""
        schema_cols = _schema_columns(conn, "tasks")
        db_defaulted = {"id", "created_at", "archived"}
        # group_id is managed by assign_task_to_group, not at insert time
        service_managed = {"group_id"}
        new_task_fields = {f.name for f in dataclasses.fields(NewTask)}
        assert new_task_fields | db_defaulted | service_managed == schema_cols


class TestNewTaskHistoryFieldsMatchSchema:
    def test_new_task_history_covers_insertable_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "task_history")
        db_defaulted = {"id", "changed_at"}
        new_hist_fields = {f.name for f in dataclasses.fields(NewTaskHistory)}
        assert new_hist_fields | db_defaulted == schema_cols


class TestPersistedBoardFieldsMatchSchema:
    def test_board_fields_match_schema_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "boards")
        board_fields = {f.name for f in dataclasses.fields(Board)}
        assert board_fields == schema_cols


class TestPersistedProjectFieldsMatchSchema:
    def test_project_fields_match_schema_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "projects")
        proj_fields = {f.name for f in dataclasses.fields(Project)}
        assert proj_fields == schema_cols


class TestPersistedColumnFieldsMatchSchema:
    def test_column_fields_match_schema_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "columns")
        col_fields = {f.name for f in dataclasses.fields(Column)}
        assert col_fields == schema_cols


class TestPersistedTaskFieldsMatchSchema:
    def test_task_fields_match_schema_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "tasks")
        task_fields = {f.name for f in dataclasses.fields(Task)}
        assert task_fields == schema_cols


class TestPersistedTaskHistoryFieldsMatchSchema:
    def test_task_history_fields_match_schema_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "task_history")
        hist_fields = {f.name for f in dataclasses.fields(TaskHistory)}
        assert hist_fields == schema_cols


# ---- Mapper field coverage tests ----


class TestMapperFieldCoverage:
    """Ensure row_to_* mappers populate every field on the target model."""

    def test_row_to_board_populates_all_fields(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            board_id = insert_board(conn)
        row = conn.execute("SELECT * FROM boards WHERE id = ?", (board_id,)).fetchone()
        board = row_to_board(row)
        expected = {f.name for f in dataclasses.fields(Board)}
        actual = {f.name for f in dataclasses.fields(board) if getattr(board, f.name) is not None}
        assert actual == expected

    def test_row_to_column_populates_all_fields(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            board_id = insert_board(conn)
            col_id = insert_column(conn, board_id)
        row = conn.execute("SELECT * FROM columns WHERE id = ?", (col_id,)).fetchone()
        col = row_to_column(row)
        expected = {f.name for f in dataclasses.fields(Column)}
        actual = {f.name for f in dataclasses.fields(col) if getattr(col, f.name) is not None}
        assert actual == expected

    def test_row_to_project_populates_all_fields(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            board_id = insert_board(conn)
            proj_id = insert_project(conn, board_id)
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (proj_id,)).fetchone()
        proj = row_to_project(row)
        expected = {f.name for f in dataclasses.fields(Project)}
        # description may be non-None from the helper, so all fields populated
        actual = {f.name for f in dataclasses.fields(proj) if getattr(proj, f.name) is not None}
        assert actual == expected

    def test_row_to_task_populates_all_non_nullable_fields(
        self, seeded: FullSeed,
    ) -> None:
        row = seeded.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (seeded.task1_id,),
        ).fetchone()
        task = row_to_task(row)
        non_nullable = {
            f.name for f in dataclasses.fields(Task)
            if "None" not in str(Task.__dataclass_fields__[f.name].type)
        }
        actual = {f.name for f in dataclasses.fields(task) if getattr(task, f.name) is not None}
        assert non_nullable <= actual

    def test_row_to_task_history_populates_all_fields(
        self, seeded: FullSeed,
    ) -> None:
        row = seeded.conn.execute(
            "SELECT * FROM task_history WHERE id = ?", (seeded.history_id,),
        ).fetchone()
        hist = row_to_task_history(row)
        # old_value is nullable, rest should be populated
        non_nullable = {
            f.name for f in dataclasses.fields(TaskHistory)
            if f.name != "old_value"
        }
        actual = {f.name for f in dataclasses.fields(hist) if getattr(hist, f.name) is not None}
        assert non_nullable <= actual
