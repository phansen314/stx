from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .models import Group, JournalEntry, Status, Task, Workspace

# ---- Edge ref types (hydrated edge endpoint with kind) ----


# Polymorphic edge endpoint discriminator. Kept in sync with the
# `CHECK (from_type IN (...))` constraint on the edges table.
type NodeType = Literal["task", "group", "workspace", "status"]


@dataclass(frozen=True)
class EdgeRef:
    """A polymorphic edge endpoint — the far end of an edge, hydrated with
    its type, ID, display title, and the edge kind label."""

    node_type: NodeType
    node_id: int
    node_title: str
    kind: str


# ---- List view types ----


@dataclass(frozen=True)
class EdgeListItem:
    """Denormalized polymorphic edge for list rendering — carries display
    titles for both endpoints."""

    from_type: NodeType
    from_id: int
    from_title: str
    to_type: NodeType
    to_id: int
    to_title: str
    workspace_id: int
    kind: str
    acyclic: bool


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
    archived: bool
    created_at: int
    start_date: int | None
    finish_date: int | None
    group_id: int | None
    metadata: dict[str, str]
    done: bool = False


@dataclass(frozen=True)
class GroupRef:
    """Group fields plus edge IDs, for list rendering and tree walking without
    fetching full related objects."""

    id: int
    workspace_id: int
    title: str
    description: str | None
    parent_id: int | None
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
    archived: bool
    created_at: int
    start_date: int | None
    finish_date: int | None
    group_id: int | None
    metadata: dict[str, str]
    status: Status
    group: Group | None
    edge_sources: tuple[EdgeRef, ...]
    edge_targets: tuple[EdgeRef, ...]
    history: tuple[JournalEntry, ...]
    done: bool = False
    version: int = 0


@dataclass(frozen=True)
class EdgeDetail:
    """Fully hydrated polymorphic edge view. Flat redeclaration of edge
    fields plus hydrated endpoint titles, metadata, and journal history.
    Follows the TaskDetail/GroupDetail pattern — does not inherit from
    EdgeListItem."""

    from_type: NodeType
    from_id: int
    from_title: str
    to_type: NodeType
    to_id: int
    to_title: str
    workspace_id: int
    kind: str
    acyclic: bool
    archived: bool
    metadata: dict[str, str]
    history: tuple[JournalEntry, ...]


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
    archived: bool
    created_at: int
    tasks: tuple[Task, ...]
    children: tuple[Group, ...]
    parent: Group | None
    metadata: dict[str, str]
    edge_sources: tuple[EdgeRef, ...]
    edge_targets: tuple[EdgeRef, ...]
    version: int = 0


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
    edge_endpoints: tuple[tuple[NodeType, int], ...]
    is_archived: bool


@dataclass(frozen=True)
class ArchivePreview:
    """Dry-run result for an archive command. Counts reflect additional
    entities beyond the root that *would* be archived."""

    entity_type: Literal["task", "group", "status", "workspace"]
    entity_name: str
    already_archived: bool
    task_count: int
    group_count: int
    status_count: int


@dataclass(frozen=True)
class EntityUpdatePreview:
    """Dry-run result for a field-level update (task/group edit).
    `before` / `after` contain only fields that differ — unchanged fields
    are omitted.

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


@dataclass(frozen=True)
class TaskMovePreview:
    """Dry-run result for `task mv`. Shows from/to status."""

    task_id: int
    title: str
    from_status: str
    to_status: str


# ---- Next-task view (topological sort of `blocks` DAG) ----


@dataclass(frozen=True)
class BlockedTask:
    """A not-done task whose `blocks`-predecessors are not all done.

    `blocked_by` is guaranteed non-empty — a BlockedTask with no blockers
    is a contradiction and indicates a bug in the caller.
    """

    task: TaskListItem
    blocked_by: tuple[int, ...]  # task ids that are not yet done; always non-empty

    def __post_init__(self) -> None:
        if not self.blocked_by:
            raise ValueError("BlockedTask.blocked_by must be non-empty")


@dataclass(frozen=True)
class NextTasksView:
    """Result of `compute_next_tasks`.

    In default (frontier) mode, `ready` is the set of not-done tasks whose
    blockers are all done, and `blocked` lists the rest with their pending
    blocker task ids.

    In `include_blocked` mode, `ready` is the full topological order of all
    not-done tasks (frontier first) and `blocked` is empty — callers that
    want the gating breakdown should request frontier mode.
    """

    workspace_id: int
    ready: tuple[TaskListItem, ...]
    blocked: tuple[BlockedTask, ...]
