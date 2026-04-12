"""Export an stx database to Markdown or full JSON."""

from __future__ import annotations

import dataclasses
import datetime
import sqlite3
import time

from . import repository as repo
from . import service
from .connection import SCHEMA_VERSION, transaction
from .formatting import format_group_num, format_task_num, format_timestamp


def _md_escape(value: str) -> str:
    """Escape user-supplied strings for safe inclusion in Markdown table cells."""
    value = value.replace("|", r"\|")
    value = value.replace("`", r"\`")
    value = value.replace("\n", "<br>")
    return value


def _render_statuses_section(
    statuses: tuple,
    tasks_by_status: dict,
) -> list[str]:
    lines = [
        "### Statuses",
        "",
        "| # | Status | Tasks |",
        "|---|--------|-------|",
    ]
    for i, s in enumerate(statuses, 1):
        count = len(tasks_by_status.get(s.id, []))
        lines.append(f"| {i} | {_md_escape(s.name)} | {count} |")
    lines.append("")
    return lines


def _render_projects_section(
    projects: tuple,
    tasks: tuple,
) -> list[str]:
    if not projects:
        return []
    proj_task_count: dict[int, int] = {}
    for t in tasks:
        if t.project_id:
            proj_task_count[t.project_id] = proj_task_count.get(t.project_id, 0) + 1
    lines = [
        "### Projects",
        "",
        "| Project | Description | Tasks |",
        "|---------|-------------|-------|",
    ]
    for p in projects:
        desc = _md_escape(p.description or "")
        count = proj_task_count.get(p.id, 0)
        lines.append(f"| {_md_escape(p.name)} | {desc} | {count} |")
    lines.append("")
    return lines


def _render_tags_section(
    tags: tuple,
    task_tag_map: dict,
) -> list[str]:
    if not tags:
        return []
    tag_task_count: dict[int, int] = {}
    for tag_ids in task_tag_map.values():
        for tag_id in tag_ids:
            tag_task_count[tag_id] = tag_task_count.get(tag_id, 0) + 1
    lines = [
        "### Tags",
        "",
        "| Tag | Tasks |",
        "|-----|-------|",
    ]
    for t in tags:
        count = tag_task_count.get(t.id, 0)
        lines.append(f"| {_md_escape(t.name)} | {count} |")
    lines.append("")
    return lines


def _render_groups_section(
    conn: sqlite3.Connection,
    projects: tuple,
) -> list[str]:
    lines: list[str] = []
    has_header = False
    for p in projects:
        group_refs = service.list_groups(conn, p.id)
        if not group_refs:
            continue
        if not has_header:
            lines += ["### Groups", ""]
            has_header = True
        lines.append(f"#### {_md_escape(p.name)}")
        lines.append("")

        group_by_id = {g.id: g for g in group_refs}
        children_map: dict[int | None, list] = {}
        for g in group_refs:
            children_map.setdefault(g.parent_id, []).append(g)
        all_task_ids = tuple(tid for g in group_refs for tid in g.task_ids)
        all_tasks = service.list_tasks_by_ids(conn, all_task_ids)
        task_by_id = {t.id: t for t in all_tasks}

        def _render_group(gid: int, indent: int) -> None:
            g = group_by_id[gid]
            prefix = "  " * indent + "- "
            lines.append(f"{prefix}**{_md_escape(g.title)}** ({format_group_num(g.id)})")
            if g.description:
                lines.append(f"  {'  ' * indent}  {_md_escape(g.description)}")
            for tid in g.task_ids:
                t = task_by_id.get(tid)
                if t:
                    lines.append(
                        f"  {'  ' * indent}- {format_task_num(t.id)}: {_md_escape(t.title)}"
                    )
            for child in children_map.get(gid, []):
                _render_group(child.id, indent + 1)

        for g in children_map.get(None, []):
            _render_group(g.id, 0)

        ungrouped = service.list_ungrouped_task_ids(conn, p.id)
        if ungrouped:
            lines.append(f"  *({len(ungrouped)} ungrouped tasks)*")
        lines.append("")
    return lines


