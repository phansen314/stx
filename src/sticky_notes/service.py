from __future__ import annotations

import sqlite3
from typing import Any

from . import repository as repo
from .connection import transaction
from .mappers import (
    group_ref_to_detail,
    group_to_ref,
    project_ref_to_detail,
    project_to_ref,
    task_ref_to_detail,
    task_to_ref,
)
from .models import (
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
from .service_models import (
    GroupDetail,
    GroupRef,
    ProjectDetail,
    ProjectRef,
    TaskDetail,
    TaskRef,
)


# ---- Private helpers ----


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
                field=TaskField(key),
                old_value=str(old_val) if old_val is not None else None,
                new_value=str(new_val),
                source=source,
            ),
        )


# ---- Board ----


def create_board(conn: sqlite3.Connection, name: str) -> Board:
    with transaction(conn):
        return repo.insert_board(conn, NewBoard(name=name))


def get_board(conn: sqlite3.Connection, board_id: int) -> Board:
    board = repo.get_board(conn, board_id)
    if board is None:
        raise LookupError(f"board {board_id} not found")
    return board


def get_board_by_name(conn: sqlite3.Connection, name: str) -> Board:
    board = repo.get_board_by_name(conn, name)
    if board is None:
        raise LookupError(f"board {name!r} not found")
    return board


def list_boards(
    conn: sqlite3.Connection,
    *,
    include_archived: bool = False,
) -> tuple[Board, ...]:
    return repo.list_boards(conn, include_archived=include_archived)


def update_board(
    conn: sqlite3.Connection,
    board_id: int,
    changes: dict[str, Any],
) -> Board:
    with transaction(conn):
        return repo.update_board(conn, board_id, changes)


# ---- Column ----


def create_column(
    conn: sqlite3.Connection,
    board_id: int,
    name: str,
    position: int = 0,
) -> Column:
    with transaction(conn):
        return repo.insert_column(conn, NewColumn(board_id=board_id, name=name, position=position))


def get_column(conn: sqlite3.Connection, column_id: int) -> Column:
    col = repo.get_column(conn, column_id)
    if col is None:
        raise LookupError(f"column {column_id} not found")
    return col


def get_column_by_name(
    conn: sqlite3.Connection,
    board_id: int,
    name: str,
) -> Column:
    col = repo.get_column_by_name(conn, board_id, name)
    if col is None:
        raise LookupError(f"column {name!r} not found")
    return col


def list_columns(
    conn: sqlite3.Connection,
    board_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Column, ...]:
    return repo.list_columns(conn, board_id, include_archived=include_archived)


def update_column(
    conn: sqlite3.Connection,
    column_id: int,
    changes: dict[str, Any],
) -> Column:
    with transaction(conn):
        return repo.update_column(conn, column_id, changes)


# ---- Project ----


def create_project(
    conn: sqlite3.Connection,
    board_id: int,
    name: str,
    description: str | None = None,
) -> Project:
    with transaction(conn):
        return repo.insert_project(
            conn, NewProject(board_id=board_id, name=name, description=description)
        )


def get_project(conn: sqlite3.Connection, project_id: int) -> Project:
    project = repo.get_project(conn, project_id)
    if project is None:
        raise LookupError(f"project {project_id} not found")
    return project


def get_project_by_name(
    conn: sqlite3.Connection,
    board_id: int,
    name: str,
) -> Project:
    project = repo.get_project_by_name(conn, board_id, name)
    if project is None:
        raise LookupError(f"project {name!r} not found")
    return project


def get_project_ref(conn: sqlite3.Connection, project_id: int) -> ProjectRef:
    project = get_project(conn, project_id)
    task_ids = repo.list_task_ids_by_project(conn, project_id)
    return project_to_ref(project, task_ids)


def get_project_detail(conn: sqlite3.Connection, project_id: int) -> ProjectDetail:
    ref = get_project_ref(conn, project_id)
    tasks = repo.list_tasks_by_project(conn, project_id)
    return project_ref_to_detail(ref, tasks)


