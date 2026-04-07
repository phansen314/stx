from __future__ import annotations

from dataclasses import dataclass

from .models import Group, Project, Status, Tag, Task, TaskHistory, Workspace


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
    project_name: str | None = None
    tag_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class GroupRef:
    """Group fields plus edge IDs, for list rendering and tree walking without
    fetching full related objects."""
    id: int
    project_id: int
    title: str
    parent_id: int | None
    position: int
    archived: bool
    created_at: int
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
    status: Status
    project: Project | None
    group: Group | None
    blocked_by: tuple[Task, ...]
    blocks: tuple[Task, ...]
    history: tuple[TaskHistory, ...]
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


@dataclass(frozen=True)
class GroupDetail:
    id: int
    project_id: int
    title: str
    parent_id: int | None
    position: int
    archived: bool
    created_at: int
    tasks: tuple[Task, ...]
    children: tuple[Group, ...]
    parent: Group | None


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
    dependency_ids: tuple[int, ...]
    is_archived: bool


@dataclass(frozen=True)
class GroupTreeNode:
    group: GroupRef
    children: tuple["GroupTreeNode", ...]


@dataclass(frozen=True)
class ProjectGroupTree:
    project_id: int
    roots: tuple[GroupTreeNode, ...]
    ungrouped_task_count: int
