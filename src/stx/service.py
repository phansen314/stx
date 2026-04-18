from __future__ import annotations

import dataclasses
import heapq
import json
import re
import sqlite3
from collections import deque
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

from . import repository as repo
from .connection import transaction
from .formatting import parse_task_num
from .hooks import HookEvent, fire_hooks
from .mappers import (
    group_to_detail,
    group_to_ref,
    row_to_edge_detail,
    task_to_detail,
    task_to_list_item,
)
from .models import (
    ConflictError,
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
    BlockedTask,
    EdgeDetail,
    EdgeListItem,
    EdgeRef,
    EntityUpdatePreview,
    GroupDetail,
    GroupRef,
    MoveToWorkspacePreview,
    NextTasksView,
    TaskDetail,
    TaskMovePreview,
    WorkspaceContext,
    WorkspaceListStatus,
    WorkspaceListView,
)

# Sentinel that distinguishes "caller did not pass this field" from "caller
# explicitly set this field to None".  Used by update_task() to support
# partial updates where omitted fields are left unchanged.
_UNSET: Any = object()


# ---- Path-based ref parsing ----


@dataclasses.dataclass(frozen=True)
class ParsedRef:
    """Result of parsing a CLI/TUI entity reference string.

    Three shapes:

    * ``kind == "bare"`` — single bare title, no path delimiters. Caller
      decides whether to interpret as a group or a task (workspace-wide
      ambiguous lookup, today's behavior).
    * ``kind == "group_path"`` — segments contains the full group path,
      anchored at root. ``len(segments) >= 1``.
    * ``kind == "task_path"`` — segments is the group prefix (possibly
      empty for "no group"); ``task_title`` is the leaf task title.
    """

    kind: str  # "bare" | "group_path" | "task_path"
    segments: tuple[str, ...] = ()
    task_title: str | None = None
    raw: str = ""


def parse_ref(raw: str) -> ParsedRef:
    """Parse a ref string into ParsedRef.

    Rules:
      * A leading ``/`` is a no-op anchor that signals "this group path
        starts at the workspace root". It promotes single-segment group
        refs from ``bare`` to ``group_path`` so callers in polymorphic
        contexts (edges) can disambiguate ``/A`` (root group A) from
        ``A`` (bare title — typically a task). Multi-segment paths are
        already absolute, so the leading slash is cosmetic there.
      * Last ``:`` (if any) splits group prefix from task title.
        ``:foo`` → root task ``foo``. ``A/B:foo`` → task ``foo`` in
        group ``A/B``. A leading ``/`` on the prefix (``/A:foo``) is
        accepted and cosmetic.
      * Otherwise, ``/`` splits the string into group path segments.
      * No delimiters → bare title (caller decides type).

    Raises ValueError on empty input or empty segment.
    """
    if not raw:
        raise ValueError("empty ref")
    if ":" in raw:
        prefix, _, leaf = raw.rpartition(":")
        if not leaf:
            raise ValueError(f"empty task title in ref {raw!r}")
        if prefix.startswith("/"):
            prefix = prefix[1:]
            if not prefix:
                # `/:foo` — leading slash with no group segments is
                # contradictory (root has no name). Reject.
                raise ValueError(f"empty group path in ref {raw!r}")
        segments = tuple(prefix.split("/")) if prefix else ()
        for seg in segments:
            if not seg:
                raise ValueError(f"empty path segment in ref {raw!r}")
        return ParsedRef(kind="task_path", segments=segments, task_title=leaf, raw=raw)
    if raw.startswith("/"):
        body = raw[1:]
        if not body:
            raise ValueError(f"empty group path in ref {raw!r}")
        segments = tuple(body.split("/"))
        for seg in segments:
            if not seg:
                raise ValueError(f"empty path segment in ref {raw!r}")
        return ParsedRef(kind="group_path", segments=segments, raw=raw)
    if "/" in raw:
        segments = tuple(raw.split("/"))
        for seg in segments:
            if not seg:
                raise ValueError(f"empty path segment in ref {raw!r}")
        return ParsedRef(kind="group_path", segments=segments, raw=raw)
    return ParsedRef(kind="bare", segments=(raw,), raw=raw)


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


_FORBIDDEN_TITLE_CHARS = ("/", ":")


def _validate_title(title: str | None, *, kind: str) -> None:
    """Reject titles containing path-syntax delimiters.

    `/` is the group-segment delimiter and `:` is the group→task delimiter
    in path refs (e.g. ``A/B:my-task``). Allowing them in titles would make
    refs ambiguous. Enforced at the service boundary so both CLI and TUI
    write paths see the same error before any DB write.
    """
    if title is None:
        return
    for ch in _FORBIDDEN_TITLE_CHARS:
        if ch in title:
            raise ValueError(
                f"{kind} title cannot contain {ch!r} (reserved for path syntax): {title!r}"
            )


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


def _workspace_name(conn: sqlite3.Connection, workspace_id: int) -> str | None:
    ws = repo.get_workspace(conn, workspace_id)
    return ws.name if ws is not None else None


# Map EntityType → hook payload entity_type string ("task", "group", ...).
# Kept separate from EntityType itself so the journal enum and the hook
# payload vocabulary can evolve independently.
_HOOK_ENTITY_TYPE: dict[EntityType, str] = {
    EntityType.TASK: "task",
    EntityType.GROUP: "group",
    EntityType.WORKSPACE: "workspace",
    EntityType.STATUS: "status",
    EntityType.EDGE: "edge",
}

# Per-entity metadata event pairs used by generic meta helpers.
_META_SET_EVENT: dict[EntityType, HookEvent] = {
    EntityType.TASK: HookEvent.TASK_META_SET,
    EntityType.GROUP: HookEvent.GROUP_META_SET,
    EntityType.WORKSPACE: HookEvent.WORKSPACE_META_SET,
    EntityType.EDGE: HookEvent.EDGE_META_SET,
}
_META_REMOVED_EVENT: dict[EntityType, HookEvent] = {
    EntityType.TASK: HookEvent.TASK_META_REMOVED,
    EntityType.GROUP: HookEvent.GROUP_META_REMOVED,
    EntityType.WORKSPACE: HookEvent.WORKSPACE_META_REMOVED,
    EntityType.EDGE: HookEvent.EDGE_META_REMOVED,
}


def _build_change_dict(old: Any, new_fields: dict[str, Any]) -> dict[str, Any]:
    """Return {field: {"old": old_val, "new": new_val}} for fields whose value differs."""
    result: dict[str, Any] = {}
    for field, new_val in new_fields.items():
        old_val = getattr(old, field, None)
        if old_val != new_val:
            result[field] = {"old": old_val, "new": new_val}
    return result


