from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .active_board import get_active_board_id, set_active_board_id
from .connection import DEFAULT_DB_PATH, get_connection, init_db
from . import service
from .export import export_markdown
from .formatting import format_group_num, format_priority, format_task_num, format_timestamp, parse_date, to_dict
from .models import Board, Column, Group, Project, TaskFilter


# ---- Result types ----


@dataclass(frozen=True)
class Ok:
    """Mutation result. JSON: {"ok": true, ...data}"""
    data: dict[str, object]
    text: str


@dataclass(frozen=True)
class Data:
    """Query result. JSON: to_dict(payload)"""
    payload: object
    text: str


type CmdResult = Ok | Data
type CommandHandler = Callable[[sqlite3.Connection, argparse.Namespace, Path], CmdResult]


# ---- Helpers: parsing & formatting ----


def parse_task_num(raw: str) -> int:
    """Accept '1', '0001', 'task-0001', '#1'."""
    s = raw.strip().lower()
    if s.startswith("task-"):
        s = s[5:]
    elif s.startswith("#"):
        s = s[1:]
    try:
        n = int(s)
    except ValueError:
        raise ValueError(f"invalid task number: {raw!r}") from None
    if n <= 0:
        raise ValueError(f"invalid task number: {raw!r}")
    return n


# ---- Helpers: resolution ----


