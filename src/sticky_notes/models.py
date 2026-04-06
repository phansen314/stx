from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class TaskFilter:
    status_id: int | None = None
    project_id: int | None = None
    priority: int | None = None
    search: str | None = None
    tag_id: int | None = None
    group_id: int | None = None
    include_archived: bool = False
    only_archived: bool = False


class TaskField(StrEnum):
    TITLE = "title"
    DESCRIPTION = "description"
    STATUS_ID = "status_id"
    PROJECT_ID = "project_id"
    PRIORITY = "priority"
    DUE_DATE = "due_date"
    POSITION = "position"
    ARCHIVED = "archived"
    START_DATE = "start_date"
    FINISH_DATE = "finish_date"
    GROUP_ID = "group_id"


# ---- Pre-insert types (no id, no created_at) ----


@dataclass(frozen=True)
class NewBoard:
    name: str


@dataclass(frozen=True)
class NewProject:
    board_id: int
    name: str
    description: str | None = None


@dataclass(frozen=True)
class NewStatus:
    board_id: int
    name: str


@dataclass(frozen=True)
class NewTask:
    board_id: int
    title: str
    status_id: int
    project_id: int | None = None
    description: str | None = None
    priority: int = 1
    due_date: int | None = None
    position: int = 0
    start_date: int | None = None
    finish_date: int | None = None


@dataclass(frozen=True)
class NewGroup:
    project_id: int
    title: str
    parent_id: int | None = None
    position: int = 0


@dataclass(frozen=True)
class NewTaskHistory:
    task_id: int
    field: TaskField
    new_value: str | None
    source: str
    old_value: str | None = None


@dataclass(frozen=True)
class NewTag:
    board_id: int
    name: str


# ---- Persisted types (full row from DB) ----


@dataclass(frozen=True)
class Tag:
    id: int
    board_id: int
    name: str
    archived: bool
    created_at: int


@dataclass(frozen=True)
class Board:
    id: int
    name: str
    archived: bool
    created_at: int


@dataclass(frozen=True)
class Project:
    id: int
    board_id: int
    name: str
    description: str | None
    archived: bool
    created_at: int


@dataclass(frozen=True)
class Status:
    id: int
    board_id: int
    name: str
    archived: bool
    created_at: int


@dataclass(frozen=True)
class Task:
    id: int
    board_id: int
    title: str
    project_id: int | None
    description: str | None
    status_id: int
    priority: int
    due_date: int | None
    position: int
    archived: bool
    created_at: int
    start_date: int | None
    finish_date: int | None
    group_id: int | None


@dataclass(frozen=True)
class Group:
    id: int
    project_id: int
    title: str
    parent_id: int | None
    position: int
    archived: bool
    created_at: int


@dataclass(frozen=True)
class TaskHistory:
    id: int
    task_id: int
    field: TaskField
    old_value: str | None
    new_value: str | None
    source: str
    changed_at: int

