from __future__ import annotations

import argparse
import dataclasses
import json
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .active_board import active_board_path, clear_active_board_id, get_active_board_id, set_active_board_id
from .connection import DEFAULT_DB_PATH, get_connection, init_db
from . import presenters, service
from .export import export_full_json, export_markdown
from .formatting import format_group_num, format_task_num, parse_date
from .models import Board


# ---- Result type ----


@dataclass(frozen=True)
class Ok:
    """Command result. JSON: {"ok": true, "data": to_dict(data)}"""
    data: object
    text: str


type CmdResult = Ok
type CommandHandler = Callable[[sqlite3.Connection, argparse.Namespace, Path], CmdResult]


# ---- Error types ----


class NoActiveBoardError(LookupError):
    """Raised when no active board is set."""


# ---- JSON serialisation ----


def to_dict(obj: object) -> object:
    """Convert dataclasses (possibly nested) to plain dicts for JSON serialisation.

    Handles StrEnum -> .value, tuples/lists, nested dataclasses, and plain dicts
    with dataclass values. Does *not* use dataclasses.asdict() which recurses
    incorrectly for StrEnum.
    """
    if isinstance(obj, StrEnum):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            f.name: to_dict(getattr(obj, f.name))
            for f in dataclasses.fields(obj)
        }
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_dict(item) for item in obj]
    return obj


# ---- Helpers: resolution ----


