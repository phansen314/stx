"""Export a sticky-notes database to a Markdown report."""

from __future__ import annotations

import datetime
import sqlite3

from . import repository as repo
from . import service
from .formatting import format_group_num, format_task_num, format_timestamp


def _md_escape(value: str) -> str:
    """Escape user-supplied strings for safe inclusion in Markdown table cells."""
    value = value.replace("|", r"\|")
    value = value.replace("`", r"\`")
    value = value.replace("\n", "<br>")
    return value


def _render_columns_section(
    cols: tuple,
    tasks_by_col: dict,
) -> list[str]:
    lines = [
        "### Columns",
        "",
        "| # | Column | Tasks |",
        "|---|--------|-------|",
    ]
    for i, c in enumerate(cols, 1):
        count = len(tasks_by_col.get(c.id, []))
        lines.append(f"| {i} | {_md_escape(c.name)} | {count} |")
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
    cols: tuple,
    tasks_by_col: dict,
    proj_map: dict,
    tag_map: dict,
    task_tag_map: dict,
) -> list[str]:
    lines = ["### Tasks", ""]
    for c in cols:
        col_tasks = tasks_by_col.get(c.id, [])
        if not col_tasks:
            continue
        lines.append(f"#### {_md_escape(c.name)}")
        lines.append("")
        lines.append("| Task | Title | Priority | Project | Tags | Due |")
        lines.append("|------|-------|----------|---------|------|-----|")
        for t in col_tasks:
            task_num = format_task_num(t.id)
            pri = f"P{t.priority}" if t.priority else ""
            proj = _md_escape(proj_map.get(t.project_id, ""))
            task_tags = _md_escape(
                ", ".join(
                    tag_map[tid]
                    for tid in task_tag_map.get(t.id, ())
                    if tid in tag_map
                )
            )
            due = format_timestamp(t.due_date) if t.due_date else ""
            lines.append(
                f"| {task_num} | {_md_escape(t.title)} | {pri} | {proj} | {task_tags} | {due} |"
            )
        lines.append("")
    return lines


def _render_deps_section(
    board_deps: list[tuple[int, int]],
) -> list[str]:
    if not board_deps:
        return []
    lines = [
        "### Dependencies",
        "",
        "```mermaid",
        "graph LR",
    ]
    for tid, did in board_deps:
        lines.append(f"    {format_task_num(tid)} --> {format_task_num(did)}")
    lines += [
        "```",
        "",
        '> Arrow reads "depends on"',
        "",
    ]
    return lines


def export_markdown(conn: sqlite3.Connection) -> str:
    """Return full database export as a Markdown string."""
    lines: list[str] = [
        "# Sticky Notes Export",
        "",
        f"Generated: {datetime.date.today().isoformat()}",
        "",
    ]

    boards = service.list_boards(conn)
    all_deps = service.list_all_dependencies(conn)

    for board in boards:
        bid = board.id
        lines.append(f"## Board: {_md_escape(board.name)}")
        lines.append("")

        cols = service.list_columns(conn, bid)
        tasks = service.list_tasks(conn, bid)
        task_ids = {t.id for t in tasks}
        projects = service.list_projects(conn, bid)
        proj_map = {p.id: p.name for p in projects}
        tags = service.list_tags(conn, bid)
        tag_map = {t.id: t.name for t in tags}
        task_tag_map = repo.batch_tag_ids_by_task(conn, tuple(task_ids))

        tasks_by_col: dict[int, list] = {}
        for t in tasks:
            tasks_by_col.setdefault(t.column_id, []).append(t)

        lines += _render_columns_section(cols, tasks_by_col)
        lines += _render_projects_section(projects, tasks)
        lines += _render_tags_section(tags, task_tag_map)
        lines += _render_groups_section(conn, projects)
        lines += _render_tasks_section(cols, tasks_by_col, proj_map, tag_map, task_tag_map)

        board_deps = [
            (tid, did)
            for tid, did in all_deps
            if tid in task_ids and did in task_ids
        ]
        lines += _render_deps_section(board_deps)

    return "\n".join(lines) + "\n"
