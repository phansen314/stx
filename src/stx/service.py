from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

from . import repository as repo
from .connection import transaction
from .formatting import parse_task_num
from .mappers import (
    group_to_detail,
    group_to_ref,
    task_to_detail,
    task_to_list_item,
)
from .models import (
    EdgeField,
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
    TaskFilter,
    Workspace,
)
from .service_models import (
    ArchivePreview,
    EdgeListItem,
    EdgeRef,
    EntityUpdatePreview,
    GroupDetail,
    GroupRef,
    MoveToWorkspacePreview,
    TaskDetail,
    TaskListItem,
    TaskMovePreview,
    WorkspaceContext,
    WorkspaceListStatus,
    WorkspaceListView,
)

# Sentinel that distinguishes "caller did not pass this field" from "caller
# explicitly set this field to None".  Used by update_task() to support
# partial updates where omitted fields are left unchanged.
_UNSET: Any = object()


# ---- Error translation ----

_UNIQUE_MESSAGES: dict[str, str] = {
    "workspaces.name": "a workspace with this name already exists",
    "statuses.workspace_id, statuses.name": "a status with this name already exists on this workspace",
    "tasks.workspace_id, tasks.title": "a task with this title already exists on this workspace",
    "uq_groups_workspace_parent_title_active": "a group with this title already exists under the same parent",
}

_UNIQUE_RE = re.compile(r"UNIQUE constraint failed: (.+)")


def _translate_integrity_error(
    exc: sqlite3.IntegrityError,
    context: str = "",
) -> ValueError | None:
    msg = str(exc)
    m = _UNIQUE_RE.search(msg)
    if m:
        constraint = m.group(1).strip()
        for pattern, human_msg in _UNIQUE_MESSAGES.items():
            if pattern in constraint:
                return ValueError(human_msg)
        if "edges" in constraint:
            return ValueError("an edge already exists between these entities with this kind")
        return ValueError("a unique constraint was violated")
    if "FOREIGN KEY constraint failed" in msg:
        if context:
            return ValueError(context)
        return ValueError("referenced entity does not exist or belongs to a different workspace")
    if "CHECK constraint failed" in msg:
        if "edges" in msg:
            return ValueError(
                "edge kind must match [a-z0-9_.-]+ and be 1-64 characters"
            )
        if context:
            return ValueError(context)
    return None


@contextmanager
def _friendly_errors(
    fk_context: str = "",
) -> Generator[None, None, None]:
    try:
        yield
    except sqlite3.IntegrityError as exc:
        translated = _translate_integrity_error(exc, fk_context)
        if translated is not None:
            raise translated from exc
        raise ValueError("database constraint violation") from exc


# ---- Private helpers ----


def _validate_task_fields(
    changes: dict[str, Any],
    *,
    workspace_id: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    if "priority" in changes:
        p = changes["priority"]
        if not isinstance(p, int):
            raise ValueError(f"priority must be an integer, got {p!r}")
    if "position" in changes:
        pos = changes["position"]
        if not isinstance(pos, int) or pos < 0:
            raise ValueError(f"position must be non-negative, got {pos}")
    start = changes.get("start_date")
    finish = changes.get("finish_date")
    if start is not None and finish is not None and finish < start:
        raise ValueError("finish date must be on or after start date")
    if conn is not None and workspace_id is not None:
        if "status_id" in changes:
            col = repo.get_status(conn, changes["status_id"])
            if col is None:
                raise LookupError(f"status {changes['status_id']} not found")
            if col.workspace_id != workspace_id:
                raise ValueError(
                    f"status {col.id} belongs to workspace {col.workspace_id}, not {workspace_id}"
                )
            if col.archived:
                raise ValueError(f"status {col.id} is archived")
        if "group_id" in changes and changes["group_id"] is not None:
            grp = repo.get_group(conn, changes["group_id"])
            if grp is None:
                raise LookupError(f"group {changes['group_id']} not found")
            if grp.workspace_id != workspace_id:
                raise ValueError(
                    f"group {grp.id} belongs to workspace {grp.workspace_id}, not {workspace_id}"
                )
            if grp.archived:
                raise ValueError(f"group {grp.id} is archived")


def _record_entity_changes(
    conn: sqlite3.Connection,
    entity_type: EntityType,
    entity_id: int,
    workspace_id: int,
    old: Any,
    changes: dict[str, Any],
    source: str,
) -> None:
    for key, new_val in changes.items():
        old_val = getattr(old, key, None)
        if old_val == new_val:
            continue
        repo.insert_journal_entry(
            conn,
            NewJournalEntry(
                entity_type=entity_type,
                entity_id=entity_id,
                workspace_id=workspace_id,
                field=key,
                old_value=str(old_val) if old_val is not None else None,
                new_value=str(new_val) if new_val is not None else None,
                source=source,
            ),
        )


def _record_edge_change(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
    workspace_id: int,
    *,
    added: bool,
    kind: str,
    acyclic: int,
    source: str,
) -> None:
    """Record edge add/archive in the journal.

    Emits TWO entries per mutation so both the endpoint and kind are captured:

      - ``field = EdgeField.ENDPOINT`` encodes the full edge identity as
        ``"<from_type>:<from_id>→<to_type>:<to_id>"`` (add: ``None → value``;
        archive: ``value → None``).
      - ``field = EdgeField.KIND`` carries the kind label symmetrically.

    ``entity_id = from_id`` so journal queries for "edges from node X"
    remain possible. ``entity_type = "edge"`` for all edge mutations.
    """
    endpoint = f"{from_type}:{from_id}\u2192{to_type}:{to_id}"
    repo.insert_journal_entry(
        conn,
        NewJournalEntry(
            entity_type=EntityType.EDGE,
            entity_id=from_id,
            workspace_id=workspace_id,
            field=EdgeField.ENDPOINT,
            old_value=None if added else endpoint,
            new_value=endpoint if added else None,
            source=source,
        ),
    )
    repo.insert_journal_entry(
        conn,
        NewJournalEntry(
            entity_type=EntityType.EDGE,
            entity_id=from_id,
            workspace_id=workspace_id,
            field=EdgeField.KIND,
            old_value=None if added else kind,
            new_value=kind if added else None,
            source=source,
        ),
    )


# ---- Workspace ----


def create_workspace(conn: sqlite3.Connection, name: str) -> Workspace:
    with transaction(conn), _friendly_errors():
        return repo.insert_workspace(conn, NewWorkspace(name=name))


def get_workspace(conn: sqlite3.Connection, workspace_id: int) -> Workspace:
    workspace = repo.get_workspace(conn, workspace_id)
    if workspace is None:
        raise LookupError(f"workspace {workspace_id} not found")
    return workspace


def get_workspace_by_name(conn: sqlite3.Connection, name: str) -> Workspace:
    workspace = repo.get_workspace_by_name(conn, name)
    if workspace is None:
        raise LookupError(f"workspace {name!r} not found")
    return workspace


def list_workspaces(
    conn: sqlite3.Connection,
    *,
    include_archived: bool = False,
    only_archived: bool = False,
) -> tuple[Workspace, ...]:
    return repo.list_workspaces(
        conn,
        include_archived=include_archived,
        only_archived=only_archived,
    )


def update_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
    changes: dict[str, Any],
    source: str = "cli",
) -> Workspace:
    with transaction(conn), _friendly_errors():
        old = repo.get_workspace(conn, workspace_id)
        result = repo.update_workspace(conn, workspace_id, changes)
        if old is not None:
            _record_entity_changes(
                conn, EntityType.WORKSPACE, workspace_id, workspace_id, old, changes, source
            )
        return result


