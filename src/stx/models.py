from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class TaskFilter:
    status_id: int | None = None
    priority: int | None = None
    search: str | None = None
    tag_id: int | None = None
    group_id: int | None = None
    include_archived: bool = False
    only_archived: bool = False


class EntityType(StrEnum):
    TASK = "task"
    GROUP = "group"
    WORKSPACE = "workspace"
    STATUS = "status"
    EDGE = "edge"


class TaskField(StrEnum):
    TITLE = "title"
    DESCRIPTION = "description"
    STATUS_ID = "status_id"
    PRIORITY = "priority"
    DUE_DATE = "due_date"
    POSITION = "position"
    ARCHIVED = "archived"
    START_DATE = "start_date"
    FINISH_DATE = "finish_date"
    GROUP_ID = "group_id"


class GroupField(StrEnum):
    TITLE = "title"
    DESCRIPTION = "description"
    PARENT_ID = "parent_id"
    POSITION = "position"
    ARCHIVED = "archived"


class WorkspaceField(StrEnum):
    NAME = "name"
    ARCHIVED = "archived"


class StatusField(StrEnum):
    NAME = "name"
    ARCHIVED = "archived"


class EdgeField(StrEnum):
    ENDPOINT = "endpoint"
    KIND = "kind"
    ACYCLIC = "acyclic"


# ---- Pre-insert types (no id, no created_at) ----


@dataclass(frozen=True)
class NewWorkspace:
    name: str


@dataclass(frozen=True)
class NewStatus:
    workspace_id: int
    name: str


@dataclass(frozen=True)
class NewTask:
    workspace_id: int
    title: str
    status_id: int
    description: str | None = None
    priority: int = 1
    due_date: int | None = None
    position: int = 0
    start_date: int | None = None
    finish_date: int | None = None
    group_id: int | None = None


@dataclass(frozen=True)
class NewGroup:
    workspace_id: int
    title: str
    description: str | None = None
    parent_id: int | None = None
    position: int = 0


@dataclass(frozen=True)
class NewJournalEntry:
    entity_type: EntityType
    entity_id: int
    workspace_id: int
    field: str
    new_value: str | None
    source: str
    old_value: str | None = None


@dataclass(frozen=True)
class NewTag:
    workspace_id: int
    name: str


# ---- Persisted types (full row from DB) ----


@dataclass(frozen=True)
class Tag:
    id: int
    workspace_id: int
    name: str
    archived: bool
    created_at: int


@dataclass(frozen=True)
class Workspace:
    id: int
    name: str
    archived: bool
    created_at: int
    metadata: dict[str, str]


@dataclass(frozen=True)
class Status:
    id: int
    workspace_id: int
    name: str
    archived: bool
    created_at: int


@dataclass(frozen=True)
class Task:
    id: int
    workspace_id: int
    title: str
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
    metadata: dict[str, str]


@dataclass(frozen=True)
class Group:
    id: int
    workspace_id: int
    title: str
    description: str | None
    parent_id: int | None
    position: int
    archived: bool
    created_at: int
    metadata: dict[str, str]


@dataclass(frozen=True)
class JournalEntry:
    id: int
    entity_type: EntityType
    entity_id: int
    workspace_id: int
    field: str
    old_value: str | None
    new_value: str | None
    source: str
    changed_at: int