def list_projects(
    conn: sqlite3.Connection,
    board_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Project, ...]:
    return repo.list_projects(conn, board_id, include_archived=include_archived)


def update_project(
    conn: sqlite3.Connection,
    project_id: int,
    changes: dict[str, Any],
) -> Project:
    with transaction(conn):
        return repo.update_project(conn, project_id, changes)


# ---- Task ----


def create_task(
    conn: sqlite3.Connection,
    board_id: int,
    title: str,
    column_id: int,
    *,
    project_id: int | None = None,
    description: str | None = None,
    priority: int = 1,
    due_date: int | None = None,
    position: int = 0,
    start_date: int | None = None,
    finish_date: int | None = None,
) -> Task:
    with transaction(conn):
        return repo.insert_task(
            conn,
            NewTask(
                board_id=board_id,
                title=title,
                column_id=column_id,
                project_id=project_id,
                description=description,
                priority=priority,
                due_date=due_date,
                position=position,
                start_date=start_date,
                finish_date=finish_date,
            ),
        )


def get_task(conn: sqlite3.Connection, task_id: int) -> Task:
    task = repo.get_task(conn, task_id)
    if task is None:
        raise LookupError(f"task {task_id} not found")
    return task


def get_task_by_title(conn: sqlite3.Connection, board_id: int, title: str) -> Task:
    task = repo.get_task_by_title(conn, board_id, title)
    if task is None:
        raise LookupError(f"task {title!r} not found")
    return task


def get_task_ref(conn: sqlite3.Connection, task_id: int) -> TaskRef:
    task = get_task(conn, task_id)
    blocked_by_ids = repo.list_blocked_by_ids(conn, task_id)
    blocks_ids = repo.list_blocks_ids(conn, task_id)
    return task_to_ref(task, blocked_by_ids, blocks_ids)


def get_task_detail(conn: sqlite3.Connection, task_id: int) -> TaskDetail:
    ref = get_task_ref(conn, task_id)
    column = get_column(conn, ref.column_id)
    project = repo.get_project(conn, ref.project_id) if ref.project_id is not None else None
    blocked_by = repo.list_blocked_by_tasks(conn, task_id)
    blocks = repo.list_blocks_tasks(conn, task_id)
    history = repo.list_task_history(conn, task_id)
    return task_ref_to_detail(ref, column, project, blocked_by, blocks, history)


def list_tasks(
    conn: sqlite3.Connection,
    board_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Task, ...]:
    return repo.list_tasks(conn, board_id, include_archived=include_archived)


def list_task_refs(
    conn: sqlite3.Connection,
    board_id: int,
    *,
    include_archived: bool = False,
) -> tuple[TaskRef, ...]:
    tasks = repo.list_tasks(conn, board_id, include_archived=include_archived)
    task_ids = tuple(t.id for t in tasks)
    blocked_by_map, blocks_map = repo.batch_dependency_ids(conn, task_ids)
    return tuple(
        task_to_ref(t, blocked_by_map.get(t.id, ()), blocks_map.get(t.id, ()))
        for t in tasks
    )


def list_task_refs_filtered(
    conn: sqlite3.Connection,
    board_id: int,
    *,
    task_filter: TaskFilter | None = None,
) -> tuple[TaskRef, ...]:
    tasks = repo.list_tasks_filtered(conn, board_id, task_filter=task_filter)
    task_ids = tuple(t.id for t in tasks)
    blocked_by_map, blocks_map = repo.batch_dependency_ids(conn, task_ids)
    return tuple(
        task_to_ref(t, blocked_by_map.get(t.id, ()), blocks_map.get(t.id, ()))
        for t in tasks
    )