# ---- Status ----


def create_status(
    conn: sqlite3.Connection,
    workspace_id: int,
    name: str,
) -> Status:
    with transaction(conn), _friendly_errors():
        return repo.insert_status(conn, NewStatus(workspace_id=workspace_id, name=name))


def get_status(conn: sqlite3.Connection, status_id: int) -> Status:
    col = repo.get_status(conn, status_id)
    if col is None:
        raise LookupError(f"status {status_id} not found")
    return col


def get_status_by_name(
    conn: sqlite3.Connection,
    workspace_id: int,
    name: str,
) -> Status:
    col = repo.get_status_by_name(conn, workspace_id, name)
    if col is None:
        raise LookupError(f"status {name!r} not found")
    return col


def list_statuses(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    include_archived: bool = False,
    only_archived: bool = False,
) -> tuple[Status, ...]:
    return repo.list_statuses(
        conn, workspace_id, include_archived=include_archived, only_archived=only_archived
    )


def update_status(
    conn: sqlite3.Connection,
    status_id: int,
    changes: dict[str, Any],
    source: str = "cli",
) -> Status:
    with transaction(conn), _friendly_errors():
        if changes.get("archived") is True:
            active_tasks = repo.list_tasks_by_status(conn, status_id)
            if active_tasks:
                raise ValueError(
                    f"status has {len(active_tasks)} active task(s); move or archive them first"
                )
        old = repo.get_status(conn, status_id)
        result = repo.update_status(conn, status_id, changes)
        if old is not None:
            _record_entity_changes(
                conn, EntityType.STATUS, status_id, old.workspace_id, old, changes, source
            )
        return result


def archive_status(
    conn: sqlite3.Connection,
    status_id: int,
    *,
    reassign_to_status_id: int | None = None,
    force: bool = False,
    source: str = "cli",
) -> Status:
    """Archive a status, optionally handling active tasks via reassign or force-archive."""
    with transaction(conn), _friendly_errors():
        old = repo.get_status(conn, status_id)
        active_tasks = repo.list_tasks_by_status(conn, status_id)
        if active_tasks:
            if reassign_to_status_id is not None:
                for task in active_tasks:
                    repo.update_task(conn, task.id, {"status_id": reassign_to_status_id})
            elif force:
                for task in active_tasks:
                    repo.update_task(conn, task.id, {"archived": True})
            else:
                raise ValueError(
                    f"status has {len(active_tasks)} active task(s); "
                    "use --reassign-to OTHER_STATUS or --force to override"
                )
        result = repo.update_status(conn, status_id, {"archived": True})
        if old is not None:
            _record_entity_changes(
                conn,
                EntityType.STATUS,
                status_id,
                old.workspace_id,
                old,
                {"archived": True},
                source,
            )
        return result


# ---- Task ----


def create_task(
    conn: sqlite3.Connection,
    workspace_id: int,
    title: str,
    status_id: int,
    *,
    description: str | None = None,
    priority: int = 1,
    due_date: int | None = None,
    position: int = 0,
    start_date: int | None = None,
    finish_date: int | None = None,
    group_id: int | None = None,
) -> Task:
    fields: dict[str, Any] = {
        "priority": priority,
        "position": position,
    }
    if start_date is not None:
        fields["start_date"] = start_date
    if finish_date is not None:
        fields["finish_date"] = finish_date
    if group_id is not None:
        fields["group_id"] = group_id
    _validate_task_fields(fields, workspace_id=workspace_id, conn=conn)
    with transaction(conn), _friendly_errors():
        return repo.insert_task(
            conn,
            NewTask(
                workspace_id=workspace_id,
                title=title,
                status_id=status_id,
                description=description,
                priority=priority,
                due_date=due_date,
                position=position,
                start_date=start_date,
                finish_date=finish_date,
                group_id=group_id,
            ),
        )


def get_task(conn: sqlite3.Connection, task_id: int) -> Task:
    task = repo.get_task(conn, task_id)
    if task is None:
        raise LookupError(f"task {task_id} not found")
    return task


def get_task_by_title(conn: sqlite3.Connection, workspace_id: int, title: str) -> Task:
    task = repo.get_task_by_title(conn, workspace_id, title)
    if task is None:
        raise LookupError(f"task {title!r} not found")
    return task


def resolve_task_id(
    conn: sqlite3.Connection,
    workspace_id: int,
    raw: str,
) -> int:
    """Resolve a task identifier to its ID.

    Numeric forms ('1', 'task-0001', '#1') are tried first; anything else
    falls back to a title lookup on this workspace. A task whose title
    literally matches `task-NNNN` would be resolved as an ID, not a title —
    avoid such titles.
    """
    try:
        return parse_task_num(raw)
    except ValueError:
        pass
    return get_task_by_title(conn, workspace_id, raw).id


def get_task_detail(conn: sqlite3.Connection, task_id: int) -> TaskDetail:
    task = get_task(conn, task_id)
    status = get_status(conn, task.status_id)
    group = repo.get_group(conn, task.group_id) if task.group_id is not None else None
    # Naming convention: edge_sources = incoming edges (other nodes that point
    # at this task); edge_targets = outgoing edges (nodes this task points at).
    edge_sources = tuple(
        EdgeRef(node_type=nt, node_id=nid, node_title=title, kind=k)
        for nt, nid, title, k in repo.list_edge_sources_into_hydrated(conn, "task", task_id)
    )
    edge_targets = tuple(
        EdgeRef(node_type=nt, node_id=nid, node_title=title, kind=k)
        for nt, nid, title, k in repo.list_edge_targets_from_hydrated(conn, "task", task_id)
    )
    history = repo.list_journal(conn, EntityType.TASK, task_id)
    return task_to_detail(
        task,
        status=status,
        group=group,
        edge_sources=edge_sources,
        edge_targets=edge_targets,
        history=history,
    )


def list_tasks(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Task, ...]:
    return repo.list_tasks(conn, workspace_id, include_archived=include_archived)


def list_tasks_filtered(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    task_filter: TaskFilter | None = None,
) -> tuple[Task, ...]:
    return repo.list_tasks_filtered(conn, workspace_id, task_filter=task_filter)


def get_workspace_list_view(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    status_id: int | None = None,
    group_id: int | None = None,
    priority: int | None = None,
    search: str | None = None,
    include_archived: bool = False,
    only_archived: bool = False,
) -> WorkspaceListView:
    """Denormalized workspace view for list rendering. Groups task list items
    by status."""
    workspace = get_workspace(conn, workspace_id)
    task_filter = TaskFilter(
        status_id=status_id,
        priority=priority,
        search=search,
        group_id=group_id,
        include_archived=include_archived,
        only_archived=only_archived,
    )
    tasks = repo.list_tasks_filtered(conn, workspace_id, task_filter=task_filter)
    statuses = repo.list_statuses(
        conn, workspace_id, include_archived=include_archived or only_archived
    )

    items_by_status: dict[int, list[Task]] = {s.id: [] for s in statuses}
    for task in tasks:
        bucket = items_by_status.get(task.status_id)
        if bucket is not None:
            bucket.append(task)

    status_list = tuple(
        WorkspaceListStatus(
            status=s,
            tasks=tuple(task_to_list_item(t) for t in items_by_status[s.id]),
        )
        for s in statuses
    )
    return WorkspaceListView(workspace=workspace, statuses=status_list)


def get_workspace_context(conn: sqlite3.Connection, workspace_id: int) -> WorkspaceContext:
    """Aggregated workspace state: view + all groups. Active items only."""
    view = get_workspace_list_view(conn, workspace_id)
    groups = list_all_groups(conn, workspace_id)
    return WorkspaceContext(view=view, groups=groups)


