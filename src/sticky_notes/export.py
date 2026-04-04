"""Export a sticky-notes database to a Markdown report."""

from __future__ import annotations

import datetime
import sqlite3

from . import repository as repo
from . import service
from .formatting import format_group_num, format_task_num


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
        lines.append(f"## Board: {board.name}")
        lines.append("")

        cols = service.list_columns(conn, bid)
        tasks = service.list_tasks(conn, bid)
        task_ids = {t.id for t in tasks}
        projects = service.list_projects(conn, bid)
        proj_map = {p.id: p.name for p in projects}
        tags = service.list_tags(conn, bid)
        tag_map = {t.id: t.name for t in tags}
        task_tag_map = repo.batch_tag_ids_by_task(conn, tuple(task_ids))

        # Group tasks by column
        tasks_by_col: dict[int, list] = {}
        for t in tasks:
            tasks_by_col.setdefault(t.column_id, []).append(t)

        # -- Column summary table --
        lines.append("### Columns")
        lines.append("")
        lines.append("| # | Column | Tasks |")
        lines.append("|---|--------|-------|")
        for i, c in enumerate(cols, 1):
            count = len(tasks_by_col.get(c.id, []))
            lines.append(f"| {i} | {c.name} | {count} |")
        lines.append("")

        # -- Projects table --
        if projects:
            proj_task_count: dict[int, int] = {}
            for t in tasks:
                if t.project_id:
                    proj_task_count[t.project_id] = (
                        proj_task_count.get(t.project_id, 0) + 1
                    )
            lines.append("### Projects")
            lines.append("")
            lines.append("| Project | Description | Tasks |")
            lines.append("|---------|-------------|-------|")
            for p in projects:
                desc = p.description or ""
                count = proj_task_count.get(p.id, 0)
                lines.append(f"| {p.name} | {desc} | {count} |")
            lines.append("")

        # -- Tags table --
        if tags:
            tag_task_count: dict[int, int] = {}
            for tid, tag_ids in task_tag_map.items():
                for tag_id in tag_ids:
                    tag_task_count[tag_id] = tag_task_count.get(tag_id, 0) + 1
            lines.append("### Tags")
            lines.append("")
            lines.append("| Tag | Tasks |")
            lines.append("|-----|-------|")
            for t in tags:
                count = tag_task_count.get(t.id, 0)
                lines.append(f"| {t.name} | {count} |")
            lines.append("")

        # -- Groups per project --
        has_groups = False
        for p in projects:
            group_refs = service.list_groups(conn, p.id)
            if not group_refs:
                continue
            if not has_groups:
                lines.append("### Groups")
                lines.append("")
                has_groups = True
            lines.append(f"#### {p.name}")
            lines.append("")

            # Pre-fetch all tasks from refs (task_ids already on GroupRef)
            group_by_id = {g.id: g for g in group_refs}
            children_map: dict[int | None, list] = {}
            for g in group_refs:
                children_map.setdefault(g.parent_id, []).append(g)
            all_task_ids = tuple(
                tid for g in group_refs for tid in g.task_ids
            )
            all_tasks = service.list_tasks_by_ids(conn, all_task_ids)
            task_by_id = {t.id: t for t in all_tasks}

            def _render_group(gid: int, indent: int) -> None:
                g = group_by_id[gid]
                prefix = "  " * indent + "- "
                lines.append(f"{prefix}**{g.title}** ({format_group_num(g.id)})")
                for tid in g.task_ids:
                    t = task_by_id.get(tid)
                    if t:
                        lines.append(f"  {'  ' * indent}- {format_task_num(t.id)}: {t.title}")
                for child in children_map.get(gid, []):
                    _render_group(child.id, indent + 1)

            for g in children_map.get(None, []):
                _render_group(g.id, 0)

            ungrouped = service.list_ungrouped_task_ids(conn, p.id)
            if ungrouped:
                lines.append(f"  *({len(ungrouped)} ungrouped tasks)*")
            lines.append("")

        # -- Tasks grouped by column --
        lines.append("### Tasks")
        lines.append("")
        for c in cols:
            col_tasks = tasks_by_col.get(c.id, [])
            if not col_tasks:
                continue
            lines.append(f"#### {c.name}")
            lines.append("")
            lines.append("| Task | Title | Priority | Project | Tags | Due |")
            lines.append("|------|-------|----------|---------|------|-----|")
            for t in col_tasks:
                task_num = format_task_num(t.id)
                pri = f"P{t.priority}" if t.priority else ""
                proj = proj_map.get(t.project_id, "")
                task_tags = ", ".join(
                    tag_map[tid] for tid in task_tag_map.get(t.id, ()) if tid in tag_map
                )
                due = (
                    datetime.datetime.fromtimestamp(
                        t.due_date, tz=datetime.timezone.utc
                    ).strftime("%Y-%m-%d")
                    if t.due_date
                    else ""
                )
                lines.append(f"| {task_num} | {t.title} | {pri} | {proj} | {task_tags} | {due} |")
            lines.append("")

        # -- Dependencies (Mermaid) --
        board_deps = [
            (tid, did)
            for tid, did in all_deps
            if tid in task_ids and did in task_ids
        ]
        if board_deps:
            lines.append("### Dependencies")
            lines.append("")
            lines.append("```mermaid")
            lines.append("graph LR")
            for tid, did in board_deps:
                lines.append(f"    {format_task_num(tid)} --> {format_task_num(did)}")
            lines.append("```")
            lines.append("")
            lines.append('> Arrow reads "depends on"')
            lines.append("")

    return "\n".join(lines) + "\n"
