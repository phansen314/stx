from __future__ import annotations

import dataclasses
import sqlite3
from typing import NamedTuple

import pytest
from helpers import (
    insert_journal_entry,
    insert_status,
    insert_task,
    insert_task_dependency,
    insert_workspace,
)

from stx.connection import read_schema, transaction
from stx.mappers import (
    DESCRIPTION_NOT_LOADED,
    group_to_detail,
    group_to_ref,
    row_to_journal_entry,
    row_to_status,
    row_to_task,
    row_to_workspace,
    shallow_fields,
    task_to_detail,
    task_to_list_item,
)
from stx.repository import _TASK_COLUMNS_NO_DESC, _GROUP_COLUMNS_NO_DESC
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
    Workspace,
)
from stx.service_models import (
    GroupDetail,
    GroupRef,
    TaskDetail,
    TaskListItem,
)

# ---- Seed helpers ----


class FullSeed(NamedTuple):
    conn: sqlite3.Connection
    workspace_id: int
    status_id: int
    task1_id: int
    task2_id: int
    history_id: int


@pytest.fixture
def seeded(conn: sqlite3.Connection) -> FullSeed:
    """Full data graph for tests that need tasks, deps, and history."""
    with transaction(conn):
        workspace_id = insert_workspace(conn)
        status_id = insert_status(conn, workspace_id)
        task1_id = insert_task(
            conn,
            workspace_id,
            "task1",
            status_id,
            priority=5,
        )
        task2_id = insert_task(conn, workspace_id, "task2", status_id, priority=3)
        insert_task_dependency(conn, task1_id, task2_id)
        history_id = insert_journal_entry(
            conn,
            task1_id,
            field="title",
            old_value="old",
            new_value="task1",
            source="tui",
        )
    return FullSeed(
        conn=conn,
        workspace_id=workspace_id,
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
            "SELECT * FROM workspaces WHERE id = ?",
            (workspace_id,),
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
            "SELECT * FROM workspaces WHERE id = ?",
            (workspace_id,),
        ).fetchone()
        workspace = row_to_workspace(row)
        assert workspace.archived is True


class TestRowToStatus:
    def test_maps_row(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn)
            col_id = insert_status(conn, workspace_id)
        row = conn.execute(
            "SELECT * FROM statuses WHERE id = ?",
            (col_id,),
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
            "SELECT * FROM statuses WHERE id = ?",
            (col_id,),
        ).fetchone()
        col = row_to_status(row)
        assert col.archived is True


class TestRowToTask:
    def test_maps_row(self, seeded: FullSeed) -> None:
        row = seeded.conn.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (seeded.task1_id,),
        ).fetchone()
        task = row_to_task(row)
        assert isinstance(task, Task)
        assert task.title == "task1"
        assert task.priority == 5
        assert task.archived is False

    def test_maps_null_optional_fields(self, seeded: FullSeed) -> None:
        """Task with NULL description, due_date, start_date, finish_date."""
        row = seeded.conn.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (seeded.task2_id,),
        ).fetchone()
        task = row_to_task(row)
        assert task.description is None
        assert task.due_date is None
        assert task.start_date is None
        assert task.finish_date is None


class TestRowToJournalEntry:
    def test_maps_row(self, seeded: FullSeed) -> None:
        row = seeded.conn.execute(
            "SELECT * FROM journal WHERE id = ?",
            (seeded.history_id,),
        ).fetchone()
        entry = row_to_journal_entry(row)
        assert isinstance(entry, JournalEntry)
        assert entry.entity_type == EntityType.TASK
        assert entry.entity_id == seeded.task1_id
        assert entry.field == "title"
        assert entry.old_value == "old"
        assert entry.new_value == "task1"
        assert entry.source == "tui"


# ---- shallow_fields tests ----


class TestShallowFields:
    def test_extracts_all_fields(self) -> None:
        task = Task(
            id=1,
            workspace_id=1,
            title="t",
            description=None,
            status_id=1,
            priority=1,
            due_date=None,
            archived=False,
            created_at=0,
            start_date=None,
            finish_date=None,
            group_id=None,
            metadata={},
        )
        fields = shallow_fields(task, Task)
        assert set(fields.keys()) == {
            "id",
            "workspace_id",
            "title",
            "description",
            "status_id",
            "priority",
            "due_date",
            "archived",
            "created_at",
            "start_date",
            "finish_date",
            "group_id",
            "metadata",
            "done",
            "version",
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
        id=1,
        workspace_id=1,
        title="t",
        description=None,
        status_id=1,
        priority=1,
        due_date=None,
        archived=False,
        created_at=0,
        start_date=None,
        finish_date=None,
        group_id=None,
        metadata={},
    )


def _status() -> Status:
    return Status(id=1, workspace_id=1, name="todo", archived=False, created_at=0)


def _group() -> Group:
    return Group(
        id=1,
        workspace_id=1,
        title="g",
        description=None,
        parent_id=None,
        archived=False,
        created_at=0,
        metadata={},
    )


