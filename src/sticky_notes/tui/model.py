from __future__ import annotations

import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass

from sticky_notes import service
from sticky_notes.models import Group, Project, Status, Task, Workspace
from sticky_notes.repository import batch_dependency_ids


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
    blocked_by_map: dict[int, tuple[int, ...]]


def _topo_sort_tasks(
    tasks: tuple[Task, ...],
    blocked_by_map: dict[int, tuple[int, ...]],
) -> tuple[Task, ...]:
    """Topological sort restricted to the given task subset.

    Tasks whose prerequisites appear in the same subset are placed after
    those prerequisites.  Tasks with no dependency relationship keep their
    original relative order (stable sort).
    """
    if len(tasks) <= 1:
        return tasks

    subset_ids = {t.id for t in tasks}
    task_by_id = {t.id: t for t in tasks}

    # Compute in-degree and reverse map restricted to the subset
    in_degree: dict[int, int] = {t.id: 0 for t in tasks}
    dependents: dict[int, list[int]] = defaultdict(list)  # dep_id -> [task_ids that depend on it]

    for t in tasks:
        for dep_id in blocked_by_map.get(t.id, ()):
            if dep_id in subset_ids:
                in_degree[t.id] += 1
                dependents[dep_id].append(t.id)

    # Seed queue with zero in-degree tasks in original order
    queue: deque[int] = deque(t.id for t in tasks if in_degree[t.id] == 0)
    result: list[Task] = []

    while queue:
        tid = queue.popleft()
        result.append(task_by_id[tid])
        for dep_tid in dependents.get(tid, ()):
            in_degree[dep_tid] -= 1
            if in_degree[dep_tid] == 0:
                queue.append(dep_tid)

    return tuple(result)


def _build_group_tree(
    group: Group,
    children_by_parent: dict[int, list[Group]],
    tasks_by_group: dict[int, list[Task]],
    blocked_by_map: dict[int, tuple[int, ...]],
) -> GroupNode:
    children = tuple(
        _build_group_tree(child, children_by_parent, tasks_by_group, blocked_by_map)
        for child in children_by_parent.get(group.id, ())
    )
    tasks = _topo_sort_tasks(
        tuple(tasks_by_group.get(group.id, ())),
        blocked_by_map,
    )
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

    # Load dependency graph
    task_ids = tuple(t.id for t in tasks)
    dep_blocked_by, _ = batch_dependency_ids(conn, task_ids)

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
        root_groups = [
            g for g in groups_by_project.get(project.id, ()) if g.parent_id is None
        ]
        group_trees = tuple(
            _build_group_tree(g, children_by_parent, tasks_by_group, dep_blocked_by)
            for g in root_groups
        )
        project_nodes.append(
            ProjectNode(
                project=project,
                groups=group_trees,
                ungrouped_tasks=_topo_sort_tasks(
                    tuple(tasks_by_project_ungrouped.get(project.id, ())),
                    dep_blocked_by,
                ),
            )
        )

    return WorkspaceModel(
        workspace=workspace,
        statuses=statuses,
        projects=tuple(project_nodes),
        unassigned_tasks=_topo_sort_tasks(tuple(unassigned), dep_blocked_by),
        all_tasks=_topo_sort_tasks(tasks, dep_blocked_by),
        blocked_by_map=dep_blocked_by,
    )
