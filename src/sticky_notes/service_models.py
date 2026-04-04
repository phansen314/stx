from __future__ import annotations

from dataclasses import dataclass

from .models import Column, Group, Project, Tag, Task, TaskHistory


# ---- Ref types (relationships as IDs) ----


@dataclass(frozen=True)
class TaskRef(Task):
    blocked_by_ids: tuple[int, ...] = ()
    blocks_ids: tuple[int, ...] = ()
    tag_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class ProjectRef(Project):
    task_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class GroupRef(Group):
    task_ids: tuple[int, ...] = ()
    child_ids: tuple[int, ...] = ()


# ---- Hydrated types (relationships as full objects) ----


@dataclass(frozen=True)
class TaskDetail(TaskRef):
    # column is always present (tasks.column_id is NOT NULL).
    # Default is None to satisfy dataclass field-ordering; __post_init__
    # enforces that callers always supply a real Column.
    column: Column = None  # type: ignore[assignment]
    project: Project | None = None
    blocked_by: tuple[Task, ...] = ()
    blocks: tuple[Task, ...] = ()
    history: tuple[TaskHistory, ...] = ()
    tags: tuple[Tag, ...] = ()

    def __post_init__(self) -> None:
        if self.column is None:
            raise TypeError("TaskDetail.column is required")


@dataclass(frozen=True)
class ProjectDetail(ProjectRef):
    tasks: tuple[Task, ...] = ()


@dataclass(frozen=True)
class GroupDetail(GroupRef):
    tasks: tuple[Task, ...] = ()
    children: tuple[Group, ...] = ()
    parent: Group | None = None
