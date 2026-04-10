from __future__ import annotations

import dataclasses
import sqlite3
from typing import NamedTuple

import pytest

from helpers import (
    insert_workspace,
    insert_status,
    insert_project,
    insert_task,
    insert_task_dependency,
    insert_task_history,
)
from sticky_notes.connection import read_schema, transaction
from sticky_notes.mappers import (
    group_to_detail,
    group_to_ref,
    project_to_detail,
    row_to_workspace,
    row_to_status,
    row_to_project,
    row_to_task,
    row_to_task_history,
    shallow_fields,
    task_to_detail,
    task_to_list_item,
)
from sticky_notes.models import (
    Workspace,
    Status,
    Group,
    NewWorkspace,
    NewStatus,
    NewProject,
    NewTask,
    NewTaskHistory,
    Project,
    Task,
    TaskField,
    TaskHistory,
)
from sticky_notes.service_models import GroupDetail, GroupRef, ProjectDetail, TaskDetail, TaskListItem


# ---- Seed helpers ----


class FullSeed(NamedTuple):
    conn: sqlite3.Connection
    workspace_id: int
    project_id: int
    status_id: int
    task1_id: int
    task2_id: int
    history_id: int


@pytest.fixture
def seeded(conn: sqlite3.Connection) -> FullSeed:
    """Full data graph for tests that need tasks, deps, and history."""
    with transaction(conn):
        workspace_id = insert_workspace(conn)
        project_id = insert_project(conn, workspace_id)
        status_id = insert_status(conn, workspace_id)
        task1_id = insert_task(
            conn, workspace_id, "task1", status_id, project_id, priority=5,
        )
        task2_id = insert_task(conn, workspace_id, "task2", status_id, priority=3)
        insert_task_dependency(conn, task1_id, task2_id)
        history_id = insert_task_history(
            conn, task1_id, field="title", old_value="old",
            new_value="task1", source="tui",
        )
    return FullSeed(
        conn=conn,
        workspace_id=workspace_id,
        project_id=project_id,
        status_id=status_id,
        task1_id=task1_id,
        task2_id=task2_id,
        history_id=history_id,
    )


# ---- Row → model tests ----


class TestRowToWorkspace:
    def test_maps_row(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn)
        row = conn.execute(
            "SELECT * FROM workspaces WHERE id = ?", (workspace_id,),
        ).fetchone()
        workspace = row_to_workspace(row)
        assert isinstance(workspace, Workspace)
        assert workspace.id == workspace_id
        assert workspace.name == "workspace1"
        assert workspace.archived is False

    def test_archived_is_bool(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn)
        with transaction(conn):
            conn.execute("UPDATE workspaces SET archived = 1 WHERE id = ?", (workspace_id,))
        row = conn.execute(
            "SELECT * FROM workspaces WHERE id = ?", (workspace_id,),
        ).fetchone()
        workspace = row_to_workspace(row)
        assert workspace.archived is True


class TestRowToStatus:
    def test_maps_row(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn)
            col_id = insert_status(conn, workspace_id)
        row = conn.execute(
            "SELECT * FROM statuses WHERE id = ?", (col_id,),
        ).fetchone()
        col = row_to_status(row)
        assert isinstance(col, Status)
        assert col.id == col_id
        assert col.name == "todo"
        assert col.archived is False
        assert isinstance(col.created_at, int)

    def test_archived_is_bool(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn)
            col_id = insert_status(conn, workspace_id)
        with transaction(conn):
            conn.execute("UPDATE statuses SET archived = 1 WHERE id = ?", (col_id,))
        row = conn.execute(
            "SELECT * FROM statuses WHERE id = ?", (col_id,),
        ).fetchone()
        col = row_to_status(row)
        assert col.archived is True


class TestRowToProject:
    def test_maps_row(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn)
            proj_id = insert_project(conn, workspace_id)
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (proj_id,),
        ).fetchone()
        project = row_to_project(row)
        assert isinstance(project, Project)
        assert project.name == "proj1"
        assert project.description == "desc"

    def test_archived_is_bool(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn)
            proj_id = insert_project(conn, workspace_id)
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
            "workspace_id": 1,
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
    def test_extracts_all_fields(self) -> None:
        task = Task(
            id=1, workspace_id=1, title="t", project_id=None, description=None,
            status_id=1, priority=1, due_date=None, position=0,
            archived=False, created_at=0, start_date=None, finish_date=None, group_id=None,
            metadata={},
        )
        fields = shallow_fields(task, Task)
        assert set(fields.keys()) == {
            "id", "workspace_id", "title", "project_id", "description",
            "status_id", "priority", "due_date", "position",
            "archived", "created_at", "start_date", "finish_date", "group_id",
            "metadata",
        }

    def test_rejects_non_dataclass(self) -> None:
        with pytest.raises(TypeError, match="is not a dataclass"):
            shallow_fields("not a dataclass", str)

    def test_rejects_wrong_instance_type(self) -> None:
        workspace = Workspace(id=1, name="b", archived=False, created_at=0, metadata={})
        with pytest.raises(TypeError, match="is not an instance of"):
            shallow_fields(workspace, Task)


