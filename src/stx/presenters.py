"""Text rendering for CLI output. Pure functions over structured service-layer
types; no DB access, no argparse. Each presenter returns a string ready for
stdout."""

from __future__ import annotations

from dataclasses import fields

from .formatting import format_group_num, format_priority, format_task_num, format_timestamp
from .models import JournalEntry, Status, Tag, Workspace
from .service_models import (
    ArchivePreview,
    EntityUpdatePreview,
    GroupDetail,
    GroupRef,
    MoveToWorkspacePreview,
    TaskDetail,
    TaskMovePreview,
    WorkspaceContext,
    WorkspaceListView,
)


def _empty(entity: str) -> str:
    return f"no {entity}s"


def format_metadata_block(metadata: dict[str, str], indent: int = 2) -> str:
    """Render a metadata dict as indented 'key: value' lines.

    Returns an empty string when the dict is empty (callers can skip the
    'Metadata:' header entirely in that case).
    """
    if not metadata:
        return ""
    pad = " " * indent
    return "\n".join(f"{pad}{k}: {v}" for k, v in sorted(metadata.items()))


def format_history_entry(h: JournalEntry) -> str:
    old_str = h.old_value if h.old_value is not None else "(none)"
    new_str = h.new_value if h.new_value is not None else "(none)"
    return f"{format_timestamp(h.changed_at)}  {h.field}: {old_str} -> {new_str}  ({h.source})"


def format_task_history(history: tuple[JournalEntry, ...]) -> str:
    if not history:
        return "no history"
    return "\n".join(format_history_entry(h) for h in history)


def format_workspace_list(workspaces: tuple[Workspace, ...], active_id: int | None) -> str:
    if not workspaces:
        return _empty("workspace")
    lines: list[str] = []
    for w in workspaces:
        marker = " *" if w.id == active_id else ""
        archived = " (archived)" if w.archived else ""
        lines.append(f"  {w.name}{marker}{archived}")
    return "\n".join(lines)


def format_status_list(statuses: tuple[Status, ...]) -> str:
    if not statuses:
        return "no statuses"
    lines: list[str] = []
    for s in statuses:
        archived = " (archived)" if s.archived else ""
        lines.append(f"  {s.name}{archived}")
    return "\n".join(lines)


def format_tag_list(tags: tuple[Tag, ...]) -> str:
    if not tags:
        return _empty("tag")
    lines: list[str] = []
    for t in tags:
        archived = " (archived)" if t.archived else ""
        lines.append(f"  {t.name}{archived}")
    return "\n".join(lines)


def format_task_detail(detail: TaskDetail) -> str:
    lines = [f"{format_task_num(detail.id)}  {detail.title}"]
    lines.append(f"  Status:      {detail.status.name}")
    if detail.group is not None:
        lines.append(f"  Group:       {detail.group.title} ({format_group_num(detail.group.id)})")
    if detail.tags:
        tag_str = ", ".join(t.name for t in detail.tags)
        lines.append(f"  Tags:        {tag_str}")
    if detail.metadata:
        lines.append("  Metadata:")
        lines.append(format_metadata_block(detail.metadata, indent=4))
    lines.append(f"  Priority:    {detail.priority}")
    if detail.due_date:
        lines.append(f"  Due:         {format_timestamp(detail.due_date)}")
    lines.append(f"  Created:     {format_timestamp(detail.created_at)}")
    if detail.edge_sources:
        items = ", ".join(
            f"{format_task_num(ref.task.id)} ({ref.kind})" for ref in detail.edge_sources
        )
        lines.append(f"  Edge sources: {items}")
    if detail.edge_targets:
        items = ", ".join(
            f"{format_task_num(ref.task.id)} ({ref.kind})" for ref in detail.edge_targets
        )
        lines.append(f"  Edge targets: {items}")
    if detail.description:
        lines.append(f"\n  Description:\n    {detail.description}")
    if detail.history:
        lines.append("\n  History:")
        for h in detail.history:
            lines.append(f"    {format_history_entry(h)}")
    return "\n".join(lines)


def format_workspace_list_view(view: WorkspaceListView) -> str:
    lines: list[str] = []
    for i, col in enumerate(view.statuses):
        if i > 0:
            lines.append("")
        lines.append(f"== {col.status.name} ==")
        if not col.tasks:
            lines.append("  (empty)")
            continue
        for item in col.tasks:
            parts = [f"  {format_task_num(item.id)}  {format_priority(item.priority)} {item.title}"]
            if item.tag_names:
                parts.append(f"  [{', '.join(item.tag_names)}]")
            lines.append("".join(parts))
    return "\n".join(lines)


def format_workspace_context(ctx: WorkspaceContext) -> str:
    lines: list[str] = [f"== {ctx.view.workspace.name} =="]
    if ctx.view.workspace.metadata:
        lines.append("Metadata:")
        lines.append(format_metadata_block(ctx.view.workspace.metadata, indent=2))
    view_str = format_workspace_list_view(ctx.view)
    if view_str:
        lines.append(view_str)
    if ctx.tags:
        lines.append(f"Tags: {', '.join(t.name for t in ctx.tags)}")
    if ctx.groups:
        group_strs = [g.title for g in ctx.groups]
        lines.append(f"Groups: {', '.join(group_strs)}")
    return "\n".join(lines)


def format_group_list(groups: tuple[GroupRef, ...]) -> str:
    if not groups:
        return _empty("group")
    lines: list[str] = []
    for ref in groups:
        archived = " (archived)" if ref.archived else ""
        lines.append(
            f"  {format_group_num(ref.id)}  {ref.title}  ({len(ref.task_ids)} tasks){archived}"
        )
    return "\n".join(lines)


