from __future__ import annotations

import sqlite3

import pytest

from stx import service
from stx.models import (
    EntityType,
    Group,
    JournalEntry,
    Status,
    Task,
    TaskFilter,
    Workspace,
)
from stx.service_models import (
    GroupDetail,
    GroupRef,
    TaskDetail,
    TaskListItem,
    WorkspaceContext,
    WorkspaceListView,
)
from tests.helpers import (
    insert_group as _raw_insert_group,
)
from tests.helpers import (
    insert_status as _raw_insert_status,
)
from tests.helpers import (
    insert_task as _raw_insert_task,
)
from tests.helpers import (
    insert_task_dependency as _raw_insert_task_dependency,
)
from tests.helpers import (
    insert_workspace as _raw_insert_workspace,
)

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


def insert_status(conn: sqlite3.Connection, workspace_id: int, name: str = "todo") -> int:
    rid = _raw_insert_status(conn, workspace_id, name)
    _commit(conn)
    return rid


def insert_task(
    conn: sqlite3.Connection,
    workspace_id: int,
    title: str,
    status_id: int,
    priority: int = 1,
    due_date: int | None = None,
) -> int:
    rid = _raw_insert_task(conn, workspace_id, title, status_id, priority, due_date)
    _commit(conn)
    return rid


def insert_task_dependency(conn: sqlite3.Connection, task_id: int, depends_on_id: int) -> None:
    _raw_insert_task_dependency(conn, task_id, depends_on_id)
    _commit(conn)