def _determine_task_events(changes: dict[str, Any]) -> list[HookEvent]:
    """Return the list of HookEvents implied by a change dict ({field: {"old","new"}})."""
    events: list[HookEvent] = []
    specific: set[str] = set()
    if "status_id" in changes:
        events.append(HookEvent.TASK_MOVED)
        specific.add("status_id")
    if "done" in changes:
        new_done = changes["done"]["new"]
        events.append(HookEvent.TASK_DONE if new_done else HookEvent.TASK_UNDONE)
        specific.add("done")
    if "group_id" in changes:
        new_group = changes["group_id"]["new"]
        events.append(HookEvent.TASK_ASSIGNED if new_group is not None else HookEvent.TASK_UNASSIGNED)
        specific.add("group_id")
    if any(k not in specific for k in changes):
        events.append(HookEvent.TASK_UPDATED)
    return events


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
    proposed = {"name": name}
    with transaction(conn), _friendly_errors():
        result = repo.insert_workspace(conn, NewWorkspace(name=name))
    fire_hooks(
        HookEvent.WORKSPACE_CREATED,
        workspace_id=result.id, workspace_name=result.name,
        entity_type="workspace", entity_id=result.id, entity=result,
        proposed=proposed,
    )
    return result


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
    if not changes:
        return get_workspace(conn, workspace_id)
    old = get_workspace(conn, workspace_id)
    pre_changes = _build_change_dict(old, changes)
    if not pre_changes:
        return old
    with transaction(conn), _friendly_errors():
        result = repo.update_workspace(conn, workspace_id, changes)
        _record_entity_changes(
            conn, EntityType.WORKSPACE, workspace_id, workspace_id, old, changes, source
        )
    post_raw = {k: getattr(result, k) for k in changes}
    post_changes = _build_change_dict(old, post_raw)
    fire_hooks(
        HookEvent.WORKSPACE_UPDATED,
        workspace_id=old.id, workspace_name=result.name,
        entity_type="workspace", entity_id=workspace_id, entity=result,
        changes=post_changes,
    )
    return result


# ---- Status ----