def update_task(
    conn: sqlite3.Connection,
    task_id: int,
    changes: dict[str, Any],
    source: str,
) -> Task:
    if not changes:
        return get_task(conn, task_id)
    with transaction(conn), _friendly_errors():
        return _update_task_body(conn, task_id, changes, source)


def _validate_task_update(
    conn: sqlite3.Connection,
    old: Task,
    changes: dict[str, Any],
) -> None:
    """Merge + validate changes against an existing task. Shared by
    `_update_task_body` (write path) and `preview_update_task` (dry-run)
    so both paths enforce identical constraints.

    Mutates nothing on the DB. Raises ValueError on invalid input,
    LookupError on missing referenced entities.
    """
    merged: dict[str, Any] = {}
    if "start_date" in changes or "finish_date" in changes:
        merged["start_date"] = changes.get("start_date", old.start_date)
        merged["finish_date"] = changes.get("finish_date", old.finish_date)
    merged.update(changes)
    _validate_task_fields(merged, workspace_id=old.workspace_id, conn=conn)


def _update_task_body(
    conn: sqlite3.Connection,
    task_id: int,
    changes: dict[str, Any],
    source: str,
) -> Task:
    """Inner body of update_task. Assumes the caller holds a transaction.

    Split out so service functions that already hold a transaction (e.g. the
    `assign_task_to_group` wrapper) can call into update_task's logic without
    triggering the transaction manager's anti-nesting guard.
    """
    old = get_task(conn, task_id)
    _validate_task_update(conn, old, changes)
    if not changes:
        return old
    updated = repo.update_task(conn, task_id, changes)
    _record_entity_changes(
        conn, EntityType.TASK, task_id, old.workspace_id, old, changes, source
    )
    return updated


def move_task(
    conn: sqlite3.Connection,
    task_id: int,
    status_id: int,
    position: int,
    source: str,
) -> Task:
    """Move a task to (status_id, position)."""
    changes: dict[str, Any] = {"status_id": status_id, "position": position}
    return update_task(conn, task_id, changes, source)


def _validate_move_to_workspace(
    conn: sqlite3.Connection,
    task_id: int,
    target_workspace_id: int,
    target_status_id: int,
) -> tuple[Task, bool, str | None, tuple[tuple[str, int], ...]]:
    """Check move-to-workspace preconditions. Non-mutating.
    Returns (task, can_move, blocking_reason, edge_endpoints).
    edge_endpoints is a deduped, sorted tuple of (node_type, node_id) pairs
    for every active edge touching this task (in or out). Type is preserved
    so tasks and groups with the same numeric ID don't collapse.
    Raises LookupError only if task_id does not exist."""
    task = get_task(conn, task_id)
    edge_endpoints: tuple[tuple[str, int], ...] = ()
    if task.archived:
        return task, False, f"task {task_id} is archived", edge_endpoints
    sources = repo.list_edge_sources_into(conn, "task", task_id)
    targets = repo.list_edge_targets_from(conn, "task", task_id)
    if sources or targets:
        edge_endpoints = tuple(sorted(set((*sources, *targets))))
        label = ", ".join(f"{nt}:{nid}" for nt, nid in edge_endpoints)
        return (
            task,
            False,
            (
                f"task {task_id} has active edges ({label}); "
                "archive them before moving to another workspace"
            ),
            edge_endpoints,
        )
    target_col = repo.get_status(conn, target_status_id)
    if target_col is None or target_col.workspace_id != target_workspace_id:
        return (
            task,
            False,
            (f"status {target_status_id} does not belong to workspace {target_workspace_id}"),
            edge_endpoints,
        )
    if target_col.archived:
        return task, False, f"status {target_status_id} is archived", edge_endpoints
    return task, True, None, edge_endpoints


def preview_move_to_workspace(
    conn: sqlite3.Connection,
    task_id: int,
    target_workspace_id: int,
    target_status_id: int,
) -> MoveToWorkspacePreview:
    """Dry-run the same validation as move_task_to_workspace. Does not mutate."""
    task, can_move, reason, edge_endpoints = _validate_move_to_workspace(
        conn,
        task_id,
        target_workspace_id,
        target_status_id,
    )
    return MoveToWorkspacePreview(
        task_id=task.id,
        task_title=task.title,
        source_workspace_id=task.workspace_id,
        target_workspace_id=target_workspace_id,
        target_status_id=target_status_id,
        can_move=can_move,
        blocking_reason=reason,
        edge_endpoints=edge_endpoints,
        is_archived=task.archived,
    )


def move_task_to_workspace(
    conn: sqlite3.Connection,
    task_id: int,
    target_workspace_id: int,
    target_status_id: int,
    *,
    source: str,
) -> Task:
    with transaction(conn), _friendly_errors():
        old, can_move, reason, _ = _validate_move_to_workspace(
            conn,
            task_id,
            target_workspace_id,
            target_status_id,
        )
        if not can_move:
            raise ValueError(reason)

        new = repo.insert_task(
            conn,
            NewTask(
                workspace_id=target_workspace_id,
                title=old.title,
                status_id=target_status_id,
                description=old.description,
                priority=old.priority,
                due_date=old.due_date,
                position=0,
                start_date=old.start_date,
                finish_date=old.finish_date,
            ),
        )

        repo.copy_task_metadata(conn, task_id, new.id)

        repo.update_task(conn, task_id, {"archived": True})
        _record_entity_changes(
            conn, EntityType.TASK, task_id, old.workspace_id, old, {"archived": True}, source
        )
        # Refetch: `new` was built before metadata was attached.
        return get_task(conn, new.id)


# ---- Entity metadata ----
#
# Tasks, workspaces, projects, and groups all carry a JSON key/value metadata
# blob. Keys are normalized to lowercase on write/read (matching the codebase's
# COLLATE NOCASE convention, which can't be applied directly to JSON keys).


_LOWERCASE_IDENT_RE = re.compile(r"^[a-z0-9_.-]+$")
_META_VALUE_MAX = 500


def _normalize_lowercase_ident(value: str, *, max_len: int, label: str) -> str:
    """Lowercase and validate an identifier that must match [a-z0-9_.-]+."""
    normalized = value.lower()
    if not normalized or len(normalized) > max_len:
        raise ValueError(f"{label} must be 1-{max_len} characters")
    if not _LOWERCASE_IDENT_RE.match(normalized):
        raise ValueError(f"{label} must match [a-z0-9_.-]+, got {value!r}")
    return normalized


def _normalize_meta_key(key: str) -> str:
    """Lowercase and validate a metadata key.

    Keys are stored lowercase to match the codebase's COLLATE NOCASE convention.
    JSON-stored fields cannot use column collation, so we normalize at the
    application layer instead.
    """
    return _normalize_lowercase_ident(key, max_len=64, label="metadata key")


def _normalize_edge_kind(kind: str) -> str:
    """Lowercase and validate an edge kind string."""
    return _normalize_lowercase_ident(kind, max_len=64, label="edge kind")


def _get_entity_meta(
    conn: sqlite3.Connection,
    entity_id: int,
    key: str,
    *,
    fetcher: Callable[[sqlite3.Connection, int], Any],
    entity_name: str,
) -> str:
    """Generic entity-metadata read. `fetcher` must return an object whose
    `.metadata` attribute is a dict of lowercase keys to values. Raises
    ``ValueError`` for invalid key shape, ``LookupError`` if the entity is
    missing or the key isn't present.
    """
    normalized = _normalize_meta_key(key)
    entity = fetcher(conn, entity_id)
    if normalized not in entity.metadata:
        raise LookupError(f"metadata key {key!r} not found on {entity_name} {entity_id}")
    return entity.metadata[normalized]