# ---- Mapper tests ----


def _task() -> Task:
    return Task(
        id=1, workspace_id=1, title="t", project_id=None, description=None,
        status_id=1, priority=1, due_date=None, position=0,
        archived=False, created_at=0, start_date=None, finish_date=None, group_id=None,
        metadata={},
    )


def _status() -> Status:
    return Status(id=1, workspace_id=1, name="todo", archived=False, created_at=0)


def _group() -> Group:
    return Group(id=1, workspace_id=1, project_id=1, title="g", description=None, parent_id=None, position=0, archived=False, created_at=0, metadata={})


class TestTaskToListItem:
    def test_creates_list_item(self) -> None:
        item = task_to_list_item(_task(), project_name="MyProj", tag_names=("a", "b"))
        assert isinstance(item, TaskListItem)
        assert item.title == "t"
        assert item.project_name == "MyProj"
        assert item.tag_names == ("a", "b")

    def test_task_fields_copied(self) -> None:
        task = _task()
        item = task_to_list_item(task, project_name=None, tag_names=())
        for f in dataclasses.fields(task):
            assert getattr(item, f.name) == getattr(task, f.name)

    def test_defaults(self) -> None:
        item = task_to_list_item(_task(), project_name=None, tag_names=())
        assert item.project_name is None
        assert item.tag_names == ()


class TestTaskToDetail:
    def test_creates_detail(self) -> None:
        status = _status()
        detail = task_to_detail(
            _task(), status=status, project=None, group=None,
            blocked_by=(), blocks=(), history=(),
        )
        assert isinstance(detail, TaskDetail)
        assert detail.status == status
        assert detail.title == "t"

    def test_task_fields_copied(self) -> None:
        task = _task()
        detail = task_to_detail(
            task, status=_status(), project=None, group=None,
            blocked_by=(), blocks=(), history=(),
        )
        for f in dataclasses.fields(task):
            assert getattr(detail, f.name) == getattr(task, f.name)

    def test_hydrated_defaults(self) -> None:
        detail = task_to_detail(
            _task(), status=_status(), project=None, group=None,
            blocked_by=(), blocks=(), history=(),
        )
        assert detail.project is None
        assert detail.group is None
        assert detail.blocked_by == ()
        assert detail.blocks == ()
        assert detail.history == ()
        assert detail.tags == ()

    def test_status_is_required_at_construction(self) -> None:
        """status is a plain required field — omitting it is a TypeError from Python."""
        with pytest.raises(TypeError):
            task_to_detail(  # type: ignore[call-arg]
                _task(), project=None, group=None,
                blocked_by=(), blocks=(), history=(),
            )


class TestProjectToDetail:
    def test_creates_detail(self) -> None:
        project = Project(id=1, workspace_id=1, name="p", description=None, archived=False, created_at=0, metadata={})
        task = _task()
        detail = project_to_detail(project, tasks=(task,))
        assert isinstance(detail, ProjectDetail)
        assert detail.name == "p"
        assert detail.tasks == (task,)

    def test_project_fields_copied(self) -> None:
        project = Project(id=1, workspace_id=1, name="p", description=None, archived=False, created_at=0, metadata={})
        detail = project_to_detail(project, tasks=())
        for f in dataclasses.fields(project):
            assert getattr(detail, f.name) == getattr(project, f.name)


class TestGroupToRef:
    def test_creates_ref(self) -> None:
        group = _group()
        ref = group_to_ref(group, task_ids=(1, 2), child_ids=(3,))
        assert isinstance(ref, GroupRef)
        assert ref.title == "g"
        assert ref.task_ids == (1, 2)
        assert ref.child_ids == (3,)

    def test_group_fields_copied(self) -> None:
        group = _group()
        ref = group_to_ref(group, task_ids=(), child_ids=())
        for f in dataclasses.fields(group):
            assert getattr(ref, f.name) == getattr(group, f.name)


class TestGroupToDetail:
    def test_creates_detail(self) -> None:
        group = _group()
        child = Group(id=2, workspace_id=1, project_id=1, title="child", description=None, parent_id=1, position=0, archived=False, created_at=0, metadata={})
        detail = group_to_detail(group, tasks=(), children=(child,), parent=None)
        assert isinstance(detail, GroupDetail)
        assert detail.title == "g"
        assert detail.children == (child,)
        assert detail.parent is None

    def test_group_fields_copied(self) -> None:
        group = _group()
        detail = group_to_detail(group, tasks=(), children=(), parent=None)
        for f in dataclasses.fields(group):
            assert getattr(detail, f.name) == getattr(group, f.name)


# ---- Pre-insert default tests ----


