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
    project_to_detail,
    task_to_detail,
    task_to_list_item,
)
from .models import (
    Group,
    NewGroup,
    NewProject,
    NewStatus,
    NewTag,
    NewTask,
    NewTaskHistory,
    NewWorkspace,
    Project,
    Status,
    Tag,
    Task,
    TaskField,
    TaskFilter,
    TaskHistory,
    Workspace,
)
from .service_models import (
    ArchivePreview,
    EntityUpdatePreview,
    GroupDetail,
    GroupRef,
    MoveToWorkspacePreview,
    ProjectDetail,
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
    "projects.workspace_id, projects.name": "a project with this name already exists on this workspace",
    "statuses.workspace_id, statuses.name": "a status with this name already exists on this workspace",
    "tags.workspace_id, tags.name": "a tag with this name already exists on this workspace",
    "groups.project_id, groups.title": "a group with this title already exists in this project",
    "tasks.workspace_id, tasks.title": "a task with this title already exists on this workspace",
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
        if "task_dependencies" in constraint:
            return ValueError("this dependency already exists")
        if "task_tags" in constraint:
            return ValueError("task already has this tag")
        return ValueError("a unique constraint was violated")
    if "FOREIGN KEY constraint failed" in msg:
        if context:
            return ValueError(context)
        return ValueError("referenced entity does not exist or belongs to a different workspace")
    if "CHECK constraint failed" in msg:
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
        if "project_id" in changes and changes["project_id"] is not None:
            proj = repo.get_project(conn, changes["project_id"])
            if proj is None:
                raise LookupError(f"project {changes['project_id']} not found")
            if proj.workspace_id != workspace_id:
                raise ValueError(
                    f"project {proj.id} belongs to workspace {proj.workspace_id}, not {workspace_id}"
                )
            if proj.archived:
                raise ValueError(f"project {proj.id} is archived")


def _validate_group_project_consistency(
    conn: sqlite3.Connection,
    old: Task,
    changes: dict[str, Any],
) -> None:
    """Enforce the (project_id, group_id) invariant on update.

    After applying `changes` on top of `old`, the task's group (if any) must
    belong to the task's project. This check fires whenever either field is
    in `changes`, so it catches both scenarios:

      1. Assigning/changing a group → must match current or new project.
      2. Changing project out from under an existing group → must clear or
         re-point the group in the same update.

    Intentional side-effect: if a task's *existing* group was archived after
    assignment, any update that also touches `project_id` (even a no-op
    project set) will surface the archived-group error. The task is in an
    inconsistent state and the user must explicitly clear or reassign the
    group before other edits in the same group/project axis. Updates that
    don't touch group_id/project_id are unaffected.
    """
    effective_group_id = changes.get("group_id", old.group_id)
    if effective_group_id is None:
        return
    grp = repo.get_group(conn, effective_group_id)
    if grp is None:
        raise LookupError(f"group {effective_group_id} not found")
    if grp.workspace_id != old.workspace_id:
        raise ValueError(
            f"group {grp.id} belongs to workspace {grp.workspace_id}, not {old.workspace_id}"
        )
    if grp.archived:
        raise ValueError(f"group {grp.id} is archived")
    effective_project_id = changes.get("project_id", old.project_id)
    if effective_project_id is None:
        raise ValueError(f"cannot assign group {grp.id}: task has no project")
    if effective_project_id != grp.project_id:
        raise ValueError(
            f"group {grp.id} belongs to project {grp.project_id}, "
            f"not task project {effective_project_id}"
        )


def _ensure_tag(conn: sqlite3.Connection, workspace_id: int, name: str) -> Tag:
    """Return the active tag on workspace_id matching name, creating it if absent."""
    tag = repo.get_tag_by_name(conn, workspace_id, name)
    if tag is None:
        tag = repo.insert_tag(conn, NewTag(workspace_id=workspace_id, name=name))
    return tag


def _record_changes(
    conn: sqlite3.Connection,
    task_id: int,
    old: Task,
    changes: dict[str, Any],
    source: str,
) -> None:
    for key, new_val in changes.items():
        old_val = getattr(old, key)
        if old_val == new_val:
            continue
        repo.insert_task_history(
            conn,
            NewTaskHistory(
                task_id=task_id,
                workspace_id=old.workspace_id,
                field=TaskField(key),
                old_value=str(old_val) if old_val is not None else None,
                new_value=str(new_val) if new_val is not None else None,
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
) -> Workspace:
    with transaction(conn), _friendly_errors():
        if changes.get("archived") is True:
            active_cols = repo.list_statuses(conn, workspace_id)
            if active_cols:
                raise ValueError(
                    f"workspace has {len(active_cols)} active status(es); "
                    "use 'workspace archive' to cascade"
                )
            active_projs = repo.list_projects(conn, workspace_id)
            if active_projs:
                raise ValueError(
                    f"workspace has {len(active_projs)} active project(s); "
                    "use 'workspace archive' to cascade"
                )
            active_tasks = repo.list_tasks(conn, workspace_id)
            if active_tasks:
                raise ValueError(
                    f"workspace has {len(active_tasks)} active task(s); "
                    "use 'workspace archive' to cascade"
                )
        return repo.update_workspace(conn, workspace_id, changes)


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
) -> Status:
    with transaction(conn), _friendly_errors():
        if changes.get("archived") is True:
            active_tasks = repo.list_tasks_by_status(conn, status_id)
            if active_tasks:
                raise ValueError(
                    f"status has {len(active_tasks)} active task(s); move or archive them first"
                )
        return repo.update_status(conn, status_id, changes)


def archive_status(
    conn: sqlite3.Connection,
    status_id: int,
    *,
    reassign_to_status_id: int | None = None,
    force: bool = False,
) -> Status:
    """Archive a status, optionally handling active tasks via reassign or force-archive."""
    with transaction(conn), _friendly_errors():
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
        return repo.update_status(conn, status_id, {"archived": True})


# ---- Project ----


def create_project(
    conn: sqlite3.Connection,
    workspace_id: int,
    name: str,
    description: str | None = None,
) -> Project:
    with transaction(conn), _friendly_errors():
        return repo.insert_project(
            conn, NewProject(workspace_id=workspace_id, name=name, description=description)
        )


def get_project(conn: sqlite3.Connection, project_id: int) -> Project:
    project = repo.get_project(conn, project_id)
    if project is None:
        raise LookupError(f"project {project_id} not found")
    return project


def get_project_by_name(
    conn: sqlite3.Connection,
    workspace_id: int,
    name: str,
) -> Project:
    project = repo.get_project_by_name(conn, workspace_id, name)
    if project is None:
        raise LookupError(f"project {name!r} not found")
    return project


def get_project_detail(conn: sqlite3.Connection, project_id: int) -> ProjectDetail:
    project = get_project(conn, project_id)
    tasks = repo.list_tasks_by_project(conn, project_id)
    return project_to_detail(project, tasks=tasks)


def list_projects(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    include_archived: bool = False,
    only_archived: bool = False,
) -> tuple[Project, ...]:
    return repo.list_projects(
        conn, workspace_id, include_archived=include_archived, only_archived=only_archived
    )


def _validate_project_update(
    conn: sqlite3.Connection,
    project_id: int,
    changes: dict[str, Any],
) -> None:
    """Shared validation for project updates. Currently enforces the
    archive-cascade block: archiving a project with active tasks or
    groups requires `project archive` instead of `project edit`.
    """
    if changes.get("archived") is True:
        active_tasks = repo.list_tasks_by_project(conn, project_id)
        if active_tasks:
            raise ValueError(
                f"project has {len(active_tasks)} active task(s); use 'project archive' to cascade"
            )
        active_groups = repo.list_groups(conn, project_id)
        if active_groups:
            raise ValueError(
                f"project has {len(active_groups)} active group(s); "
                "use 'project archive' to cascade"
            )


def update_project(
    conn: sqlite3.Connection,
    project_id: int,
    changes: dict[str, Any],
) -> Project:
    with transaction(conn), _friendly_errors():
        _validate_project_update(conn, project_id, changes)
        return repo.update_project(conn, project_id, changes)


# ---- Task ----


def create_task(
    conn: sqlite3.Connection,
    workspace_id: int,
    title: str,
    status_id: int,
    *,
    project_id: int | None = None,
    description: str | None = None,
    priority: int = 1,
    due_date: int | None = None,
    position: int = 0,
    start_date: int | None = None,
    finish_date: int | None = None,
    group_id: int | None = None,
    tags: tuple[str, ...] = (),
) -> Task:
    fields: dict[str, Any] = {
        "priority": priority,
        "position": position,
    }
    if start_date is not None:
        fields["start_date"] = start_date
    if finish_date is not None:
        fields["finish_date"] = finish_date
    _validate_task_fields(fields, workspace_id=workspace_id, conn=conn)
    with transaction(conn), _friendly_errors():
        if group_id is not None:
            group = get_group(conn, group_id)
            if group.archived:
                raise ValueError(f"group {group_id} is archived")
            if project_id is None:
                project_id = group.project_id
            elif project_id != group.project_id:
                raise ValueError(
                    f"project {project_id} does not match group's project {group.project_id}"
                )
        task = repo.insert_task(
            conn,
            NewTask(
                workspace_id=workspace_id,
                title=title,
                status_id=status_id,
                project_id=project_id,
                description=description,
                priority=priority,
                due_date=due_date,
                position=position,
                start_date=start_date,
                finish_date=finish_date,
                group_id=group_id,
            ),
        )
        for tag_name in tags:
            tag = _ensure_tag(conn, workspace_id, tag_name)
            repo.add_tag_to_task(conn, task.id, tag.id)
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
    project = repo.get_project(conn, task.project_id) if task.project_id is not None else None
    group = repo.get_group(conn, task.group_id) if task.group_id is not None else None
    blocked_by = repo.list_blocked_by_tasks(conn, task_id)
    blocks = repo.list_blocks_tasks(conn, task_id)
    history = repo.list_task_history(conn, task_id)
    tags = repo.list_tags_by_task(conn, task_id)
    return task_to_detail(
        task,
        status=status,
        project=project,
        group=group,
        blocked_by=blocked_by,
        blocks=blocks,
        history=history,
        tags=tags,
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
    project_id: int | None = None,
    tag_id: int | None = None,
    group_id: int | None = None,
    priority: int | None = None,
    search: str | None = None,
    include_archived: bool = False,
    only_archived: bool = False,
) -> WorkspaceListView:
    """Denormalized workspace view for list rendering. Groups task list items by
    status (alphabetical by name) with project and tag names pre-resolved,
    so callers don't need to re-query projects/tags for display. When
    include_archived is True, archived statuses are included as well."""
    workspace = get_workspace(conn, workspace_id)
    task_filter = TaskFilter(
        status_id=status_id,
        project_id=project_id,
        priority=priority,
        search=search,
        tag_id=tag_id,
        group_id=group_id,
        include_archived=include_archived,
        only_archived=only_archived,
    )
    tasks = repo.list_tasks_filtered(conn, workspace_id, task_filter=task_filter)
    statuses = repo.list_statuses(
        conn, workspace_id, include_archived=include_archived or only_archived
    )
    projects = repo.list_projects(conn, workspace_id, include_archived=True)
    proj_name_by_id: dict[int, str] = {p.id: p.name for p in projects}
    tags = repo.list_tags(conn, workspace_id, include_archived=True)
    tag_name_by_id: dict[int, str] = {t.id: t.name for t in tags}

    task_ids = tuple(t.id for t in tasks)
    tag_map = repo.batch_tag_ids_by_task(conn, task_ids)

    items_by_status: dict[int, list[Task]] = {s.id: [] for s in statuses}
    for task in tasks:
        bucket = items_by_status.get(task.status_id)
        if bucket is not None:
            bucket.append(task)

    def _to_item(task: Task) -> TaskListItem:
        proj_name = proj_name_by_id.get(task.project_id) if task.project_id is not None else None
        tag_names = tuple(
            tag_name_by_id[tid] for tid in tag_map.get(task.id, ()) if tid in tag_name_by_id
        )
        return task_to_list_item(task, project_name=proj_name, tag_names=tag_names)

    status_list = tuple(
        WorkspaceListStatus(status=s, tasks=tuple(_to_item(t) for t in items_by_status[s.id]))
        for s in statuses
    )
    return WorkspaceListView(workspace=workspace, statuses=status_list)


def get_workspace_context(conn: sqlite3.Connection, workspace_id: int) -> WorkspaceContext:
    """Aggregated workspace state: view + projects + tags + all groups. Active items only."""
    view = get_workspace_list_view(conn, workspace_id)
    projects = list_projects(conn, workspace_id)
    tags = list_tags(conn, workspace_id)
    groups: list[GroupRef] = []
    for proj in projects:
        groups.extend(list_groups(conn, proj.id))
    return WorkspaceContext(view=view, projects=projects, tags=tags, groups=tuple(groups))


def update_task(
    conn: sqlite3.Connection,
    task_id: int,
    changes: dict[str, Any],
    source: str,
    *,
    add_tags: tuple[str, ...] = (),
    remove_tags: tuple[str, ...] = (),
) -> Task:
    if not changes and not add_tags and not remove_tags:
        return get_task(conn, task_id)
    with transaction(conn), _friendly_errors():
        return _update_task_body(
            conn,
            task_id,
            changes,
            source,
            add_tags=add_tags,
            remove_tags=remove_tags,
        )


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
    if "group_id" in changes or "project_id" in changes:
        _validate_group_project_consistency(conn, old, changes)


def _update_task_body(
    conn: sqlite3.Connection,
    task_id: int,
    changes: dict[str, Any],
    source: str,
    *,
    add_tags: tuple[str, ...] = (),
    remove_tags: tuple[str, ...] = (),
) -> Task:
    """Inner body of update_task. Assumes the caller holds a transaction.

    Split out so service functions that already hold a transaction (e.g. the
    `assign_task_to_group` wrapper) can call into update_task's logic without
    triggering the transaction manager's anti-nesting guard.
    """
    old = get_task(conn, task_id)
    _validate_task_update(conn, old, changes)
    if changes:
        updated = repo.update_task(conn, task_id, changes)
        _record_changes(conn, task_id, old, changes, source)
    else:
        updated = old
    for tag_name in add_tags:
        tag = _ensure_tag(conn, old.workspace_id, tag_name)
        repo.add_tag_to_task(conn, task_id, tag.id)
    for tag_name in remove_tags:
        existing_tag = repo.get_tag_by_name(conn, old.workspace_id, tag_name)
        if existing_tag is None:
            raise LookupError(f"tag {tag_name!r} not found")
        existing = repo.list_tag_ids_by_task(conn, task_id)
        if existing_tag.id not in existing:
            raise LookupError(f"task {task_id} is not tagged {tag_name!r}")
        repo.remove_tag_from_task(conn, task_id, existing_tag.id)
    return updated


def move_task(
    conn: sqlite3.Connection,
    task_id: int,
    status_id: int,
    position: int,
    source: str,
    *,
    project_id: Any = _UNSET,
) -> Task:
    """Move a task to (status_id, position). If project_id is provided (including None),
    also reassign the task's project in the same transaction."""
    changes: dict[str, Any] = {"status_id": status_id, "position": position}
    if project_id is not _UNSET:
        changes["project_id"] = project_id
    return update_task(conn, task_id, changes, source)


def _validate_move_to_workspace(
    conn: sqlite3.Connection,
    task_id: int,
    target_workspace_id: int,
    target_status_id: int,
    project_id: int | None,
) -> tuple[Task, bool, str | None, tuple[int, ...]]:
    """Check move-to-workspace preconditions. Non-mutating.
    Returns (task, can_move, blocking_reason, dependency_ids).
    Raises LookupError only if task_id does not exist."""
    task = get_task(conn, task_id)
    dep_ids: tuple[int, ...] = ()
    if task.archived:
        return task, False, f"task {task_id} is archived", dep_ids
    blocked_by = repo.list_blocked_by_ids(conn, task_id)
    blocks = repo.list_blocks_ids(conn, task_id)
    if blocked_by or blocks:
        dep_ids = tuple(sorted({*blocked_by, *blocks}))
        return (
            task,
            False,
            (
                f"task {task_id} has dependencies ({', '.join(str(d) for d in dep_ids)}); "
                "remove them before moving to another workspace"
            ),
            dep_ids,
        )
    target_col = repo.get_status(conn, target_status_id)
    if target_col is None or target_col.workspace_id != target_workspace_id:
        return (
            task,
            False,
            (f"status {target_status_id} does not belong to workspace {target_workspace_id}"),
            dep_ids,
        )
    if target_col.archived:
        return task, False, f"status {target_status_id} is archived", dep_ids
    if project_id is not None:
        proj = repo.get_project(conn, project_id)
        if proj is None or proj.workspace_id != target_workspace_id:
            return (
                task,
                False,
                (f"project {project_id} does not belong to workspace {target_workspace_id}"),
                dep_ids,
            )
        if proj.archived:
            return task, False, f"project {project_id} is archived", dep_ids
    return task, True, None, dep_ids


def preview_move_to_workspace(
    conn: sqlite3.Connection,
    task_id: int,
    target_workspace_id: int,
    target_status_id: int,
    *,
    project_id: int | None = None,
) -> MoveToWorkspacePreview:
    """Dry-run the same validation as move_task_to_workspace. Does not mutate."""
    task, can_move, reason, dep_ids = _validate_move_to_workspace(
        conn,
        task_id,
        target_workspace_id,
        target_status_id,
        project_id,
    )
    return MoveToWorkspacePreview(
        task_id=task.id,
        task_title=task.title,
        source_workspace_id=task.workspace_id,
        target_workspace_id=target_workspace_id,
        target_status_id=target_status_id,
        target_project_id=project_id,
        can_move=can_move,
        blocking_reason=reason,
        dependency_ids=dep_ids,
        is_archived=task.archived,
    )


def move_task_to_workspace(
    conn: sqlite3.Connection,
    task_id: int,
    target_workspace_id: int,
    target_status_id: int,
    *,
    project_id: int | None = None,
    source: str,
) -> Task:
    with transaction(conn), _friendly_errors():
        old, can_move, reason, _ = _validate_move_to_workspace(
            conn,
            task_id,
            target_workspace_id,
            target_status_id,
            project_id,
        )
        if not can_move:
            raise ValueError(reason)

        new = repo.insert_task(
            conn,
            NewTask(
                workspace_id=target_workspace_id,
                title=old.title,
                status_id=target_status_id,
                project_id=project_id,
                description=old.description,
                priority=old.priority,
                due_date=old.due_date,
                position=0,
                start_date=old.start_date,
                finish_date=old.finish_date,
            ),
        )

        # Migrate active tags by name to the target workspace.  Archived tags on
        # the source workspace are intentionally skipped: they cannot be referenced
        # on the destination workspace and recreating them there would resurrect
        # tags the user had already retired.
        for tag in repo.list_tags_by_task(conn, task_id):
            target_tag = repo.get_tag_by_name(conn, target_workspace_id, tag.name)
            if target_tag is None:
                target_tag = repo.insert_tag(
                    conn, NewTag(workspace_id=target_workspace_id, name=tag.name)
                )
            repo.add_tag_to_task(conn, new.id, target_tag.id)

        repo.copy_task_metadata(conn, task_id, new.id)

        repo.update_task(conn, task_id, {"archived": True})
        _record_changes(conn, task_id, old, {"archived": True}, source)
        # Refetch: `new` was built before tags/metadata were attached.
        return get_task(conn, new.id)


# ---- Entity metadata ----
#
# Tasks, workspaces, projects, and groups all carry a JSON key/value metadata
# blob. Keys are normalized to lowercase on write/read (matching the codebase's
# COLLATE NOCASE convention, which can't be applied directly to JSON keys).


_META_KEY_RE = re.compile(r"^[a-z0-9_.-]+$")
_META_VALUE_MAX = 500


def _normalize_meta_key(key: str) -> str:
    """Lowercase and validate a metadata key.

    Keys are stored lowercase to match the codebase's COLLATE NOCASE convention.
    JSON-stored fields cannot use column collation, so we normalize at the
    application layer instead.
    """
    normalized = key.lower()
    if not normalized or len(normalized) > 64:
        raise ValueError("metadata key must be 1-64 characters")
    if not _META_KEY_RE.match(normalized):
        raise ValueError(f"metadata key must match [a-z0-9_.-]+, got {key!r}")
    return normalized


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
    setter: Callable[[sqlite3.Connection, int, str, str], None],
    fetcher: Callable[[sqlite3.Connection, int], Any],
) -> Any:
    """Generic entity-metadata write. Validates the key and value length,
    then persists via `setter` and returns the refreshed entity from `fetcher`.
    """
    normalized = _normalize_meta_key(key)
    if len(value) > _META_VALUE_MAX:
        raise ValueError(f"metadata value must be \u2264 {_META_VALUE_MAX} characters")
    with transaction(conn), _friendly_errors():
        setter(conn, entity_id, normalized, value)
        return fetcher(conn, entity_id)