def _set_entity_meta(
    conn: sqlite3.Connection,
    entity_id: int,
    key: str,
    value: str,
    *,
    entity_type: EntityType,
    setter: Callable[[sqlite3.Connection, int, str, str], None],
    fetcher: Callable[[sqlite3.Connection, int], Any],
    source: str = "cli",
) -> Any:
    """Generic entity-metadata write. Validates the key and value length,
    then persists via `setter` and returns the refreshed entity from `fetcher`.
    """
    normalized = _normalize_meta_key(key)
    if len(value) > _META_VALUE_MAX:
        raise ValueError(f"metadata value must be \u2264 {_META_VALUE_MAX} characters")
    with transaction(conn), _friendly_errors():
        old_entity = fetcher(conn, entity_id)
        old_value = old_entity.metadata.get(normalized) if old_entity is not None else None
        setter(conn, entity_id, normalized, value)
        result = fetcher(conn, entity_id)
        if old_value != value and result is not None:
            repo.insert_journal_entry(
                conn,
                NewJournalEntry(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    workspace_id=getattr(result, "workspace_id", entity_id),
                    field=f"meta.{normalized}",
                    old_value=old_value,
                    new_value=value,
                    source=source,
                ),
            )
        return result


def _remove_entity_meta(
    conn: sqlite3.Connection,
    entity_id: int,
    key: str,
    *,
    entity_type: EntityType,
    remover: Callable[[sqlite3.Connection, int, str], None],
    fetcher: Callable[[sqlite3.Connection, int], Any],
    entity_name: str,
    source: str = "cli",
) -> str:
    """Generic entity-metadata removal. Raises ``LookupError`` if the key
    isn't present on the entity. Returns the old value atomically so
    callers don't need a separate read.
    """
    normalized = _normalize_meta_key(key)
    with transaction(conn), _friendly_errors():
        old = fetcher(conn, entity_id)
        if normalized not in old.metadata:
            raise LookupError(f"metadata key {key!r} not found on {entity_name} {entity_id}")
        old_value = old.metadata[normalized]
        remover(conn, entity_id, normalized)
        repo.insert_journal_entry(
            conn,
            NewJournalEntry(
                entity_type=entity_type,
                entity_id=entity_id,
                workspace_id=getattr(old, "workspace_id", entity_id),
                field=f"meta.{normalized}",
                old_value=old_value,
                new_value=None,
                source=source,
            ),
        )
        return old_value


def _replace_entity_metadata(
    conn: sqlite3.Connection,
    entity_id: int,
    new_metadata: dict[str, str],
    *,
    entity_type: EntityType,
    writer: Callable[[sqlite3.Connection, int, str], None],
    fetcher: Callable[[sqlite3.Connection, int], Any],
    source: str = "cli",
) -> Any:
    """Generic bulk-replace for an entity's metadata blob.

    Normalizes every key, rejects duplicates after normalization, enforces
    the per-value length cap, then writes the whole dict in one UPDATE and
    journals each added/changed/removed key.
    """
    normalized: dict[str, str] = {}
    for raw_key, value in new_metadata.items():
        key = _normalize_meta_key(raw_key)
        if key in normalized:
            raise ValueError(f"duplicate metadata key after normalization: {key!r}")
        if len(value) > _META_VALUE_MAX:
            raise ValueError(
                f"metadata value for key {key!r} must be \u2264 {_META_VALUE_MAX} characters"
            )
        normalized[key] = value
    with transaction(conn), _friendly_errors():
        old_entity = fetcher(conn, entity_id)
        old_meta = old_entity.metadata if old_entity is not None else {}
        writer(conn, entity_id, json.dumps(normalized))
        result = fetcher(conn, entity_id)
        if result is not None:
            for k in set(old_meta) | set(normalized):
                old_val = old_meta.get(k)
                new_val = normalized.get(k)
                if old_val != new_val:
                    repo.insert_journal_entry(
                        conn,
                        NewJournalEntry(
                            entity_type=entity_type,
                            entity_id=entity_id,
                            workspace_id=getattr(result, "workspace_id", entity_id),
                            field=f"meta.{k}",
                            old_value=old_val,
                            new_value=new_val,
                            source=source,
                        ),
                    )
        return result


# ---- Task metadata ----


def get_task_meta(conn: sqlite3.Connection, task_id: int, key: str) -> str:
    return _get_entity_meta(conn, task_id, key, fetcher=get_task, entity_name="task")


def set_task_meta(
    conn: sqlite3.Connection,
    task_id: int,
    key: str,
    value: str,
    *,
    source: str = "cli",
) -> Task:
    return _set_entity_meta(
        conn,
        task_id,
        key,
        value,
        entity_type=EntityType.TASK,
        setter=repo.set_task_metadata_key,
        fetcher=get_task,
        source=source,
    )


def remove_task_meta(
    conn: sqlite3.Connection,
    task_id: int,
    key: str,
    *,
    source: str = "cli",
) -> str:
    return _remove_entity_meta(
        conn,
        task_id,
        key,
        entity_type=EntityType.TASK,
        remover=repo.remove_task_metadata_key,
        fetcher=get_task,
        entity_name="task",
        source=source,
    )


def replace_task_metadata(
    conn: sqlite3.Connection,
    task_id: int,
    new_metadata: dict[str, str],
    *,
    source: str,
) -> Task:
    """Atomically replace a task's entire metadata blob. Each added, changed,
    or removed key emits a `meta.<key>` journal entry via
    `_replace_entity_metadata`.
    """
    return _replace_entity_metadata(
        conn,
        task_id,
        new_metadata,
        entity_type=EntityType.TASK,
        writer=repo.replace_task_metadata,
        fetcher=get_task,
        source=source,
    )


# ---- Workspace metadata ----


def get_workspace_meta(conn: sqlite3.Connection, workspace_id: int, key: str) -> str:
    return _get_entity_meta(conn, workspace_id, key, fetcher=get_workspace, entity_name="workspace")


def set_workspace_meta(
    conn: sqlite3.Connection,
    workspace_id: int,
    key: str,
    value: str,
    *,
    source: str = "cli",
) -> Workspace:
    return _set_entity_meta(
        conn,
        workspace_id,
        key,
        value,
        entity_type=EntityType.WORKSPACE,
        setter=repo.set_workspace_metadata_key,
        fetcher=get_workspace,
        source=source,
    )


def remove_workspace_meta(
    conn: sqlite3.Connection,
    workspace_id: int,
    key: str,
    *,
    source: str = "cli",
) -> str:
    return _remove_entity_meta(
        conn,
        workspace_id,
        key,
        entity_type=EntityType.WORKSPACE,
        remover=repo.remove_workspace_metadata_key,
        fetcher=get_workspace,
        entity_name="workspace",
        source=source,
    )


def replace_workspace_metadata(
    conn: sqlite3.Connection,
    workspace_id: int,
    new_metadata: dict[str, str],
    *,
    source: str,
) -> Workspace:
    """Atomically replace a workspace's entire metadata blob. Each added,
    changed, or removed key emits a `meta.<key>` journal entry.
    """
    return _replace_entity_metadata(
        conn,
        workspace_id,
        new_metadata,
        entity_type=EntityType.WORKSPACE,
        writer=repo.replace_workspace_metadata,
        fetcher=get_workspace,
        source=source,
    )


