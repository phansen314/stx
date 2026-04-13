from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from stx import service
from stx.models import Group, Project, Status, Task, Workspace


@dataclass(frozen=True)
class GroupNode:
    group: Group
    tasks: tuple[Task, ...]
    children: tuple[GroupNode, ...]


@dataclass(frozen=True)
class ProjectNode:
    project: Project
    groups: tuple[GroupNode, ...]
    ungrouped_tasks: tuple[Task, ...]


@dataclass(frozen=True)
class WorkspaceModel:
    workspace: Workspace
    statuses: tuple[Status, ...]
    projects: tuple[ProjectNode, ...]
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
    projects = service.list_projects(conn, workspace_id)
    groups = service.list_groups_for_workspace(conn, workspace_id)
    tasks = service.list_tasks(conn, workspace_id)

    # Index tasks by group and project
    tasks_by_group: dict[int, list[Task]] = defaultdict(list)
    tasks_by_project_ungrouped: dict[int, list[Task]] = defaultdict(list)
    unassigned: list[Task] = []

    for task in tasks:
        if task.project_id is None:
            unassigned.append(task)
        elif task.group_id is not None:
            tasks_by_group[task.group_id].append(task)
        else:
            tasks_by_project_ungrouped[task.project_id].append(task)

    # Index groups by project and parent
    groups_by_project: dict[int, list[Group]] = defaultdict(list)
    children_by_parent: dict[int, list[Group]] = defaultdict(list)

    for group in groups:
        groups_by_project[group.project_id].append(group)
        if group.parent_id is not None:
            children_by_parent[group.parent_id].append(group)

    # Build project nodes with group trees
    project_nodes: list[ProjectNode] = []
    for project in projects:
        root_groups = tuple(g for g in groups_by_project.get(project.id, ()) if g.parent_id is None)
        group_trees = tuple(
            _build_group_tree(g, children_by_parent, tasks_by_group) for g in root_groups
        )
        project_nodes.append(
            ProjectNode(
                project=project,
                groups=group_trees,
                ungrouped_tasks=tuple(tasks_by_project_ungrouped.get(project.id, ())),
            )
        )

    return WorkspaceModel(
        workspace=workspace,
        statuses=statuses,
        projects=tuple(project_nodes),
        unassigned_tasks=tuple(unassigned),
        all_tasks=tasks,
    )
