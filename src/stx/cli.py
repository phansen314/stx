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

from . import presenters, service
from .active_workspace import (
    active_workspace_path,
    clear_active_workspace_id,
    get_active_workspace_id,
    set_active_workspace_id,
)
from .connection import DEFAULT_DB_PATH, get_connection, init_db
from .export import export_full_json, export_markdown
from .graph import GraphFormat, write_graph
from .formatting import format_group_num, format_task_num, parse_date, parse_task_num
from .models import ConflictError, Workspace
from .service_models import ArchivePreview

EXIT_DB_ERROR = 2
EXIT_NOT_FOUND = 3
EXIT_VALIDATION = 4
EXIT_NO_ACTIVE_WS = 5
EXIT_CONFLICT = 6


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


def to_dict(obj: object) -> Any:
    """Convert dataclasses (possibly nested) to plain dicts for JSON serialisation.

    Handles StrEnum -> .value, tuples/lists, nested dataclasses, and plain dicts
    with dataclass values. Does *not* use dataclasses.asdict() which recurses
    incorrectly for StrEnum.
    """
    if isinstance(obj, StrEnum):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_dict(item) for item in obj]
    return obj


# ---- Helpers: resolution ----


def _resolve_workspace(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> Workspace:
    """Resolve the active workspace from --workspace flag or tui.toml (with legacy file fallback).
    Stays in the CLI layer rather than the service layer."""
    if args.workspace:
        return service.get_workspace_by_name(conn, args.workspace)
    workspace_id = get_active_workspace_id(ctx.config_path, ctx.db_path)
    if workspace_id is None:
        raise NoActiveWorkspaceError(
            "no active workspace — use 'stx workspace create <name>' or 'stx workspace use <name>'"
        )
    return service.get_workspace(conn, workspace_id)


def _resolve_task(
    conn: sqlite3.Connection,
    workspace: Workspace,
    raw: str,
) -> int:
    return service.resolve_task_id(conn, workspace.id, raw)


# ---- CAS retry helper ----

_MAX_CAS_RETRIES = 3


def _with_cas_retry(
    fetch: Callable[[], Any],
    already: Callable[[Any], CmdResult | None],
    action: Callable[[Any], CmdResult],
) -> CmdResult:
    """Fetch an entity, attempt `action`. On ConflictError, re-fetch and retry.

    `already(entity)` — return a CmdResult if the entity is already in the
    desired state (idempotency short-circuit), or None to proceed with action.
    Retries up to _MAX_CAS_RETRIES times; re-raises ConflictError on exhaustion
    (caught by main() → EXIT_CONFLICT).
    """
    for attempt in range(_MAX_CAS_RETRIES + 1):
        entity = fetch()
        result = already(entity)
        if result is not None:
            return result
        try:
            return action(entity)
        except ConflictError:
            if attempt == _MAX_CAS_RETRIES:
                raise
    assert False, "unreachable"  # noqa: B011


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


def cmd_task_create(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    col = service.get_status_by_name(conn, workspace.id, args.status)
    group_id = None
    if args.group:
        grp = service.resolve_group(conn, workspace.id, args.group)
        group_id = grp.id
    due = parse_date(args.due) if args.due else None
    task = service.create_task(
        conn,
        workspace_id=workspace.id,
        title=args.title,
        status_id=col.id,
        description=(args.desc or "").strip() or None,
        priority=args.priority,
        due_date=due,
        group_id=group_id,
    )
    detail = service.get_task_detail(conn, task.id)
    return Ok(data=detail, text=f"created {format_task_num(task.id)}: {task.title}")


def cmd_task_ls(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    status_id = (
        service.get_status_by_name(conn, workspace.id, args.status).id if args.status else None
    )
    group_id = (
        service.resolve_group(conn, workspace.id, args.group).id
        if args.group
        else None
    )
    include_archived = args.archived in ("include", "only")
    only_archived = args.archived == "only"
    view = service.get_workspace_list_view(
        conn,
        workspace.id,
        status_id=status_id,
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
    if args.group is not None:
        if args.group == "":
            changes["group_id"] = None
        else:
            grp = service.resolve_group(conn, workspace.id, args.group)
            changes["group_id"] = grp.id
    if not changes:
        detail = service.get_task_detail(conn, task_id)
        return Ok(data=detail, text="nothing to update")
    if args.dry_run:
        preview = service.preview_update_task(conn, task_id, changes)
        return Ok(data=preview, text=presenters.format_entity_update_preview(preview))
    service.update_task(conn, task_id, changes, source="cli")
    detail = service.get_task_detail(conn, task_id)
    return Ok(data=detail, text=f"updated {format_task_num(task_id)}")


def cmd_task_mv(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    col = service.get_status_by_name(conn, workspace.id, args.status)
    pre = service.get_task_detail(conn, task_id)
    from_status = pre.status.name
    if args.dry_run:
        preview = service.preview_move_task(conn, task_id, col.id)
        return Ok(data=preview, text=presenters.format_task_move_preview(preview))
    service.move_task(conn, task_id, col.id, source="cli")
    detail = service.get_task_detail(conn, task_id)
    return Ok(data=detail, text=f"moved {format_task_num(task_id)}: {from_status} -> {col.name}")


def cmd_task_transfer(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    target_workspace = service.get_workspace_by_name(conn, args.to_workspace)
    target_col = service.get_status_by_name(conn, target_workspace.id, args.status)
    if args.dry_run:
        preview = service.preview_move_to_workspace(
            conn,
            task_id,
            target_workspace.id,
            target_col.id,
        )
        text = presenters.format_move_preview(
            preview,
            target_workspace.name,
            target_col.name,
            source_workspace_name=workspace.name,
        )
        return Ok(data=preview, text=text)
    new = service.move_task_to_workspace(
        conn,
        task_id,
        target_workspace.id,
        target_col.id,
        source="cli",
    )
    detail = service.get_task_detail(conn, new.id)
    return Ok(
        data={"task": detail, "source_task_id": task_id},
        text=f"transferred {format_task_num(task_id)} -> workspace '{target_workspace.name}' / status '{target_col.name}' (new {format_task_num(new.id)})",
    )


def cmd_task_archive(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
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
    from .models import EntityType

    history = service.list_journal(conn, EntityType.TASK, task_id)
    return Ok(data=history, text=presenters.format_journal_entries(history))


def cmd_task_done(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)

    def fetch() -> Any:
        return service.get_task(conn, task_id)

    def already(pre: Any) -> CmdResult | None:
        if pre.done:
            return Ok(data=pre, text=f"{format_task_num(task_id)} already done")
        return None

    def action(pre: Any) -> CmdResult:
        service.mark_task_done(conn, task_id, source="cli",
                               expected_version=pre.version)
        detail = service.get_task_detail(conn, task_id)
        return Ok(data=detail, text=f"marked {format_task_num(task_id)} done")

    return _with_cas_retry(fetch, already, action)


def cmd_task_undone(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    if not args.force:
        # Un-done is gated to prevent fat-finger reverts on a completed task.
        # Require --force for non-interactive callers, otherwise prompt.
        if not _stdin_is_tty():
            raise ValueError(
                f"refusing to flip {format_task_num(task_id)} from done to not-done "
                f"without --force (non-interactive stdin)"
            )
        print(
            f"warning: flipping {format_task_num(task_id)} from done back to not-done",
            file=sys.stderr,
        )
        answer = input("proceed? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            return Ok(data=None, text="aborted")

    def fetch() -> Any:
        return service.get_task(conn, task_id)

    def already(pre: Any) -> CmdResult | None:
        if not pre.done:
            return Ok(data=pre, text=f"{format_task_num(task_id)} already not done")
        return None

    def action(pre: Any) -> CmdResult:
        service.mark_task_undone(conn, task_id, source="cli",
                                 expected_version=pre.version)
        detail = service.get_task_detail(conn, task_id)
        return Ok(data=detail, text=f"marked {format_task_num(task_id)} not done")

    return _with_cas_retry(fetch, already, action)


# ---- Workspace subcommands ----


def cmd_workspace_create(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = service.create_workspace(conn, args.name)
    set_active_workspace_id(ctx.config_path, workspace.id)
    if args.statuses:
        for name in [s.strip() for s in args.statuses.split(",") if s.strip()]:
            service.create_status(conn, workspace.id, name)
    return Ok(data=workspace, text=f"created workspace '{workspace.name}' (active)")


def cmd_workspace_ls(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    include_archived = args.archived in ("include", "only")
    only_archived = args.archived == "only"
    workspaces = service.list_workspaces(
        conn,
        include_archived=include_archived,
        only_archived=only_archived,
    )
    active_id = get_active_workspace_id(ctx.config_path, ctx.db_path)
    payload = [{**to_dict(w), "active": w.id == active_id} for w in workspaces]
    return Ok(data=payload, text=presenters.format_workspace_list(workspaces, active_id))


def cmd_workspace_use(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = service.get_workspace_by_name(conn, args.name)
    set_active_workspace_id(ctx.config_path, workspace.id)
    return Ok(data=workspace, text=f"switched to workspace '{workspace.name}'")


def cmd_workspace_log(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    from .models import EntityType

    history = service.list_journal(conn, EntityType.WORKSPACE, workspace.id)
    return Ok(data=history, text=presenters.format_journal_entries(history))


def cmd_workspace_edit(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    changes: dict[str, Any] = {}
    if args.name is not None:
        changes["name"] = args.name
    if args.dry_run:
        preview = service.preview_update_workspace(conn, workspace.id, changes)
        return Ok(data=preview, text=presenters.format_entity_update_preview(preview))
    if not changes:
        return Ok(data=workspace, text="nothing to update")
    old_name = workspace.name
    updated = service.update_workspace(conn, workspace.id, changes)
    if "name" in changes and changes["name"] != old_name:
        return Ok(data=updated, text=f"renamed workspace '{old_name}' -> '{updated.name}'")
    return Ok(data=updated, text=f"updated workspace '{updated.name}'")


def cmd_workspace_archive(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
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


def cmd_status_create(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    col = service.create_status(conn, workspace.id, args.name)
    return Ok(data=col, text=f"created status '{col.name}'")


def cmd_status_ls(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    include_archived = args.archived in ("include", "only")
    only_archived = args.archived == "only"
    statuses = service.list_statuses(
        conn,
        workspace.id,
        include_archived=include_archived,
        only_archived=only_archived,
    )
    return Ok(data=statuses, text=presenters.format_status_list(statuses))


def cmd_status_show(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    col = service.get_status_by_name(conn, workspace.id, args.name)
    from .models import TaskFilter

    tasks = service.list_tasks_filtered(
        conn, workspace.id, task_filter=TaskFilter(status_id=col.id)
    )
    return Ok(data=col, text=presenters.format_status_detail(col, len(tasks)))


def cmd_status_edit(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    col = service.get_status_by_name(conn, workspace.id, args.name)
    changes: dict[str, Any] = {}
    if args.new_name is not None:
        changes["name"] = args.new_name
    if args.terminal is not None:
        changes["is_terminal"] = args.terminal
    if not changes:
        return Ok(data=col, text="nothing to update")
    old_name = col.name
    updated = service.update_status(conn, col.id, changes)
    if "name" in changes and changes["name"] != old_name:
        return Ok(data=updated, text=f"renamed status '{old_name}' -> '{updated.name}'")
    return Ok(data=updated, text=f"updated status '{updated.name}'")


def cmd_status_order(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
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


def cmd_status_archive(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    col = service.get_status_by_name(conn, workspace.id, args.name)
    if args.dry_run:
        preview = service.preview_archive_status(conn, col.id)
        return Ok(data=preview, text="dry-run: " + presenters.format_archive_preview(preview))
    # No confirmation prompt: --force means "archive tasks, just do it";
    # --reassign-to means "move tasks, no data loss". Without either flag the
    # service layer blocks on active tasks, so no side-effects to confirm.
    # When --force is used with active tasks, emit a stderr warning so the
    # cascade-archive is not silent (parity with task/group/workspace prompts).
    reassign_to_id = None
    if args.reassign_to:
        reassign_col = service.get_status_by_name(conn, workspace.id, args.reassign_to)
        reassign_to_id = reassign_col.id
    if args.force and not args.reassign_to:
        preview = service.preview_archive_status(conn, col.id)
        if preview.task_count > 0:
            print(
                f"warning: --force will cascade-archive {preview.task_count} active task(s) in status '{col.name}'",
                file=sys.stderr,
            )
    updated = service.archive_status(
        conn,
        col.id,
        reassign_to_status_id=reassign_to_id,
        force=args.force,
    )
    return Ok(data=updated, text=f"archived status '{col.name}'")


# ---- Edge typed-ref resolution ----


def _resolve_edge_node(
    conn: sqlite3.Connection,
    workspace_id: int,
    ref: str,
) -> tuple[str, int]:
    """Parse a typed node ref and return (node_type, node_id).

    Type inference from delimiters when no explicit ``<type>:`` prefix is
    given:
      * Numeric forms (``task-NNNN``, ``#N``, plain int) → task by id.
      * Leading ``/`` (``/A``, ``/A/B/C``)               → group path
        (the leading slash anchors single-segment refs as groups).
      * Path with ``/`` but no ``:`` (``A/B/C``)         → group path.
      * Path containing ``:`` (``A/B:leaf``, ``:foo``)    → task path.
      * Bare title (no delimiters)                        → task by title.

    Explicit prefixes always override inference:
      ``group:<path>``, ``task:<path>``, ``workspace:<name>``, ``status:<name>``.
    """
    if ref.startswith("group:"):
        suffix = ref[len("group:"):]
        if not suffix:
            raise ValueError("empty group ref after 'group:'")
        grp = service.resolve_group(conn, workspace_id, suffix)
        return "group", grp.id
    if ref.startswith("task:"):
        suffix = ref[len("task:"):]
        if not suffix:
            raise ValueError("empty task ref after 'task:'")
        return "task", service.resolve_task_id(conn, workspace_id, suffix)
    if ref.startswith("workspace:"):
        name = ref[len("workspace:"):]
        ws = service.get_workspace_by_name(conn, name)
        return "workspace", ws.id
    if ref.startswith("status:"):
        name = ref[len("status:"):]
        st = service.get_status_by_name(conn, workspace_id, name)
        return "status", st.id
    # No explicit prefix — try numeric task short-circuit first, then
    # infer from path delimiters.
    try:
        return "task", parse_task_num(ref)
    except ValueError:
        pass
    parsed = service.parse_ref(ref)
    if parsed.kind == "group_path":
        grp = service.resolve_group_path(conn, workspace_id, parsed.segments)
        return "group", grp.id
    # bare or task_path — both resolve as tasks.
    return "task", service.resolve_task_id(conn, workspace_id, ref)


def _edge_node_label(node_type: str, node_id: int, title: str) -> str:
    if node_type == "task":
        return f"{format_task_num(node_id)} ({title})"
    elif node_type == "group":
        return f"{format_group_num(node_id)} ({title})"
    elif node_type == "status":
        return f"status:{node_id} ({title})"
    else:
        return f"workspace:{node_id} ({title})"


# ---- Edge subcommands ----


def cmd_edge_create(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    from_type, from_id = _resolve_edge_node(
        conn, workspace.id, args.source    )
    to_type, to_id = _resolve_edge_node(
        conn, workspace.id, args.target    )
    acyclic: bool | None = None
    if args.acyclic is not None:
        acyclic = args.acyclic
    # service.add_edge returns the normalized kind so the Ok payload matches
    # what actually hit the DB (e.g. --kind BLOCKS → "blocks").
    kind = service.add_edge(
        conn, (from_type, from_id), (to_type, to_id), kind=args.kind, acyclic=acyclic
    )
    return Ok(
        data={
            "from_type": from_type,
            "from_id": from_id,
            "to_type": to_type,
            "to_id": to_id,
            "kind": kind,
        },
        text=f"{from_type}:{from_id} --({kind})--> {to_type}:{to_id}",
    )


def cmd_edge_archive(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    from_type, from_id = _resolve_edge_node(
        conn, workspace.id, args.source    )
    to_type, to_id = _resolve_edge_node(
        conn, workspace.id, args.target    )
    kind = service.archive_edge(
        conn, (from_type, from_id), (to_type, to_id), kind=args.kind
    )
    return Ok(
        data={
            "from_type": from_type,
            "from_id": from_id,
            "to_type": to_type,
            "to_id": to_id,
            "kind": kind,
        },
        text=f"archived edge {from_type}:{from_id} -> {to_type}:{to_id} [{kind}]",
    )


def cmd_edge_show(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    from_type, from_id = _resolve_edge_node(
        conn, workspace.id, args.source    )
    to_type, to_id = _resolve_edge_node(
        conn, workspace.id, args.target    )
    detail = service.get_edge_detail(
        conn, (from_type, from_id), (to_type, to_id), kind=args.kind
    )
    return Ok(data=detail, text=presenters.format_edge_detail(detail))


def cmd_edge_edit(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    from_type, from_id = _resolve_edge_node(
        conn, workspace.id, args.source    )
    to_type, to_id = _resolve_edge_node(
        conn, workspace.id, args.target    )
    changes: dict[str, Any] = {}
    if args.acyclic is not None:
        changes["acyclic"] = args.acyclic
    if not changes:
        detail = service.get_edge_detail(
            conn, (from_type, from_id), (to_type, to_id), kind=args.kind
        )
        return Ok(data=detail, text="nothing to update")
    detail = service.update_edge(
        conn,
        (from_type, from_id),
        (to_type, to_id),
        kind=args.kind,
        changes=changes,
        source="cli",
    )
    return Ok(
        data=detail,
        text=f"updated edge {from_type}:{from_id} --({detail.kind})--> {to_type}:{to_id}",
    )


def cmd_edge_log(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    from_type, from_id = _resolve_edge_node(
        conn, workspace.id, args.source    )
    to_type, to_id = _resolve_edge_node(
        conn, workspace.id, args.target    )
    history = service.list_journal_for_edge(
        conn, (from_type, from_id), (to_type, to_id), kind=args.kind
    )
    return Ok(data=history, text=presenters.format_journal_entries(history))


def cmd_edge_ls(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    from_type: str | None = None
    from_id: int | None = None
    to_type: str | None = None
    to_id: int | None = None
    if args.source:
        from_type, from_id = _resolve_edge_node(
            conn, workspace.id, args.source        )
    if args.target:
        to_type, to_id = _resolve_edge_node(
            conn, workspace.id, args.target        )
    edges = service.list_edges(
        conn,
        workspace.id,
        kind=args.kind or None,
        from_type=from_type,
        from_id=from_id,
        to_type=to_type,
        to_id=to_id,
    )
    text = presenters.format_edge_list(edges)
    return Ok(data=list(edges), text=text)


# ---- Edge metadata subcommands ----


def _resolve_edge_meta_endpoints(
    conn: sqlite3.Connection, args: argparse.Namespace, workspace_id: int
) -> tuple[str, int, str, int]:
    from_type, from_id = _resolve_edge_node(
        conn, workspace_id, args.source    )
    to_type, to_id = _resolve_edge_node(
        conn, workspace_id, args.target    )
    return from_type, from_id, to_type, to_id


def cmd_edge_meta_ls(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    from_type, from_id, to_type, to_id = _resolve_edge_meta_endpoints(conn, args, workspace.id)
    kind = args.kind
    meta = service.list_edge_metadata(conn, from_type, from_id, to_type, to_id, kind)
    records = _meta_records(meta)
    text = presenters.format_metadata_block(meta, indent=2) or "no metadata"
    return Ok(data=records, text=text)


def cmd_edge_meta_get(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    from_type, from_id, to_type, to_id = _resolve_edge_meta_endpoints(conn, args, workspace.id)
    kind = args.kind
    value = service.get_edge_meta(conn, from_type, from_id, to_type, to_id, kind, args.key)
    key = args.key.lower()
    return Ok(data={"key": key, "value": value}, text=value)


def cmd_edge_meta_set(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    from_type, from_id, to_type, to_id = _resolve_edge_meta_endpoints(conn, args, workspace.id)
    kind = args.kind
    service.set_edge_meta(conn, from_type, from_id, to_type, to_id, kind, args.key, args.value)
    key = args.key.lower()
    return Ok(
        data={"key": key, "value": args.value},
        text=f"set {key}={args.value} on edge ({from_type}:{from_id} → {to_type}:{to_id} [{kind}])",
    )


def cmd_edge_meta_del(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    from_type, from_id, to_type, to_id = _resolve_edge_meta_endpoints(conn, args, workspace.id)
    kind = args.kind
    removed = service.remove_edge_meta(conn, from_type, from_id, to_type, to_id, kind, args.key)
    key = args.key.lower()
    return Ok(
        data={"key": key, "value": removed},
        text=f"removed {key} from edge ({from_type}:{from_id} → {to_type}:{to_id} [{kind}])",
    )


# ---- Group subcommands ----


def cmd_group_create(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    title = args.title
    parent_id = None
    if "/" in title or ":" in title:
        # Path-as-title: last segment is the leaf title, prefix is the parent
        # path. Mutually exclusive with --parent (would be redundant or
        # conflicting).
        if ":" in title:
            raise ValueError(
                f"group title cannot contain ':' (reserved for path syntax): {title!r}"
            )
        if args.parent:
            raise ValueError(
                "cannot combine path-in-title with --parent; use one or the other"
            )
        segments = title.split("/")
        if any(not s for s in segments):
            raise ValueError(f"empty path segment in group title {title!r}")
        title = segments[-1]
        prefix = tuple(segments[:-1])
        if prefix:
            parent = service.resolve_group_path(conn, workspace.id, prefix)
            parent_id = parent.id
    elif args.parent:
        parent = service.resolve_group(conn, workspace.id, args.parent)
        parent_id = parent.id
    description = (args.desc or "").strip() or None
    grp = service.create_group(
        conn, workspace.id, title, parent_id=parent_id, description=description
    )
    return Ok(data=grp, text=f"created group '{grp.title}' ({format_group_num(grp.id)})")


def cmd_group_ls(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    include_archived = args.archived in ("include", "only")
    only_archived = args.archived == "only"
    refs = service.list_groups(
        conn,
        workspace.id,
        include_archived=include_archived,
        only_archived=only_archived,
    )
    return Ok(data=list(refs), text=presenters.format_group_list(refs))


def cmd_group_show(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.title)
    detail = service.get_group_detail(conn, grp.id)
    ancestry = service.get_group_ancestry(conn, grp.id)
    ancestry_titles = tuple(g.title for g in ancestry)
    text = presenters.format_group_detail(detail, ancestry_titles)
    return Ok(data=detail, text=text)


def cmd_group_edit(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.title)
    changes: dict[str, Any] = {}
    if args.new_title is not None:
        changes["title"] = args.new_title
    if args.desc is not None:
        changes["description"] = args.desc.strip() or None
    if args.dry_run:
        preview = service.preview_update_group(conn, grp.id, changes)
        return Ok(data=preview, text=presenters.format_entity_update_preview(preview))
    if not changes:
        return Ok(data=grp, text="nothing to update")
    old_title = grp.title
    updated = service.update_group(conn, grp.id, changes)
    if "title" in changes and changes["title"] != old_title:
        return Ok(data=updated, text=f"renamed group '{old_title}' -> '{updated.title}'")
    return Ok(data=updated, text=f"updated group '{updated.title}'")


def cmd_group_log(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.title)
    from .models import EntityType

    history = service.list_journal(conn, EntityType.GROUP, grp.id)
    return Ok(data=history, text=presenters.format_journal_entries(history))


def cmd_group_archive(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.title)
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
    grp = service.resolve_group(conn, workspace.id, args.title)
    promote = args.parent == "/"
    if promote:
        changes: dict[str, Any] = {"parent_id": None}
    else:
        parent = service.resolve_group(conn, workspace.id, args.parent)
        changes = {"parent_id": parent.id}
    if args.dry_run:
        preview = service.preview_update_group(conn, grp.id, changes)
        return Ok(data=preview, text=presenters.format_entity_update_preview(preview))
    updated = service.update_group(conn, grp.id, changes)
    if promote:
        return Ok(data=updated, text=f"promoted group '{grp.title}' to top-level")
    parent_title = service.get_group(conn, changes["parent_id"]).title
    return Ok(data=updated, text=f"moved group '{grp.title}' under '{parent_title}'")


def cmd_group_assign(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    grp = service.resolve_group(conn, workspace.id, args.title)
    service.assign_task_to_group(conn, task_id, grp.id, source="cli")
    detail = service.get_task_detail(conn, task_id)
    return Ok(
        data=detail,
        text=f"assigned {format_task_num(task_id)} to group '{grp.title}'",
    )


def cmd_group_unassign(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    # Get the group title before unassigning for the output message
    detail = service.get_task_detail(conn, task_id)
    group_name = detail.group.title if detail.group else None
    service.unassign_task_from_group(conn, task_id, source="cli")
    detail = service.get_task_detail(conn, task_id)
    suffix = f" from group '{group_name}'" if group_name else " from group"
    return Ok(data=detail, text=f"unassigned {format_task_num(task_id)}{suffix}")


# ---- Context ----


def cmd_workspace_show(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    if args.name:
        workspace = service.get_workspace_by_name(conn, args.name)
    else:
        workspace = _resolve_workspace(conn, args, ctx)
    ws_ctx = service.get_workspace_context(conn, workspace.id)
    return Ok(data=ws_ctx, text=presenters.format_workspace_context(ws_ctx))


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
        raise ValueError(
            f"destination already exists: {output_path} (use --overwrite to overwrite)"
        )
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


# ---- Next ----


def cmd_next(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    edge_kinds = frozenset(args.edge_kind) if args.edge_kind else None
    view = service.compute_next_tasks(
        conn,
        workspace.id,
        rank=args.rank,
        include_blocked=args.include_blocked,
        edge_kinds=edge_kinds,
    )
    ready = view.ready
    if args.limit is not None and args.limit >= 0:
        ready = ready[: args.limit]
    payload_view = (
        view if args.limit is None else dataclasses.replace(view, ready=ready)
    )
    text = presenters.format_next_tasks(payload_view)
    return Ok(data=payload_view, text=text)


# ---- Graph ----


def cmd_graph(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    if args.kind:
        seen: set[tuple[str, int, str, int]] = set()
        edge_list: list = []
        for k in args.kind:
            for e in service.list_edges(conn, workspace.id, kind=k):
                key = (e.from_type, e.from_id, e.to_type, e.to_id)
                if key not in seen:
                    seen.add(key)
                    edge_list.append(e)
        edges = tuple(edge_list)
    else:
        edges = service.list_edges(conn, workspace.id)
    if not edges:
        return Ok(data={"path": None}, text="no edges in workspace")
    fmt = GraphFormat(args.format)
    output = Path(args.output) if args.output else None
    path = write_graph(edges, workspace.name, fmt, output=output)
    return Ok(data={"path": str(path), "format": fmt.value}, text=f"wrote {path}")


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
    lines = ["stx files:"]
    for _, label, p in entries:
        marker = "exists" if p.exists() else "missing"
        lines.append(f"  {label:<{width}}  {p}  [{marker}]")
    return Ok(data=data, text="\n".join(lines))


# ---- TUI ----


# ---- Metadata helpers (shared across entity types) ----


def _meta_records(metadata: dict[str, str]) -> list[dict[str, str]]:
    return [{"key": k, "value": v} for k, v in sorted(metadata.items())]


# ---- Task metadata ----


def cmd_task_meta_ls(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    task = service.get_task(conn, task_id)
    records = _meta_records(task.metadata)
    text = presenters.format_metadata_block(task.metadata, indent=2) or "no metadata"
    return Ok(data=records, text=text)


def cmd_task_meta_get(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    value = service.get_task_meta(conn, task_id, args.key)
    key = args.key.lower()
    return Ok(data={"key": key, "value": value}, text=value)


def cmd_task_meta_set(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    service.set_task_meta(conn, task_id, args.key, args.value)
    key = args.key.lower()
    return Ok(
        data={"key": key, "value": args.value},
        text=f"set {key}={args.value} on task {format_task_num(task_id)}",
    )


def cmd_task_meta_del(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    task_id = _resolve_task(conn, workspace, args.task)
    removed = service.remove_task_meta(conn, task_id, args.key)
    key = args.key.lower()
    return Ok(
        data={"key": key, "value": removed},
        text=f"removed {key} from task {format_task_num(task_id)}",
    )


# ---- Workspace metadata ----


def cmd_workspace_meta_ls(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    records = _meta_records(workspace.metadata)
    text = presenters.format_metadata_block(workspace.metadata, indent=2) or "no metadata"
    return Ok(data=records, text=text)


def cmd_workspace_meta_get(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    value = service.get_workspace_meta(conn, workspace.id, args.key)
    key = args.key.lower()
    return Ok(data={"key": key, "value": value}, text=value)


def cmd_workspace_meta_set(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    service.set_workspace_meta(conn, workspace.id, args.key, args.value)
    key = args.key.lower()
    return Ok(
        data={"key": key, "value": args.value},
        text=f"set {key}={args.value} on workspace '{workspace.name}'",
    )


def cmd_workspace_meta_del(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    removed = service.remove_workspace_meta(conn, workspace.id, args.key)
    key = args.key.lower()
    return Ok(
        data={"key": key, "value": removed}, text=f"removed {key} from workspace '{workspace.name}'"
    )


# ---- Group metadata ----


def cmd_group_meta_ls(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.title)
    records = _meta_records(grp.metadata)
    text = presenters.format_metadata_block(grp.metadata, indent=2) or "no metadata"
    return Ok(data=records, text=text)


def cmd_group_meta_get(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.title)
    value = service.get_group_meta(conn, grp.id, args.key)
    key = args.key.lower()
    return Ok(data={"key": key, "value": value}, text=value)


def cmd_group_meta_set(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.title)
    service.set_group_meta(conn, grp.id, args.key, args.value)
    key = args.key.lower()
    return Ok(
        data={"key": key, "value": args.value},
        text=f"set {key}={args.value} on group '{grp.title}'",
    )


def cmd_group_meta_del(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    workspace = _resolve_workspace(conn, args, ctx)
    grp = service.resolve_group(conn, workspace.id, args.title)
    removed = service.remove_group_meta(conn, grp.id, args.key)
    key = args.key.lower()
    return Ok(data={"key": key, "value": removed}, text=f"removed {key} from group '{grp.title}'")


def cmd_tui(conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext) -> CmdResult:
    conn.close()
    from stx.tui import main as tui_main

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


def cmd_config_get(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    from dataclasses import fields

    from .tui.config import TuiConfig, load_config

    all_keys = {f.name for f in fields(TuiConfig)}
    if args.key not in all_keys:
        raise LookupError(f"unknown config key: {args.key!r}")
    config = load_config(ctx.config_path)
    value = getattr(config, args.key)
    return Ok(data={"key": args.key, "value": value}, text=str(value))


def cmd_config_set(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    from .tui.config import load_config, save_config

    if args.key not in _CONFIG_EDITABLE:
        raise ValueError(
            f"config key {args.key!r} is not editable via CLI (editable: {', '.join(sorted(_CONFIG_EDITABLE))})"
        )
    new_value = _CONFIG_VALIDATORS[args.key](conn, args.value)
    config = load_config(ctx.config_path)
    setattr(config, args.key, new_value)
    save_config(config, ctx.config_path)
    return Ok(data={"key": args.key, "value": new_value}, text=f"set {args.key} = {new_value}")


def cmd_config_del(
    conn: sqlite3.Connection, args: argparse.Namespace, ctx: RunContext
) -> CmdResult:
    from dataclasses import fields

    from .tui.config import TuiConfig, load_config, save_config

    if args.key not in _CONFIG_EDITABLE:
        raise ValueError(
            f"config key {args.key!r} is not editable via CLI (editable: {', '.join(sorted(_CONFIG_EDITABLE))})"
        )
    default_value = next(f.default for f in fields(TuiConfig) if f.name == args.key)
    config = load_config(ctx.config_path)
    setattr(config, args.key, default_value)
    save_config(config, ctx.config_path)
    return Ok(
        data={"key": args.key, "value": default_value},
        text=f"deleted {args.key} (reset to {default_value!r})",
    )


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
    "task_done": cmd_task_done,
    "task_undone": cmd_task_undone,
    "task_meta_ls": cmd_task_meta_ls,
    "task_meta_get": cmd_task_meta_get,
    "task_meta_set": cmd_task_meta_set,
    "task_meta_del": cmd_task_meta_del,
    "workspace_create": cmd_workspace_create,
    "workspace_ls": cmd_workspace_ls,
    "workspace_use": cmd_workspace_use,
    "workspace_edit": cmd_workspace_edit,
    "workspace_log": cmd_workspace_log,
    "workspace_archive": cmd_workspace_archive,
    "workspace_meta_ls": cmd_workspace_meta_ls,
    "workspace_meta_get": cmd_workspace_meta_get,
    "workspace_meta_set": cmd_workspace_meta_set,
    "workspace_meta_del": cmd_workspace_meta_del,
    "status_create": cmd_status_create,
    "status_ls": cmd_status_ls,
    "status_show": cmd_status_show,
    "status_edit": cmd_status_edit,
    "status_order": cmd_status_order,
    "status_archive": cmd_status_archive,
    "edge_create": cmd_edge_create,
    "edge_archive": cmd_edge_archive,
    "edge_ls": cmd_edge_ls,
    "edge_show": cmd_edge_show,
    "edge_edit": cmd_edge_edit,
    "edge_log": cmd_edge_log,
    "edge_meta_ls": cmd_edge_meta_ls,
    "edge_meta_get": cmd_edge_meta_get,
    "edge_meta_set": cmd_edge_meta_set,
    "edge_meta_del": cmd_edge_meta_del,
    "group_create": cmd_group_create,
    "group_ls": cmd_group_ls,
    "group_show": cmd_group_show,
    "group_edit": cmd_group_edit,
    "group_log": cmd_group_log,
    "group_archive": cmd_group_archive,
    "group_mv": cmd_group_mv,
    "group_assign": cmd_group_assign,
    "group_unassign": cmd_group_unassign,
    "group_meta_ls": cmd_group_meta_ls,
    "group_meta_get": cmd_group_meta_get,
    "group_meta_set": cmd_group_meta_set,
    "group_meta_del": cmd_group_meta_del,
    "workspace_show": cmd_workspace_show,
    "config_ls": cmd_config_ls,
    "config_get": cmd_config_get,
    "config_set": cmd_config_set,
    "config_del": cmd_config_del,
    "export": cmd_export,
    "backup": cmd_backup,
    "info": cmd_info,
    "next": cmd_next,
    "graph": cmd_graph,
    "tui": cmd_tui,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stx", description="stx — structured context and task management"
    )
    parser.add_argument("--db", type=Path, help="path to SQLite database file")
    parser.add_argument(
        "--config", type=Path, help="path to tui.toml (default: ~/.config/stx/tui.toml)"
    )
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
    p_create.add_argument("--priority", "-p", type=int, default=1)
    p_create.add_argument("--due", default=None, help="YYYY-MM-DD")
    p_create.add_argument("--group", "-g", default=None, help="group title")

    p_ls = task_sub.add_parser("ls", help="list tasks")
    p_ls.set_defaults(command="task_ls")
    p_ls.add_argument(
        "--archived",
        choices=["hide", "include", "only"],
        default="hide",
        help="archived visibility: hide (default), include, or only",
    )
    p_ls.add_argument("--status", "-S", default=None, help="filter by status name")
    p_ls.add_argument("--priority", "-p", type=int, default=None, help="filter by priority integer")
    p_ls.add_argument("--search", default=None, help="search title substring")
    p_ls.add_argument("--group", "-g", default=None, help="filter by group title")

    p_show = task_sub.add_parser("show", help="show task detail")
    p_show.set_defaults(command="task_show")
    p_show.add_argument("task", help="task number (task-NNNN/N/#N) or title")

    p_edit = task_sub.add_parser("edit", help="edit a task")
    p_edit.set_defaults(command="task_edit")
    p_edit.add_argument("task", help="task number (task-NNNN/N/#N) or title")
    p_edit.add_argument("--title", default=None)
    p_edit.add_argument("--desc", "-d", default=None)
    p_edit.add_argument("--priority", "-p", type=int, default=None)
    p_edit.add_argument("--due", default=None, help="YYYY-MM-DD")
    p_edit.add_argument(
        "--group",
        "-g",
        default=None,
        help="group title to assign; pass empty string to unassign",
    )
    p_edit.add_argument("--dry-run", action="store_true", help="preview changes without writing")

    p_mv = task_sub.add_parser("mv", help="move task to status (within workspace)")
    p_mv.set_defaults(command="task_mv")
    p_mv.add_argument("task", help="task number (task-NNNN/N/#N) or title")
    p_mv.add_argument("--status", "-S", required=True, help="target status name")
    p_mv.add_argument("--dry-run", action="store_true", help="preview move without writing")

    p_transfer = task_sub.add_parser("transfer", help="move task to a different workspace")
    p_transfer.set_defaults(command="task_transfer")
    p_transfer.add_argument("task", help="task number (task-NNNN/N/#N) or title")
    p_transfer.add_argument(
        "--to", dest="to_workspace", required=True, help="target workspace name"
    )
    p_transfer.add_argument("--status", "-S", required=True, help="status on target workspace")
    p_transfer.add_argument("--dry-run", action="store_true", help="preview without executing")

    p_tarch = task_sub.add_parser("archive", help="archive a task (with confirmation)")
    p_tarch.set_defaults(command="task_archive")
    p_tarch.add_argument("task", help="task number (task-NNNN/N/#N) or title")
    p_tarch.add_argument("--force", action="store_true", help="skip confirmation prompt")
    p_tarch.add_argument("--dry-run", action="store_true", help="preview without executing")

    p_log = task_sub.add_parser("log", help="show task change log")
    p_log.set_defaults(command="task_log")
    p_log.add_argument("task", help="task number (task-NNNN/N/#N) or title")

    p_tdone = task_sub.add_parser("done", help="mark task done (independent of status)")
    p_tdone.set_defaults(command="task_done")
    p_tdone.add_argument("task", help="task number (task-NNNN/N/#N) or title")

    p_tundone = task_sub.add_parser("undone", help="flip a task back to not-done")
    p_tundone.set_defaults(command="task_undone")
    p_tundone.add_argument("task", help="task number (task-NNNN/N/#N) or title")
    p_tundone.add_argument(
        "--force", action="store_true", help="skip confirmation prompt"
    )

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
    p_wl.add_argument(
        "--archived",
        choices=["hide", "include", "only"],
        default="hide",
        help="archived visibility: hide (default), include, or only",
    )

    p_wu = workspace_sub.add_parser("use", help="switch active workspace")
    p_wu.set_defaults(command="workspace_use")
    p_wu.add_argument("name")

    p_we = workspace_sub.add_parser("edit", help="edit a workspace (rename, etc.)")
    p_we.set_defaults(command="workspace_edit")
    p_we.add_argument(
        "--name",
        default=None,
        help="new workspace name (renames the workspace)",
    )
    p_we.add_argument("--dry-run", action="store_true", help="preview changes without writing")

    p_wsh = workspace_sub.add_parser(
        "show", help="workspace snapshot: statuses, tasks, groups"
    )
    p_wsh.set_defaults(command="workspace_show")
    p_wsh.add_argument(
        "name", nargs="?", default=None, help="workspace name (default: active workspace)"
    )

    p_warc = workspace_sub.add_parser(
        "archive", help="cascade-archive workspace and all descendants"
    )
    p_warc.set_defaults(command="workspace_archive")
    p_warc.add_argument(
        "name", nargs="?", default=None, help="workspace name (default: active workspace)"
    )
    p_warc.add_argument("--force", action="store_true", help="skip confirmation prompt")
    p_warc.add_argument("--dry-run", action="store_true", help="preview without executing")

    p_wlog = workspace_sub.add_parser("log", help="show workspace journal / change history")
    p_wlog.set_defaults(command="workspace_log")

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
    p_cl.add_argument(
        "--archived",
        choices=["hide", "include", "only"],
        default="hide",
        help="archived visibility: hide (default), include, or only",
    )

    p_csh = status_sub.add_parser("show", help="show status detail")
    p_csh.set_defaults(command="status_show")
    p_csh.add_argument("name")

    p_cedit = status_sub.add_parser("edit", help="edit a status (rename, etc.)")
    p_cedit.set_defaults(command="status_edit")
    p_cedit.add_argument("name", help="existing status name")
    p_cedit.add_argument(
        "--name",
        dest="new_name",
        default=None,
        help="new status name (renames the status)",
    )
    p_cedit_term = p_cedit.add_mutually_exclusive_group()
    p_cedit_term.add_argument(
        "--terminal",
        dest="terminal",
        action="store_const",
        const=True,
        default=None,
        help="mark status terminal: tasks moved into it auto-set done=1",
    )
    p_cedit_term.add_argument(
        "--no-terminal",
        dest="terminal",
        action="store_const",
        const=False,
        help="unmark terminal: tasks moved into it auto-set done=0",
    )

    p_corder = status_sub.add_parser(
        "order", help="set status display order for active workspace (used by TUI)"
    )
    p_corder.set_defaults(command="status_order")
    p_corder.add_argument("statuses", nargs="+", help="status names in desired order")

    p_carch = status_sub.add_parser("archive", help="archive a status")
    p_carch.set_defaults(command="status_archive")
    p_carch.add_argument("name")
    p_carch.add_argument(
        "--reassign-to", default=None, metavar="STATUS", help="move tasks to this status"
    )
    p_carch.add_argument("--force", action="store_true", help="archive tasks instead of blocking")
    p_carch.add_argument("--dry-run", action="store_true", help="preview without executing")

    # ---- Edge subcommands ----

    p_edge = sub.add_parser(
        "edge",
        help="polymorphic edge management (kinded links between tasks, groups, workspaces, statuses)",
    )
    edge_sub = p_edge.add_subparsers()

    _edge_ref_help = (
        "node ref. Type inferred from delimiters: "
        "task-NNNN/#N/int -> task by id; /A or /A/B/C (leading slash) "
        "-> group path; A/B/C (multi-seg) -> group path; "
        "A:leaf or :leaf -> task path; bare title -> task. "
        "Override with explicit prefix: group:<path>, task:<path>, "
        "workspace:<name>, status:<name>"
    )

    p_ea = edge_sub.add_parser("create", help="add an edge")
    p_ea.set_defaults(command="edge_create")
    p_ea.add_argument("--source", "-s", required=True, help=f"source node — {_edge_ref_help}")
    p_ea.add_argument("--target", "-t", required=True, help=f"target node — {_edge_ref_help}")
    p_ea.add_argument("--kind", "-k", required=True, help="edge kind (e.g. blocks, spawns, informs)")
    p_ea_acyclic = p_ea.add_mutually_exclusive_group()
    p_ea_acyclic.add_argument(
        "--acyclic", dest="acyclic", action="store_const", const=True, default=None,
        help="enforce DAG constraint (default: on for blocks/spawns, off otherwise)",
    )
    p_ea_acyclic.add_argument(
        "--no-acyclic", dest="acyclic", action="store_const", const=False,
        help="disable DAG constraint for this edge",
    )

    p_er = edge_sub.add_parser("archive", help="archive an edge")
    p_er.set_defaults(command="edge_archive")
    p_er.add_argument("--source", "-s", required=True, help=f"source node — {_edge_ref_help}")
    p_er.add_argument("--target", "-t", required=True, help=f"target node — {_edge_ref_help}")
    p_er.add_argument("--kind", "-k", required=True, help="edge kind to archive")

    p_els = edge_sub.add_parser("ls", help="list edges in workspace")
    p_els.set_defaults(command="edge_ls")
    p_els.add_argument("--source", "-s", default=None, help=f"filter by source node — {_edge_ref_help}")
    p_els.add_argument("--target", "-t", default=None, help=f"filter by target node — {_edge_ref_help}")
    p_els.add_argument("--kind", "-k", default=None, help="filter by edge kind")

    p_emeta = edge_sub.add_parser("meta", help="edge metadata management")
    emeta_sub = p_emeta.add_subparsers()

    def _add_edge_meta_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--source", "-s", required=True, help=f"source node — {_edge_ref_help}")
        p.add_argument("--target", "-t", required=True, help=f"target node — {_edge_ref_help}")
        p.add_argument("--kind", "-k", required=True, help="edge kind")

    p_emeta_ls = emeta_sub.add_parser("ls", help="list all edge metadata")
    p_emeta_ls.set_defaults(command="edge_meta_ls")
    _add_edge_meta_args(p_emeta_ls)

    p_emeta_get = emeta_sub.add_parser("get", help="get an edge metadata value")
    p_emeta_get.set_defaults(command="edge_meta_get")
    _add_edge_meta_args(p_emeta_get)
    p_emeta_get.add_argument("key")

    p_emeta_set = emeta_sub.add_parser("set", help="set an edge metadata key/value")
    p_emeta_set.set_defaults(command="edge_meta_set")
    _add_edge_meta_args(p_emeta_set)
    p_emeta_set.add_argument("key")
    p_emeta_set.add_argument("value")

    p_emeta_del = emeta_sub.add_parser("del", help="delete an edge metadata key")
    p_emeta_del.set_defaults(command="edge_meta_del")
    _add_edge_meta_args(p_emeta_del)
    p_emeta_del.add_argument("key")

    p_esh = edge_sub.add_parser("show", help="show edge detail")
    p_esh.set_defaults(command="edge_show")
    _add_edge_meta_args(p_esh)

    p_eed = edge_sub.add_parser("edit", help="edit edge fields (acyclic flag)")
    p_eed.set_defaults(command="edge_edit")
    _add_edge_meta_args(p_eed)
    p_eed_acyclic = p_eed.add_mutually_exclusive_group()
    p_eed_acyclic.add_argument(
        "--acyclic", dest="acyclic", action="store_const", const=True, default=None,
        help="enable DAG constraint (re-runs cycle detection)",
    )
    p_eed_acyclic.add_argument(
        "--no-acyclic", dest="acyclic", action="store_const", const=False,
        help="disable DAG constraint",
    )

    p_elog = edge_sub.add_parser("log", help="show edge journal / change history")
    p_elog.set_defaults(command="edge_log")
    _add_edge_meta_args(p_elog)

    # ---- Group subcommands ----

    p_grp = sub.add_parser("group", help="group management")
    grp_sub = p_grp.add_subparsers()

    p_gc = grp_sub.add_parser("create", help="create a group")
    p_gc.set_defaults(command="group_create")
    p_gc.add_argument("title")
    p_gc.add_argument("--desc", "-d", default=None, help="group description")
    p_gc.add_argument("--parent", default=None, help="parent group title")

    p_gl = grp_sub.add_parser("ls", help="list groups")
    p_gl.set_defaults(command="group_ls")
    p_gl.add_argument(
        "--archived",
        choices=["hide", "include", "only"],
        default="hide",
        help="archived visibility: hide (default), include, or only",
    )

    p_gs = grp_sub.add_parser("show", help="show group detail")
    p_gs.set_defaults(command="group_show")
    p_gs.add_argument("title")

    p_ge = grp_sub.add_parser("edit", help="edit a group")
    p_ge.set_defaults(command="group_edit")
    p_ge.add_argument("title")
    p_ge.add_argument(
        "--title",
        dest="new_title",
        default=None,
        help="new group title (renames the group)",
    )
    p_ge.add_argument("--desc", "-d", default=None, help="group description")
    p_ge.add_argument("--dry-run", action="store_true", help="preview changes without writing")

    p_glog = grp_sub.add_parser("log", help="show group journal / change history")
    p_glog.set_defaults(command="group_log")
    p_glog.add_argument("title")

    p_garc = grp_sub.add_parser(
        "archive", help="cascade-archive group and all descendant groups/tasks"
    )
    p_garc.set_defaults(command="group_archive")
    p_garc.add_argument("title")
    p_garc.add_argument("--force", action="store_true", help="skip confirmation prompt")
    p_garc.add_argument("--dry-run", action="store_true", help="preview without executing")

    p_gmv = grp_sub.add_parser("mv", help="reparent a group")
    p_gmv.set_defaults(command="group_mv")
    p_gmv.add_argument("title")
    p_gmv.add_argument(
        "--parent",
        required=True,
        help="new parent group ref ('/' for root, or a path like '/Backend' or 'A/B')",
    )
    p_gmv.add_argument("--dry-run", action="store_true", help="preview reparent without writing")

    p_gasn = grp_sub.add_parser("assign", help="assign task to group")
    p_gasn.set_defaults(command="group_assign")
    p_gasn.add_argument("task", help="task number or title")
    p_gasn.add_argument("title", help="group title")

    p_gun = grp_sub.add_parser("unassign", help="unassign task from group")
    p_gun.set_defaults(command="group_unassign")
    p_gun.add_argument("task", help="task number or title")

    p_gmeta = grp_sub.add_parser("meta", help="group metadata key/value management")
    gmeta_sub = p_gmeta.add_subparsers()

    p_gmeta_ls = gmeta_sub.add_parser("ls", help="list all metadata")
    p_gmeta_ls.set_defaults(command="group_meta_ls")
    p_gmeta_ls.add_argument("title", help="group title")

    p_gmeta_get = gmeta_sub.add_parser("get", help="get a metadata value")
    p_gmeta_get.set_defaults(command="group_meta_get")
    p_gmeta_get.add_argument("title", help="group title")
    p_gmeta_get.add_argument("key")

    p_gmeta_set = gmeta_sub.add_parser("set", help="set a metadata key/value")
    p_gmeta_set.set_defaults(command="group_meta_set")
    p_gmeta_set.add_argument("title", help="group title")
    p_gmeta_set.add_argument("key")
    p_gmeta_set.add_argument("value")

    p_gmeta_del = gmeta_sub.add_parser("del", help="delete a metadata key")
    p_gmeta_del.set_defaults(command="group_meta_del")
    p_gmeta_del.add_argument("title", help="group title")
    p_gmeta_del.add_argument("key")

    # ---- Config subcommands ----

    p_config = sub.add_parser("config", help="TUI config management (tui.toml)")
    config_sub = p_config.add_subparsers()

    p_cfg_ls = config_sub.add_parser("ls", help="show all config values")
    p_cfg_ls.set_defaults(command="config_ls")

    p_cfg_get = config_sub.add_parser("get", help="get a config value")
    p_cfg_get.set_defaults(command="config_get")
    p_cfg_get.add_argument("key", help="config key name")

    p_cfg_set = config_sub.add_parser(
        "set", help="set a config value (auto_refresh_seconds, active_workspace)"
    )
    p_cfg_set.set_defaults(command="config_set")
    p_cfg_set.add_argument("key", help="config key name")
    p_cfg_set.add_argument("value", help="new value")

    p_cfg_del = config_sub.add_parser("del", help="reset a config value to its default")
    p_cfg_del.set_defaults(command="config_del")
    p_cfg_del.add_argument("key", help="config key name")

    # ---- Export ----

    p_export = sub.add_parser("export", help="export database as JSON (default) or markdown (--md)")
    p_export.set_defaults(command="export")
    p_export.add_argument("--md", action="store_true", help="export as markdown instead of JSON")
    p_export.add_argument("-o", "--output", help="write to file instead of stdout")
    p_export.add_argument(
        "--overwrite", action="store_true", help="overwrite destination file if it exists"
    )

    # ---- Backup ----

    p_backup = sub.add_parser(
        "backup", help="atomic binary DB snapshot (safe pre-migration backup)"
    )
    p_backup.set_defaults(command="backup")
    p_backup.add_argument("dest", help="destination .db file path")
    p_backup.add_argument(
        "--overwrite", action="store_true", help="overwrite destination if it exists"
    )

    # ---- Next ----

    p_next = sub.add_parser(
        "next",
        help="compute next actionable tasks via topo sort of an acyclic edge DAG",
    )
    p_next.set_defaults(command="next")
    p_next.add_argument(
        "--rank",
        action="store_true",
        help="sort the ready list by priority desc, due_date asc, id asc",
    )
    p_next.add_argument(
        "--include-blocked",
        action="store_true",
        help="return the full topological order of all not-done tasks instead of just the ready frontier",
    )
    p_next.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cap the ready list to N items (applied after ranking/topo sort)",
    )
    p_next.add_argument(
        "--edge-kind",
        action="append",
        metavar="KIND",
        default=None,
        help=(
            "edge kind(s) to use when building the dependency DAG "
            "(default: blocks). Repeatable: --edge-kind blocks --edge-kind spawns"
        ),
    )

    # ---- Graph ----

    p_graph = sub.add_parser("graph", help="generate a DOT or Mermaid graph of workspace edges")
    p_graph.set_defaults(command="graph")
    p_graph.add_argument(
        "-f", "--format", choices=["dot", "mermaid"], default="dot",
        help="output format (default: dot)",
    )
    p_graph.add_argument(
        "-k", "--kind", action="append", metavar="KIND", default=None,
        help="filter edges by kind (repeatable: -k blocks -k spawns)",
    )
    p_graph.add_argument("-o", "--output", help="write to file instead of temp file")

    # ---- Info ----

    p_info = sub.add_parser("info", help="show stx file locations")
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

    ctx = RunContext(
        db_path=args.db or DEFAULT_DB_PATH, config_path=args.config or DEFAULT_CONFIG_PATH
    )
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
    except ConflictError as exc:
        code = "conflict"
        if json_mode:
            _json_err(str(exc), code)
        else:
            _text_err(str(exc), code)
        raise SystemExit(EXIT_CONFLICT)
    except ValueError as exc:
        code = "validation"
        if json_mode:
            _json_err(str(exc), code)
        else:
            _text_err(str(exc), code)
        raise SystemExit(EXIT_VALIDATION)
    finally:
        conn.close()