# ---- Group metadata ----


def get_group_meta(conn: sqlite3.Connection, group_id: int, key: str) -> str:
    return _get_entity_meta(conn, group_id, key, fetcher=get_group, entity_name="group")


def set_group_meta(
    conn: sqlite3.Connection,
    group_id: int,
    key: str,
    value: str,
    *,
    source: str = "cli",
) -> Group:
    return _set_entity_meta(
        conn,
        group_id,
        key,
        value,
        entity_type=EntityType.GROUP,
        setter=repo.set_group_metadata_key,
        fetcher=get_group,
        source=source,
    )


def remove_group_meta(
    conn: sqlite3.Connection,
    group_id: int,
    key: str,
    *,
    source: str = "cli",
) -> str:
    return _remove_entity_meta(
        conn,
        group_id,
        key,
        entity_type=EntityType.GROUP,
        remover=repo.remove_group_metadata_key,
        fetcher=get_group,
        entity_name="group",
        source=source,
    )


def replace_group_metadata(
    conn: sqlite3.Connection,
    group_id: int,
    new_metadata: dict[str, str],
    *,
    source: str,
) -> Group:
    """Atomically replace a group's entire metadata blob. Each added,
    changed, or removed key emits a `meta.<key>` journal entry.
    """
    return _replace_entity_metadata(
        conn,
        group_id,
        new_metadata,
        entity_type=EntityType.GROUP,
        writer=repo.replace_group_metadata,
        fetcher=get_group,
        source=source,
    )


# ---- Edge ----

# Default acyclic flag per edge kind. Kinds not listed default to False.
_ACYCLIC_DEFAULTS: dict[str, bool] = {
    "blocks": True,
    "spawns": True,
}


def _default_acyclic(kind: str) -> bool:
    return _ACYCLIC_DEFAULTS.get(kind, False)


def _resolve_edge_node(
    conn: sqlite3.Connection,
    node_type: str,
    node_id: int,
) -> tuple[int, bool]:
    """Return (workspace_id, archived) for a node. Raises LookupError if not found."""
    if node_type == "task":
        task = get_task(conn, node_id)
        if task is None:
            raise LookupError(f"task {node_id} not found")
        return task.workspace_id, task.archived
    elif node_type == "group":
        grp = repo.get_group(conn, node_id)
        if grp is None:
            raise LookupError(f"group {node_id} not found")
        return grp.workspace_id, grp.archived
    elif node_type == "workspace":
        ws = repo.get_workspace(conn, node_id)
        if ws is None:
            raise LookupError(f"workspace {node_id} not found")
        return ws.id, ws.archived
    else:
        raise ValueError(f"unknown node_type {node_type!r}")


def _check_no_cycle(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
) -> None:
    """Raise ValueError if adding the edge (from→to) would create a cycle in
    the acyclic subgraph. Checks both directions: if the source is already
    reachable from the target, adding this edge closes a cycle."""
    reachable_from_to = repo.get_reachable_nodes(conn, to_type, to_id)
    if (from_type, from_id) in reachable_from_to:
        raise ValueError(
            f"adding edge {from_type}:{from_id} → {to_type}:{to_id} would create a cycle"
        )


def add_edge(
    conn: sqlite3.Connection,
    src: tuple[str, int],
    dst: tuple[str, int],
    *,
    kind: str,
    acyclic: bool | None = None,
    source: str = "cli",
) -> str:
    """Create an edge from ``src`` to ``dst``.

    ``src`` and ``dst`` are ``(node_type, node_id)`` tuples. The tuple shape
    is intentional: it prevents callers from silently swapping ``from_id``
    with ``to_id`` (both plain ints) — a real risk with the unified
    polymorphic edge table.

    Both endpoints must exist on the same workspace and not be archived.
    If ``acyclic`` is None the default for the given kind is used.
    Cycle detection runs only when the edge is acyclic.

    Returns the normalized (lowercased, validated) kind — callers that need
    to surface the kind back to the user should prefer the returned value
    over the input so CLI/JSON output matches what actually hit the DB.

    **Revival semantics.** When this call reactivates a previously archived
    edge (same PK — from_type/from_id/to_type/to_id/kind), the existing row's
    metadata is wiped back to ``{}`` and ``acyclic`` is overwritten with the
    new value. The revival journals only ``archived: 1→0`` (plus an
    ``acyclic`` entry if it changed) — it does NOT re-emit ``endpoint`` /
    ``kind`` journal rows, since the edge identity is unchanged. Treat
    archive+revive as "fresh start": don't archive an edge if you want its
    metadata preserved.
    """
    from_type, from_id = src
    to_type, to_id = dst
    kind = _normalize_edge_kind(kind)
    if acyclic is None:
        acyclic = _default_acyclic(kind)
    acyclic_int = 1 if acyclic else 0
    with transaction(conn), _friendly_errors():
        from_ws, from_archived = _resolve_edge_node(conn, from_type, from_id)
        to_ws, to_archived = _resolve_edge_node(conn, to_type, to_id)
        if from_type == to_type and from_id == to_id:
            raise ValueError("an edge cannot point to itself")
        if from_ws != to_ws:
            raise ValueError(
                f"both endpoints must be on the same workspace: "
                f"{from_type} {from_id} is on workspace {from_ws}, "
                f"{to_type} {to_id} is on workspace {to_ws}"
            )
        if from_archived:
            raise ValueError(f"{from_type} {from_id} is archived")
        if to_archived:
            raise ValueError(f"{to_type} {to_id} is archived")
        existing = repo.get_active_edge(conn, from_type, from_id, to_type, to_id, kind)
        if existing is not None:
            raise ValueError(
                f"edge already exists: {from_type}:{from_id} → {to_type}:{to_id} [{kind}]"
            )
        if acyclic:
            _check_no_cycle(conn, from_type, from_id, to_type, to_id)
        archived_row = repo.get_archived_edge(conn, from_type, from_id, to_type, to_id, kind)
        repo.add_edge(conn, from_type, from_id, to_type, to_id, from_ws, kind, acyclic_int)
        if archived_row is not None:
            # Reviving an archived edge — emit unarchive journal entry
            repo.insert_journal_entry(
                conn,
                NewJournalEntry(
                    entity_type=EntityType.EDGE,
                    entity_id=from_id,
                    workspace_id=from_ws,
                    field="archived",
                    old_value="1",
                    new_value="0",
                    source=source,
                ),
            )
            old_acyclic = archived_row[1]
            if old_acyclic != acyclic_int:
                repo.insert_journal_entry(
                    conn,
                    NewJournalEntry(
                        entity_type=EntityType.EDGE,
                        entity_id=from_id,
                        workspace_id=from_ws,
                        field=EdgeField.ACYCLIC,
                        old_value=str(old_acyclic),
                        new_value=str(acyclic_int),
                        source=source,
                    ),
                )
        else:
            _record_edge_change(
                conn,
                from_type,
                from_id,
                to_type,
                to_id,
                from_ws,
                added=True,
                kind=kind,
                acyclic=acyclic_int,
                source=source,
            )
    return kind