class TestTaskToListItem:
    def test_creates_list_item(self) -> None:
        item = task_to_list_item(_task())
        assert isinstance(item, TaskListItem)
        assert item.title == "t"

    def test_task_fields_copied(self) -> None:
        task = _task()
        item = task_to_list_item(task)
        for f in dataclasses.fields(task):
            assert getattr(item, f.name) == getattr(task, f.name)


class TestTaskToDetail:
    def test_creates_detail(self) -> None:
        status = _status()
        detail = task_to_detail(
            _task(),
            status=status,
            group=None,
            edge_sources=(),
            edge_targets=(),
            history=(),
        )
        assert isinstance(detail, TaskDetail)
        assert detail.status == status
        assert detail.title == "t"

    def test_task_fields_copied(self) -> None:
        task = _task()
        detail = task_to_detail(
            task,
            status=_status(),
            group=None,
            edge_sources=(),
            edge_targets=(),
            history=(),
        )
        for f in dataclasses.fields(task):
            assert getattr(detail, f.name) == getattr(task, f.name)

    def test_hydrated_defaults(self) -> None:
        detail = task_to_detail(
            _task(),
            status=_status(),
            group=None,
            edge_sources=(),
            edge_targets=(),
            history=(),
        )
        assert detail.group is None
        assert detail.edge_sources == ()
        assert detail.edge_targets == ()
        assert detail.history == ()

    def test_status_is_required_at_construction(self) -> None:
        """status is a plain required field — omitting it is a TypeError from Python."""
        with pytest.raises(TypeError):
            task_to_detail(  # type: ignore[call-arg]
                _task(),
                group=None,
                edge_sources=(),
                edge_targets=(),
                history=(),
            )


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
        child = Group(
            id=2,
            workspace_id=1,
            title="child",
            description=None,
            parent_id=1,
            archived=False,
            created_at=0,
            metadata={},
        )
        detail = group_to_detail(
            group,
            tasks=(),
            children=(child,),
            parent=None,
            edge_sources=(),
            edge_targets=(),
        )
        assert isinstance(detail, GroupDetail)
        assert detail.title == "g"
        assert detail.children == (child,)
        assert detail.parent is None

    def test_group_fields_copied(self) -> None:
        group = _group()
        detail = group_to_detail(
            group,
            tasks=(),
            children=(),
            parent=None,
            edge_sources=(),
            edge_targets=(),
        )
        for f in dataclasses.fields(group):
            assert getattr(detail, f.name) == getattr(group, f.name)


# ---- Pre-insert default tests ----


class TestPreInsertDefaults:
    def test_new_workspace_has_no_defaults(self) -> None:
        workspace = NewWorkspace(name="b")
        assert workspace.name == "b"

    def test_new_group_defaults(self) -> None:
        grp = NewGroup(workspace_id=1, title="g")
        assert grp.description is None
        assert grp.parent_id is None

    def test_new_status_defaults(self) -> None:
        col = NewStatus(workspace_id=1, name="c")
        assert col.name == "c"

    def test_new_task_defaults(self) -> None:
        task = NewTask(workspace_id=1, title="t", status_id=1)
        assert task.description is None
        assert task.priority == 1
        assert task.due_date is None
        assert task.start_date is None
        assert task.finish_date is None
        assert task.group_id is None

    def test_new_journal_entry_defaults(self) -> None:
        hist = NewJournalEntry(
            entity_type=EntityType.TASK,
            entity_id=1,
            workspace_id=1,
            field="title",
            new_value="v",
            source="tui",
        )
        assert hist.old_value is None


# ---- Cross-layer consistency tests ----


def _schema_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Extract column names from a live table using PRAGMA table_info."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


class TestTaskFieldMatchesSchema:
    def test_rendered_schema_contains_journal_table(self) -> None:
        """read_schema() returns the schema with the journal table (no task_history)."""
        schema = read_schema()
        assert "CREATE TABLE IF NOT EXISTS journal" in schema
        assert "task_history" not in schema


class TestNewWorkspaceFieldsMatchSchema:
    def test_new_workspace_covers_insertable_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "workspaces")
        db_defaulted = {"id", "created_at", "archived", "metadata"}
        new_workspace_fields = {f.name for f in dataclasses.fields(NewWorkspace)}
        assert new_workspace_fields | db_defaulted == schema_cols


class TestNewGroupFieldsMatchSchema:
    def test_new_group_covers_insertable_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "groups")
        db_defaulted = {"id", "created_at", "archived", "metadata"}
        new_group_fields = {f.name for f in dataclasses.fields(NewGroup)}
        assert new_group_fields | db_defaulted == schema_cols


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


class TestNewJournalEntryFieldsMatchSchema:
    def test_new_journal_entry_covers_insertable_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "journal")
        db_defaulted = {"id", "changed_at"}
        new_entry_fields = {f.name for f in dataclasses.fields(NewJournalEntry)}
        assert new_entry_fields | db_defaulted == schema_cols