def update_task(
    conn: sqlite3.Connection,
    task_id: int,
    changes: dict[str, Any],
    source: str,
) -> Task:
    with transaction(conn):
        old = get_task(conn, task_id)
        updated = repo.update_task(conn, task_id, changes)
        _record_changes(conn, task_id, old, changes, source)
        return updated


def move_task(
    conn: sqlite3.Connection,
    task_id: int,
    column_id: int,
    position: int,
    source: str,
) -> Task:
    return update_task(conn, task_id, {"column_id": column_id, "position": position}, source)


def move_task_to_board(
    conn: sqlite3.Connection,
    task_id: int,
    target_board_id: int,
    target_column_id: int,
    *,
    project_id: int | None = None,
    source: str,
) -> Task:
    with transaction(conn):
        old = get_task(conn, task_id)
        if old.archived:
            raise ValueError(f"task {task_id} is archived")

        blocked_by = repo.list_blocked_by_ids(conn, task_id)
        blocks = repo.list_blocks_ids(conn, task_id)
        if blocked_by or blocks:
            dep_ids = sorted({*blocked_by, *blocks})
            raise ValueError(
                f"task {task_id} has dependencies ({', '.join(str(d) for d in dep_ids)}); "
                "remove them before moving to another board"
            )

        target_col = repo.get_column(conn, target_column_id)
        if target_col is None or target_col.board_id != target_board_id:
            raise ValueError(
                f"column {target_column_id} does not belong to board {target_board_id}"
            )
        if project_id is not None:
            proj = repo.get_project(conn, project_id)
            if proj is None or proj.board_id != target_board_id:
                raise ValueError(
                    f"project {project_id} does not belong to board {target_board_id}"
                )

        new = repo.insert_task(
            conn,
            NewTask(
                board_id=target_board_id,
                title=old.title,
                column_id=target_column_id,
                project_id=project_id,
                description=old.description,
                priority=old.priority,
                due_date=old.due_date,
                position=0,
                start_date=old.start_date,
                finish_date=old.finish_date,
            ),
        )

        repo.update_task(conn, task_id, {"archived": True})
        _record_changes(conn, task_id, old, {"archived": True}, source)
        return new


# ---- Dependency ----


def add_dependency(
    conn: sqlite3.Connection,
    task_id: int,
    depends_on_id: int,
) -> None:
    with transaction(conn):
        repo.add_dependency(conn, task_id, depends_on_id)


def remove_dependency(
    conn: sqlite3.Connection,
    task_id: int,
    depends_on_id: int,
) -> None:
    with transaction(conn):
        repo.remove_dependency(conn, task_id, depends_on_id)


