from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .models import Group, JournalEntry, Status, Tag, Task, Workspace

# ---- Edge ref types (hydrated edge with kind) ----


@dataclass(frozen=True)
class TaskEdgeRef:
    """A task edge hydrated with the full task object and its kind."""

    task: Task
    kind: str


@dataclass(frozen=True)
class GroupEdgeRef:
    """A group edge hydrated with the full group object and its kind."""

    group: Group
    kind: str


# ---- List view types ----


@dataclass(frozen=True)
class TaskEdgeListItem:
    """Denormalized task edge for list rendering — carries task titles."""

    source_id: int
    source_title: str
    target_id: int
    target_title: str
    workspace_id: int
    kind: str


@dataclass(frozen=True)
class GroupEdgeListItem:
    """Denormalized group edge for list rendering — carries group titles."""

    source_id: int
    source_title: str
    target_id: int
    target_title: str
    workspace_id: int
    kind: str


@dataclass(frozen=True)
class TaskListItem:
    """Task fields plus resolved display names, for list rendering without
    extra lookups. Carries names, not full objects."""

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
    tag_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class GroupRef:
    """Group fields plus edge IDs, for list rendering and tree walking without
    fetching full related objects."""

    id: int
    workspace_id: int
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
    tags: tuple[Tag, ...]
    groups: tuple[GroupRef, ...]


# ---- Hydrated types (relationships as full objects) ----


@dataclass(frozen=True)
class TaskDetail:
    """Fully hydrated task view.

    Edge naming convention — `edge_sources` holds *incoming* edges (tasks
    that point to this one; each `ref.task` is the source end of an edge
    whose target is this task). `edge_targets` holds *outgoing* edges (tasks
    this one points to; each `ref.task` is the target end). Read literally:
    "edge_sources" = "source tasks of edges touching me", "edge_targets" =
    "target tasks of edges touching me". Archived endpoints are hidden —
    both queries join on `tasks.archived = 0`.
    """

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
    status: Status
    group: Group | None
    edge_sources: tuple[TaskEdgeRef, ...]
    edge_targets: tuple[TaskEdgeRef, ...]
    history: tuple[JournalEntry, ...]
    tags: tuple[Tag, ...]


@dataclass(frozen=True)
class GroupDetail:
    """Fully hydrated group view.

    Edge naming convention follows `TaskDetail`: `edge_sources` holds
    *incoming* group edges (groups pointing to this one; each `ref.group` is
    the source end). `edge_targets` holds *outgoing* edges (groups this one
    points to; each `ref.group` is the target end). Archived endpoints are
    hidden.
    """

    id: int
    workspace_id: int
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
    edge_sources: tuple[GroupEdgeRef, ...]
    edge_targets: tuple[GroupEdgeRef, ...]


# ---- Preview types ----


@dataclass(frozen=True)
class MoveToWorkspacePreview:
    task_id: int
    task_title: str
    source_workspace_id: int
    target_workspace_id: int
    target_status_id: int
    can_move: bool
    blocking_reason: str | None
    edge_ids: tuple[int, ...]
    is_archived: bool


@dataclass(frozen=True)
class ArchivePreview:
    """Dry-run result for an archive command. Counts reflect additional
    entities beyond the root that *would* be archived."""

    entity_type: Literal["task", "group", "status", "tag", "workspace"]
    entity_name: str
    already_archived: bool
    task_count: int
    group_count: int
    status_count: int


@dataclass(frozen=True)
class EntityUpdatePreview:
    """Dry-run result for a field-level update (task/group edit).
    `before` / `after` contain only fields that differ — unchanged fields
    are omitted. Tag diffs live on `tags_added` / `tags_removed` for tasks;
    other entity kinds leave those empty.

    Note: `before` and `after` are mutable dicts (shallow-frozen). This is
    an intentional exception to the tuple-everywhere convention because
    diff payloads are JSON-consumer-facing and dict shape is the natural
    JSON representation. Callers must treat these fields as read-only.
    """

    entity_type: Literal["task", "group"]
    entity_id: int
    label: str  # task title, group title
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    tags_added: tuple[str, ...] = ()
    tags_removed: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskMovePreview:
    """Dry-run result for `task mv`. Shows from/to status and position."""

    task_id: int
    title: str
    from_status: str
    to_status: str
    from_position: int
    to_position: int