def archive_edge(
    conn: sqlite3.Connection,
    src: tuple[str, int],
    dst: tuple[str, int],
    *,
    kind: str,
    source: str = "cli",
) -> str:
    """Archive an active edge identified by ``src`` → ``dst`` + kind.

    ``src`` and ``dst`` are ``(node_type, node_id)`` tuples — see
    :func:`add_edge` for the rationale behind the tuple shape.

    Returns the normalized kind so CLI/JSON output reflects the value that
    actually hit the DB, not the raw user input.
    """
    from_type, from_id = src
    to_type, to_id = dst
    kind = _normalize_edge_kind(kind)
    with transaction(conn), _friendly_errors():
        active = repo.get_active_edge(conn, from_type, from_id, to_type, to_id, kind)
        if active is None:
            archived = repo.get_archived_edge(conn, from_type, from_id, to_type, to_id, kind)
            if archived is not None:
                raise LookupError(
                    f"edge {from_type}:{from_id} → {to_type}:{to_id} [{kind}] is already archived"
                )
            raise LookupError(
                f"no edge found: {from_type}:{from_id} → {to_type}:{to_id} [{kind}]"
            )
        from_ws, _ = _resolve_edge_node(conn, from_type, from_id)
        repo.archive_edge(conn, from_type, from_id, to_type, to_id, kind)
        _record_edge_change(
            conn,
            from_type,
            from_id,
            to_type,
            to_id,
            from_ws,
            added=False,
            kind=kind,
            acyclic=active[1],
            source=source,
        )
    return kind


def list_edges(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    kind: str | None = None,
    from_type: str | None = None,
    from_id: int | None = None,
    to_type: str | None = None,
    to_id: int | None = None,
) -> tuple[EdgeListItem, ...]:
    if kind is not None:
        kind = _normalize_edge_kind(kind)
    return repo.list_edges_by_workspace(
        conn,
        workspace_id,
        kind=kind,
        from_type=from_type,
        from_id=from_id,
        to_type=to_type,
        to_id=to_id,
    )


# ---- Edge metadata ----


def list_edge_metadata(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
    kind: str,
) -> dict[str, str]:
    return repo.get_edge_metadata(conn, from_type, from_id, to_type, to_id, kind)


def get_edge_meta(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
    kind: str,
    key: str,
) -> str:
    normalized = _normalize_meta_key(key)
    meta = repo.get_edge_metadata(conn, from_type, from_id, to_type, to_id, kind)
    if normalized not in meta:
        raise LookupError(
            f"metadata key {key!r} not found on edge "
            f"({from_type}:{from_id} → {to_type}:{to_id} [{kind}])"
        )
    return meta[normalized]


def set_edge_meta(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
    kind: str,
    key: str,
    value: str,
    source: str = "cli",
) -> None:
    normalized = _normalize_meta_key(key)
    if len(value) > _META_VALUE_MAX:
        raise ValueError(f"metadata value must be \u2264 {_META_VALUE_MAX} characters")
    workspace_id = repo.get_edge_workspace_id(conn, from_type, from_id, to_type, to_id, kind)
    with transaction(conn), _friendly_errors():
        old_meta = repo.get_edge_metadata(conn, from_type, from_id, to_type, to_id, kind)
        old_value = old_meta.get(normalized)
        repo.set_edge_metadata_key(conn, from_type, from_id, to_type, to_id, kind, normalized, value)
        if old_value != value:
            repo.insert_journal_entry(
                conn,
                NewJournalEntry(
                    entity_type=EntityType.EDGE,
                    entity_id=from_id,
                    workspace_id=workspace_id,
                    field=f"meta.{normalized}",
                    old_value=old_value,
                    new_value=value,
                    source=source,
                ),
            )


def remove_edge_meta(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
    kind: str,
    key: str,
    source: str = "cli",
) -> str:
    normalized = _normalize_meta_key(key)
    workspace_id = repo.get_edge_workspace_id(conn, from_type, from_id, to_type, to_id, kind)
    with transaction(conn), _friendly_errors():
        old_meta = repo.get_edge_metadata(conn, from_type, from_id, to_type, to_id, kind)
        if normalized not in old_meta:
            raise LookupError(
                f"metadata key {key!r} not found on edge "
                f"({from_type}:{from_id} → {to_type}:{to_id} [{kind}])"
            )
        old_value = old_meta[normalized]
        repo.remove_edge_metadata_key(conn, from_type, from_id, to_type, to_id, kind, normalized)
        repo.insert_journal_entry(
            conn,
            NewJournalEntry(
                entity_type=EntityType.EDGE,
                entity_id=from_id,
                workspace_id=workspace_id,
                field=f"meta.{normalized}",
                old_value=old_value,
                new_value=None,
                source=source,
            ),
        )
        return old_value


def replace_edge_metadata(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
    kind: str,
    new_metadata: dict[str, str],
    source: str = "cli",
) -> None:
    normalized: dict[str, str] = {}
    for raw_key, value in new_metadata.items():
        k = _normalize_meta_key(raw_key)
        if k in normalized:
            raise ValueError(f"duplicate metadata key after normalization: {k!r}")
        if len(value) > _META_VALUE_MAX:
            raise ValueError(f"metadata value for key {k!r} must be \u2264 {_META_VALUE_MAX} characters")
        normalized[k] = value
    workspace_id = repo.get_edge_workspace_id(conn, from_type, from_id, to_type, to_id, kind)
    with transaction(conn), _friendly_errors():
        old_meta = repo.get_edge_metadata(conn, from_type, from_id, to_type, to_id, kind)
        repo.replace_edge_metadata(conn, from_type, from_id, to_type, to_id, kind, json.dumps(normalized))
        for k in set(old_meta) | set(normalized):
            old_val = old_meta.get(k)
            new_val = normalized.get(k)
            if old_val != new_val:
                repo.insert_journal_entry(
                    conn,
                    NewJournalEntry(
                        entity_type=EntityType.EDGE,
                        entity_id=from_id,
                        workspace_id=workspace_id,
                        field=f"meta.{k}",
                        old_value=old_val,
                        new_value=new_val,
                        source=source,
                    ),
                )


# ---- History ----


def list_journal(
    conn: sqlite3.Connection,
    entity_type: EntityType,
    entity_id: int,
) -> tuple[JournalEntry, ...]:
    return repo.list_journal(conn, entity_type, entity_id)


# ---- Group ----


def _would_create_cycle(
    conn: sqlite3.Connection,
    group_id: int,
    new_parent_id: int,
) -> bool:
    subtree_ids = repo.get_subtree_group_ids(conn, group_id)
    return new_parent_id in subtree_ids


def create_group(
    conn: sqlite3.Connection,
    workspace_id: int,
    title: str,
    parent_id: int | None = None,
    position: int = 0,
    description: str | None = None,
) -> Group:
    with transaction(conn), _friendly_errors():
        get_workspace(conn, workspace_id)
        if parent_id is not None:
            parent = repo.get_group(conn, parent_id)
            if parent is None:
                raise LookupError(f"parent group {parent_id} not found")
            if parent.workspace_id != workspace_id:
                raise ValueError(
                    f"parent group belongs to workspace {parent.workspace_id}, not {workspace_id}"
                )
            if parent.archived:
                raise ValueError(f"parent group {parent_id} is archived")
        return repo.insert_group(
            conn,
            NewGroup(
                workspace_id=workspace_id,
                title=title,
                description=description,
                parent_id=parent_id,
                position=position,
            ),
        )


def get_group(conn: sqlite3.Connection, group_id: int) -> Group:
    group = repo.get_group(conn, group_id)
    if group is None:
        raise LookupError(f"group {group_id} not found")
    return group


def get_group_by_title(
    conn: sqlite3.Connection,
    workspace_id: int,
    parent_id: int | None,
    title: str,
) -> Group:
    group = repo.get_group_by_title(conn, workspace_id, parent_id, title)
    if group is None:
        raise LookupError(f"group {title!r} not found")
    return group


