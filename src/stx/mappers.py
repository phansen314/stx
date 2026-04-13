from __future__ import annotations

import dataclasses
import json
import sqlite3
from typing import Any

from .models import (
    EntityType,
    Group,
    JournalEntry,
    Project,
    Status,
    Tag,
    Task,
    Workspace,
)
from .service_models import (
    GroupDetail,
    GroupEdgeListItem,
    GroupEdgeRef,
    GroupRef,
    ProjectDetail,
    TaskDetail,
    TaskEdgeListItem,
    TaskEdgeRef,
    TaskListItem,
)

type Row = sqlite3.Row


# ---- DB row -> persisted model ----


def row_to_workspace(row: Row) -> Workspace:
    return Workspace(
        id=row["id"],
        name=row["name"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
        metadata=json.loads(row["metadata"]),
    )


def row_to_project(row: Row) -> Project:
    return Project(
        id=row["id"],
        workspace_id=row["workspace_id"],
        name=row["name"],
        description=row["description"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
        metadata=json.loads(row["metadata"]),
    )


def row_to_status(row: Row) -> Status:
    return Status(
        id=row["id"],
        workspace_id=row["workspace_id"],
        name=row["name"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
    )


def row_to_task(row: Row) -> Task:
    return Task(
        id=row["id"],
        workspace_id=row["workspace_id"],
        title=row["title"],
        project_id=row["project_id"],
        description=row["description"],
        status_id=row["status_id"],
        priority=row["priority"],
        due_date=row["due_date"],
        position=row["position"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
        start_date=row["start_date"],
        finish_date=row["finish_date"],
        group_id=row["group_id"],
        metadata=json.loads(row["metadata"]),
    )


def row_to_group(row: Row) -> Group:
    return Group(
        id=row["id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        title=row["title"],
        description=row["description"],
        parent_id=row["parent_id"],
        position=row["position"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
        metadata=json.loads(row["metadata"]),
    )


def row_to_tag(row: Row) -> Tag:
    return Tag(
        id=row["id"],
        workspace_id=row["workspace_id"],
        name=row["name"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
    )


def row_to_journal_entry(row: Row) -> JournalEntry:
    return JournalEntry(
        id=row["id"],
        entity_type=EntityType(row["entity_type"]),
        entity_id=row["entity_id"],
        workspace_id=row["workspace_id"],
        field=row["field"],
        old_value=row["old_value"],
        new_value=row["new_value"],
        source=row["source"],
        changed_at=row["changed_at"],
    )


def row_to_task_edge_list_item(row: Row) -> TaskEdgeListItem:
    return TaskEdgeListItem(
        source_id=row["source_id"],
        source_title=row["source_title"],
        target_id=row["target_id"],
        target_title=row["target_title"],
        workspace_id=row["workspace_id"],
        kind=row["kind"],
    )


def row_to_group_edge_list_item(row: Row) -> GroupEdgeListItem:
    return GroupEdgeListItem(
        source_id=row["source_id"],
        source_title=row["source_title"],
        target_id=row["target_id"],
        target_title=row["target_title"],
        workspace_id=row["workspace_id"],
        kind=row["kind"],
    )


# ---- Utility ----


def shallow_fields(instance: object, cls: type) -> dict[str, Any]:
    if not dataclasses.is_dataclass(cls):
        raise TypeError(f"{cls!r} is not a dataclass")
    if not isinstance(instance, cls):
        raise TypeError(f"{instance!r} is not an instance of {cls!r}")
    return {f.name: getattr(instance, f.name) for f in dataclasses.fields(cls)}


# ---- Domain model -> list / ref ----


def task_to_list_item(
    task: Task,
    *,
    project_name: str | None,
    tag_names: tuple[str, ...],
) -> TaskListItem:
    return TaskListItem(
        **shallow_fields(task, Task),
        project_name=project_name,
        tag_names=tag_names,
    )


def group_to_ref(
    group: Group,
    *,
    task_ids: tuple[int, ...],
    child_ids: tuple[int, ...],
) -> GroupRef:
    return GroupRef(
        **shallow_fields(group, Group),
        task_ids=task_ids,
        child_ids=child_ids,
    )


# ---- Domain model -> hydrated ----


def task_to_detail(
    task: Task,
    *,
    status: Status,
    project: Project | None,
    group: Group | None,
    edge_sources: tuple[TaskEdgeRef, ...],
    edge_targets: tuple[TaskEdgeRef, ...],
    history: tuple[JournalEntry, ...],
    tags: tuple[Tag, ...] = (),
) -> TaskDetail:
    return TaskDetail(
        **shallow_fields(task, Task),
        status=status,
        project=project,
        group=group,
        edge_sources=edge_sources,
        edge_targets=edge_targets,
        history=history,
        tags=tags,
    )


def project_to_detail(
    project: Project,
    *,
    tasks: tuple[Task, ...],
) -> ProjectDetail:
    return ProjectDetail(
        **shallow_fields(project, Project),
        tasks=tasks,
    )


def group_to_detail(
    group: Group,
    *,
    tasks: tuple[Task, ...],
    children: tuple[Group, ...],
    parent: Group | None,
    edge_sources: tuple[GroupEdgeRef, ...],
    edge_targets: tuple[GroupEdgeRef, ...],
) -> GroupDetail:
    return GroupDetail(
        **shallow_fields(group, Group),
        tasks=tasks,
        children=children,
        parent=parent,
        edge_sources=edge_sources,
        edge_targets=edge_targets,
    )
