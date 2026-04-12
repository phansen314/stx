from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .models import Group, JournalEntry, Project, Status, Tag, Task, Workspace

# ---- List view types ----


@dataclass(frozen=True)
class TaskListItem:
    """Task fields plus resolved display names, for list rendering without
    extra lookups. Carries names, not full objects."""

    id: int
    workspace_id: int
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
    metadata: dict[str, str]
    project_name: str | None = None
    tag_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class GroupRef:
    """Group fields plus edge IDs, for list rendering and tree walking without
    fetching full related objects."""

    id: int
    workspace_id: int
    project_id: int
    title: str
    description: str | None
    parent_id: int | None
    position: int
    archived: bool
    created_at: int
    metadata: dict[str, str]
    task_ids: tuple[int, ...] = ()
    child_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class WorkspaceListStatus:
    status: Status
    tasks: tuple[TaskListItem, ...]


@dataclass(frozen=True)
class WorkspaceListView:
    workspace: Workspace
    statuses: tuple[WorkspaceListStatus, ...]


@dataclass(frozen=True)
class WorkspaceContext:
    """Aggregated workspace state for one-call session startup."""

    view: WorkspaceListView
    projects: tuple[Project, ...]
    tags: tuple[Tag, ...]
    groups: tuple[GroupRef, ...]


# ---- Hydrated types (relationships as full objects) ----


@dataclass(frozen=True)
class TaskDetail:
    id: int
    workspace_id: int
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
    metadata: dict[str, str]
    status: Status
    project: Project | None
    group: Group | None
    blocked_by: tuple[Task, ...]
    blocks: tuple[Task, ...]
    history: tuple[JournalEntry, ...]
    tags: tuple[Tag, ...]


@dataclass(frozen=True)
class ProjectDetail:
    id: int
    workspace_id: int
    name: str
    description: str | None
    archived: bool
    created_at: int
    tasks: tuple[Task, ...]
    metadata: dict[str, str]


@dataclass(frozen=True)
class GroupDetail:
    id: int
    workspace_id: int
    project_id: int
    title: str
    description: str | None
    parent_id: int | None
    position: int
    archived: bool
    created_at: int
    tasks: tuple[Task, ...]
    children: tuple[Group, ...]
    parent: Group | None
    metadata: dict[str, str]


# ---- Preview types ----


@dataclass(frozen=True)
class MoveToWorkspacePreview:
    task_id: int
    task_title: str
    source_workspace_id: int
    target_workspace_id: int
    target_status_id: int
    target_project_id: int | None
    can_move: bool
    blocking_reason: str | None
    dependency_ids: tuple[int, ...]
    is_archived: bool


@dataclass(frozen=True)
class ArchivePreview:
    """Dry-run result for an archive command. Counts reflect additional
    entities beyond the root that *would* be archived."""

    entity_type: Literal["task", "group", "project", "status", "tag", "workspace"]
    entity_name: str
    already_archived: bool
    task_count: int
    group_count: int
    project_count: int
    status_count: int


@dataclass(frozen=True)
class EntityUpdatePreview:
    """Dry-run result for a field-level update (task/project/group edit).
    `before` / `after` contain only fields that differ — unchanged fields
    are omitted. Tag diffs live on `tags_added` / `tags_removed` for tasks;
    other entity kinds leave those empty.

    Note: `before` and `after` are mutable dicts (shallow-frozen). This is
    an intentional exception to the tuple-everywhere convention because
    diff payloads are JSON-consumer-facing and dict shape is the natural
    JSON representation. Callers must treat these fields as read-only.
    """

    entity_type: Literal["task", "project", "group"]
    entity_id: int
    label: str  # task title, project name, group title
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    tags_added: tuple[str, ...] = ()
    tags_removed: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskMovePreview:
    """Dry-run result for `task mv`. Shows from/to status, position, and
    optional project change."""

    task_id: int
    title: str
    from_status: str
    to_status: str
    from_position: int
    to_position: int
    from_project: str | None
    to_project: str | None
    project_changed: bool