def _resolve_board(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> Board:
    """Resolve the active board. Depends on CLI state (active-board file), so it
    stays in the CLI layer rather than the service layer."""
    if args.board:
        return service.get_board_by_name(conn, args.board)
    board_id = get_active_board_id(db_path)
    if board_id is None:
        raise NoActiveBoardError(
            "no active board — use 'todo board create <name>' or 'todo board use <name>'"
        )
    return service.get_board(conn, board_id)


def _resolve_task(
    conn: sqlite3.Connection,
    board: Board,
    raw: str,
    by_title: bool = False,
) -> int:
    return service.resolve_task_id(conn, board.id, raw, by_title=by_title)


# ---- JSON/text output ----


def _emit_json(result: Ok) -> None:
    print(json.dumps({"ok": True, "data": to_dict(result.data)}))


def _json_err(message: str, code: str) -> None:
    print(json.dumps({"ok": False, "error": message, "code": code}), file=sys.stderr)


def _text_err(message: str, code: str) -> None:
    print(f"[{code}] error: {message}", file=sys.stderr)


# ---- Command handlers ----


def cmd_task_create(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    col = service.get_status_by_name(conn, board.id, args.status)
    project_id = service.get_project_by_name(conn, board.id, args.project).id if args.project else None
    due = parse_date(args.due) if args.due else None
    task = service.create_task(
        conn,
        board_id=board.id,
        title=args.title,
        status_id=col.id,
        project_id=project_id,
        description=args.desc,
        priority=args.priority,
        due_date=due,
        tags=tuple(args.tag or ()),
    )
    return Ok(data=task, text=f"created {format_task_num(task.id)}: {task.title}")


def cmd_task_ls(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    status_id = service.get_status_by_name(conn, board.id, args.status).id if args.status else None
    project_id = service.get_project_by_name(conn, board.id, args.project).id if args.project else None
    tag_id = service.get_tag_by_name(conn, board.id, args.tag).id if args.tag else None
    group_id = (
        service.resolve_group(conn, board.id, args.group, project_name=args.project).id
        if args.group else None
    )
    only_archived = getattr(args, "archived", False)
    view = service.get_board_list_view(
        conn, board.id,
        status_id=status_id,
        project_id=project_id,
        tag_id=tag_id,
        group_id=group_id,
        priority=args.priority,
        search=args.search,
        include_archived=args.all,
        only_archived=only_archived,
    )
    return Ok(data=view, text=presenters.format_board_list_view(view))


def cmd_task_show(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    task_id = _resolve_task(conn, board, args.task_num, by_title=args.by_title)
    detail = service.get_task_detail(conn, task_id)
    return Ok(data=detail, text=presenters.format_task_detail(detail))


def cmd_task_edit(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    task_id = _resolve_task(conn, board, args.task_num, by_title=args.by_title)
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
        changes["project_id"] = service.get_project_by_name(conn, board.id, args.project).id
    add_tags = tuple(args.tag or ())
    remove_tags = tuple(args.untag or ())
    updated = service.update_task(
        conn, task_id, changes, source="cli",
        add_tags=add_tags, remove_tags=remove_tags,
    )
    return Ok(data=updated, text=f"updated {format_task_num(task_id)}")


def cmd_task_mv(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    task_id = _resolve_task(conn, board, args.task_num, by_title=args.by_title)
    col = service.get_status_by_name(conn, board.id, args.status)
    position = args.position if args.position is not None else 0
    if args.project:
        project_id = service.get_project_by_name(conn, board.id, args.project).id
        updated = service.move_task(conn, task_id, col.id, position, source="cli", project_id=project_id)
    else:
        updated = service.move_task(conn, task_id, col.id, position, source="cli")
    return Ok(data=updated, text=f"moved {format_task_num(task_id)} -> {col.name}")


def cmd_task_transfer(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    task_id = _resolve_task(conn, board, args.task_num, by_title=args.by_title)
    target_board = service.get_board_by_name(conn, args.target_board)
    target_col = service.get_status_by_name(conn, target_board.id, args.status)
    project_id = (
        service.get_project_by_name(conn, target_board.id, args.project).id
        if args.project else None
    )
    if args.dry_run:
        preview = service.preview_move_to_board(
            conn, task_id, target_board.id, target_col.id, project_id=project_id,
        )
        text = presenters.format_move_preview(preview, target_board.name, target_col.name)
        return Ok(data=preview, text=text)
    new = service.move_task_to_board(
        conn, task_id, target_board.id, target_col.id,
        project_id=project_id, source="cli",
    )
    return Ok(
        data={"task": new, "source_task_id": task_id},
        text=f"transferred {format_task_num(task_id)} -> board '{target_board.name}' / status '{target_col.name}' (new {format_task_num(new.id)})",
    )


def cmd_task_rm(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    task_id = _resolve_task(conn, board, args.task_num, by_title=args.by_title)
    archived = service.update_task(conn, task_id, {"archived": True}, source="cli")
    return Ok(data=archived, text=f"archived {format_task_num(task_id)}")


def cmd_task_log(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    task_id = _resolve_task(conn, board, args.task_num, by_title=args.by_title)
    history = service.list_task_history(conn, task_id)
    return Ok(data=history, text=presenters.format_task_history(history))


# ---- Board subcommands ----


def cmd_board_create(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = service.create_board(conn, args.name)
    set_active_board_id(db_path, board.id)
    if args.statuses:
        for name in [s.strip() for s in args.statuses.split(",") if s.strip()]:
            service.create_status(conn, board.id, name)
    return Ok(data=board, text=f"created board '{board.name}' (active)")


def cmd_board_ls(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    boards = service.list_boards(conn, include_archived=args.all)
    active_id = get_active_board_id(db_path)
    payload = [{**to_dict(b), "active": b.id == active_id} for b in boards]
    return Ok(data=payload, text=presenters.format_board_list(boards, active_id))


def cmd_board_use(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = service.get_board_by_name(conn, args.name)
    set_active_board_id(db_path, board.id)
    return Ok(data=board, text=f"switched to board '{board.name}'")


def cmd_board_rename(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    if args.new_name is not None:
        board = service.get_board_by_name(conn, args.old_or_new_name)
        new_name = args.new_name
    else:
        board = _resolve_board(conn, args, db_path)
        new_name = args.old_or_new_name
    old_name = board.name
    updated = service.update_board(conn, board.id, {"name": new_name})
    return Ok(data=updated, text=f"renamed board '{old_name}' -> '{new_name}'")


def cmd_board_rm(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    if args.name:
        board = service.get_board_by_name(conn, args.name)
    else:
        board = _resolve_board(conn, args, db_path)
    updated = service.update_board(conn, board.id, {"archived": True})
    if get_active_board_id(db_path) == board.id:
        clear_active_board_id(db_path)
    return Ok(data=updated, text=f"archived board '{board.name}'")


# ---- Status subcommands ----


def cmd_status_create(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    col = service.create_status(conn, board.id, args.name)
    return Ok(data=col, text=f"created status '{col.name}'")


def cmd_status_ls(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    statuses = service.list_statuses(conn, board.id)
    return Ok(data=statuses, text=presenters.format_status_list(statuses))


def cmd_status_rename(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    col = service.get_status_by_name(conn, board.id, args.old_name)
    updated = service.update_status(conn, col.id, {"name": args.new_name})
    return Ok(data=updated, text=f"renamed status '{args.old_name}' -> '{args.new_name}'")


def cmd_status_rm(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    col = service.get_status_by_name(conn, board.id, args.name)
    reassign_to_id = None
    if args.reassign_to:
        reassign_col = service.get_status_by_name(conn, board.id, args.reassign_to)
        reassign_to_id = reassign_col.id
    updated = service.archive_status(
        conn, col.id,
        reassign_to_status_id=reassign_to_id,
        force=args.force,
    )
    return Ok(data=updated, text=f"archived status '{col.name}'")


# ---- Project subcommands ----


def cmd_project_create(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    proj = service.create_project(conn, board.id, args.name, description=args.desc)
    return Ok(data=proj, text=f"created project '{proj.name}'")


def cmd_project_ls(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    projects = service.list_projects(conn, board.id)
    return Ok(data=projects, text=presenters.format_project_list(projects))


def cmd_project_show(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    proj = service.get_project_by_name(conn, board.id, args.name)
    detail = service.get_project_detail(conn, proj.id)
    return Ok(data=detail, text=presenters.format_project_detail(detail))


def cmd_project_rm(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    proj = service.get_project_by_name(conn, board.id, args.name)
    updated = service.update_project(conn, proj.id, {"archived": True})
    return Ok(data=updated, text=f"archived project '{proj.name}'")


# ---- Dependency subcommands ----


def cmd_dep_create(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    by_title = args.by_title
    task_id = _resolve_task(conn, board, args.task_num, by_title=by_title)
    depends_on_id = _resolve_task(conn, board, args.depends_on_num, by_title=by_title)
    service.add_dependency(conn, task_id, depends_on_id)
    return Ok(
        data={"task_id": task_id, "depends_on_id": depends_on_id},
        text=f"{format_task_num(task_id)} now blocked by {format_task_num(depends_on_id)}",
    )


def cmd_dep_rm(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    by_title = args.by_title
    task_id = _resolve_task(conn, board, args.task_num, by_title=by_title)
    depends_on_id = _resolve_task(conn, board, args.depends_on_num, by_title=by_title)
    service.remove_dependency(conn, task_id, depends_on_id)
    return Ok(
        data={"task_id": task_id, "depends_on_id": depends_on_id},
        text=f"removed dependency {format_task_num(task_id)} -> {format_task_num(depends_on_id)}",
    )


# ---- Group subcommands ----


def cmd_group_create(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    proj = service.get_project_by_name(conn, board.id, args.project)
    parent_id = None
    if args.parent:
        parent = service.resolve_group(conn, board.id, args.parent, project_name=args.project)
        parent_id = parent.id
    grp = service.create_group(conn, proj.id, args.title, parent_id=parent_id)
    return Ok(data=grp, text=f"created group '{grp.title}' ({format_group_num(grp.id)})")


def cmd_group_ls(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    project_name = args.project
    if project_name:
        projects = (service.get_project_by_name(conn, board.id, project_name),)
    else:
        projects = service.list_projects(conn, board.id)
    if not projects:
        return Ok(data=[], text=presenters.format_group_list(()))
    if args.tree:
        sections: list = []
        for proj in projects:
            tree = service.build_group_tree(conn, proj.id, include_archived=args.all)
            task_ids = _collect_tree_task_ids(tree)
            tasks = service.list_tasks_by_ids(conn, task_ids)
            sections.append((proj, tree, {t.id: t for t in tasks}))
        payload = [tree for _, tree, _ in sections]
        return Ok(data=payload, text=presenters.format_group_trees(tuple(sections)))
    refs_sections = tuple(
        (proj, service.list_groups(conn, proj.id, include_archived=args.all))
        for proj in projects
    )
    all_refs = [r for _, refs in refs_sections for r in refs]
    return Ok(data=all_refs, text=presenters.format_group_list(refs_sections))


def _collect_tree_task_ids(tree) -> tuple[int, ...]:
    def _iter(nodes):
        for n in nodes:
            yield from n.group.task_ids
            yield from _iter(n.children)
    return tuple(_iter(tree.roots))


def cmd_group_show(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    grp = service.resolve_group(conn, board.id, args.title, project_name=args.project)
    detail = service.get_group_detail(conn, grp.id)
    ancestry = service.get_group_ancestry(conn, grp.id)
    ancestry_titles = tuple(g.title for g in ancestry)
    proj = service.get_project(conn, detail.project_id)
    text = presenters.format_group_detail(detail, proj.name, ancestry_titles)
    return Ok(data=detail, text=text)


def cmd_group_rename(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    grp = service.resolve_group(conn, board.id, args.title, project_name=args.project)
    updated = service.update_group(conn, grp.id, {"title": args.new_title})
    return Ok(data=updated, text=f"renamed group '{args.title}' -> '{args.new_title}'")


def cmd_group_rm(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    grp = service.resolve_group(conn, board.id, args.title, project_name=args.project)
    archived = service.archive_group(conn, grp.id, source="cli")
    return Ok(data=archived, text=f"archived group '{grp.title}'")


def cmd_group_mv(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    grp = service.resolve_group(conn, board.id, args.title, project_name=args.project)
    parent_str = args.parent
    if not parent_str:
        updated = service.update_group(conn, grp.id, {"parent_id": None})
        return Ok(data=updated, text=f"promoted group '{grp.title}' to top-level")
    parent = service.resolve_group(conn, board.id, parent_str, project_name=args.project)
    updated = service.update_group(conn, grp.id, {"parent_id": parent.id})
    return Ok(data=updated, text=f"moved group '{grp.title}' under '{parent.title}'")


def cmd_group_assign(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    task_id = _resolve_task(conn, board, args.task, by_title=args.by_title)
    grp = service.resolve_group(conn, board.id, args.group_title, project_name=args.project)
    updated = service.assign_task_to_group(conn, task_id, grp.id, source="cli")
    return Ok(
        data={"task": updated, "group_id": grp.id},
        text=f"assigned {format_task_num(task_id)} to group '{grp.title}'",
    )


def cmd_group_unassign(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    task_id = _resolve_task(conn, board, args.task, by_title=args.by_title)
    # Get the group title before unassigning for the output message
    detail = service.get_task_detail(conn, task_id)
    group_name = detail.group.title if detail.group else None
    updated = service.unassign_task_from_group(conn, task_id, source="cli")
    suffix = f" from group '{group_name}'" if group_name else " from group"
    return Ok(data=updated, text=f"unassigned {format_task_num(task_id)}{suffix}")


# ---- Tag ----


def cmd_tag_create(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    tag = service.create_tag(conn, board.id, args.name)
    return Ok(data=tag, text=f"created tag '{tag.name}'")


def cmd_tag_ls(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    tags = service.list_tags(conn, board.id, include_archived=args.all)
    return Ok(data=tags, text=presenters.format_tag_list(tags))


def cmd_tag_rm(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    tag = service.get_tag_by_name(conn, board.id, args.name)
    archived = service.archive_tag(conn, tag.id, unassign=args.unassign)
    return Ok(data=archived, text=f"archived tag '{tag.name}'")


# ---- Context ----


def cmd_context(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    board = _resolve_board(conn, args, db_path)
    ctx = service.get_board_context(conn, board.id)
    return Ok(data=ctx, text=presenters.format_board_context(ctx))


# ---- Export ----


def cmd_export(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    if args.md:
        content = export_markdown(conn)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content)
            return Ok(
                data={"output_path": str(args.output), "bytes": len(content.encode())},
                text=f"wrote {args.output}",
            )
        return Ok(data={"markdown": content}, text=content)
    else:
        dump = export_full_json(conn)
        content = json.dumps(dump, indent=2)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content)
            return Ok(
                data={"output_path": str(args.output), "bytes": len(content.encode())},
                text=f"wrote {args.output}",
            )
        return Ok(data=dump, text=content)


# ---- Backup ----


def cmd_backup(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    dest = Path(args.dest)
    if dest.exists() and not args.overwrite:
        raise ValueError(f"destination already exists: {dest} (use --overwrite to overwrite)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    target = sqlite3.connect(str(dest))
    try:
        conn.backup(target)
    finally:
        target.close()
    return Ok(
        data={"dest": str(dest), "bytes": dest.stat().st_size},
        text=f"backed up to {dest}",
    )


# ---- Info ----


def cmd_info(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    ab_path = active_board_path(db_path)
    wal = db_path.with_name(db_path.name + "-wal")
    shm = db_path.with_name(db_path.name + "-shm")
    entries = [
        ("database", db_path),
        ("wal sidecar", wal),
        ("shm sidecar", shm),
        ("active-board pointer", ab_path),
    ]
    data = {
        "db": str(db_path),
        "wal": str(wal),
        "shm": str(shm),
        "active_board": str(ab_path),
        "existing": [str(p) for _, p in entries if p.exists()],
        "reset_command": "python scripts/wipe_db.py",
    }
    width = max(len(label) for label, _ in entries)
    lines = ["sticky-notes files:"]
    for label, p in entries:
        marker = "exists" if p.exists() else "missing"
        lines.append(f"  {label:<{width}}  {p}  [{marker}]")
    lines.append("")
    lines.append("To wipe all state: python scripts/wipe_db.py")
    return Ok(data=data, text="\n".join(lines))


# ---- TUI ----


def cmd_tui(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> CmdResult:
    conn.close()
    from sticky_notes.tui import main as tui_main
    tui_argv = ["--db", str(db_path)] if db_path != DEFAULT_DB_PATH else []
    tui_main(tui_argv)
    raise SystemExit(0)


# ---- Parser ----


HANDLERS: dict[str, CommandHandler] = {
    "task_create": cmd_task_create,
    "task_ls": cmd_task_ls,
    "task_show": cmd_task_show,
    "task_edit": cmd_task_edit,
    "task_mv": cmd_task_mv,
    "task_transfer": cmd_task_transfer,
    "task_rm": cmd_task_rm,
    "task_log": cmd_task_log,
    "board_create": cmd_board_create,
    "board_ls": cmd_board_ls,
    "board_use": cmd_board_use,
    "board_rename": cmd_board_rename,
    "board_rm": cmd_board_rm,
    "status_create": cmd_status_create,
    "status_ls": cmd_status_ls,
    "status_rename": cmd_status_rename,
    "status_rm": cmd_status_rm,
    "project_create": cmd_project_create,
    "project_ls": cmd_project_ls,
    "project_show": cmd_project_show,
    "project_rm": cmd_project_rm,
    "dep_create": cmd_dep_create,
    "dep_rm": cmd_dep_rm,
    "group_create": cmd_group_create,
    "group_ls": cmd_group_ls,
    "group_show": cmd_group_show,
    "group_rename": cmd_group_rename,
    "group_rm": cmd_group_rm,
    "group_mv": cmd_group_mv,
    "group_assign": cmd_group_assign,
    "group_unassign": cmd_group_unassign,
    "tag_create": cmd_tag_create,
    "tag_ls": cmd_tag_ls,
    "tag_rm": cmd_tag_rm,
    "context": cmd_context,
    "export": cmd_export,
    "backup": cmd_backup,
    "info": cmd_info,
    "tui": cmd_tui,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="todo", description="Sticky Notes — local kanban CLI")
    parser.add_argument("--db", type=Path, help="path to SQLite database file")
    parser.add_argument("--board", "-b", help="board name (overrides active board)")
    parser.add_argument("--json", action="store_true", help="output JSON instead of text")
    parser.add_argument("--quiet", "-q", action="store_true", help="suppress output on success")
    parser.set_defaults(command=None)

    sub = parser.add_subparsers()

    # ---- Task subcommands ----

    p_task = sub.add_parser("task", help="task management")
    task_sub = p_task.add_subparsers()

    p_create = task_sub.add_parser("create", help="create a task")
    p_create.set_defaults(command="task_create")
    p_create.add_argument("title")
    p_create.add_argument("--desc", "-d", default=None)
    p_create.add_argument("--status", "-S", required=True, help="status name")
    p_create.add_argument("--project", "-p", default=None)
    p_create.add_argument("--priority", "-P", type=int, default=1)
    p_create.add_argument("--due", default=None, help="YYYY-MM-DD")
    p_create.add_argument("--tag", "-t", action="append", default=None, help="tag name (repeatable)")

    p_ls = task_sub.add_parser("ls", help="list tasks")
    p_ls.set_defaults(command="task_ls")
    p_ls.add_argument("--all", "-a", action="store_true", help="include archived")
    p_ls.add_argument("--archived", action="store_true", help="show only archived")
    p_ls.add_argument("--status", "-S", default=None, help="filter by status name")
    p_ls.add_argument("--project", "-p", default=None, help="filter by project name")
    p_ls.add_argument("--priority", "-P", type=int, default=None, help="filter by priority (1-5)")
    p_ls.add_argument("--search", "-s", default=None, help="search title substring")
    p_ls.add_argument("--group", "-g", default=None, help="filter by group title")
    p_ls.add_argument("--tag", "-t", default=None, help="filter by tag name")

    p_show = task_sub.add_parser("show", help="show task detail")
    p_show.set_defaults(command="task_show")
    p_show.add_argument("task_num")
    p_show.add_argument("--by-title", action="store_true", help="resolve task by title string")

    p_edit = task_sub.add_parser("edit", help="edit a task")
    p_edit.set_defaults(command="task_edit")
    p_edit.add_argument("task_num")
    p_edit.add_argument("--by-title", action="store_true", help="resolve task by title string")
    p_edit.add_argument("--title", default=None)
    p_edit.add_argument("--desc", "-d", default=None)
    p_edit.add_argument("--priority", "-P", type=int, default=None)
    p_edit.add_argument("--due", default=None, help="YYYY-MM-DD")
    p_edit.add_argument("--project", "-p", default=None)
    p_edit.add_argument("--tag", "-t", action="append", default=None, help="add tag (repeatable)")
    p_edit.add_argument("--untag", action="append", default=None, help="remove tag (repeatable)")

    p_mv = task_sub.add_parser("mv", help="move task to status (within board)")
    p_mv.set_defaults(command="task_mv")
    p_mv.add_argument("task_num")
    p_mv.add_argument("status", help="status name")
    p_mv.add_argument("position", type=int, nargs="?", default=None)
    p_mv.add_argument("--by-title", action="store_true", help="resolve task by title string")
    p_mv.add_argument("--project", "-p", default=None, help="also change task project")

    p_transfer = task_sub.add_parser("transfer", help="move task to a different board")
    p_transfer.set_defaults(command="task_transfer")
    p_transfer.add_argument("task_num")
    p_transfer.add_argument("--board", dest="target_board", required=True, help="target board name")
    p_transfer.add_argument("--status", "-S", required=True, help="status on target board")
    p_transfer.add_argument("--project", "-p", default=None, help="project on target board")
    p_transfer.add_argument("--dry-run", action="store_true", default=False, help="preview without executing")
    p_transfer.add_argument("--by-title", action="store_true", help="resolve task by title string")

    p_rm = task_sub.add_parser("rm", help="archive a task")
    p_rm.set_defaults(command="task_rm")
    p_rm.add_argument("task_num")
    p_rm.add_argument("--by-title", action="store_true", help="resolve task by title string")

    p_log = task_sub.add_parser("log", help="show task change log")
    p_log.set_defaults(command="task_log")
    p_log.add_argument("task_num")
    p_log.add_argument("--by-title", action="store_true", help="resolve task by title string")

    # ---- Board subcommands ----

    p_board = sub.add_parser("board", help="board management")
    board_sub = p_board.add_subparsers()

    p_bc = board_sub.add_parser("create", help="create a board")
    p_bc.set_defaults(command="board_create")
    p_bc.add_argument("name")
    p_bc.add_argument("--statuses", default=None, help="comma-separated status names to create")

    p_bl = board_sub.add_parser("ls", help="list boards")
    p_bl.set_defaults(command="board_ls")
    p_bl.add_argument("--all", "-a", action="store_true", help="include archived")

    p_bu = board_sub.add_parser("use", help="switch active board")
    p_bu.set_defaults(command="board_use")
    p_bu.add_argument("name")

    p_br = board_sub.add_parser("rename", help="rename a board")
    p_br.set_defaults(command="board_rename")
    p_br.add_argument("old_or_new_name", help="new name (if active board) or old name")
    p_br.add_argument("new_name", nargs="?", default=None, help="new name (when old name provided)")

    p_ba = board_sub.add_parser("rm", help="archive a board")
    p_ba.set_defaults(command="board_rm")
    p_ba.add_argument("name", nargs="?", default=None, help="board name (defaults to active)")

    # ---- Status subcommands ----

    p_status = sub.add_parser("status", help="status management")
    status_sub = p_status.add_subparsers()

    p_ca = status_sub.add_parser("create", help="create a status")
    p_ca.set_defaults(command="status_create")
    p_ca.add_argument("name")

    p_cl = status_sub.add_parser("ls", help="list statuses")
    p_cl.set_defaults(command="status_ls")

    p_cr = status_sub.add_parser("rename", help="rename a status")
    p_cr.set_defaults(command="status_rename")
    p_cr.add_argument("old_name")
    p_cr.add_argument("new_name")

    p_carch = status_sub.add_parser("rm", help="archive a status")
    p_carch.set_defaults(command="status_rm")
    p_carch.add_argument("name")
    p_carch.add_argument("--reassign-to", default=None, metavar="STATUS", help="move tasks to this status")
    p_carch.add_argument("--force", action="store_true", help="archive tasks instead of blocking")

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

    p_pa = proj_sub.add_parser("rm", help="archive a project")
    p_pa.set_defaults(command="project_rm")
    p_pa.add_argument("name")

    # ---- Dependency subcommands ----

    p_dep = sub.add_parser("dep", help="dependency management")
    dep_sub = p_dep.add_subparsers()

    p_da = dep_sub.add_parser("create", help="add a dependency")
    p_da.set_defaults(command="dep_create")
    p_da.add_argument("task_num")
    p_da.add_argument("depends_on_num")
    p_da.add_argument("--by-title", action="store_true", help="resolve tasks by title string")

    p_dr = dep_sub.add_parser("rm", help="remove a dependency")
    p_dr.set_defaults(command="dep_rm")
    p_dr.add_argument("task_num")
    p_dr.add_argument("depends_on_num")
    p_dr.add_argument("--by-title", action="store_true", help="resolve tasks by title string")

    # ---- Group subcommands ----

    p_grp = sub.add_parser("group", help="group management")
    grp_sub = p_grp.add_subparsers()

    p_gc = grp_sub.add_parser("create", help="create a group")
    p_gc.set_defaults(command="group_create")
    p_gc.add_argument("title")
    p_gc.add_argument("--parent", default=None, help="parent group title")
    p_gc.add_argument("--project", "-p", required=True, help="project name")

    p_gl = grp_sub.add_parser("ls", help="list groups")
    p_gl.set_defaults(command="group_ls")
    p_gl.add_argument("--project", "-p", default=None, help="filter by project name")
    p_gl.add_argument("--all", "-a", action="store_true", help="include archived")
    p_gl.add_argument("--tree", action="store_true", help="tree view")

    p_gs = grp_sub.add_parser("show", help="show group detail")
    p_gs.set_defaults(command="group_show")
    p_gs.add_argument("title")
    p_gs.add_argument("--project", "-p", default=None, help="disambiguate by project")

    p_grn = grp_sub.add_parser("rename", help="rename a group")
    p_grn.set_defaults(command="group_rename")
    p_grn.add_argument("title")
    p_grn.add_argument("new_title")
    p_grn.add_argument("--project", "-p", default=None, help="disambiguate by project")

    p_ga = grp_sub.add_parser("rm", help="archive a group")
    p_ga.set_defaults(command="group_rm")
    p_ga.add_argument("title")
    p_ga.add_argument("--project", "-p", default=None, help="disambiguate by project")

    p_gmv = grp_sub.add_parser("mv", help="reparent a group")
    p_gmv.set_defaults(command="group_mv")
    p_gmv.add_argument("title")
    p_gmv.add_argument("--parent", required=True, help="new parent title, or '' to promote to top-level")
    p_gmv.add_argument("--project", "-p", default=None, help="disambiguate by project")

    p_gasn = grp_sub.add_parser("assign", help="assign task to group")
    p_gasn.set_defaults(command="group_assign")
    p_gasn.add_argument("task", help="task number or title")
    p_gasn.add_argument("group_title", help="group title")
    p_gasn.add_argument("--project", "-p", default=None, help="disambiguate by project")
    p_gasn.add_argument("--by-title", action="store_true", help="resolve task by title string")

    p_gun = grp_sub.add_parser("unassign", help="unassign task from group")
    p_gun.set_defaults(command="group_unassign")
    p_gun.add_argument("task", help="task number or title")
    p_gun.add_argument("--by-title", action="store_true", help="resolve task by title string")

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
    p_tr.add_argument("--unassign", action="store_true", help="also remove tag from all tasks")

    # ---- Context ----

    p_ctx = sub.add_parser("context", help="board summary: statuses, tasks, projects, tags, groups")
    p_ctx.set_defaults(command="context")

    # ---- Export ----

    p_export = sub.add_parser("export", help="export database as JSON (default) or markdown (--md)")
    p_export.set_defaults(command="export")
    p_export.add_argument("--md", action="store_true", help="export as markdown instead of JSON")
    p_export.add_argument("-o", "--output", help="write to file instead of stdout")

    # ---- Backup ----

    p_backup = sub.add_parser("backup", help="atomic binary DB snapshot (safe pre-migration backup)")
    p_backup.set_defaults(command="backup")
    p_backup.add_argument("dest", help="destination .db file path")
    p_backup.add_argument("--overwrite", action="store_true", help="overwrite destination if it exists")

    # ---- Info ----

    p_info = sub.add_parser("info", help="show sticky-notes file locations")
    p_info.set_defaults(command="info")

    # ---- TUI ----

    p_tui = sub.add_parser("tui", help="launch interactive TUI")
    p_tui.set_defaults(command="tui")

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
        elif result.text and not args.quiet:
            sys.stdout.write(result.text)
            if not result.text.endswith("\n"):
                sys.stdout.write("\n")
    except KeyboardInterrupt:
        raise SystemExit(130)
    except sqlite3.OperationalError as exc:
        code = "db_error"
        if args.json:
            _json_err(f"database error: {exc}", code)
        else:
            _text_err(f"database error: {exc}", code)
        raise SystemExit(2)
    except NoActiveBoardError as exc:
        code = "missing_active_board"
        if args.json:
            _json_err(str(exc), code)
        else:
            _text_err(str(exc), code)
        raise SystemExit(1)
    except LookupError as exc:
        code = "not_found"
        if args.json:
            _json_err(str(exc), code)
        else:
            _text_err(str(exc), code)
        raise SystemExit(1)
    except ValueError as exc:
        code = "validation"
        if args.json:
            _json_err(str(exc), code)
        else:
            _text_err(str(exc), code)
        raise SystemExit(1)
    finally:
        conn.close()