def insert_group(
    conn: sqlite3.Connection,
    workspace_id: int,
    title: str = "group1",
    parent_id: int | None = None,
) -> int:
    rid = _raw_insert_group(conn, workspace_id, title, parent_id)
    _commit(conn)
    return rid


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

    def test_list_statuses_only_archived(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        service.create_status(conn, bid, "active")
        old = service.create_status(conn, bid, "old")
        service.update_status(conn, old.id, {"archived": True})
        result = service.list_statuses(conn, bid, only_archived=True)
        assert len(result) == 1
        assert result[0].name == "old"

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


# ---- Task ----


class TestTaskService:
    def test_create(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "do stuff", cid)
        assert isinstance(task, Task)
        assert task.title == "do stuff"
        assert task.priority == 1

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
        assert service.resolve_task_id(conn, bid, "Find me") == task.id

    def test_resolve_task_id_missing_title_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        with pytest.raises(LookupError):
            service.resolve_task_id(conn, bid, "nonexistent task")

    def test_get_detail(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        tid = insert_task(conn, bid, "a", cid)
        detail = service.get_task_detail(conn, tid)
        assert isinstance(detail, TaskDetail)
        assert detail.status.id == cid

    def test_get_task_detail_hydrates_group(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        grp = service.create_group(conn, bid, "Auth")
        task = service.create_task(conn, bid, "t", cid)
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
        # t2 is the source of the edge (points at t1) → outgoing = edge_targets
        assert len(detail.edge_targets) == 1
        assert detail.edge_targets[0].node_id == t1
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

    def test_update_with_no_changes_is_noop(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        result = service.update_task(conn, task.id, {}, "cli")
        assert result.id == task.id
        assert result.title == task.title

    def test_update_records_history(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "old", cid)
        service.update_task(conn, task.id, {"title": "new"}, "tui")
        history = service.list_journal(conn, EntityType.TASK, task.id)
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
        history = service.list_journal(conn, EntityType.TASK, task.id)
        assert len(history) == 0

    def test_update_multiple_fields_records_multiple_history(
        self, conn: sqlite3.Connection
    ) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "old", cid, priority=1)
        service.update_task(conn, task.id, {"title": "new", "priority": 5}, "mcp")
        history = service.list_journal(conn, EntityType.TASK, task.id)
        assert len(history) == 2
        fields = {h.field for h in history}
        assert fields == {"title", "priority"}

    def test_update_none_old_value_stored_as_null(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        assert task.description is None
        service.update_task(conn, task.id, {"description": "added"}, "tui")
        history = service.list_journal(conn, EntityType.TASK, task.id)
        assert len(history) == 1
        assert history[0].old_value is None
        assert history[0].new_value == "added"

    def test_move_task(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        c1 = insert_status(conn, bid, "todo")
        c2 = insert_status(conn, bid, "done")
        task = service.create_task(conn, bid, "t", c1)
        moved = service.move_task(conn, task.id, c2, "tui")
        assert moved.status_id == c2
        history = service.list_journal(conn, EntityType.TASK, task.id)
        assert any(h.field == "status_id" for h in history)

    # ---- Pre-validation ----

    def test_create_priority_unbounded_round_trip(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t_low = service.create_task(conn, bid, "t-low", cid, priority=-1)
        t_high = service.create_task(conn, bid, "t-high", cid, priority=42)
        assert t_low.priority == -1
        assert t_high.priority == 42

    def test_create_priority_non_int_rejected(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        with pytest.raises(ValueError, match="priority"):
            service.create_task(conn, bid, "t", cid, priority="high")  # type: ignore[arg-type]

    def test_create_finish_before_start(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        with pytest.raises(ValueError, match="finish date"):
            service.create_task(conn, bid, "t", cid, start_date=200, finish_date=100)

    def test_update_priority_unbounded(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        updated = service.update_task(conn, task.id, {"priority": 99}, "test")
        assert updated.priority == 99

    def test_update_finish_before_existing_start(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid, start_date=200)
        with pytest.raises(ValueError, match="finish date"):
            service.update_task(conn, task.id, {"finish_date": 100}, "test")

    def test_preview_update_task_rejects_same_invalid_inputs_as_update(
        self, conn: sqlite3.Connection
    ) -> None:
        """Drift guard: preview_update_task must raise on the same invalid
        changes that update_task rejects. Any new validation added to
        update_task (via _validate_task_update) must propagate to preview.
        """
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid, start_date=200)
        # finish before start — date merge edge case shared by both paths
        with pytest.raises(ValueError, match="finish date"):
            service.preview_update_task(conn, task.id, {"finish_date": 100})
        # non-int priority
        with pytest.raises(ValueError, match="priority"):
            service.preview_update_task(conn, task.id, {"priority": "high"})  # type: ignore[dict-item]

    def test_diff_fields_rejects_unknown_key(self, conn: sqlite3.Connection) -> None:
        """_diff_fields must raise AttributeError on typo'd change keys
        rather than silently producing a bogus None-valued entry.
        """
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        with pytest.raises(AttributeError):
            service._diff_fields(task, {"nonexistent_field": "x"})

    def test_diff_fields_with_resolver(self, conn: sqlite3.Connection) -> None:
        """_diff_fields resolvers map raw field values to display values
        for both before and after. Verify the resolver is applied to both
        sides and non-resolved keys pass through unchanged.
        """
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid, priority=2)
        before, after = service._diff_fields(
            task,
            {"priority": 5, "status_id": 999},
            resolvers={"status_id": lambda sid: f"status-{sid}"},
        )
        # priority has no resolver → raw values
        assert before["priority"] == 2
        assert after["priority"] == 5
        # status_id uses resolver on both sides
        assert before["status_id"] == f"status-{cid}"
        assert after["status_id"] == "status-999"

    def test_preview_update_task_after_matches_real_update(self, conn: sqlite3.Connection) -> None:
        """Drift guard: preview's `after` dict must equal the actual field
        values written by update_task for the same changes.
        """
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "orig", cid, priority=2)
        changes = {"title": "renamed", "priority": 4}
        preview = service.preview_update_task(conn, task.id, changes)
        updated = service.update_task(conn, task.id, changes, "test")
        assert preview.after["title"] == updated.title
        assert preview.after["priority"] == updated.priority

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

    def test_update_status_not_found(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        with pytest.raises(LookupError, match="status 999"):
            service.update_task(conn, task.id, {"status_id": 999}, "test")

    # ---- Archival safety ----

    def test_move_to_archived_status_blocked(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        c1 = insert_status(conn, bid, "active")
        c2 = insert_status(conn, bid, "archived")
        service.update_status(conn, c2, {"archived": True})
        task = service.create_task(conn, bid, "t", c1)
        with pytest.raises(ValueError, match="archived"):
            service.update_task(conn, task.id, {"status_id": c2}, "test")

    def test_assign_to_archived_group_blocked(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        gid = insert_group(conn, bid, "g1")
        service.cascade_archive_group(conn, gid, source="test")
        tid = insert_task(conn, bid, "t", cid)
        with pytest.raises(ValueError, match="archived"):
            service.assign_task_to_group(conn, tid, gid, source="test")


# ---- Unified Edge ----


class TestEdgeService:
    def test_add_task_edge(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_edge(conn, ("task", t2), ("task", t1), kind="blocks")
        detail = service.get_task_detail(conn, t2)
        # t2 is the source → outgoing edge shows up in edge_targets
        assert any(ref.node_id == t1 for ref in detail.edge_targets)

    def test_archive_task_edge(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_edge(conn, ("task", t2), ("task", t1), kind="blocks")
        service.archive_edge(conn, ("task", t2), ("task", t1), kind="blocks")
        detail = service.get_task_detail(conn, t2)
        assert detail.edge_sources == ()
        assert detail.edge_targets == ()

    def test_add_self_ref_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        tid = insert_task(conn, bid, "a", cid)
        with pytest.raises(ValueError, match="cannot point to itself"):
            service.add_edge(conn, ("task", tid), ("task", tid), kind="blocks")

    def test_add_cross_workspace_raises(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, "workspace1")
        b2 = insert_workspace(conn, "workspace2")
        c1 = insert_status(conn, b1)
        c2 = insert_status(conn, b2)
        t1 = insert_task(conn, b1, "a", c1)
        t2 = insert_task(conn, b2, "b", c2)
        with pytest.raises(ValueError, match="same workspace"):
            service.add_edge(conn, ("task", t2), ("task", t1), kind="blocks")

    def test_cycle_direct_rejected_for_acyclic_kind(self, conn: sqlite3.Connection) -> None:
        # "blocks" is acyclic by default — direct cycle must be rejected
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_edge(conn, ("task", t1), ("task", t2), kind="blocks")  # t1 -> t2
        with pytest.raises(ValueError, match="cycle"):
            service.add_edge(conn, ("task", t2), ("task", t1), kind="blocks")  # t2 -> t1 (cycle)

    def test_cycle_transitive_rejected_for_acyclic_kind(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        t3 = insert_task(conn, bid, "c", cid)
        service.add_edge(conn, ("task", t1), ("task", t2), kind="blocks")  # t1 -> t2
        service.add_edge(conn, ("task", t2), ("task", t3), kind="blocks")  # t2 -> t3
        with pytest.raises(ValueError, match="cycle"):
            service.add_edge(conn, ("task", t3), ("task", t1), kind="blocks")  # t3 -> t1 (cycle)

    def test_cycle_allowed_for_non_acyclic_kind(self, conn: sqlite3.Connection) -> None:
        # "related-to" is not acyclic by default — cycles are fine
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_edge(conn, ("task", t1), ("task", t2), kind="related-to")
        service.add_edge(conn, ("task", t2), ("task", t1), kind="related-to")  # cycle OK

    def test_cycle_ignores_non_acyclic_path(self, conn: sqlite3.Connection) -> None:
        """A cycle that closes through a non-acyclic edge is NOT rejected.
        Design guarantee: only ``acyclic=1`` edges participate in DAG
        enforcement — a ``related-to`` hop cannot transitively create a cycle
        for ``blocks``."""
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        t3 = insert_task(conn, bid, "c", cid)
        service.add_edge(conn, ("task", t1), ("task", t2), kind="blocks")        # acyclic
        service.add_edge(conn, ("task", t2), ("task", t3), kind="related-to")    # non-acyclic
        # t3 -blocks-> t1 closes the loop only via the related-to hop.
        # Reachability CTE walks only acyclic=1 edges, so t1 is NOT reachable
        # from t3 and this edge must succeed.
        service.add_edge(conn, ("task", t3), ("task", t1), kind="blocks")

    def test_cycle_cross_type_rejected(self, conn: sqlite3.Connection) -> None:
        """Cycle detection must walk heterogeneous node types. Adding
        task → group → task where the closing edge uses an acyclic kind
        must be rejected. A bug in the polymorphic nodes CTE or reachability
        join would silently let this through."""
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        g1 = insert_group(conn, bid, "g")
        service.add_edge(conn, ("task", t1), ("group", g1), kind="blocks")  # t1 -> g1 (acyclic)
        with pytest.raises(ValueError, match="cycle"):
            service.add_edge(conn, ("group", g1), ("task", t1), kind="spawns")  # closes the loop

    def test_cross_type_edge_via_service(self, conn: sqlite3.Connection) -> None:
        """Smoke test for polymorphic add_edge through the service layer
        (task → group). The repo test covers raw insert; this verifies that
        _resolve_edge_node + workspace_id resolution + hydration all work
        across types end-to-end."""
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "t", cid)
        g1 = insert_group(conn, bid, "g")
        service.add_edge(conn, ("task", t1), ("group", g1), kind="spawns")
        detail = service.get_task_detail(conn, t1)
        targets = {(ref.node_type, ref.node_id) for ref in detail.edge_targets}
        assert ("group", g1) in targets

    def test_non_cycle_allowed(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        t3 = insert_task(conn, bid, "c", cid)
        service.add_edge(conn, ("task", t1), ("task", t2), kind="blocks")  # t1 -> t2
        service.add_edge(conn, ("task", t1), ("task", t3), kind="blocks")  # t1 -> t3 (diamond)
        service.add_edge(conn, ("task", t2), ("task", t3), kind="blocks")  # t2 -> t3 (converge)
        detail = service.get_task_detail(conn, t1)
        # t1 sources two outgoing edges (→t2, →t3) → edge_targets
        assert {ref.node_id for ref in detail.edge_targets} == {t2, t3}

    def test_add_duplicate_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_edge(conn, ("task", t1), ("task", t2), kind="blocks")
        with pytest.raises(ValueError, match="edge already exists"):
            service.add_edge(conn, ("task", t1), ("task", t2), kind="blocks")

    def test_add_with_kind_stored(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_edge(conn, ("task", t1), ("task", t2), kind="blocks")
        row = conn.execute(
            "SELECT kind FROM edges WHERE from_type='task' AND from_id=? AND to_id=?", (t1, t2)
        ).fetchone()
        assert row is not None
        assert row["kind"] == "blocks"

    def test_kind_normalized_to_lowercase(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_edge(conn, ("task", t1), ("task", t2), kind="Blocks")
        row = conn.execute(
            "SELECT kind FROM edges WHERE from_type='task' AND from_id=? AND to_id=?", (t1, t2)
        ).fetchone()
        assert row["kind"] == "blocks"

    def test_invalid_kind_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        with pytest.raises(ValueError, match="edge kind"):
            service.add_edge(conn, ("task", t1), ("task", t2), kind="invalid kind!")

    def test_add_group_edge(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        g1 = insert_group(conn, bid, "g1")
        g2 = insert_group(conn, bid, "g2")
        service.add_edge(conn, ("group", g1), ("group", g2), kind="blocks")
        edges = service.list_edges(conn, bid)
        assert any(e.from_id == g1 and e.to_id == g2 and e.kind == "blocks" for e in edges)

    def test_archive_group_edge(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        g1 = insert_group(conn, bid, "g1")
        g2 = insert_group(conn, bid, "g2")
        service.add_edge(conn, ("group", g1), ("group", g2), kind="blocks")
        service.archive_edge(conn, ("group", g1), ("group", g2), kind="blocks")
        assert service.list_edges(conn, bid) == ()

    def test_group_self_ref_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        g1 = insert_group(conn, bid, "g1")
        with pytest.raises(ValueError, match="cannot point to itself"):
            service.add_edge(conn, ("group", g1), ("group", g1), kind="blocks")

    def test_group_cycle_rejected(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        g1 = insert_group(conn, bid, "g1")
        g2 = insert_group(conn, bid, "g2")
        service.add_edge(conn, ("group", g1), ("group", g2), kind="blocks")
        with pytest.raises(ValueError, match="cycle"):
            service.add_edge(conn, ("group", g2), ("group", g1), kind="blocks")

    def test_group_transitive_cycle_rejected(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        g1 = insert_group(conn, bid, "g1")
        g2 = insert_group(conn, bid, "g2")
        g3 = insert_group(conn, bid, "g3")
        service.add_edge(conn, ("group", g1), ("group", g2), kind="blocks")
        service.add_edge(conn, ("group", g2), ("group", g3), kind="blocks")
        with pytest.raises(ValueError, match="cycle"):
            service.add_edge(conn, ("group", g3), ("group", g1), kind="blocks")

    def test_group_edge_duplicate_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        g1 = insert_group(conn, bid, "g1")
        g2 = insert_group(conn, bid, "g2")
        service.add_edge(conn, ("group", g1), ("group", g2), kind="blocks")
        with pytest.raises(ValueError, match="edge already exists"):
            service.add_edge(conn, ("group", g1), ("group", g2), kind="blocks")

    def test_cross_workspace_group_edge_raises(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, "workspace1")
        b2 = insert_workspace(conn, "workspace2")
        g1 = insert_group(conn, b1, "g1")
        g2 = insert_group(conn, b2, "g2")
        with pytest.raises(ValueError, match="same workspace"):
            service.add_edge(conn, ("group", g1), ("group", g2), kind="blocks")


# ---- Status edges ----


class TestStatusEdges:
    def test_status_edge_stored(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        s_todo = insert_status(conn, bid, "todo")
        s_doing = insert_status(conn, bid, "doing")
        service.add_edge(
            conn, ("status", s_todo), ("status", s_doing), kind="transition"
        )
        edges = service.list_edges(conn, bid)
        assert any(
            e.from_type == "status"
            and e.from_id == s_todo
            and e.to_type == "status"
            and e.to_id == s_doing
            and e.kind == "transition"
            for e in edges
        )

    def test_status_edges_are_pure_annotation(
        self, conn: sqlite3.Connection
    ) -> None:
        """Regression guard: status edges carry no write-path semantics.
        Defining a transition graph must not constrain task status moves."""
        bid = insert_workspace(conn)
        s_todo = insert_status(conn, bid, "todo")
        s_doing = insert_status(conn, bid, "doing")
        s_done = insert_status(conn, bid, "done")
        service.add_edge(
            conn, ("status", s_todo), ("status", s_doing), kind="transition"
        )
        t = insert_task(conn, bid, "t", s_todo)
        # 'done' is not in the transition graph — must still be allowed.
        service.update_task(conn, t, {"status_id": s_done}, "test")
        assert service.get_task(conn, t).status_id == s_done

    def test_cross_workspace_status_edge_rejected(
        self, conn: sqlite3.Connection
    ) -> None:
        b1 = insert_workspace(conn, "w1")
        b2 = insert_workspace(conn, "w2")
        s1 = insert_status(conn, b1, "todo")
        s2 = insert_status(conn, b2, "doing")
        with pytest.raises(ValueError, match="same workspace"):
            service.add_edge(
                conn, ("status", s1), ("status", s2), kind="transition"
            )

    def test_archived_status_endpoint_rejected(
        self, conn: sqlite3.Connection
    ) -> None:
        bid = insert_workspace(conn)
        s1 = insert_status(conn, bid, "todo")
        s2 = insert_status(conn, bid, "doing")
        conn.execute("UPDATE statuses SET archived = 1 WHERE id = ?", (s2,))
        conn.commit()
        with pytest.raises(ValueError, match="archived"):
            service.add_edge(
                conn, ("status", s1), ("status", s2), kind="transition"
            )

    def test_status_edges_allow_cycles(self, conn: sqlite3.Connection) -> None:
        """State machines have rollback loops; status edges default to
        acyclic=0, so cycle detection must not fire."""
        bid = insert_workspace(conn)
        s_doing = insert_status(conn, bid, "doing")
        s_done = insert_status(conn, bid, "done")
        service.add_edge(
            conn, ("status", s_doing), ("status", s_done), kind="transition"
        )
        service.add_edge(
            conn, ("status", s_done), ("status", s_doing), kind="rollback"
        )


# ---- History ----


class TestHistoryService:
    def test_list(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        task = service.create_task(conn, bid, "t", cid)
        service.update_task(conn, task.id, {"title": "new"}, "tui")
        history = service.list_journal(conn, EntityType.TASK, task.id)
        assert len(history) == 1
        assert isinstance(history[0], JournalEntry)

    def test_list_missing_task_returns_empty(self, conn: sqlite3.Connection) -> None:
        assert service.list_journal(conn, EntityType.TASK, 9999) == ()


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

        with pytest.raises(ValueError, match="active edges"):
            service.move_task_to_workspace(conn, t2, b2, c2, source="test")

    def test_blocks_deps(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "blocker", cid)
        t2 = insert_task(conn, bid, "blocked", cid)
        insert_task_dependency(conn, t2, t1)

        b2 = insert_workspace(conn, "workspace2")
        c2 = insert_status(conn, b2, "backlog")

        with pytest.raises(ValueError, match="active edges"):
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

    def test_copies_dates(self, conn: sqlite3.Connection) -> None:
        b1 = insert_workspace(conn, "workspace1")
        c1 = insert_status(conn, b1, "todo")
        task = service.create_task(
            conn,
            b1,
            "dated",
            c1,
            due_date=1700000000,
            start_date=1699000000,
            finish_date=1701000000,
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
        assert preview.edge_endpoints == ()
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
        assert preview.edge_endpoints == (("task", t1),)
        assert "active edges" in preview.blocking_reason

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
    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int]:
        """Returns (workspace_id, status_id)."""
        bid = insert_workspace(conn, "workspace1")
        cid = insert_status(conn, bid, "todo")
        return bid, cid

    def test_create_group(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        grp = service.create_group(conn, bid, "Frontend")
        assert isinstance(grp, Group)
        assert grp.title == "Frontend"
        assert grp.workspace_id == bid

    def test_create_with_parent(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        parent = service.create_group(conn, bid, "parent")
        child = service.create_group(conn, bid, "child", parent_id=parent.id)
        assert child.parent_id == parent.id

    def test_create_with_cross_workspace_parent_raises(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        bid2 = insert_workspace(conn, "ws2")
        parent = service.create_group(conn, bid, "parent")
        with pytest.raises(ValueError):
            service.create_group(conn, bid2, "child", parent_id=parent.id)

    def test_create_with_missing_parent_raises(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        with pytest.raises(LookupError, match="parent"):
            service.create_group(conn, bid, "child", parent_id=9999)

    def test_get_group(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        grp = service.create_group(conn, bid, "g")
        assert service.get_group(conn, grp.id) == grp

    def test_get_group_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_group(conn, 9999)

    def test_get_group_by_title(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        grp = service.create_group(conn, bid, "Backend")
        assert service.get_group_by_title(conn, bid, None, "Backend") == grp

    def test_get_group_by_title_missing_raises(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        with pytest.raises(LookupError):
            service.get_group_by_title(conn, bid, None, "nope")

    def test_resolve_group_unique_across_workspace(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        grp = service.create_group(conn, bid, "Frontend")
        resolved = service.resolve_group_by_title(conn, bid, "Frontend")
        assert resolved == grp

    def test_resolve_group_case_insensitive(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        grp = service.create_group(conn, bid, "Frontend")
        resolved = service.resolve_group_by_title(conn, bid, "frontend")
        assert resolved == grp

    def test_resolve_group_missing_raises(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        with pytest.raises(LookupError, match="not found"):
            service.resolve_group_by_title(conn, bid, "nope")

    def test_resolve_group_ambiguous_raises(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        p1 = service.create_group(conn, bid, "p1")
        p2 = service.create_group(conn, bid, "p2")
        service.create_group(conn, bid, "shared", parent_id=p1.id)
        service.create_group(conn, bid, "shared", parent_id=p2.id)
        with pytest.raises(LookupError, match="ambiguous"):
            service.resolve_group_by_title(conn, bid, "shared")

    def test_resolve_group_ambiguity_resolved_by_parent(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        p1 = service.create_group(conn, bid, "p1")
        p2 = service.create_group(conn, bid, "p2")
        service.create_group(conn, bid, "shared", parent_id=p1.id)
        g2 = service.create_group(conn, bid, "shared", parent_id=p2.id)
        resolved = service.resolve_group_by_title(conn, bid, "shared", parent_id=p2.id, parent_known=True)
        assert resolved == g2

    def test_resolve_group_by_path(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        p1 = service.create_group(conn, bid, "parent-1")
        p2 = service.create_group(conn, bid, "parent-2")
        g1 = service.create_group(conn, bid, "shared", parent_id=p1.id)
        g2 = service.create_group(conn, bid, "shared", parent_id=p2.id)
        assert service.resolve_group(conn, bid, "parent-1/shared") == g1
        assert service.resolve_group(conn, bid, "parent-2/shared") == g2

    def test_resolve_group_no_parent_unambiguous(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        grp = service.create_group(conn, bid, "only")
        assert service.resolve_group(conn, bid, "only") == grp

    def test_resolve_group_unknown_path_raises(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        service.create_group(conn, bid, "g")
        with pytest.raises(LookupError, match="not found"):
            service.resolve_group(conn, bid, "no-such-parent/g")

    def test_get_ancestry_single(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        grp = service.create_group(conn, bid, "root")
        ancestry = service.get_group_ancestry(conn, grp.id)
        assert len(ancestry) == 1
        assert ancestry[0].id == grp.id

    def test_get_ancestry_nested(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        root = service.create_group(conn, bid, "root")
        mid = service.create_group(conn, bid, "mid", parent_id=root.id)
        leaf = service.create_group(conn, bid, "leaf", parent_id=mid.id)
        ancestry = service.get_group_ancestry(conn, leaf.id)
        assert [g.id for g in ancestry] == [root.id, mid.id, leaf.id]

    def test_get_ancestry_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_group_ancestry(conn, 9999)

    def test_list_groups(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        service.create_group(conn, bid, "g1")
        service.create_group(conn, bid, "g2")
        refs = service.list_groups(conn, bid)
        assert len(refs) == 2
        assert all(isinstance(r, GroupRef) for r in refs)

    def test_update_group(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        grp = service.create_group(conn, bid, "old")
        updated = service.update_group(conn, grp.id, {"title": "new"})
        assert updated.title == "new"

    def test_reparent_cycle_detection(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        g1 = service.create_group(conn, bid, "g1")
        g2 = service.create_group(conn, bid, "g2", parent_id=g1.id)
        g3 = service.create_group(conn, bid, "g3", parent_id=g2.id)
        with pytest.raises(ValueError, match="cycle"):
            service.update_group(conn, g1.id, {"parent_id": g3.id})

    def test_reparent_to_self_raises(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        g = service.create_group(conn, bid, "g")
        with pytest.raises(ValueError, match="cycle"):
            service.update_group(conn, g.id, {"parent_id": g.id})

    def test_cascade_archive_archives_tasks(self, conn: sqlite3.Connection) -> None:
        bid, cid = self._setup(conn)
        grp = service.create_group(conn, bid, "g")
        tid = insert_task(conn, bid, "t", cid)
        service.assign_task_to_group(conn, tid, grp.id, source="test")
        service.cascade_archive_group(conn, grp.id, source="test")
        assert service.get_task(conn, tid).archived is True

    def test_cascade_archive_archives_descendants(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        parent = service.create_group(conn, bid, "parent")
        mid = service.create_group(conn, bid, "mid", parent_id=parent.id)
        child = service.create_group(conn, bid, "child", parent_id=mid.id)
        service.cascade_archive_group(conn, parent.id, source="test")
        assert service.get_group(conn, parent.id).archived is True
        assert service.get_group(conn, mid.id).archived is True
        assert service.get_group(conn, child.id).archived is True

    def test_cascade_archive_group_is_archived(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        grp = service.create_group(conn, bid, "g")
        service.cascade_archive_group(conn, grp.id, source="test")
        assert service.get_group(conn, grp.id).archived is True

    def test_get_group_detail(self, conn: sqlite3.Connection) -> None:
        bid, cid = self._setup(conn)
        parent = service.create_group(conn, bid, "parent")
        child = service.create_group(conn, bid, "child", parent_id=parent.id)
        tid = insert_task(conn, bid, "t", cid)
        service.assign_task_to_group(conn, tid, parent.id, source="test")
        detail = service.get_group_detail(conn, parent.id)
        assert isinstance(detail, GroupDetail)
        assert len(detail.tasks) == 1
        assert detail.tasks[0].id == tid
        assert len(detail.children) == 1
        assert detail.children[0].id == child.id
        assert detail.parent is None

    def test_get_group_detail_with_parent(self, conn: sqlite3.Connection) -> None:
        bid, _ = self._setup(conn)
        parent = service.create_group(conn, bid, "parent")
        child = service.create_group(conn, bid, "child", parent_id=parent.id)
        detail = service.get_group_detail(conn, child.id)
        assert detail.parent is not None
        assert detail.parent.id == parent.id

    def test_cascade_archive_group_integrity_error_becomes_value_error(
        self, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from stx import repository as repo_mod

        bid, _ = self._setup(conn)
        grp = service.create_group(conn, bid, "g")

        def raise_integrity(*args, **kwargs):
            raise sqlite3.IntegrityError(
                "UNIQUE constraint failed: groups.workspace_id, groups.title"
            )

        monkeypatch.setattr(repo_mod, "update_group", raise_integrity)
        with pytest.raises(ValueError):
            service.cascade_archive_group(conn, grp.id, source="test")


class TestTaskGroupAssignment:
    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int]:
        bid = insert_workspace(conn, "workspace1")
        cid = insert_status(conn, bid, "todo")
        return bid, cid

    def test_assign_task(self, conn: sqlite3.Connection) -> None:
        bid, cid = self._setup(conn)
        grp = service.create_group(conn, bid, "g")
        tid = insert_task(conn, bid, "t", cid)
        service.assign_task_to_group(conn, tid, grp.id, source="test")
        assert service.get_task(conn, tid).group_id == grp.id

    def test_assign_cross_workspace_raises(self, conn: sqlite3.Connection) -> None:
        bid, cid = self._setup(conn)
        bid2 = insert_workspace(conn, "workspace2")
        grp = service.create_group(conn, bid2, "g")
        tid = insert_task(conn, bid, "t", cid)
        with pytest.raises(ValueError, match="workspace"):
            service.assign_task_to_group(conn, tid, grp.id, source="test")

    def test_unassign_task(self, conn: sqlite3.Connection) -> None:
        bid, cid = self._setup(conn)
        grp = service.create_group(conn, bid, "g")
        tid = insert_task(conn, bid, "t", cid)
        service.assign_task_to_group(conn, tid, grp.id, source="test")
        service.unassign_task_from_group(conn, tid, source="test")
        assert service.get_task(conn, tid).group_id is None


class TestUpdateTaskGroupId:
    """update_task now accepts group_id directly; these tests cover the invariant."""

    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int]:
        bid = insert_workspace(conn, "workspace1")
        cid = insert_status(conn, bid, "todo")
        return bid, cid

    def test_update_task_sets_group_id(self, conn: sqlite3.Connection) -> None:
        bid, cid = self._setup(conn)
        grp = service.create_group(conn, bid, "g")
        tid = insert_task(conn, bid, "t", cid)
        service.update_task(conn, tid, {"group_id": grp.id}, source="test")
        assert service.get_task(conn, tid).group_id == grp.id

    def test_update_task_clears_group_id(self, conn: sqlite3.Connection) -> None:
        bid, cid = self._setup(conn)
        grp = service.create_group(conn, bid, "g")
        tid = insert_task(conn, bid, "t", cid)
        service.update_task(conn, tid, {"group_id": grp.id}, source="test")
        service.update_task(conn, tid, {"group_id": None}, source="test")
        assert service.get_task(conn, tid).group_id is None

    def test_update_task_group_archived_raises(self, conn: sqlite3.Connection) -> None:
        bid, cid = self._setup(conn)
        grp = service.create_group(conn, bid, "g")
        service.cascade_archive_group(conn, grp.id, source="test")
        tid = insert_task(conn, bid, "t", cid)
        with pytest.raises(ValueError, match="archived"):
            service.update_task(conn, tid, {"group_id": grp.id}, source="test")

    def test_update_task_group_on_wrong_workspace_raises(self, conn: sqlite3.Connection) -> None:
        bid1, cid1 = self._setup(conn)
        bid2 = insert_workspace(conn, "workspace2")
        cid2 = insert_status(conn, bid2, "todo")
        grp_other = service.create_group(conn, bid2, "g_other")
        tid = insert_task(conn, bid1, "t", cid1)
        with pytest.raises(ValueError, match="workspace"):
            service.update_task(conn, tid, {"group_id": grp_other.id}, source="test")


class TestTaskGroupHistory:
    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int]:
        bid = insert_workspace(conn, "workspace1")
        cid = insert_status(conn, bid, "todo")
        return bid, cid

    def test_assign_records_history(self, conn: sqlite3.Connection) -> None:
        bid, cid = self._setup(conn)
        grp = service.create_group(conn, bid, "g")
        tid = insert_task(conn, bid, "t", cid)
        service.assign_task_to_group(conn, tid, grp.id, source="test")
        history = service.list_journal(conn, EntityType.TASK, tid)
        group_entries = [h for h in history if h.field == "group_id"]
        assert len(group_entries) == 1
        assert group_entries[0].old_value is None
        assert group_entries[0].new_value == str(grp.id)
        assert group_entries[0].source == "test"

    def test_source_forwarded_to_history(self, conn: sqlite3.Connection) -> None:
        bid, cid = self._setup(conn)
        grp = service.create_group(conn, bid, "g")
        tid = insert_task(conn, bid, "t", cid)
        service.assign_task_to_group(conn, tid, grp.id, source="cli")
        history = service.list_journal(conn, EntityType.TASK, tid)
        entry = next(h for h in history if h.field == "group_id")
        assert entry.source == "cli"
        service.unassign_task_from_group(conn, tid, source="tui")
        history2 = service.list_journal(conn, EntityType.TASK, tid)
        unassign = next(h for h in history2 if h.field == "group_id" and h.new_value is None)
        assert unassign.source == "tui"

    def test_reassign_records_old_and_new(self, conn: sqlite3.Connection) -> None:
        bid, cid = self._setup(conn)
        g1 = service.create_group(conn, bid, "g1")
        g2 = service.create_group(conn, bid, "g2")
        tid = insert_task(conn, bid, "t", cid)
        service.assign_task_to_group(conn, tid, g1.id, source="test")
        service.assign_task_to_group(conn, tid, g2.id, source="test")
        history = service.list_journal(conn, EntityType.TASK, tid)
        group_entries = [h for h in history if h.field == "group_id"]
        assert len(group_entries) == 2
        # newest first (ORDER BY changed_at DESC)
        assert group_entries[0].old_value == str(g1.id)
        assert group_entries[0].new_value == str(g2.id)

    def test_unassign_records_history(self, conn: sqlite3.Connection) -> None:
        bid, cid = self._setup(conn)
        grp = service.create_group(conn, bid, "g")
        tid = insert_task(conn, bid, "t", cid)
        service.assign_task_to_group(conn, tid, grp.id, source="test")
        service.unassign_task_from_group(conn, tid, source="test")
        history = service.list_journal(conn, EntityType.TASK, tid)
        group_entries = [h for h in history if h.field == "group_id"]
        assert len(group_entries) == 2
        # newest first
        unassign = group_entries[0]
        assert unassign.old_value == str(grp.id)
        assert unassign.new_value is None
        assert unassign.source == "test"

    def test_unassign_no_op_no_history(self, conn: sqlite3.Connection) -> None:
        bid, cid = self._setup(conn)
        tid = insert_task(conn, bid, "t", cid)
        service.unassign_task_from_group(conn, tid, source="test")
        history = service.list_journal(conn, EntityType.TASK, tid)
        assert not [h for h in history if h.field == "group_id"]

    def test_assign_same_group_no_history(self, conn: sqlite3.Connection) -> None:
        bid, cid = self._setup(conn)
        grp = service.create_group(conn, bid, "g")
        tid = insert_task(conn, bid, "t", cid)
        service.assign_task_to_group(conn, tid, grp.id, source="test")
        service.assign_task_to_group(conn, tid, grp.id, source="test")
        history = service.list_journal(conn, EntityType.TASK, tid)
        group_entries = [h for h in history if h.field == "group_id"]
        # The second call is a no-op (group_id already matches); _record_changes skips it.
        assert len(group_entries) == 1


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

    def test_include_archived_shows_archived_statuses(self, conn: sqlite3.Connection) -> None:
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
        assert ctx.groups == ()

    def test_includes_groups(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        grp = service.create_group(conn, bid, "sprint-1")
        ctx = service.get_workspace_context(conn, bid)
        assert len(ctx.groups) == 1
        assert ctx.groups[0].id == grp.id
        assert ctx.groups[0].title == "sprint-1"

    def test_groups_from_workspace(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        service.create_group(conn, bid, "g1")
        service.create_group(conn, bid, "g2")
        ctx = service.get_workspace_context(conn, bid)
        assert len(ctx.groups) == 2
        titles = {g.title for g in ctx.groups}
        assert titles == {"g1", "g2"}

    def test_archived_excluded(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        service.create_group(conn, bid, "grp")
        # archive via raw SQL
        conn.execute("UPDATE groups SET archived=1 WHERE workspace_id=?", (bid,))
        conn.commit()
        ctx = service.get_workspace_context(conn, bid)
        assert ctx.groups == ()

    def test_missing_workspace_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.get_workspace_context(conn, 9999)


# ---- Update preview helpers ----


class TestPreviewHelpers:
    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int, int]:
        """Returns (workspace_id, status_id_todo, status_id_done)."""
        bid = insert_workspace(conn)
        cid_todo = insert_status(conn, bid, "todo")
        cid_done = insert_status(conn, bid, "done")
        return bid, cid_todo, cid_done

    # ---- preview_update_task ----

    def test_task_before_reflects_current_values(self, conn: sqlite3.Connection) -> None:
        bid, cid, _ = self._setup(conn)
        task = service.create_task(conn, bid, "orig", cid, priority=2)
        preview = service.preview_update_task(
            conn,
            task.id,
            {"title": "renamed", "priority": 4},
        )
        assert preview.before["title"] == "orig"
        assert preview.before["priority"] == 2
        assert preview.after["title"] == "renamed"
        assert preview.after["priority"] == 4

    def test_task_omits_unchanged_fields(self, conn: sqlite3.Connection) -> None:
        bid, cid, _ = self._setup(conn)
        task = service.create_task(conn, bid, "orig", cid, priority=2)
        preview = service.preview_update_task(
            conn,
            task.id,
            {"title": "orig", "priority": 4},
        )
        assert "title" not in preview.before
        assert "title" not in preview.after
        assert preview.after["priority"] == 4

    # ---- preview_move_task ----

    def test_move_happy_path(self, conn: sqlite3.Connection) -> None:
        bid, cid_todo, cid_done = self._setup(conn)
        task = service.create_task(conn, bid, "t", cid_todo)
        preview = service.preview_move_task(conn, task.id, cid_done)
        assert preview.from_status == "todo"
        assert preview.to_status == "done"

    # ---- preview_update_group ----

    def test_group_rename_diff(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        grp = service.create_group(conn, bid, "old-title")
        preview = service.preview_update_group(conn, grp.id, {"title": "new-title"})
        assert preview.before["title"] == "old-title"
        assert preview.after["title"] == "new-title"

    def test_group_reparent_diff_resolves_titles(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        p1 = service.create_group(conn, bid, "parent-1")
        p2 = service.create_group(conn, bid, "parent-2")
        child = service.create_group(conn, bid, "child", parent_id=p1.id)
        preview = service.preview_update_group(conn, child.id, {"parent_id": p2.id})
        # Resolver maps raw parent_id ints to title strings
        assert preview.before["parent_id"] == "parent-1"
        assert preview.after["parent_id"] == "parent-2"

    def test_group_promote_to_top_diff(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        parent = service.create_group(conn, bid, "parent")
        child = service.create_group(conn, bid, "child", parent_id=parent.id)
        preview = service.preview_update_group(conn, child.id, {"parent_id": None})
        assert preview.before["parent_id"] == "parent"
        assert preview.after["parent_id"] is None

    def test_group_cycle_detection(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        g1 = service.create_group(conn, bid, "g1")
        g2 = service.create_group(conn, bid, "g2", parent_id=g1.id)
        with pytest.raises(ValueError, match="cycle"):
            service.preview_update_group(conn, g1.id, {"parent_id": g2.id})


# ---- Archive preview + cascade ----


class TestArchivePreviewAndCascade:
    def _setup_full(self, conn: sqlite3.Connection) -> tuple[int, int, int, int, int]:
        """Create workspace with 2 statuses, 2 groups (parent+child), 2 tasks."""
        bid = insert_workspace(conn)
        cid1 = insert_status(conn, bid, "todo")
        cid2 = insert_status(conn, bid, "done")
        g1 = insert_group(conn, bid, "parent")
        g2 = insert_group(conn, bid, "child", parent_id=g1)
        t1 = insert_task(conn, bid, "t1", cid1)
        t2 = insert_task(conn, bid, "t2", cid2)
        service.assign_task_to_group(conn, t1, g1, source="test")
        service.assign_task_to_group(conn, t2, g2, source="test")
        return bid, g1, g2, t1, t2

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
        bid, g1, g2, t1, t2 = self._setup_full(conn)
        preview = service.preview_archive_group(conn, g1)
        assert preview.entity_type == "group"
        assert preview.group_count == 1  # child group
        assert preview.task_count == 2  # both tasks

    def test_preview_archive_workspace(self, conn: sqlite3.Connection) -> None:
        bid, g1, g2, t1, t2 = self._setup_full(conn)
        preview = service.preview_archive_workspace(conn, bid)
        assert preview.entity_type == "workspace"
        assert preview.group_count == 2
        assert preview.status_count == 2
        assert preview.task_count == 2

    # ---- Cascade correctness ----

    def test_cascade_archive_group_archives_all(self, conn: sqlite3.Connection) -> None:
        bid, g1, g2, t1, t2 = self._setup_full(conn)
        service.cascade_archive_group(conn, g1, source="test")
        assert service.get_group(conn, g1).archived is True
        assert service.get_group(conn, g2).archived is True
        assert service.get_task(conn, t1).archived is True
        assert service.get_task(conn, t2).archived is True

    def test_cascade_archive_workspace_archives_all(self, conn: sqlite3.Connection) -> None:
        bid, g1, g2, t1, t2 = self._setup_full(conn)
        service.cascade_archive_workspace(conn, bid, source="test")
        assert service.get_workspace(conn, bid).archived is True
        assert service.get_group(conn, g1).archived is True
        assert service.get_task(conn, t1).archived is True
        # All statuses archived
        from stx import repository as repo

        statuses = repo.list_statuses(conn, bid, include_archived=True)
        assert all(s.archived for s in statuses)

    # ---- Cascade history recording ----

    def test_cascade_archive_group_records_history(self, conn: sqlite3.Connection) -> None:
        bid, g1, g2, t1, t2 = self._setup_full(conn)
        service.cascade_archive_group(conn, g1, source="test")
        for tid in (t1, t2):
            history = service.list_journal(conn, EntityType.TASK, tid)
            archived_entries = [h for h in history if h.field == "archived"]
            assert len(archived_entries) == 1
            assert archived_entries[0].old_value == "False"
            assert archived_entries[0].new_value == "True"
            assert archived_entries[0].source == "test"

    def test_cascade_archive_workspace_records_history(self, conn: sqlite3.Connection) -> None:
        bid, g1, g2, t1, t2 = self._setup_full(conn)
        service.cascade_archive_workspace(conn, bid, source="test")
        for tid in (t1, t2):
            history = service.list_journal(conn, EntityType.TASK, tid)
            archived_entries = [h for h in history if h.field == "archived"]
            assert len(archived_entries) == 1

    def test_cascade_archive_group_journals_descendant_groups(
        self, conn: sqlite3.Connection
    ) -> None:
        bid, g1, g2, t1, t2 = self._setup_full(conn)
        # g1 is the parent (journaled via update_group); g2 is the descendant.
        service.cascade_archive_group(conn, g1, source="test")
        descendant_history = service.list_journal(conn, EntityType.GROUP, g2)
        archived = [h for h in descendant_history if h.field == "archived"]
        assert len(archived) == 1
        assert archived[0].old_value == "False"
        assert archived[0].new_value == "True"
        assert archived[0].source == "test"

    def test_cascade_archive_workspace_journals_groups_and_statuses(
        self, conn: sqlite3.Connection
    ) -> None:
        bid, g1, g2, t1, t2 = self._setup_full(conn)
        from stx import repository as repo

        status_ids = tuple(s.id for s in repo.list_statuses(conn, bid))
        service.cascade_archive_workspace(conn, bid, source="test")
        for gid in (g1, g2):
            history = service.list_journal(conn, EntityType.GROUP, gid)
            archived = [h for h in history if h.field == "archived"]
            assert len(archived) == 1
            assert archived[0].source == "test"
        for sid in status_ids:
            history = service.list_journal(conn, EntityType.STATUS, sid)
            archived = [h for h in history if h.field == "archived"]
            assert len(archived) == 1
            assert archived[0].source == "test"

    # ---- Dep re-creation after archive ----

    def test_readd_dependency_after_archive(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_edge(conn, ("task", t2), ("task", t1), kind="blocks")
        service.archive_edge(conn, ("task", t2), ("task", t1), kind="blocks")
        service.add_edge(conn, ("task", t2), ("task", t1), kind="blocks")  # should not crash
        detail = service.get_task_detail(conn, t2)
        # t2 is the source → outgoing = edge_targets
        assert len(detail.edge_targets) == 1

    def test_readd_edge_journals_archived_flip(self, conn: sqlite3.Connection) -> None:
        """Reviving an archived edge (same kind) emits archived 1→0 entry."""
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_edge(conn, ("task", t2), ("task", t1), kind="blocks")
        service.archive_edge(conn, ("task", t2), ("task", t1), kind="blocks")
        service.add_edge(conn, ("task", t2), ("task", t1), kind="blocks")  # revive same edge
        entries = service.list_journal(conn, EntityType.EDGE, t2)
        archived_flips = [e for e in entries if e.field == "archived" and e.new_value == "0"]
        assert len(archived_flips) == 1

    def test_archive_already_archived_edge_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_edge(conn, ("task", t1), ("task", t2), kind="blocks")
        service.archive_edge(conn, ("task", t1), ("task", t2), kind="blocks")
        with pytest.raises(LookupError, match="already archived"):
            service.archive_edge(conn, ("task", t1), ("task", t2), kind="blocks")

    def test_archive_nonexistent_edge_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        with pytest.raises(LookupError, match="no edge found"):
            service.archive_edge(conn, ("task", t1), ("task", t2), kind="blocks")

    def test_readd_group_edge_after_archive(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        g1 = insert_group(conn, bid, "g1")
        g2 = insert_group(conn, bid, "g2")
        service.add_edge(conn, ("group", g1), ("group", g2), kind="blocks")
        service.archive_edge(conn, ("group", g1), ("group", g2), kind="blocks")
        service.add_edge(conn, ("group", g1), ("group", g2), kind="blocks")  # should not crash
        edges = service.list_edges(conn, bid)
        assert any(e.from_id == g1 and e.to_id == g2 and e.kind == "blocks" for e in edges)

    def test_archive_already_archived_group_edge_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        g1 = insert_group(conn, bid, "g1")
        g2 = insert_group(conn, bid, "g2")
        service.add_edge(conn, ("group", g1), ("group", g2), kind="blocks")
        service.archive_edge(conn, ("group", g1), ("group", g2), kind="blocks")
        with pytest.raises(LookupError, match="already archived"):
            service.archive_edge(conn, ("group", g1), ("group", g2), kind="blocks")

    def test_archive_nonexistent_group_edge_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        g1 = insert_group(conn, bid, "g1")
        g2 = insert_group(conn, bid, "g2")
        with pytest.raises(LookupError, match="no edge found"):
            service.archive_edge(conn, ("group", g1), ("group", g2), kind="blocks")

    def test_source_archived_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.update_task(conn, t1, {"archived": True}, "cli")
        with pytest.raises(ValueError, match=f"task {t1} is archived"):
            service.add_edge(conn, ("task", t1), ("task", t2), kind="blocks")

    def test_target_archived_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.update_task(conn, t2, {"archived": True}, "cli")
        with pytest.raises(ValueError, match=f"task {t2} is archived"):
            service.add_edge(conn, ("task", t1), ("task", t2), kind="blocks")

    def test_group_source_archived_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        g1 = insert_group(conn, bid, "g1")
        g2 = insert_group(conn, bid, "g2")
        service.update_group(conn, g1, {"archived": True}, "cli")
        with pytest.raises(ValueError, match=f"group {g1} is archived"):
            service.add_edge(conn, ("group", g1), ("group", g2), kind="blocks")

    def test_group_target_archived_raises(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        g1 = insert_group(conn, bid, "g1")
        g2 = insert_group(conn, bid, "g2")
        service.update_group(conn, g2, {"archived": True}, "cli")
        with pytest.raises(ValueError, match=f"group {g2} is archived"):
            service.add_edge(conn, ("group", g1), ("group", g2), kind="blocks")

    def test_db_check_rejects_bad_kind(self, conn: sqlite3.Connection) -> None:
        """Raw DB insert with a bad kind must be rejected by the CHECK constraint."""
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO edges (from_type, from_id, to_type, to_id, workspace_id, kind) "
                "VALUES ('task', ?, 'task', ?, ?, ?)",
                (t1, t2, bid, "BAD KIND!"),
            )

    def test_list_edges_filters_archived_endpoints(self, conn: sqlite3.Connection) -> None:
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_edge(conn, ("task", t1), ("task", t2), kind="blocks")
        service.update_task(conn, t2, {"archived": True}, "cli")
        edges = service.list_edges(conn, bid)
        assert edges == ()

    def test_task_detail_hides_edges_to_archived_endpoint(
        self, conn: sqlite3.Connection
    ) -> None:
        """get_task_detail should omit edges whose other endpoint has been archived."""
        bid = insert_workspace(conn)
        cid = insert_status(conn, bid)
        t1 = insert_task(conn, bid, "a", cid)
        t2 = insert_task(conn, bid, "b", cid)
        service.add_edge(conn, ("task", t1), ("task", t2), kind="blocks")
        service.update_task(conn, t2, {"archived": True}, "cli")
        detail = service.get_task_detail(conn, t1)
        assert detail.edge_sources == ()
        assert detail.edge_targets == ()

    def test_transfer_not_blocked_by_edge_to_archived_task(
        self, conn: sqlite3.Connection
    ) -> None:
        """Moving task-A to another workspace should not be blocked by edge A→B if B is archived."""
        b1 = insert_workspace(conn, "src")
        c1 = insert_status(conn, b1, "todo")
        t1 = insert_task(conn, b1, "active", c1)
        t2 = insert_task(conn, b1, "to-be-archived", c1)
        service.add_edge(conn, ("task", t1), ("task", t2), kind="blocks")
        service.update_task(conn, t2, {"archived": True}, "cli")
        b2 = insert_workspace(conn, "dst")
        c2 = insert_status(conn, b2, "backlog")
        preview = service.preview_move_to_workspace(conn, t1, b2, c2)
        assert preview.can_move is True
        assert preview.edge_endpoints == ()


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
        old = service.remove_task_meta(conn, tid, "branch")
        assert old == "feat/kv"
        assert service.get_task(conn, tid).metadata == {}

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

    def test_get_meta(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        service.set_task_meta(conn, tid, "branch", "feat/kv")
        assert service.get_task_meta(conn, tid, "branch") == "feat/kv"

    def test_get_meta_missing_key_raises(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        with pytest.raises(LookupError, match="not found"):
            service.get_task_meta(conn, tid, "nope")

    def test_get_meta_invalid_key_raises(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        with pytest.raises(ValueError, match="must match"):
            service.get_task_meta(conn, tid, "BAD KEY")

    def test_move_task_to_workspace_copies_metadata(self, conn: sqlite3.Connection) -> None:
        bid1, tid = self._setup(conn)
        service.set_task_meta(conn, tid, "branch", "feat/kv")
        service.set_task_meta(conn, tid, "jira", "PROJ-1")
        bid2 = insert_workspace(conn, "w2")
        sid2 = insert_status(conn, bid2, "todo")
        new_task = service.move_task_to_workspace(conn, tid, bid2, sid2, source="test")
        assert new_task.metadata == {"branch": "feat/kv", "jira": "PROJ-1"}

    def test_set_meta_normalizes_case(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        service.set_task_meta(conn, tid, "BRANCH", "feat/kv")
        task = service.get_task(conn, tid)
        assert task.metadata == {"branch": "feat/kv"}

    def test_get_meta_case_insensitive(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        service.set_task_meta(conn, tid, "branch", "feat/kv")
        assert service.get_task_meta(conn, tid, "Branch") == "feat/kv"
        assert service.get_task_meta(conn, tid, "BRANCH") == "feat/kv"

    def test_remove_meta_case_insensitive(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        service.set_task_meta(conn, tid, "branch", "feat/kv")
        service.remove_task_meta(conn, tid, "BRANCH")
        assert service.get_task(conn, tid).metadata == {}

    def test_set_meta_overwrites_regardless_of_case(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        service.set_task_meta(conn, tid, "Branch", "old")
        service.set_task_meta(conn, tid, "BRANCH", "new")
        assert service.get_task(conn, tid).metadata == {"branch": "new"}


class TestReplaceTaskMetadata:
    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int]:
        bid = insert_workspace(conn, "w")
        sid = insert_status(conn, bid, "todo")
        tid = insert_task(conn, bid, "task1", sid)
        return bid, tid

    def test_replace_sets_multiple_keys(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        task = service.replace_task_metadata(
            conn,
            tid,
            {"a": "1", "b": "2"},
            source="test",
        )
        assert task.metadata == {"a": "1", "b": "2"}

    def test_replace_clears_all_with_empty_dict(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        service.set_task_meta(conn, tid, "a", "1")
        service.set_task_meta(conn, tid, "b", "2")
        task = service.replace_task_metadata(conn, tid, {}, source="test")
        assert task.metadata == {}

    def test_replace_overwrites_existing(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        service.set_task_meta(conn, tid, "a", "1")
        task = service.replace_task_metadata(
            conn,
            tid,
            {"a": "2", "b": "3"},
            source="test",
        )
        assert task.metadata == {"a": "2", "b": "3"}

    def test_replace_normalizes_keys(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        task = service.replace_task_metadata(
            conn,
            tid,
            {"Foo": "bar"},
            source="test",
        )
        assert task.metadata == {"foo": "bar"}

    def test_replace_rejects_bad_key_shape(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        with pytest.raises(ValueError, match="must match"):
            service.replace_task_metadata(
                conn,
                tid,
                {"has space": "v"},
                source="test",
            )

    def test_replace_rejects_empty_key(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        with pytest.raises(ValueError, match="1-64 characters"):
            service.replace_task_metadata(
                conn,
                tid,
                {"": "v"},
                source="test",
            )

    def test_replace_rejects_long_value(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        with pytest.raises(ValueError, match="500"):
            service.replace_task_metadata(
                conn,
                tid,
                {"k": "x" * 501},
                source="test",
            )

    def test_replace_rejects_duplicate_normalized_keys(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        with pytest.raises(ValueError, match="duplicate metadata key"):
            service.replace_task_metadata(
                conn,
                tid,
                {"foo": "1", "FOO": "2"},
                source="test",
            )

    def test_replace_missing_task_raises_lookup(self, conn: sqlite3.Connection) -> None:
        self._setup(conn)
        with pytest.raises(LookupError):
            service.replace_task_metadata(conn, 999, {"k": "v"}, source="test")

    def test_replace_records_journal_entries(self, conn: sqlite3.Connection) -> None:
        _, tid = self._setup(conn)
        service.set_task_meta(conn, tid, "a", "1")
        before = conn.execute(
            "SELECT COUNT(*) FROM journal WHERE entity_id = ?", (tid,)
        ).fetchone()[0]
        service.replace_task_metadata(
            conn,
            tid,
            {"a": "2", "b": "3"},
            source="test",
        )
        after = conn.execute("SELECT COUNT(*) FROM journal WHERE entity_id = ?", (tid,)).fetchone()[
            0
        ]
        assert after == before + 2  # 'a' changed, 'b' added


class TestReplaceWorkspaceMetadata:
    def _setup(self, conn: sqlite3.Connection) -> int:
        return insert_workspace(conn, "w")

    def test_replace_sets_multiple_keys(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        ws = service.replace_workspace_metadata(
            conn,
            wid,
            {"a": "1", "b": "2"},
            source="test",
        )
        assert ws.metadata == {"a": "1", "b": "2"}

    def test_replace_clears_all_with_empty_dict(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        service.set_workspace_meta(conn, wid, "a", "1")
        ws = service.replace_workspace_metadata(conn, wid, {}, source="test")
        assert ws.metadata == {}

    def test_replace_overwrites_existing(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        service.set_workspace_meta(conn, wid, "a", "1")
        ws = service.replace_workspace_metadata(
            conn,
            wid,
            {"a": "2", "b": "3"},
            source="test",
        )
        assert ws.metadata == {"a": "2", "b": "3"}

    def test_replace_normalizes_keys(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        ws = service.replace_workspace_metadata(
            conn,
            wid,
            {"Foo": "bar"},
            source="test",
        )
        assert ws.metadata == {"foo": "bar"}

    def test_replace_rejects_bad_key_shape(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        with pytest.raises(ValueError, match="must match"):
            service.replace_workspace_metadata(
                conn,
                wid,
                {"has space": "v"},
                source="test",
            )

    def test_replace_rejects_long_value(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        with pytest.raises(ValueError, match="500"):
            service.replace_workspace_metadata(
                conn,
                wid,
                {"k": "x" * 501},
                source="test",
            )

    def test_replace_rejects_duplicate_normalized_keys(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        with pytest.raises(ValueError, match="duplicate metadata key"):
            service.replace_workspace_metadata(
                conn,
                wid,
                {"foo": "1", "FOO": "2"},
                source="test",
            )

    def test_replace_missing_workspace_raises_lookup(self, conn: sqlite3.Connection) -> None:
        self._setup(conn)
        with pytest.raises(LookupError):
            service.replace_workspace_metadata(
                conn,
                999,
                {"k": "v"},
                source="test",
            )




class TestReplaceGroupMetadata:
    def _setup(self, conn: sqlite3.Connection) -> int:
        wid = insert_workspace(conn, "w")
        return insert_group(conn, wid, "g")

    def test_replace_sets_multiple_keys(self, conn: sqlite3.Connection) -> None:
        gid = self._setup(conn)
        g = service.replace_group_metadata(
            conn,
            gid,
            {"a": "1", "b": "2"},
            source="test",
        )
        assert g.metadata == {"a": "1", "b": "2"}

    def test_replace_clears_all_with_empty_dict(self, conn: sqlite3.Connection) -> None:
        gid = self._setup(conn)
        service.set_group_meta(conn, gid, "a", "1")
        g = service.replace_group_metadata(conn, gid, {}, source="test")
        assert g.metadata == {}

    def test_replace_overwrites_existing(self, conn: sqlite3.Connection) -> None:
        gid = self._setup(conn)
        service.set_group_meta(conn, gid, "a", "1")
        g = service.replace_group_metadata(
            conn,
            gid,
            {"a": "2", "b": "3"},
            source="test",
        )
        assert g.metadata == {"a": "2", "b": "3"}

    def test_replace_normalizes_keys(self, conn: sqlite3.Connection) -> None:
        gid = self._setup(conn)
        g = service.replace_group_metadata(
            conn,
            gid,
            {"Foo": "bar"},
            source="test",
        )
        assert g.metadata == {"foo": "bar"}

    def test_replace_rejects_bad_key_shape(self, conn: sqlite3.Connection) -> None:
        gid = self._setup(conn)
        with pytest.raises(ValueError, match="must match"):
            service.replace_group_metadata(
                conn,
                gid,
                {"has space": "v"},
                source="test",
            )

    def test_replace_rejects_long_value(self, conn: sqlite3.Connection) -> None:
        gid = self._setup(conn)
        with pytest.raises(ValueError, match="500"):
            service.replace_group_metadata(
                conn,
                gid,
                {"k": "x" * 501},
                source="test",
            )

    def test_replace_rejects_duplicate_normalized_keys(self, conn: sqlite3.Connection) -> None:
        gid = self._setup(conn)
        with pytest.raises(ValueError, match="duplicate metadata key"):
            service.replace_group_metadata(
                conn,
                gid,
                {"foo": "1", "FOO": "2"},
                source="test",
            )

    def test_replace_missing_group_raises_lookup(self, conn: sqlite3.Connection) -> None:
        self._setup(conn)
        with pytest.raises(LookupError):
            service.replace_group_metadata(
                conn,
                999,
                {"k": "v"},
                source="test",
            )


# ---- Workspace / Project / Group metadata ----


class TestWorkspaceMeta:
    def _setup(self, conn: sqlite3.Connection) -> int:
        return insert_workspace(conn, "w")

    def test_set_get(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        ws = service.set_workspace_meta(conn, wid, "env", "prod")
        assert ws.metadata == {"env": "prod"}
        assert service.get_workspace_meta(conn, wid, "env") == "prod"

    def test_set_normalizes_case(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        service.set_workspace_meta(conn, wid, "ENV", "prod")
        assert service.get_workspace(conn, wid).metadata == {"env": "prod"}

    def test_get_case_insensitive(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        service.set_workspace_meta(conn, wid, "env", "prod")
        assert service.get_workspace_meta(conn, wid, "ENV") == "prod"

    def test_remove(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        service.set_workspace_meta(conn, wid, "env", "prod")
        service.remove_workspace_meta(conn, wid, "env")
        assert service.get_workspace(conn, wid).metadata == {}

    def test_remove_missing_key_raises(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        with pytest.raises(LookupError, match="not found"):
            service.remove_workspace_meta(conn, wid, "nope")

    def test_get_missing_key_raises(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        with pytest.raises(LookupError, match="not found"):
            service.get_workspace_meta(conn, wid, "nope")

    def test_value_too_long_raises(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        with pytest.raises(ValueError, match="500"):
            service.set_workspace_meta(conn, wid, "k", "v" * 501)

    def test_key_invalid_raises(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        with pytest.raises(ValueError, match="must match"):
            service.set_workspace_meta(conn, wid, "BAD KEY", "v")


class TestGroupMeta:
    def _setup(self, conn: sqlite3.Connection) -> int:
        bid = insert_workspace(conn, "w")
        return service.create_group(conn, bid, "g").id

    def test_set_get(self, conn: sqlite3.Connection) -> None:
        gid = self._setup(conn)
        grp = service.set_group_meta(conn, gid, "sprint", "3")
        assert grp.metadata == {"sprint": "3"}
        assert service.get_group_meta(conn, gid, "sprint") == "3"

    def test_set_normalizes_case(self, conn: sqlite3.Connection) -> None:
        gid = self._setup(conn)
        service.set_group_meta(conn, gid, "SPRINT", "3")
        assert service.get_group(conn, gid).metadata == {"sprint": "3"}

    def test_get_case_insensitive(self, conn: sqlite3.Connection) -> None:
        gid = self._setup(conn)
        service.set_group_meta(conn, gid, "sprint", "3")
        assert service.get_group_meta(conn, gid, "SPRINT") == "3"

    def test_remove(self, conn: sqlite3.Connection) -> None:
        gid = self._setup(conn)
        service.set_group_meta(conn, gid, "sprint", "3")
        service.remove_group_meta(conn, gid, "sprint")
        assert service.get_group(conn, gid).metadata == {}

    def test_remove_missing_key_raises(self, conn: sqlite3.Connection) -> None:
        gid = self._setup(conn)
        with pytest.raises(LookupError, match="not found"):
            service.remove_group_meta(conn, gid, "nope")

    def test_nonexistent_entity_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(LookupError):
            service.set_group_meta(conn, 9999, "k", "v")


# ---- Journal recording tests ----


def _journal_entries(conn, entity_type_str, entity_id):
    return conn.execute(
        "SELECT * FROM journal WHERE entity_type = ? AND entity_id = ? ORDER BY id",
        (entity_type_str, entity_id),
    ).fetchall()


class TestJournalRecordingGroup:
    def _seed(self, conn):
        wid = insert_workspace(conn, "w")
        sid = insert_status(conn, wid, "todo")
        gid = insert_group(conn, wid, "G")
        return wid, sid, gid

    def test_update_group_title_journaled(self, conn):
        wid, sid, gid = self._seed(conn)
        service.update_group(conn, gid, {"title": "New"}, source="test")
        entries = _journal_entries(conn, "group", gid)
        assert len(entries) == 1
        assert entries[0]["field"] == "title"
        assert entries[0]["new_value"] == "New"

    def test_group_title_collision_friendly_error(self, conn):
        wid, sid, gid = self._seed(conn)
        service.create_group(conn, wid, "Other")
        with pytest.raises(ValueError, match="already exists under the same parent"):
            service.update_group(conn, gid, {"title": "Other"}, source="test")


class TestJournalRecordingWorkspace:
    def test_update_workspace_name_journaled(self, conn):
        wid = insert_workspace(conn, "Old")
        service.update_workspace(conn, wid, {"name": "New"}, source="test")
        entries = _journal_entries(conn, "workspace", wid)
        assert len(entries) == 1
        assert entries[0]["field"] == "name"
        assert entries[0]["old_value"] == "Old"
        assert entries[0]["new_value"] == "New"


class TestJournalRecordingStatus:
    def test_update_status_name_journaled(self, conn):
        wid = insert_workspace(conn, "w")
        sid = insert_status(conn, wid, "todo")
        service.update_status(conn, sid, {"name": "done"}, source="test")
        entries = _journal_entries(conn, "status", sid)
        assert len(entries) == 1
        assert entries[0]["field"] == "name"
        assert entries[0]["new_value"] == "done"


class TestJournalRecordingEdges:
    def _seed(self, conn):
        wid = insert_workspace(conn, "w")
        sid = insert_status(conn, wid, "todo")
        t1 = insert_task(conn, wid, "t1", sid)
        t2 = insert_task(conn, wid, "t2", sid)
        return wid, t1, t2

    def test_add_edge_journaled(self, conn):
        wid, t1, t2 = self._seed(conn)
        service.add_edge(conn, ("task", t1), ("task", t2), kind="blocks", source="test")
        entries = _journal_entries(conn, "edge", t1)
        # Add emits two entries: endpoint (None → value) + kind (None → "blocks").
        assert len(entries) == 2
        endpoint_entry = next(e for e in entries if e["field"] == "endpoint")
        assert endpoint_entry["old_value"] is None
        expected_endpoint = f"task:{t1}\u2192task:{t2}"
        assert endpoint_entry["new_value"] == expected_endpoint
        kind_entry = next(e for e in entries if e["field"] == "kind")
        assert kind_entry["old_value"] is None
        assert kind_entry["new_value"] == "blocks"

    def test_archive_edge_journaled(self, conn):
        wid, t1, t2 = self._seed(conn)
        service.add_edge(conn, ("task", t1), ("task", t2), kind="blocks", source="test")
        service.archive_edge(conn, ("task", t1), ("task", t2), kind="blocks", source="test")
        entries = _journal_entries(conn, "edge", t1)
        expected_endpoint = f"task:{t1}\u2192task:{t2}"
        endpoint_remove = next(
            e for e in entries if e["field"] == "endpoint" and e["new_value"] is None
        )
        assert endpoint_remove["old_value"] == expected_endpoint
        kind_remove = next(
            e for e in entries if e["field"] == "kind" and e["new_value"] is None
        )
        assert kind_remove["old_value"] == "blocks"

    def test_revive_edge_journals_only_archived_flip(self, conn):
        """Locks in the revival semantics documented on ``add_edge``:
        reviving an archived edge writes a single ``archived: 1→0`` entry
        (plus an ``acyclic`` entry if it changed) and does NOT re-emit the
        ``endpoint`` / ``kind`` rows. Archive+revive is a "fresh start" —
        callers that want metadata preserved should not archive."""
        wid, t1, t2 = self._seed(conn)
        service.add_edge(conn, ("task", t1), ("task", t2), kind="blocks", source="test")
        service.archive_edge(conn, ("task", t1), ("task", t2), kind="blocks", source="test")
        # Baseline: 4 entries so far (add emits 2, archive emits 2).
        baseline = len(_journal_entries(conn, "edge", t1))
        assert baseline == 4

        service.add_edge(conn, ("task", t1), ("task", t2), kind="blocks", source="test")
        entries = _journal_entries(conn, "edge", t1)
        new_entries = entries[baseline:]
        # Revival with unchanged acyclic → exactly one new entry: archived flip.
        assert len(new_entries) == 1
        archived_flip = new_entries[0]
        assert archived_flip["field"] == "archived"
        assert archived_flip["old_value"] == "1"
        assert archived_flip["new_value"] == "0"
        # Guard: no endpoint / kind rows re-emitted (the documented no-re-emit).
        assert not any(e["field"] == "endpoint" for e in new_entries)
        assert not any(e["field"] == "kind" for e in new_entries)

    def test_revive_edge_with_acyclic_change_journals_both(self, conn):
        """Reviving with a different ``acyclic`` value writes both the
        ``archived`` flip and an ``acyclic`` delta."""
        wid, t1, t2 = self._seed(conn)
        # Archive the original acyclic=1 (blocks default).
        service.add_edge(conn, ("task", t1), ("task", t2), kind="blocks", source="test")
        service.archive_edge(conn, ("task", t1), ("task", t2), kind="blocks", source="test")
        baseline = len(_journal_entries(conn, "edge", t1))

        # Revive with acyclic=False — the UPSERT flips acyclic 1→0.
        service.add_edge(
            conn, ("task", t1), ("task", t2),
            kind="blocks", acyclic=False, source="test",
        )
        entries = _journal_entries(conn, "edge", t1)
        new_entries = entries[baseline:]
        fields = {e["field"] for e in new_entries}
        assert "archived" in fields
        assert "acyclic" in fields
        acyclic_entry = next(e for e in new_entries if e["field"] == "acyclic")
        assert acyclic_entry["old_value"] == "1"
        assert acyclic_entry["new_value"] == "0"


class TestJournalRecordingMetadata:
    def _seed(self, conn):
        wid = insert_workspace(conn, "w")
        sid = insert_status(conn, wid, "todo")
        tid = insert_task(conn, wid, "t", sid)
        return wid, tid

    def test_set_task_meta_journaled(self, conn):
        wid, tid = self._seed(conn)
        service.set_task_meta(conn, tid, "foo", "bar")
        entries = conn.execute(
            "SELECT * FROM journal WHERE entity_type='task' AND entity_id=? AND field='meta.foo'",
            (tid,),
        ).fetchall()
        assert len(entries) == 1
        assert entries[0]["old_value"] is None
        assert entries[0]["new_value"] == "bar"

    def test_remove_task_meta_journaled(self, conn):
        wid, tid = self._seed(conn)
        service.set_task_meta(conn, tid, "foo", "bar")
        service.remove_task_meta(conn, tid, "foo")
        entries = conn.execute(
            "SELECT * FROM journal WHERE entity_type='task' AND entity_id=? AND field='meta.foo' ORDER BY id",
            (tid,),
        ).fetchall()
        assert len(entries) == 2
        assert entries[1]["old_value"] == "bar"
        assert entries[1]["new_value"] is None

    def test_replace_task_meta_journals_each_changed_key(self, conn):
        wid, tid = self._seed(conn)
        service.set_task_meta(conn, tid, "a", "1")
        before = conn.execute(
            "SELECT COUNT(*) FROM journal WHERE entity_type='task' AND entity_id=? AND field LIKE 'meta.%'",
            (tid,),
        ).fetchone()[0]
        service.replace_task_metadata(conn, tid, {"a": "2", "b": "3"}, source="test")
        after = conn.execute(
            "SELECT COUNT(*) FROM journal WHERE entity_type='task' AND entity_id=? AND field LIKE 'meta.%'",
            (tid,),
        ).fetchone()[0]
        assert after == before + 2  # 'a' changed, 'b' added


# ---- Done flag, terminal status, group rollup propagation ----


class TestDoneFlag:
    """Phase 2 of the `stx next` work.

    Covers:
      - is_terminal toggle on a status does NOT retro-mark existing tasks
      - moving a task into / out of a terminal status auto-flips task.done
      - manual mark_task_done / mark_task_undone overrides
      - journal source distinguishes auto vs manual flips
    """

    def _seed(
        self,
        conn: sqlite3.Connection,
        *,
        terminal_done: bool = True,
    ) -> dict[str, int]:
        """Workspace with a `todo` (non-terminal) and `done` (terminal) status,
        plus a parent group `g_root` containing two tasks. The terminal flag
        on `done` can be flipped via `terminal_done=False` to test the
        non-terminal path.
        """
        wid = insert_workspace(conn, "w")
        todo_id = insert_status(conn, wid, "todo")
        done_id = insert_status(conn, wid, "done")
        if terminal_done:
            service.update_status(conn, done_id, {"is_terminal": True}, source="test")
        gid = insert_group(conn, wid, "g_root")
        t1 = insert_task(conn, wid, "t1", todo_id)
        t2 = insert_task(conn, wid, "t2", todo_id)
        service.assign_task_to_group(conn, t1, gid, source="test")
        service.assign_task_to_group(conn, t2, gid, source="test")
        return {
            "wid": wid,
            "todo": todo_id,
            "done": done_id,
            "gid": gid,
            "t1": t1,
            "t2": t2,
        }

    def test_create_into_terminal_status_sets_done(self, conn: sqlite3.Connection) -> None:
        # Tasks created directly into a terminal status must start as done=True.
        ids = self._seed(conn)
        tid = service.create_task(conn, ids["wid"], "pre-done task", ids["done"])
        assert service.get_task(conn, tid).done is True

    def test_create_into_non_terminal_status_leaves_done_false(
        self, conn: sqlite3.Connection
    ) -> None:
        ids = self._seed(conn)
        tid = service.create_task(conn, ids["wid"], "not done task", ids["todo"])
        assert service.get_task(conn, tid).done is False

    def test_is_terminal_toggle_does_not_retro_mark(self, conn: sqlite3.Connection) -> None:
        # Seed without terminal flag. Tasks already in `done` status before
        # the flag flips should not be retroactively marked done.
        ids = self._seed(conn, terminal_done=False)
        service.update_task(conn, ids["t1"], {"status_id": ids["done"]}, source="test")
        assert service.get_task(conn, ids["t1"]).done is False
        # Now flip the flag — t1 should still be not-done.
        service.update_status(conn, ids["done"], {"is_terminal": True}, source="test")
        assert service.get_task(conn, ids["t1"]).done is False

    def test_move_into_terminal_status_auto_marks_done(
        self, conn: sqlite3.Connection
    ) -> None:
        ids = self._seed(conn)
        service.update_task(conn, ids["t1"], {"status_id": ids["done"]}, source="cli")
        t1 = service.get_task(conn, ids["t1"])
        assert t1.done is True
        # Auto flip is journaled with source="auto", separate from the
        # status_id change which kept its caller-supplied source.
        rows = conn.execute(
            "SELECT field, source FROM journal WHERE entity_type='task' AND entity_id=? "
            "ORDER BY id",
            (ids["t1"],),
        ).fetchall()
        fields_sources = [(r["field"], r["source"]) for r in rows]
        assert ("status_id", "cli") in fields_sources
        assert ("done", "auto") in fields_sources

    def test_move_out_of_terminal_status_retains_done(
        self, conn: sqlite3.Connection
    ) -> None:
        # done is sticky: moving OUT of a terminal status does NOT clear it.
        # Only explicit mark_task_undone can clear done.
        ids = self._seed(conn)
        service.update_task(conn, ids["t1"], {"status_id": ids["done"]}, source="cli")
        assert service.get_task(conn, ids["t1"]).done is True
        service.update_task(conn, ids["t1"], {"status_id": ids["todo"]}, source="cli")
        assert service.get_task(conn, ids["t1"]).done is True

    def test_mark_task_done_manual(self, conn: sqlite3.Connection) -> None:
        ids = self._seed(conn)
        service.mark_task_done(conn, ids["t1"], source="cli")
        assert service.get_task(conn, ids["t1"]).done is True
        rows = conn.execute(
            "SELECT source FROM journal WHERE entity_type='task' AND entity_id=? "
            "AND field='done'",
            (ids["t1"],),
        ).fetchall()
        assert any(r["source"] == "cli" for r in rows)

    def test_mark_task_undone_manual(self, conn: sqlite3.Connection) -> None:
        ids = self._seed(conn)
        service.mark_task_done(conn, ids["t1"], source="cli")
        service.mark_task_undone(conn, ids["t1"], source="cli")
        assert service.get_task(conn, ids["t1"]).done is False

    def test_mark_task_done_is_true_noop(self, conn: sqlite3.Connection) -> None:
        # mark_task_done on an already-done task must not write (version unchanged).
        ids = self._seed(conn)
        service.mark_task_done(conn, ids["t1"], source="cli")
        v_after_first = service.get_task(conn, ids["t1"]).version
        service.mark_task_done(conn, ids["t1"], source="cli")
        v_after_second = service.get_task(conn, ids["t1"]).version
        assert v_after_first == v_after_second

    def test_mark_task_undone_is_true_noop(self, conn: sqlite3.Connection) -> None:
        # mark_task_undone on an already-not-done task must not write.
        ids = self._seed(conn)
        v_before = service.get_task(conn, ids["t1"]).version
        service.mark_task_undone(conn, ids["t1"], source="cli")
        v_after = service.get_task(conn, ids["t1"]).version
        assert v_before == v_after

    def test_archive_status_reassign_to_terminal_flips_done(
        self, conn: sqlite3.Connection
    ) -> None:
        ids = self._seed(conn)
        service.archive_status(
            conn, ids["todo"],
            reassign_to_status_id=ids["done"],
            source="cli",
        )
        assert service.get_task(conn, ids["t1"]).done is True
        assert service.get_task(conn, ids["t2"]).done is True
        rows = conn.execute(
            "SELECT field, source FROM journal WHERE entity_type='task' AND field='done' "
            "ORDER BY id",
        ).fetchall()
        assert all(r["source"] == "auto" for r in rows)
        assert len(rows) == 2

    def test_archive_status_reassign_to_nonterminal_leaves_done_false(
        self, conn: sqlite3.Connection
    ) -> None:
        ids = self._seed(conn)
        other = insert_status(conn, ids["wid"], "other")
        service.archive_status(
            conn, ids["todo"],
            reassign_to_status_id=other,
            source="cli",
        )
        assert service.get_task(conn, ids["t1"]).done is False
        assert service.get_task(conn, ids["t2"]).done is False


class TestComputeNextTasks:
    """Phase 3: `compute_next_tasks` topo-sorts the active `blocks` edge DAG."""

    def _seed_chain(self, conn: sqlite3.Connection) -> dict[str, int]:
        """Three tasks A → B → C connected by `blocks` edges. None are done.
        A is the only frontier item; B blocked by A; C blocked by B.
        """
        wid = insert_workspace(conn, "w")
        todo = insert_status(conn, wid, "todo")
        a = insert_task(conn, wid, "A", todo, priority=1)
        b = insert_task(conn, wid, "B", todo, priority=5)
        c = insert_task(conn, wid, "C", todo, priority=3)
        # A blocks B, B blocks C — A must finish before B, B before C.
        service.add_edge(
            conn,
            src=("task", a),
            dst=("task", b),
            kind="blocks",
            source="test",
        )
        service.add_edge(
            conn,
            src=("task", b),
            dst=("task", c),
            kind="blocks",
            source="test",
        )
        return {"wid": wid, "todo": todo, "a": a, "b": b, "c": c}

    def test_chain_frontier_progresses_as_tasks_complete(
        self, conn: sqlite3.Connection
    ) -> None:
        ids = self._seed_chain(conn)
        view = service.compute_next_tasks(conn, ids["wid"])
        assert tuple(t.id for t in view.ready) == (ids["a"],)
        # B and C are blocked.
        blocked_ids = {b.task.id for b in view.blocked}
        assert blocked_ids == {ids["b"], ids["c"]}

        service.mark_task_done(conn, ids["a"], source="cli")
        view = service.compute_next_tasks(conn, ids["wid"])
        assert tuple(t.id for t in view.ready) == (ids["b"],)

        service.mark_task_done(conn, ids["b"], source="cli")
        view = service.compute_next_tasks(conn, ids["wid"])
        assert tuple(t.id for t in view.ready) == (ids["c"],)

    def test_blocked_by_lists_pending_blockers(
        self, conn: sqlite3.Connection
    ) -> None:
        ids = self._seed_chain(conn)
        view = service.compute_next_tasks(conn, ids["wid"])
        b_entry = next(b for b in view.blocked if b.task.id == ids["b"])
        assert b_entry.blocked_by == (ids["a"],)
        c_entry = next(b for b in view.blocked if b.task.id == ids["c"])
        assert c_entry.blocked_by == (ids["b"],)

    def test_include_blocked_returns_full_topo(self, conn: sqlite3.Connection) -> None:
        ids = self._seed_chain(conn)
        view = service.compute_next_tasks(conn, ids["wid"], include_blocked=True)
        assert tuple(t.id for t in view.ready) == (ids["a"], ids["b"], ids["c"])
        assert view.blocked == ()

    def test_rank_orders_frontier_by_priority(
        self, conn: sqlite3.Connection
    ) -> None:
        wid = insert_workspace(conn, "w")
        todo = insert_status(conn, wid, "todo")
        # Three independent tasks, all in the frontier. Different priorities.
        low = insert_task(conn, wid, "low", todo, priority=1)
        high = insert_task(conn, wid, "high", todo, priority=9)
        mid = insert_task(conn, wid, "mid", todo, priority=5)
        unranked = service.compute_next_tasks(conn, wid)
        # Default order: by id.
        assert tuple(t.id for t in unranked.ready) == (low, high, mid)
        ranked = service.compute_next_tasks(conn, wid, rank=True)
        # Ranked order: by priority desc.
        assert tuple(t.id for t in ranked.ready) == (high, mid, low)

    def test_group_endpoint_expands_to_member_tasks(
        self, conn: sqlite3.Connection
    ) -> None:
        wid = insert_workspace(conn, "w")
        todo = insert_status(conn, wid, "todo")
        gid = insert_group(conn, wid, "g")
        member1 = insert_task(conn, wid, "m1", todo)
        member2 = insert_task(conn, wid, "m2", todo)
        service.assign_task_to_group(conn, member1, gid, source="test")
        service.assign_task_to_group(conn, member2, gid, source="test")
        target = insert_task(conn, wid, "target", todo)
        # Group `g` blocks `target` — every member of g must finish first.
        service.add_edge(
            conn,
            src=("group", gid),
            dst=("task", target),
            kind="blocks",
            source="test",
        )
        view = service.compute_next_tasks(conn, wid)
        # Frontier is the two group members — target is blocked by both.
        ready_ids = {t.id for t in view.ready}
        assert ready_ids == {member1, member2}
        target_entry = next(b for b in view.blocked if b.task.id == target)
        assert set(target_entry.blocked_by) == {member1, member2}

        # Finishing only one member is not enough.
        service.mark_task_done(conn, member1, source="cli")
        view = service.compute_next_tasks(conn, wid)
        assert {t.id for t in view.ready} == {member2}

        service.mark_task_done(conn, member2, source="cli")
        view = service.compute_next_tasks(conn, wid)
        assert {t.id for t in view.ready} == {target}

    def test_archived_blocker_is_ignored(self, conn: sqlite3.Connection) -> None:
        ids = self._seed_chain(conn)
        # Archive A — B should become unblocked even though A is not done.
        # This relies on the archived-task universe filter in compute_next_tasks.
        service.archive_task(conn, ids["a"], source="cli")
        view = service.compute_next_tasks(conn, ids["wid"])
        ready_ids = {t.id for t in view.ready}
        assert ids["b"] in ready_ids
        # C is still blocked by B.
        assert any(b.task.id == ids["c"] for b in view.blocked)

    def test_empty_workspace_returns_empty_view(self, conn: sqlite3.Connection) -> None:
        wid = insert_workspace(conn, "w")
        view = service.compute_next_tasks(conn, wid)
        assert view.ready == ()
        assert view.blocked == ()

    def test_cycle_detection_raises(self, conn: sqlite3.Connection) -> None:
        # Bypass the service-layer cycle check by inserting a cycle directly
        # via raw SQL, then confirm compute_next_tasks surfaces it as RuntimeError.
        wid = insert_workspace(conn, "w")
        todo = insert_status(conn, wid, "todo")
        a = insert_task(conn, wid, "A", todo)
        b = insert_task(conn, wid, "B", todo)
        # A blocks B and B blocks A — a cycle.
        service.add_edge(conn, src=("task", a), dst=("task", b),
                         kind="blocks", source="test")
        # Bypass the acyclic check for the return edge.
        conn.execute(
            "INSERT INTO edges (from_type, from_id, to_type, to_id, workspace_id, kind, acyclic) "
            "VALUES ('task', ?, 'task', ?, ?, 'blocks', 1)",
            (b, a, wid),
        )
        conn.commit()
        with pytest.raises(RuntimeError, match="cycle detected"):
            service.compute_next_tasks(conn, wid, include_blocked=True)



# ---- Path-based ref resolution (introduced 0.15) ----


class TestParseRef:
    def test_bare_title(self) -> None:
        p = service.parse_ref("foo")
        assert p.kind == "bare"
        assert p.segments == ("foo",)
        assert p.task_title is None

    def test_group_path(self) -> None:
        p = service.parse_ref("a/b/c")
        assert p.kind == "group_path"
        assert p.segments == ("a", "b", "c")

    def test_task_path_nested(self) -> None:
        p = service.parse_ref("a/b:leaf")
        assert p.kind == "task_path"
        assert p.segments == ("a", "b")
        assert p.task_title == "leaf"

    def test_task_path_root(self) -> None:
        p = service.parse_ref(":root-task")
        assert p.kind == "task_path"
        assert p.segments == ()
        assert p.task_title == "root-task"

    def test_last_colon_wins(self) -> None:
        # Only the LAST colon splits group-path from task title. Earlier
        # colons aren't legal in titles, but parse_ref is pure and just
        # delegates to validation downstream — confirm split semantics.
        p = service.parse_ref("a:b:c")
        assert p.kind == "task_path"
        assert p.task_title == "c"

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty ref"):
            service.parse_ref("")

    def test_empty_segment_raises(self) -> None:
        with pytest.raises(ValueError, match="empty path segment"):
            service.parse_ref("a//b")
        with pytest.raises(ValueError, match="empty path segment"):
            service.parse_ref("foo/")
        with pytest.raises(ValueError, match="empty path segment"):
            service.parse_ref("//a")  # leading-slash anchor + empty seg

    def test_empty_task_title_raises(self) -> None:
        with pytest.raises(ValueError, match="empty task title"):
            service.parse_ref("a/b:")

    # ---- Leading-slash anchor (introduced 0.15) ----

    def test_leading_slash_single_segment_is_group_path(self) -> None:
        # `/A` promotes a single-segment ref from `bare` to `group_path`,
        # disambiguating root group A from a task title A.
        p = service.parse_ref("/A")
        assert p.kind == "group_path"
        assert p.segments == ("A",)

    def test_leading_slash_multi_segment(self) -> None:
        p = service.parse_ref("/A/B/C")
        assert p.kind == "group_path"
        assert p.segments == ("A", "B", "C")

    def test_leading_slash_on_task_path_prefix(self) -> None:
        # `/A:foo` — leading slash on the group prefix is cosmetic.
        p = service.parse_ref("/A:foo")
        assert p.kind == "task_path"
        assert p.segments == ("A",)
        assert p.task_title == "foo"

    def test_leading_slash_alone_raises(self) -> None:
        with pytest.raises(ValueError, match="empty group path"):
            service.parse_ref("/")

    def test_leading_slash_with_empty_task_prefix_raises(self) -> None:
        # `/:foo` — root has no name; rejected.
        with pytest.raises(ValueError, match="empty group path"):
            service.parse_ref("/:foo")


class TestResolveGroupPath:
    def _setup(self, conn: sqlite3.Connection) -> int:
        return insert_workspace(conn, "w")

    def test_strict_walk(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        a = service.create_group(conn, wid, "a")
        b = service.create_group(conn, wid, "b", parent_id=a.id)
        c = service.create_group(conn, wid, "c", parent_id=b.id)
        assert service.resolve_group_path(conn, wid, ("a", "b", "c")) == c
        assert service.resolve_group_path(conn, wid, ("a", "b")) == b
        assert service.resolve_group_path(conn, wid, ("a",)) == a

    def test_does_not_match_non_root_first_segment(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        a = service.create_group(conn, wid, "a")
        service.create_group(conn, wid, "b", parent_id=a.id)
        with pytest.raises(LookupError, match="not found under <root>"):
            service.resolve_group_path(conn, wid, ("b",))

    def test_missing_segment_names_path_so_far(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        a = service.create_group(conn, wid, "a")
        service.create_group(conn, wid, "b", parent_id=a.id)
        with pytest.raises(LookupError, match="'c'.*under a/b"):
            service.resolve_group_path(conn, wid, ("a", "b", "c"))

    def test_collision_under_different_parents(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        p1 = service.create_group(conn, wid, "p1")
        p2 = service.create_group(conn, wid, "p2")
        s1 = service.create_group(conn, wid, "shared", parent_id=p1.id)
        s2 = service.create_group(conn, wid, "shared", parent_id=p2.id)
        assert service.resolve_group_path(conn, wid, ("p1", "shared")) == s1
        assert service.resolve_group_path(conn, wid, ("p2", "shared")) == s2

    def test_resolve_group_dispatches_to_path(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        a = service.create_group(conn, wid, "a")
        b = service.create_group(conn, wid, "b", parent_id=a.id)
        assert service.resolve_group(conn, wid, "a/b") == b

    def test_resolve_group_rejects_task_path(self, conn: sqlite3.Connection) -> None:
        wid = self._setup(conn)
        with pytest.raises(ValueError, match="expected group ref"):
            service.resolve_group(conn, wid, "a:foo")


class TestResolveTaskPath:
    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int]:
        wid = insert_workspace(conn, "w")
        sid = insert_status(conn, wid, "todo")
        return wid, sid

    def test_task_under_group(self, conn: sqlite3.Connection) -> None:
        wid, sid = self._setup(conn)
        a = service.create_group(conn, wid, "a")
        b = service.create_group(conn, wid, "b", parent_id=a.id)
        t = service.create_task(conn, wid, "leaf", sid, group_id=b.id)
        assert service.resolve_task_path(conn, wid, ("a", "b"), "leaf").id == t.id

    def test_root_task(self, conn: sqlite3.Connection) -> None:
        wid, sid = self._setup(conn)
        t = service.create_task(conn, wid, "ungrouped", sid)
        assert service.resolve_task_path(conn, wid, (), "ungrouped").id == t.id

    def test_task_under_group_misses_other_group(self, conn: sqlite3.Connection) -> None:
        wid, sid = self._setup(conn)
        a = service.create_group(conn, wid, "a")
        b = service.create_group(conn, wid, "b")
        service.create_task(conn, wid, "shared", sid, group_id=a.id)
        with pytest.raises(LookupError, match="not found in b"):
            service.resolve_task_path(conn, wid, ("b",), "shared")

    def test_resolve_task_id_dispatch(self, conn: sqlite3.Connection) -> None:
        wid, sid = self._setup(conn)
        a = service.create_group(conn, wid, "a")
        t1 = service.create_task(conn, wid, "leaf", sid, group_id=a.id)
        t2 = service.create_task(conn, wid, "rootleaf", sid)
        assert service.resolve_task_id(conn, wid, "a:leaf") == t1.id
        assert service.resolve_task_id(conn, wid, ":rootleaf") == t2.id
        assert service.resolve_task_id(conn, wid, str(t1.id)) == t1.id

    def test_resolve_task_id_rejects_group_path(self, conn: sqlite3.Connection) -> None:
        wid, _ = self._setup(conn)
        with pytest.raises(ValueError, match="expected task ref"):
            service.resolve_task_id(conn, wid, "a/b/c")


class TestTitleValidation:
    def _setup(self, conn: sqlite3.Connection) -> tuple[int, int]:
        wid = insert_workspace(conn, "w")
        sid = insert_status(conn, wid, "todo")
        return wid, sid

    def test_create_task_rejects_slash(self, conn: sqlite3.Connection) -> None:
        wid, sid = self._setup(conn)
        with pytest.raises(ValueError, match="cannot contain"):
            service.create_task(conn, wid, "bad/title", sid)

    def test_create_task_rejects_colon(self, conn: sqlite3.Connection) -> None:
        wid, sid = self._setup(conn)
        with pytest.raises(ValueError, match="cannot contain"):
            service.create_task(conn, wid, "bad:title", sid)

    def test_create_group_rejects_slash(self, conn: sqlite3.Connection) -> None:
        wid, _ = self._setup(conn)
        with pytest.raises(ValueError, match="cannot contain"):
            service.create_group(conn, wid, "bad/title")

    def test_create_group_rejects_colon(self, conn: sqlite3.Connection) -> None:
        wid, _ = self._setup(conn)
        with pytest.raises(ValueError, match="cannot contain"):
            service.create_group(conn, wid, "bad:title")

    def test_update_task_rejects_slash_in_title(self, conn: sqlite3.Connection) -> None:
        wid, sid = self._setup(conn)
        t = service.create_task(conn, wid, "ok", sid)
        with pytest.raises(ValueError, match="cannot contain"):
            service.update_task(conn, t.id, {"title": "bad/title"}, "test")

    def test_update_group_rejects_colon_in_title(self, conn: sqlite3.Connection) -> None:
        wid, _ = self._setup(conn)
        g = service.create_group(conn, wid, "ok")
        with pytest.raises(ValueError, match="cannot contain"):
            service.update_group(conn, g.id, {"title": "bad:title"}, "test")