def _remove_entity_meta(
    conn: sqlite3.Connection,
    entity_id: int,
    key: str,
    *,
    remover: Callable[[sqlite3.Connection, int, str], None],
    fetcher: Callable[[sqlite3.Connection, int], Any],
    entity_name: str,
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
        return old_value


def _replace_entity_metadata(
    conn: sqlite3.Connection,
    entity_id: int,
    new_metadata: dict[str, str],
    *,
    writer: Callable[[sqlite3.Connection, int, str], None],
    fetcher: Callable[[sqlite3.Connection, int], Any],
) -> Any:
    """Generic bulk-replace for an entity's metadata blob.

    Normalizes every key, rejects duplicates after normalization, enforces
    the per-value length cap, then writes the whole dict in one UPDATE and
    returns the refreshed entity. No history is recorded — consistent with
    per-key set/remove helpers which also bypass history.
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
        fetcher(conn, entity_id)  # existence check
        writer(conn, entity_id, json.dumps(normalized))
        return fetcher(conn, entity_id)


# ---- Task metadata ----


def get_task_meta(conn: sqlite3.Connection, task_id: int, key: str) -> str:
    return _get_entity_meta(conn, task_id, key, fetcher=get_task, entity_name="task")


def set_task_meta(conn: sqlite3.Connection, task_id: int, key: str, value: str) -> Task:
    return _set_entity_meta(
        conn,
        task_id,
        key,
        value,
        setter=repo.set_task_metadata_key,
        fetcher=get_task,
    )


def remove_task_meta(conn: sqlite3.Connection, task_id: int, key: str) -> str:
    return _remove_entity_meta(
        conn,
        task_id,
        key,
        remover=repo.remove_task_metadata_key,
        fetcher=get_task,
        entity_name="task",
    )


def replace_task_metadata(
    conn: sqlite3.Connection,
    task_id: int,
    new_metadata: dict[str, str],
    *,
    source: str,
) -> Task:
    """Atomically replace a task's entire metadata blob. `source` is accepted
    for signature parity with `update_task`; metadata writes don't record
    history today (consistent with per-key `set_task_meta` / `remove_task_meta`).
    """
    del source  # not tracked today; see docstring
    return _replace_entity_metadata(
        conn,
        task_id,
        new_metadata,
        writer=repo.replace_task_metadata,
        fetcher=get_task,
    )


# ---- Workspace metadata ----


def get_workspace_meta(conn: sqlite3.Connection, workspace_id: int, key: str) -> str:
    return _get_entity_meta(conn, workspace_id, key, fetcher=get_workspace, entity_name="workspace")


def set_workspace_meta(
    conn: sqlite3.Connection, workspace_id: int, key: str, value: str
) -> Workspace:
    return _set_entity_meta(
        conn,
        workspace_id,
        key,
        value,
        setter=repo.set_workspace_metadata_key,
        fetcher=get_workspace,
    )


def remove_workspace_meta(conn: sqlite3.Connection, workspace_id: int, key: str) -> str:
    return _remove_entity_meta(
        conn,
        workspace_id,
        key,
        remover=repo.remove_workspace_metadata_key,
        fetcher=get_workspace,
        entity_name="workspace",
    )


def replace_workspace_metadata(
    conn: sqlite3.Connection,
    workspace_id: int,
    new_metadata: dict[str, str],
    *,
    source: str,
) -> Workspace:
    """Atomically replace a workspace's entire metadata blob. See
    `replace_task_metadata` for the `source` parameter rationale.
    """
    del source
    return _replace_entity_metadata(
        conn,
        workspace_id,
        new_metadata,
        writer=repo.replace_workspace_metadata,
        fetcher=get_workspace,
    )


# ---- Project metadata ----


def get_project_meta(conn: sqlite3.Connection, project_id: int, key: str) -> str:
    return _get_entity_meta(conn, project_id, key, fetcher=get_project, entity_name="project")


def set_project_meta(conn: sqlite3.Connection, project_id: int, key: str, value: str) -> Project:
    return _set_entity_meta(
        conn,
        project_id,
        key,
        value,
        setter=repo.set_project_metadata_key,
        fetcher=get_project,
    )


def remove_project_meta(conn: sqlite3.Connection, project_id: int, key: str) -> str:
    return _remove_entity_meta(
        conn,
        project_id,
        key,
        remover=repo.remove_project_metadata_key,
        fetcher=get_project,
        entity_name="project",
    )


def replace_project_metadata(
    conn: sqlite3.Connection,
    project_id: int,
    new_metadata: dict[str, str],
    *,
    source: str,
) -> Project:
    """Atomically replace a project's entire metadata blob. See
    `replace_task_metadata` for the `source` parameter rationale.
    """
    del source
    return _replace_entity_metadata(
        conn,
        project_id,
        new_metadata,
        writer=repo.replace_project_metadata,
        fetcher=get_project,
    )


# ---- Group metadata ----


def get_group_meta(conn: sqlite3.Connection, group_id: int, key: str) -> str:
    return _get_entity_meta(conn, group_id, key, fetcher=get_group, entity_name="group")


def set_group_meta(conn: sqlite3.Connection, group_id: int, key: str, value: str) -> Group:
    return _set_entity_meta(
        conn,
        group_id,
        key,
        value,
        setter=repo.set_group_metadata_key,
        fetcher=get_group,
    )


def remove_group_meta(conn: sqlite3.Connection, group_id: int, key: str) -> str:
    return _remove_entity_meta(
        conn,
        group_id,
        key,
        remover=repo.remove_group_metadata_key,
        fetcher=get_group,
        entity_name="group",
    )


def replace_group_metadata(
    conn: sqlite3.Connection,
    group_id: int,
    new_metadata: dict[str, str],
    *,
    source: str,
) -> Group:
    """Atomically replace a group's entire metadata blob. See
    `replace_task_metadata` for the `source` parameter rationale.
    """
    del source
    return _replace_entity_metadata(
        conn,
        group_id,
        new_metadata,
        writer=repo.replace_group_metadata,
        fetcher=get_group,
    )


# ---- Dependency ----


def add_dependency(
    conn: sqlite3.Connection,
    task_id: int,
    depends_on_id: int,
) -> None:
    with transaction(conn), _friendly_errors():
        if task_id == depends_on_id:
            raise ValueError("a task cannot depend on itself")
        task = get_task(conn, task_id)
        dep = get_task(conn, depends_on_id)
        if task.workspace_id != dep.workspace_id:
            raise ValueError(
                f"tasks must be on the same workspace: "
                f"task {task_id} is on workspace {task.workspace_id}, "
                f"task {depends_on_id} is on workspace {dep.workspace_id}"
            )
        existing = repo.list_blocked_by_ids(conn, task_id)
        if depends_on_id in existing:
            raise ValueError(f"task {task_id} already depends on task {depends_on_id}")
        if task_id in repo.get_reachable_task_ids(conn, depends_on_id):
            raise ValueError(f"adding dependency {task_id} -> {depends_on_id} would create a cycle")
        repo.add_dependency(conn, task_id, depends_on_id)


def archive_dependency(
    conn: sqlite3.Connection,
    task_id: int,
    depends_on_id: int,
) -> None:
    with transaction(conn), _friendly_errors():
        existing = repo.list_blocked_by_ids(conn, task_id)
        if depends_on_id not in existing:
            raise LookupError(f"task {task_id} does not depend on task {depends_on_id}")
        repo.archive_dependency(conn, task_id, depends_on_id)


def list_all_dependencies(
    conn: sqlite3.Connection,
) -> tuple[tuple[int, int], ...]:
    return repo.list_all_dependencies(conn)


# ---- Group Dependency ----


def add_group_dependency(
    conn: sqlite3.Connection,
    group_id: int,
    depends_on_id: int,
) -> None:
    with transaction(conn), _friendly_errors():
        if group_id == depends_on_id:
            raise ValueError("a group cannot depend on itself")
        grp = repo.get_group(conn, group_id)
        if grp is None:
            raise LookupError(f"group {group_id} not found")
        dep = repo.get_group(conn, depends_on_id)
        if dep is None:
            raise LookupError(f"group {depends_on_id} not found")
        grp_proj = repo.get_project(conn, grp.project_id)
        dep_proj = repo.get_project(conn, dep.project_id)
        if grp_proj is None or dep_proj is None or grp_proj.workspace_id != dep_proj.workspace_id:
            raise ValueError(
                f"groups must be on the same workspace: "
                f"group {group_id} is on workspace {grp_proj.workspace_id if grp_proj else '?'}, "
                f"group {depends_on_id} is on workspace {dep_proj.workspace_id if dep_proj else '?'}"
            )
        existing = repo.list_group_blocked_by_ids(conn, group_id)
        if depends_on_id in existing:
            raise ValueError(f"group {group_id} already depends on group {depends_on_id}")
        if group_id in repo.get_reachable_group_dep_ids(conn, depends_on_id):
            raise ValueError(
                f"adding dependency {group_id} -> {depends_on_id} would create a cycle"
            )
        repo.add_group_dependency(conn, group_id, depends_on_id)


def archive_group_dependency(
    conn: sqlite3.Connection,
    group_id: int,
    depends_on_id: int,
) -> None:
    with transaction(conn), _friendly_errors():
        existing = repo.list_group_blocked_by_ids(conn, group_id)
        if depends_on_id not in existing:
            raise LookupError(f"group {group_id} does not depend on group {depends_on_id}")
        repo.archive_group_dependency(conn, group_id, depends_on_id)


def list_all_group_dependencies(
    conn: sqlite3.Connection,
) -> tuple[tuple[int, int], ...]:
    return repo.list_all_group_dependencies(conn)


# ---- History ----


def list_task_history(
    conn: sqlite3.Connection,
    task_id: int,
) -> tuple[TaskHistory, ...]:
    return repo.list_task_history(conn, task_id)


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
    project_id: int,
    title: str,
    parent_id: int | None = None,
    position: int = 0,
    description: str | None = None,
) -> Group:
    with transaction(conn), _friendly_errors():
        project = get_project(conn, project_id)
        if parent_id is not None:
            parent = repo.get_group(conn, parent_id)
            if parent is None:
                raise LookupError(f"parent group {parent_id} not found")
            if parent.project_id != project_id:
                raise ValueError(
                    f"parent group belongs to project {parent.project_id}, not {project_id}"
                )
        return repo.insert_group(
            conn,
            NewGroup(
                workspace_id=project.workspace_id,
                project_id=project_id,
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
    project_id: int,
    title: str,
) -> Group:
    group = repo.get_group_by_title(conn, project_id, title)
    if group is None:
        raise LookupError(f"group {title!r} not found")
    return group


def resolve_group_by_title(
    conn: sqlite3.Connection,
    workspace_id: int,
    title: str,
    *,
    project_id: int | None = None,
) -> Group:
    """Resolve a group by title. If project_id is given, scope the search to that project.
    Otherwise search all projects on the workspace; raises LookupError on ambiguity.
    Comparison is case-insensitive (matching the underlying title COLLATE NOCASE)."""
    if project_id is not None:
        return get_group_by_title(conn, project_id, title)
    candidates = repo.list_groups_by_workspace(conn, workspace_id, title=title)
    if not candidates:
        raise LookupError(f"group {title!r} not found")
    if len(candidates) > 1:
        proj_names = []
        for g in candidates:
            proj = repo.get_project(conn, g.project_id)
            if proj is not None:
                proj_names.append(proj.name)
        raise LookupError(
            f"group {title!r} is ambiguous — exists in projects: "
            + ", ".join(repr(n) for n in proj_names)
            + ". Use --project to disambiguate"
        )
    return candidates[0]


def resolve_group(
    conn: sqlite3.Connection,
    workspace_id: int,
    title: str,
    *,
    project_name: str | None = None,
) -> Group:
    """Resolve a group by title. If project_name is given, translates it to a
    project_id and scopes the search; otherwise searches all projects on the
    workspace (raising LookupError on ambiguity)."""
    project_id = get_project_by_name(conn, workspace_id, project_name).id if project_name else None
    return resolve_group_by_title(conn, workspace_id, title, project_id=project_id)


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
    return group_to_detail(group, tasks=tasks, children=children, parent=parent)


def list_groups(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    include_archived: bool = False,
    only_archived: bool = False,
) -> tuple[GroupRef, ...]:
    groups = repo.list_groups(
        conn,
        project_id,
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


def update_group(
    conn: sqlite3.Connection,
    group_id: int,
    changes: dict[str, Any],
) -> Group:
    with transaction(conn), _friendly_errors():
        if "parent_id" in changes:
            new_parent = changes["parent_id"]
            if new_parent is not None and _would_create_cycle(conn, group_id, new_parent):
                raise ValueError("reparenting would create a cycle")
        return repo.update_group(conn, group_id, changes)


# ---- Task-group assignment ----


def assign_task_to_group(
    conn: sqlite3.Connection,
    task_id: int,
    group_id: int,
    *,
    source: str,
) -> Task:
    """Assign a group to a task, auto-inferring project_id from the group
    when the task has none. Preserves the CLI `group assign` convenience.

    Holds a single outer transaction so the reads (task, group) stay
    consistent with the subsequent update — closing the TOCTOU window that
    would otherwise exist between the reads and a separate update_task call.
    """
    with transaction(conn), _friendly_errors():
        task = get_task(conn, task_id)
        group = get_group(conn, group_id)  # raises LookupError on miss
        changes: dict[str, Any] = {"group_id": group_id}
        if task.project_id is None:
            changes["project_id"] = group.project_id
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
    project_id: int,
) -> tuple[int, ...]:
    return repo.list_ungrouped_task_ids(conn, project_id)


# ---- Tag ----


def create_tag(conn: sqlite3.Connection, workspace_id: int, name: str) -> Tag:
    with transaction(conn), _friendly_errors():
        return repo.insert_tag(conn, NewTag(workspace_id=workspace_id, name=name))


def get_tag(conn: sqlite3.Connection, tag_id: int) -> Tag:
    tag = repo.get_tag(conn, tag_id)
    if tag is None:
        raise LookupError(f"tag {tag_id} not found")
    return tag


def get_tag_by_name(conn: sqlite3.Connection, workspace_id: int, name: str) -> Tag:
    tag = repo.get_tag_by_name(conn, workspace_id, name)
    if tag is None:
        raise LookupError(f"tag {name!r} not found")
    return tag


def list_tags(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    include_archived: bool = False,
    only_archived: bool = False,
) -> tuple[Tag, ...]:
    return repo.list_tags(
        conn,
        workspace_id,
        include_archived=include_archived,
        only_archived=only_archived,
    )


def update_tag(
    conn: sqlite3.Connection,
    tag_id: int,
    changes: dict[str, Any],
) -> Tag:
    with transaction(conn), _friendly_errors():
        return repo.update_tag(conn, tag_id, changes)


def archive_tag(conn: sqlite3.Connection, tag_id: int, *, unassign: bool = False) -> Tag:
    with transaction(conn), _friendly_errors():
        if unassign:
            repo.remove_all_task_tags_by_tag(conn, tag_id)
        return repo.update_tag(conn, tag_id, {"archived": True})


def tag_task(
    conn: sqlite3.Connection,
    task_id: int,
    tag_name: str,
    workspace_id: int,
) -> Tag:
    with transaction(conn), _friendly_errors():
        task = get_task(conn, task_id)
        if task.workspace_id != workspace_id:
            raise ValueError(
                f"task {task_id} belongs to workspace {task.workspace_id}, "
                f"not workspace {workspace_id}"
            )
        tag = _ensure_tag(conn, workspace_id, tag_name)
        repo.add_tag_to_task(conn, task_id, tag.id)
        return tag


def untag_task(
    conn: sqlite3.Connection,
    task_id: int,
    tag_name: str,
    workspace_id: int,
) -> None:
    with transaction(conn), _friendly_errors():
        task = get_task(conn, task_id)
        if task.workspace_id != workspace_id:
            raise ValueError(
                f"task {task_id} belongs to workspace {task.workspace_id}, "
                f"not workspace {workspace_id}"
            )
        tag = repo.get_tag_by_name(conn, workspace_id, tag_name)
        if tag is None:
            raise LookupError(f"tag {tag_name!r} not found")
        existing = repo.list_tag_ids_by_task(conn, task_id)
        if tag.id not in existing:
            raise LookupError(f"task {task_id} is not tagged {tag_name!r}")
        repo.remove_tag_from_task(conn, task_id, tag.id)


# ---- Archive (preview + cascade) ----


def preview_archive_task(conn: sqlite3.Connection, task_id: int) -> ArchivePreview:
    task = get_task(conn, task_id)
    return ArchivePreview(
        entity_type="task",
        entity_name=task.title,
        already_archived=task.archived,
        task_count=0,
        group_count=0,
        project_count=0,
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
        project_count=0,
        status_count=0,
    )


def preview_archive_project(conn: sqlite3.Connection, project_id: int) -> ArchivePreview:
    project = get_project(conn, project_id)
    return ArchivePreview(
        entity_type="project",
        entity_name=project.name,
        already_archived=project.archived,
        task_count=repo.count_active_tasks_in_project(conn, project_id),
        group_count=repo.count_active_groups_in_project(conn, project_id),
        project_count=0,
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
        project_count=repo.count_active_projects_in_workspace(conn, workspace_id),
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
        project_count=0,
        status_count=0,
    )


def preview_archive_tag(conn: sqlite3.Connection, tag_id: int) -> ArchivePreview:
    tag = get_tag(conn, tag_id)
    return ArchivePreview(
        entity_type="tag",
        entity_name=tag.name,
        already_archived=tag.archived,
        task_count=repo.count_active_tasks_by_tag(conn, tag_id),
        group_count=0,
        project_count=0,
        status_count=0,
    )


def preview_update_task(
    conn: sqlite3.Connection,
    task_id: int,
    changes: dict[str, Any],
    *,
    add_tags: tuple[str, ...] = (),
    remove_tags: tuple[str, ...] = (),
) -> EntityUpdatePreview:
    """Compute a diff for `update_task` without writing. Validates the
    merged change set the same way `update_task` does so dry-run surfaces
    validation errors before commit.
    """
    old = get_task(conn, task_id)
    _validate_task_update(conn, old, changes)
    before, after = _diff_fields(old, changes)
    current_tag_names = tuple(t.name for t in repo.list_tags_by_task(conn, task_id))
    added = tuple(t for t in add_tags if t.lower() not in {n.lower() for n in current_tag_names})
    removed: list[str] = []
    for t in remove_tags:
        matches = [n for n in current_tag_names if n.lower() == t.lower()]
        if not matches:
            raise LookupError(f"task {task_id} is not tagged {t!r}")
        removed.append(matches[0])
    return EntityUpdatePreview(
        entity_type="task",
        entity_id=task_id,
        label=old.title,
        before=before,
        after=after,
        tags_added=added,
        tags_removed=tuple(removed),
    )


def preview_move_task(
    conn: sqlite3.Connection,
    task_id: int,
    status_id: int,
    position: int,
    *,
    project_id: int | None = None,
    change_project: bool = False,
) -> TaskMovePreview:
    """Compute a from/to snapshot for `move_task`. No DB writes.

    Pass `change_project=True` to reassign the project; `project_id` is
    then the new value (None means unassign). When `change_project=False`
    the preview reports no project change.
    """
    task = get_task(conn, task_id)
    from_status = get_status(conn, task.status_id)
    to_status = get_status(conn, status_id)
    from_project = (
        repo.get_project(conn, task.project_id).name if task.project_id is not None else None  # type: ignore[union-attr]
    )
    if change_project:
        to_project_id = project_id
        project_changed = to_project_id != task.project_id
    else:
        to_project_id = task.project_id
        project_changed = False
    to_project = (
        repo.get_project(conn, to_project_id).name if to_project_id is not None else None  # type: ignore[union-attr]
    )
    return TaskMovePreview(
        task_id=task_id,
        title=task.title,
        from_status=from_status.name,
        to_status=to_status.name,
        from_position=task.position,
        to_position=position,
        from_project=from_project,
        to_project=to_project,
        project_changed=project_changed,
    )


def preview_update_project(
    conn: sqlite3.Connection,
    project_id: int,
    changes: dict[str, Any],
) -> EntityUpdatePreview:
    """Compute a diff for `update_project` without writing. Runs the same
    validation as `update_project` so dry-run surfaces rejection errors.
    """
    old = get_project(conn, project_id)
    _validate_project_update(conn, project_id, changes)
    before, after = _diff_fields(old, changes)
    return EntityUpdatePreview(
        entity_type="project",
        entity_id=project_id,
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
        _record_changes(conn, task_id, old, {"archived": True}, source)
        return updated


def _record_archive_history(
    conn: sqlite3.Connection,
    task_ids: tuple[int, ...],
    workspace_id: int,
    source: str,
) -> None:
    # Values must match str(bool) used by _record_changes for single-task archive.
    # If Task.archived ever changes from bool, update both paths together.
    for tid in task_ids:
        repo.insert_task_history(
            conn,
            NewTaskHistory(
                task_id=tid,
                workspace_id=workspace_id,
                field=TaskField.ARCHIVED,
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
        repo.archive_tasks_in_group_subtree(conn, group_id)
        _record_archive_history(conn, task_ids, group.workspace_id, source)
        repo.archive_descendant_groups(conn, group_id)
        return repo.update_group(conn, group_id, {"archived": True})


def cascade_archive_project(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    source: str,
) -> Project:
    with transaction(conn), _friendly_errors():
        project = get_project(conn, project_id)
        task_ids = repo.list_active_task_ids_in_project(conn, project_id)
        repo.archive_tasks_in_project(conn, project_id)
        _record_archive_history(conn, task_ids, project.workspace_id, source)
        repo.archive_groups_in_project(conn, project_id)
        return repo.update_project(conn, project_id, {"archived": True})


def cascade_archive_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    source: str,
) -> Workspace:
    with transaction(conn), _friendly_errors():
        task_ids = repo.list_active_task_ids_in_workspace(conn, workspace_id)
        repo.archive_tasks_in_workspace(conn, workspace_id)
        _record_archive_history(conn, task_ids, workspace_id, source)
        repo.archive_groups_in_workspace(conn, workspace_id)
        repo.archive_projects_in_workspace(conn, workspace_id)
        repo.archive_statuses_in_workspace(conn, workspace_id)
        return repo.update_workspace(conn, workspace_id, {"archived": True})
