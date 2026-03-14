from __future__ import annotations

import sqlite3
from typing import Any

from . import repository as repo
from .connection import transaction
from .mappers import (
    project_ref_to_detail,
    project_to_ref,
    task_ref_to_detail,
    task_to_ref,
)
from .models import (
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
from .service_models import (
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
    refs = []
    for t in tasks:
        blocked_by_ids = repo.list_blocked_by_ids(conn, t.id)
        blocks_ids = repo.list_blocks_ids(conn, t.id)
        refs.append(task_to_ref(t, blocked_by_ids, blocks_ids))
    return tuple(refs)


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