def resolve_group_by_title(
    conn: sqlite3.Connection,
    workspace_id: int,
    title: str,
    *,
    parent_id: int | None = None,
    parent_known: bool = False,
) -> Group:
    """Resolve a group by title on a workspace.

    When `parent_known` is True, `parent_id` narrows the lookup to groups
    with that exact parent (None = root groups). When `parent_known` is
    False, all groups on the workspace matching the title are considered;
    ambiguity raises LookupError.
    """
    if parent_known:
        return get_group_by_title(conn, workspace_id, parent_id, title)
    candidates = repo.list_groups_by_workspace(conn, workspace_id, title=title)
    if not candidates:
        raise LookupError(f"group {title!r} not found")
    if len(candidates) > 1:
        raise LookupError(
            f"group {title!r} is ambiguous — {len(candidates)} matches. "
            "Use --parent to disambiguate"
        )
    return candidates[0]


def resolve_group(
    conn: sqlite3.Connection,
    workspace_id: int,
    title: str,
    *,
    parent_title: str | None = None,
    parent_root: bool = False,
) -> Group:
    """Resolve a group by title.

    If `parent_root` is True, looks up a root-level group (parent_id IS NULL).
    If `parent_title` is given, resolves that parent first and scopes under it.
    Otherwise searches all groups on the workspace (ambiguity is an error).
    """
    if parent_root:
        return resolve_group_by_title(
            conn, workspace_id, title, parent_id=None, parent_known=True
        )
    if parent_title is not None:
        parent = resolve_group_by_title(conn, workspace_id, parent_title)
        return resolve_group_by_title(
            conn, workspace_id, title, parent_id=parent.id, parent_known=True
        )
    return resolve_group_by_title(conn, workspace_id, title)


def get_group_ancestry(
    conn: sqlite3.Connection,
    group_id: int,
) -> tuple[Group, ...]:
    """Groups from root to this group, inclusive. Raises LookupError if group_id doesn't exist."""
    ancestry = repo.get_group_ancestry(conn, group_id)
    if not ancestry:
        raise LookupError(f"group {group_id} not found")
    return ancestry


def get_group_detail(conn: sqlite3.Connection, group_id: int) -> GroupDetail:
    group = get_group(conn, group_id)
    task_ids = repo.list_task_ids_by_group(conn, group_id)
    tasks = repo.list_tasks_by_ids(conn, task_ids)
    children = repo.list_child_groups(conn, group_id)
    # parent is a separate query; a self-join would require column aliasing to
    # distinguish group vs parent columns, adding complexity for a single extra
    # point lookup that only fires when parent_id is set.
    parent = repo.get_group(conn, group.parent_id) if group.parent_id is not None else None
    # See TaskDetail naming convention: edge_sources = incoming,
    # edge_targets = outgoing.
    edge_sources = tuple(
        EdgeRef(node_type=nt, node_id=nid, node_title=title, kind=k)
        for nt, nid, title, k in repo.list_edge_sources_into_hydrated(conn, "group", group_id)
    )
    edge_targets = tuple(
        EdgeRef(node_type=nt, node_id=nid, node_title=title, kind=k)
        for nt, nid, title, k in repo.list_edge_targets_from_hydrated(conn, "group", group_id)
    )
    return group_to_detail(
        group,
        tasks=tasks,
        children=children,
        parent=parent,
        edge_sources=edge_sources,
        edge_targets=edge_targets,
    )


def list_groups(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    parent_id: int | None = None,
    include_archived: bool = False,
    only_archived: bool = False,
) -> tuple[GroupRef, ...]:
    """List groups on a workspace. When `parent_id` is None, returns root
    groups (parent_id IS NULL). Pass an explicit parent_id to list its
    children.
    """
    groups = repo.list_groups(
        conn,
        workspace_id,
        parent_id=parent_id,
        include_archived=include_archived,
        only_archived=only_archived,
    )
    if not groups:
        return ()
    group_ids = tuple(g.id for g in groups)
    task_ids_map = repo.batch_task_ids_by_group(conn, group_ids)
    child_ids_map = repo.batch_child_ids_by_group(
        conn,
        group_ids,
        include_archived=include_archived,
    )
    return tuple(
        group_to_ref(g, task_ids=task_ids_map.get(g.id, ()), child_ids=child_ids_map.get(g.id, ()))
        for g in groups
    )


def list_all_groups(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    include_archived: bool = False,
) -> tuple[GroupRef, ...]:
    """Return every group on a workspace (hydrated as GroupRef). Order is
    by position/id but the hierarchy is flat — callers that need the tree
    structure should walk `child_ids`.
    """
    groups = repo.list_groups_by_workspace(
        conn, workspace_id, include_archived=include_archived
    )
    if not groups:
        return ()
    group_ids = tuple(g.id for g in groups)
    task_ids_map = repo.batch_task_ids_by_group(conn, group_ids)
    child_ids_map = repo.batch_child_ids_by_group(
        conn,
        group_ids,
        include_archived=include_archived,
    )
    return tuple(
        group_to_ref(g, task_ids=task_ids_map.get(g.id, ()), child_ids=child_ids_map.get(g.id, ()))
        for g in groups
    )


def update_group(
    conn: sqlite3.Connection,
    group_id: int,
    changes: dict[str, Any],
    source: str = "cli",
) -> Group:
    with transaction(conn), _friendly_errors():
        if "parent_id" in changes:
            new_parent = changes["parent_id"]
            if new_parent is not None and _would_create_cycle(conn, group_id, new_parent):
                raise ValueError("reparenting would create a cycle")
        old = repo.get_group(conn, group_id)
        result = repo.update_group(conn, group_id, changes)
        if old is not None:
            _record_entity_changes(
                conn, EntityType.GROUP, group_id, old.workspace_id, old, changes, source
            )
        return result


# ---- Task-group assignment ----


def assign_task_to_group(
    conn: sqlite3.Connection,
    task_id: int,
    group_id: int,
    *,
    source: str,
) -> Task:
    """Assign a group to a task. The group must belong to the same workspace
    as the task; validation inside `_update_task_body` enforces this.
    """
    with transaction(conn), _friendly_errors():
        get_task(conn, task_id)
        get_group(conn, group_id)  # raises LookupError on miss
        changes: dict[str, Any] = {"group_id": group_id}
        return _update_task_body(conn, task_id, changes, source)


def unassign_task_from_group(
    conn: sqlite3.Connection,
    task_id: int,
    *,
    source: str,
) -> Task:
    return update_task(conn, task_id, {"group_id": None}, source=source)


# ---- Task-group queries ----


def list_task_ids_by_group(
    conn: sqlite3.Connection,
    group_id: int,
) -> tuple[int, ...]:
    return repo.list_task_ids_by_group(conn, group_id)


def batch_task_ids_by_group(
    conn: sqlite3.Connection,
    group_ids: tuple[int, ...],
) -> dict[int, tuple[int, ...]]:
    return repo.batch_task_ids_by_group(conn, group_ids)


def list_tasks_by_ids(
    conn: sqlite3.Connection,
    task_ids: tuple[int, ...],
) -> tuple[Task, ...]:
    return repo.list_tasks_by_ids(conn, task_ids)


def list_groups_for_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Group, ...]:
    return repo.list_groups_by_workspace(conn, workspace_id, include_archived=include_archived)


def list_ungrouped_task_ids(
    conn: sqlite3.Connection,
    workspace_id: int,
) -> tuple[int, ...]:
    return repo.list_ungrouped_task_ids(conn, workspace_id)


# ---- Archive (preview + cascade) ----


