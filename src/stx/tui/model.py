from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from stx import service
from stx.models import Group, Status, Task, Workspace


@dataclass(frozen=True)
class GroupNode:
    group: Group
    tasks: tuple[Task, ...]
    children: tuple[GroupNode, ...]


@dataclass(frozen=True)
class WorkspaceModel:
    workspace: Workspace
    statuses: tuple[Status, ...]
    root_groups: tuple[GroupNode, ...]
    unassigned_tasks: tuple[Task, ...]
    all_tasks: tuple[Task, ...]


def flatten_group_tree(nodes: tuple[GroupNode, ...]) -> list[tuple[str, int]]:
    """Flatten a GroupNode tree into (label, id) pairs for a Select widget.

    Labels show ancestry as "Parent > Child > Grandchild" so nested groups
    remain distinguishable in a flat dropdown.
    """
    out: list[tuple[str, int]] = []

    def walk(node: GroupNode, prefix: str) -> None:
        label = f"{prefix} > {node.group.title}" if prefix else node.group.title
        out.append((label, node.group.id))
        for child in node.children:
            walk(child, label)

    for node in nodes:
        walk(node, "")
    return out


def _build_group_tree(
    group: Group,
    children_by_parent: dict[int, list[Group]],
    tasks_by_group: dict[int, list[Task]],
) -> GroupNode:
    children = tuple(
        _build_group_tree(child, children_by_parent, tasks_by_group)
        for child in children_by_parent.get(group.id, ())
    )
    tasks = tuple(tasks_by_group.get(group.id, ()))
    return GroupNode(group=group, tasks=tasks, children=children)


def load_workspace_model(
    conn: sqlite3.Connection,
    workspace_id: int,
) -> WorkspaceModel:
    workspace = service.get_workspace(conn, workspace_id)
    statuses = service.list_statuses(conn, workspace_id)
    groups = service.list_groups_for_workspace(conn, workspace_id)
    tasks = service.list_tasks(conn, workspace_id)

    tasks_by_group: dict[int, list[Task]] = defaultdict(list)
    unassigned: list[Task] = []

    for task in tasks:
        if task.group_id is not None:
            tasks_by_group[task.group_id].append(task)
        else:
            unassigned.append(task)

    children_by_parent: dict[int, list[Group]] = defaultdict(list)
    for group in groups:
        if group.parent_id is not None:
            children_by_parent[group.parent_id].append(group)

    root_groups = tuple(
        _build_group_tree(g, children_by_parent, tasks_by_group)
        for g in groups
        if g.parent_id is None
    )

    return WorkspaceModel(
        workspace=workspace,
        statuses=statuses,
        root_groups=root_groups,
        unassigned_tasks=tuple(unassigned),
        all_tasks=tasks,
    )