def _resolve_board(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> Board:
    if args.board:
        return service.get_board_by_name(conn, args.board)
    board_id = get_active_board_id(db_path)
    if board_id is None:
        raise LookupError("no active board — use 'todo board create <name>' or 'todo board use <name>'")
    return service.get_board(conn, board_id)


def _resolve_column(conn: sqlite3.Connection, board_id: int, name: str) -> Column:
    return service.get_column_by_name(conn, board_id, name)


def _resolve_project(conn: sqlite3.Connection, board_id: int, name: str) -> Project:
    return service.get_project_by_name(conn, board_id, name)


def _first_column(conn: sqlite3.Connection, board_id: int) -> Column:
    cols = service.list_columns(conn, board_id)
    if not cols:
        raise LookupError("board has no columns — use 'todo col add <name>' first")
    return cols[0]


def _last_column(conn: sqlite3.Connection, board_id: int) -> Column:
    cols = service.list_columns(conn, board_id)
    if not cols:
        raise LookupError("board has no columns — use 'todo col add <name>' first")
    return cols[-1]


def _resolve_task(conn: sqlite3.Connection, raw: str, args: argparse.Namespace, db_path: Path) -> int:
    """Resolve a task identifier to its ID. Tries numeric parse first, then title lookup."""
    try:
        return parse_task_num(raw)
    except ValueError:
        pass
    board = _resolve_board(conn, args, db_path)
    return service.get_task_by_title(conn, board.id, raw).id


def _resolve_group(
    conn: sqlite3.Connection,
    board_id: int,
    title: str,
    project_name: str | None = None,
) -> Group:
    """Resolve a group by title. If project_name given, search only that project.
    Otherwise search all projects on the board; error if ambiguous."""
    if project_name is not None:
        proj = _resolve_project(conn, board_id, project_name)
        return service.get_group_by_title(conn, proj.id, title)
    projects = service.list_projects(conn, board_id)
    matches: list[Group] = []
    for proj in projects:
        try:
            grp = service.get_group_by_title(conn, proj.id, title)
            matches.append(grp)
        except LookupError:
            continue
    if not matches:
        raise LookupError(f"group {title!r} not found")
    if len(matches) > 1:
        proj_names = []
        for m in matches:
            p = service.get_project(conn, m.project_id)
            proj_names.append(p.name)
        raise LookupError(
            f"group {title!r} is ambiguous — exists in projects: "
            + ", ".join(repr(n) for n in proj_names)
            + ". Use --project to disambiguate"
        )
    return matches[0]


# ---- JSON output ----


def _emit_json(result: CmdResult) -> None:
    if isinstance(result, Ok):
        print(json.dumps({"ok": True, **{k: to_dict(v) for k, v in result.data.items()}}))
    else:
        print(json.dumps(to_dict(result.payload)))


def _json_err(message: str) -> None:
    print(json.dumps({"ok": False, "error": message}))


# ---- Command handlers ----


def cmd_add(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    if args.col:
        col = _resolve_column(conn, board.id, args.col)
    else:
        col = _first_column(conn, board.id)
    project_id = None
    if args.project:
        project_id = _resolve_project(conn, board.id, args.project).id
    due = parse_date(args.due) if args.due else None
    task = service.create_task(
        conn,
        board_id=board.id,
        title=args.title,
        column_id=col.id,
        project_id=project_id,
        description=args.desc,
        priority=args.priority,
        due_date=due,
    )
    if args.tag:
        for tag_name in args.tag:
            service.tag_task(conn, task.id, tag_name, board.id)
    return Ok(data={"id": task.id}, text=f"created {format_task_num(task.id)}")


def cmd_ls(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    cols = service.list_columns(conn, board.id)
    # Build filter from CLI flags
    column_id = None
    if args.column:
        column_id = _resolve_column(conn, board.id, args.column).id
    project_id = None
    if args.project:
        project_id = _resolve_project(conn, board.id, args.project).id
    priority = args.priority
    search = args.search
    tag_id = None
    if args.tag:
        tag = service.get_tag_by_name(conn, board.id, args.tag)
        tag_id = tag.id
    task_filter = TaskFilter(
        column_id=column_id,
        project_id=project_id,
        priority=priority,
        search=search,
        tag_id=tag_id,
        include_archived=args.all,
    )
    refs = service.list_task_refs_filtered(conn, board.id, task_filter=task_filter)
    # Optional group filter
    group_name = args.group
    if group_name:
        grp = _resolve_group(conn, board.id, group_name, project_name=args.project)
        group_task_ids = set(service.list_task_ids_by_group(conn, grp.id))
        refs = tuple(r for r in refs if r.id in group_task_ids)
    # Group refs by column_id
    by_col: dict[int, list] = {c.id: [] for c in cols}
    for ref in refs:
        if ref.column_id in by_col:
            by_col[ref.column_id].append(ref)
    payload = {
        "board": board.name,
        "columns": [
            {"name": c.name, "id": c.id, "tasks": list(by_col[c.id])}
            for c in cols
        ],
    }
    # Build text output
    projects = service.list_projects(conn, board.id, include_archived=True)
    proj_names: dict[int, str] = {p.id: p.name for p in projects}
    all_tags = service.list_tags(conn, board.id, include_archived=True)
    tag_names: dict[int, str] = {t.id: t.name for t in all_tags}
    lines: list[str] = []
    for col in cols:
        lines.append(f"\n== {col.name} ==")
        tasks = by_col[col.id]
        if not tasks:
            lines.append("  (empty)")
        else:
            for ref in tasks:
                parts = [f"  {format_task_num(ref.id)}  {format_priority(ref.priority)} {ref.title}"]
                if ref.project_id and ref.project_id in proj_names:
                    parts.append(f"  @{proj_names[ref.project_id]}")
                if ref.tag_ids:
                    tag_strs = [tag_names[tid] for tid in ref.tag_ids if tid in tag_names]
                    if tag_strs:
                        parts.append(f"  [{', '.join(tag_strs)}]")
                lines.append("".join(parts))
    return Data(payload=payload, text="\n".join(lines))


def cmd_show(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    task_id = _resolve_task(conn, args.task_num, args, db_path)
    detail = service.get_task_detail(conn, task_id)
    lines = [f"{format_task_num(detail.id)}  {detail.title}"]
    lines.append(f"  Column:      {detail.column.name}")
    if detail.project:
        lines.append(f"  Project:     {detail.project.name}")
    if detail.group_id is not None:
        grp = service.get_group(conn, detail.group_id)
        lines.append(f"  Group:       {grp.title} ({format_group_num(grp.id)})")
    if detail.tags:
        tag_str = ", ".join(t.name for t in detail.tags)
        lines.append(f"  Tags:        {tag_str}")
    lines.append(f"  Priority:    {detail.priority}")
    if detail.due_date:
        lines.append(f"  Due:         {format_timestamp(detail.due_date)}")
    lines.append(f"  Created:     {format_timestamp(detail.created_at)}")
    if detail.blocked_by:
        nums = ", ".join(format_task_num(t.id) for t in detail.blocked_by)
        lines.append(f"  Blocked by:  {nums}")
    if detail.blocks:
        nums = ", ".join(format_task_num(t.id) for t in detail.blocks)
        lines.append(f"  Blocks:      {nums}")
    if detail.description:
        lines.append(f"\n  Description:\n    {detail.description}")
    if detail.history:
        lines.append("\n  History:")
        for h in detail.history:
            old_str = h.old_value if h.old_value is not None else "(none)"
            new_str = h.new_value if h.new_value is not None else "(none)"
            lines.append(f"    {format_timestamp(h.changed_at)}  {h.field}: {old_str} -> {new_str}  ({h.source})")
    return Data(payload=detail, text="\n".join(lines))


def cmd_edit(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    task_id = _resolve_task(conn, args.task_num, args, db_path)
    changes: dict = {}
    if args.title is not None:
        changes["title"] = args.title
    if args.desc is not None:
        changes["description"] = args.desc
    if args.priority is not None:
        changes["priority"] = args.priority
    if args.due is not None:
        changes["due_date"] = parse_date(args.due)
    if args.project is not None:
        board = _resolve_board(conn, args, db_path)
        changes["project_id"] = _resolve_project(conn, board.id, args.project).id
    has_tag_ops = bool(args.tag or args.untag)
    if not changes and not has_tag_ops:
        raise ValueError("nothing to change")
    if changes:
        service.update_task(conn, task_id, changes, source="cli")
    if has_tag_ops:
        board = _resolve_board(conn, args, db_path)
        for tag_name in (args.tag or []):
            service.tag_task(conn, task_id, tag_name, board.id)
        for tag_name in (args.untag or []):
            service.untag_task(conn, task_id, tag_name, board.id)
    return Ok(data={"id": task_id}, text=f"updated {format_task_num(task_id)}")


def cmd_mv(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    task_id = _resolve_task(conn, args.task_num, args, db_path)
    target_board_name = getattr(args, "target_board", None)

    if target_board_name:
        # Cross-board move
        if not args.column_name:
            raise ValueError("column name required when moving to another board")
        target_board = service.get_board_by_name(conn, target_board_name)
        target_col = _resolve_column(conn, target_board.id, args.column_name)
        project_id = None
        if getattr(args, "project", None):
            project_id = _resolve_project(conn, target_board.id, args.project).id

        if getattr(args, "dry_run", False):
            task = service.get_task(conn, task_id)
            blocked_by = service.get_task_ref(conn, task_id).blocked_by_ids
            blocks = service.get_task_ref(conn, task_id).blocks_ids
            has_deps = bool(blocked_by or blocks)
            dep_ids = sorted({*blocked_by, *blocks}) if has_deps else []
            lines = [f"dry-run: would move {format_task_num(task_id)} ({task.title})"]
            lines.append(f'  from board {task.board_id} -> board "{target_board.name}" / column "{target_col.name}"')
            if has_deps:
                lines.append(f"  \u26a0 has dependencies: {', '.join(format_task_num(d) for d in dep_ids)}")
                lines.append("  move would FAIL \u2014 remove dependencies first")
            else:
                lines.append("  no dependencies \u2014 move OK")
            return Data(
                payload={"dry_run": True, "can_move": not has_deps,
                         "task_id": task_id, "target_board": target_board.name,
                         "target_column": target_col.name, "dependency_ids": dep_ids},
                text="\n".join(lines),
            )

        new = service.move_task_to_board(
            conn, task_id, target_board.id, target_col.id,
            project_id=project_id, source="cli",
        )
        return Ok(
            data={"id": task_id, "new_id": new.id},
            text=f'moved {format_task_num(task_id)} -> board "{target_board.name}" / column "{target_col.name}" (new {format_task_num(new.id)})',
        )

    # Within-board move
    project_name = args.project
    if args.column_name:
        board = _resolve_board(conn, args, db_path)
        col = _resolve_column(conn, board.id, args.column_name)
        position = args.position if args.position is not None else 0
        service.move_task(conn, task_id, col.id, position, source="cli")
        if project_name:
            project_id = _resolve_project(conn, board.id, project_name).id
            service.update_task(conn, task_id, {"project_id": project_id}, source="cli")
        return Ok(data={"id": task_id}, text=f"moved {format_task_num(task_id)} -> {col.name}")
    elif project_name:
        board = _resolve_board(conn, args, db_path)
        project_id = _resolve_project(conn, board.id, project_name).id
        service.update_task(conn, task_id, {"project_id": project_id}, source="cli")
        return Ok(data={"id": task_id}, text=f"updated {format_task_num(task_id)} project -> {project_name}")
    else:
        raise ValueError("specify a column, --board, or --project")


def cmd_done(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    task_id = _resolve_task(conn, args.task_num, args, db_path)
    board = _resolve_board(conn, args, db_path)
    col = _last_column(conn, board.id)
    service.move_task(conn, task_id, col.id, 0, source="cli")
    return Ok(data={"id": task_id}, text=f"moved {format_task_num(task_id)} -> {col.name}")


def cmd_rm(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    task_id = _resolve_task(conn, args.task_num, args, db_path)
    service.update_task(conn, task_id, {"archived": True}, source="cli")
    return Ok(data={"id": task_id}, text=f"archived {format_task_num(task_id)}")


def cmd_log(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    task_id = _resolve_task(conn, args.task_num, args, db_path)
    # Verify task exists
    service.get_task(conn, task_id)
    history = service.list_task_history(conn, task_id)
    if not history:
        return Data(payload=history, text="no history")
    lines: list[str] = []
    for h in history:
        old_str = h.old_value if h.old_value is not None else "(none)"
        new_str = h.new_value if h.new_value is not None else "(none)"
        lines.append(f"{format_timestamp(h.changed_at)}  {h.field}: {old_str} -> {new_str}  ({h.source})")
    return Data(payload=history, text="\n".join(lines))


# ---- Board subcommands ----


def cmd_board_create(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = service.create_board(conn, args.name)
    set_active_board_id(db_path, board.id)
    return Ok(data={"id": board.id}, text=f"created board {board.name!r} (active)")


def cmd_board_ls(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    boards = service.list_boards(conn, include_archived=args.all)
    active_id = get_active_board_id(db_path)
    payload = [{**to_dict(b), "active": b.id == active_id} for b in boards]
    if not boards:
        return Data(payload=payload, text="no boards")
    lines: list[str] = []
    for b in boards:
        marker = " *" if b.id == active_id else ""
        archived = " (archived)" if b.archived else ""
        lines.append(f"  {b.name}{marker}{archived}")
    return Data(payload=payload, text="\n".join(lines))


def cmd_board_use(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = service.get_board_by_name(conn, args.name)
    set_active_board_id(db_path, board.id)
    return Ok(data={"id": board.id}, text=f"switched to board {board.name!r}")


def cmd_board_rename(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    service.update_board(conn, board.id, {"name": args.new_name})
    return Ok(data={"id": board.id}, text=f"renamed board -> {args.new_name!r}")


def cmd_board_archive(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    service.update_board(conn, board.id, {"archived": True})
    return Ok(data={"id": board.id}, text=f"archived board {board.name!r}")


# ---- Column subcommands ----


def cmd_col_add(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    position = args.pos if args.pos is not None else 0
    col = service.create_column(conn, board.id, args.name, position=position)
    return Ok(data={"id": col.id}, text=f"created column {col.name!r}")


def cmd_col_ls(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    cols = service.list_columns(conn, board.id)
    if not cols:
        return Data(payload=cols, text="no columns")
    lines = [f"  {c.position}  {c.name}" for c in cols]
    return Data(payload=cols, text="\n".join(lines))


def cmd_col_rename(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    col = _resolve_column(conn, board.id, args.old_name)
    service.update_column(conn, col.id, {"name": args.new_name})
    return Ok(data={"id": col.id}, text=f"renamed column {args.old_name!r} -> {args.new_name!r}")


def cmd_col_archive(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    col = _resolve_column(conn, board.id, args.name)
    service.update_column(conn, col.id, {"archived": True})
    return Ok(data={"id": col.id}, text=f"archived column {col.name!r}")


# ---- Project subcommands ----


def cmd_project_create(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    proj = service.create_project(conn, board.id, args.name, description=args.desc)
    return Ok(data={"id": proj.id}, text=f"created project {proj.name!r}")


def cmd_project_ls(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    projects = service.list_projects(conn, board.id)
    if not projects:
        return Data(payload=projects, text="no projects")
    lines: list[str] = []
    for p in projects:
        desc = f"  {p.description}" if p.description else ""
        lines.append(f"  {p.name}{desc}")
    return Data(payload=projects, text="\n".join(lines))


def cmd_project_show(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    proj = _resolve_project(conn, board.id, args.name)
    detail = service.get_project_detail(conn, proj.id)
    lines = [f"{detail.name}"]
    if detail.description:
        lines.append(f"  {detail.description}")
    lines.append(f"  Tasks: {len(detail.tasks)}")
    for t in detail.tasks:
        lines.append(f"    {format_task_num(t.id)}  {t.title}")
    return Data(payload=detail, text="\n".join(lines))


def cmd_project_archive(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    proj = _resolve_project(conn, board.id, args.name)
    service.update_project(conn, proj.id, {"archived": True})
    return Ok(data={"id": proj.id}, text=f"archived project {proj.name!r}")


# ---- Dependency subcommands ----


def cmd_dep_add(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    task_id = _resolve_task(conn, args.task_num, args, db_path)
    depends_on_id = _resolve_task(conn, args.depends_on_num, args, db_path)
    service.add_dependency(conn, task_id, depends_on_id)
    return Ok(
        data={"task_id": task_id, "depends_on_id": depends_on_id},
        text=f"{format_task_num(task_id)} now blocked by {format_task_num(depends_on_id)}",
    )


def cmd_dep_rm(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    task_id = _resolve_task(conn, args.task_num, args, db_path)
    depends_on_id = _resolve_task(conn, args.depends_on_num, args, db_path)
    service.remove_dependency(conn, task_id, depends_on_id)
    return Ok(
        data={"task_id": task_id, "depends_on_id": depends_on_id},
        text=f"removed dependency {format_task_num(task_id)} -> {format_task_num(depends_on_id)}",
    )


# ---- Group subcommands ----


def cmd_group_create(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    project_name = args.project
    if not project_name:
        raise ValueError("--project is required for group create")
    proj = _resolve_project(conn, board.id, project_name)
    parent_id = None
    if args.parent:
        parent = _resolve_group(conn, board.id, args.parent, project_name=project_name)
        parent_id = parent.id
    grp = service.create_group(conn, proj.id, args.title, parent_id=parent_id)
    return Ok(data={"id": grp.id}, text=f"created group {grp.title!r} ({format_group_num(grp.id)})")


def cmd_group_ls(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    project_name = args.project
    if project_name:
        projects = [_resolve_project(conn, board.id, project_name)]
    else:
        projects = list(service.list_projects(conn, board.id))
    all_refs = []
    for proj in projects:
        refs = service.list_groups(conn, proj.id, include_archived=args.all)
        all_refs.extend(refs)
    if not projects:
        return Data(payload=all_refs, text="no projects")
    tree_mode = args.tree
    include_archived = args.all
    lines: list[str] = []
    for proj in projects:
        refs = service.list_groups(conn, proj.id, include_archived=include_archived)
        if not refs and len(projects) == 1:
            return Data(payload=all_refs, text="no groups")
        if not refs:
            continue
        if len(projects) > 1:
            lines.append(f"\n== {proj.name} ==")
        if tree_mode:
            lines.extend(_format_group_tree(conn, proj.id, refs))
        else:
            for ref in refs:
                archived = " (archived)" if ref.archived else ""
                lines.append(f"  {format_group_num(ref.id)}  {ref.title}  ({len(ref.task_ids)} tasks){archived}")
    return Data(payload=all_refs, text="\n".join(lines))


def _format_group_tree(
    conn: sqlite3.Connection,
    project_id: int,
    refs: tuple,
) -> list[str]:
    lines: list[str] = []
    # Pre-fetch all tasks referenced by any group
    all_task_ids = tuple(tid for ref in refs for tid in ref.task_ids)
    all_tasks = service.list_tasks_by_ids(conn, all_task_ids)
    task_by_id = {t.id: t for t in all_tasks}

    # Build lookup structures
    ref_by_id = {r.id: r for r in refs}
    children_map: dict[int | None, list] = {}
    for ref in refs:
        children_map.setdefault(ref.parent_id, []).append(ref)

    def _format_subtree(group_id: int, prefix: str, is_last: bool) -> None:
        ref = ref_by_id[group_id]
        connector = "+-- " if prefix else ""
        archived = " (archived)" if ref.archived else ""
        lines.append(f"{prefix}{connector}{format_group_num(ref.id)}  {ref.title}{archived}")
        child_prefix = prefix + ("|   " if not is_last and prefix else "    ") if prefix else ""
        children = children_map.get(group_id, [])
        for i, tid in enumerate(ref.task_ids):
            task = task_by_id.get(tid)
            if task is None:
                continue
            item_connector = "+-- " if child_prefix or prefix else "+-- "
            lines.append(f"{child_prefix}{item_connector}{format_task_num(task.id)}: {task.title}")
        for i, child_ref in enumerate(children):
            _format_subtree(child_ref.id, child_prefix, i == len(children) - 1)

    # Top-level groups (parent_id is None)
    top_level = children_map.get(None, [])
    for i, ref in enumerate(top_level):
        _format_subtree(ref.id, "", i == len(top_level) - 1)

    # Ungrouped tasks count
    ungrouped = service.list_ungrouped_task_ids(conn, project_id)
    if ungrouped:
        lines.append(f"\n({len(ungrouped)} ungrouped tasks)")
    return lines


def cmd_group_show(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    project_name = args.project
    grp = _resolve_group(conn, board.id, args.title, project_name=project_name)
    detail = service.get_group_detail(conn, grp.id)
    # Build path
    path_parts = [detail.title]
    current = detail.parent
    while current is not None:
        path_parts.append(current.title)
        p = service.get_group(conn, current.id)
        if p.parent_id is not None:
            current = service.get_group(conn, p.parent_id)
        else:
            current = None
    path_parts.reverse()
    proj = service.get_project(conn, detail.project_id)
    lines = [f"Group: {detail.title} ({format_group_num(detail.id)})"]
    lines.append(f"  Project: {proj.name}")
    lines.append(f"  Path:    {' > '.join(path_parts)}")
    lines.append(f"  Tasks:   {len(detail.tasks)}")
    if detail.children:
        child_names = ", ".join(c.title for c in detail.children)
        lines.append(f"  Sub-groups: {child_names}")
    if detail.tasks:
        lines.append("")
        for t in detail.tasks:
            due = f"  due: {format_timestamp(t.due_date)}" if t.due_date else ""
            lines.append(f"  {format_task_num(t.id)}  {format_priority(t.priority)} {t.title}{due}")
    return Data(payload=detail, text="\n".join(lines))


def cmd_group_rename(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    project_name = args.project
    grp = _resolve_group(conn, board.id, args.title, project_name=project_name)
    service.update_group(conn, grp.id, {"title": args.new_title})
    return Ok(data={"id": grp.id}, text=f"renamed group {args.title!r} -> {args.new_title!r}")


def cmd_group_archive(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    project_name = args.project
    grp = _resolve_group(conn, board.id, args.title, project_name=project_name)
    service.archive_group(conn, grp.id)
    return Ok(data={"id": grp.id}, text=f"archived group {grp.title!r}")


def cmd_group_mv(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    project_name = args.project
    grp = _resolve_group(conn, board.id, args.title, project_name=project_name)
    parent_str = args.parent
    if parent_str.lower() == "none":
        service.update_group(conn, grp.id, {"parent_id": None})
        return Ok(data={"id": grp.id}, text=f"promoted group {grp.title!r} to top-level")
    parent = _resolve_group(conn, board.id, parent_str, project_name=project_name)
    service.update_group(conn, grp.id, {"parent_id": parent.id})
    return Ok(data={"id": grp.id}, text=f"moved group {grp.title!r} under {parent.title!r}")


def cmd_group_assign(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    task_id = _resolve_task(conn, args.task, args, db_path)
    project_name = args.project
    grp = _resolve_group(conn, board.id, args.group_title, project_name=project_name)
    service.assign_task_to_group(conn, task_id, grp.id)
    return Ok(
        data={"task_id": task_id, "group_id": grp.id},
        text=f"assigned {format_task_num(task_id)} to group {grp.title!r}",
    )


def cmd_group_unassign(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    task_id = _resolve_task(conn, args.task, args, db_path)
    service.unassign_task_from_group(conn, task_id)
    return Ok(data={"task_id": task_id}, text=f"unassigned {format_task_num(task_id)} from group")


# ---- Tag ----


def cmd_tag_create(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    tag = service.create_tag(conn, board.id, args.name)
    return Ok(data={"id": tag.id}, text=f"created tag {tag.name!r}")


def cmd_tag_ls(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    tags = service.list_tags(conn, board.id, include_archived=args.all)
    if not tags:
        return Data(payload=tags, text="no tags")
    lines = []
    for t in tags:
        archived = " (archived)" if t.archived else ""
        lines.append(f"  {t.name}{archived}")
    return Data(payload=tags, text="\n".join(lines))


def cmd_tag_rm(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    tag = service.get_tag_by_name(conn, board.id, args.name)
    service.archive_tag(conn, tag.id)
    return Ok(data={"id": tag.id}, text=f"archived tag {tag.name!r}")


# ---- Export ----


def cmd_export(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    md = export_markdown(conn)
    if args.output:
        Path(args.output).write_text(md)
        print(f"Wrote {args.output}", file=sys.stderr)
        return Data(payload={"markdown": md}, text="")
    return Data(payload={"markdown": md}, text=md)


# ---- Parser ----


HANDLERS: dict[str, CommandHandler] = {
    "add": cmd_add,
    "ls": cmd_ls,
    "show": cmd_show,
    "edit": cmd_edit,
    "mv": cmd_mv,
    "done": cmd_done,
    "rm": cmd_rm,
    "log": cmd_log,
    "board_create": cmd_board_create,
    "board_ls": cmd_board_ls,
    "board_use": cmd_board_use,
    "board_rename": cmd_board_rename,
    "board_archive": cmd_board_archive,
    "col_add": cmd_col_add,
    "col_ls": cmd_col_ls,
    "col_rename": cmd_col_rename,
    "col_archive": cmd_col_archive,
    "project_create": cmd_project_create,
    "project_ls": cmd_project_ls,
    "project_show": cmd_project_show,
    "project_archive": cmd_project_archive,
    "dep_add": cmd_dep_add,
    "dep_rm": cmd_dep_rm,
    "group_create": cmd_group_create,
    "group_ls": cmd_group_ls,
    "group_show": cmd_group_show,
    "group_rename": cmd_group_rename,
    "group_archive": cmd_group_archive,
    "group_mv": cmd_group_mv,
    "group_assign": cmd_group_assign,
    "group_unassign": cmd_group_unassign,
    "tag_create": cmd_tag_create,
    "tag_ls": cmd_tag_ls,
    "tag_rm": cmd_tag_rm,
    "export": cmd_export,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="todo", description="Sticky Notes — local kanban CLI")
    parser.add_argument("--db", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--board", "-b", help="board name (overrides active board)")
    parser.add_argument("--json", action="store_true", help="output JSON instead of text")
    parser.set_defaults(command=None)

    sub = parser.add_subparsers()

    # ---- Top-level shortcuts ----

    p_add = sub.add_parser("add", help="add a task")
    p_add.set_defaults(command="add")
    p_add.add_argument("title")
    p_add.add_argument("--desc", "-d", default=None)
    p_add.add_argument("--col", "-c", default=None, help="column name")
    p_add.add_argument("--project", "-p", default=None)
    p_add.add_argument("--priority", type=int, default=1)
    p_add.add_argument("--due", default=None, help="YYYY-MM-DD")
    p_add.add_argument("--tag", "-t", action="append", default=None, help="tag name (repeatable)")

    p_ls = sub.add_parser("ls", help="list tasks")
    p_ls.set_defaults(command="ls")
    p_ls.add_argument("--all", "-a", action="store_true", help="include archived")
    p_ls.add_argument("--column", "-c", default=None, help="filter by column name")
    p_ls.add_argument("--project", "-p", default=None, help="filter by project name")
    p_ls.add_argument("--priority", "-P", type=int, default=None, help="filter by priority (1-5)")
    p_ls.add_argument("--search", "-s", default=None, help="search title substring")
    p_ls.add_argument("--group", "-g", default=None, help="filter by group title")
    p_ls.add_argument("--tag", "-t", default=None, help="filter by tag name")

    p_show = sub.add_parser("show", help="show task detail")
    p_show.set_defaults(command="show")
    p_show.add_argument("task_num")

    p_edit = sub.add_parser("edit", help="edit a task")
    p_edit.set_defaults(command="edit")
    p_edit.add_argument("task_num")
    p_edit.add_argument("--title", default=None)
    p_edit.add_argument("--desc", "-d", default=None)
    p_edit.add_argument("--priority", type=int, default=None)
    p_edit.add_argument("--due", default=None, help="YYYY-MM-DD")
    p_edit.add_argument("--project", "-p", default=None)
    p_edit.add_argument("--tag", "-t", action="append", default=None, help="add tag (repeatable)")
    p_edit.add_argument("--untag", action="append", default=None, help="remove tag (repeatable)")

    p_mv = sub.add_parser("mv", help="move task to column or board")
    p_mv.set_defaults(command="mv")
    p_mv.add_argument("task_num")
    p_mv.add_argument("column_name", nargs="?", default=None, help="column name")
    p_mv.add_argument("position", type=int, nargs="?", default=None)
    p_mv.add_argument("--board", dest="target_board", default=None, help="target board name")
    p_mv.add_argument("--project", "-p", default=None, help="project name on target board")
    p_mv.add_argument("--dry-run", action="store_true", default=False, help="preview move without executing")

    p_done = sub.add_parser("done", help="move task to last column")
    p_done.set_defaults(command="done")
    p_done.add_argument("task_num")

    p_rm = sub.add_parser("rm", help="archive a task")
    p_rm.set_defaults(command="rm")
    p_rm.add_argument("task_num")

    p_log = sub.add_parser("log", help="show task change log")
    p_log.set_defaults(command="log")
    p_log.add_argument("task_num")

    # ---- Board subcommands ----

    p_board = sub.add_parser("board", help="board management")
    board_sub = p_board.add_subparsers()

    p_bc = board_sub.add_parser("create", help="create a board")
    p_bc.set_defaults(command="board_create")
    p_bc.add_argument("name")

    p_bl = board_sub.add_parser("ls", help="list boards")
    p_bl.set_defaults(command="board_ls")
    p_bl.add_argument("--all", "-a", action="store_true", help="include archived")

    p_bu = board_sub.add_parser("use", help="switch active board")
    p_bu.set_defaults(command="board_use")
    p_bu.add_argument("name")

    p_br = board_sub.add_parser("rename", help="rename active board")
    p_br.set_defaults(command="board_rename")
    p_br.add_argument("new_name")

    p_ba = board_sub.add_parser("archive", help="archive active board")
    p_ba.set_defaults(command="board_archive")

    # ---- Column subcommands ----

    p_col = sub.add_parser("col", help="column management")
    col_sub = p_col.add_subparsers()

    p_ca = col_sub.add_parser("add", help="add a column")
    p_ca.set_defaults(command="col_add")
    p_ca.add_argument("name")
    p_ca.add_argument("--pos", type=int, default=None, help="position")

    p_cl = col_sub.add_parser("ls", help="list columns")
    p_cl.set_defaults(command="col_ls")

    p_cr = col_sub.add_parser("rename", help="rename a column")
    p_cr.set_defaults(command="col_rename")
    p_cr.add_argument("old_name")
    p_cr.add_argument("new_name")

    p_carch = col_sub.add_parser("archive", help="archive a column")
    p_carch.set_defaults(command="col_archive")
    p_carch.add_argument("name")

    # ---- Project subcommands ----

    p_proj = sub.add_parser("project", help="project management")
    proj_sub = p_proj.add_subparsers()

    p_pc = proj_sub.add_parser("create", help="create a project")
    p_pc.set_defaults(command="project_create")
    p_pc.add_argument("name")
    p_pc.add_argument("--desc", "-d", default=None)

    p_pl = proj_sub.add_parser("ls", help="list projects")
    p_pl.set_defaults(command="project_ls")

    p_ps = proj_sub.add_parser("show", help="show project detail")
    p_ps.set_defaults(command="project_show")
    p_ps.add_argument("name")

    p_pa = proj_sub.add_parser("archive", help="archive a project")
    p_pa.set_defaults(command="project_archive")
    p_pa.add_argument("name")

    # ---- Dependency subcommands ----

    p_dep = sub.add_parser("dep", help="dependency management")
    dep_sub = p_dep.add_subparsers()

    p_da = dep_sub.add_parser("add", help="add a dependency")
    p_da.set_defaults(command="dep_add")
    p_da.add_argument("task_num")
    p_da.add_argument("depends_on_num")

    p_dr = dep_sub.add_parser("rm", help="remove a dependency")
    p_dr.set_defaults(command="dep_rm")
    p_dr.add_argument("task_num")
    p_dr.add_argument("depends_on_num")

    # ---- Group subcommands ----

    p_grp = sub.add_parser("group", help="group management")
    grp_sub = p_grp.add_subparsers()

    p_gc = grp_sub.add_parser("create", help="create a group")
    p_gc.set_defaults(command="group_create")
    p_gc.add_argument("title")
    p_gc.add_argument("--parent", default=None, help="parent group title")
    p_gc.add_argument("--project", "-p", default=None, help="project name (required)")

    p_gl = grp_sub.add_parser("ls", help="list groups")
    p_gl.set_defaults(command="group_ls")
    p_gl.add_argument("--project", "-p", default=None, help="filter by project name")
    p_gl.add_argument("--all", "-a", action="store_true", help="include archived")
    p_gl.add_argument("--tree", "-t", action="store_true", help="tree view")

    p_gs = grp_sub.add_parser("show", help="show group detail")
    p_gs.set_defaults(command="group_show")
    p_gs.add_argument("title")
    p_gs.add_argument("--project", "-p", default=None, help="disambiguate by project")

    p_grn = grp_sub.add_parser("rename", help="rename a group")
    p_grn.set_defaults(command="group_rename")
    p_grn.add_argument("title")
    p_grn.add_argument("new_title")
    p_grn.add_argument("--project", "-p", default=None, help="disambiguate by project")

    p_ga = grp_sub.add_parser("archive", help="archive a group")
    p_ga.set_defaults(command="group_archive")
    p_ga.add_argument("title")
    p_ga.add_argument("--project", "-p", default=None, help="disambiguate by project")

    p_gmv = grp_sub.add_parser("mv", help="reparent a group")
    p_gmv.set_defaults(command="group_mv")
    p_gmv.add_argument("title")
    p_gmv.add_argument("--parent", required=True, help="new parent title, or 'none'")
    p_gmv.add_argument("--project", "-p", default=None, help="disambiguate by project")

    p_gasn = grp_sub.add_parser("assign", help="assign task to group")
    p_gasn.set_defaults(command="group_assign")
    p_gasn.add_argument("task", help="task number or title")
    p_gasn.add_argument("group_title", help="group title")
    p_gasn.add_argument("--project", "-p", default=None, help="disambiguate by project")

    p_gun = grp_sub.add_parser("unassign", help="unassign task from group")
    p_gun.set_defaults(command="group_unassign")
    p_gun.add_argument("task", help="task number or title")

    # ---- Tag subcommands ----

    p_tag = sub.add_parser("tag", help="tag management")
    tag_sub = p_tag.add_subparsers()

    p_tc = tag_sub.add_parser("create", help="create a tag")
    p_tc.set_defaults(command="tag_create")
    p_tc.add_argument("name")

    p_tl = tag_sub.add_parser("ls", help="list tags")
    p_tl.set_defaults(command="tag_ls")
    p_tl.add_argument("--all", "-a", action="store_true", help="include archived")

    p_tr = tag_sub.add_parser("rm", help="archive a tag")
    p_tr.set_defaults(command="tag_rm")
    p_tr.add_argument("name")

    # ---- Export ----

    p_export = sub.add_parser("export", help="export database to markdown")
    p_export.set_defaults(command="export")
    p_export.add_argument("-o", "--output", help="write to file instead of stdout")

    return parser


# ---- Entry point ----


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        raise SystemExit(0)
    db_path = args.db or DEFAULT_DB_PATH
    conn = get_connection(db_path)
    try:
        init_db(conn)
        result = HANDLERS[args.command](conn, args, db_path)
        if args.json:
            _emit_json(result)
        elif result.text:
            sys.stdout.write(result.text)
            if not result.text.endswith("\n"):
                sys.stdout.write("\n")
    except (LookupError, sqlite3.IntegrityError, ValueError) as exc:
        if args.json:
            _json_err(str(exc))
            raise SystemExit(1)
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    finally:
        conn.close()