def preview_archive_task(conn: sqlite3.Connection, task_id: int) -> ArchivePreview:
    task = get_task(conn, task_id)
    return ArchivePreview(
        entity_type="task",
        entity_name=task.title,
        already_archived=task.archived,
        task_count=0,
        group_count=0,
        status_count=0,
    )


def preview_archive_group(conn: sqlite3.Connection, group_id: int) -> ArchivePreview:
    group = get_group(conn, group_id)
    return ArchivePreview(
        entity_type="group",
        entity_name=group.title,
        already_archived=group.archived,
        task_count=repo.count_active_tasks_in_group_subtree(conn, group_id),
        group_count=repo.count_active_descendant_groups(conn, group_id),
        status_count=0,
    )


def preview_archive_workspace(conn: sqlite3.Connection, workspace_id: int) -> ArchivePreview:
    workspace = get_workspace(conn, workspace_id)
    return ArchivePreview(
        entity_type="workspace",
        entity_name=workspace.name,
        already_archived=workspace.archived,
        task_count=repo.count_active_tasks_in_workspace(conn, workspace_id),
        group_count=repo.count_active_groups_in_workspace(conn, workspace_id),
        status_count=repo.count_active_statuses_in_workspace(conn, workspace_id),
    )


def preview_archive_status(conn: sqlite3.Connection, status_id: int) -> ArchivePreview:
    status = get_status(conn, status_id)
    return ArchivePreview(
        entity_type="status",
        entity_name=status.name,
        already_archived=status.archived,
        task_count=repo.count_active_tasks_by_status(conn, status_id),
        group_count=0,
        status_count=0,
    )


def preview_update_task(
    conn: sqlite3.Connection,
    task_id: int,
    changes: dict[str, Any],
) -> EntityUpdatePreview:
    """Compute a diff for `update_task` without writing. Validates the
    merged change set the same way `update_task` does so dry-run surfaces
    validation errors before commit.
    """
    old = get_task(conn, task_id)
    _validate_task_update(conn, old, changes)
    before, after = _diff_fields(old, changes)
    return EntityUpdatePreview(
        entity_type="task",
        entity_id=task_id,
        label=old.title,
        before=before,
        after=after,
    )


def preview_move_task(
    conn: sqlite3.Connection,
    task_id: int,
    status_id: int,
    position: int,
) -> TaskMovePreview:
    """Compute a from/to snapshot for `move_task`. No DB writes."""
    task = get_task(conn, task_id)
    from_status = get_status(conn, task.status_id)
    to_status = get_status(conn, status_id)
    return TaskMovePreview(
        task_id=task_id,
        title=task.title,
        from_status=from_status.name,
        to_status=to_status.name,
        from_position=task.position,
        to_position=position,
    )


def preview_update_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
    changes: dict[str, Any],
) -> EntityUpdatePreview:
    """Compute a diff for `update_workspace` without writing."""
    old = get_workspace(conn, workspace_id)
    before, after = _diff_fields(old, changes)
    return EntityUpdatePreview(
        entity_type="workspace",
        entity_id=workspace_id,
        label=old.name,
        before=before,
        after=after,
    )


def preview_update_group(
    conn: sqlite3.Connection,
    group_id: int,
    changes: dict[str, Any],
) -> EntityUpdatePreview:
    """Compute a diff for `update_group` without writing. For `parent_id`
    changes, the diff renders parent group titles (or None) via a
    resolver rather than exposing raw ids.
    """
    old = get_group(conn, group_id)
    if "parent_id" in changes:
        new_parent_id = changes["parent_id"]
        if new_parent_id is not None and _would_create_cycle(conn, group_id, new_parent_id):
            raise ValueError("reparenting would create a cycle")

    def _resolve_parent(pid: int | None) -> str | None:
        if pid is None:
            return None
        return get_group(conn, pid).title

    before, after = _diff_fields(old, changes, resolvers={"parent_id": _resolve_parent})
    return EntityUpdatePreview(
        entity_type="group",
        entity_id=group_id,
        label=old.title,
        before=before,
        after=after,
    )


def _diff_fields(
    entity: Any,
    changes: dict[str, Any],
    *,
    resolvers: dict[str, Callable[[Any], Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (before, after) dicts containing only fields in `changes`
    whose new value differs from the entity's current value.

    Raises AttributeError if a key in `changes` doesn't exist on the
    entity — surfaces caller typos loudly instead of silently producing
    a bogus None-valued diff entry.

    `resolvers` is an optional per-key mapping of callables applied to
    both the before and after values before inclusion in the result.
    Use for relational fields that store raw ids internally but should
    render as display names in the diff (e.g. parent_id → parent title).
    """
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    resolvers = resolvers or {}
    for key, new_value in changes.items():
        current = getattr(entity, key)
        if current != new_value:
            resolver = resolvers.get(key)
            if resolver is not None:
                before[key] = resolver(current)
                after[key] = resolver(new_value)
            else:
                before[key] = current
                after[key] = new_value
    return before, after


def archive_task(
    conn: sqlite3.Connection,
    task_id: int,
    *,
    source: str,
) -> Task:
    with transaction(conn), _friendly_errors():
        old = get_task(conn, task_id)
        updated = repo.update_task(conn, task_id, {"archived": True})
        _record_entity_changes(
            conn, EntityType.TASK, task_id, old.workspace_id, old, {"archived": True}, source
        )
        return updated


def _record_bulk_archive(
    conn: sqlite3.Connection,
    entity_type: EntityType,
    entity_ids: tuple[int, ...],
    workspace_id: int,
    source: str,
) -> None:
    # Values must match str(bool) used by _record_changes for single-entity archive.
    for eid in entity_ids:
        repo.insert_journal_entry(
            conn,
            NewJournalEntry(
                entity_type=entity_type,
                entity_id=eid,
                workspace_id=workspace_id,
                field="archived",
                old_value="False",
                new_value="True",
                source=source,
            ),
        )


def cascade_archive_group(
    conn: sqlite3.Connection,
    group_id: int,
    *,
    source: str,
) -> Group:
    with transaction(conn), _friendly_errors():
        group = get_group(conn, group_id)
        task_ids = repo.list_active_task_ids_in_group_subtree(conn, group_id)
        descendant_group_ids = repo.list_active_descendant_group_ids(conn, group_id)
        repo.archive_tasks_in_group_subtree(conn, group_id)
        _record_bulk_archive(conn, EntityType.TASK, task_ids, group.workspace_id, source)
        repo.archive_descendant_groups(conn, group_id)
        _record_bulk_archive(
            conn, EntityType.GROUP, descendant_group_ids, group.workspace_id, source
        )
        # parent group itself is journaled via update_group below
        return repo.update_group(conn, group_id, {"archived": True})


def cascade_archive_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    source: str,
) -> Workspace:
    with transaction(conn), _friendly_errors():
        task_ids = repo.list_active_task_ids_in_workspace(conn, workspace_id)
        group_ids = repo.list_active_group_ids_in_workspace(conn, workspace_id)
        status_ids = repo.list_active_status_ids_in_workspace(conn, workspace_id)
        repo.archive_tasks_in_workspace(conn, workspace_id)
        _record_bulk_archive(conn, EntityType.TASK, task_ids, workspace_id, source)
        repo.archive_groups_in_workspace(conn, workspace_id)
        _record_bulk_archive(conn, EntityType.GROUP, group_ids, workspace_id, source)
        repo.archive_statuses_in_workspace(conn, workspace_id)
        _record_bulk_archive(conn, EntityType.STATUS, status_ids, workspace_id, source)
        return repo.update_workspace(conn, workspace_id, {"archived": True})