class TestPreInsertDefaults:
    def test_new_workspace_has_no_defaults(self) -> None:
        workspace = NewWorkspace(name="b")
        assert workspace.name == "b"

    def test_new_project_defaults(self) -> None:
        proj = NewProject(workspace_id=1, name="p")
        assert proj.description is None

    def test_new_status_defaults(self) -> None:
        col = NewStatus(workspace_id=1, name="c")
        assert col.name == "c"

    def test_new_task_defaults(self) -> None:
        task = NewTask(workspace_id=1, title="t", status_id=1)
        assert task.project_id is None
        assert task.description is None
        assert task.priority == 1
        assert task.due_date is None
        assert task.position == 0
        assert task.start_date is None
        assert task.finish_date is None

    def test_new_task_history_defaults(self) -> None:
        hist = NewTaskHistory(task_id=1, workspace_id=1, field=TaskField.TITLE, new_value="v", source="tui")
        assert hist.old_value is None


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


class TestNewWorkspaceFieldsMatchSchema:
    def test_new_workspace_covers_insertable_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "workspaces")
        db_defaulted = {"id", "created_at", "archived", "metadata"}
        new_workspace_fields = {f.name for f in dataclasses.fields(NewWorkspace)}
        assert new_workspace_fields | db_defaulted == schema_cols


class TestNewProjectFieldsMatchSchema:
    def test_new_project_covers_insertable_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "projects")
        db_defaulted = {"id", "created_at", "archived", "metadata"}
        new_proj_fields = {f.name for f in dataclasses.fields(NewProject)}
        assert new_proj_fields | db_defaulted == schema_cols


class TestNewStatusFieldsMatchSchema:
    def test_new_status_covers_insertable_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "statuses")
        db_defaulted = {"id", "created_at", "archived"}
        new_status_fields = {f.name for f in dataclasses.fields(NewStatus)}
        assert new_status_fields | db_defaulted == schema_cols


class TestNewTaskFieldsMatchSchema:
    def test_new_task_covers_insertable_columns(self, conn: sqlite3.Connection) -> None:
        """NewTask fields + DB-defaulted/service-managed columns should cover all tasks columns."""
        schema_cols = _schema_columns(conn, "tasks")
        db_defaulted = {"id", "created_at", "archived"}
        # metadata starts as the SQL default '{}' and is managed via json_set afterwards
        service_managed = {"metadata"}
        new_task_fields = {f.name for f in dataclasses.fields(NewTask)}
        assert new_task_fields | db_defaulted | service_managed == schema_cols


class TestNewTaskHistoryFieldsMatchSchema:
    def test_new_task_history_covers_insertable_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "task_history")
        db_defaulted = {"id", "changed_at"}
        new_hist_fields = {f.name for f in dataclasses.fields(NewTaskHistory)}
        assert new_hist_fields | db_defaulted == schema_cols


class TestPersistedWorkspaceFieldsMatchSchema:
    def test_workspace_fields_match_schema_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "workspaces")
        workspace_fields = {f.name for f in dataclasses.fields(Workspace)}
        assert workspace_fields == schema_cols


class TestPersistedProjectFieldsMatchSchema:
    def test_project_fields_match_schema_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "projects")
        proj_fields = {f.name for f in dataclasses.fields(Project)}
        assert proj_fields == schema_cols


class TestPersistedStatusFieldsMatchSchema:
    def test_status_fields_match_schema_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "statuses")
        status_fields = {f.name for f in dataclasses.fields(Status)}
        assert status_fields == schema_cols


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

    def test_row_to_workspace_populates_all_fields(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn)
        row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        workspace = row_to_workspace(row)
        expected = {f.name for f in dataclasses.fields(Workspace)}
        actual = {f.name for f in dataclasses.fields(workspace) if getattr(workspace, f.name) is not None}
        assert actual == expected

    def test_row_to_status_populates_all_fields(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn)
            col_id = insert_status(conn, workspace_id)
        row = conn.execute("SELECT * FROM statuses WHERE id = ?", (col_id,)).fetchone()
        col = row_to_status(row)
        expected = {f.name for f in dataclasses.fields(Status)}
        actual = {f.name for f in dataclasses.fields(col) if getattr(col, f.name) is not None}
        assert actual == expected

    def test_row_to_project_populates_all_fields(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn)
            proj_id = insert_project(conn, workspace_id)
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


class TestRowToTaskMetadata:
    def test_parses_json_metadata(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            wid = insert_workspace(conn)
            sid = insert_status(conn, wid)
            tid = insert_task(conn, wid, "t", sid)
            conn.execute(
                '''UPDATE tasks SET metadata = '{"branch":"feat/kv","jira":"PROJ-1"}' WHERE id = ?''',
                (tid,),
            )
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
        task = row_to_task(row)
        assert task.metadata == {"branch": "feat/kv", "jira": "PROJ-1"}

    def test_empty_metadata_default(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            wid = insert_workspace(conn)
            sid = insert_status(conn, wid)
            tid = insert_task(conn, wid, "t", sid)
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
        task = row_to_task(row)
        assert task.metadata == {}