def list_all_dependencies(
    conn: sqlite3.Connection,
) -> tuple[tuple[int, int], ...]:
    return repo.list_all_dependencies(conn)


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
) -> Group:
    with transaction(conn):
        if parent_id is not None:
            parent = repo.get_group(conn, parent_id)
            if parent is None:
                raise LookupError(f"parent group {parent_id} not found")
            if parent.project_id != project_id:
                raise ValueError(
                    f"parent group belongs to project {parent.project_id}, "
                    f"not {project_id}"
                )
        return repo.insert_group(
            conn,
            NewGroup(
                project_id=project_id,
                title=title,
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


def get_group_ref(conn: sqlite3.Connection, group_id: int) -> GroupRef:
    group = get_group(conn, group_id)
    task_ids = repo.list_task_ids_by_group(conn, group_id)
    children = repo.list_child_groups(conn, group_id)
    child_ids = tuple(c.id for c in children)
    return group_to_ref(group, task_ids, child_ids)


def get_group_detail(conn: sqlite3.Connection, group_id: int) -> GroupDetail:
    ref = get_group_ref(conn, group_id)
    tasks = repo.list_tasks_by_ids(conn, ref.task_ids)
    children = repo.list_child_groups(conn, group_id)
    parent = repo.get_group(conn, ref.parent_id) if ref.parent_id is not None else None
    return group_ref_to_detail(ref, tasks, children, parent)


def list_groups(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    include_archived: bool = False,
) -> tuple[GroupRef, ...]:
    groups = repo.list_groups(conn, project_id, include_archived=include_archived)
    if not groups:
        return ()
    group_ids = tuple(g.id for g in groups)
    task_ids_map = repo.batch_task_ids_by_group(conn, group_ids)
    child_ids_map = repo.batch_child_ids_by_group(
        conn, group_ids, include_archived=include_archived,
    )
    return tuple(
        group_to_ref(g, task_ids_map.get(g.id, ()), child_ids_map.get(g.id, ()))
        for g in groups
    )


def update_group(
    conn: sqlite3.Connection,
    group_id: int,
    changes: dict[str, Any],
) -> Group:
    with transaction(conn):
        if "parent_id" in changes:
            new_parent = changes["parent_id"]
            if new_parent is not None and _would_create_cycle(conn, group_id, new_parent):
                raise ValueError("reparenting would create a cycle")
        return repo.update_group(conn, group_id, changes)


def archive_group(conn: sqlite3.Connection, group_id: int) -> None:
    with transaction(conn):
        group = get_group(conn, group_id)
        task_ids = repo.list_task_ids_by_group(conn, group_id)
        for tid in task_ids:
            repo.insert_task_history(
                conn,
                NewTaskHistory(
                    task_id=tid,
                    field=TaskField.GROUP_ID,
                    old_value=str(group_id),
                    new_value="None",
                    source="archive_group",
                ),
            )
        repo.delete_task_groups_by_group(conn, group_id)
        repo.reparent_children(conn, group_id, group.parent_id)
        repo.update_group(conn, group_id, {"archived": True})


# ---- Task-group assignment ----


def assign_task_to_group(
    conn: sqlite3.Connection,
    task_id: int,
    group_id: int,
) -> None:
    with transaction(conn):
        task = get_task(conn, task_id)
        group = get_group(conn, group_id)
        if task.project_id is None:
            repo.update_task(conn, task_id, {"project_id": group.project_id})
        elif task.project_id != group.project_id:
            raise ValueError(
                f"task belongs to project {task.project_id}, "
                f"group belongs to project {group.project_id}"
            )
        old_group_id = repo.get_task_group_id(conn, task_id)
        repo.assign_task_to_group(conn, task_id, group_id)
        repo.insert_task_history(
            conn,
            NewTaskHistory(
                task_id=task_id,
                field=TaskField.GROUP_ID,
                old_value=str(old_group_id) if old_group_id is not None else None,
                new_value=str(group_id),
                source="assign_task_to_group",
            ),
        )


def unassign_task_from_group(
    conn: sqlite3.Connection,
    task_id: int,
) -> None:
    with transaction(conn):
        old_group_id = repo.get_task_group_id(conn, task_id)
        repo.unassign_task_from_group(conn, task_id)
        if old_group_id is not None:
            repo.insert_task_history(
                conn,
                NewTaskHistory(
                    task_id=task_id,
                    field=TaskField.GROUP_ID,
                    old_value=str(old_group_id),
                    new_value="None",
                    source="unassign_task_from_group",
                ),
            )


# ---- Task-group queries ----


def get_task_group_id(
    conn: sqlite3.Connection,
    task_id: int,
) -> int | None:
    return repo.get_task_group_id(conn, task_id)


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


def batch_group_ids_by_task(
    conn: sqlite3.Connection,
    task_ids: tuple[int, ...],
) -> dict[int, int]:
    return repo.batch_group_ids_by_task(conn, task_ids)


def list_groups_for_board(
    conn: sqlite3.Connection,
    board_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Group, ...]:
    return repo.list_groups_by_board(conn, board_id, include_archived=include_archived)


def list_ungrouped_task_ids(
    conn: sqlite3.Connection,
    project_id: int,
) -> tuple[int, ...]:
    return repo.list_ungrouped_task_ids(conn, project_id)
