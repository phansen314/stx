from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from time import strftime, gmtime

from .active_board import get_active_board_id, set_active_board_id
from .connection import DEFAULT_DB_PATH, get_connection, init_db
from . import service
from .export import export_markdown
from .models import Board, Column, Project

type CommandHandler = Callable[[sqlite3.Connection, argparse.Namespace, Path], None]


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


def parse_date(raw: str) -> int:
    """YYYY-MM-DD -> Unix epoch int."""
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"invalid date: {raw!r} (expected YYYY-MM-DD)") from None
    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return int(dt.timestamp())


def format_task_num(task_id: int) -> str:
    return f"task-{task_id:04d}"


def format_timestamp(epoch: int) -> str:
    return strftime("%Y-%m-%d", gmtime(epoch))


def format_priority(p: int) -> str:
    return f"[P{p}]"


# ---- Helpers: resolution ----


def _resolve_board(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> Board:
    if args.board:
        return service.get_board_by_name(conn, args.board)
    board_id = get_active_board_id(db_path)
    if board_id is None:
        raise LookupError("no active board — use 'todo board create <name>' or 'todo board use <name>'")
    return service.get_board(conn, board_id)


def _resolve_column(conn: sqlite3.Connection, board_id: int, name: str) -> Column:
    # Try exact match first (fast, direct SQL lookup)
    try:
        return service.get_column_by_name(conn, board_id, name)
    except LookupError:
        pass
    # Fall back to case-insensitive scan for CLI convenience
    cols = service.list_columns(conn, board_id)
    for col in cols:
        if col.name.lower() == name.lower():
            return col
    raise LookupError(f"column {name!r} not found")


def _resolve_project(conn: sqlite3.Connection, board_id: int, name: str) -> Project:
    # Try exact match first (fast, direct SQL lookup)
    try:
        return service.get_project_by_name(conn, board_id, name)
    except LookupError:
        pass
    # Fall back to case-insensitive scan for CLI convenience
    projects = service.list_projects(conn, board_id)
    for proj in projects:
        if proj.name.lower() == name.lower():
            return proj
    raise LookupError(f"project {name!r} not found")


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


# ---- Command handlers ----


def cmd_add(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
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
    print(f"created {format_task_num(task.id)}")


def cmd_ls(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    board = _resolve_board(conn, args, db_path)
    cols = service.list_columns(conn, board.id)
    refs = service.list_task_refs(conn, board.id, include_archived=args.all)
    # Group refs by column_id
    by_col: dict[int, list] = {c.id: [] for c in cols}
    for ref in refs:
        if ref.column_id in by_col:
            by_col[ref.column_id].append(ref)
    # Look up project names
    projects = service.list_projects(conn, board.id, include_archived=True)
    proj_names: dict[int, str] = {p.id: p.name for p in projects}
    for col in cols:
        print(f"\n== {col.name} ==")
        tasks = by_col[col.id]
        if not tasks:
            print("  (empty)")
        else:
            for ref in tasks:
                parts = [f"  {format_task_num(ref.id)}  {format_priority(ref.priority)} {ref.title}"]
                if ref.project_id and ref.project_id in proj_names:
                    parts.append(f"  @{proj_names[ref.project_id]}")
                print("".join(parts))


def cmd_show(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    task_id = _resolve_task(conn, args.task_num, args, db_path)
    detail = service.get_task_detail(conn, task_id)
    print(f"{format_task_num(detail.id)}  {detail.title}")
    print(f"  Column:      {detail.column.name}")
    if detail.project:
        print(f"  Project:     {detail.project.name}")
    print(f"  Priority:    {detail.priority}")
    if detail.due_date:
        print(f"  Due:         {format_timestamp(detail.due_date)}")
    print(f"  Created:     {format_timestamp(detail.created_at)}")
    if detail.blocked_by:
        nums = ", ".join(format_task_num(t.id) for t in detail.blocked_by)
        print(f"  Blocked by:  {nums}")
    if detail.blocks:
        nums = ", ".join(format_task_num(t.id) for t in detail.blocks)
        print(f"  Blocks:      {nums}")
    if detail.description:
        print(f"\n  Description:\n    {detail.description}")
    if detail.history:
        print("\n  History:")
        for h in detail.history:
            old_str = h.old_value if h.old_value is not None else "(none)"
            print(f"    {format_timestamp(h.changed_at)}  {h.field}: {old_str} -> {h.new_value}  ({h.source})")


def cmd_edit(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
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
    if not changes:
        print("nothing to change", file=sys.stderr)
        return
    service.update_task(conn, task_id, changes, source="cli")
    print(f"updated {format_task_num(task_id)}")


def cmd_mv(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    task_id = _resolve_task(conn, args.task_num, args, db_path)
    board = _resolve_board(conn, args, db_path)
    col = _resolve_column(conn, board.id, args.column_name)
    position = args.position if args.position is not None else 0
    service.move_task(conn, task_id, col.id, position, source="cli")
    print(f"moved {format_task_num(task_id)} -> {col.name}")


def cmd_done(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    task_id = _resolve_task(conn, args.task_num, args, db_path)
    board = _resolve_board(conn, args, db_path)
    col = _last_column(conn, board.id)
    service.move_task(conn, task_id, col.id, 0, source="cli")
    print(f"moved {format_task_num(task_id)} -> {col.name}")


def cmd_rm(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    task_id = _resolve_task(conn, args.task_num, args, db_path)
    service.update_task(conn, task_id, {"archived": True}, source="cli")
    print(f"archived {format_task_num(task_id)}")


def cmd_log(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    task_id = _resolve_task(conn, args.task_num, args, db_path)
    # Verify task exists
    service.get_task(conn, task_id)
    history = service.list_task_history(conn, task_id)
    if not history:
        print("no history")
        return
    for h in history:
        old_str = h.old_value if h.old_value is not None else "(none)"
        print(f"{format_timestamp(h.changed_at)}  {h.field}: {old_str} -> {h.new_value}  ({h.source})")


# ---- Board subcommands ----


def cmd_board_create(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    board = service.create_board(conn, args.name)
    set_active_board_id(db_path, board.id)
    print(f"created board {board.name!r} (active)")


def cmd_board_ls(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    boards = service.list_boards(conn, include_archived=args.all)
    active_id = get_active_board_id(db_path)
    if not boards:
        print("no boards")
        return
    for b in boards:
        marker = " *" if b.id == active_id else ""
        archived = " (archived)" if b.archived else ""
        print(f"  {b.name}{marker}{archived}")


def cmd_board_use(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    board = service.get_board_by_name(conn, args.name)
    set_active_board_id(db_path, board.id)
    print(f"switched to board {board.name!r}")


def cmd_board_rename(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    board = _resolve_board(conn, args, db_path)
    service.update_board(conn, board.id, {"name": args.new_name})
    print(f"renamed board -> {args.new_name!r}")


def cmd_board_archive(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    board = _resolve_board(conn, args, db_path)
    service.update_board(conn, board.id, {"archived": True})
    print(f"archived board {board.name!r}")


# ---- Column subcommands ----


def cmd_col_add(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    board = _resolve_board(conn, args, db_path)
    position = args.pos if args.pos is not None else 0
    col = service.create_column(conn, board.id, args.name, position=position)
    print(f"created column {col.name!r}")


def cmd_col_ls(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    board = _resolve_board(conn, args, db_path)
    cols = service.list_columns(conn, board.id)
    if not cols:
        print("no columns")
        return
    for c in cols:
        print(f"  {c.position}  {c.name}")


def cmd_col_rename(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    board = _resolve_board(conn, args, db_path)
    col = _resolve_column(conn, board.id, args.old_name)
    service.update_column(conn, col.id, {"name": args.new_name})
    print(f"renamed column {args.old_name!r} -> {args.new_name!r}")


def cmd_col_archive(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    board = _resolve_board(conn, args, db_path)
    col = _resolve_column(conn, board.id, args.name)
    service.update_column(conn, col.id, {"archived": True})
    print(f"archived column {col.name!r}")


# ---- Project subcommands ----


def cmd_project_create(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    board = _resolve_board(conn, args, db_path)
    proj = service.create_project(conn, board.id, args.name, description=args.desc)
    print(f"created project {proj.name!r}")


def cmd_project_ls(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    board = _resolve_board(conn, args, db_path)
    projects = service.list_projects(conn, board.id)
    if not projects:
        print("no projects")
        return
    for p in projects:
        desc = f"  {p.description}" if p.description else ""
        print(f"  {p.name}{desc}")


def cmd_project_show(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    board = _resolve_board(conn, args, db_path)
    proj = _resolve_project(conn, board.id, args.name)
    detail = service.get_project_detail(conn, proj.id)
    print(f"{detail.name}")
    if detail.description:
        print(f"  {detail.description}")
    print(f"  Tasks: {len(detail.tasks)}")
    for t in detail.tasks:
        print(f"    {format_task_num(t.id)}  {t.title}")


def cmd_project_archive(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    board = _resolve_board(conn, args, db_path)
    proj = _resolve_project(conn, board.id, args.name)
    service.update_project(conn, proj.id, {"archived": True})
    print(f"archived project {proj.name!r}")


# ---- Dependency subcommands ----


def cmd_dep_add(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    task_id = _resolve_task(conn, args.task_num, args, db_path)
    depends_on_id = _resolve_task(conn, args.depends_on_num, args, db_path)
    service.add_dependency(conn, task_id, depends_on_id)
    print(f"{format_task_num(task_id)} now blocked by {format_task_num(depends_on_id)}")


def cmd_dep_rm(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    task_id = _resolve_task(conn, args.task_num, args, db_path)
    depends_on_id = _resolve_task(conn, args.depends_on_num, args, db_path)
    service.remove_dependency(conn, task_id, depends_on_id)
    print(f"removed dependency {format_task_num(task_id)} -> {format_task_num(depends_on_id)}")


# ---- Export ----


def cmd_export(conn: sqlite3.Connection, args: argparse.Namespace, db_path: Path) -> None:
    md = export_markdown(conn)
    if args.output:
        Path(args.output).write_text(md)
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(md)


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
    "export": cmd_export,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="todo", description="Sticky Notes — local kanban CLI")
    parser.add_argument("--db", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--board", "-b", help="board name (overrides active board)")
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

    p_ls = sub.add_parser("ls", help="list tasks")
    p_ls.set_defaults(command="ls")
    p_ls.add_argument("--all", "-a", action="store_true", help="include archived")

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

    p_mv = sub.add_parser("mv", help="move task to column")
    p_mv.set_defaults(command="mv")
    p_mv.add_argument("task_num")
    p_mv.add_argument("column_name")
    p_mv.add_argument("position", type=int, nargs="?", default=None)

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
        HANDLERS[args.command](conn, args, db_path)
    except LookupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except sqlite3.IntegrityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    finally:
        conn.close()