def format_group_detail(
    detail: GroupDetail,
    ancestry_titles: tuple[str, ...],
) -> str:
    lines = [f"{format_group_num(detail.id)}  {detail.title}"]
    if detail.description:
        lines.append(f"  Description: {detail.description}")
    lines.append(f"  Path:        {' > '.join(ancestry_titles)}")
    lines.append(f"  Tasks:       {len(detail.tasks)}")
    if detail.metadata:
        lines.append("  Metadata:")
        lines.append(format_metadata_block(detail.metadata, indent=4))
    if detail.children:
        child_names = ", ".join(c.title for c in detail.children)
        lines.append(f"  Sub-groups: {child_names}")
    if detail.edge_sources:
        items = ", ".join(
            f"{format_group_num(ref.group.id)} ({ref.kind})" for ref in detail.edge_sources
        )
        lines.append(f"  Edge sources: {items}")
    if detail.edge_targets:
        items = ", ".join(
            f"{format_group_num(ref.group.id)} ({ref.kind})" for ref in detail.edge_targets
        )
        lines.append(f"  Edge targets: {items}")
    if detail.tasks:
        lines.append("")
        for t in detail.tasks:
            due = f"  due: {format_timestamp(t.due_date)}" if t.due_date else ""
            lines.append(f"  {format_task_num(t.id)}  {format_priority(t.priority)} {t.title}{due}")
    return "\n".join(lines)


def format_move_preview(
    preview: MoveToWorkspacePreview,
    target_workspace_name: str,
    target_status_name: str,
    *,
    source_workspace_name: str,
) -> str:
    lines = [f"dry-run: would transfer {format_task_num(preview.task_id)} ({preview.task_title})"]
    dest = f"workspace '{target_workspace_name}' / status '{target_status_name}'"
    lines.append(f"  from workspace '{source_workspace_name}' -> {dest}")
    if not preview.can_move:
        if preview.edge_ids:
            edge_list = ", ".join(format_task_num(d) for d in preview.edge_ids)
            lines.append(f"  \u26a0 has active edges: {edge_list}")
            lines.append("  move would FAIL \u2014 archive edges first")
        else:
            lines.append(f"  \u26a0 {preview.blocking_reason}")
            lines.append("  move would FAIL")
    else:
        lines.append("  no active edges \u2014 transfer OK")
    return "\n".join(lines)


def format_archive_preview(preview: ArchivePreview) -> str:
    if preview.already_archived:
        return f"{preview.entity_type} '{preview.entity_name}' is already archived; nothing to do"
    total = preview.task_count + preview.group_count + preview.status_count
    lines = [f"would archive {preview.entity_type} '{preview.entity_name}'"]
    if total == 0:
        return lines[0]
    if preview.group_count:
        group_label = "descendant groups" if preview.entity_type == "group" else "groups"
        lines.append(f"  {group_label}: {preview.group_count}")
    if preview.status_count:
        lines.append(f"  statuses: {preview.status_count}")
    if preview.task_count:
        lines.append(f"  tasks: {preview.task_count}")
    return "\n".join(lines)


def _fmt_diff_value(value: object) -> str:
    """Format a before/after value for human-readable diff output.

    Strings render with explicit single quotes (`'foo'`), None renders as
    `(none)`, everything else renders via `str()` (ints, bools). Shared
    across `format_entity_update_preview` and `format_task_move_preview`
    for consistency.
    """
    if value is None:
        return "(none)"
    if isinstance(value, str):
        return f"'{value}'"
    return str(value)


def format_entity_update_preview(preview: EntityUpdatePreview) -> str:
    if preview.entity_type == "task":
        header = f"{format_task_num(preview.entity_id)} ({preview.label})"
    else:
        header = f"{format_group_num(preview.entity_id)} ({preview.label})"
    lines = [f"dry-run: would update {header}"]
    has_body = False
    for key in preview.after:
        before = preview.before.get(key)
        after = preview.after[key]
        lines.append(f"  {key}: {_fmt_diff_value(before)} -> {_fmt_diff_value(after)}")
        has_body = True
    for tag in preview.tags_added:
        lines.append(f"  +tag {tag}")
        has_body = True
    for tag in preview.tags_removed:
        lines.append(f"  -tag {tag}")
        has_body = True
    if not has_body:
        lines.append("  (no changes)")
    return "\n".join(lines)


def format_task_move_preview(preview: TaskMovePreview) -> str:
    lines = [f"dry-run: would move {format_task_num(preview.task_id)} ({preview.title})"]
    lines.append(
        f"  status: {_fmt_diff_value(preview.from_status)} -> {_fmt_diff_value(preview.to_status)}"
    )
    lines.append(
        f"  position: {_fmt_diff_value(preview.from_position)} -> {_fmt_diff_value(preview.to_position)}"
    )
    return "\n".join(lines)


def format_config(config: object) -> str:
    lines = ["config:"]
    for f in fields(config):  # type: ignore[arg-type]
        lines.append(f"  {f.name}: {getattr(config, f.name)!r}")
    return "\n".join(lines)


def format_edge_list(edges: tuple, *, entity: str = "task") -> str:
    """Render a list of TaskEdgeListItem or GroupEdgeListItem as a table.

    ``entity`` is 'task' or 'group' — controls the ID formatter.
    """
    if not edges:
        return f"no {entity} edges"
    fmt_id = format_task_num if entity == "task" else format_group_num
    lines = []
    for e in edges:
        src = f"{fmt_id(e.source_id)}  {e.source_title}"
        tgt = f"{fmt_id(e.target_id)}  {e.target_title}"
        lines.append(f"  {src}  --[{e.kind}]-->  {tgt}")
    return "\n".join(lines)
