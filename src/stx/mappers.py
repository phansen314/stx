from __future__ import annotations

import dataclasses
import json
import sqlite3
from typing import Any

from .models import (
    EntityType,
    Group,
    JournalEntry,
    Status,
    Task,
    Workspace,
)
from .service_models import (
    EdgeDetail,
    EdgeListItem,
    EdgeRef,
    GroupDetail,
    GroupRef,
    TaskDetail,
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
        description=row["description"],
        status_id=row["status_id"],
        priority=row["priority"],
        due_date=row["due_date"],
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
        title=row["title"],
        description=row["description"],
        parent_id=row["parent_id"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
        metadata=json.loads(row["metadata"]),
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


def row_to_edge_list_item(row: Row) -> EdgeListItem:
    return EdgeListItem(
        from_type=row["from_type"],
        from_id=row["from_id"],
        from_title=row["from_title"],
        to_type=row["to_type"],
        to_id=row["to_id"],
        to_title=row["to_title"],
        workspace_id=row["workspace_id"],
        kind=row["kind"],
        acyclic=bool(row["acyclic"]),
    )


def row_to_edge_detail(
    row: Row,
    *,
    history: tuple[JournalEntry, ...],
) -> EdgeDetail:
    return EdgeDetail(
        from_type=row["from_type"],
        from_id=row["from_id"],
        from_title=row["from_title"],
        to_type=row["to_type"],
        to_id=row["to_id"],
        to_title=row["to_title"],
        workspace_id=row["workspace_id"],
        kind=row["kind"],
        acyclic=bool(row["acyclic"]),
        archived=bool(row["archived"]),
        metadata=json.loads(row["metadata"]),
        history=history,
    )


# ---- Utility ----


def shallow_fields(instance: object, cls: type) -> dict[str, Any]:
    if not dataclasses.is_dataclass(cls):
        raise TypeError(f"{cls!r} is not a dataclass")
    if not isinstance(instance, cls):
        raise TypeError(f"{instance!r} is not an instance of {cls!r}")
    return {f.name: getattr(instance, f.name) for f in dataclasses.fields(cls)}


# ---- Domain model -> list / ref ----


def task_to_list_item(task: Task) -> TaskListItem:
    return TaskListItem(**shallow_fields(task, Task))


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
    group: Group | None,
    edge_sources: tuple[EdgeRef, ...],
    edge_targets: tuple[EdgeRef, ...],
    history: tuple[JournalEntry, ...],
) -> TaskDetail:
    return TaskDetail(
        **shallow_fields(task, Task),
        status=status,
        group=group,
        edge_sources=edge_sources,
        edge_targets=edge_targets,
        history=history,
    )


def group_to_detail(
    group: Group,
    *,
    tasks: tuple[Task, ...],
    children: tuple[Group, ...],
    parent: Group | None,
    edge_sources: tuple[EdgeRef, ...],
    edge_targets: tuple[EdgeRef, ...],
) -> GroupDetail:
    return GroupDetail(
        **shallow_fields(group, Group),
        tasks=tasks,
        children=children,
        parent=parent,
        edge_sources=edge_sources,
        edge_targets=edge_targets,
    )