def _render_tasks_section(
    statuses: tuple,
    tasks_by_status: dict,
    proj_map: dict,
    tag_map: dict,
    task_tag_map: dict,
) -> list[str]:
    lines = ["### Tasks", ""]
    for s in statuses:
        col_tasks = tasks_by_status.get(s.id, [])
        if not col_tasks:
            continue
        lines.append(f"#### {_md_escape(s.name)}")
        lines.append("")
        lines.append("| Task | Title | Priority | Project | Tags | Due |")
        lines.append("|------|-------|----------|---------|------|-----|")
        for t in col_tasks:
            task_num = format_task_num(t.id)
            pri = f"P{t.priority}" if t.priority else ""
            proj = _md_escape(proj_map.get(t.project_id, ""))
            task_tags = _md_escape(
                ", ".join(tag_map[tid] for tid in task_tag_map.get(t.id, ()) if tid in tag_map)
            )
            due = format_timestamp(t.due_date) if t.due_date else ""
            lines.append(
                f"| {task_num} | {_md_escape(t.title)} | {pri} | {proj} | {task_tags} | {due} |"
            )
        lines.append("")
    return lines


def _render_descriptions_section(
    tasks: tuple,
) -> list[str]:
    described = [(t.id, t.title, t.description) for t in tasks if t.description]
    if not described:
        return []
    lines = ["### Descriptions", ""]
    for tid, title, desc in described:
        lines.append(f"#### {format_task_num(tid)}: {_md_escape(title)}")
        lines.append("")
        lines.append(desc)
        lines.append("")
    return lines


def _render_task_metadata_section(
    tasks: tuple,
) -> list[str]:
    has_meta = [(t.id, t.title, t.metadata) for t in tasks if t.metadata]
    if not has_meta:
        return []
    lines = ["### Task Metadata", ""]
    for tid, title, meta in has_meta:
        lines.append(f"#### {format_task_num(tid)}: {_md_escape(title)}")
        lines.append("")
        for k, v in sorted(meta.items()):
            lines.append(f"- **{_md_escape(k)}**: {_md_escape(v)}")
        lines.append("")
    return lines


def _render_workspace_metadata_block(workspace) -> list[str]:
    if not workspace.metadata:
        return []
    lines = ["**Metadata:**", ""]
    for k, v in sorted(workspace.metadata.items()):
        lines.append(f"- **{_md_escape(k)}**: {_md_escape(v)}")
    lines.append("")
    return lines


def _render_project_metadata_section(projects: tuple) -> list[str]:
    has_meta = [(p.name, p.metadata) for p in projects if p.metadata]
    if not has_meta:
        return []
    lines = ["### Project Metadata", ""]
    for name, meta in has_meta:
        lines.append(f"#### {_md_escape(name)}")
        lines.append("")
        for k, v in sorted(meta.items()):
            lines.append(f"- **{_md_escape(k)}**: {_md_escape(v)}")
        lines.append("")
    return lines


def _render_group_metadata_section(
    conn: sqlite3.Connection,
    projects: tuple,
) -> list[str]:
    rows: list[tuple[str, str, dict[str, str]]] = []
    for p in projects:
        for g in service.list_groups(conn, p.id):
            if g.metadata:
                rows.append((p.name, g.title, g.metadata))
    if not rows:
        return []
    lines = ["### Group Metadata", ""]
    for proj_name, title, meta in rows:
        lines.append(f"#### {_md_escape(proj_name)} > {_md_escape(title)}")
        lines.append("")
        for k, v in sorted(meta.items()):
            lines.append(f"- **{_md_escape(k)}**: {_md_escape(v)}")
        lines.append("")
    return lines


def _render_deps_section(
    workspace_deps: list[tuple[int, int]],
) -> list[str]:
    if not workspace_deps:
        return []
    lines = [
        "### Dependencies",
        "",
        "```mermaid",
        "graph LR",
    ]
    for tid, did in workspace_deps:
        lines.append(f"    {format_task_num(tid)} --> {format_task_num(did)}")
    lines += [
        "```",
        "",
        '> Arrow reads "depends on"',
        "",
    ]
    return lines


