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
from typing import Any

from .active_workspace import active_workspace_path, clear_active_workspace_id, get_active_workspace_id, set_active_workspace_id
from .connection import DEFAULT_DB_PATH, get_connection, init_db
from . import presenters, service
from .export import export_full_json, export_markdown
from .formatting import format_group_num, format_task_num, parse_date
from .models import Workspace
from .service_models import ArchivePreview


EXIT_DB_ERROR = 2
EXIT_NOT_FOUND = 3
EXIT_VALIDATION = 4
EXIT_NO_ACTIVE_WS = 5


# ---- Result type ----


@dataclass(frozen=True)
class Ok:
    """Command result. JSON: {"ok": true, "data": to_dict(data)}"""
    data: object
    text: str


type CmdResult = Ok


@dataclass(frozen=True)
class RunContext:
    """Per-invocation CLI context threaded through every handler."""
    db_path: Path
    config_path: Path


type CommandHandler = Callable[[sqlite3.Connection, argparse.Namespace, RunContext], CmdResult]


# ---- Error types ----


class NoActiveWorkspaceError(Exception):
    """Raised when no active workspace is set.

    Intentionally not a LookupError subclass — generic except LookupError
    sites elsewhere should not swallow this control-flow signal.
    """


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


def _resolve_workspace(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> Workspace:
    """Resolve the active workspace from --workspace flag or tui.toml (with legacy file fallback).
    Stays in the CLI layer rather than the service layer."""
    if args.workspace:
        return service.get_workspace_by_name(conn, args.workspace)
    workspace_id = get_active_workspace_id(ctx.config_path, ctx.db_path)
    if workspace_id is None:
        raise NoActiveWorkspaceError(
            "no active workspace — use 'todo workspace create <name>' or 'todo workspace use <name>'"
        )
    return service.get_workspace(conn, workspace_id)


def _resolve_task(
    conn: sqlite3.Connection,
    workspace: Workspace,
    raw: str,
) -> int:
    return service.resolve_task_id(conn, workspace.id, raw)


# ---- JSON/text output ----


def _stdout_is_tty() -> bool:
    return sys.stdout.isatty()


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _emit_json(result: Ok) -> None:
    print(json.dumps({"ok": True, "data": to_dict(result.data)}))


def _json_err(message: str, code: str) -> None:
    print(json.dumps({"ok": False, "error": message, "code": code}), file=sys.stderr)


def _text_err(message: str, code: str) -> None:
    print(f"[{code}] error: {message}", file=sys.stderr)


def _confirm_archive(preview: ArchivePreview, *, auto_confirm: bool = False) -> bool:
    if auto_confirm:
        return True
    if not _stdin_is_tty():
        raise ValueError(
            "non-interactive stdin — pass --force to skip confirmation or --dry-run to preview"
        )
    print(presenters.format_archive_preview(preview), file=sys.stderr)
    answer = input("proceed? [y/N] ")
    return answer.strip().lower() in ("y", "yes")


# ---- Command handlers ----


def cmd_task_create(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    col = service.get_status_by_name(conn, workspace.id, args.status)
    project_id = service.get_project_by_name(conn, workspace.id, args.project).id if args.project else None
    group_id = None
    if args.group:
        grp = service.resolve_group(conn, workspace.id, args.group, project_name=args.project)
        group_id = grp.id
        if project_id is None:
            project_id = grp.project_id
    due = parse_date(args.due) if args.due else None
    task = service.create_task(
        conn,
        workspace_id=workspace.id,
        title=args.title,
        status_id=col.id,
        project_id=project_id,
        description=(args.desc or "").strip() or None,
        priority=args.priority,
        due_date=due,
        group_id=group_id,
        tags=tuple(args.tag or ()),
    )
    detail = service.get_task_detail(conn, task.id)
    return Ok(data=detail, text=f"created {format_task_num(task.id)}: {task.title}")


def cmd_task_ls(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    status_id = service.get_status_by_name(conn, workspace.id, args.status).id if args.status else None
    project_id = service.get_project_by_name(conn, workspace.id, args.project).id if args.project else None
    tag_id = service.get_tag_by_name(conn, workspace.id, args.tag).id if args.tag else None
    group_id = (
        service.resolve_group(conn, workspace.id, args.group, project_name=args.project).id
        if args.group else None
    )
    include_archived = args.archived in ("include", "only")
    only_archived = args.archived == "only"
    view = service.get_workspace_list_view(
        conn, workspace.id,
        status_id=status_id,
        project_id=project_id,
        tag_id=tag_id,
        group_id=group_id,
        priority=args.priority,
        search=args.search,
        include_archived=include_archived,
        only_archived=only_archived,
    )
    data = [
        {"status": to_dict(col.status), "tasks": [to_dict(t) for t in col.tasks]}
        for col in view.statuses
    ]
    return Ok(data=data, text=presenters.format_workspace_list_view(view))


def cmd_task_show(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    detail = service.get_task_detail(conn, task_id)
    return Ok(data=detail, text=presenters.format_task_detail(detail))


def cmd_task_edit(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    changes: dict = {}
    if args.title is not None:
        changes["title"] = args.title
    if args.desc is not None:
        changes["description"] = args.desc.strip() or None
    if args.priority is not None:
        changes["priority"] = args.priority
    if args.due is not None:
        changes["due_date"] = parse_date(args.due)
    if args.project is not None:
        changes["project_id"] = service.get_project_by_name(conn, workspace.id, args.project).id
    add_tags = tuple(args.tag or ())
    remove_tags = tuple(args.untag or ())
    if not changes and not add_tags and not remove_tags:
        detail = service.get_task_detail(conn, task_id)
        return Ok(data=detail, text="nothing to update")
    if args.dry_run:
        preview = service.preview_update_task(
            conn, task_id, changes, add_tags=add_tags, remove_tags=remove_tags,
        )
        return Ok(data=preview, text=presenters.format_entity_update_preview(preview))
    service.update_task(
        conn, task_id, changes, source="cli",
        add_tags=add_tags, remove_tags=remove_tags,
    )
    detail = service.get_task_detail(conn, task_id)
    return Ok(data=detail, text=f"updated {format_task_num(task_id)}")


def cmd_task_mv(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    col = service.get_status_by_name(conn, workspace.id, args.status)
    position = args.position if args.position is not None else 0
    change_project = args.project is not None
    project_id = (
        service.get_project_by_name(conn, workspace.id, args.project).id
        if change_project else None
    )
    pre = service.get_task_detail(conn, task_id)
    from_status = pre.status.name
    if args.dry_run:
        preview = service.preview_move_task(
            conn, task_id, col.id, position,
            project_id=project_id, change_project=change_project,
        )
        return Ok(data=preview, text=presenters.format_task_move_preview(preview))
    if change_project:
        service.move_task(conn, task_id, col.id, position, source="cli", project_id=project_id)
    else:
        service.move_task(conn, task_id, col.id, position, source="cli")
    detail = service.get_task_detail(conn, task_id)
    return Ok(data=detail, text=f"moved {format_task_num(task_id)}: {from_status} -> {col.name}")


def cmd_task_transfer(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    target_workspace = service.get_workspace_by_name(conn, args.to_workspace)
    target_col = service.get_status_by_name(conn, target_workspace.id, args.status)
    target_project = (
        service.get_project_by_name(conn, target_workspace.id, args.project)
        if args.project else None
    )
    project_id = target_project.id if target_project else None
    if args.dry_run:
        preview = service.preview_move_to_workspace(
            conn, task_id, target_workspace.id, target_col.id, project_id=project_id,
        )
        text = presenters.format_move_preview(
            preview, target_workspace.name, target_col.name,
            source_workspace_name=workspace.name,
            target_project_name=target_project.name if target_project else None,
        )
        return Ok(data=preview, text=text)
    new = service.move_task_to_workspace(
        conn, task_id, target_workspace.id, target_col.id,
        project_id=project_id, source="cli",
    )
    detail = service.get_task_detail(conn, new.id)
    return Ok(
        data={"task": detail, "source_task_id": task_id},
        text=f"transferred {format_task_num(task_id)} -> workspace '{target_workspace.name}' / status '{target_col.name}' (new {format_task_num(new.id)})",
    )


def cmd_task_archive(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    if args.dry_run:
        preview = service.preview_archive_task(conn, task_id)
        return Ok(data=preview, text="dry-run: " + presenters.format_archive_preview(preview))
    if not args.force:
        preview = service.preview_archive_task(conn, task_id)
        if not _confirm_archive(preview):
            return Ok(data=None, text="aborted")
    service.archive_task(conn, task_id, source="cli")
    detail = service.get_task_detail(conn, task_id)
    return Ok(data=detail, text=f"archived {format_task_num(task_id)}")


def cmd_task_log(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    history = service.list_task_history(conn, task_id)
    return Ok(data=history, text=presenters.format_task_history(history))


# ---- Workspace subcommands ----


def cmd_workspace_create(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = service.create_workspace(conn, args.name)
    set_active_workspace_id(ctx.config_path, workspace.id)
    if args.statuses:
        for name in [s.strip() for s in args.statuses.split(",") if s.strip()]:
            service.create_status(conn, workspace.id, name)
    return Ok(data=workspace, text=f"created workspace '{workspace.name}' (active)")


def cmd_workspace_ls(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    include_archived = args.archived in ("include", "only")
    only_archived = args.archived == "only"
    workspaces = service.list_workspaces(
        conn, include_archived=include_archived, only_archived=only_archived,
    )
    active_id = get_active_workspace_id(ctx.config_path, ctx.db_path)
    payload = [{**to_dict(w), "active": w.id == active_id} for w in workspaces]
    return Ok(data=payload, text=presenters.format_workspace_list(workspaces, active_id))


def cmd_workspace_use(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = service.get_workspace_by_name(conn, args.name)
    set_active_workspace_id(ctx.config_path, workspace.id)
    return Ok(data=workspace, text=f"switched to workspace '{workspace.name}'")


def cmd_workspace_rename(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = service.get_workspace_by_name(conn, args.old_name)
    updated = service.update_workspace(conn, workspace.id, {"name": args.new_name})
    return Ok(data=updated, text=f"renamed workspace '{args.old_name}' -> '{args.new_name}'")


def cmd_workspace_archive(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    if args.name:
        workspace = service.get_workspace_by_name(conn, args.name)
    else:
        workspace = _resolve_workspace(conn, args, ctx)
    if args.dry_run:
        preview = service.preview_archive_workspace(conn, workspace.id)
        return Ok(data=preview, text="dry-run: " + presenters.format_archive_preview(preview))
    if not args.force:
        preview = service.preview_archive_workspace(conn, workspace.id)
        if not _confirm_archive(preview):
            return Ok(data=None, text="aborted")
    archived = service.cascade_archive_workspace(conn, workspace.id, source="cli")
    was_active = get_active_workspace_id(ctx.config_path, ctx.db_path) == workspace.id
    if was_active:
        clear_active_workspace_id(ctx.config_path)
    suffix = " (active pointer cleared)" if was_active else ""
    return Ok(
        data={"workspace": archived, "active_cleared": was_active},
        text=f"archived workspace '{workspace.name}' and all descendants{suffix}",
    )


# ---- Status subcommands ----


def cmd_status_create(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    col = service.create_status(conn, workspace.id, args.name)
    return Ok(data=col, text=f"created status '{col.name}'")


def cmd_status_ls(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    include_archived = args.archived in ("include", "only")
    only_archived = args.archived == "only"
    statuses = service.list_statuses(
        conn, workspace.id, include_archived=include_archived, only_archived=only_archived,
    )
    return Ok(data=statuses, text=presenters.format_status_list(statuses))


def cmd_status_rename(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    col = service.get_status_by_name(conn, workspace.id, args.old_name)
    updated = service.update_status(conn, col.id, {"name": args.new_name})
    return Ok(data=updated, text=f"renamed status '{args.old_name}' -> '{args.new_name}'")


def cmd_status_order(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    from .tui.config import load_config, save_config

    workspace = _resolve_workspace(conn, args, ctx)
    seen: set[str] = set()
    statuses: list[dict[str, Any]] = []
    for name in args.statuses:
        key = name.lower()
        if key in seen:
            raise ValueError(f"duplicate status in order: {name!r}")
        seen.add(key)
        status = service.get_status_by_name(conn, workspace.id, name)
        statuses.append({"id": status.id, "name": name})
    config = load_config(ctx.config_path)
    config.status_order[workspace.id] = [s["id"] for s in statuses]
    save_config(config, ctx.config_path)
    return Ok(
        data={
            "workspace_id": workspace.id,
            "statuses": statuses,
        },
        text=f"set status order for workspace '{workspace.name}': {', '.join(args.statuses)}",
    )


def cmd_status_archive(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    col = service.get_status_by_name(conn, workspace.id, args.name)
    if args.dry_run:
        preview = service.preview_archive_status(conn, col.id)
        return Ok(data=preview, text="dry-run: " + presenters.format_archive_preview(preview))
    # No confirmation prompt: --force means "archive tasks, just do it";
    # --reassign-to means "move tasks, no data loss". Without either flag the
    # service layer blocks on active tasks, so no side-effects to confirm.
    reassign_to_id = None
    if args.reassign_to:
        reassign_col = service.get_status_by_name(conn, workspace.id, args.reassign_to)
        reassign_to_id = reassign_col.id
    updated = service.archive_status(
        conn, col.id,
        reassign_to_status_id=reassign_to_id,
        force=args.force,
    )
    return Ok(data=updated, text=f"archived status '{col.name}'")


# ---- Project subcommands ----


def cmd_project_create(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    description = (args.desc or "").strip() or None
    proj = service.create_project(conn, workspace.id, args.name, description=description)
    return Ok(data=proj, text=f"created project '{proj.name}'")


def cmd_project_ls(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    include_archived = args.archived in ("include", "only")
    only_archived = args.archived == "only"
    projects = service.list_projects(
        conn, workspace.id, include_archived=include_archived, only_archived=only_archived,
    )
    return Ok(data=projects, text=presenters.format_project_list(projects))


def cmd_project_show(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    proj = service.get_project_by_name(conn, workspace.id, args.name)
    detail = service.get_project_detail(conn, proj.id)
    return Ok(data=detail, text=presenters.format_project_detail(detail))


def cmd_project_edit(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    proj = service.get_project_by_name(conn, workspace.id, args.name)
    changes: dict[str, Any] = {}
    if args.desc is not None:
        changes["description"] = args.desc.strip() or None
    if args.dry_run:
        preview = service.preview_update_project(conn, proj.id, changes)
        return Ok(data=preview, text=presenters.format_entity_update_preview(preview))
    if not changes:
        return Ok(data=proj, text="nothing to update")
    updated = service.update_project(conn, proj.id, changes)
    return Ok(data=updated, text=f"updated project '{updated.name}'")


def cmd_project_rename(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    proj = service.get_project_by_name(conn, workspace.id, args.old_name)
    updated = service.update_project(conn, proj.id, {"name": args.new_name})
    return Ok(data=updated, text=f"renamed project '{args.old_name}' -> '{args.new_name}'")


def cmd_project_archive(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    proj = service.get_project_by_name(conn, workspace.id, args.name)
    if args.dry_run:
        preview = service.preview_archive_project(conn, proj.id)
        return Ok(data=preview, text="dry-run: " + presenters.format_archive_preview(preview))
    if not args.force:
        preview = service.preview_archive_project(conn, proj.id)
        if not _confirm_archive(preview):
            return Ok(data=None, text="aborted")
    archived = service.cascade_archive_project(conn, proj.id, source="cli")
    return Ok(data=archived, text=f"archived project '{proj.name}' and all descendants")


# ---- Dependency subcommands ----


def cmd_dep_create(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    depends_on_id = _resolve_task(conn, workspace, args.blocked_by)
    service.add_dependency(conn, task_id, depends_on_id)
    blocked = service.get_task(conn, task_id)
    blocking = service.get_task(conn, depends_on_id)
    return Ok(
        data={
            "blocked_task_id": task_id,
            "blocked_task_title": blocked.title,
            "blocking_task_id": depends_on_id,
            "blocking_task_title": blocking.title,
        },
        text=f"{format_task_num(task_id)} now blocked by {format_task_num(depends_on_id)}",
    )


def cmd_dep_archive(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    depends_on_id = _resolve_task(conn, workspace, args.blocked_by)
    service.archive_dependency(conn, task_id, depends_on_id)
    blocked = service.get_task(conn, task_id)
    blocking = service.get_task(conn, depends_on_id)
    return Ok(
        data={
            "blocked_task_id": task_id,
            "blocked_task_title": blocked.title,
            "blocking_task_id": depends_on_id,
            "blocking_task_title": blocking.title,
        },
        text=f"archived dependency {format_task_num(task_id)} -> {format_task_num(depends_on_id)}",
    )


# ---- Group dependency subcommands ----


def cmd_group_dep_create(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.group, project_name=args.project)
    dep = service.resolve_group(conn, workspace.id, args.blocked_by, project_name=args.project)
    service.add_group_dependency(conn, grp.id, dep.id)
    return Ok(
        data={
            "blocked_group_id": grp.id,
            "blocked_group_title": grp.title,
            "blocking_group_id": dep.id,
            "blocking_group_title": dep.title,
        },
        text=f"group '{grp.title}' now blocked by '{dep.title}'",
    )


def cmd_group_dep_archive(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.group, project_name=args.project)
    dep = service.resolve_group(conn, workspace.id, args.blocked_by, project_name=args.project)
    service.archive_group_dependency(conn, grp.id, dep.id)
    return Ok(
        data={
            "blocked_group_id": grp.id,
            "blocked_group_title": grp.title,
            "blocking_group_id": dep.id,
            "blocking_group_title": dep.title,
        },
        text=f"archived dependency '{grp.title}' -> '{dep.title}'",
    )


# ---- Group subcommands ----


def cmd_group_create(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    proj = service.get_project_by_name(conn, workspace.id, args.project)
    parent_id = None
    if args.parent:
        parent = service.resolve_group(conn, workspace.id, args.parent, project_name=args.project)
        parent_id = parent.id
    description = (args.desc or "").strip() or None
    grp = service.create_group(conn, proj.id, args.title, parent_id=parent_id, description=description)
    return Ok(data=grp, text=f"created group '{grp.title}' ({format_group_num(grp.id)})")


def cmd_group_ls(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    project_name = args.project
    if project_name:
        projects = (service.get_project_by_name(conn, workspace.id, project_name),)
    else:
        projects = service.list_projects(conn, workspace.id)
    if not projects:
        return Ok(data=[], text=presenters.format_group_list(()))
    include_archived = args.archived in ("include", "only")
    only_archived = args.archived == "only"
    refs_sections = tuple(
        (
            proj,
            service.list_groups(
                conn, proj.id,
                include_archived=include_archived,
                only_archived=only_archived,
            ),
        )
        for proj in projects
    )
    payload = [{**to_dict(r), "project_name": proj.name} for proj, refs in refs_sections for r in refs]
    return Ok(data=payload, text=presenters.format_group_list(refs_sections))


def cmd_group_show(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.title, project_name=args.project)
    detail = service.get_group_detail(conn, grp.id)
    ancestry = service.get_group_ancestry(conn, grp.id)
    ancestry_titles = tuple(g.title for g in ancestry)
    proj = service.get_project(conn, detail.project_id)
    text = presenters.format_group_detail(detail, proj.name, ancestry_titles)
    return Ok(data=detail, text=text)


def cmd_group_rename(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.old_title, project_name=args.project)
    changes = {"title": args.new_title}
    if args.dry_run:
        preview = service.preview_update_group(conn, grp.id, changes)
        return Ok(data=preview, text=presenters.format_entity_update_preview(preview))
    updated = service.update_group(conn, grp.id, changes)
    return Ok(data=updated, text=f"renamed group '{args.old_title}' -> '{args.new_title}'")


def cmd_group_edit(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.title, project_name=args.project)
    changes: dict[str, Any] = {}
    if args.desc is not None:
        changes["description"] = args.desc.strip() or None
    if args.dry_run:
        preview = service.preview_update_group(conn, grp.id, changes)
        return Ok(data=preview, text=presenters.format_entity_update_preview(preview))
    if not changes:
        return Ok(data=grp, text="nothing to update")
    updated = service.update_group(conn, grp.id, changes)
    return Ok(data=updated, text=f"updated group '{updated.title}'")


def cmd_group_archive(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.title, project_name=args.project)
    if args.dry_run:
        preview = service.preview_archive_group(conn, grp.id)
        return Ok(data=preview, text="dry-run: " + presenters.format_archive_preview(preview))
    if not args.force:
        preview = service.preview_archive_group(conn, grp.id)
        if not _confirm_archive(preview):
            return Ok(data=None, text="aborted")
    archived = service.cascade_archive_group(conn, grp.id, source="cli")
    return Ok(data=archived, text=f"archived group '{grp.title}' and all descendants")


def cmd_group_mv(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.title, project_name=args.project)
    if args.to_top:
        changes: dict[str, Any] = {"parent_id": None}
    else:
        parent = service.resolve_group(conn, workspace.id, args.parent, project_name=args.project)
        changes = {"parent_id": parent.id}
    if args.dry_run:
        preview = service.preview_update_group(conn, grp.id, changes)
        return Ok(data=preview, text=presenters.format_entity_update_preview(preview))
    updated = service.update_group(conn, grp.id, changes)
    if args.to_top:
        return Ok(data=updated, text=f"promoted group '{grp.title}' to top-level")
    parent_title = (
        service.get_group(conn, changes["parent_id"]).title if changes["parent_id"] is not None else None
    )
    return Ok(data=updated, text=f"moved group '{grp.title}' under '{parent_title}'")


def cmd_group_assign(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    grp = service.resolve_group(conn, workspace.id, args.title, project_name=args.project)
    service.assign_task_to_group(conn, task_id, grp.id, source="cli")
    detail = service.get_task_detail(conn, task_id)
    return Ok(
        data=detail,
        text=f"assigned {format_task_num(task_id)} to group '{grp.title}'",
    )


def cmd_group_unassign(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    # Get the group title before unassigning for the output message
    detail = service.get_task_detail(conn, task_id)
    group_name = detail.group.title if detail.group else None
    service.unassign_task_from_group(conn, task_id, source="cli")
    detail = service.get_task_detail(conn, task_id)
    suffix = f" from group '{group_name}'" if group_name else " from group"
    return Ok(data=detail, text=f"unassigned {format_task_num(task_id)}{suffix}")


# ---- Tag ----


def cmd_tag_create(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    tag = service.create_tag(conn, workspace.id, args.name)
    return Ok(data=tag, text=f"created tag '{tag.name}'")


def cmd_tag_rename(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    tag = service.get_tag_by_name(conn, workspace.id, args.old_name)
    updated = service.update_tag(conn, tag.id, {"name": args.new_name})
    return Ok(data=updated, text=f"renamed tag '{args.old_name}' -> '{args.new_name}'")


def cmd_tag_ls(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    include_archived = args.archived in ("include", "only")
    only_archived = args.archived == "only"
    tags = service.list_tags(
        conn, workspace.id, include_archived=include_archived, only_archived=only_archived,
    )
    return Ok(data=tags, text=presenters.format_tag_list(tags))


def cmd_tag_archive(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    tag = service.get_tag_by_name(conn, workspace.id, args.name)
    if args.dry_run:
        preview = service.preview_archive_tag(conn, tag.id)
        return Ok(data=preview, text="dry-run: " + presenters.format_archive_preview(preview))
    if not args.force:
        preview = service.preview_archive_tag(conn, tag.id)
        if not _confirm_archive(preview):
            return Ok(data=None, text="aborted")
    archived = service.archive_tag(conn, tag.id, unassign=args.unassign)
    return Ok(data=archived, text=f"archived tag '{tag.name}'")


# ---- Context ----


def cmd_workspace_show(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    if args.name:
        workspace = service.get_workspace_by_name(conn, args.name)
    else:
        workspace = _resolve_workspace(conn, args, ctx)
    ctx = service.get_workspace_context(conn, workspace.id)
    return Ok(data=ctx, text=presenters.format_workspace_context(ctx))


# ---- Export ----


def cmd_export(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    if args.md:
        content = export_markdown(conn)
        if args.output:
            output_path = _prepare_export_output(Path(args.output), args.overwrite)
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
            output_path = _prepare_export_output(Path(args.output), args.overwrite)
            output_path.write_text(content)
            return Ok(
                data={"output_path": str(args.output), "bytes": len(content.encode())},
                text=f"wrote {args.output}",
            )
        return Ok(data=dump, text=content)


def _prepare_export_output(output_path: Path, overwrite: bool) -> Path:
    if output_path.exists() and not overwrite:
        raise ValueError(f"destination already exists: {output_path} (use --overwrite to overwrite)")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


# ---- Backup ----


def cmd_backup(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
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


def cmd_info(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    ab_path = active_workspace_path(ctx.db_path)
    wal = ctx.db_path.with_name(ctx.db_path.name + "-wal")
    shm = ctx.db_path.with_name(ctx.db_path.name + "-shm")
    entries = [
        ("db", "database", ctx.db_path),
        ("wal", "wal sidecar", wal),
        ("shm", "shm sidecar", shm),
        ("active_workspace", "active-workspace pointer", ab_path),
    ]
    data = {key: {"path": str(p), "exists": p.exists()} for key, _, p in entries}
    width = max(len(label) for _, label, _ in entries)
    lines = ["sticky-notes files:"]
    for _, label, p in entries:
        marker = "exists" if p.exists() else "missing"
        lines.append(f"  {label:<{width}}  {p}  [{marker}]")
    return Ok(data=data, text="\n".join(lines))


# ---- TUI ----


# ---- Metadata helpers (shared across entity types) ----


def _meta_records(metadata: dict[str, str]) -> list[dict[str, str]]:
    return [{"key": k, "value": v} for k, v in sorted(metadata.items())]


# ---- Task metadata ----


def cmd_task_meta_ls(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    task = service.get_task(conn, task_id)
    records = _meta_records(task.metadata)
    text = presenters.format_metadata_block(task.metadata, indent=2) or "no metadata"
    return Ok(data=records, text=text)


def cmd_task_meta_get(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    value = service.get_task_meta(conn, task_id, args.key)
    key = args.key.lower()
    return Ok(data={"key": key, "value": value}, text=value)


def cmd_task_meta_set(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    service.set_task_meta(conn, task_id, args.key, args.value)
    key = args.key.lower()
    return Ok(data={"key": key, "value": args.value}, text=f"set {key}={args.value} on task {format_task_num(task_id)}")


def cmd_task_meta_del(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    removed = service.remove_task_meta(conn, task_id, args.key)
    key = args.key.lower()
    return Ok(data={"key": key, "value": removed}, text=f"removed {key} from task {format_task_num(task_id)}")


# ---- Workspace metadata ----


def cmd_workspace_meta_ls(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    records = _meta_records(workspace.metadata)
    text = presenters.format_metadata_block(workspace.metadata, indent=2) or "no metadata"
    return Ok(data=records, text=text)


def cmd_workspace_meta_get(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    value = service.get_workspace_meta(conn, workspace.id, args.key)
    key = args.key.lower()
    return Ok(data={"key": key, "value": value}, text=value)


def cmd_workspace_meta_set(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    service.set_workspace_meta(conn, workspace.id, args.key, args.value)
    key = args.key.lower()
    return Ok(data={"key": key, "value": args.value}, text=f"set {key}={args.value} on workspace '{workspace.name}'")


def cmd_workspace_meta_del(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    removed = service.remove_workspace_meta(conn, workspace.id, args.key)
    key = args.key.lower()
    return Ok(data={"key": key, "value": removed}, text=f"removed {key} from workspace '{workspace.name}'")


# ---- Project metadata ----


def cmd_project_meta_ls(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    project = service.get_project_by_name(conn, workspace.id, args.name)
    records = _meta_records(project.metadata)
    text = presenters.format_metadata_block(project.metadata, indent=2) or "no metadata"
    return Ok(data=records, text=text)


def cmd_project_meta_get(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    project = service.get_project_by_name(conn, workspace.id, args.name)
    value = service.get_project_meta(conn, project.id, args.key)
    key = args.key.lower()
    return Ok(data={"key": key, "value": value}, text=value)


def cmd_project_meta_set(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    project = service.get_project_by_name(conn, workspace.id, args.name)
    service.set_project_meta(conn, project.id, args.key, args.value)
    key = args.key.lower()
    return Ok(data={"key": key, "value": args.value}, text=f"set {key}={args.value} on project '{project.name}'")


def cmd_project_meta_del(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    project = service.get_project_by_name(conn, workspace.id, args.name)
    removed = service.remove_project_meta(conn, project.id, args.key)
    key = args.key.lower()
    return Ok(data={"key": key, "value": removed}, text=f"removed {key} from project '{project.name}'")


# ---- Group metadata ----


def cmd_group_meta_ls(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.title, project_name=args.project)
    records = _meta_records(grp.metadata)
    text = presenters.format_metadata_block(grp.metadata, indent=2) or "no metadata"
    return Ok(data=records, text=text)


def cmd_group_meta_get(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.title, project_name=args.project)
    value = service.get_group_meta(conn, grp.id, args.key)
    key = args.key.lower()
    return Ok(data={"key": key, "value": value}, text=value)


def cmd_group_meta_set(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.title, project_name=args.project)
    service.set_group_meta(conn, grp.id, args.key, args.value)
    key = args.key.lower()
    return Ok(data={"key": key, "value": args.value}, text=f"set {key}={args.value} on group '{grp.title}'")


def cmd_group_meta_del(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.title, project_name=args.project)
    removed = service.remove_group_meta(conn, grp.id, args.key)
    key = args.key.lower()
    return Ok(data={"key": key, "value": removed}, text=f"removed {key} from group '{grp.title}'")


def cmd_tui(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    conn.close()
    from sticky_notes.tui import main as tui_main
    from .tui.config import DEFAULT_CONFIG_PATH
    tui_argv: list[str] = []
    if ctx.db_path != DEFAULT_DB_PATH:
        tui_argv += ["--db", str(ctx.db_path)]
    if ctx.config_path != DEFAULT_CONFIG_PATH:
        tui_argv += ["--config", str(ctx.config_path)]
    tui_main(tui_argv)
    raise SystemExit(0)


# ---- Config subcommands ----

_CONFIG_EDITABLE: frozenset[str] = frozenset({"auto_refresh_seconds", "active_workspace"})


def _parse_positive_int(conn: sqlite3.Connection, raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"expected a positive integer, got {raw!r}")
    if value <= 0:
        raise ValueError(f"value must be a positive integer, got {value}")
    return value


def _parse_workspace_ref(conn: sqlite3.Connection, raw: str) -> int:
    try:
        ws_id = int(raw)
        workspace = service.get_workspace(conn, ws_id)
        return workspace.id
    except (ValueError, LookupError):
        pass
    workspace = service.get_workspace_by_name(conn, raw)
    return workspace.id


_CONFIG_VALIDATORS: dict[str, Callable[[sqlite3.Connection, str], Any]] = {
    "auto_refresh_seconds": _parse_positive_int,
    "active_workspace": _parse_workspace_ref,
}


def cmd_config_ls(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    from .tui.config import load_config
    config = load_config(ctx.config_path)
    return Ok(data=to_dict(config), text=presenters.format_config(config))


def cmd_config_get(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    from dataclasses import fields
    from .tui.config import TuiConfig, load_config
    all_keys = {f.name for f in fields(TuiConfig)}
    if args.key not in all_keys:
        raise LookupError(f"unknown config key: {args.key!r}")
    config = load_config(ctx.config_path)
    value = getattr(config, args.key)
    return Ok(data={"key": args.key, "value": value}, text=str(value))


def cmd_config_set(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    from .tui.config import load_config, save_config
    if args.key not in _CONFIG_EDITABLE:
        raise ValueError(f"config key {args.key!r} is not editable via CLI (editable: {', '.join(sorted(_CONFIG_EDITABLE))})")
    new_value = _CONFIG_VALIDATORS[args.key](conn, args.value)
    config = load_config(ctx.config_path)
    setattr(config, args.key, new_value)
    save_config(config, ctx.config_path)
    return Ok(data={"key": args.key, "value": new_value}, text=f"set {args.key} = {new_value}")


def cmd_config_unset(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    from dataclasses import fields
    from .tui.config import TuiConfig, load_config, save_config
    if args.key not in _CONFIG_EDITABLE:
        raise ValueError(f"config key {args.key!r} is not editable via CLI (editable: {', '.join(sorted(_CONFIG_EDITABLE))})")
    default_value = next(
        f.default for f in fields(TuiConfig) if f.name == args.key
    )
    config = load_config(ctx.config_path)
    setattr(config, args.key, default_value)
    save_config(config, ctx.config_path)
    return Ok(data={"key": args.key, "value": default_value}, text=f"unset {args.key} (reset to {default_value!r})")


# ---- Parser ----


HANDLERS: dict[str, CommandHandler] = {
    "task_create": cmd_task_create,
    "task_ls": cmd_task_ls,
    "task_show": cmd_task_show,
    "task_edit": cmd_task_edit,
    "task_mv": cmd_task_mv,
    "task_transfer": cmd_task_transfer,
    "task_archive": cmd_task_archive,
    "task_log": cmd_task_log,
    "task_meta_ls": cmd_task_meta_ls,
    "task_meta_get": cmd_task_meta_get,
    "task_meta_set": cmd_task_meta_set,
    "task_meta_del": cmd_task_meta_del,
    "workspace_create": cmd_workspace_create,
    "workspace_ls": cmd_workspace_ls,
    "workspace_use": cmd_workspace_use,
    "workspace_rename": cmd_workspace_rename,
    "workspace_archive": cmd_workspace_archive,
    "workspace_meta_ls": cmd_workspace_meta_ls,
    "workspace_meta_get": cmd_workspace_meta_get,
    "workspace_meta_set": cmd_workspace_meta_set,
    "workspace_meta_del": cmd_workspace_meta_del,
    "status_create": cmd_status_create,
    "status_ls": cmd_status_ls,
    "status_rename": cmd_status_rename,
    "status_order": cmd_status_order,
    "status_archive": cmd_status_archive,
    "project_create": cmd_project_create,
    "project_ls": cmd_project_ls,
    "project_show": cmd_project_show,
    "project_edit": cmd_project_edit,
    "project_rename": cmd_project_rename,
    "project_archive": cmd_project_archive,
    "project_meta_ls": cmd_project_meta_ls,
    "project_meta_get": cmd_project_meta_get,
    "project_meta_set": cmd_project_meta_set,
    "project_meta_del": cmd_project_meta_del,
    "dep_create": cmd_dep_create,
    "dep_archive": cmd_dep_archive,
    "group_dep_create": cmd_group_dep_create,
    "group_dep_archive": cmd_group_dep_archive,
    "group_create": cmd_group_create,
    "group_ls": cmd_group_ls,
    "group_show": cmd_group_show,
    "group_rename": cmd_group_rename,
    "group_edit": cmd_group_edit,
    "group_archive": cmd_group_archive,
    "group_mv": cmd_group_mv,
    "group_assign": cmd_group_assign,
    "group_unassign": cmd_group_unassign,
    "group_meta_ls": cmd_group_meta_ls,
    "group_meta_get": cmd_group_meta_get,
    "group_meta_set": cmd_group_meta_set,
    "group_meta_del": cmd_group_meta_del,
    "tag_create": cmd_tag_create,
    "tag_ls": cmd_tag_ls,
    "tag_rename": cmd_tag_rename,
    "tag_archive": cmd_tag_archive,
    "workspace_show": cmd_workspace_show,
    "config_ls": cmd_config_ls,
    "config_get": cmd_config_get,
    "config_set": cmd_config_set,
    "config_unset": cmd_config_unset,
    "export": cmd_export,
    "backup": cmd_backup,
    "info": cmd_info,
    "tui": cmd_tui,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="todo", description="Sticky Notes — local kanban CLI")
    parser.add_argument("--db", type=Path, help="path to SQLite database file")
    parser.add_argument("--config", type=Path, help="path to tui.toml (default: ~/.config/sticky-notes/tui.toml)")
    parser.add_argument("--workspace", "-w", help="workspace name (overrides active workspace)")
    fmt_group = parser.add_mutually_exclusive_group()
    fmt_group.add_argument("--json", action="store_true", help="output JSON (default when piped)")
    fmt_group.add_argument("--text", action="store_true", help="force text output even when piped")
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
    p_create.add_argument("--priority", type=int, default=1)
    p_create.add_argument("--due", default=None, help="YYYY-MM-DD")
    p_create.add_argument("--tag", "-t", action="append", default=None, help="tag name (repeatable)")
    p_create.add_argument("--group", "-g", default=None, help="group title")

    p_ls = task_sub.add_parser("ls", help="list tasks")
    p_ls.set_defaults(command="task_ls")
    p_ls.add_argument("--archived", choices=["hide", "include", "only"], default="hide", help="archived visibility: hide (default), include, or only")
    p_ls.add_argument("--status", "-S", default=None, help="filter by status name")
    p_ls.add_argument("--project", "-p", default=None, help="filter by project name")
    p_ls.add_argument("--priority", type=int, default=None, help="filter by priority integer")
    p_ls.add_argument("--search", default=None, help="search title substring")
    p_ls.add_argument("--group", "-g", default=None, help="filter by group title")
    p_ls.add_argument("--tag", "-t", default=None, help="filter by tag name")

    p_show = task_sub.add_parser("show", help="show task detail")
    p_show.set_defaults(command="task_show")
    p_show.add_argument("task", help="task number (task-NNNN/N/#N) or title")

    p_edit = task_sub.add_parser("edit", help="edit a task")
    p_edit.set_defaults(command="task_edit")
    p_edit.add_argument("task", help="task number (task-NNNN/N/#N) or title")
    p_edit.add_argument("--title", default=None)
    p_edit.add_argument("--desc", "-d", default=None)
    p_edit.add_argument("--priority", type=int, default=None)
    p_edit.add_argument("--due", default=None, help="YYYY-MM-DD")
    p_edit.add_argument("--project", "-p", default=None)
    p_edit.add_argument("--tag", "-t", action="append", default=None, help="add tag (repeatable)")
    p_edit.add_argument("--untag", action="append", default=None, help="remove tag (repeatable)")
    p_edit.add_argument("--dry-run", action="store_true", help="preview changes without writing")

    p_mv = task_sub.add_parser("mv", help="move task to status (within workspace)")
    p_mv.set_defaults(command="task_mv")
    p_mv.add_argument("task", help="task number (task-NNNN/N/#N) or title")
    p_mv.add_argument("--status", "-S", required=True, help="target status name")
    p_mv.add_argument("position", type=int, nargs="?", default=None, help="zero-indexed position within status; 0 = top (default), higher values move further down")
    p_mv.add_argument("--project", "-p", default=None, help="also change task project")
    p_mv.add_argument("--dry-run", action="store_true", help="preview move without writing")

    p_transfer = task_sub.add_parser("transfer", help="move task to a different workspace")
    p_transfer.set_defaults(command="task_transfer")
    p_transfer.add_argument("task", help="task number (task-NNNN/N/#N) or title")
    p_transfer.add_argument("--to", dest="to_workspace", required=True, help="target workspace name")
    p_transfer.add_argument("--status", "-S", required=True, help="status on target workspace")
    p_transfer.add_argument("--project", "-p", default=None, help="project on target workspace")
    p_transfer.add_argument("--dry-run", action="store_true", help="preview without executing")

    p_tarch = task_sub.add_parser("archive", help="archive a task (with confirmation)")
    p_tarch.set_defaults(command="task_archive")
    p_tarch.add_argument("task", help="task number (task-NNNN/N/#N) or title")
    p_tarch.add_argument("--force", action="store_true", help="skip confirmation prompt")
    p_tarch.add_argument("--dry-run", action="store_true", help="preview without executing")

    p_log = task_sub.add_parser("log", help="show task change log")
    p_log.set_defaults(command="task_log")
    p_log.add_argument("task", help="task number (task-NNNN/N/#N) or title")

    p_meta = task_sub.add_parser("meta", help="task metadata key/value management")
    meta_sub = p_meta.add_subparsers()

    p_meta_ls = meta_sub.add_parser("ls", help="list all metadata")
    p_meta_ls.set_defaults(command="task_meta_ls")
    p_meta_ls.add_argument("task", help="task number (task-NNNN/N/#N) or title")

    p_meta_get = meta_sub.add_parser("get", help="get a metadata value")
    p_meta_get.set_defaults(command="task_meta_get")
    p_meta_get.add_argument("task", help="task number (task-NNNN/N/#N) or title")
    p_meta_get.add_argument("key")

    p_meta_set = meta_sub.add_parser("set", help="set a metadata key/value")
    p_meta_set.set_defaults(command="task_meta_set")
    p_meta_set.add_argument("task", help="task number (task-NNNN/N/#N) or title")
    p_meta_set.add_argument("key")
    p_meta_set.add_argument("value")

    p_meta_del = meta_sub.add_parser("del", help="delete a metadata key")
    p_meta_del.set_defaults(command="task_meta_del")
    p_meta_del.add_argument("task", help="task number (task-NNNN/N/#N) or title")
    p_meta_del.add_argument("key")

    # ---- Workspace subcommands ----

    p_workspace = sub.add_parser("workspace", help="workspace management")
    workspace_sub = p_workspace.add_subparsers()

    p_wc = workspace_sub.add_parser("create", help="create a workspace")
    p_wc.set_defaults(command="workspace_create")
    p_wc.add_argument("name")
    p_wc.add_argument("--statuses", default=None, help="comma-separated status names to create")

    p_wl = workspace_sub.add_parser("ls", help="list workspaces")
    p_wl.set_defaults(command="workspace_ls")
    p_wl.add_argument("--archived", choices=["hide", "include", "only"], default="hide", help="archived visibility: hide (default), include, or only")

    p_wu = workspace_sub.add_parser("use", help="switch active workspace")
    p_wu.set_defaults(command="workspace_use")
    p_wu.add_argument("name")

    p_wr = workspace_sub.add_parser("rename", help="rename a workspace")
    p_wr.set_defaults(command="workspace_rename")
    p_wr.add_argument("old_name", help="existing workspace name")
    p_wr.add_argument("new_name", help="new workspace name")

    p_wsh = workspace_sub.add_parser("show", help="workspace snapshot: statuses, tasks, projects, tags, groups")
    p_wsh.set_defaults(command="workspace_show")
    p_wsh.add_argument("name", nargs="?", default=None, help="workspace name (default: active workspace)")

    p_warc = workspace_sub.add_parser("archive", help="cascade-archive workspace and all descendants")
    p_warc.set_defaults(command="workspace_archive")
    p_warc.add_argument("name", nargs="?", default=None, help="workspace name (default: active workspace)")
    p_warc.add_argument("--force", action="store_true", help="skip confirmation prompt")
    p_warc.add_argument("--dry-run", action="store_true", help="preview without executing")

    p_wmeta = workspace_sub.add_parser("meta", help="workspace metadata key/value management")
    wmeta_sub = p_wmeta.add_subparsers()

    p_wmeta_ls = wmeta_sub.add_parser("ls", help="list all metadata")
    p_wmeta_ls.set_defaults(command="workspace_meta_ls")

    p_wmeta_get = wmeta_sub.add_parser("get", help="get a metadata value")
    p_wmeta_get.set_defaults(command="workspace_meta_get")
    p_wmeta_get.add_argument("key")

    p_wmeta_set = wmeta_sub.add_parser("set", help="set a metadata key/value")
    p_wmeta_set.set_defaults(command="workspace_meta_set")
    p_wmeta_set.add_argument("key")
    p_wmeta_set.add_argument("value")

    p_wmeta_del = wmeta_sub.add_parser("del", help="delete a metadata key")
    p_wmeta_del.set_defaults(command="workspace_meta_del")
    p_wmeta_del.add_argument("key")

    # ---- Status subcommands ----

    p_status = sub.add_parser("status", help="status management")
    status_sub = p_status.add_subparsers()

    p_ca = status_sub.add_parser("create", help="create a status")
    p_ca.set_defaults(command="status_create")
    p_ca.add_argument("name")

    p_cl = status_sub.add_parser("ls", help="list statuses")
    p_cl.set_defaults(command="status_ls")
    p_cl.add_argument("--archived", choices=["hide", "include", "only"], default="hide", help="archived visibility: hide (default), include, or only")

    p_cr = status_sub.add_parser("rename", help="rename a status")
    p_cr.set_defaults(command="status_rename")
    p_cr.add_argument("old_name")
    p_cr.add_argument("new_name")

    p_corder = status_sub.add_parser("order", help="set status display order for active workspace (used by TUI)")
    p_corder.set_defaults(command="status_order")
    p_corder.add_argument("statuses", nargs="+", help="status names in desired order")

    p_carch = status_sub.add_parser("archive", help="archive a status")
    p_carch.set_defaults(command="status_archive")
    p_carch.add_argument("name")
    p_carch.add_argument("--reassign-to", default=None, metavar="STATUS", help="move tasks to this status")
    p_carch.add_argument("--force", action="store_true", help="archive tasks instead of blocking")
    p_carch.add_argument("--dry-run", action="store_true", help="preview without executing")

    # ---- Project subcommands ----

    p_proj = sub.add_parser("project", help="project management")
    proj_sub = p_proj.add_subparsers()

    p_pc = proj_sub.add_parser("create", help="create a project")
    p_pc.set_defaults(command="project_create")
    p_pc.add_argument("name")
    p_pc.add_argument("--desc", "-d", default=None)

    p_pl = proj_sub.add_parser("ls", help="list projects")
    p_pl.set_defaults(command="project_ls")
    p_pl.add_argument("--archived", choices=["hide", "include", "only"], default="hide", help="archived visibility: hide (default), include, or only")

    p_ps = proj_sub.add_parser("show", help="show project detail")
    p_ps.set_defaults(command="project_show")
    p_ps.add_argument("name")

    p_pe = proj_sub.add_parser("edit", help="edit a project")
    p_pe.set_defaults(command="project_edit")
    p_pe.add_argument("name")
    p_pe.add_argument("--desc", "-d", default=None, help="project description")
    p_pe.add_argument("--dry-run", action="store_true", help="preview changes without writing")

    p_pren = proj_sub.add_parser("rename", help="rename a project")
    p_pren.set_defaults(command="project_rename")
    p_pren.add_argument("old_name")
    p_pren.add_argument("new_name")

    p_parc = proj_sub.add_parser("archive", help="cascade-archive project and all groups/tasks")
    p_parc.set_defaults(command="project_archive")
    p_parc.add_argument("name")
    p_parc.add_argument("--force", action="store_true", help="skip confirmation prompt")
    p_parc.add_argument("--dry-run", action="store_true", help="preview without executing")

    p_pmeta = proj_sub.add_parser("meta", help="project metadata key/value management")
    pmeta_sub = p_pmeta.add_subparsers()

    p_pmeta_ls = pmeta_sub.add_parser("ls", help="list all metadata")
    p_pmeta_ls.set_defaults(command="project_meta_ls")
    p_pmeta_ls.add_argument("name", help="project name")

    p_pmeta_get = pmeta_sub.add_parser("get", help="get a metadata value")
    p_pmeta_get.set_defaults(command="project_meta_get")
    p_pmeta_get.add_argument("name", help="project name")
    p_pmeta_get.add_argument("key")

    p_pmeta_set = pmeta_sub.add_parser("set", help="set a metadata key/value")
    p_pmeta_set.set_defaults(command="project_meta_set")
    p_pmeta_set.add_argument("name", help="project name")
    p_pmeta_set.add_argument("key")
    p_pmeta_set.add_argument("value")

    p_pmeta_del = pmeta_sub.add_parser("del", help="delete a metadata key")
    p_pmeta_del.set_defaults(command="project_meta_del")
    p_pmeta_del.add_argument("name", help="project name")
    p_pmeta_del.add_argument("key")

    # ---- Dependency subcommands ----

    p_dep = sub.add_parser("dep", help="dependency management")
    dep_sub = p_dep.add_subparsers()

    p_da = dep_sub.add_parser("create", help="add a dependency")
    p_da.set_defaults(command="dep_create")
    p_da.add_argument("--task", required=True, help="task that will be blocked")
    p_da.add_argument("--blocked-by", dest="blocked_by", required=True, help="task that blocks --task")

    p_dr = dep_sub.add_parser("archive", help="archive a dependency")
    p_dr.set_defaults(command="dep_archive")
    p_dr.add_argument("--task", required=True, help="task that was blocked")
    p_dr.add_argument("--blocked-by", dest="blocked_by", required=True, help="task that was blocking --task")

    # ---- Group subcommands ----

    p_grp = sub.add_parser("group", help="group management")
    grp_sub = p_grp.add_subparsers()

    p_gc = grp_sub.add_parser("create", help="create a group")
    p_gc.set_defaults(command="group_create")
    p_gc.add_argument("title")
    p_gc.add_argument("--desc", "-d", default=None, help="group description")
    p_gc.add_argument("--parent", default=None, help="parent group title")
    p_gc.add_argument("--project", "-p", required=True, help="project name (required; groups are project-scoped)")

    p_gl = grp_sub.add_parser("ls", help="list groups")
    p_gl.set_defaults(command="group_ls")
    p_gl.add_argument("--project", "-p", default=None, help="filter by project name (optional; lists all projects when omitted)")
    p_gl.add_argument("--archived", choices=["hide", "include", "only"], default="hide", help="archived visibility: hide (default), include, or only")

    p_gs = grp_sub.add_parser("show", help="show group detail")
    p_gs.set_defaults(command="group_show")
    p_gs.add_argument("title")
    p_gs.add_argument("--project", "-p", default=None, help="disambiguate by project")

    p_grn = grp_sub.add_parser("rename", help="rename a group")
    p_grn.set_defaults(command="group_rename")
    p_grn.add_argument("old_title", help="current group title")
    p_grn.add_argument("new_title", help="new group title")
    p_grn.add_argument("--project", "-p", default=None, help="disambiguate by project")
    p_grn.add_argument("--dry-run", action="store_true", help="preview rename without writing")

    p_ge = grp_sub.add_parser("edit", help="edit a group")
    p_ge.set_defaults(command="group_edit")
    p_ge.add_argument("title")
    p_ge.add_argument("--desc", "-d", default=None, help="group description")
    p_ge.add_argument("--project", "-p", default=None, help="disambiguate by project")
    p_ge.add_argument("--dry-run", action="store_true", help="preview changes without writing")

    p_garc = grp_sub.add_parser("archive", help="cascade-archive group and all descendant groups/tasks")
    p_garc.set_defaults(command="group_archive")
    p_garc.add_argument("title")
    p_garc.add_argument("--project", "-p", default=None, help="disambiguate by project")
    p_garc.add_argument("--force", action="store_true", help="skip confirmation prompt")
    p_garc.add_argument("--dry-run", action="store_true", help="preview without executing")

    p_gmv = grp_sub.add_parser("mv", help="reparent a group")
    p_gmv.set_defaults(command="group_mv")
    p_gmv.add_argument("title")
    p_gmv_parent = p_gmv.add_mutually_exclusive_group(required=True)
    p_gmv_parent.add_argument("--parent", help="new parent group title")
    p_gmv_parent.add_argument("--to-top", action="store_true", help="promote to top-level (no parent)")
    p_gmv.add_argument("--project", "-p", default=None, help="disambiguate by project")
    p_gmv.add_argument("--dry-run", action="store_true", help="preview reparent without writing")

    p_gasn = grp_sub.add_parser("assign", help="assign task to group")
    p_gasn.set_defaults(command="group_assign")
    p_gasn.add_argument("task", help="task number or title")
    p_gasn.add_argument("title", help="group title")
    p_gasn.add_argument("--project", "-p", default=None, help="disambiguate by project")

    p_gun = grp_sub.add_parser("unassign", help="unassign task from group")
    p_gun.set_defaults(command="group_unassign")
    p_gun.add_argument("task", help="task number or title")

    p_gmeta = grp_sub.add_parser("meta", help="group metadata key/value management")
    gmeta_sub = p_gmeta.add_subparsers()

    p_gmeta_ls = gmeta_sub.add_parser("ls", help="list all metadata")
    p_gmeta_ls.set_defaults(command="group_meta_ls")
    p_gmeta_ls.add_argument("title", help="group title")
    p_gmeta_ls.add_argument("--project", "-p", default=None, help="disambiguate by project")

    p_gmeta_get = gmeta_sub.add_parser("get", help="get a metadata value")
    p_gmeta_get.set_defaults(command="group_meta_get")
    p_gmeta_get.add_argument("title", help="group title")
    p_gmeta_get.add_argument("key")
    p_gmeta_get.add_argument("--project", "-p", default=None, help="disambiguate by project")

    p_gmeta_set = gmeta_sub.add_parser("set", help="set a metadata key/value")
    p_gmeta_set.set_defaults(command="group_meta_set")
    p_gmeta_set.add_argument("title", help="group title")
    p_gmeta_set.add_argument("key")
    p_gmeta_set.add_argument("value")
    p_gmeta_set.add_argument("--project", "-p", default=None, help="disambiguate by project")

    p_gmeta_del = gmeta_sub.add_parser("del", help="delete a metadata key")
    p_gmeta_del.set_defaults(command="group_meta_del")
    p_gmeta_del.add_argument("title", help="group title")
    p_gmeta_del.add_argument("key")
    p_gmeta_del.add_argument("--project", "-p", default=None, help="disambiguate by project")

    # Group dependencies — nested under `group dep`
    p_gdep = grp_sub.add_parser("dep", help="group dependency management")
    gdep_sub = p_gdep.add_subparsers()

    p_gda = gdep_sub.add_parser("create", help="add a group dependency")
    p_gda.set_defaults(command="group_dep_create")
    p_gda.add_argument("-g", "--group", required=True, help="group title that will be blocked")
    p_gda.add_argument("--blocked-by", dest="blocked_by", required=True, help="group title that blocks --group")
    p_gda.add_argument("--project", "-p", default=None, help="disambiguate by project name")

    p_gdr = gdep_sub.add_parser("archive", help="archive a group dependency")
    p_gdr.set_defaults(command="group_dep_archive")
    p_gdr.add_argument("-g", "--group", required=True, help="group title that was blocked")
    p_gdr.add_argument("--blocked-by", dest="blocked_by", required=True, help="group title that was blocking --group")
    p_gdr.add_argument("--project", "-p", default=None, help="disambiguate by project name")

    # ---- Tag subcommands ----

    p_tag = sub.add_parser("tag", help="tag management")
    tag_sub = p_tag.add_subparsers()

    p_tc = tag_sub.add_parser("create", help="create a tag")
    p_tc.set_defaults(command="tag_create")
    p_tc.add_argument("name")

    p_tl = tag_sub.add_parser("ls", help="list tags")
    p_tl.set_defaults(command="tag_ls")
    p_tl.add_argument("--archived", choices=["hide", "include", "only"], default="hide", help="archived visibility: hide (default), include, or only")

    p_tren = tag_sub.add_parser("rename", help="rename a tag")
    p_tren.set_defaults(command="tag_rename")
    p_tren.add_argument("old_name")
    p_tren.add_argument("new_name")

    p_tr = tag_sub.add_parser("archive", help="archive a tag")
    p_tr.set_defaults(command="tag_archive")
    p_tr.add_argument("name")
    p_tr.add_argument("--unassign", action="store_true", help="strip the tag from all tasks before archiving (without this flag, the archived tag remains attached to tasks)")
    p_tr.add_argument("--force", action="store_true", help="skip confirmation prompt")
    p_tr.add_argument("--dry-run", action="store_true", help="preview without executing")


    # ---- Config subcommands ----

    p_config = sub.add_parser("config", help="TUI config management (tui.toml)")
    config_sub = p_config.add_subparsers()

    p_cfg_ls = config_sub.add_parser("ls", help="show all config values")
    p_cfg_ls.set_defaults(command="config_ls")

    p_cfg_get = config_sub.add_parser("get", help="get a config value")
    p_cfg_get.set_defaults(command="config_get")
    p_cfg_get.add_argument("key", help="config key name")

    p_cfg_set = config_sub.add_parser("set", help="set a config value (auto_refresh_seconds, active_workspace)")
    p_cfg_set.set_defaults(command="config_set")
    p_cfg_set.add_argument("key", help="config key name")
    p_cfg_set.add_argument("value", help="new value")

    p_cfg_unset = config_sub.add_parser("unset", help="reset a config value to its default")
    p_cfg_unset.set_defaults(command="config_unset")
    p_cfg_unset.add_argument("key", help="config key name")

    # ---- Export ----

    p_export = sub.add_parser("export", help="export database as JSON (default) or markdown (--md)")
    p_export.set_defaults(command="export")
    p_export.add_argument("--md", action="store_true", help="export as markdown instead of JSON")
    p_export.add_argument("-o", "--output", help="write to file instead of stdout")
    p_export.add_argument("--overwrite", action="store_true", help="overwrite destination file if it exists")

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
    from .tui.config import DEFAULT_CONFIG_PATH
    ctx = RunContext(db_path=args.db or DEFAULT_DB_PATH, config_path=args.config or DEFAULT_CONFIG_PATH)
    json_mode = args.json or (not args.text and not _stdout_is_tty())
    conn = get_connection(ctx.db_path)
    try:
        init_db(conn)
        result = HANDLERS[args.command](conn, args, ctx)
        if json_mode:
            _emit_json(result)
        elif result.text and not args.quiet:
            sys.stdout.write(result.text)
            if not result.text.endswith("\n"):
                sys.stdout.write("\n")
    except KeyboardInterrupt:
        raise SystemExit(130)
    except sqlite3.OperationalError as exc:
        code = "db_error"
        if json_mode:
            _json_err(f"database error: {exc}", code)
        else:
            _text_err(f"database error: {exc}", code)
        raise SystemExit(EXIT_DB_ERROR)
    except NoActiveWorkspaceError as exc:
        code = "missing_active_workspace"
        if json_mode:
            _json_err(str(exc), code)
        else:
            _text_err(str(exc), code)
        raise SystemExit(EXIT_NO_ACTIVE_WS)
    except LookupError as exc:
        code = "not_found"
        if json_mode:
            _json_err(str(exc), code)
        else:
            _text_err(str(exc), code)
        raise SystemExit(EXIT_NOT_FOUND)
    except ValueError as exc:
        code = "validation"
        if json_mode:
            _json_err(str(exc), code)
        else:
            _text_err(str(exc), code)
        raise SystemExit(EXIT_VALIDATION)
    finally:
        conn.close()
