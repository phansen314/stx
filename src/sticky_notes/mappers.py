from __future__ import annotations

import dataclasses
import sqlite3
from typing import Any

from .models import (
    Board,
    Column,
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

type Row = sqlite3.Row


# ---- DB row -> persisted model ----


def row_to_board(row: Row) -> Board:
    return Board(
        id=row["id"],
        name=row["name"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
    )


def row_to_project(row: Row) -> Project:
    return Project(
        id=row["id"],
        board_id=row["board_id"],
        name=row["name"],
        description=row["description"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
    )


def row_to_column(row: Row) -> Column:
    return Column(
        id=row["id"],
        board_id=row["board_id"],
        name=row["name"],
        position=row["position"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
    )


def row_to_task(row: Row) -> Task:
    return Task(
        id=row["id"],
        board_id=row["board_id"],
        title=row["title"],
        project_id=row["project_id"],
        description=row["description"],
        column_id=row["column_id"],
        priority=row["priority"],
        due_date=row["due_date"],
        position=row["position"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
        start_date=row["start_date"],
        finish_date=row["finish_date"],
    )


def row_to_task_history(row: Row) -> TaskHistory:
    return TaskHistory(
        id=row["id"],
        task_id=row["task_id"],
        field=TaskField(row["field"]),
        old_value=row["old_value"],
        new_value=row["new_value"],
        source=row["source"],
        changed_at=row["changed_at"],
    )


# ---- Persisted model -> ref ----


def shallow_fields(instance: object, cls: type) -> dict[str, Any]:
    if not dataclasses.is_dataclass(cls):
        raise TypeError(f"{cls!r} is not a dataclass")
    if not isinstance(instance, cls):
        raise TypeError(f"{instance!r} is not an instance of {cls!r}")
    return {f.name: getattr(instance, f.name) for f in dataclasses.fields(cls)}


def task_to_ref(
    task: Task,
    blocked_by_ids: tuple[int, ...],
    blocks_ids: tuple[int, ...],
) -> TaskRef:
    return TaskRef(
        **shallow_fields(task, Task),
        blocked_by_ids=blocked_by_ids,
        blocks_ids=blocks_ids,
    )


def project_to_ref(
    project: Project,
    task_ids: tuple[int, ...],
) -> ProjectRef:
    return ProjectRef(
        **shallow_fields(project, Project),
        task_ids=task_ids,
    )


# ---- Ref -> hydrated ----


def task_ref_to_detail(
    ref: TaskRef,
    column: Column,
    project: Project | None,
    blocked_by: tuple[Task, ...],
    blocks: tuple[Task, ...],
    history: tuple[TaskHistory, ...],
) -> TaskDetail:
    return TaskDetail(
        **shallow_fields(ref, TaskRef),
        column=column,
        project=project,
        blocked_by=blocked_by,
        blocks=blocks,
        history=history,
    )


def project_ref_to_detail(
    ref: ProjectRef,
    tasks: tuple[Task, ...],
) -> ProjectDetail:
    return ProjectDetail(
        **shallow_fields(ref, ProjectRef),
        tasks=tasks,
    )