class TestPersistedWorkspaceFieldsMatchSchema:
    def test_workspace_fields_match_schema_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "workspaces")
        workspace_fields = {f.name for f in dataclasses.fields(Workspace)}
        assert workspace_fields == schema_cols


class TestPersistedGroupFieldsMatchSchema:
    def test_group_fields_match_schema_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "groups")
        group_fields = {f.name for f in dataclasses.fields(Group)}
        assert group_fields == schema_cols


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


class TestPersistedJournalEntryFieldsMatchSchema:
    def test_journal_entry_fields_match_schema_columns(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "journal")
        entry_fields = {f.name for f in dataclasses.fields(JournalEntry)}
        assert entry_fields == schema_cols


# ---- Mapper field coverage tests ----


class TestMapperFieldCoverage:
    """Ensure row_to_* mappers populate every field on the target model."""

    def test_row_to_workspace_populates_all_fields(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            workspace_id = insert_workspace(conn)
        row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        workspace = row_to_workspace(row)
        expected = {f.name for f in dataclasses.fields(Workspace)}
        actual = {
            f.name for f in dataclasses.fields(workspace) if getattr(workspace, f.name) is not None
        }
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

    def test_row_to_task_populates_all_non_nullable_fields(
        self,
        seeded: FullSeed,
    ) -> None:
        row = seeded.conn.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (seeded.task1_id,),
        ).fetchone()
        task = row_to_task(row)
        non_nullable = {
            f.name
            for f in dataclasses.fields(Task)
            if "None" not in str(Task.__dataclass_fields__[f.name].type)
        }
        actual = {f.name for f in dataclasses.fields(task) if getattr(task, f.name) is not None}
        assert non_nullable <= actual

    def test_row_to_journal_entry_populates_all_fields(
        self,
        seeded: FullSeed,
    ) -> None:
        row = seeded.conn.execute(
            "SELECT * FROM journal WHERE id = ?",
            (seeded.history_id,),
        ).fetchone()
        entry = row_to_journal_entry(row)
        # old_value is nullable, rest should be populated
        non_nullable = {f.name for f in dataclasses.fields(JournalEntry) if f.name != "old_value"}
        actual = {f.name for f in dataclasses.fields(entry) if getattr(entry, f.name) is not None}
        assert non_nullable <= actual


class TestRowToTaskMetadata:
    def test_parses_json_metadata(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            wid = insert_workspace(conn)
            sid = insert_status(conn, wid)
            tid = insert_task(conn, wid, "t", sid)
            conn.execute(
                """UPDATE tasks SET metadata = '{"branch":"feat/kv","jira":"PROJ-1"}' WHERE id = ?""",
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


# ---- Bulk column constant drift tests ----


def _parse_column_constant(constant: str) -> set[str]:
    """Extract real column names from a column constant, ignoring computed expressions."""
    cols = set()
    for part in constant.split(","):
        part = part.strip()
        if not part or " AS " in part or "(" in part:
            continue
        cols.add(part)
    return cols


class TestBulkColumnConstants:
    def test_task_columns_no_desc_matches_schema(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "tasks")
        expected = schema_cols - {"description"}
        actual = _parse_column_constant(_TASK_COLUMNS_NO_DESC)
        assert actual == expected

    def test_group_columns_no_desc_matches_schema(self, conn: sqlite3.Connection) -> None:
        schema_cols = _schema_columns(conn, "groups")
        expected = schema_cols - {"description"}
        actual = _parse_column_constant(_GROUP_COLUMNS_NO_DESC)
        assert actual == expected


# ---- Sentinel description tests ----


class TestDescriptionSentinel:
    def test_task_with_description_gets_sentinel(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            wid = insert_workspace(conn)
            sid = insert_status(conn, wid)
            tid = insert_task(conn, wid, "t", sid, description="hello")
        row = conn.execute(
            f"SELECT {_TASK_COLUMNS_NO_DESC} FROM tasks WHERE id = ?", (tid,)
        ).fetchone()
        task = row_to_task(row)
        assert task.description == DESCRIPTION_NOT_LOADED

    def test_task_without_description_gets_none(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            wid = insert_workspace(conn)
            sid = insert_status(conn, wid)
            tid = insert_task(conn, wid, "t", sid)
        row = conn.execute(
            f"SELECT {_TASK_COLUMNS_NO_DESC} FROM tasks WHERE id = ?", (tid,)
        ).fetchone()
        task = row_to_task(row)
        assert task.description is None

    def test_task_full_select_gets_real_description(self, conn: sqlite3.Connection) -> None:
        with transaction(conn):
            wid = insert_workspace(conn)
            sid = insert_status(conn, wid)
            tid = insert_task(conn, wid, "t", sid, description="hello")
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
        task = row_to_task(row)
        assert task.description == "hello"
