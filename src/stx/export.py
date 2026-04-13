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


def _render_groups_section(
    conn: sqlite3.Connection,
    workspace_id: int,
) -> list[str]:
    all_refs = service.list_groups_for_workspace(conn, workspace_id)
    if not all_refs:
        return []

    group_by_id = {g.id: g for g in all_refs}
    children_map: dict[int | None, list] = {}
    for g in all_refs:
        children_map.setdefault(g.parent_id, []).append(g)

    # Build group_id → task list from workspace tasks
    all_tasks_flat = service.list_tasks(conn, workspace_id, include_archived=True)
    task_by_id = {t.id: t for t in all_tasks_flat}
    task_ids_by_group: dict[int, list[int]] = {}
    for t in all_tasks_flat:
        if t.group_id is not None:
            task_ids_by_group.setdefault(t.group_id, []).append(t.id)

    lines: list[str] = ["### Groups", ""]

    def _render_group(gid: int, indent: int) -> None:
        g = group_by_id[gid]
        prefix = "  " * indent + "- "
        lines.append(f"{prefix}**{_md_escape(g.title)}** ({format_group_num(g.id)})")
        if g.description:
            lines.append(f"  {'  ' * indent}  {_md_escape(g.description)}")
        for tid in task_ids_by_group.get(gid, []):
            t = task_by_id.get(tid)
            if t:
                lines.append(
                    f"  {'  ' * indent}- {format_task_num(t.id)}: {_md_escape(t.title)}"
                )
        for child in children_map.get(gid, []):
            _render_group(child.id, indent + 1)

    for g in children_map.get(None, []):
        _render_group(g.id, 0)

    lines.append("")
    return lines


def _render_tasks_section(
    statuses: tuple,
    tasks_by_status: dict,
) -> list[str]:
    lines = ["### Tasks", ""]
    for s in statuses:
        col_tasks = tasks_by_status.get(s.id, [])
        if not col_tasks:
            continue
        lines.append(f"#### {_md_escape(s.name)}")
        lines.append("")
        lines.append("| Task | Title | Priority | Due |")
        lines.append("|------|-------|----------|-----|")
        for t in col_tasks:
            task_num = format_task_num(t.id)
            pri = f"P{t.priority}" if t.priority else ""
            due = format_timestamp(t.due_date) if t.due_date else ""
            lines.append(
                f"| {task_num} | {_md_escape(t.title)} | {pri} | {due} |"
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


def _render_group_metadata_section(
    conn: sqlite3.Connection,
    workspace_id: int,
) -> list[str]:
    rows: list[tuple[str, dict[str, str]]] = []
    for g in service.list_groups_for_workspace(conn, workspace_id):
        if g.metadata:
            rows.append((g.title, g.metadata))
    if not rows:
        return []
    lines = ["### Group Metadata", ""]
    for title, meta in rows:
        lines.append(f"#### {_md_escape(title)}")
        lines.append("")
        for k, v in sorted(meta.items()):
            lines.append(f"- **{_md_escape(k)}**: {_md_escape(v)}")
        lines.append("")
    return lines


def _render_edges_section(
    edge_rows: list[dict],
    task_ids: set[int],
    group_ids: set[int],
    workspace_ids: set[int],
) -> list[str]:
    """Render active edges whose both endpoints belong to this workspace export."""

    def _in_scope(node_type: str, node_id: int) -> bool:
        if node_type == "task":
            return node_id in task_ids
        elif node_type == "group":
            return node_id in group_ids
        elif node_type == "workspace":
            return node_id in workspace_ids
        return False

    def _node_label(node_type: str, node_id: int) -> str:
        if node_type == "task":
            return format_task_num(node_id)
        elif node_type == "group":
            return format_group_num(node_id)
        else:
            return f"ws{node_id}"

    active = [
        r for r in edge_rows
        if not r["archived"]
        and _in_scope(r["from_type"], r["from_id"])
        and _in_scope(r["to_type"], r["to_id"])
    ]
    if not active:
        return []
    lines = [
        "### Edges",
        "",
        "```mermaid",
        "graph LR",
    ]
    for r in active:
        src = _node_label(r["from_type"], r["from_id"])
        tgt = _node_label(r["to_type"], r["to_id"])
        lines.append(f"    {src} -->|{r['kind']}| {tgt}")
    lines += [
        "```",
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
        tasks: list[dict] = []
        groups: list[dict] = []

        for workspace in workspaces:
            bid = workspace.id
            statuses.extend(
                dataclasses.asdict(s)
                for s in service.list_statuses(conn, bid, include_archived=True)
            )
            tasks.extend(
                dataclasses.asdict(t) for t in service.list_tasks(conn, bid, include_archived=True)
            )
            groups.extend(
                dataclasses.asdict(g)
                for g in service.list_groups_for_workspace(conn, bid, include_archived=True)
            )

        edges = list(repo.list_all_edge_rows(conn))
        journal = [dataclasses.asdict(h) for h in repo.list_all_journal(conn)]

    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": int(time.time()),
        "workspaces": [dataclasses.asdict(w) for w in workspaces],
        "statuses": statuses,
        "tasks": tasks,
        "groups": groups,
        "edges": edges,
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
    all_edge_rows = list(repo.list_all_edge_rows(conn))

    for workspace in workspaces:
        bid = workspace.id
        lines.append(f"## Workspace: {_md_escape(workspace.name)}")
        lines.append("")
        lines += _render_workspace_metadata_block(workspace)

        statuses = service.list_statuses(conn, bid)
        tasks = service.list_tasks(conn, bid)
        task_ids = {t.id for t in tasks}
        groups = service.list_groups_for_workspace(conn, bid)
        group_ids = {g.id for g in groups}

        tasks_by_status: dict[int, list] = {}
        for t in tasks:
            tasks_by_status.setdefault(t.status_id, []).append(t)

        lines += _render_statuses_section(statuses, tasks_by_status)
        lines += _render_groups_section(conn, bid)
        lines += _render_tasks_section(statuses, tasks_by_status)
        lines += _render_descriptions_section(tasks)
        lines += _render_group_metadata_section(conn, bid)
        lines += _render_task_metadata_section(tasks)
        lines += _render_edges_section(all_edge_rows, task_ids, group_ids, {bid})

    return "\n".join(lines) + "\n"