def export_full_json(conn: sqlite3.Connection) -> dict:
    """Return a lossless full-database snapshot as a plain dict ready for json.dumps.

    Includes all rows from every table (archived rows included) with all FK columns
    intact so the dump can be reimported via INSERT statements. Wrapped in a single
    read transaction so the snapshot is consistent even if the TUI is writing concurrently
    (WAL mode lets readers and writers proceed without blocking each other).
    """
    with transaction(conn):
        workspaces = service.list_workspaces(conn, include_archived=True)

        statuses: list[dict] = []
        projects: list[dict] = []
        tasks: list[dict] = []
        tags: list[dict] = []
        groups: list[dict] = []

        for workspace in workspaces:
            bid = workspace.id
            statuses.extend(
                dataclasses.asdict(s)
                for s in service.list_statuses(conn, bid, include_archived=True)
            )
            projects.extend(
                dataclasses.asdict(p)
                for p in service.list_projects(conn, bid, include_archived=True)
            )
            tasks.extend(
                dataclasses.asdict(t) for t in service.list_tasks(conn, bid, include_archived=True)
            )
            tags.extend(
                dataclasses.asdict(t) for t in service.list_tags(conn, bid, include_archived=True)
            )
            groups.extend(
                dataclasses.asdict(g)
                for g in service.list_groups_for_workspace(conn, bid, include_archived=True)
            )

        task_tags = list(repo.list_all_task_tags(conn))
        task_dependencies = list(repo.list_all_task_dependencies(conn))
        journal = [dataclasses.asdict(h) for h in repo.list_all_journal(conn)]

    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": int(time.time()),
        "workspaces": [dataclasses.asdict(w) for w in workspaces],
        "statuses": statuses,
        "projects": projects,
        "tasks": tasks,
        "tags": tags,
        "groups": groups,
        "task_tags": task_tags,
        "task_dependencies": task_dependencies,
        "journal": journal,
    }


def export_markdown(conn: sqlite3.Connection) -> str:
    """Return full database export as a Markdown string."""
    lines: list[str] = [
        "# stx Export",
        "",
        f"Generated: {datetime.date.today().isoformat()}",
        "",
    ]

    workspaces = service.list_workspaces(conn)
    all_deps = service.list_all_dependencies(conn)

    for workspace in workspaces:
        bid = workspace.id
        lines.append(f"## Workspace: {_md_escape(workspace.name)}")
        lines.append("")
        lines += _render_workspace_metadata_block(workspace)

        statuses = service.list_statuses(conn, bid)
        tasks = service.list_tasks(conn, bid)
        task_ids = {t.id for t in tasks}
        projects = service.list_projects(conn, bid)
        proj_map = {p.id: p.name for p in projects}
        tags = service.list_tags(conn, bid)
        tag_map = {t.id: t.name for t in tags}
        task_tag_map = repo.batch_tag_ids_by_task(conn, tuple(task_ids))

        tasks_by_status: dict[int, list] = {}
        for t in tasks:
            tasks_by_status.setdefault(t.status_id, []).append(t)

        lines += _render_statuses_section(statuses, tasks_by_status)
        lines += _render_projects_section(projects, tasks)
        lines += _render_tags_section(tags, task_tag_map)
        lines += _render_groups_section(conn, projects)
        lines += _render_tasks_section(statuses, tasks_by_status, proj_map, tag_map, task_tag_map)
        lines += _render_descriptions_section(tasks)
        lines += _render_project_metadata_section(projects)
        lines += _render_group_metadata_section(conn, projects)
        lines += _render_task_metadata_section(tasks)

        workspace_deps = [
            (tid, did) for tid, did in all_deps if tid in task_ids and did in task_ids
        ]
        lines += _render_deps_section(workspace_deps)

    return "\n".join(lines) + "\n"