def create_status(
    conn: sqlite3.Connection,
    workspace_id: int,
    name: str,
) -> Status:
    ws_name = _workspace_name(conn, workspace_id)
    proposed = {"workspace_id": workspace_id, "name": name}
    with transaction(conn), _friendly_errors():
        result = repo.insert_status(conn, NewStatus(workspace_id=workspace_id, name=name))
    fire_hooks(
        HookEvent.STATUS_CREATED,
        workspace_id=workspace_id, workspace_name=ws_name,
        entity_type="status", entity_id=result.id, entity=result,
        proposed=proposed,
    )
    return result


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
    if not changes:
        return get_status(conn, status_id)
    old = get_status(conn, status_id)
    pre_changes = _build_change_dict(old, changes)
    if not pre_changes:
        return old
    ws_name = _workspace_name(conn, old.workspace_id)
    with transaction(conn), _friendly_errors():
        if changes.get("archived") is True:
            active_tasks = repo.list_tasks_by_status(conn, status_id)
            if active_tasks:
                raise ValueError(
                    f"status has {len(active_tasks)} active task(s); move or archive them first"
                )
        result = repo.update_status(conn, status_id, changes)
        _record_entity_changes(
            conn, EntityType.STATUS, status_id, old.workspace_id, old, changes, source
        )
    post_raw = {k: getattr(result, k) for k in changes}
    post_changes = _build_change_dict(old, post_raw)
    fire_hooks(
        HookEvent.STATUS_UPDATED,
        workspace_id=old.workspace_id, workspace_name=ws_name,
        entity_type="status", entity_id=status_id, entity=result,
        changes=post_changes,
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
    pre = get_status(conn, status_id)
    ws_name = _workspace_name(conn, pre.workspace_id)
    archive_changes = {"archived": {"old": pre.archived, "new": True}}
    with transaction(conn), _friendly_errors():
        old = repo.get_status(conn, status_id)
        active_tasks = repo.list_tasks_by_status(conn, status_id)
        if reassign_to_status_id is not None and active_tasks:
            hook_extras: dict = {
                "reassigned_task_ids": [t.id for t in active_tasks],
                "reassigned_to": reassign_to_status_id,
            }
        elif force and active_tasks:
            hook_extras = {"archived_task_ids": [t.id for t in active_tasks]}
        else:
            hook_extras = {}
        if active_tasks:
            if reassign_to_status_id is not None:
                target = repo.get_status(conn, reassign_to_status_id)
                if target is None:
                    raise LookupError(f"status {reassign_to_status_id} not found")
                if old is not None and target.workspace_id != old.workspace_id:
                    raise ValueError(
                        f"reassign target status {reassign_to_status_id} "
                        f"belongs to a different workspace"
                    )
                if target.archived:
                    raise ValueError(
                        f"reassign target status {reassign_to_status_id} is archived"
                    )
                repo.reassign_tasks_by_status(conn, status_id, reassign_to_status_id)
                for task in active_tasks:
                    _record_entity_changes(
                        conn,
                        EntityType.TASK,
                        task.id,
                        task.workspace_id,
                        task,
                        {"status_id": reassign_to_status_id},
                        source,
                    )
                if target.is_terminal:
                    conn.execute(
                        "UPDATE tasks SET done = 1, version = version + 1 "
                        "WHERE status_id = :sid AND archived = 0 AND done = 0",
                        {"sid": reassign_to_status_id},
                    )
                    for task in active_tasks:
                        if not task.done:
                            repo.insert_journal_entry(
                                conn,
                                NewJournalEntry(
                                    entity_type=EntityType.TASK,
                                    entity_id=task.id,
                                    workspace_id=task.workspace_id,
                                    field="done",
                                    old_value=str(False),
                                    new_value=str(True),
                                    source="auto",
                                ),
                            )
            elif force:
                repo.archive_tasks_by_status(conn, status_id)
                for task in active_tasks:
                    _record_entity_changes(
                        conn,
                        EntityType.TASK,
                        task.id,
                        task.workspace_id,
                        task,
                        {"archived": True},
                        source,
                    )
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
    fire_hooks(
        HookEvent.STATUS_ARCHIVED,
        workspace_id=pre.workspace_id, workspace_name=ws_name,
        entity_type="status", entity_id=status_id, entity=result,
        changes=archive_changes,
        **hook_extras,
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
    start_date: int | None = None,
    finish_date: int | None = None,
    group_id: int | None = None,
) -> Task:
    _validate_title(title, kind="task")
    fields: dict[str, Any] = {
        "priority": priority,
    }
    if start_date is not None:
        fields["start_date"] = start_date
    if finish_date is not None:
        fields["finish_date"] = finish_date
    if group_id is not None:
        fields["group_id"] = group_id
    _validate_task_fields(fields, workspace_id=workspace_id, conn=conn)
    proposed = {
        "workspace_id": workspace_id,
        "title": title,
        "status_id": status_id,
        "description": description,
        "priority": priority,
        "due_date": due_date,
        "start_date": start_date,
        "finish_date": finish_date,
        "group_id": group_id,
    }
    ws_name = _workspace_name(conn, workspace_id)
    with transaction(conn), _friendly_errors():
        # Mirror the status-driven done auto-set from _update_task_body: a task
        # created directly into a terminal status starts as done=True so it
        # doesn't linger on the `stx next` frontier.
        status = repo.get_status(conn, status_id)
        initial_done = bool(status.is_terminal) if status is not None else False
        task = repo.insert_task(
            conn,
            NewTask(
                workspace_id=workspace_id,
                title=title,
                status_id=status_id,
                description=description,
                priority=priority,
                due_date=due_date,
                start_date=start_date,
                finish_date=finish_date,
                group_id=group_id,
                done=initial_done,
            ),
        )
    fire_hooks(
        HookEvent.TASK_CREATED,
        workspace_id=workspace_id, workspace_name=ws_name,
        entity_type="task", entity_id=task.id, entity=task,
        proposed=proposed,
    )
    if task.done:
        fire_hooks(
            HookEvent.TASK_DONE,
            workspace_id=workspace_id, workspace_name=ws_name,
            entity_type="task", entity_id=task.id, entity=task,
            changes={"done": {"old": False, "new": True}},
        )
    return task


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

    Resolution order:
      1. Numeric forms (``1``, ``task-0001``, ``#1``).
      2. Path forms (``A/B:leaf`` or ``:root-leaf``) via parse_ref.
      3. Bare title — workspace-wide title lookup.

    A task whose title literally matches ``task-NNNN`` would be resolved
    as an ID, not a title — avoid such titles. Group-only path refs
    (``A/B/C``) are rejected since the caller asked for a task.
    """
    try:
        return parse_task_num(raw)
    except ValueError:
        pass
    parsed = parse_ref(raw)
    if parsed.kind == "group_path":
        raise ValueError(f"expected task ref, got group path: {raw!r}")
    if parsed.kind == "task_path":
        return resolve_task_path(
            conn, workspace_id, parsed.segments, parsed.task_title or ""
        ).id
    return get_task_by_title(conn, workspace_id, parsed.segments[0]).id


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
    *,
    expected_version: int | None = None,
) -> Task:
    if not changes:
        return get_task(conn, task_id)
    old = get_task(conn, task_id)
    ws_name = _workspace_name(conn, old.workspace_id)
    pre_changes = _build_change_dict(old, changes)
    if not pre_changes:
        return old
    with transaction(conn), _friendly_errors():
        result = _update_task_body(conn, task_id, changes, source,
                                   expected_version=expected_version)
    post_raw = {k: getattr(result, k) for k in changes}
    if result.done != old.done:  # include auto-done from terminal status
        post_raw["done"] = result.done
    post_changes = _build_change_dict(old, post_raw)
    post_events = _determine_task_events(post_changes)
    for event in post_events:
        fire_hooks(
            event,
            workspace_id=old.workspace_id, workspace_name=ws_name,
            entity_type="task", entity_id=task_id, entity=result,
            changes=post_changes,
        )
    return result


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
    if "title" in changes:
        _validate_title(changes["title"], kind="task")
    _validate_task_fields(merged, workspace_id=old.workspace_id, conn=conn)


def _update_task_body(
    conn: sqlite3.Connection,
    task_id: int,
    changes: dict[str, Any],
    source: str,
    *,
    expected_version: int | None = None,
) -> Task:
    """Inner body of update_task. Assumes the caller holds a transaction.

    Split out so service functions that already hold a transaction (e.g. the
    `assign_task_to_group` wrapper) can call into update_task's logic without
    triggering the transaction manager's anti-nesting guard.

    `expected_version` — when provided, the first DB write uses CAS
    (``WHERE version = expected_version``). Subsequent writes within the same
    body (auto-done flip) do NOT use CAS; the first write already bumped the
    version, and those are unconditional follow-ups in the same transaction.
    """
    old = get_task(conn, task_id)
    _validate_task_update(conn, old, changes)
    if not changes:
        return old
    updated = repo.update_task(conn, task_id, changes,
                               expected_version=expected_version)
    _record_entity_changes(
        conn, EntityType.TASK, task_id, old.workspace_id, old, changes, source
    )
    # Status-driven done auto-set: moving a task INTO a terminal status
    # sets done=True. Moving OUT of a terminal status does NOT clear done —
    # done is sticky and can only be cleared explicitly via mark_task_undone
    # (which requires --force from the CLI). If the caller already passed
    # `done` explicitly, that wins — no override.
    if "status_id" in changes and "done" not in changes:
        # _validate_task_fields already verified the status exists; get_status
        # cannot return None here.
        new_status = repo.get_status(conn, changes["status_id"])
        if bool(new_status.is_terminal) and not updated.done:  # type: ignore[union-attr]
            updated = repo.update_task(conn, task_id, {"done": True})
            repo.insert_journal_entry(
                conn,
                NewJournalEntry(
                    entity_type=EntityType.TASK,
                    entity_id=task_id,
                    workspace_id=old.workspace_id,
                    field="done",
                    old_value=str(False),
                    new_value=str(True),
                    source="auto",
                ),
            )
    return updated


def move_task(
    conn: sqlite3.Connection,
    task_id: int,
    status_id: int,
    source: str,
) -> Task:
    """Move a task to a new status."""
    return update_task(conn, task_id, {"status_id": status_id}, source)


def mark_task_done(
    conn: sqlite3.Connection,
    task_id: int,
    *,
    source: str,
    expected_version: int | None = None,
) -> Task:
    """Flip a task's `done` flag to True. True no-op (no write) if already done.

    Independent of status. Caller-supplied source is recorded in the journal
    so manual flips ("cli", "tui") can be told apart from status-driven auto
    flips. Triggers parent-group rollup recompute via `_update_task_body`.

    Pass `expected_version` for CAS semantics: raises `ConflictError` if
    another writer has modified the task since it was read.
    """
    task = get_task(conn, task_id)
    if task.done:
        return task
    return update_task(conn, task_id, {"done": True}, source,
                       expected_version=expected_version)


def mark_task_undone(
    conn: sqlite3.Connection,
    task_id: int,
    *,
    source: str,
    expected_version: int | None = None,
) -> Task:
    """Flip a task's `done` flag to False. True no-op (no write) if already not done.

    The CLI gates this behind `--force` (with a warning) since users may flip
    accidentally; the service layer itself does not warn — that is a UI
    concern. Triggers parent-group rollup recompute via `_update_task_body`.

    Pass `expected_version` for CAS semantics.
    """
    task = get_task(conn, task_id)
    if not task.done:
        return task
    return update_task(conn, task_id, {"done": False}, source,
                       expected_version=expected_version)


# ---- Next-task computation (topological sort of `blocks` DAG) ----


def _expand_endpoint_to_tasks(
    conn: sqlite3.Connection,
    node_type: str,
    node_id: int,
    cache: dict[tuple[str, int], frozenset[int]],
) -> frozenset[int]:
    """Resolve a polymorphic edge endpoint to the set of not-done task ids it covers.

    - ``task`` → just that task id (caller intersects with not_done_ids).
    - ``group`` → every non-archived, not-done task recursively under the
      group's subtree. Only not-done tasks are returned so the caller's
      blocker map is already filtered: done tasks in a group contribute no
      active blockers and are excluded at query time rather than post-hoc.
    - ``workspace`` / ``status`` → empty: annotation nodes don't participate
      in `stx next` computation.

    Memoized via ``cache`` so each endpoint is only expanded once per
    ``compute_next_tasks`` call.
    """
    key = (node_type, node_id)
    cached = cache.get(key)
    if cached is not None:
        return cached
    if node_type == "task":
        result: frozenset[int] = frozenset({node_id})
    elif node_type == "group":
        subtree = repo.get_subtree_group_ids(conn, node_id)
        if not subtree:
            result = frozenset()
        else:
            id_map = repo.batch_task_ids_by_group(conn, subtree, include_done=False)
            collected: set[int] = set()
            for tids in id_map.values():
                collected.update(tids)
            result = frozenset(collected)
    else:
        result = frozenset()
    cache[key] = result
    return result


def compute_next_tasks(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    rank: bool = False,
    include_blocked: bool = False,
    edge_kinds: frozenset[str] | None = None,
) -> NextTasksView:
    """Compute the next actionable tasks via topological sort of an acyclic
    edge DAG. Default edge kind is ``blocks``; pass ``edge_kinds`` to use a
    different set (e.g. ``frozenset({"spawns"})`` or multiple kinds).

    Default (frontier) mode: `ready` lists every non-done, non-archived task
    whose blocking predecessors (recursively expanded across group endpoints)
    are all done. `blocked` lists the remaining not-done tasks with the task
    ids of their not-yet-done blockers.

    `include_blocked=True`: `ready` is the full topological order of all
    not-done tasks (Kahn's algorithm), starting with the frontier and
    extending through their dependents. `blocked` is empty.

    `rank=True`: in frontier mode, sorts `ready` by (priority desc, due_date
    asc, id asc). In include-blocked mode, the topo sort uses the same key
    as a tiebreaker so higher-priority items come out first within each
    in-degree-zero wave.
    """
    # Load only not-done, non-archived tasks. Done tasks are not candidates
    # for the frontier and contribute no active blocking edges, so there is
    # no reason to load them. This makes the computation scale with the
    # number of remaining tasks rather than the total task history.
    tasks = repo.list_tasks(conn, workspace_id, include_archived=False, include_done=False)
    not_done_ids = frozenset(t.id for t in tasks)
    task_by_id: dict[int, Task] = {t.id: t for t in tasks}

    edges = repo.list_workspace_dag_edges(
        conn, workspace_id, edge_kinds if edge_kinds is not None else frozenset({"blocks"})
    )
    cache: dict[tuple[str, int], frozenset[int]] = {}
    blockers: dict[int, set[int]] = {tid: set() for tid in not_done_ids}
    # _expand_endpoint_to_tasks returns only not-done, non-archived task IDs.
    # Intersect with not_done_ids to handle the single-task case (task endpoints
    # are returned as-is; the intersection drops them if they are done).
    for from_t, from_id, to_t, to_id in edges:
        srcs = _expand_endpoint_to_tasks(conn, from_t, from_id, cache) & not_done_ids
        dsts = _expand_endpoint_to_tasks(conn, to_t, to_id, cache) & not_done_ids
        for d in dsts:
            for s in srcs:
                if s == d:
                    continue
                blockers[d].add(s)

    def rank_key(task: Task) -> tuple[int, int, int]:
        # Higher priority first; missing due_date sorts last (effectively +inf);
        # id is the final tiebreaker for determinism.
        return (
            -task.priority,
            task.due_date if task.due_date is not None else (1 << 62),
            task.id,
        )

    if include_blocked:
        # Kahn's algorithm over the not-done task universe. All entries in
        # blockers[tid] are already not-done (filtered at expansion time),
        # so every blocker counts toward in-degree unconditionally.
        in_degree: dict[int, int] = {tid: 0 for tid in not_done_ids}
        forward: dict[int, list[int]] = {tid: [] for tid in not_done_ids}
        for tid in not_done_ids:
            for src in blockers[tid]:
                in_degree[tid] += 1
                forward[src].append(tid)
        if rank:
            heap: list[tuple[tuple[int, int, int], int]] = []
            for tid, deg in in_degree.items():
                if deg == 0:
                    heapq.heappush(heap, (rank_key(task_by_id[tid]), tid))
            ordered: list[int] = []
            while heap:
                _, tid = heapq.heappop(heap)
                ordered.append(tid)
                for nxt in forward[tid]:
                    in_degree[nxt] -= 1
                    if in_degree[nxt] == 0:
                        heapq.heappush(heap, (rank_key(task_by_id[nxt]), nxt))
        else:
            queue = deque(sorted(tid for tid, d in in_degree.items() if d == 0))
            ordered = []
            while queue:
                tid = queue.popleft()
                ordered.append(tid)
                for nxt in forward[tid]:
                    in_degree[nxt] -= 1
                    if in_degree[nxt] == 0:
                        queue.append(nxt)
        # Any task missing from `ordered` would mean a residual cycle in
        # supposedly-acyclic blocks edges — surface explicitly rather than
        # silently dropping.
        if len(ordered) != len(not_done_ids):
            missing = sorted(set(not_done_ids) - set(ordered))
            raise RuntimeError(
                f"compute_next_tasks: cycle detected among blocks edges, "
                f"unresolved tasks: {missing}"
            )
        ready = tuple(task_to_list_item(task_by_id[tid]) for tid in ordered)
        return NextTasksView(workspace_id=workspace_id, ready=ready, blocked=())

    # All blocker sets contain only not-done tasks (filtered at expansion time),
    # so no further subtraction is needed for the frontier or blocked list.
    frontier = [t for t in tasks if not blockers[t.id]]
    if rank:
        frontier.sort(key=rank_key)
    else:
        frontier.sort(key=lambda t: t.id)
    ready = tuple(task_to_list_item(t) for t in frontier)
    blocked_list: list[BlockedTask] = []
    for t in tasks:
        active = tuple(sorted(blockers[t.id]))
        if not active:
            continue
        blocked_list.append(BlockedTask(task=task_to_list_item(t), blocked_by=active))
    blocked_list.sort(key=lambda b: b.task.id)
    return NextTasksView(
        workspace_id=workspace_id,
        ready=ready,
        blocked=tuple(blocked_list),
    )


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
    old = get_task(conn, task_id)
    src_ws = {"id": old.workspace_id, "name": _workspace_name(conn, old.workspace_id)}
    tgt_ws = {"id": target_workspace_id, "name": _workspace_name(conn, target_workspace_id)}
    transfer_changes = {
        "workspace_id": {"old": old.workspace_id, "new": target_workspace_id},
        "status_id": {"old": old.status_id, "new": target_status_id},
    }
    with transaction(conn), _friendly_errors():
        old_inner, can_move, reason, _ = _validate_move_to_workspace(
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
                title=old_inner.title,
                status_id=target_status_id,
                description=old_inner.description,
                priority=old_inner.priority,
                due_date=old_inner.due_date,
                start_date=old_inner.start_date,
                finish_date=old_inner.finish_date,
            ),
        )

        repo.copy_task_metadata(conn, task_id, new.id)

        repo.update_task(conn, task_id, {"archived": True})
        _record_entity_changes(
            conn, EntityType.TASK, task_id, old_inner.workspace_id, old_inner, {"archived": True}, source
        )
        # Refetch: `new` was built before metadata was attached.
        result = get_task(conn, new.id)
    fire_hooks(
        HookEvent.TASK_TRANSFERRED,
        workspace_id=old.workspace_id, workspace_name=src_ws["name"],
        entity_type="task", entity_id=result.id, entity=result,
        changes=transfer_changes,
        source_workspace=src_ws,
        target_workspace=tgt_ws,
    )
    return result


# ---- Entity metadata ----
#
# Tasks, workspaces, and groups all carry a JSON key/value metadata blob.
# Keys are normalized to lowercase on write/read (matching the codebase's
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
    if entity is None:
        raise LookupError(f"{entity_name} {entity_id} not found")
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
    workspace_id_of: Callable[[Any], int],
    entity_name: str,
    source: str = "cli",
) -> Any:
    """Generic entity-metadata write. Validates the key and value length,
    persists via `setter`, and returns the new entity built from the old
    one — skipping a redundant re-fetch. Fires meta_set hooks around the
    write when the value actually changes.
    """
    normalized = _normalize_meta_key(key)
    if len(value) > _META_VALUE_MAX:
        raise ValueError(f"metadata value must be \u2264 {_META_VALUE_MAX} characters")
    pre_entity = fetcher(conn, entity_id)
    if pre_entity is None:
        raise LookupError(f"{entity_name} {entity_id} not found")
    hook_event = _META_SET_EVENT.get(entity_type)
    hook_type_name = _HOOK_ENTITY_TYPE.get(entity_type)
    pre_ws_id = workspace_id_of(pre_entity)
    pre_ws_name = _workspace_name(conn, pre_ws_id)
    with transaction(conn), _friendly_errors():
        old_entity = fetcher(conn, entity_id)
        if old_entity is None:
            raise LookupError(f"{entity_name} {entity_id} not found")
        old_value = old_entity.metadata.get(normalized)
        setter(conn, entity_id, normalized, value)
        changed = old_value != value
        if changed:
            repo.insert_journal_entry(
                conn,
                NewJournalEntry(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    workspace_id=workspace_id_of(old_entity),
                    field=f"meta.{normalized}",
                    old_value=old_value,
                    new_value=value,
                    source=source,
                ),
            )
        result = dataclasses.replace(
            old_entity,
            metadata={**old_entity.metadata, normalized: value},
        )
    if changed and hook_event is not None:
        fire_hooks(
            hook_event,
            workspace_id=pre_ws_id, workspace_name=pre_ws_name,
            entity_type=hook_type_name, entity_id=entity_id, entity=result,
            meta_key=normalized, meta_value=value,
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
    workspace_id_of: Callable[[Any], int],
    entity_name: str,
    source: str = "cli",
) -> str:
    """Generic entity-metadata removal. Raises ``LookupError`` if the key
    isn't present on the entity. Returns the old value atomically so
    callers don't need a separate read. Fires meta_removed hooks around
    the write.
    """
    normalized = _normalize_meta_key(key)
    pre_entity = fetcher(conn, entity_id)
    if pre_entity is None:
        raise LookupError(f"{entity_name} {entity_id} not found")
    if normalized not in pre_entity.metadata:
        raise LookupError(f"metadata key {key!r} not found on {entity_name} {entity_id}")
    hook_event = _META_REMOVED_EVENT.get(entity_type)
    hook_type_name = _HOOK_ENTITY_TYPE.get(entity_type)
    pre_ws_id = workspace_id_of(pre_entity)
    pre_ws_name = _workspace_name(conn, pre_ws_id)
    with transaction(conn), _friendly_errors():
        old = fetcher(conn, entity_id)
        if old is None:
            raise LookupError(f"{entity_name} {entity_id} not found")
        if normalized not in old.metadata:
            raise LookupError(f"metadata key {key!r} not found on {entity_name} {entity_id}")
        old_value = old.metadata[normalized]
        remover(conn, entity_id, normalized)
        repo.insert_journal_entry(
            conn,
            NewJournalEntry(
                entity_type=entity_type,
                entity_id=entity_id,
                workspace_id=workspace_id_of(old),
                field=f"meta.{normalized}",
                old_value=old_value,
                new_value=None,
                source=source,
            ),
        )
    if hook_event is not None:
        new_entity = fetcher(conn, entity_id)
        fire_hooks(
            hook_event,
            workspace_id=pre_ws_id, workspace_name=pre_ws_name,
            entity_type=hook_type_name, entity_id=entity_id, entity=new_entity,
            meta_key=normalized, meta_value=None,
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
    workspace_id_of: Callable[[Any], int],
    entity_name: str,
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
    pre_entity = fetcher(conn, entity_id)
    if pre_entity is None:
        raise LookupError(f"{entity_name} {entity_id} not found")
    pre_ws_id = workspace_id_of(pre_entity)
    pre_ws_name = _workspace_name(conn, pre_ws_id)
    hook_type_name = _HOOK_ENTITY_TYPE.get(entity_type)
    set_event = _META_SET_EVENT.get(entity_type)
    removed_event = _META_REMOVED_EVENT.get(entity_type)
    # Collect (key, new_value, event) for keys that actually change so we can
    # fire one hook per key before and after the bulk write.
    key_deltas: list[tuple[str, str | None, HookEvent]] = []
    for k in set(pre_entity.metadata) | set(normalized):
        old_v = pre_entity.metadata.get(k)
        new_v = normalized.get(k)
        if old_v != new_v:
            event = set_event if new_v is not None else removed_event
            if event is not None:
                key_deltas.append((k, new_v, event))
    with transaction(conn), _friendly_errors():
        old_entity = fetcher(conn, entity_id)
        if old_entity is None:
            raise LookupError(f"{entity_name} {entity_id} not found")
        old_meta = old_entity.metadata
        writer(conn, entity_id, json.dumps(normalized))
        workspace_id = workspace_id_of(old_entity)
        for k in set(old_meta) | set(normalized):
            old_val = old_meta.get(k)
            new_val = normalized.get(k)
            if old_val != new_val:
                repo.insert_journal_entry(
                    conn,
                    NewJournalEntry(
                        entity_type=entity_type,
                        entity_id=entity_id,
                        workspace_id=workspace_id,
                        field=f"meta.{k}",
                        old_value=old_val,
                        new_value=new_val,
                        source=source,
                    ),
                )
        result = dataclasses.replace(old_entity, metadata=dict(normalized))
    for k, new_v, event in key_deltas:
        fire_hooks(
            event,
            workspace_id=pre_ws_id, workspace_name=pre_ws_name,
            entity_type=hook_type_name, entity_id=entity_id, entity=result,
            meta_key=k, meta_value=new_v,
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
        workspace_id_of=lambda t: t.workspace_id,
        entity_name="task",
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
        workspace_id_of=lambda t: t.workspace_id,
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
    or removed key emits a `meta.<key>` journal entry and a meta_set /
    meta_removed hook via ``_replace_entity_metadata``.
    """
    return _replace_entity_metadata(
        conn,
        task_id,
        new_metadata,
        entity_type=EntityType.TASK,
        writer=repo.replace_task_metadata,
        fetcher=get_task,
        workspace_id_of=lambda t: t.workspace_id,
        entity_name="task",
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
        workspace_id_of=lambda w: w.id,
        entity_name="workspace",
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
        workspace_id_of=lambda w: w.id,
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
        workspace_id_of=lambda w: w.id,
        entity_name="workspace",
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
        workspace_id_of=lambda g: g.workspace_id,
        entity_name="group",
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
        workspace_id_of=lambda g: g.workspace_id,
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
        workspace_id_of=lambda g: g.workspace_id,
        entity_name="group",
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
    elif node_type == "status":
        st = repo.get_status(conn, node_id)
        if st is None:
            raise LookupError(f"status {node_id} not found")
        return st.workspace_id, st.archived
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
    proposed_edge = {
        "from_type": from_type, "from_id": from_id,
        "to_type": to_type, "to_id": to_id,
        "kind": kind, "acyclic": bool(acyclic),
    }
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
    # Re-read post-commit so the entity dict carries the fresh version (stale
    # snapshot would violate the edgeEntity schema under concurrent writers).
    post_entity = _edge_entity_snapshot(
        conn, from_type, from_id, to_type, to_id, kind
    ) or {
        "from_type": from_type, "from_id": from_id,
        "to_type": to_type, "to_id": to_id,
        "workspace_id": from_ws, "kind": kind,
        "acyclic": bool(acyclic_int), "metadata": {},
        "archived": False, "version": 0,
    }
    if archived_row is not None:
        # Revival of an archived edge — not a creation, emit an update.
        revival_changes: dict = {"archived": {"old": True, "new": False}}
        old_acyclic = archived_row[1]
        if old_acyclic != acyclic_int:
            revival_changes["acyclic"] = {"old": bool(old_acyclic), "new": bool(acyclic_int)}
        fire_hooks(
            HookEvent.EDGE_UPDATED,
            workspace_id=from_ws, workspace_name=_workspace_name(conn, from_ws),
            entity_type="edge", entity_id=from_id,
            entity=post_entity,
            changes=revival_changes,
        )
    else:
        fire_hooks(
            HookEvent.EDGE_CREATED,
            workspace_id=from_ws, workspace_name=_workspace_name(conn, from_ws),
            entity_type="edge", entity_id=from_id,
            entity=post_entity,
            proposed=proposed_edge,
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
    pre_row = repo.get_edge_detail_row(conn, from_type, from_id, to_type, to_id, kind)
    if pre_row is not None and not pre_row["archived"]:
        pre_ws = pre_row["workspace_id"]
        pre_entity = {
            "from_type": from_type, "from_id": from_id,
            "to_type": to_type, "to_id": to_id,
            "workspace_id": pre_ws, "kind": kind,
            "acyclic": bool(pre_row["acyclic"]),
            "metadata": repo.get_edge_metadata(conn, from_type, from_id, to_type, to_id, kind),
            "archived": False, "version": int(pre_row["version"]),
        }
    else:
        pre_entity = None
        pre_ws = None
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
    if pre_entity is not None:
        # Re-read post-commit for fresh `version`. `_edge_entity_snapshot` skips
        # archived rows, so read the row directly.
        post_row = repo.get_edge_detail_row(conn, from_type, from_id, to_type, to_id, kind)
        post_version = int(post_row["version"]) if post_row is not None else pre_entity["version"] + 1
        fire_hooks(
            HookEvent.EDGE_ARCHIVED,
            workspace_id=pre_ws, workspace_name=_workspace_name(conn, pre_ws),
            entity_type="edge", entity_id=from_id,
            entity={**pre_entity, "archived": True, "version": post_version},
            changes={"archived": {"old": False, "new": True}},
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


def _edge_entity_snapshot(
    conn: sqlite3.Connection,
    from_type: str, from_id: int,
    to_type: str, to_id: int,
    kind: str,
    *,
    metadata: dict[str, str] | None = None,
) -> dict | None:
    """Build an edge-entity dict shaped like `edgeEntity` in the hook schema,
    for inclusion in hook payloads. Returns None if the edge is not active.
    """
    row = repo.get_edge_detail_row(conn, from_type, from_id, to_type, to_id, kind)
    if row is None or row["archived"]:
        return None
    if metadata is None:
        metadata = repo.get_edge_metadata(conn, from_type, from_id, to_type, to_id, kind)
    return {
        "from_type": from_type, "from_id": from_id,
        "to_type": to_type, "to_id": to_id,
        "workspace_id": row["workspace_id"], "kind": kind,
        "acyclic": bool(row["acyclic"]),
        "metadata": metadata,
        "archived": False, "version": int(row["version"]),
    }


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
    changed: bool = False
    pre_snapshot: dict | None = None
    with transaction(conn), _friendly_errors():
        old_meta = repo.get_edge_metadata(conn, from_type, from_id, to_type, to_id, kind)
        old_value_inside = old_meta.get(normalized)
        changed = old_value_inside != value
        if changed:
            pre_snapshot = _edge_entity_snapshot(
                conn, from_type, from_id, to_type, to_id, kind, metadata=old_meta
            )
        repo.set_edge_metadata_key(conn, from_type, from_id, to_type, to_id, kind, normalized, value)
        if changed:
            repo.insert_journal_entry(
                conn,
                NewJournalEntry(
                    entity_type=EntityType.EDGE,
                    entity_id=from_id,
                    workspace_id=workspace_id,
                    field=f"meta.{normalized}",
                    old_value=old_value_inside,
                    new_value=value,
                    source=source,
                ),
            )
    if changed and pre_snapshot is not None:
        # Re-read post-commit so `version` reflects the write (stale pre_snapshot
        # version would violate the edgeEntity schema invariant).
        post_snapshot = _edge_entity_snapshot(
            conn, from_type, from_id, to_type, to_id, kind
        ) or {
            **pre_snapshot,
            "metadata": {**pre_snapshot["metadata"], normalized: value},
        }
        fire_hooks(
            HookEvent.EDGE_META_SET,
            workspace_id=workspace_id, workspace_name=_workspace_name(conn, workspace_id),
            entity_type="edge", entity_id=from_id, entity=post_snapshot,
            meta_key=normalized, meta_value=value,
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
    pre_meta = repo.get_edge_metadata(conn, from_type, from_id, to_type, to_id, kind)
    if normalized not in pre_meta:
        raise LookupError(
            f"metadata key {key!r} not found on edge "
            f"({from_type}:{from_id} → {to_type}:{to_id} [{kind}])"
        )
    pre_snapshot = _edge_entity_snapshot(
        conn, from_type, from_id, to_type, to_id, kind, metadata=pre_meta
    )
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
    if pre_snapshot is not None:
        post_meta = {k: v for k, v in pre_snapshot["metadata"].items() if k != normalized}
        fire_hooks(
            HookEvent.EDGE_META_REMOVED,
            workspace_id=workspace_id, workspace_name=_workspace_name(conn, workspace_id),
            entity_type="edge", entity_id=from_id,
            entity={**pre_snapshot, "metadata": post_meta},
            meta_key=normalized, meta_value=None,
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
    pre_meta = repo.get_edge_metadata(conn, from_type, from_id, to_type, to_id, kind)
    key_deltas: list[tuple[str, str | None, HookEvent]] = []
    for k in set(pre_meta) | set(normalized):
        old_v = pre_meta.get(k)
        new_v = normalized.get(k)
        if old_v != new_v:
            event = HookEvent.EDGE_META_SET if new_v is not None else HookEvent.EDGE_META_REMOVED
            key_deltas.append((k, new_v, event))
    pre_snapshot = _edge_entity_snapshot(
        conn, from_type, from_id, to_type, to_id, kind, metadata=pre_meta
    ) if key_deltas else None
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
    if pre_snapshot is not None:
        post_snapshot = {**pre_snapshot, "metadata": dict(normalized)}
        for k, new_v, event in key_deltas:
            fire_hooks(
                event,
                workspace_id=workspace_id, workspace_name=_workspace_name(conn, workspace_id),
                entity_type="edge", entity_id=from_id, entity=post_snapshot,
                meta_key=k, meta_value=new_v,
            )


# ---- Edge detail / edit / log ----


def get_edge_detail(
    conn: sqlite3.Connection,
    src: tuple[str, int],
    dst: tuple[str, int],
    *,
    kind: str,
) -> EdgeDetail:
    """Return a fully hydrated single-edge view."""
    from_type, from_id = src
    to_type, to_id = dst
    kind = _normalize_edge_kind(kind)
    row = repo.get_edge_detail_row(conn, from_type, from_id, to_type, to_id, kind)
    if row is None:
        raise LookupError(
            f"edge ({from_type}:{from_id} → {to_type}:{to_id} [{kind}]) not found"
        )
    history = repo.list_journal_for_edge(conn, from_type, from_id, to_type, to_id)
    # Filter history to entries matching this specific kind (same endpoint,
    # different kinds share entity_id + timestamps in pathological cases).
    endpoint = f"{from_type}:{from_id}\u2192{to_type}:{to_id}"
    history = _filter_edge_history(history, endpoint, kind)
    return row_to_edge_detail(row, history=history)


def _filter_edge_history(
    history: tuple[JournalEntry, ...],
    endpoint: str,
    kind: str,
) -> tuple[JournalEntry, ...]:
    """Narrow edge journal entries to those attributable to one (endpoint, kind)
    pair. Endpoint rows are unambiguous by content; sibling rows (kind,
    acyclic, archived, meta.*) are kept when they share a `changed_at` with a
    matched endpoint row AND, for kind rows, the value matches."""
    matched_timestamps: set[int] = set()
    for h in history:
        if h.field == EdgeField.ENDPOINT and endpoint in (h.old_value or "", h.new_value or ""):
            matched_timestamps.add(h.changed_at)
    out: list[JournalEntry] = []
    for h in history:
        if h.changed_at not in matched_timestamps:
            continue
        if h.field == EdgeField.KIND:
            if kind not in (h.old_value or "", h.new_value or ""):
                continue
        out.append(h)
    return tuple(out)


def update_edge(
    conn: sqlite3.Connection,
    src: tuple[str, int],
    dst: tuple[str, int],
    *,
    kind: str,
    changes: dict[str, Any],
    source: str = "cli",
) -> EdgeDetail:
    """Update mutable edge fields (currently only ``acyclic``).

    When flipping acyclic from 0 → 1, re-runs cycle detection over the
    post-update acyclic subgraph. Journals both an ENDPOINT anchor row and
    the ACYCLIC delta so `edge log` can recover the mutation via the
    shared changed_at timestamp (entity_id + endpoint match)."""
    from_type, from_id = src
    to_type, to_id = dst
    kind = _normalize_edge_kind(kind)
    normalized_changes: dict[str, Any] = {}
    if "acyclic" in changes:
        normalized_changes["acyclic"] = 1 if changes["acyclic"] else 0
    if not normalized_changes:
        raise ValueError("no valid fields to update")
    pre_entity: dict | None = None
    pre_ws_id: int | None = None
    pre_changes: dict | None = None
    with transaction(conn), _friendly_errors():
        row = repo.get_edge_detail_row(conn, from_type, from_id, to_type, to_id, kind)
        if row is None or row["archived"]:
            raise LookupError(
                f"edge ({from_type}:{from_id} → {to_type}:{to_id} [{kind}]) not found"
            )
        workspace_id = row["workspace_id"]
        old_acyclic = int(row["acyclic"])
        new_acyclic = normalized_changes["acyclic"]
        if new_acyclic == old_acyclic:
            # No-op — skip write, journal, and hooks.
            history = repo.list_journal_for_edge(conn, from_type, from_id, to_type, to_id)
            endpoint = f"{from_type}:{from_id}\u2192{to_type}:{to_id}"
            return row_to_edge_detail(
                row, history=_filter_edge_history(history, endpoint, kind)
            )
        pre_ws_id = workspace_id
        pre_entity = {
            "from_type": from_type, "from_id": from_id,
            "to_type": to_type, "to_id": to_id,
            "workspace_id": pre_ws_id, "kind": kind,
            "acyclic": bool(old_acyclic),
            "metadata": repo.get_edge_metadata(conn, from_type, from_id, to_type, to_id, kind),
            "archived": False, "version": int(row["version"]),
        }
        pre_changes = {"acyclic": {"old": bool(old_acyclic), "new": bool(new_acyclic)}}
        repo.update_edge(
            conn, from_type, from_id, to_type, to_id, kind, normalized_changes
        )
        if new_acyclic == 1 and old_acyclic == 0:
            # Transition off→on: cycle check runs against the post-write
            # edge set (our edge now participates as acyclic=1). Any cycle
            # raises ValueError, rolling back the transaction.
            _check_no_cycle(conn, from_type, from_id, to_type, to_id)
        endpoint = f"{from_type}:{from_id}\u2192{to_type}:{to_id}"
        repo.insert_journal_entry(
            conn,
            NewJournalEntry(
                entity_type=EntityType.EDGE,
                entity_id=from_id,
                workspace_id=workspace_id,
                field=EdgeField.ENDPOINT,
                old_value=endpoint,
                new_value=endpoint,
                source=source,
            ),
        )
        repo.insert_journal_entry(
            conn,
            NewJournalEntry(
                entity_type=EntityType.EDGE,
                entity_id=from_id,
                workspace_id=workspace_id,
                field=EdgeField.ACYCLIC,
                old_value=str(old_acyclic),
                new_value=str(new_acyclic),
                source=source,
            ),
        )
        # Also emit a kind row at the same timestamp so history filter can
        # disambiguate multi-kind edges sharing an endpoint.
        repo.insert_journal_entry(
            conn,
            NewJournalEntry(
                entity_type=EntityType.EDGE,
                entity_id=from_id,
                workspace_id=workspace_id,
                field=EdgeField.KIND,
                old_value=kind,
                new_value=kind,
                source=source,
            ),
        )
    result = get_edge_detail(conn, src, dst, kind=kind)
    if pre_entity is not None and pre_changes is not None:
        # Re-read post-commit so `version` reflects the write.
        post_entity = _edge_entity_snapshot(
            conn, from_type, from_id, to_type, to_id, kind
        ) or {**pre_entity, "acyclic": bool(new_acyclic)}
        fire_hooks(
            HookEvent.EDGE_UPDATED,
            workspace_id=pre_ws_id, workspace_name=_workspace_name(conn, pre_ws_id),
            entity_type="edge", entity_id=from_id,
            entity=post_entity,
            changes=pre_changes,
        )
    return result


def list_journal_for_edge(
    conn: sqlite3.Connection,
    src: tuple[str, int],
    dst: tuple[str, int],
    *,
    kind: str,
) -> tuple[JournalEntry, ...]:
    """Return journal entries attributable to a single (endpoint, kind) edge."""
    from_type, from_id = src
    to_type, to_id = dst
    kind = _normalize_edge_kind(kind)
    history = repo.list_journal_for_edge(conn, from_type, from_id, to_type, to_id)
    endpoint = f"{from_type}:{from_id}\u2192{to_type}:{to_id}"
    return _filter_edge_history(history, endpoint, kind)


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
    description: str | None = None,
) -> Group:
    _validate_title(title, kind="group")
    ws_name = _workspace_name(conn, workspace_id)
    proposed = {
        "workspace_id": workspace_id,
        "title": title,
        "description": description,
        "parent_id": parent_id,
    }
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
        result = repo.insert_group(
            conn,
            NewGroup(
                workspace_id=workspace_id,
                title=title,
                description=description,
                parent_id=parent_id,
            ),
        )
    fire_hooks(
        HookEvent.GROUP_CREATED,
        workspace_id=workspace_id, workspace_name=ws_name,
        entity_type="group", entity_id=result.id, entity=result,
        proposed=proposed,
    )
    return result


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
            "Use a path ref (e.g. parent/child) to disambiguate"
        )
    return candidates[0]


def resolve_group_path(
    conn: sqlite3.Connection,
    workspace_id: int,
    segments: tuple[str, ...],
) -> Group:
    """Walk a multi-segment group path strictly from root.

    Each segment must exist as a non-archived child of the previous
    (segment[0] anchored at ``parent_id IS NULL``). Missing segments raise
    LookupError naming the failing segment and the path traversed so far.
    """
    if not segments:
        raise ValueError("empty group path")
    parent_id: int | None = None
    walked: list[str] = []
    current: Group | None = None
    for seg in segments:
        current = repo.get_group_by_title(conn, workspace_id, parent_id, seg)
        if current is None:
            so_far = "/".join(walked) or "<root>"
            raise LookupError(
                f"group path segment {seg!r} not found under {so_far}"
            )
        walked.append(seg)
        parent_id = current.id
    assert current is not None
    return current


def resolve_task_path(
    conn: sqlite3.Connection,
    workspace_id: int,
    group_segments: tuple[str, ...],
    task_title: str,
) -> Task:
    """Resolve a task scoped to a (possibly empty) group path.

    Empty ``group_segments`` → search tasks with ``group_id IS NULL``.
    Otherwise walk the group path and scope to that group's id.
    """
    if group_segments:
        group = resolve_group_path(conn, workspace_id, group_segments)
        scope_id: int | None = group.id
        scope_label = "/".join(group_segments)
    else:
        scope_id = None
        scope_label = "<root>"
    task = repo.get_task_by_title_and_group(conn, workspace_id, scope_id, task_title)
    if task is None:
        raise LookupError(f"task {task_title!r} not found in {scope_label}")
    return task


def resolve_group(
    conn: sqlite3.Connection,
    workspace_id: int,
    ref: str,
) -> Group:
    """Resolve a group by ref. Accepts:

    * Bare title (workspace-wide; ambiguity errors).
    * ``A/B/C`` group path (strict walk from root).

    Rejects task-path refs (``A:foo``) — caller asked for a group.
    """
    parsed = parse_ref(ref)
    if parsed.kind == "task_path":
        raise ValueError(f"expected group ref, got task path: {ref!r}")
    if parsed.kind == "bare":
        return resolve_group_by_title(conn, workspace_id, parsed.segments[0])
    return resolve_group_path(conn, workspace_id, parsed.segments)


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
    by id; the hierarchy is flat — callers that need the tree structure
    should walk `child_ids`.
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
    *,
    expected_version: int | None = None,
) -> Group:
    if "title" in changes:
        _validate_title(changes["title"], kind="group")
    if not changes:
        return get_group(conn, group_id)
    pre_old = get_group(conn, group_id)
    pre_changes = _build_change_dict(pre_old, changes)
    ws_name = _workspace_name(conn, pre_old.workspace_id)
    with transaction(conn), _friendly_errors():
        if "parent_id" in changes:
            new_parent = changes["parent_id"]
            if new_parent is not None and _would_create_cycle(conn, group_id, new_parent):
                raise ValueError("reparenting would create a cycle")
        old = repo.get_group(conn, group_id)
        result = repo.update_group(conn, group_id, changes,
                                   expected_version=expected_version)
        if old is not None:
            _record_entity_changes(
                conn, EntityType.GROUP, group_id, old.workspace_id, old, changes, source
            )
    post_raw = {k: getattr(result, k) for k in changes}
    post_changes = _build_change_dict(pre_old, post_raw)
    if post_changes:
        fire_hooks(
            HookEvent.GROUP_UPDATED,
            workspace_id=pre_old.workspace_id, workspace_name=ws_name,
            entity_type="group", entity_id=group_id, entity=result,
            changes=post_changes,
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
    return update_task(conn, task_id, {"group_id": group_id}, source)


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
    old = get_task(conn, task_id)
    ws_name = _workspace_name(conn, old.workspace_id)
    archive_changes = {"archived": {"old": old.archived, "new": True}}
    with transaction(conn), _friendly_errors():
        updated = repo.update_task(conn, task_id, {"archived": True})
        _record_entity_changes(
            conn, EntityType.TASK, task_id, old.workspace_id, old, {"archived": True}, source
        )
    fire_hooks(
        HookEvent.TASK_ARCHIVED,
        workspace_id=old.workspace_id, workspace_name=ws_name,
        entity_type="task", entity_id=task_id, entity=updated,
        changes=archive_changes,
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
    # Design carve-out: bulk-archived tasks here do NOT fire TASK_ARCHIVED hooks.
    # Per-task post-hooks on a large subtree would be expensive and the GROUP_ARCHIVED
    # event is the correct signal for this operation.
    pre = get_group(conn, group_id)
    ws_name = _workspace_name(conn, pre.workspace_id)
    archive_changes = {"archived": {"old": pre.archived, "new": True}}
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
        result = repo.update_group(conn, group_id, {"archived": True})
    group_hook_extras: dict = {}
    if task_ids:
        group_hook_extras["archived_task_ids"] = list(task_ids)
    if descendant_group_ids:
        group_hook_extras["archived_group_ids"] = list(descendant_group_ids)
    fire_hooks(
        HookEvent.GROUP_ARCHIVED,
        workspace_id=pre.workspace_id, workspace_name=ws_name,
        entity_type="group", entity_id=group_id, entity=result,
        changes=archive_changes,
        **group_hook_extras,
    )
    return result


def cascade_archive_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    source: str,
) -> Workspace:
    # Design carve-out: bulk-archived tasks/groups here do NOT fire per-entity hooks.
    # WORKSPACE_ARCHIVED is the correct signal for consumers.
    pre = get_workspace(conn, workspace_id)
    archive_changes = {"archived": {"old": pre.archived, "new": True}}
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
        result = repo.update_workspace(conn, workspace_id, {"archived": True})
    ws_hook_extras: dict = {}
    if task_ids:
        ws_hook_extras["archived_task_ids"] = list(task_ids)
    if group_ids:
        ws_hook_extras["archived_group_ids"] = list(group_ids)
    if status_ids:
        ws_hook_extras["archived_status_ids"] = list(status_ids)
    fire_hooks(
        HookEvent.WORKSPACE_ARCHIVED,
        workspace_id=pre.id, workspace_name=pre.name,
        entity_type="workspace", entity_id=workspace_id, entity=result,
        changes=archive_changes,
        **ws_hook_extras,
    )
    return result
